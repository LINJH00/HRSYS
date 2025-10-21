"""
Direct homepage evaluation utilities.

Given a personal homepage URL, run a lightweight pipeline using
functions from author_discovery to extract a profile and return a
CandidateOverview-like payload suitable for the frontend.
"""
from __future__ import annotations

from typing import Dict, Any, List, Callable, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

import json

# Reuse the rich pipeline utilities already implemented
import backend.talent_search_module.author_discovery as ad
from backend.talent_search_module.dynamic_concurrency import get_llm_workers


def _ensure_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _to_frontend_payload_from_overview(overview: Any) -> Dict[str, Any]:
    """Convert schemas.CandidateOverview (or dict) to the simplified
    structure expected by frontend.candidate_profile.render.
    """
    try:
        data = overview.model_dump(by_alias=True) if hasattr(overview, "model_dump") else dict(overview)
    except Exception:
        data = dict(overview or {})

    reps_src = data.get("Representative Papers", []) or []
    reps: List[Dict[str, Any]] = []
    for rp in reps_src:
        if isinstance(rp, dict):
            reps.append({
                "title": rp.get("Title") or rp.get("title", ""),
                "venue": rp.get("Venue") or rp.get("venue", ""),
                "year": rp.get("Year") if rp.get("Year") is not None else rp.get("year", ""),
                "type": rp.get("Type") or rp.get("type", ""),
                "links": rp.get("Links") or rp.get("links", ""),
            })
        else:
            reps.append({
                "title": getattr(rp, "title", ""),
                "venue": getattr(rp, "venue", ""),
                "year": getattr(rp, "year", ""),
                "type": getattr(rp, "type", ""),
                "links": getattr(rp, "links", ""),
            })

    payload = {
        "name": data.get("Name", ""),
        "email": data.get("Email", ""),
        "current_role_affiliation": data.get("Current Role & Affiliation", ""),
        "current_status": data.get("Current Status", ""),
        "research_keywords": _ensure_list(data.get("Research Keywords", [])),
        "research_focus": _ensure_list(data.get("Research Focus", [])),
        "profiles": data.get("Profiles", {}),
        "publication_overview": _ensure_list(data.get("Publication Overview", [])),
        "top_tier_hits": _ensure_list(data.get("Top-tier Hits (Last 24 Months)", [])),
        "honors_grants": _ensure_list(data.get("Honors/Grants", [])),
        "service_talks": _ensure_list(data.get("Academic Service / Invited Talks", [])),
        "open_source_projects": _ensure_list(data.get("Open-source / Datasets / Projects", [])),
        "representative_papers": reps,
        "highlights": _ensure_list(data.get("Highlights", [])),
        "radar": data.get("Radar", {}),
        "total_score": data.get("Total Score", 0),
        "detailed_scores": data.get("Detailed Scores", {}),
    }
    return payload


def evaluate_homepage_to_candidate_overview(
    homepage_url: str,
    author_hint: str = "",
    api_key: str | None = None,
    on_progress: Optional[Callable[[str, float], None]] = None,
) -> Dict[str, Any]:
    """Run a homepage-only pipeline to produce a frontend-ready payload.

    - Fetch homepage (with subpages) using ad.fetch_homepage_comprehensive
    - Extract structured info via ad.HOMEPAGE_EXTRACT_PROMPT
    - Attach insights/projects/service/talks/rep papers (best-effort)
    - Build CandidateOverview using existing builder
    - Return a simplified dict for the frontend
    """
    # Helper to emit progress safely
    def _progress(event: str, pct: float) -> None:
        try:
            if on_progress is not None:
                on_progress(event, float(max(0.0, min(1.0, pct))))
        except Exception:
            # Best-effort only; never break pipeline due to UI progress issues
            pass

    # 1) Fetch homepage content (with subpages)
    _progress("fetching_homepage", 0.02)
    result = ad.fetch_homepage_comprehensive(homepage_url, author_name=author_hint or "", include_subpages=True, max_subpages=6)
    _progress("fetched_homepage", 0.08)

    # 2) Initialize base profile
    profile = ad.AuthorProfile(
        name=author_hint or "",
        aliases=[], platforms={}, ids={}, homepage_url=homepage_url,
        affiliation_current=None, emails=[], interests=[], selected_publications=[],
        confidence=0.3, notable_achievements=[], social_impact=None, career_stage=None, overall_score=0.0
    )
    
    # Protect platforms added directly from reliable HTML parsing so later steps don't overwrite
    protected_platforms = set()

    # 2.5) Add high-quality social links and emails extracted from HTML directly
    try:
        html_social_links = (result.get("social_platforms") or {})
        html_emails = (result.get("emails") or [])

        if html_social_links:
            print(f"[Direct Homepage] Adding {len(html_social_links)} social links from HTML")
        for platform, url in html_social_links.items():
            try:
                if platform not in profile.platforms and ad.validate_social_link_for_author(platform, url, author_hint or ""):
                    profile.platforms[platform] = url
                    protected_platforms.add(platform)
                    print(f"[Direct Homepage] Added {platform}: {url}")
            except Exception as e:
                print(f"[Direct Homepage] Skipped {platform} due to validation error: {e}")

        # Best-effort: include relevant emails early (optional for UI but useful downstream)
        for email in html_emails:
            try:
                if email not in profile.emails and ad.is_email_relevant_to_author(email, author_hint or ""):
                    profile.emails.append(email)
            except Exception:
                pass
    except Exception as e:
        print(f"[Direct Homepage] HTML social/email integration failed: {e}")

    # 3) Run extraction prompts in parallel
    dump = (result.get("text_content") or "")[:25000]
    llm_ext = ad.llm.get_llm("extract", temperature=0.1, api_key=api_key)

    # 定义提取任务
    def extract_main_profile():
        """提取主要profile信息"""
        try:
            ext = ad.llm.safe_structured(llm_ext, ad.HOMEPAGE_EXTRACT_PROMPT(author_hint or "", dump), ad.schemas.LLMAuthorProfileSpec)
            if ext:
                ad.process_extracted_profile_info(ext, homepage_url, author_hint or (getattr(ext, 'name', '') or ''), profile, protected_platforms, is_homepage=True)
                return True
        except Exception as e:
            print(f"[Direct Homepage] Main profile extraction failed: {e}")
        return False

    def extract_insights():
        """提取insights信息"""
        try:
            insights = ad.llm.safe_structured(llm_ext, ad.HOMEPAGE_INSIGHTS_PROMPT(author_hint or "", dump), ad.schemas.HomepageInsightsSpec)
            if insights:
                setattr(profile, '_homepage_insights', insights)
                return True
        except Exception as e:
            print(f"[Direct Homepage] Insights extraction failed: {e}")
        return False

    def extract_highlights():
        """提取highlights信息"""
        try:
            curated = ad.llm.safe_structured(llm_ext, ad.HOMEPAGE_HIGHLIGHTS_PROMPT(author_hint or "", dump), ad.schemas.HomepageHighlightsSpec)
            if curated:
                setattr(profile, '_homepage_highlights', curated)
                return True
        except Exception as e:
            print(f"[Direct Homepage] Highlights extraction failed: {e}")
        return False

    def extract_projects():
        """提取开源项目信息"""
        try:
            projects = ad.llm.safe_structured(llm_ext, ad.HOMEPAGE_PROJECTS_PROMPT(author_hint or "", dump), ad.schemas.OpenSourceProjectsSpec)
            if projects:
                setattr(profile, '_homepage_projects', projects)
                return True
        except Exception as e:
            print(f"[Direct Homepage] Projects extraction failed: {e}")
        return False

    def extract_service_talks():
        """提取学术服务和受邀报告信息"""
        try:
            svc = ad.llm.safe_structured(llm_ext, ad.HOMEPAGE_SERVICE_TALKS_PROMPT(author_hint or "", dump), ad.schemas.AcademicServiceSpec)
            if svc:
                setattr(profile, '_homepage_service_talks', svc)
                return True
        except Exception as e:
            print(f"[Direct Homepage] Service/Talks extraction failed: {e}")
        return False

    def extract_rep_papers():
        """提取代表作信息"""
        try:
            rep = ad.llm.safe_structured(llm_ext, ad.HOMEPAGE_REP_PAPERS_PROMPT(author_hint or "", dump), ad.schemas.LLMRepresentativePapersSpec)
            if rep:
                setattr(profile, '_homepage_rep_papers', rep)
                return True
        except Exception as e:
            print(f"[Direct Homepage] Rep papers extraction failed: {e}")
        return False

    # 并行执行所有提取任务
    extraction_tasks = [
        ("main_profile", extract_main_profile),
        ("insights", extract_insights),
        ("highlights", extract_highlights),
        ("projects", extract_projects),
        ("service_talks", extract_service_talks),
        ("rep_papers", extract_rep_papers)
    ]

    _progress("starting_extraction", 0.10)
    total_tasks = len(extraction_tasks)
    completed_tasks = 0
    # Dynamic concurrency: LLM extraction tasks (CPU-bound)
    extraction_workers = get_llm_workers(total_tasks)
    print(f"[Direct Homepage] Using {extraction_workers} workers for {total_tasks} extraction tasks")
    with ThreadPoolExecutor(max_workers=extraction_workers) as executor:
        # 提交所有任务
        future_to_task = {
            executor.submit(task_func): task_name 
            for task_name, task_func in extraction_tasks
        }
        
        # 收集结果
        for future in as_completed(future_to_task):
            task_name = future_to_task[future]
            try:
                success = future.result()
                if success:
                    print(f"[Direct Homepage] Successfully extracted {task_name}")
                completed_tasks += 1
                # Map progress from 10%..70% across extraction completions
                frac = completed_tasks / max(1, total_tasks)
                pct = 0.10 + 0.60 * frac
                _progress(f"extraction:{task_name}:{'ok' if success else 'skip'}", pct)
            except Exception as e:
                print(f"[Direct Homepage] {task_name} extraction failed: {e}")
                completed_tasks += 1
                frac = completed_tasks / max(1, total_tasks)
                pct = 0.10 + 0.60 * frac
                _progress(f"extraction:{task_name}:error", pct)

    # 4) Evaluate and build overview
    _progress("evaluating_profile", 0.74)
    # Top3 selection fallback from already extracted publications
    pubs = list(profile.selected_publications)
    pubs.sort(key=lambda x: (x.get('year') or 0, x.get('citations') or 0), reverse=True)
    top3 = pubs[:3]

    eval_res = ad.evaluate_profile_7d(profile, top3, api_key=api_key)
    _progress("building_overview", 0.86)
    overview = ad.build_candidate_overview(profile, eval_res, top3)

    # 5) Convert to simplified frontend payload
    _progress("finalizing_payload", 0.94)
    payload = _to_frontend_payload_from_overview(overview)
    _progress("done", 1.0)
    return payload


