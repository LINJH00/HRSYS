"""
Agent functions for Talent Search System
Handles query parsing and search execution
"""

from typing import Dict, Any, List, Tuple, Union, Optional
import json
import sys
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
import copy

# Use robust import utilities
from pathlib import Path
import sys

# Add project paths for imports
current_dir = Path(__file__).parent
backend_dir = current_dir.parent
sys.path.insert(0, str(backend_dir))
sys.path.insert(0, str(current_dir))

try:
    import schemas
    from schemas import (
        QuerySpec,
        ResearchState,
        QuerySpecDiff,
        CandidateOverview,
        EvaluationResult,
        PaperCollection,
        PaperInfo,
        PaperAuthorsResult,
        AuthorWithId,
    )
    import docker_utils
    import search
    import utils
    from backend import config
    from backend import llm
    import extraction
    from author_discovery import AuthorProfile, orchestrate_candidate_report  # type: ignore
    from semantic_paper_search import SemanticScholarClient  # type: ignore
    from dynamic_concurrency import get_optimal_workers, get_candidate_workers, get_extraction_workers, get_llm_workers  # type: ignore
except Exception as e:
    print(f"Agents ImportError: {e}")

def agent_parse_search_query(search_query: str, api_key: str = None) -> QuerySpec:
    """
    Parse a natural language search query into structured QuerySpec

    Args:
        search_query: Natural language query from user
        api_key: Optional API key for LLM calls

    Returns:
        QuerySpec: Structured search parameters
    """
    # 使用LLM解析查询（如果LLM可用）
    try:
        llm_instance = llm.get_llm("parse", temperature=0.3, api_key=api_key)

        conf_list = ", ".join(config.DEFAULT_CONFERENCES.keys())
        prompt = (
            "You are a professional talent recruitment analysis assistant responsible for parsing recruitment queries and extracting structured information.\n\n"
            "=== PARSING TASK INSTRUCTIONS ===\n"
            "Please carefully analyze the user's recruitment query and extract the following key information:\n\n"
            "1. **top_n** (int): Number of candidates needed. Look for numbers in the query like '10 candidates', '20 people', etc.\n\n"
            f"2. **years** (int[]): Years to focus on for papers. Default to {config.DEFAULT_YEARS} (last year, this year, next year) if not specified.\n\n"
            "3. **venues** (string[]): Target conferences/journals. Users will explicitly mention venues like 'ACL', 'NeurIPS', etc.\n"
            f"   Known venues include (not exhaustive): {conf_list}\n"
            "   Recognition rules:\n"
            "   - Direct conference names: ACL, EMNLP, NAACL, NeurIPS, ICLR, ICML\n"
            "   - Conference variants: NIPS→NeurIPS, The Web Conference→WWW\n"
            "   - Platforms: OpenReview (counts as a venue)\n\n"
            "4. **keywords** (string[]): Research areas and technical keywords.\n"
            "   CRITICAL EXTRACTION RULES (STRICT):\n"
            "   - Only extract keywords or phrases that appear verbatim (case-insensitive) in the user's query.\n"
            "   - Do NOT infer, expand, or add related technologies, synonyms, acronyms, abbreviations, or parent/child research fields that are NOT explicitly written by the user.\n"
            "   - Multi-word technical phrases MUST be preserved as one single keyword. Example: 'graph foundation model' must stay as one keyword.\n"
            "   - If a multi-word keyword is present, DO NOT also include its sub-components or shorter related forms unless they also appear explicitly in the query.\n"
            "   - If a term is mentioned in a negated context, DO NOT include it as a keyword.\n"
            "     Negation patterns include: 'not X', 'no X', 'without X', 'avoid X', 'exclude X', 'except X', 'rather than X'.\n"
            "   - Do NOT split a phrase into smaller parts. If no keyword exactly matches known terms, return the original phrase exactly as written by the user.\n"
            "   - Do NOT add high-level general fields like 'machine learning', 'deep learning', 'AI', 'artificial intelligence', or 'data science' unless these terms are explicitly written by the user.\n"
            "   - Do NOT normalize, paraphrase, or interpret the user's intent. Only extract exactly what they wrote.\n"
            "5. **must_be_current_student** (bool): Whether candidates must be current students. Look for:\n"
            "   - Explicit requirements: current student, currently enrolled, active student\n"
            "   - Degree phases: PhD student, Master's student, graduate student\n"
            "   - Default: true (unless explicitly stated otherwise)\n\n"
            "6. **degree_levels** (string[]): Acceptable degree levels.\n"
            "   CRITICAL EXTRACTION RULES (MUST FOLLOW EXACTLY):\n"
            "   - ONLY extract the EXACT degree terms that appear verbatim in the user's query text.\n"
            "   - Recognized degree patterns: \"PhD\", \"PhD student\", \"Doctoral\", \"Master\", \"MSc\", \"MS\",\n"
            "     \"Graduate\", \"Undergraduate\", \"Bachelor\", \"Postdoc\", \"MD\", \"MBA\".\n"
            "   - DO NOT add synonyms, variants, or related degrees that are NOT written in the query.\n"
            "     Examples:\n"
            "     * If query says \"PhD/MSc\" → return [\"PhD\", \"MSc\"] only, NOT [\"PhD\", \"MSc\", \"Master\"]\n"
            "     * If query says \"Master students\" → return [\"Master\"] only, NOT [\"Master\", \"MSc\"]\n"
            "     * If query says \"PhD candidates\" → return [\"PhD\"] only\n"
            "   - If a degree appears in a phrase (e.g. \"PhD student\"), extract the base term (\"PhD\") unless the full phrase is significant.\n"
            "   - If the query includes ANY degree term explicitly, DO NOT add default values.\n"
            "   - If the query does NOT mention any degree information at all, use this default:\n"
            "     [\"PhD\", \"MSc\", \"Master\", \"Graduate\"].\n"
            "   - When in doubt, extract FEWER degrees rather than adding unmentioned ones.\n"
            "7. **author_priority** (string[]): Author position preferences.\n"
            "   Recognition: first author, last author, corresponding author\n"
            "   Default: ['first', 'last']\n\n"
            "8. **extra_constraints** (string[]): Other constraints.\n"
            "   Recognition: geographic requirements (e.g., 'Asia', 'North America')\n"
            "   institutional requirements (e.g., 'top universities', 'Ivy League')\n"
            "   language requirements, experience requirements, etc.\n\n"
            "=== PARSING STRATEGY TIPS ===\n"
            "• Prioritize explicitly mentioned information, then make reasonable inferences\n"
            "• For technical keywords, identify specific models, methods, and research areas\n"
            "• Distinguish between different recruitment goals: interns vs researchers vs postdocs\n"
            "• Pay attention to time-sensitive information: recent publications, accepted papers, upcoming deadlines\n\n"
            "Return STRICT JSON format only, no additional text.\n\n"
            "User Query:\n"
            f"{search_query}\n"
        )

        query_spec = llm.safe_structured(llm_instance, prompt, schemas.QuerySpec)

        # 如果venues为空，设置默认值：3个核心会议 + 随机 2个 / 3个 顶会
        if query_spec.venues == []:
            import random
            # 核心会议（固定）
            need_n = query_spec.top_n
            core_venues = config.CORE_CONFERENCES.copy()
            # 从顶级会议池随机选 2个 / 3个 顶会
            random_venues = config.TOP_TIER_CONFERENCES.copy()            # 合并
            query_spec.venues = core_venues + random_venues
            print(f"[Parse Query] No venues specified, using default:")
            print(f"  Core: {core_venues}")
            print(f"  Random: {random_venues}")
            print(f"  Final: {query_spec.venues}")

        return query_spec

    except Exception as e:
        print(f"LLM解析失败，使用模拟数据: {e}")

        # 回退到模拟数据
        import random
        # 动态年份
        fallback_years = config.DEFAULT_YEARS.copy()
        core_venues = config.CORE_CONFERENCES.copy()
        random_venues = config.TOP_TIER_CONFERENCES.copy()
        fallback_venues = core_venues + random_venues
        
        print(f"[Fallback] Using default configuration:")
        print(f"  Years: {fallback_years}")
        print(f"  Venues: {fallback_venues}")
        
        return schemas.QuerySpec(
            top_n=10,
            years=fallback_years,
            venues=fallback_venues,
            keywords=["social simulation", "multi-agent systems"],
            must_be_current_student=True,
            degree_levels=["PhD", "Master"],
            author_priority=["first"],
        )


def _batch_search_until_candidates(
    queries: List[str], target_n: int, chunk_size: int = None
) -> List[Dict[str, Any]]:
    """Run search in chunks until at least target_n candidates are collected."""
    chunk_size = chunk_size or getattr(config, "SEARCH_BATCH_CHUNK_TREND", 5)
    results: List[Dict[str, Any]] = []
    for i in range(0, len(queries), chunk_size):
        batch = queries[i : i + chunk_size]
        for q in batch:
            try:
                serp = docker_utils.run_search(q)
                results.extend(serp)
            except Exception as e:
                print(f"[agent] search error for {q}: {e}")
        if len(results) >= target_n:
            break
    return results


def _plan_terms(spec: QuerySpec) -> List[str]:
    try:
        return search.build_conference_queries(
            spec, config.DEFAULT_CONFERENCES, cap=config.MAX_SEARCH_TERMS
        )
    except Exception:
        return [
            "accepted papers program schedule",
        ]


def _run_search_terms(
    terms: List[str], pages: int = 1, k_per_query: int = 10, search_engines: List[str] = None
) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    if not terms:
        return results
    if search_engines is None:
        search_engines = config.SEARXNG_ENGINES
    # Dynamic concurrency: search terms are IO-bound
    max_workers = get_optimal_workers(len(terms), 'io_bound')
    max_workers = min(max_workers, 20)  # Cap at 20 to avoid overwhelming search engines
    print(f"[_run_search_terms] Using {max_workers} workers for {len(terms)} search terms")
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        fut2term = {
            ex.submit(
                docker_utils.run_search, t, pages=pages, k_per_query=k_per_query, search_engines=search_engines
            ): t
            for t in terms
        }
        for fut in as_completed(fut2term):
            t = fut2term[fut]
            try:
                rows = fut.result() or []
                for r in rows:
                    if r.get("url", "").startswith("http"):
                        r["term"] = t
                        results.append(r)
            except Exception as e:
                print(f"[agent.search] term error: {t} -> {e}")
    # dedupe by url
    seen = set()
    uniq = []
    for r in results:
        u = r.get("url", "")
        if u and u not in seen:
            seen.add(u)
            uniq.append(r)
    return uniq


def _filter_serp_urls(
    serp: List[Dict[str, Any]], spec: QuerySpec
) -> List[Dict[str, Any]]:
    """Filter out obviously low-quality or irrelevant domains from SERP.

    Mirrors the stricter filtering used in the demo notebook: removes social media,
    code hosting, general forums/news, and low-signal blogs.
    """
    if not serp:
        return []

    # Static allow/block heuristics; keep local to avoid coupling to config unless needed
    not_allowed_domains = {
        "x.com",
        "twitter.com",
        "github.com",
        "linkedin.com",
        "facebook.com",
        "youtube.com",
        "reddit.com",
        "medium.com",
        "substack.com",
    }
    low_quality_indicators = {
        "news",
        # "blog",
        "forum",  # Note: OpenReview使用/forum/，会在下面白名单
        "discussion",
        "comment",
        "review",
    }
    
    # 白名单：这些域名即使包含低质量指标词也应保留
    whitelist_domains = {
        "openreview.net",  # OpenReview的论文页都是/forum?id=xxx格式
        "arxiv.org",
        "aclanthology.org",
        "proceedings.mlr.press",
        "proceedings.neurips.cc",
    }

    filtered: List[Dict[str, Any]] = []
    filtered_out: Dict[str, List[str]] = {
        "no_url": [],
        "blocked_domain": [],
        "low_quality": []
    }
    
    for item in serp:
        url = (item.get("url") or "").lower()
        title = (item.get("title") or "")[:80]  # 截断标题用于显示
        
        if not url:
            filtered_out["no_url"].append(f"[No URL] {title}")
            continue
        
        # 检查是否在白名单（白名单域名跳过所有过滤）
        is_whitelisted = any(wl_domain in url for wl_domain in whitelist_domains)
        
        if is_whitelisted:
            filtered.append(item)
            continue
            
        # Blocked domains
        blocked_domain = None
        for dom in not_allowed_domains:
            if dom in url:
                blocked_domain = dom
                break
        if blocked_domain:
            filtered_out["blocked_domain"].append(f"[{blocked_domain}] {title} -> {url[:60]}")
            continue
            
        # Low-quality indicators in path/host
        low_quality_match = None
        for ind in low_quality_indicators:
            if ind in url:
                low_quality_match = ind
                break
        if low_quality_match:
            filtered_out["low_quality"].append(f"[{low_quality_match}] {title} -> {url[:60]}")
            continue
            
        filtered.append(item)
    
    # Print debug information
    total_filtered = sum(len(v) for v in filtered_out.values())
    if total_filtered > 0:
        print(f"\n{'='*80}")
        print(f"[FILTER DEBUG] Filtered {total_filtered}/{len(serp)} papers, kept {len(filtered)}")
        print(f"{'='*80}")
        
        if filtered_out["no_url"]:
            print(f"\nNO URL ({len(filtered_out['no_url'])} papers):")
            for item in filtered_out["no_url"][:5]:  # 只显示前5个
                print(f"  • {item}")
            if len(filtered_out["no_url"]) > 5:
                print(f"  ... and {len(filtered_out['no_url']) - 5} more")
        
        if filtered_out["blocked_domain"]:
            print(f"\nBLOCKED DOMAIN ({len(filtered_out['blocked_domain'])} papers):")
            for item in filtered_out["blocked_domain"][:5]:
                print(f"  • {item}")
            if len(filtered_out["blocked_domain"]) > 5:
                print(f"  ... and {len(filtered_out['blocked_domain']) - 5} more")
        
        if filtered_out["low_quality"]:
            print(f"\nLOW QUALITY INDICATOR ({len(filtered_out['low_quality'])} papers):")
            for item in filtered_out["low_quality"][:5]:
                print(f"  • {item}")
            if len(filtered_out["low_quality"]) > 5:
                print(f"  ... and {len(filtered_out['low_quality']) - 5} more")
        
        print(f"\nKEPT ({len(filtered)} papers) - will proceed to LLM scoring")
        for i, item in enumerate(filtered[:3], 1):
            title = (item.get("title") or "")[:80]
            url = (item.get("url") or "")[:60]
            print(f"  {i}. {title} -> {url}")
        if len(filtered) > 3:
            print(f"  ... and {len(filtered) - 3} more")
        print(f"{'='*80}\n")
    
    return filtered


def _select_urls(
    serp: List[Dict[str, Any]], spec: QuerySpec, api_key: str = None
) -> Tuple[List[str], List[Dict[str, Any]], List[schemas.PaperWithScore]]:
    """
    Select URLs to fetch using unified LLM scoring system.
    
    Strategy:
    1. Hard filter SERP (remove obvious non-academic sites)
    2. LLM score all remaining papers (1-10 based on title + snippet)
    3. Sort by score, apply domain limits, select top N
    4. Fallback to heuristic if LLM fails
    """
    try:
        # 1) Hard filter SERP first
        serp_filtered = _filter_serp_urls(serp, spec)

        # Early exit: if nothing left
        if not serp_filtered:
            return [], [], []
        print(f"[select] serp_filtered: {len(serp_filtered)}")
        
        # 2) Use LLM-based scoring (unified approach)
        use_llm_scoring = getattr(config, "USE_LLM_PAPER_SCORING", True)
        
        if use_llm_scoring:
            try:
                # Use LLM to score papers based on title and abstract
                llm_instance = llm.get_llm("select", temperature=0.1, api_key=api_key)
                
                # Build the user query context
                query_parts = []
                if spec.keywords:
                    query_parts.append(" ".join(spec.keywords))
                if spec.venues:
                    query_parts.append(f"conferences: {', '.join(spec.venues)}")
                user_query = " ".join(query_parts) or "research papers"
                
                # Get scored papers (returns list of (url, score) tuples)
                # This function:
                # 1. Scores all papers using LLM (1-10 scale)
                # 2. Sorts by score (descending)
                # 3. Applies domain limits (max 12 per domain)
                # 4. Returns top 50 papers
                scored_urls = search.llm_pick_urls(
                    serp_filtered, 
                    user_query, 
                    llm_instance,
                    need=50,  # 增加到 50 篇论文以扩大候选池
                    max_per_domain=12  # 同时增加每域上限以获得更多样化的候选人
                )
                
                # Extract URLs and create aligned SERP list
                urls = [url for url, score in scored_urls]
                url_to_score = {url: score for url, score in scored_urls}
                url_set = set(urls)
                
                # Create aligned SERP list with scores
                serps = []
                for it in serp_filtered:
                    url = it.get("url", "")
                    if url in url_set:
                        # Add score to the SERP item for logging/debugging
                        it_with_score = it.copy()
                        it_with_score["llm_score"] = url_to_score.get(url, 0)
                        serps.append(it_with_score)
                
                # Order SERP items to match URL order
                url_to_item = {it.get("url"): it for it in serps}
                serps_ordered = [url_to_item.get(u) for u in urls if url_to_item.get(u)]
                
                # Create PaperWithScore objects for all scored papers
                scored_papers = []
                for it in serps_ordered:
                    url = it.get("url", "")
                    score = url_to_score.get(url, 0)
                    
                    # Calculate relevant_tier and completeness_score
                    relevant_tier = 1 if score >= 8 else 0
                    
                    # Calculate completeness score
                    completeness = 0.0
                    title = it.get("title", "")
                    abstract = it.get("snippet", "")
                    
                    if title and len(title) >= 20:
                        completeness += 2.0
                    if abstract:
                        if len(abstract) >= 300:
                            completeness += 3.0
                        elif len(abstract) >= 150:
                            completeness += 2.0
                        elif len(abstract) >= 50:
                            completeness += 1.0
                    
                    import re
                    if re.search(r'20\d{2}', title):
                        completeness += 0.5
                    
                    url_lower = url.lower()
                    high_quality_domains = ["arxiv.org", "openreview.net", "aclanthology.org", 
                                          "proceedings.neurips.cc", "proceedings.mlr.press"]
                    if any(domain in url_lower for domain in high_quality_domains):
                        completeness += 1.0

                    paper = schemas.PaperWithScore(
                        url=url,
                        title=title,
                        abstract=abstract,
                        score=score,
                        relevant_tier=relevant_tier,
                        completeness_score=completeness,
                        associated_candidates=[]  # Will be filled later
                    )
                    scored_papers.append(paper)
                
                # Log the results
                if config.VERBOSE:
                    print(f"[select] LLM scoring completed. Selected {len(scored_urls)} papers for crawling:")
                    for i, (url, score) in enumerate(scored_urls[:10], 1):
                        print(f"  {i}. Score {score}/10: {url}")
                
                return urls, serps_ordered, scored_papers
                
            except Exception as e:
                if config.VERBOSE:
                    print(f"[select] LLM scoring failed, falling back to heuristic: {e}")
                # Fall through to heuristic method
        
        # Fallback: heuristic method (when LLM disabled or failed)
        urls = search.heuristic_pick_urls(
            serp_filtered, spec.keywords, need=config.SELECT_K, max_per_domain=4
        )
        url_set = set(urls)
        serps = [it for it in serp_filtered if (it.get("url") or "") in url_set]
        url_to_item = {it.get("url"): it for it in serps}
        serps_ordered = [url_to_item.get(u) for u in urls if url_to_item.get(u)]
        return urls, serps_ordered, []  # No scored papers for heuristic path
    except Exception:
        return [], [], []


def _extract_single_paper_name(
    fetch_item: Tuple[str, str], 
    spec: QuerySpec,
    api_key: str = None
) -> Tuple[bool, str, str]:
    """
    Extract paper name from a single source. Returns (success, paper_name, url) tuple.
    
    Args:
        fetch_item: Tuple of (url, content_text)
        spec: Query specification for context
        api_key: API key for LLM calls
    
    Returns:
        Tuple of (success, paper_name, url)
    """
    url, content_text = fetch_item
    
    try:
        spec_item = extraction.extract_paper_name_from_sources(fetch_item, spec, api_key)
        have = getattr(spec_item, "have_paper_name", False)
        pname = getattr(spec_item, "paper_name", "")
        
        if have and pname:
            return True, pname, url
        else:
            return False, "", url
            
    except Exception as e:
        if config.VERBOSE:
            print(f"[paper-name] {url} -> {e}")
        return False, "", url


def _extract_paper_names_concurrent(
    fetched_source: Dict[str, str], 
    spec: QuerySpec, 
    paper_collection: schemas.PaperCollection,
    max_workers: int = None,
    api_key: str = None
) -> None:
    """
    Extract paper names from multiple sources concurrently using ThreadPoolExecutor.
    
    Args:
        fetched_source: Dictionary mapping URLs to their fetched text content
        spec: Query specification for context
        paper_collection: PaperCollection object to add papers to
        max_workers: Maximum number of concurrent threads (default: config.EXTRACTION_MAX_WORKERS)
        api_key: API key for LLM calls
    """
    if not fetched_source:
        return
    
    # Use config default if max_workers not specified
    if max_workers is None:
        # Dynamic concurrency: URL extraction is IO-bound
        max_workers = get_extraction_workers(len(fetched_source))
        print(f"[_extract_paper_names_concurrent] Using {max_workers} workers for {len(fetched_source)} URLs")
    
    # Use ThreadPoolExecutor for concurrent extraction
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all extraction tasks
        future_to_url = {
            executor.submit(_extract_single_paper_name, fetch_item, spec, api_key): fetch_item[0]
            for fetch_item in fetched_source.items()
        }
        
        # Collect results as they complete
        for future in as_completed(future_to_url):
            try:
                success, paper_name, url = future.result()
                if success and paper_name:
                    paper_collection.add_paper(paper_name=paper_name, url=url)
            except Exception as e:
                url = future_to_url[future]
                if config.VERBOSE:
                    print(f"[paper-name.concurrent] error for {url}: {e}")


def _fetch_single_url(serp_item: Dict[str, Any]) -> Tuple[str, str]:
    """
    Fetch text for a single URL. Returns (url, text) tuple.
    Returns (url, "") if fetch fails or text is too short.
    """
    u = serp_item.get("url", "")
    snippet = serp_item.get("snippet", "")
    
    if not u:
        return u, ""
    
    try:
        txt = search.fetch_text(u, config.FETCH_MAX_CHARS, snippet=snippet)
        if len(txt) >= config.MIN_TEXT_LENGTH:
            return u, txt
        else:
            return u, ""
    except Exception as e:
        print(f"[agent.fetch] {u} -> {e}")
        return u, ""


def _fetch_many(selected_serps: List[Dict[str, Any]], max_workers: int = None) -> Dict[str, str]:
    """
    Fetch text from multiple URLs concurrently using ThreadPoolExecutor.
    
    Args:
        selected_serps: List of SERP items containing URL and snippet info
        max_workers: Maximum number of concurrent threads (default: config.FETCH_MAX_WORKERS)
    
    Returns:
        Dictionary mapping URLs to their fetched text content
    """
    sources: Dict[str, str] = {}
    if not selected_serps:
        return sources
    
    # Use config default if max_workers not specified
    if max_workers is None:
        # Dynamic concurrency: URL fetching is IO-bound
        max_workers = get_extraction_workers(len(selected_serps))
        print(f"[_fetch_many] Using {max_workers} workers for {len(selected_serps)} URLs")
    
    # Use ThreadPoolExecutor for concurrent fetching
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all fetch tasks
        future_to_url = {
            executor.submit(_fetch_single_url, serp_item): serp_item.get("url", "")
            for serp_item in selected_serps
        }
        
        # Collect results as they complete
        for future in as_completed(future_to_url):
            try:
                url, text = future.result()
                if text:  # Only add if we got valid text
                    sources[url] = text
            except Exception as e:
                url = future_to_url[future]
                print(f"[agent.fetch.concurrent] {url} -> {e}")
    
    return sources


def _expand_author_queries(names: List[str]) -> List[str]:
    add: List[str] = []
    for n in names:
        n = (n or "").strip()
        if not n:
            continue
        add.extend(
            [
                f'"{n}" OpenReview',
                f'"{n}" Semantic Scholar',
                f'"{n}" LinkedIn',
                f'"{n}" Twitter OR X',
                f'"{n}" homepage OR personal site OR github.io OR GitHub',
            ]
        )
    # dedupe preserve order, limit
    seen = set()
    out = []
    for q in add:
        if q not in seen:
            seen.add(q)
            out.append(q)
            if len(out) >= 80:
                break
    return out


# ============================ NEW ROLE CLASSIFICATION SYSTEM ============================

def classify_role_rule_based(role_text: str) -> str:
    """Rule-based role classification as fallback
    
    Args:
        role_text: The role/position text to classify
    
    Returns:
        One of the 6 role categories or "Unknown"
    """
    if not role_text or not role_text.strip():
        return "Unknown"
    
    t = role_text.lower()
    
    # Define keyword patterns for each category
    # Priority: Check from highest to lowest priority
    
    # 1. Professor (highest priority)
    professor_patterns = [
        "assistant professor", "associate professor", "full professor",
        "asst prof", "assoc prof", "professor", "prof.",
    ]
    if any(p in t for p in professor_patterns):
        # Exclude "former professor", "ex-professor"
        if not any(ex in t for ex in ["former", "ex-", "received", "got my"]):
            return "Professor"
    
    # 2. Postdoc
    postdoc_patterns = [
        "postdoc", "post-doc", "post doc", "postdoctoral", "post-doctoral",
        "postdoctoral researcher", "postdoctoral fellow",
    ]
    if any(p in t for p in postdoc_patterns):
        if not any(ex in t for ex in ["former", "ex-", "received", "completed"]):
            return "Postdoc"
    
    # 3. Industrial Researcher
    # Keywords: company names, "industry", combined with researcher/scientist
    industrial_keywords = [
        "google", "microsoft", "meta", "facebook", "amazon", "apple", 
        "nvidia", "openai", "deepmind", "anthropic", "bytedance", "tencent",
        "baidu", "alibaba", "huawei", "intel", "ibm", "sony",
    ]
    researcher_keywords = [
        "research scientist", "researcher", "research engineer", 
        "senior researcher", "staff researcher", "research intern",
    ]
    
    has_industrial_keyword = any(k in t for k in industrial_keywords) or "industry" in t or "company" in t
    has_researcher_keyword = any(k in t for k in researcher_keywords)
    
    if has_industrial_keyword and has_researcher_keyword:
        return "IndustrialResearcher"
    
    # 4. Institution Researcher (academic institution)
    institution_keywords = [
        "university", "institute", "college", "academia", "research center",
        "research institute", "laboratory", "lab",
    ]
    has_institution_keyword = any(k in t for k in institution_keywords)
    
    if has_institution_keyword and has_researcher_keyword:
        return "InstitutionResearcher"
    
    # If only researcher keyword without clear context, check for PhD mention
    if has_researcher_keyword:
        # If mentions "phd" or "ph.d.", likely institution researcher
        if "phd" in t or "ph.d" in t or "doctor" in t:
            return "InstitutionResearcher"
        # Otherwise could be industrial
        return "IndustrialResearcher"
    
    # 5. PhD Student
    phd_patterns = [
        "phd student", "ph.d student", "ph.d. student", 
        "doctoral student", "doctoral candidate", "phd candidate",
        "graduate student", "grad student",
    ]
    if any(p in t for p in phd_patterns):
        # Exclude if mentions master explicitly
        if not any(m in t for m in ["master", "msc", "m.s.", "m.sc."]):
            return "PhDStudent"
    
    # 6. Master Student (lowest priority)
    master_patterns = [
        "master student", "master's student", "msc student", "ms student",
        "m.s. student", "m.sc. student", "m.eng student",
    ]
    if any(p in t for p in master_patterns):
        return "MasterStudent"
    
    return "Unknown"


def classify_role_llm(role_text: str, api_key: str = None) -> dict:
    """LLM-based role classification
    
    Args:
        role_text: The role/position text to classify
        api_key: Optional API key for LLM calls
    
    Returns:
        dict with keys: "role_category", "rationale_short", "confidence"
    """
    if not role_text or not role_text.strip():
        return {"role_category": "Unknown", "rationale_short": "Empty input", "confidence": 1.0}
    
    try:
        from backend.llm import get_llm
        import json
        
        llm = get_llm("role_classifier", temperature=0.1, api_key=api_key)
        
        # Create comprehensive prompt with examples
        role_categories_str = ", ".join(config.ROLE_CATEGORIES.keys())
        
        prompt = f"""You are a strict talent classifier for recruitment purposes.

**Allowed categories ONLY**: {role_categories_str}, Unknown

**TASK**: Classify the *CURRENT* role in the given text. Return JSON only.

**CRITICAL RULES**:
1. IGNORE past degrees/positions (keywords: "received", "got my PhD/degree", "graduated", "former", "ex-", "previously", "was a")
2. ONLY use present-tense descriptions OR current titles WITHOUT temporal markers
3. If multiple current roles exist, pick highest-level (priority: Professor > Postdoc > IndustrialResearcher > InstitutionResearcher > PhDStudent > MasterStudent)
4. If nothing clear matches, output "Unknown"
5. "Research Scientist" at company/industry = IndustrialResearcher
6. "Research Scientist" at university/institute = InstitutionResearcher
7. Postdoc is separate from Professor (recent PhD graduate, temporary position)

**OUTPUT JSON FORMAT**:
{{
  "role_category": "<one of the allowed categories>",
  "rationale_short": "<max 15 words explaining decision>",
  "confidence": <0.0-1.0>
}}

**EXAMPLES**:

Input: "PhD student at MIT working on computer vision"
Output: {{"role_category": "PhDStudent", "rationale_short": "Currently PhD student", "confidence": 1.0}}

Input: "I received my Ph.D. degree from Stanford. Now Research Scientist at Google"
Output: {{"role_category": "IndustrialResearcher", "rationale_short": "Current: Research Scientist at Google (company)", "confidence": 0.95}}

Input: "Master's student at CMU, interested in NLP"
Output: {{"role_category": "MasterStudent", "rationale_short": "Currently Master student", "confidence": 1.0}}

Input: "Assistant Professor of Computer Science at Berkeley"
Output: {{"role_category": "Professor", "rationale_short": "Assistant Professor position", "confidence": 1.0}}

Input: "Postdoctoral researcher at Harvard Medical School"
Output: {{"role_category": "Postdoc", "rationale_short": "Postdoctoral researcher", "confidence": 1.0}}

Input: "Research Scientist at Microsoft Research"
Output: {{"role_category": "IndustrialResearcher", "rationale_short": "Industry researcher at Microsoft", "confidence": 0.9}}

Input: "Research Scientist, Institute for AI, ETH Zurich"
Output: {{"role_category": "InstitutionResearcher", "rationale_short": "Academic institution researcher", "confidence": 0.9}}

Input: "I got my PhD in 2020. Former postdoc. Currently software engineer at Apple."
Output: {{"role_category": "Unknown", "rationale_short": "Current role is software engineer, not researcher", "confidence": 0.8}}

Input: "PhD student and part-time Research Scientist at NVIDIA"
Output: {{"role_category": "IndustrialResearcher", "rationale_short": "Dual role, higher priority: IndustrialResearcher", "confidence": 0.85}}

**NOW CLASSIFY THIS**:
Role Text: "{role_text}"

Output JSON:"""

        response = llm.invoke(prompt)
        response_text = utils.strip_thinking(response.content if hasattr(response, 'content') else str(response))
        
        # Try to parse JSON
        # Remove markdown code blocks if present
        response_text = response_text.strip()
        if response_text.startswith("```"):
            # Extract content between ```json and ``` or ``` and ```
            lines = response_text.split("\n")
            response_text = "\n".join(lines[1:-1]) if len(lines) > 2 else response_text
        
        result = json.loads(response_text)
        
        # Validate result
        role_cat = result.get("role_category", "Unknown")
        if role_cat not in config.ROLE_CATEGORIES and role_cat != "Unknown":
            if config.VERBOSE:
                print(f"[classify_role_llm] Invalid category '{role_cat}', fallback to Unknown")
            role_cat = "Unknown"
        
        return {
            "role_category": role_cat,
            "rationale_short": result.get("rationale_short", "")[:100],
            "confidence": float(result.get("confidence", 0.5))
        }
        
    except Exception as e:
        if config.VERBOSE:
            print(f"[classify_role_llm] Error: {e}, falling back to rule-based")
        # Fallback to rule-based
        role_cat = classify_role_rule_based(role_text)
        return {
            "role_category": role_cat,
            "rationale_short": "LLM failed, rule-based classification",
            "confidence": 0.5 if role_cat != "Unknown" else 0.3
        }


def classify_role(role_text: str, api_key: str = None, use_llm: bool = None) -> str:
    """Main role classification function
    
    Args:
        role_text: The role/position text to classify
        api_key: Optional API key for LLM calls
        use_llm: Override config.ENABLE_LLM_DEGREE_MATCHING if specified
    
    Returns:
        One of the 6 role categories: MasterStudent, PhDStudent, Postdoc, 
        Professor, InstitutionResearcher, IndustrialResearcher, or "Unknown"
    """
    if use_llm is None:
        use_llm = config.ENABLE_LLM_DEGREE_MATCHING
    
    if use_llm:
        result = classify_role_llm(role_text, api_key)
        role_category = result["role_category"]
        
        if config.VERBOSE:
            print(f"[classify_role] Role: '{role_text[:80]}...'")
            print(f"[classify_role] Category: {role_category}")
            print(f"[classify_role] Rationale: {result['rationale_short']}")
            print(f"[classify_role] Confidence: {result['confidence']:.2f}")
        
        # If low confidence, also try rule-based and compare
        if result["confidence"] < 0.6:
            rule_result = classify_role_rule_based(role_text)
            if config.VERBOSE:
                print(f"[classify_role] Low confidence, rule-based suggests: {rule_result}")
            # If rule-based is not Unknown and different, consider using it
            if rule_result != "Unknown" and rule_result != role_category:
                if config.VERBOSE:
                    print(f"[classify_role] Using rule-based result due to low confidence")
                return rule_result
        
        return role_category
    else:
        return classify_role_rule_based(role_text)


def _role_matches_degree(role_text: str, degree_levels: List[str]) -> bool:
    """Rule-based degree matching function that checks current role vs degree requirements
    
    This function ensures proper matching:
    - If PhD is required, current role should be PhD student, not AP/Postdoc
    - If Master is required, current role should be Master student, not PhD student
    """
    t = (role_text or "").lower()
    if not degree_levels:
        return True
    degs = [d.lower() for d in degree_levels]
    
    # Define role patterns with their academic level
    role_patterns = {
        "phd_student": ["phd student", "doctoral student", "ph.d student", "phd candidate", "doctoral candidate"],
        "master_student": ["master student", "msc student", "ms student", "m.eng student", "m eng student"],
        "undergraduate_student": ["undergraduate student", "bachelor student", "bsc student", "bs student", "undergrad"],
        "graduate_student": ["graduate student", "grad student"],
        "assistant_professor": ["assistant professor", "ap", "assistant prof", "asst prof"],
        "associate_professor": ["associate professor", "assoc prof"],
        "professor": ["professor", "prof", "full professor"],
        "postdoc": ["postdoc", "post-doctoral", "post doctoral", "postdoctoral", "post-doc"],
        "researcher": ["researcher", "research scientist", "research fellow"],
    }
    
    # Check for overqualified positions first
    overqualified_patterns = ["assistant professor", "associate professor", "professor", "postdoc", "post-doctoral", "post doctoral", "postdoctoral"]
    
    # If any overqualified position is detected, check if it matches degree requirements
    for pattern in overqualified_patterns:
        if pattern in t:
            # If PhD is required and person is AP/Professor/Postdoc, they are overqualified
            if "phd" in degs and any(over in t for over in ["assistant professor", "associate professor", "professor", "postdoc", "post-doctoral"]):
                return False
            # If Master is required and person is PhD student or higher, they are overqualified
            if "master" in degs and any(over in t for over in ["phd student", "doctoral student", "assistant professor", "associate professor", "professor", "postdoc"]):
                return False
    
    # Check for appropriate matches
    for degree in degs:
        if degree == "phd":
            # PhD required - look for PhD student or equivalent
            if any(pattern in t for pattern in role_patterns["phd_student"] + role_patterns["graduate_student"]):
                return True
        elif degree in ["master", "msc", "ms"]:
            # Master required - look for Master student, not PhD student
            if any(pattern in t for pattern in role_patterns["master_student"] + role_patterns["graduate_student"]):
                # But exclude PhD students
                if not any(phd_pattern in t for phd_pattern in role_patterns["phd_student"]):
                    return True
        elif degree in ["bachelor", "undergraduate"]:
            # Bachelor required - look for undergraduate student
            if any(pattern in t for pattern in role_patterns["undergraduate_student"]):
                return True
    
    # If no specific match found, return False (strict matching)
    return False


def role_matches_degree(role_text: str, degree_levels: List[str], api_key: str = None) -> bool:
    """NEW: Main degree matching function using role classification system
    
    This is the new implementation that:
    1. First classifies the role into one of 6 categories
    2. Then checks if that category matches the degree requirements
    
    Args:
        role_text: The role/position text to analyze
        degree_levels: List of required degree levels (e.g., ['PhD', 'Master'])
        api_key: Optional API key for LLM calls
    
    Returns:
        bool: True if the role matches the degree requirements, False otherwise
    """
    # Empty degree requirements = accept all
    if not degree_levels:
        return True
    
    # Empty role text = reject
    if not role_text or not role_text.strip():
        return False
    
    # Step 1: Classify the role
    role_category = classify_role(role_text, api_key=api_key)
    
    if config.VERBOSE:
        print(f"[role_matches_degree] Role text: '{role_text[:80]}...'")
        print(f"[role_matches_degree] Classified as: {role_category}")
        print(f"[role_matches_degree] Required degrees: {degree_levels}")
    
    # Unknown role = reject (strict matching)
    if role_category == "Unknown":
        if config.VERBOSE:
            print(f"[role_matches_degree] Result: ❌ NO MATCH (Unknown category)")
        return False
    
    # Step 2: Check if role_category matches any of the degree requirements
    # Normalize degree levels to lowercase for comparison
    degree_levels_lower = [d.lower().strip() for d in degree_levels]
    
    # Check each degree requirement
    for degree in degree_levels_lower:
        # Get acceptable role categories for this degree
        acceptable_roles = config.DEGREE_TO_ROLE_MAPPING.get(degree, [])
        
        if role_category in acceptable_roles:
            if config.VERBOSE:
                print(f"[role_matches_degree] Result: ✅ MATCH ('{degree}' accepts '{role_category}')")
            return True
    
    # No match found
    if config.VERBOSE:
        print(f"[role_matches_degree] Result: ❌ NO MATCH")
    return False


def _llm_role_matches_degree(role_text: str, degree_levels: List[str], api_key: str = None) -> bool:
    """LLM-based degree matching that checks if person has the required degree
    
    This function now accepts:
    - PhD requirement: PhD students, Postdocs, Research Scientists with PhD degree
    - Master requirement: Master students, Research Assistants with Master degree
    - Rejects: Faculty positions (AP/Professor), non-degree holders
    
    Args:
        role_text: The role/position text to analyze
        degree_levels: List of required degree levels
        api_key: Optional API key for LLM calls
    """
    if not degree_levels:
        return True
    
    if not role_text or not role_text.strip():
        return False
    
    try:
        from backend.llm import get_llm
        
        # Create LLM instance with provided API key
        llm = get_llm("degree_matcher", temperature=0.1, api_key=api_key)
        
        # More detailed prompt that considers current position vs degree requirements
        degree_list = ", ".join(degree_levels)
        prompt = f"""
Analyze whether the person's academic background matches the REQUIRED degree level.

Current Role/Position: "{role_text}"
Required Degree Level(s): {degree_list}

MATCHING RULES:

**PhD required** → Accept if ANY of these are true:
  ✅ Currently "PhD student" / "Doctoral candidate" / "PhD candidate"
  ✅ "Postdoc" / "Postdoctoral researcher" (recent PhD graduates, typically within 1-3 years)
  ✅ Text explicitly mentions "I got my Ph.D. degree" / "Ph.D. from [university]" / "PhD graduate"
  ✅ "Research Scientist" / "Researcher" / "Senior Researcher" who explicitly states having PhD degree
  ❌ "Assistant Professor" / "Associate Professor" / "Professor" (too senior for recruitment)
  ❌ No mention of PhD degree at all

**Master required** → Accept if ANY of these are true:
  ✅ Currently "Master student" / "MSc student" / "MS student"
  ✅ Text mentions "Master's degree from" or similar
  ✅ "Research Assistant" with Master's degree mentioned
  ❌ "PhD student" (overqualified for Master requirement)
  ❌ Senior positions without Master mention

**Graduate required** → Very broad:
  ✅ Any graduate student (Master, PhD)
  ✅ Postdoc
  ✅ Research positions with graduate degree mentioned

IMPORTANT:
- Focus on whether they HAVE the required degree, not just current student status
- Postdocs are recent PhDs and should MATCH for PhD requirement
- Industry researchers (Research Scientist, Senior Researcher) who explicitly mention PhD → MATCH
- Only reject if they are faculty (AP/Professor) or clearly don't have the degree

Examples:
- Required: PhD, Current: "PhD student at MIT" → MATCH
- Required: PhD, Current: "Postdoc at Harvard" → MATCH ✅ (changed)
- Required: PhD, Current: "I got my Ph.D. degree in CUHK. Research Scientist at NVIDIA" → MATCH ✅ (changed)
- Required: PhD, Current: "Senior Researcher working on generative models" (no PhD mentioned) → NO
- Required: PhD, Current: "Assistant Professor at Stanford" → NO
- Required: Master, Current: "Master student at CMU" → MATCH
- Required: Master, Current: "PhD student at Berkeley" → NO

Answer only: MATCH or NO
"""
        
        # Get LLM response
        response = llm.invoke(prompt, enable_thinking=False)
        result = response.content.strip().upper()
        
        if config.VERBOSE:
            print(f"[_llm_role_matches_degree] Role: '{role_text}', Required: {degree_list}, Result: {result}")
        
        # Simple check
        return "MATCH" in result
        
    except Exception as e:
        # Fallback to rule-based matching if LLM fails
        if config.VERBOSE:
            print(f"[_llm_role_matches_degree] LLM failed, using rule-based: {e}")
        return _role_matches_degree(role_text, degree_levels)


def _overview_matches_spec(ov: CandidateOverview, spec: QuerySpec, api_key: str = None) -> bool:
    """Check CandidateOverview against student/degree requirements in QuerySpec.

    Uses both current_role_affiliation and current_status text for robust matching.
    
    Args:
        ov: Candidate overview to check
        spec: Query specification with requirements
        api_key: Optional API key for LLM calls
    """
    candidate_name = getattr(ov, "name", "Unknown")
    
    try:
        role_text = getattr(ov, "current_role_affiliation", "") or ""
        status_text = getattr(ov, "current_status", "") or ""

        # # Student requirement
        # if spec.must_be_current_student:
        #     if not utils.looks_like_student(role_text) and not utils.looks_like_student(
        #         status_text
        #     ):
        #         return False

        # Degree level requirement
        if spec.degree_levels:
            print(f"\n{'='*80}")
            print(f"[Degree Filter DEBUG] Checking: {candidate_name}")
            print(f"{'='*80}")
            print(f"Required degrees: {spec.degree_levels}")
            print(f"\n📋 Candidate info:")
            print(f"   Role: '{role_text}'")
            print(f"   Status: '{status_text}'")
            
            # Check role match
            role_match = role_matches_degree(role_text, spec.degree_levels, api_key)
            print(f"\n🔍 Role matching:")
            print(f"   Text: '{role_text}'")
            print(f"   Result: {'✅ MATCH' if role_match else '❌ NO MATCH'}")
            
            # Check status match
            status_match = role_matches_degree(status_text, spec.degree_levels, api_key)
            print(f"\n🔍 Status matching:")
            print(f"   Text: '{status_text}'")
            print(f"   Result: {'✅ MATCH' if status_match else '❌ NO MATCH'}")
            
            final_match = role_match or status_match
            
            if not final_match:
                print(f"\n❌ FILTERED: Neither role nor status matches required degrees")
                print(f"   Candidate: {candidate_name}")
                print(f"   Required: {spec.degree_levels}")
                print(f"   Role: {role_text[:100]}")
                print(f"   Status: {status_text[:100]}")
                print(f"{'='*80}\n")
                return False
            else:
                print(f"\n✅ PASSED: Degree requirement satisfied")
                print(f"   Candidate: {candidate_name}")
                print(f"   Matched via: {'role' if role_match else 'status'}")
                print(f"{'='*80}\n")

        return True
    except Exception as e:
        print(f"\n⚠️  EXCEPTION in _overview_matches_spec for {candidate_name}: {e}")
        # If anything goes wrong, be conservative and drop it when constraints exist
        if spec.must_be_current_student or spec.degree_levels:
            print(f"   → Filtering out due to exception with constraints")
            return False
        return True


def _filter_candidates(
    cands: List[Dict[str, Any]], spec: QuerySpec, api_key: str = None
) -> List[Dict[str, Any]]:
    out = []
    for c in cands:
        role = c.get("Current Role & Affiliation", "")
        if spec.must_be_current_student:
            if not utils.looks_like_student(role) and not utils.looks_like_student(
                c.get("Evidence Notes", "")
            ):
                continue
        if spec.degree_levels:
            if not role_matches_degree(role, spec.degree_levels, api_key):
                continue
        out.append(c)
    return out


def _score_candidate(c: Dict[str, Any], spec: QuerySpec) -> float:
    score = 0.0
    role = (c.get("Current Role & Affiliation") or "").lower()
    profs = c.get("Profiles") or {}
    focus = c.get("Research Focus") or []
    # links
    score += 5.0 if profs.get("Homepage") else 0.0
    score += 3.0 if profs.get("Google Scholar") else 0.0
    score += 2.0 if profs.get("OpenReview") else 0.0
    score += 1.5 if profs.get("GitHub") else 0.0
    score += 1.0 if profs.get("LinkedIn") else 0.0
    # focus alignment
    if spec.keywords:
        text = " ".join(focus).lower()
        score += sum(1.0 for kw in spec.keywords if kw.lower() in text)
    # role
    if "phd" in role or "doctoral" in role:
        score += 3.0
    if "master" in role or "msc" in role:
        score += 2.0
    if "postdoc" in role:
        score += 1.0
    # student requirement bonus
    if spec.must_be_current_student and utils.looks_like_student(role):
        score += 1.0
    # focus richness
    score += min(len(focus), 5) * 0.5
    return score


def agent_execute_search(spec: QuerySpec, api_key: str = None, progress_callback=None) -> schemas.SearchResults:
    """Run real pipeline: plan -> search -> select -> fetch -> extract -> filter -> score -> sort.
    
    Returns SearchResults with recommended candidates, additional candidates, and reference papers.
    Searches for 1.5x the requested number of candidates and splits them into two groups.
    
    Args:
        spec: Query specification
        api_key: API key for LLM calls
        progress_callback: Optional callback function(event: str, progress: float) for progress updates
    """
    def report_progress(event: str, pct: float):
        """Helper to safely report progress"""
        if progress_callback:
            try:
                progress_callback(event, pct)
            except Exception:
                pass
    
    # Step 1: Planning search terms
    report_progress("parsing", 0.05)
    terms = _plan_terms(spec)

    # Cap concurrent student searches by spec.top_n to avoid nested concurrency overload
    try:
        topn = int(spec.top_n)
    except Exception:
        topn = 1
    chunk = config.SEARCH_BATCH_CHUNK_TREND
    pos = 0
    all_serp: List[Dict[str, Any]] = []
    sources: Dict[str, str] = {}
    selected_urls_set = set()
    selected_serp_url_set = set()
    candidates_accum: Dict[str, CandidateOverview] = {}
    search_candidate_set = set()
    
    # Search for 1.5x the requested number (rounded up)
    import math
    target_candidates = math.ceil(spec.top_n * 1.5)
    left_required_candidates = target_candidates
    
    # Track scored papers with their metadata
    all_scored_papers: Dict[str, schemas.PaperWithScore] = {}  # url -> PaperWithScore
    paper_to_candidate: Dict[str, str] = {}  # paper_url -> candidate_name

    while pos < len(terms) and len(candidates_accum) < target_candidates:
        # 早停优化：如果已超过用户需求，即使未达到1.5倍目标也可停止
        if len(candidates_accum) > spec.top_n:
            print(f"[Early Stop] Found {len(candidates_accum)} candidates (user requested {spec.top_n})")
            print(f"[Early Stop] Stopping search to save resources (target was {target_candidates})")
            break
        
        batch_terms = terms[pos : pos + chunk]
        pos += chunk
        
        # Report search progress (10% - 30%)
        search_progress = 0.10 + (pos / len(terms)) * 0.20
        report_progress("searching", search_progress)
        
        # Use function defaults: pages=1, k_per_query=6 (more conservative to avoid rate limiting)
        serp = _run_search_terms(batch_terms, search_engines=config.SEARXNG_ENGINES_PAPER_SEARCH)
        all_serp.extend(serp)

        selected_urls, selected_serp, batch_scored_papers = _select_urls(serp, spec, api_key)        
        # Save scored papers to our collection
        for paper in batch_scored_papers:
            if paper.url not in all_scored_papers:
                all_scored_papers[paper.url] = paper

        print(f"[agent.execute_search] start remove duplicate serp items")
        # Deduplicate SERP items by URL
        new_serp_items = []
        for it in selected_serp:
            u = (it.get("url") or "").strip()
            if u and u not in selected_serp_url_set:
                selected_serp_url_set.add(u)
                new_serp_items.append(it)

        print(f"[agent.execute_search] start remove duplicate serp url")
        # Track URLs as well
        for u in selected_urls:
            if u not in selected_urls_set:
                selected_urls_set.add(u)

        # Report fetching progress (30% - 40%)
        report_progress("searching", 0.35)
        
        print(f"[agent.execute_search] new_serp_items: {len(new_serp_items)}")
        fetched_source = _fetch_many(new_serp_items)
        sources.update(fetched_source)

        print(f"[agent.execute_search] fetched_source: {len(fetched_source)}")

        # Report extraction progress (40% - 45%)
        report_progress("searching", 0.42)
        
        # Extract paper names and build a deduplicated collection (align with notebook)
        paper_collection = schemas.PaperCollection()
        _extract_paper_names_concurrent(fetched_source, spec, paper_collection, api_key=api_key)
        
        print(f"[agent.execute_search] paper_collection: {len(paper_collection.get_all_papers())}")

        # Build mapping url -> paper_name using primary url per paper
        final_fetch_paper_name: Dict[str, str] = {}
        for p in paper_collection.get_all_papers():
            primary_url = p.primary_url or (p.urls[0] if p.urls else None)
            if primary_url:
                final_fetch_paper_name[primary_url] = p.paper_name

        print(f"[agent.execute_search] final_fetch_paper_name: {len(final_fetch_paper_name)}")

        # Query Semantic Scholar to get authors by paper title (batch)
        s2_authors_all: List[str] = []
        if final_fetch_paper_name:
            try:
                # Report analyzing progress (45% - 50%)
                report_progress("analyzing", 0.48)
                
                client = SemanticScholarClient()

                results = client.search_papers_with_authors_batch(
                    url_to_title=final_fetch_paper_name,
                    min_score=0.80,
                )
                
                results = [r for r in results if r.found]
                seen_names = set()
                for r in results:
                    for a in r.authors or []:
                        nm = (a.name or "").strip()
                        if nm and nm not in seen_names:
                            seen_names.add(nm)
                            s2_authors_all.append(nm)
                        # only process the first author
                        break

                if config.VERBOSE:
                    print(f"[S2] Found {len(s2_authors_all)} authors through Semantic Scholar")

                # Build candidate overviews concurrently with cap = left_required_candidates
                filter_first_author_name_set = set()
                if search_candidate_set:
                    filter_first_author_name_set = set(first_name for first_name, _, _, _ in search_candidate_set)
                
                for r in results:
                    if not (r.authors and r.paper_name):
                        continue
                    first = r.authors[0]
                    first_name = (first.name or "").strip()
                    first_id = first.author_id or None
                    if not first_name:
                        continue
                    if first_name not in filter_first_author_name_set:
                        filter_first_author_name_set.add(first_name)
                        search_candidate_set.add((first_name, first_id, r.paper_name, r.url))

                
                if len(search_candidate_set) < left_required_candidates:
                    # 候选池不够了，但先检查是否已经满足用户需求
                    if len(candidates_accum) > spec.top_n:
                        # 虽然没达到1.5倍的内部目标，但已经超过用户要求
                        print(f"[Optimization] Found {len(candidates_accum)} candidates (user requested {spec.top_n})")
                        print(f"[Optimization] Candidate pool exhausted, stopping search early to save resources")
                        break  # 直接跳出while循环，结束搜索
                    else:
                        # 还没达到用户要求，必须继续搜索
                        print(f"[agent.execute_search] search_candidate_set: {len(search_candidate_set)} < left_required_candidates -> {left_required_candidates} -> need to add more candidates")
                        continue_search = True
                else:
                    continue_search = False
                    
                if continue_search:
                    continue
                
                ######################################################################################
                # Prepare candidates item to search 
                items = list(search_candidate_set)
                
                # Dynamic concurrency: candidate processing is mixed IO/CPU
                max_workers = get_candidate_workers(
                    candidates=len(items), 
                    required=left_required_candidates
                )
                # Ensure we don't exceed item count
                max_workers = min(max_workers, len(items), 20)  # Cap at 20 for resource safety

                def _submit_one(ex, first_name, first_id, paper_title, paper_url):
                    return ex.submit(
                        orchestrate_candidate_report,
                        first_author=first_name,
                        paper_title=paper_title,
                        paper_url=paper_url,
                        aliases=[first_name],
                        author_id=first_id,
                        api_key=api_key,
                    )
                # Report candidate analysis start (50% - 80% will be dynamic)
                report_progress("analyzing", 0.50)
                
                print("="*50)
                print(f"[agent.execute_search] start submit search candidate task with: {len(items)} candidates")
                print(f"[agent.execute_search] start submit tasks with max_workers: {max_workers}")
                print(f'API key: {api_key}')
                with ThreadPoolExecutor(max_workers=max_workers) as ex:
                    # Submit initial window up to max_workers
                    idx = 0
                    futures = {}
                    while idx < len(items) and len(futures) < max_workers:
                        first_name, first_id, paper_title, paper_url = items[idx]
                        fut = _submit_one(ex, first_name, first_id, paper_title, paper_url)
                        futures[fut] = (first_name, first_id, paper_title, paper_url)
                        idx += 1

                    # Process as they complete; submit next until enough candidates gathered
                    while futures and len(candidates_accum) < target_candidates:
                        for fut in as_completed(list(futures.keys()), timeout=None):
                            first_name, first_id, paper_title, paper_url = futures.pop(fut)
                            
                            # remove this candidate from search_candidate_set
                            search_candidate_set.remove((first_name, first_id, paper_title, paper_url))
                            try:
                                profile, overview, eval_res = fut.result()
                            except Exception as e:
                                print(f"[orchestrate] {first_name} error: {e}")
                                profile, overview = None, None

                            if overview:
                                if _overview_matches_spec(overview, spec, api_key):
                                    print(f"[agent.execute_search] add candidate to candidates_accum: {first_name}")
                                    candidates_accum[first_name] = overview
                                    
                                    # Record paper-to-candidate mapping
                                    if paper_url and paper_url in all_scored_papers:
                                        if first_name not in all_scored_papers[paper_url].associated_candidates:
                                            all_scored_papers[paper_url].associated_candidates.append(first_name)
                                    
                                    # # remove this candidate from search_candidate_set
                                    # search_candidate_set.remove((first_name, first_id, paper_title))
                                    left_required_candidates -= 1
                                else:
                                    print(f"[agent.execute_search] {first_name} -> overview not matches spec filtered")
                                
                                # Report dynamic analyzing progress (50% - 75%)
                                analyzing_progress = 0.50 + (len(candidates_accum) / target_candidates) * 0.25
                                report_progress("analyzing", min(analyzing_progress, 0.75))
                                
                                print(f"[agent.execute_search] current found candidates: {len(candidates_accum)}")
                                print(f"[agent.execute_search] left required candidates: {left_required_candidates}")
                                if len(candidates_accum) >= target_candidates or left_required_candidates <= 0:
                                    break
                            else:
                                print(f"[orchestrate] {first_name} -> overview is None")

                            # 🚀 Rolling window: submit next task to keep max_workers saturated
                            if idx < len(items) and len(candidates_accum) < target_candidates:
                                next_first_name, next_first_id, next_paper_title, next_paper_url = items[idx]
                                print(f"[Rolling Window] Submitting next candidate: {next_first_name} ({idx+1}/{len(items)})")
                                nfut = _submit_one(ex, next_first_name, next_first_id, next_paper_title, next_paper_url)
                                futures[nfut] = (next_first_name, next_first_id, next_paper_title, next_paper_url)
                                idx += 1
                                print(f"[Rolling Window] Active workers: {len(futures)}, Processed: {idx}/{len(items)}")

                    # If enough gathered, best-effort cancel remaining
                    for fut in list(futures.keys()):  # Create a copy of keys to avoid RuntimeError
                        first_name, first_id, paper_title, paper_url = futures.pop(fut)
                        search_candidate_set.remove((first_name, first_id, paper_title, paper_url))
                        fut.cancel()
                print(f"[agent.execute_search] finished search candidate task with: {len(candidates_accum)} candidates")
                print("="*50)
            except Exception as e:
                if config.VERBOSE:
                    print(f"[S2] error: {e}")
        else:
            print(f"[agent.execute_search] final_fetch_paper_name is empty")
            print(f'[agent.execute_search] num candidates found: {len(candidates_accum)}')
            print(f'[agent.execute_search] left required candidates: {left_required_candidates}')
            print(f'[agent.execute_search] search term position: {pos}')
            print("="*50)
            
    # Report ranking progress (75% - 85%)
    report_progress("ranking", 0.78)
    
    # Sort candidates by total_score
    ranked = sorted(
        candidates_accum.values(),
        key=lambda x: getattr(x, "total_score", 0),
        reverse=True,
    )
    
    # Split candidates into recommended (top_n) and additional (remaining)
    recommended = ranked[: spec.top_n]
    additional = ranked[spec.top_n : target_candidates]
    
    # Report ranking completion (85% - 90%)
    report_progress("ranking", 0.88)
    
    # Sort reference papers by score (descending)
    reference_papers = sorted(
        all_scored_papers.values(),
        key=lambda x: x.score,
        reverse=True
    )
    
    # Report finalizing progress (90% - 95%)
    report_progress("finalizing", 0.92)
    
    # Build user query for metadata
    query_parts = []
    if spec.keywords:
        query_parts.append(" ".join(spec.keywords))
    if spec.venues:
        query_parts.append(f"conferences: {', '.join(spec.venues)}")
    user_query = " ".join(query_parts) or "research papers"
    
    # Create and return SearchResults
    results = schemas.SearchResults(
        recommended_candidates=recommended,
        additional_candidates=additional,
        reference_papers=reference_papers,
        total_candidates_found=len(ranked),
        search_query=user_query
    )
    
    # Report completion (100%)
    report_progress("done", 1.0)
    
    print(f"[agent.execute_search] Returning {len(recommended)} recommended + {len(additional)} additional candidates")
    print(f"[agent.execute_search] Total reference papers: {len(reference_papers)}")
    
    return results

def agent_adjust_search_parameters(
    current_spec: Dict[str, Any],
    user_input: str,
    chat_history: List[Dict[str, str]] = None,
) -> QuerySpec | None:
    """
    Use LLM to adjust search parameters based on a new user instruction and recent chat history.

    Args:
        current_spec: Existing query spec as dict
        user_input: New user adjustment instruction
        chat_history: Optional recent chat messages as a list of {"role": "user"|"assistant", "content": str}

    Returns:
        QuerySpec: Updated query spec
    """
    try:
        llm_instance = llm.get_llm("adjust", temperature=0.2)

        # Clamp history to last 10 messages
        chat_history = chat_history or []
        recent_msgs = chat_history[-10:]

        # Prepare a compact history string
        def fmt(m):
            role = m.get("role", "user")
            content = m.get("content", "").strip()
            return f"{role.upper()}: {content}"

        history_text = "\n".join(fmt(m) for m in recent_msgs)

        conf_list = ", ".join(config.DEFAULT_CONFERENCES.keys())
        prompt = (
            "SYSTEM ROLE: You update a structured search spec for a recruitment/talent search engine.\n"
            "You MUST output STRICT JSON matching the QuerySpec schema (no extra keys, no comments, no prose).\n"
            "\n"
            "OBJECTIVE\n"
            "Given (1) the current JSON spec, (2) a new user instruction, and (3) recent conversation snippets,\n"
            "produce an UPDATED QuerySpec where ONLY the fields explicitly changed by the new instruction are modified.\n"
            "All other fields must remain identical to the current spec.\n"
            "\n"
            "SCHEMA (QuerySpec):\n"
            "{\n"
            '  "top_n": int,\n'
            '  "years": int[],\n'
            '  "venues": string[],\n'
            '  "keywords": string[],\n'
            '  "must_be_current_student": bool,\n'
            '  "degree_levels": string[],\n'
            '  "author_priority": string[],\n'
            '  "extra_constraints": string[]\n'
            "}\n"
            "\n"
            "PRECEDENCE & EDIT RULES (VERY IMPORTANT)\n"
            "1) New User Instruction > recent conversation context > Current Spec.\n"
            '2) If the instruction includes ADDITIVE language (e.g., "also include X", "add Y"), then UNION with the existing list.\n'
            '3) If it includes EXCLUSIVE language (e.g., "only X", "strictly X", "limit to X"), then REPLACE the list with exactly those items.\n'
            '4) If it includes NEGATION (e.g., "exclude X", "not X", "no X"), REMOVE those items from the list if present.\n'
            "5) If a field is NOT mentioned, DO NOT change it.\n"
            '6) For numbers in "top_n", parse the most salient integer in the instruction ("~", "around", "at least" → just use the integer).\n'
            '7) Years: extract explicit 4-digit years if present; if phrases like "last 2 years" appear, map to [CURRENT_YEAR, CURRENT_YEAR-1].\n'
            "   If years are not mentioned, DO NOT change them.\n"
            '8) must_be_current_student: set True if the instruction says "current/enrolled/active students only"; set False if it says\n'
            '   "alumni allowed", "graduates ok", "postdocs ok", or similar. If not mentioned, DO NOT change it.\n'
            "\n"
            "NORMALIZATION RULES\n"
            "- Venues canonicalization (case-insensitive → canonical UPPER names). Known venues include: {conf_list}.\n"
            '  Synonyms map to canonical: {"NIPS":"NeurIPS", "The Web Conference":"WWW", "WWW":"WWW"}.\n'
            "  Deduplicate while preserving the user-specified order.\n"
            '- Degree levels canonical set: ["PhD", "MSc", "Master", "Graduate", "Undergraduate", "Bachelor", "Postdoc"].\n'
            '  Map synonyms: {"MS":"MSc", "M.S.":"MSc", "MEng":"Master", "BSc":"Bachelor", "BS":"Bachelor"}.\n'
            '- Author priority canonical set: ["first", "last", "corresponding"]. Map synonyms: {"lead":"first", "senior":"last"}.\n'
            "- Keywords: trim whitespace, lower-case, deduplicate.\n"
            "\n"
            "CONSTRAINTS\n"
            "- ABSOLUTELY DO NOT invent defaults or remove existing values unless the instruction explicitly requests it or implies it\n"
            "  via exclusive/negation phrasing. If ambiguous, prefer ADD (union) rather than replace.\n"
            "- Output MUST be valid JSON for QuerySpec, including ALL fields. No nulls. No extra commentary.\n"
            "\n"
            "INPUTS\n"
            "=== Conversation (most recent last) ===\n"
            f"{history_text}\n"
            "\n"
            "=== Current Spec (JSON) ===\n"
            f"{json.dumps(current_spec, ensure_ascii=False)}\n"
            "\n"
            "=== New User Instruction ===\n"
            f"{user_input}\n"
            "\n"
            "OUTPUT FORMAT\n"
            "Return ONLY the final JSON for QuerySpec. No markdown, no code fences, no explanations.\n"
        )

        # Use schemas.QuerySpec for structured parsing
        adjusted = llm.safe_structured(llm_instance, prompt, schemas.QuerySpec)

        # If venues empty, apply sensible default: 3个核心会议 + 随机2个顶会
        if adjusted.venues == []:
            import random
            core_venues = config.CORE_CONFERENCES.copy()
            random_venues = random.sample(config.TOP_TIER_CONFERENCES, min(2, len(config.TOP_TIER_CONFERENCES)))
            adjusted.venues = core_venues + random_venues
            print(f"[Adjust Params] No venues after adjustment, using default:")
            print(f"  Core: {core_venues}")
            print(f"  Random: {random_venues}")
            print(f"  Final: {adjusted.venues}")

        return adjusted
    except Exception as e:
        return None

def agent_classify_user_adjustment(
    current_spec: Dict[str, Any],
    user_input: str,
    chat_history: List[Dict[str, str]] | None = None,
) -> Dict[str, Any]:
    """
    Classify whether the user input is requesting a change to search parameters.

    Returns a dict: {"is_adjustment": bool, "help_instruction": str}
    If is_adjustment is False, help_instruction contains a concise instruction for the user.
    """
    try:
        llm_instance = llm.get_llm("classify", temperature=0.0)

        chat_history = chat_history or []
        recent_msgs = chat_history[-10:]

        def fmt(m):
            role = m.get("role", "user")
            content = m.get("content", "").strip()
            return f"{role.upper()}: {content}"

        history_text = "\n".join(fmt(m) for m in recent_msgs)

        prompt = (
            "SYSTEM: You classify if the user's new message is asking to ADJUST the search parameters (like top_n, years, venues, keywords, must_be_current_student, degree_levels, author_priority, extra_constraints) or not.\n"
            'Return STRICT JSON with keys: {"is_adjustment": bool, "help_instruction": string}.\n'
            "If the message is NOT an adjustment (e.g., greeting, question, generic feedback without parameters), set is_adjustment=false and provide a short, concrete help_instruction that tells the user exactly how to specify changes (one sentence).\n"
            "If it IS an adjustment, set is_adjustment=true and help_instruction=''.\n\n"
            "=== Conversation (most recent last) ===\n"
            f"{history_text}\n\n"
            "=== Current Spec (JSON) ===\n"
            f"{json.dumps(current_spec, ensure_ascii=False)}\n\n"
            "=== New User Message ===\n"
            f"{user_input}\n\n"
            "OUTPUT: JSON only."
        )

        result = llm.safe_structured(
            llm_instance, prompt, schemas.UserAdjustmentClassification
        )
        # Expecting UserAdjustmentClassification object
        if isinstance(result, schemas.UserAdjustmentClassification):
            is_adjustment = result.is_adjustment
            help_instruction = result.help_instruction if not is_adjustment else ""
            return {
                "is_adjustment": is_adjustment,
                "help_instruction": help_instruction,
            }
        # Fallback
        is_adjustment = any(
            k in user_input.lower()
            for k in [
                "add",
                "remove",
                "only",
                "exclude",
                "top",
                "year",
                "venue",
                "keyword",
                "student",
                "degree",
                "author",
            ]
        )
        return {
            "is_adjustment": is_adjustment,
            "help_instruction": (
                "Please specify what to change, e.g., 'top_n 15' or 'add keywords: computer vision'."
                if not is_adjustment
                else ""
            ),
        }
    except Exception as e:
        print(f"LLM分类失败, 返回原始参数: {e.message}")
        return {
            "is_adjustment": False,
            "help_instruction": "Tell me what to change, e.g., 'set top_n to 15' or 'add venues: ACL, EMNLP'.",
        }


def agent_validate_search_request(
    user_input: str, chat_history: List[Dict[str, str]] | None = None
) -> Dict[str, Any]:
    """
    Validate whether the user input contains sufficient information for a meaningful search.

    Returns a dict: {"is_valid_search": bool, "search_terms_found": List[str],
                     "missing_elements": List[str], "suggestion": str}
    """
    try:
        llm_instance = llm.get_llm("validate", temperature=0.0)

        chat_history = chat_history or []
        recent_msgs = chat_history[-5:]  # Only look at recent context

        def fmt(m):
            role = m.get("role", "user")
            content = m.get("content", "").strip()
            return f"{role.upper()}: {content}"

        history_text = "\n".join(fmt(m) for m in recent_msgs)

        prompt = (
            "SYSTEM: You validate if the user's message contains enough information for a meaningful talent search.\n"
            "IMPORTANT: Respond ONLY in English. All output must be in English.\n\n"
            "A valid search should contain at least one of:\n"
            "- Research areas/topics (e.g., 'machine learning', 'computer vision', 'NLP')\n"
            "- Academic terms (e.g., 'PhD students', 'researchers', 'graduate students')\n"
            "- Specific skills or expertise\n"
            "- Academic venues or conferences\n"
            "- Career stage or degree level\n\n"
            'Return STRICT JSON with keys: {"is_valid_search": bool, "search_terms_found": [str], "missing_elements": [str], "suggestion": str}.\n'
            "If valid, set is_valid_search=true and list the search terms found.\n"
            "If invalid, set is_valid_search=false, list what's missing, and provide a helpful suggestion.\n\n"
            "=== Recent Conversation ===\n"
            f"{history_text}\n\n"
            "=== User Message to Validate ===\n"
            f"{user_input}\n\n"
            "OUTPUT: JSON only."
        )

        result = llm.safe_structured(
            llm_instance, prompt, schemas.SearchValidationResult
        )

        if isinstance(result, schemas.SearchValidationResult):
            return {
                "is_valid_search": result.is_valid_search,
                "search_terms_found": result.search_terms_found,
                "missing_elements": result.missing_elements,
                "suggestion": result.suggestion,
            }

        # Fallback
        has_research_terms = any(
            term in user_input.lower()
            for term in [
                "machine learning",
                "ai",
                "artificial intelligence",
                "computer vision",
                "nlp",
                "natural language",
                "deep learning",
                "neural",
                "research",
                "phd",
                "student",
                "graduate",
                "academic",
                "paper",
                "publication",
                "conference",
                "journal",
            ]
        )

        return {
            "is_valid_search": has_research_terms,
            "search_terms_found": (
                [] if not has_research_terms else ["research terms detected"]
            ),
            "missing_elements": (
                [] if has_research_terms else ["research areas", "academic context"]
            ),
            "suggestion": (
                "Please specify what type of talent you're looking for, including research areas or academic background."
                if not has_research_terms
                else ""
            ),
        }

    except Exception as e:
        print(f"Search validation failed: {e}")
        return {
            "is_valid_search": False,
            "search_terms_found": [],
            "missing_elements": ["clear search criteria"],
            "suggestion": "Please describe what type of talent you're looking for, including research areas or academic background.",
        }


def agent_diff_search_parameters(
    current_spec: Dict[str, Any],
    user_input: str,
    chat_history: List[Dict[str, str]] | None = None,
) -> QuerySpecDiff | None:
    """
    Use LLM to produce a PARTIAL update (diff) for QuerySpec. Only include fields that change.
    """
    try:
        llm_instance = llm.get_llm("adjust_diff", temperature=0.2)

        chat_history = chat_history or []
        recent_msgs = chat_history[-10:]

        def fmt(m):
            role = m.get("role", "user")
            content = m.get("content", "").strip()
            return f"{role.upper()}: {content}"

        history_text = "\n".join(fmt(m) for m in recent_msgs)

        conf_list = ", ".join(config.DEFAULT_CONFERENCES.keys())
        prompt = (
            "SYSTEM ROLE: You update a structured search spec for a recruitment/talent search engine.\n"
            "You MUST output STRICT JSON matching the QuerySpecDiff schema (omit fields that do not change).\n\n"
            "OBJECTIVE\n"
            "Given (1) the current JSON spec, (2) a new user instruction, and (3) recent conversation snippets,\n"
            "produce a PARTIAL QuerySpecDiff with ONLY the fields changed by the new instruction.\n\n"
            "SCHEMA (QuerySpecDiff): {"
            " 'top_n': int?, 'years': int[]?, 'venues': string[]?, 'keywords': string[]?, 'must_be_current_student': bool?, 'degree_levels': string[]?, 'author_priority': string[]?, 'extra_constraints': string[]? }\n\n"
            "EDIT RULES\n"
            "- ADDITIVE language (e.g., 'also include X', 'add Y'): union with existing list and return the NEW list for that field.\n"
            "- EXCLUSIVE language (e.g., 'only X', 'strictly X', 'limit to X'): replace the list with exactly those items.\n"
            "- NEGATION (e.g., 'exclude X', 'no X'): remove those items if present and return the NEW list.\n"
            "- If a field is NOT mentioned, DO NOT include it in the output.\n"
            "- Numbers: set 'top_n' to the salient integer.\n"
            "- Years: handle explicit years or phrases like 'last 2 years' to [CURRENT_YEAR, CURRENT_YEAR-1]. If not mentioned, omit.\n\n"
            "NORMALIZATION\n"
            f"- Venues canonicalization. Known venues include: {conf_list}. Map 'NIPS'->'NeurIPS', 'The Web Conference'->'WWW'. Deduplicate, preserve user order.\n"
            "- Degree levels canonical set: ['PhD','MSc','Master','Graduate','Undergraduate','Bachelor','Postdoc'] with common synonyms.\n"
            "- Author priority canonical set: ['first','last','corresponding'] (lead->first, senior->last).\n"
            "- Keywords: lower-case, trim, deduplicate.\n\n"
            "CONSTRAINTS\n"
            "- Output MUST be valid JSON for QuerySpecDiff. No markdown, no prose.\n\n"
            "INPUTS\n"
            "=== Conversation (most recent last) ===\n"
            f"{history_text}\n\n"
            "=== Current Spec (JSON) ===\n"
            f"{json.dumps(current_spec, ensure_ascii=False)}\n\n"
            "=== New User Instruction ===\n"
            f"{user_input}\n\n"
            "OUTPUT FORMAT\n"
            "Return ONLY the final JSON for QuerySpecDiff."
        )

        diff = llm.safe_structured(llm_instance, prompt, QuerySpecDiff)
        return diff
    except Exception:
        return None


def merge_query_spec_with_diff(
    base_spec: Dict[str, Any], diff: QuerySpecDiff
) -> Dict[str, Any]:
    """Apply QuerySpecDiff fields onto base_spec and return a new dict."""
    try:
        updated = dict(base_spec)
        data = diff.dict(exclude_none=True)
        for k, v in data.items():
            updated[k] = v
        return updated
    except Exception:
        # Safe fallback: return original
        return base_spec


def node_parse_query(state: ResearchState) -> Dict[str, Any]:
    """
    Node function for parsing queries in the research workflow

    Args:
        state: Current research state

    Returns:
        Updated state with parsed query
    """
    # 这个函数用于工作流系统
    # 暂时直接返回状态
    return state


if __name__ == "__main__":
    agent_search_input = QuerySpec(
        top_n=3,
        years=[2025, 2024],
        venues=[
            "ICLR",
            "ICML",
            "NeurIPS",
            "ACL",
            "EMNLP",
            "NAACL",
            "KDD",
            "WWW",
            "AAAI",
            "IJCAI",
            "CVPR",
            "ECCV",
            "ICCV",
            "SIGIR",
        ],
        keywords=["LLM", "Large Language Model", "graph neural network"],
        must_be_current_student=True,
        degree_levels=["PhD", "MSc"],
        author_priority=["first", "last"],
        extra_constraints=[],
    )

    # For testing, you may need to provide an API key
    # agent_execute_search(agent_search_input, api_key="your_api_key_here")
    print("Test code disabled - requires API key")
def agent_generate_search_summary(results, query_spec):
    total = len(results.recommended_candidates) + len(results.additional_candidates)
    areas = []
    for c in results.recommended_candidates[:3]:
        if hasattr(c, 'research_focus'):
            areas.extend(c.research_focus[:2])
    
    areas_text = ", ".join(list(set(areas))[:5]) if areas else "relevant research areas"
    return f"Found {total} candidates specializing in {areas_text}."