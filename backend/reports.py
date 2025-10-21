from typing import List, Dict, Any, Optional, Callable
import requests
import json
from pydantic import BaseModel, Field
from concurrent.futures import ThreadPoolExecutor, as_completed

# Reuse our homepage evaluator and LLM utilities
from backend.talent_search_module.direct_homepage_evaluation import (
    evaluate_homepage_to_candidate_overview,
)
from . import llm


def humanize_list(items: List[str], max_items: int = 5) -> str:
    items = items[:max_items]
    if not items:
        return "—"
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + f" and {items[-1]}"


def get_arxiv_recent(name_query: str, max_results: int = 10) -> List[Dict[str, Any]]:
    import xml.etree.ElementTree as ET
    url = (
        "http://export.arxiv.org/api/query?search_query=au:" +
        requests.utils.quote(name_query) + "&start=0&max_results=" + str(max_results)
    )
    r = requests.get(url, timeout=30)
    if r.status_code != 200:
        return []
    feed = ET.fromstring(r.text)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    out = []
    for e in feed.findall("a:entry", ns):
        title = e.findtext("a:title", default="", namespaces=ns).strip().replace("\n", " ")
        link = ""
        for l in e.findall("a:link", ns):
            if l.attrib.get("type") == "text/html":
                link = l.attrib.get("href", "")
        updated = e.findtext("a:updated", default="", namespaces=ns)
        out.append({"title": title, "url": link, "updated": updated})
    return out


# ===================== Pydantic output specs for aggregation =====================

class _PeopleSnapshot(BaseModel):
    size: int = Field(..., description="Team size")
    institutions_degrees: List[str] = Field(default_factory=list)
    research_topic_clusters: List[str] = Field(default_factory=list)
    collaborators_institutions: List[str] = Field(default_factory=list)


class _ExecutiveSummary(BaseModel):
    key_milestones: List[str] = Field(default_factory=list)
    core_research_lines: List[str] = Field(default_factory=list)
    opportunities_needs: List[str] = Field(default_factory=list)


class _PublicationsSummary(BaseModel):
    volume_structure: List[str] = Field(default_factory=list)
    top_tier_stats: List[str] = Field(default_factory=list)
    representative_works: List[str] = Field(default_factory=list)


class _ServiceImpactSummary(BaseModel):
    reviewing_pc: List[str] = Field(default_factory=list)
    invited_talks: List[str] = Field(default_factory=list)
    media_coverage: List[str] = Field(default_factory=list)
    open_source: List[str] = Field(default_factory=list)


class _TopicMapItem(BaseModel):
    topic: str
    members: List[str] = Field(default_factory=list)
    representative_works: List[str] = Field(default_factory=list)


class _OverallReport(BaseModel):
    people_snapshot: _PeopleSnapshot
    executive_summary: _ExecutiveSummary
    publications: _PublicationsSummary
    service_impact: _ServiceImpactSummary
    research_map: List[_TopicMapItem] = Field(default_factory=list)


class _IndividualHeader(BaseModel):
    title: str = ""
    email: str = ""
    homepage: str = ""
    scholar: str = ""


class _IndividualPaper(BaseModel):
    title: str
    venue: str = ""
    year: Optional[int] = None
    links: str = ""


class _IndividualReport(BaseModel):
    name: str
    header: _IndividualHeader
    keywords: List[str] = Field(default_factory=list)
    highlights: List[str] = Field(default_factory=list)
    publication_overview: str = ""
    honors_grants: List[str] = Field(default_factory=list)
    service_talks: List[str] = Field(default_factory=list)
    open_source_projects: List[str] = Field(default_factory=list)
    representative_papers: List[_IndividualPaper] = Field(default_factory=list)
    radar: Dict[str, int] = Field(default_factory=dict)
    total_score: int = 0
    detailed_scores: Dict[str, str] = Field(default_factory=dict)


def _first_scholar_link(profiles: Dict[str, str]) -> str:
    try:
        for k, v in (profiles or {}).items():
            key = (k or "").lower()
            if "scholar" in key:
                return v
    except Exception:
        pass
    return ""


def _member_payload_to_individual(name: str, homepage: str, payload: Dict[str, Any]) -> _IndividualReport:
    profiles = payload.get("profiles", {})
    reps = []
    for p in payload.get("representative_papers", []) or []:
        try:
            reps.append(_IndividualPaper(
                title=p.get("title", ""),
                venue=p.get("venue", ""),
                year=p.get("year"),
                links=p.get("links", ""),
            ))
        except Exception:
            continue

    pub_ov = payload.get("publication_overview") or []
    if isinstance(pub_ov, list):
        pub_summary = f"Total listed: {len(pub_ov)}; " + humanize_list(pub_ov, max_items=3)
    else:
        pub_summary = str(pub_ov)

    header = _IndividualHeader(
        title=payload.get("current_role_affiliation", ""),
        email=payload.get("email", ""),
        homepage=homepage,
        scholar=_first_scholar_link(profiles),
    )

    return _IndividualReport(
        name=name,
        header=header,
        keywords=(payload.get("research_keywords") or []) + (payload.get("research_focus") or []),
        highlights=payload.get("highlights", []) or [],
        publication_overview=pub_summary,
        honors_grants=payload.get("honors_grants", []) or [],
        service_talks=payload.get("service_talks", []) or [],
        open_source_projects=payload.get("open_source_projects", []) or [],
        representative_papers=reps,
        radar=payload.get("radar", {}) or {},
        total_score=int(payload.get("total_score", 0) or 0),
        detailed_scores=payload.get("detailed_scores", {}) or {},
    )


class _ResearchMapList(BaseModel):
    items: List[_TopicMapItem] = Field(default_factory=list)


def _aggregate_group_report(individuals: List[_IndividualReport], api_key: Optional[str]) -> _OverallReport:
    """Use multiple LLM prompts in parallel to synthesize each section."""
    llm_inst = llm.get_llm("group_report", temperature=0.2, api_key=api_key)

    # Compact member context for the model
    compact = []
    for m in individuals:
        compact.append({
            "name": m.name,
            "title": m.header.title,
            "homepage": m.header.homepage,
            "keywords": m.keywords[:16],
            "highlights": m.highlights[:10],
            "reps": [{"title": p.title, "venue": p.venue, "year": p.year} for p in m.representative_papers[:5]],
            "service": m.service_talks[:10],
            "honors": m.honors_grants[:10],
        })

    team_json = json.dumps(compact, ensure_ascii=False)
    size = len(individuals)

    def synth_people_snapshot():
        prompt = (
            "You are summarizing a research team. Return STRICT JSON as {size:int, institutions_degrees:str[], research_topic_clusters:str[], collaborators_institutions:str[]}. "
            "Rules: clusters must be 3-5 items, each <= 8 words; include only institution/degree bullets that can be grounded in member data; collaborators/institutions should be short names.\n\n"
            f"TEAM DATA:\n{team_json}"
        )
        res = llm.safe_structured(llm_inst, prompt, _PeopleSnapshot)
        try:
            res.size = size
        except Exception:
            pass
        return res

    def synth_exec_summary():
        prompt = (
            "Produce an executive summary JSON {key_milestones:str[], core_research_lines:str[], opportunities_needs:str[]} "
            "for the last 24 months based on team data. Milestones should cite venue/year where possible; 6-10 bullets max across items; concise.\n\n"
            f"TEAM DATA:\n{team_json}"
        )
        return llm.safe_structured(llm_inst, prompt, _ExecutiveSummary)

    def synth_publications():
        prompt = (
            "Summarize publications as JSON {volume_structure:str[], top_tier_stats:str[], representative_works:str[]} "
            "with concise bullets using venue acronyms and years.\n\n"
            f"TEAM DATA:\n{team_json}"
        )
        return llm.safe_structured(llm_inst, prompt, _PublicationsSummary)

    def synth_service_impact():
        prompt = (
            "Summarize service/impact as JSON {reviewing_pc:str[], invited_talks:str[], media_coverage:str[], open_source:str[]} "
            "keeping each list 3-8 bullets.\n\n"
            f"TEAM DATA:\n{team_json}"
        )
        return llm.safe_structured(llm_inst, prompt, _ServiceImpactSummary)

    def synth_research_map():
        prompt = (
            "Build a within-group topic map. Return STRICT JSON as {items:[{topic:string, members:string[], representative_works:str[]}]} "
            "Constraints: 3-5 topics, topic names <= 8 words, members are names from data.\n\n"
            f"TEAM DATA:\n{team_json}"
        )
        res = llm.safe_structured(llm_inst, prompt, _ResearchMapList)
        return res.items

    with ThreadPoolExecutor(max_workers=5) as ex:
        fut_to_key = {
            ex.submit(synth_people_snapshot): "ps",
            ex.submit(synth_exec_summary): "es",
            ex.submit(synth_publications): "pub",
            ex.submit(synth_service_impact): "svc",
            ex.submit(synth_research_map): "map",
        }
        ps = None; es = None; pub = None; svc = None; rmap = None
        for fut in as_completed(fut_to_key):
            key = fut_to_key[fut]
            try:
                val = fut.result()
                if key == "ps":
                    ps = val
                elif key == "es":
                    es = val
                elif key == "pub":
                    pub = val
                elif key == "svc":
                    svc = val
                elif key == "map":
                    rmap = val
            except Exception:
                pass

    # Fallbacks to avoid None
    ps = ps or _PeopleSnapshot(size=size, institutions_degrees=[], research_topic_clusters=[], collaborators_institutions=[])
    es = es or _ExecutiveSummary(key_milestones=[], core_research_lines=[], opportunities_needs=[])
    pub = pub or _PublicationsSummary(volume_structure=[], top_tier_stats=[], representative_works=[])
    svc = svc or _ServiceImpactSummary(reviewing_pc=[], invited_talks=[], media_coverage=[], open_source=[])
    rmap = rmap or []

    return _OverallReport(
        people_snapshot=ps,
        executive_summary=es,
        publications=pub,
        service_impact=svc,
        research_map=rmap,
    )


def generate_group_achievement_report(
    members: List[Dict[str, str]],
    api_key: Optional[str] = None,
    on_progress: Optional[Callable[[str, float], None]] = None,
) -> Dict[str, Any]:
    """
    Build a detailed group achievement report by:
      1) Running homepage evaluation for each member (parallel)
      2) Converting to detailed individual reports for UI
      3) Aggregating into an overall report via LLM

    members: list of {name, homepage, affiliation?}
    Returns dict with keys: overall_report, individual_reports
    """

    def _emit(evt: str, pct: float) -> None:
        try:
            if on_progress:
                on_progress(evt, float(max(0.0, min(1.0, pct))))
        except Exception:
            pass

    total = max(1, len(members))
    _emit("group:start", 0.01)

    # 1) Evaluate members in parallel
    individuals: List[_IndividualReport] = []
    completed = 0
    with ThreadPoolExecutor(max_workers=min(6, total)) as ex:
        futures = {}
        for m in members:
            name = m.get("name", "")
            homepage = m.get("homepage", "")

            def _run(name=name, homepage=homepage):
                # Nest progress for this member lightly; we only surface coarse-grained
                try:
                    _emit(f"member:{name}:start", completed / total * 0.6)
                    payload = evaluate_homepage_to_candidate_overview(
                        homepage_url=homepage,
                        author_hint=name,
                        api_key=api_key,
                        on_progress=None,
                    )
                    return name, homepage, payload, None
                except Exception as e:
                    return name, homepage, None, e

            futures[ex.submit(_run)] = (name, homepage)

        for fut in as_completed(futures):
            name, homepage = futures[fut]
            try:
                _name, _homepage, payload, err = fut.result()
                if err is None and isinstance(payload, dict):
                    ind = _member_payload_to_individual(_name, _homepage, payload)
                    individuals.append(ind)
            finally:
                completed += 1
                _emit("group:progress", 0.6 * (completed / total))

    # 2) Aggregate
    _emit("group:aggregate", 0.7)
    overall = _aggregate_group_report(individuals, api_key=api_key)
    _emit("group:done", 1.0)

    # Return structured data as plain dicts compatible with frontend renderer
    return {
        "overall_report": overall.model_dump(),
        "individual_reports": [i.model_dump() for i in individuals],
    }


# Backwards-compat single-person text report (kept for legacy uses)
def build_achievement_report(person_name: str) -> str:
    lines: List[str] = []
    for p in get_arxiv_recent(person_name, max_results=5):
        lines.append(f"arXiv: {p['title']}  ({p['updated'][:10]})  {p['url']}")
    if not lines:
        return f"No signals available for {person_name}."
    return "\n".join(lines)