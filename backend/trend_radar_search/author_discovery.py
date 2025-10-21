"""
Author Discovery Module for Talent Search System
Implements comprehensive author profile discovery and integration
"""
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from typing import List, Dict, Any, Tuple, Optional
import re
import time
from dataclasses import dataclass, field
from urllib.parse import urlparse, urljoin
import json
import requests
from bs4 import BeautifulSoup

from backend import config
# import utils
import search
from backend import llm
import schemas
from utils import normalize_url, domain_of, clean_text, safe_sleep
from search import searxng_search, fetch_text, extract_title_unified, extract_main_text

import docker_utils
from dynamic_concurrency import get_optimal_workers, get_llm_workers, get_extraction_workers

# ============================ DATA CLASSES ============================

@dataclass
class AuthorProfile:
    """Complete author profile with all discovered information"""
    name: str
    aliases: List[str]
    platforms: Dict[str, str]        # {'openreview': url, 'semanticscholar': url, ...}
    ids: Dict[str, str]              # {'orcid': '0000-0000-0000-0000', 'semanticscholar': '2316...', ...}
    homepage_url: Optional[str]
    affiliation_current: Optional[str]
    emails: List[str]
    interests: List[str]
    selected_publications: List[Dict[str, Any]]  # [{'title':..., 'year':..., 'venue':..., 'url':...}]
    confidence: float                 # 0~1
    
    # 新增字段
    notable_achievements: List[str] = field(default_factory=list)  # Awards, honors, recognitions
    social_impact: Optional[str] = None      # H-index, citations, influence metrics
    career_stage: Optional[str] = None       # student/postdoc/assistant_prof/etc
    overall_score: float = 0.0               # 综合评分 0~100

@dataclass
class ProfileCandidate:
    """Candidate profile URL with scoring and LLM decision"""
    url: str
    title: str
    snippet: str
    score: float
    should_fetch: Optional[bool] = None
    reason: Optional[str] = None
    trusted_source: bool = False  # True if from OpenReview profile (skip validation)

# ============================ PLATFORM CONFIGURATION ============================

# Platform priority (high → low) - OpenReview now has highest priority
TRUST_RANK = ['openreview', 'orcid', 'scholar', 'semanticscholar', 'dblp', 'university', 'homepage', 'github', 'huggingface', 'researchgate', 'twitter', 'linkedin']

# Whitelist domains with high trust scores
WHITELIST_HOSTS = {
    'orcid.org': 0.9,
    'openreview.net': 0.9,
    'scholar.google.com': 0.9,
    'semanticscholar.org': 0.9,
    'dblp.org': 0.9,
}

# Secondary domains with medium trust
SECONDARY_HOSTS = {
    'github.io': 1, 'github.com': 0.8, 'huggingface.co': 0.8,
}

# Domains to block/avoid
PERSONAL_DOMAINS = {
    'linkedin.com', 'x.com', 'twitter.com', 'facebook.com', 'medium.com', 'reddit.com', 'youtube.com'
}

# ============================ SEARCH QUERY TEMPLATES ============================

# 优化的平台特定查询模板 - 只保留最高质量的查询
# 注意：现在OpenReview是强制要求，不需要在这里搜索
# Homepage搜索只在OpenReview没有homepage时才执行，使用homepage_search_strategies
PLATFORM_QUERIES = [
    # 个人主页 - 最高优先级（只保留最有效的）
    '{q} site:github.io',
    '{q} personal website OR homepage',
    
    # 学术平台 - 高质量来源（用于补充信息）
    '{q} site:scholar.google.com/citations',
    '{q} site:orcid.org',
    '{q} site:semanticscholar.org/author',
    '{q} site:dblp.org',
]

# 优化的Notable查询 - 只保留高价值的成就查询
NOTABLE_QUERIES = [
    '{q} "best paper" OR "outstanding paper" OR "paper award"',
    '{q} "fellow" OR "IEEE fellow" OR "ACM fellow"',
    '{q} "rising star" OR "young researcher award"',
    '{q} "keynote" OR "invited speaker"',
    '{q} "distinguished" OR "excellence award"'
]

# ============================ REGEX PATTERNS FOR ID EXTRACTION ============================

ID_PATTERNS = {
    'orcid': re.compile(r'orcid\.org/(\d{4}-\d{4}-\d{4}-\d{4})'),
    'openreview': re.compile(r'openreview\.net/profile\?id=([A-Za-z0-9_\-\.%]+)'),
    'scholar': re.compile(r'scholar\.google\.com/citations\?user=([A-Za-z0-9_\-]+)'),
    'semanticscholar': re.compile(r'semanticscholar\.org/author/([^/\s]+)'),
    'dblp1': re.compile(r'dblp\.org/pid/([0-9a-z/]+)'),
    'dblp2': re.compile(r'dblp\.org/pers/([0-9a-z/]+)'),
    'twitter': re.compile(r'(?:x\.com|twitter\.com)/([A-Za-z0-9_]{1,15})(?:/|$)'),
    'github': re.compile(r'github\.com/([A-Za-z0-9\-]+)(?:/|$)'),
}

# ============================ LLM PROMPTS ============================

# 第一阶段：判断是否包含作者信息
PROMPT_HAS_AUTHOR_INFO = lambda author_name, title, url, snippet: f"""
You are a strict but practical triager. Decide if this page is ABOUT the specific researcher (i.e., a profile/homepage/bio with substantive info), not merely a mention.

TARGET AUTHOR: {author_name}

CANDIDATE PAGE:
Title: {title[:180]}
URL: {url}
Snippet: {snippet[:400]}


---------------------------
DECISION PRINCIPLES
1) Favor structured signals over snippet length.
   - A brief snippet MUST NOT lower the decision if URL/title strongly indicate a personal or profile page.

2) Positive (ABOUT) patterns (any strong signal may suffice):
   A. Personal homepage domains/paths:
      - *.github.io, sites.google.com/..., university personal pages (e.g., /~name, /people/name, /~netid, /~firstname.lastname)
      - lab/faculty/staff/person pages under .edu/.ac.* (.edu, .ac.uk, .edu.au, .ac.nz, etc.)
   B. Academic profile platforms (individual profile pages), e.g.:
      - Google Scholar profile (scholar.google.com/citations?user=...)
      - ORCID (orcid.org/0000-...), DBLP (dblp.org/pid/... or /pers/hd/.../Name), Semantic Scholar author pages (/author/...), AMiner, ResearchGate profile pages
   C. Title strongly matches the person:
      - Title equals or starts with the exact name "{author_name}" or "{author_name} – Home", "Homepage", "Publications", "CV", "Bio"
   D. Page indicates role/affiliation keywords near the name:
      - "PhD student", "Professor", "Assistant Professor", "Postdoc", "Researcher", "CS PhD", "Stanford University", "Department of Computer Science", "Bio", "About", "Publications", "Contact"

3) Negative (NOT ABOUT) patterns:
   - Generic conference/journal/cfp pages, lab news posts that only mention the name
   - Search result aggregators without landing on a specific profile (e.g., generic Google Scholar search query pages, not a citations profile)
   - Single paper detail pages listing authors but no author bio/profile context
   - Social media posts or news articles that merely mention the name without profile info

4) Heuristic scoring (use this to guide decision & confidence):
   +2 if domain/path is clearly a personal or faculty/staff page (see 2A)
   +2 if it's a recognized academic profile page (see 2B)
   +1 if title equals or begins with "{author_name}"
   +1 if snippet includes role/affiliation/profile keywords (see 2D)
   -1 if page looks like a generic venue/cfp/news item
   -2 if it is clearly just a paper page with no bio/profile

Decision rule:
- If total score ≥ 2 → has_author_info = true (confidence:
    0.80–0.95 if ≥ 3; 0.60–0.80 if exactly 2)
- If total score ≤ 1 → has_author_info = false (confidence 0.40–0.70, explain why)

5) Important:
   - DO NOT penalize for a short snippet when URL/title strongly suggest a personal/profile page (e.g., *.github.io with the exact name).
   - When marking true based on strong URL/title signals but limited text, give a moderate-to-high confidence and mention the signal (e.g., "github.io personal homepage with exact-name title").

Return concise reasons citing the strongest signals (domain/path, title match, platform type).

Output JSON only:
{{"has_author_info": true/false, "confidence": 0.0-1.0, "reason": "<brief explanation>"}}
"""


# 新增：Profile身份验证prompt
PROMPT_VERIFY_PROFILE_IDENTITY = lambda author_name, platform, url, content_preview: f"""
Verify if this {platform} profile belongs to the target researcher.

TARGET AUTHOR: {author_name}

PROFILE TO VERIFY:
Platform: {platform}
URL: {url}
Content Preview: {content_preview[:1000]}

Is this profile definitely for the target author {author_name}?

VERIFICATION CRITERIA:
✓ Name match (exact or reasonable variations)
✓ Research area consistency 
✓ Institution/affiliation match
✓ Publication overlap
✓ Profile completeness and authenticity

REJECT IF:
✗ Different person with similar name
✗ Generic/incomplete profile
✗ Conflicting information (different field, institution)
✗ Suspicious/fake profile indicators

Return JSON: {{"is_target_author": true/false, "confidence": 0.0-1.0, "reason": "<specific reason>"}}
"""

# Homepage身份预验证prompt
PROMPT_HOMEPAGE_IDENTITY_CHECK = lambda author_name, paper_title, url, preview_content: f"""
PERSONAL HOMEPAGE IDENTITY VERIFICATION (Strict Evidence-Weighted)

GOAL
Decide if this is a PERSONAL HOMEPAGE belonging to the target author, NOT an institutional/workshop/conference page.

INPUTS
- TARGET AUTHOR: {author_name}
- KNOWN PAPER (for topical/author-name cues only, explicit mention is NOT required): {paper_title}
- HOMEPAGE URL: {url}
- HOMEPAGE PREVIEW (title/body/snippet; may be truncated): {preview_content[:1200]}

CRITICAL DISTINCTION
This must be a PERSONAL HOMEPAGE, not:
- Workshop/conference websites (e.g., "MICCAI Workshop", "Conference 2024")
- Institutional pages (e.g., department pages, lab pages, course pages)
- Event pages (e.g., symposium, workshop, meeting pages)
- Generic academic pages without personal content
- Github page for project or code or Github account page or Github Repo page

EVIDENCE SIGNALS (assign points; sum them to make a decision)

REQUIRED PRECONDITIONS (ALL must be satisfied):
  [R1] Exact name match: The target author's exact name appears prominently (title, header, about section): +3
  [R2] Personal homepage indicators: Page shows personal content (CV, bio, publications, research interests, personal info): +2
  [R3] NOT institutional/event page: Page is clearly personal, not a workshop/conference/institutional page: +2

STRONG SIGNALS (high confidence indicators):
  [S1] Personal identifiers: Personal email, GitHub profile, Google Scholar, DBLP, ORCID links: +2
  [S2] Research area alignment: Research interests match the paper's domain: +1
  [S3] Credible affiliation: Institution/affiliation present and plausible for the author: +1
  [S4] Personal timeline: CV, education, career history, personal achievements: +1
  [S5] Personal publications: List of personal publications, not just conference info: +1

WEAK SIGNALS (supporting evidence):
  [W1] URL structure: URL contains author name or personal identifier: +0.5
  [W2] Personal photos: Headshots or personal images: +0.5
  [W3] Contact info: Personal contact details: +0.5

NEGATIVE / CONFLICTING SIGNALS (strong rejection indicators):
  [N1] Workshop/Conference page: Page is clearly a workshop, conference, or event page: -5
  [N2] Institutional page: Page belongs to institution/department/lab, not individual: -4
  [N3] Event announcement: Page announces events, calls for papers, programs: -4
  [N4] Multiple authors: Page lists multiple people, not focused on single author: -3
  [N5] Generic template: No personal content, just generic academic template: -2
  [N6] Different person: Evidence of different person with same name: -3

DECISION RULE
1. REQUIRED PRECONDITIONS: [R1], [R2], and [R3] must ALL be satisfied
2. Compute TOTAL = sum(all positive signals - negative signals)
3. If any required precondition is missing, return false
4. If TOTAL ≥ 4.0 and no major negative signals ([N1], [N2], [N3]), return true
5. If any major negative signal exists, return false regardless of score
6. If TOTAL < 4.0, return false

OUTPUT (JSON):
{{
  "is_target_author_homepage": true/false,
  "confidence": 0.0-1.0,
  "author_name_found": "<exact name string as it appears on the page>",
  "research_area_match": true/false,
  "reason": "<detailed evidence audit: list which signals were hit/missed and decision rationale>"
}}

EXAMPLES:
- PERSONAL HOMEPAGE: "John Smith - Computer Science PhD Student at MIT. Research interests: Machine Learning, Computer Vision. Publications: [list]. Contact: john@mit.edu" → TRUE
- WORKSHOP PAGE: "MICCAI Workshop 2024 - Call for Papers. Important Dates. Program Committee: John Smith, Jane Doe..." → FALSE
- INSTITUTIONAL PAGE: "MIT Computer Science Department. Faculty: Prof. Smith, Prof. Doe. Courses offered..." → FALSE

Be strict and conservative. When in doubt, reject.
"""

# 第二阶段：判断是否值得抓取
PROMPT_PROFILE_RELEVANCE = lambda author_name, paper_title, title, url, snippet: f"""
This page contains author information. Decide if it's worth fetching for profile building.

AUTHOR: {author_name}
PAPER: {paper_title}

CANDIDATE:
Title: {title[:180]}
URL: {url}
SNIPPET: {snippet[:400]}

Rate the VALUE for building author profile (0.0-1.0):

HIGH VALUE (0.8-1.0):
- Official academic profiles (ORCID, OpenReview, Semantic Scholar)
- University faculty pages
- Personal research websites
- Detailed CV/bio pages

MEDIUM VALUE (0.5-0.7):
- GitHub profiles with research projects
- Conference speaker bios
- Research group member pages
- Professional platform profiles

LOW VALUE (0.1-0.4):
- Brief mentions in news
- Social media profiles
- Generic directory listings

Return JSON: {{"should_fetch": true/false, "value_score": 0.0-1.0, "reason": "<short>"}}
"""

# 个人网站专用的"零幻觉"提取 prompt（严格版）
HOMEPAGE_EXTRACT_PROMPT = lambda author_name, dump: f"""
You are in ZERO-HALLUCINATION mode. Extract ONLY information that appears **verbatim in TEXT CONTENT**. 
If something is not explicitly present, return an empty string "" or empty list [].

TARGET AUTHOR: {author_name}
CONTENT TYPE: Personal Website / Homepage

TEXT CONTENT (source of truth — do not infer beyond this):
{dump}
==== END ====

OUTPUT REQUIREMENTS
- Return **valid JSON only** (no prose, no comments).
- Use exactly these keys (and no extras):
{{
  "name": "<full name as written or ''>",
  "aliases": ["..."],                      // author's own variants only; else []
  "affiliation_current": "<FULL role + institution, e.g. 'PhD student at MIT' or 'Associate Professor at CMU' or ''>",
  "emails": ["..."],                       // professional emails only; else []
  "interests": ["..."],                    // concrete research areas; else []
  "selected_publications": [               // up to 3; else []
    {{"title":"...", "year":2024, "venue":"...", "url":"..."}}
  ],
  "notable_achievements": ["..."],         // awards/fellowships/best papers; else []
  "social_impact": "<e.g., 'h-index: 18, citations: 1350' or ''>",
  "career_stage": "<student/postdoc/assistant_prof/associate_prof/full_prof/industry or ''>",
  "social_links": {{
    "scholar": "",                         // MUST be a URL string present verbatim in TEXT CONTENT, else ""
    "github": "",
    "linkedin": "",
    "twitter": "",
    "orcid": ""
  }}
}}

CRITICAL NON-NEGOTIABLE RULES
1) **VERBATIM-URL RULE for social_links**: A field may be non-empty **only if the exact URL substring exists in TEXT CONTENT**.
   - Acceptable patterns (must appear literally in TEXT CONTENT):
     - scholar: "scholar.google.com/citations?user="…
     - github:  "github.com/<username>"…
     - linkedin:"linkedin.com/in/<handle>"…
     - twitter: "twitter.com/<handle>" or "x.com/<handle>"
     - orcid:   "orcid.org/0000-0000-0000-0000" (4-4-4-4 digits)
   - **Do NOT** construct URLs from names, emails, or guesses. **If absent, return ""**.

2) **DO NOT NORMALIZE OR REWRITE URLs**. Copy the substring exactly as it appears in TEXT CONTENT (including http/https if shown). If a platform is mentioned without a visible URL, leave the field as "".

3) **Emails**: copy only emails that appear verbatim in TEXT CONTENT. Exclude generic addresses (info@, admin@, support@, etc.). If none, return [].

4) **Affiliation**: MUST include BOTH the role/position AND the institution name (e.g., "PhD student at MIT", "Postdoc at Stanford University", "Associate Professor at CMU"). Never provide just the institution name alone. Extract from explicit statements like "I am a PhD student at..." or "Assistant Professor at...".

5) **Aliases**: include only alternative names that refer to THIS author and are shown in TEXT CONTENT. Otherwise [].

6) **Publications/achievements/metrics**: include only if explicitly present. **No inferences.**

7) If any field is missing or unclear, return "" or [] for that field.

Return JSON only.
"""

# 新增：Homepage Insights 提取（仅从个人网站）
HOMEPAGE_INSIGHTS_PROMPT = lambda author_name, dump: f"""
You are in ZERO-HALLUCINATION mode. Extract ONLY what is explicitly present in TEXT CONTENT from the person's personal website. If information is not explicitly present, return empty string "" or empty list [].

TARGET AUTHOR: {author_name}
CONTENT TYPE: Personal Website / Homepage

TEXT CONTENT (source of truth — do not infer beyond this):
{dump}
==== END ====

OUTPUT REQUIREMENTS
- Return valid JSON only with exactly these keys:
{{
  "current_status": "<concise status like 'Associate Professor at UMD' or ''>",
  "role_affiliation_detailed": "<verbatim detailed role & affiliation line or ''>",
  "research_focus": ["..."],          
  "research_keywords": ["..."],       
  "highlights": ["..."]               
}}

EXTRACTION RULES
1) Prefer explicit self-descriptions like headings, bio lines, hero sections, or 'About' paragraphs for status.
2) Research focus: extract at most 5 items. Each item must be fewer than 5 words. Use explicit lists or clearly marked sections (Research/Focus/Interests).
3) Research keywords: tags/keywords shown; if absent, keep [].
4) Highlights: items from 'News', 'Highlights', 'Awards', 'Recent', 'Service' sections. Keep each item a single line.
5) Do not merge or infer from links alone; rely on text content only.
"""

# New: Dedicated highlights curation prompt
HOMEPAGE_HIGHLIGHTS_PROMPT = lambda author_name, dump: f"""
You are in STRICT extraction and curation mode for homepage highlights.

TEXT CONTENT (source of truth — do not invent beyond this):
{dump}
==== END ====

Task Phases:
Phase A — Extraction:
- Parse sections likely named 'News', 'Highlights', 'Awards', 'Recent', 'Service', etc.
- Collect raw candidate items verbatim (short phrases or single-sentence items).

Phase B — Evaluation (internal, do not output intermediate lists):
- Score each candidate (keep scores private):
  +2 if award/grant/fellowship/best paper/distinguished honor
  +1.5 if invited/keynote talk or notable media/press
  +1 if code/dataset/project release or paper acceptance at top-tier venue
  +0.5 if lab/group leadership/service role
  -1 if trivial (e.g., 'page updated', 'moved site') or unrelated
- Keep items with total score ≥ 1.0. Deduplicate near-duplicates.

Phase C — Curation & Formatting:
- Produce ≤16 curated highlight strings.
- Each item ≤160 characters, self-contained, no excessive dates; include venue/event names when helpful.
- Use concise, neutral phrasing; do not add content not present in TEXT CONTENT.

Output JSON only with EXACT keys and types:
{{
  "curated_highlights": [
    "<concise curated highlight item>",
    "..."
  ],
  "summary": "<1–2 sentence overall summary of the highlights>"
}}
"""

# New: Open-source projects and datasets extractor
HOMEPAGE_PROJECTS_PROMPT = lambda author_name, dump: f"""
Extract open-source items (projects/datasets/libraries/code) that are clearly authored or owned by the target.
Use TEXT CONTENT only. Do not include generic outbound links not attributed to the author/lab.

TEXT CONTENT (source of truth):
{dump}
==== END ====

Task Phases:
Phase A — Extraction:
- Identify candidate items that have: a name, brief description, and ideally a URL shown on the page.

Phase B — Evaluation (internal, do not output scores):
- Relevance to author/lab (+1.0 strong attribution; +0.5 weak attribution).
- Presence of first-party URL on page (+0.5).
- Clarity and uniqueness of the item (+0.5).
- Exclude forks/mirrors, generic external resources, or unrelated tools.
- Keep items with total score ≥ 1.0.

Phase C — Formatting:
- Choose the most accurate type from: project | dataset | library | code.
- Description: verbatim or lightly compressed 1-clause description present on page.
- URL: copy as shown (http/https); if not present in TEXT CONTENT, leave empty string.
- Output up to 6 items.

Output JSON only with EXACT schema:
{{
  "items": [
    {{"name": "<name>", "type": "project|dataset|library|code", "url": "<url or ''>", "description": "<short clause>"}},
    {{"name": "...", "type": "...", "url": "...", "description": "..."}}
  ]
}}
"""

# New: Academic service and invited talks extractor
HOMEPAGE_SERVICE_TALKS_PROMPT = lambda author_name, dump: f"""
Extract academic service roles and invited/keynote talks strictly from TEXT CONTENT.
- Service roles examples: PC/AC/OC, area chair, editor, organizer, chair, reviewer (only if explicitly listed).
- Invited talks: explicitly marked invited/keynote/talk/seminar/colloquium with venue if present.

TEXT CONTENT (source of truth):
{dump}
==== END ====

Task Phases:
Phase A — Extraction:
- Collect raw service entries and talk entries as written.

Phase B — Evaluation (internal):
- Relevance to academic service (exclude teaching duties unless labeled service) and talks (exclude generic presentations).
- Prefer entries with venue/event and year; keep concise.

Phase C — Formatting:
- For service roles, format like: "<role> @ <venue/organization> (<year or ''>)" when possible.
- For invited talks, format like: "<title or topic> — <venue/event> (<year or ''>)".
- Deduplicate near-identical entries. Keep up to 24 per list.

Output JSON only with EXACT keys and types:
{{
  "service_roles": ["role @ venue (year)", "..."],
  "invited_talks": ["title — venue (year)", "..."]
}}
"""

# New: Representative papers extracted from homepage
HOMEPAGE_REP_PAPERS_PROMPT = lambda author_name, dump: f"""
Select up to 3 representative papers from the homepage TEXT CONTENT.
Preference order:
1) Items listed under 'selected publications' or similar curated sections.
2) Recent papers in top-tier venues (e.g., NeurIPS, ICML, ICLR, CVPR, ICCV, ACL, Nature, Science).
3) Otherwise, papers with clear venue/year and a link shown on the page.

TEXT CONTENT (source of truth):
{dump}
==== END ====

Task Phases:
Phase A — Extraction:
- Identify candidate papers with title and any of: venue, year, or URL.

Phase B — Evaluation (internal scoring, do not output scores):
- +2 if in 'selected publications' or explicitly labeled representative/highlight.
- +1.5 if venue is top-tier or journal like Nature/Science.
- +1 if year present and ≥ (current_year-3).
- +0.5 if page provides a direct paper URL.
- Keep top-scoring candidates; deduplicate by normalized title.

Phase C — Formatting:
- Title: as written (trim whitespace).
- Venue: concise short name (e.g., NeurIPS, Nature, arXiv). Leave "" if uncertain.
- Year: integer if visible; else null.
- Type mapping:
  - If venue contains 'arXiv' → "Preprint"
  - If venue is a major journal (Nature/Science/TPAMI/etc.) → "Journal Article"
  - Else → "Conference Paper"
- Links: a URL string present on the page for the paper. If none, leave "".

Output JSON only with EXACT schema:
{{
  "papers": [
    {{"Title": "<title>", "Venue": "<venue or ''>", "Year": <int or null>, "Type": "Conference Paper|Preprint|Journal Article", "Links": "<url or ''>"}},
    {{"Title": "...", "Venue": "...", "Year": <int or null>, "Type": "...", "Links": "..."}}
  ]
}}
"""

# 通用字段抽取prompt
PROFILE_EXTRACT_PROMPT = lambda author_name, dump, platform_type="generic": f"""
Extract author profile fields from {platform_type} page content.

TARGET AUTHOR: {author_name}
PLATFORM TYPE: {platform_type}

TEXT CONTENT:
{dump}
==== END ====

Return STRICT JSON with these keys:
{{
  "name": "<full name as written>",
  "aliases": ["ONLY alternative names/nicknames of THIS AUTHOR"],
  "affiliation_current": "<FULL role + institution, e.g. 'PhD student at MIT' or 'Postdoc at Stanford' or 'Professor at CMU'>",
  "emails": ["professional emails only"],
  "personal_homepage": "<personal website URL if different from current page>",
  "interests": ["research areas/topics"],
  "selected_publications": [{{"title":"...", "year":2024, "venue":"...", "url":"..."}}],
  "notable_achievements": ["awards/honors/recognitions"],
  "social_impact": "<h-index, citations, influence metrics>",
  "career_stage": "<student/postdoc/assistant_prof/associate_prof/full_prof/industry>",
  "social_links": {{"platform": "url"}}
}}

CRITICAL EXTRACTION RULES:
1. **Name**: Use the most complete/formal version found for THIS AUTHOR ONLY
2. **Aliases**: ONLY include alternative names/nicknames of THE TARGET AUTHOR
3. **Affiliation**: MUST include both role AND institution (e.g., "PhD student at XYZ University", "Associate Professor at ABC Institute", "Research Scientist at Company"). Never just the institution name alone.
4. **Emails**: Only work/institutional emails visible on page
5. **Homepage**: Personal website URL (NOT the current page URL)
6. **Interests**: Specific research areas, not generic terms
7. **Publications**: Max 3 most recent/important papers by THIS AUTHOR
8. **Notable**: Awards, fellowships, best papers of THIS AUTHOR only
9. **Social Impact**: Citation counts, h-index of THIS AUTHOR
10. **Career Stage**: Current career stage of THIS AUTHOR
11. **Social Links**: Extract social media/platform links from the page

PLATFORM-SPECIFIC HINTS:
- OpenReview: Focus on reviews, paper submissions, expertise areas  
- Google Scholar: Emphasize citation metrics, publication trends
- ORCID: Look for comprehensive work history, affiliations
- University pages: Focus on teaching, research groups, lab info
- GitHub: Technical projects, code contributions, collaboration

If any field is unclear/absent, return empty string "" or empty list [].
DO NOT invent information not present in the text.
NEVER include names of other people in aliases field.
"""




def _run_search_terms(terms: List[str], pages: int = 1, k_per_query: int = 6, search_engines: List[str] = None) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    if not terms:
        return results
    if search_engines is None:
        search_engines = config.SEARXNG_ENGINES
    # Run sequentially to avoid nested concurrency conflicts with downstream multi-threading
    for t in terms:
        try:
            rows = docker_utils.run_search(t, pages=pages, k_per_query=k_per_query, search_engines=search_engines) or []
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

# ============================ QUERY BUILDING FUNCTIONS ============================

def build_author_queries(first_author: str, paper_title: str, aliases: List[str] = None, 
                        include_notable: bool = True, search_more: bool = False) -> List[str]:
    """Build comprehensive and precise search queries for author discovery"""
    aliases = aliases or []
    name_variants = [first_author] + aliases
    base = []

    for nm in name_variants:
        # 核心查询：作者名 + 论文名
        name_paper_q = f'"{nm}" "{paper_title}"'
        # 作者名查询
        name_q = f'"{nm}"'
        
        # 平台特定查询
        for tpl in PLATFORM_QUERIES:
            if "github.io" in tpl or "personal" in tpl or "homepage" in tpl:
                base.append(tpl.format(q=name_q))
            else:
                base.append(tpl.format(q=name_paper_q))
                
            # 优先使用名字+论文的查询
            if "x.com" in tpl or "twitter.com" in tpl or "linkedin.com" in tpl or "researchgate.net" in tpl or "huggingface.co" in tpl:
                # 然后使用只有名字的查询（更广泛）
                base.append(tpl.format(q=name_q))
            else:
                base.append(tpl.format(q=name_paper_q))

        
        # 添加Notable信息查询
        if include_notable:
            for notable_tpl in NOTABLE_QUERIES:
                base.append(notable_tpl.format(q=name_q))

    # 去重并排序（优先级排序）
    seen, out = set(), []
    
    priority_0_0 = [q for q in base if any(site in q for site in ['github.io', "personal", "homepage"]) ]
    
    # 第一优先级：个人主页
    priority_0 = [q for q in base if any(site in q for site in ['github.com', 'personal', 'homepage', 'x.com', 'twitter.com', 'linkedin.com', 'researchgate.net', 'huggingface.co']) 
                  and paper_title in q]
    
    # # 第一优先级：学术平台 + 名字+论文
    # priority_1 = [q for q in base if any(site in q for site in 
    #               ['openreview.net', 'semanticscholar.org', 'scholar.google.com', 'orcid.org']) 
    #               and paper_title in q]
    
    # # 第二优先级：机构页面 + 名字+论文  
    # priority_2 = [q for q in base if any(site in q for site in 
    #               ['site:edu', 'site:ac.']) 
    #               and paper_title in q]
    
    # # 第三优先级：学术平台 + 只有名字
    # priority_3 = [q for q in base if any(site in q for site in 
    #               ['openreview.net', 'semanticscholar.org', 'scholar.google.com', 'orcid.org']) 
    #               and paper_title not in q and not any(notable in q for notable in 
    #               ['award', 'fellow', 'best paper'])]
    
    # # 第四优先级：Notable查询
    # priority_4 = [q for q in base if any(notable in q for notable in 
    #               ['award', 'fellow', 'best paper', 'rising star', 'keynote'])]
    
    # # 第五优先级：其他查询
    # priority_5 = [q for q in base if q not in priority_0 + priority_1 + priority_2 + priority_3 + priority_4]
    
    # 按优先级合并
    # for priority_list in [priority_0_0,priority_0, priority_1, priority_2, priority_3, priority_4, priority_5]:
    if not search_more:
        for priority_list in [priority_0_0]:
            for q in priority_list:
                if q not in seen and len(out) < 150:  # 增加查询数量限制
                    seen.add(q)
                    out.append(q)
    else:
        for priority_list in [priority_0]:
            for q in priority_list:
                if q not in seen and len(out) < 150:  # 增加查询数量限制
                    seen.add(q)
                    out.append(q)
    return out

# ============================ SCORING AND EVALUATION FUNCTIONS ============================

def score_candidate(item: Dict[str, Any], author_name: str, paper_title: str) -> float:
    """Score a search result candidate based on relevance and trust"""
    url = (item.get('url') or '').lower()
    title = (item.get('title') or '')
    snippet = (item.get('snippet') or '')

    dom = domain_of(url)
    score = 0.0

    # Domain trust scoring
    if dom in WHITELIST_HOSTS:
        score += 0.8 * WHITELIST_HOSTS[dom]
    elif any(dom.endswith(k) for k in SECONDARY_HOSTS):
        score += 0.5
    elif dom in PERSONAL_DOMAINS:
        score += 0.9

    # Name and paper matching signals
    if author_name.lower() in (title + " " + snippet).lower():
        score += 0.25

    # Paper title presence
    if len(paper_title) > 0 and paper_title[:20].lower() in (title + " " + snippet).lower():
        score += 0.25

    # Platform-specific patterns
    if any(k in url for k in ['orcid.org/', 'openreview.net/profile', '/citations?user=', '/author/']):
        score += 0.25

    # Avoid generic content
    if any(k in url for k in ['news', 'blog', 'forum', 'comment', 'review']):
        score -= 0.2

    return max(0.0, score)

def extract_ids_from_url(url: str) -> Dict[str, str]:
    """Extract platform IDs from URL using regex patterns"""
    out = {}
    for key, pat in ID_PATTERNS.items():
        m = pat.search(url)
        if m:
            val = m.group(1)
            if key.startswith('dblp'):
                out['dblp'] = val
            else:
                out[key] = val
    return out

def check_url_redirect(url: str, max_redirects: int = 5) -> Tuple[str, bool]:
    """
    检查URL是否有重定向，返回最终URL和是否发生了重定向
    
    Args:
        url: 原始URL
        max_redirects: 最大重定向次数
        
    Returns:
        (final_url, redirected)
    """
    try:
        # 使用HEAD请求检查重定向，避免下载完整内容
        response = requests.head(url, allow_redirects=True, timeout=10, headers=config.UA)
        final_url = response.url
        
        # 规范化URL比较
        original_normalized = normalize_url(url)
        final_normalized = normalize_url(final_url)
        
        redirected = original_normalized != final_normalized
        
        if redirected:
            print(f"[URL Redirect] {url} → {final_url}")
        
        return final_url, redirected
        
    except Exception as e:
        print(f"[URL Redirect] Failed to check redirect for {url}: {e}")
        return url, False

def verify_homepage_identity_before_fetch(author_name: str, paper_title: str, url: str, 
                                       snippet: str, llm_client) -> Tuple[bool, float, str]:
    """
    在抓取homepage完整内容之前验证身份
    
    Args:
        author_name: 目标作者姓名
        paper_title: 已知论文标题
        url: homepage URL
        snippet: 搜索结果snippet
        llm_client: LLM客户端
        
    Returns:
        (is_target_author, confidence, reason)
    """
    try:
        # 获取少量预览内容进行身份验证
        preview_content = fetch_text(url, max_chars=2000, snippet=snippet)
        if not preview_content or len(preview_content) < 100:
            return False, 0.1, "Insufficient content for verification"
        
        prompt = PROMPT_HOMEPAGE_IDENTITY_CHECK(author_name, paper_title, url, preview_content)
        result = llm.safe_structured(llm_client, prompt, schemas.LLMHomepageIdentitySpec)
        
        if result:
            is_target = bool(getattr(result, 'is_target_author_homepage', False))
            confidence = float(getattr(result, 'confidence', 0.0))
            reason = str(getattr(result, 'reason', 'LLM verification'))
            author_found = str(getattr(result, 'author_name_found', ''))
            research_match = bool(getattr(result, 'research_area_match', False))
            
            # 增加额外的验证逻辑
            if is_target and confidence >= 0.7:
                # 检查找到的作者名是否与目标匹配
                if author_found and author_name.lower() in author_found.lower():
                    return True, confidence, f"Identity verified: {reason}"
                elif research_match:
                    return True, max(0.6, confidence - 0.1), f"Research area match: {reason}"
                else:
                    return False, 0.3, f"Name mismatch despite LLM approval: {reason}"
            
            return is_target, confidence, reason
        
    except Exception as e:
        print(f"[Homepage Identity Check] LLM failed for {url}: {e}")
        
    # 回退到简单的文本匹配
    if snippet:
        author_words = set(author_name.lower().split())
        snippet_lower = snippet.lower()
        name_matches = sum(1 for word in author_words if len(word) > 2 and word in snippet_lower)
        
        if name_matches >= len(author_words) * 0.7:
            return True, 0.6, "Fallback name matching in snippet"
    
    return False, 0.2, "Failed identity verification"

def verify_homepage_content_after_fetch(author_name: str, url: str, homepage_content: str, 
                                      llm_client) -> Tuple[bool, float, str]:
    """
    在全面抓取homepage内容后进行二次验证
    
    Args:
        author_name: 目标作者姓名
        url: homepage URL
        homepage_content: 抓取到的完整homepage内容
        llm_client: LLM客户端
        
    Returns:
        (is_personal_homepage, confidence, reason)
    """
    try:
        # 使用更严格的post-fetch验证prompt
        prompt = f"""
POST-FETCH HOMEPAGE VALIDATION (Strict Personal Homepage Check)

GOAL
Verify this is a PERSONAL HOMEPAGE after comprehensive content extraction.

TARGET AUTHOR: {author_name}
URL: {url}
FULL CONTENT: {homepage_content[:200]}

CRITICAL REQUIREMENTS (ALL must be met):
1. PERSONAL HOMEPAGE: Must be clearly a personal page, not institutional/workshop/conference
2. AUTHOR FOCUS: Content must be primarily about the individual author, not multiple people
3. PERSONAL CONTENT: Must contain personal information (CV, bio, publications, research interests)

STRICT REJECTION CRITERIA (any of these = REJECT):
- Workshop/conference pages (e.g., "MICCAI Workshop", "Call for Papers", "Program Committee")
- Institutional pages (department, lab, course pages)
- Event pages (symposium, meeting, workshop announcements)
- Multi-author pages without clear individual focus
- Generic academic templates without personal content

EVIDENCE ANALYSIS:
- Personal identifiers (email, GitHub, Google Scholar, ORCID): +2
- Personal timeline/CV content: +2
- Individual research interests/publications: +2
- Personal photos/contact info: +1
- Single author focus (not multiple people): +2

NEGATIVE INDICATORS:
- Workshop/conference content: -5
- Event announcements: -4
- Institutional focus: -4
- Generic template: -2

DECISION: Only return TRUE if this is clearly a personal homepage focused on the individual author.

OUTPUT (JSON):
{{
  "is_personal_homepage": true/false,
  "confidence": 0.0-1.0,
  "reason": "<detailed analysis of why this is/isn't a personal homepage>"
}}
"""
        
        result = llm.safe_structured(llm_client, prompt, schemas.LLMHomepageIdentitySpecSimple)
        
        if result:
            is_personal = bool(getattr(result, 'is_personal_homepage', False))
            confidence = float(getattr(result, 'confidence', 0.0))
            reason = str(getattr(result, 'reason', 'Post-fetch validation'))
            
            return is_personal, confidence, reason
        
    except Exception as e:
        print(f"[Post-fetch Homepage Validation] LLM failed for {url}: {e}")
    
    # Fallback: simple content analysis
    content_lower = homepage_content.lower()
    
    # Check for workshop/conference indicators
    workshop_indicators = [
        'workshop', 'conference', 'call for papers', 'program committee', 
        'important dates', 'submission deadline', 'keynote speakers',
        'poster session', 'awards', 'sponsors'
    ]
    
    if any(indicator in content_lower for indicator in workshop_indicators):
        return False, 0.1, "Workshop/conference page detected"
    
    # Check for personal content indicators
    personal_indicators = [
        'cv', 'curriculum vitae', 'biography', 'about me', 'research interests',
        'publications', 'contact', 'email', 'github', 'google scholar'
    ]
    
    personal_score = sum(1 for indicator in personal_indicators if indicator in content_lower)
    
    if personal_score >= 3:
        return True, 0.6, f"Personal content detected ({personal_score} indicators)"
    
    return False, 0.3, "Insufficient personal content indicators"

def verify_profile_identity(author_name: str, platform: str, url: str, content: str, 
                          llm_client) -> Tuple[bool, float, str]:
    """
    使用LLM验证profile是否属于目标作者
    
    Args:
        author_name: 目标作者姓名
        platform: 平台类型 (linkedin, twitter, scholar, etc.)
        url: profile URL
        content: 页面内容预览
        llm_client: LLM客户端
        
    Returns:
        (is_target_author, confidence, reason)
    """
    # 对于权威学术平台，降低验证要求
    if platform in ['orcid', 'openreview', 'scholar', 'semanticscholar']:
        # 简单的名字匹配检查
        author_words = set(author_name.lower().split())
        content_lower = content.lower()
        
        # 检查是否有足够的名字匹配
        name_matches = sum(1 for word in author_words if len(word) > 2 and word in content_lower)
        if name_matches >= len(author_words) * 0.6:  # 60%的名字词汇匹配
            return True, 0.8, f"Academic platform with name match"
    
    # 对于社交平台，使用LLM严格验证
    if platform in ['linkedin', 'twitter', 'researchgate']:
        try:
            prompt = PROMPT_VERIFY_PROFILE_IDENTITY(author_name, platform, url, content)
            result = llm.safe_structured(llm_client, prompt, schemas.LLMSelectSpecVerifyIdentity)
            
            if result:
                is_target = bool(getattr(result, 'is_target_author', False))
                confidence = float(getattr(result, 'confidence', 0.0))
                reason = str(getattr(result, 'reason', 'LLM verification'))
                return is_target, confidence, reason
        except Exception as e:
            print(f"[Profile Verification] LLM failed for {platform}: {e}")
    
    # 默认：基于内容的简单验证
    author_words = set(author_name.lower().split())
    content_lower = content.lower()
    name_matches = sum(1 for word in author_words if len(word) > 2 and word in content_lower)
    
    if name_matches >= len(author_words) * 0.7:
        return True, 0.6, "Basic name matching"
    
    return False, 0.2, "Insufficient name match"

# ============================ SMART PLATFORM URL MANAGEMENT ============================

def should_update_platform_url(profile: AuthorProfile, platform_type: str, new_url: str, author_name: str) -> bool:
    """判断是否应该更新平台URL - 使用LLM验证关键更新"""
    current_url = profile.platforms.get(platform_type)
    if not current_url:
        return True  # 没有现有URL，直接添加
    
    # 对于LinkedIn和Twitter，如果现有URL质量很低，需要LLM验证
    if platform_type in ['linkedin', 'twitter']:
        current_quality = assess_url_quality(current_url, platform_type, author_name)
        new_quality = assess_url_quality(new_url, platform_type, author_name)
        
        # 如果新URL质量显著更高，且现有URL质量很低，直接更新
        if current_quality < 0.3 and new_quality > 0.6:
            return True
        
        # 如果质量相近，保持现有URL
        if abs(new_quality - current_quality) < 0.2:
            return False
    
    return assess_url_quality(new_url, platform_type, author_name) > assess_url_quality(current_url, platform_type, author_name)

def update_platform_url(profile: AuthorProfile, platform_type: str, new_url: str, author_name: str):
    """智能更新平台URL，优先保留更准确的链接"""
    
    if should_update_platform_url(profile, platform_type, new_url, author_name):
        profile.platforms[platform_type] = new_url

def assess_url_quality(url: str, platform: str, author: str) -> float:
    """评估URL质量"""
    score = 0.0
    author_lower = author.lower().replace(' ', '')
    author_parts = [part.lower() for part in author.split()]
    
    # 包含作者名字的URL质量更高
    if any(part in url.lower() for part in author_parts if len(part) > 2):
        score += 0.5
    
    # 特定平台的质量指标
    if platform == 'scholar' and 'citations?user=' in url:
        score += 0.4
    elif platform == 'github' and not any(bad in url for bad in ['/orgs/', '/topics/', '/search']):
        score += 0.4
    elif platform == 'linkedin':
        if '/in/' in url and not '/directory/' in url:
            score += 0.6  # LinkedIn个人档案
            # 检查用户名是否与作者相关
            linkedin_username = url.split('/in/')[-1].split('/')[0].split('?')[0]
            if any(part.lower() in linkedin_username.lower() for part in author_parts if len(part) > 2):
                score += 0.4
        elif '/directory/' in url:
            score -= 0.5  # 目录页面质量很低
    elif platform == 'twitter':
        if not any(bad in url for bad in ['/status/', '/search', '?lang=', '/hashtag/']):
            # 检查用户名是否与作者相关
            twitter_username = url.split('/')[-1].split('?')[0]
            name_match = any(part.lower() in twitter_username.lower() for part in author_parts if len(part) > 2)
            if name_match:
                score += 0.7  # 用户名匹配的Twitter账号
            else:
                score += 0.2  # 用户名不匹配的Twitter账号质量低
    elif platform == 'orcid' and re.search(r'\d{4}-\d{4}-\d{4}-\d{4}', url):
        score += 0.5
    elif platform == 'openreview' and 'profile?id=' in url:
        score += 0.4
    elif platform == 'homepage':
        # 个人域名优于托管服务
        if any(domain in url for domain in ['.com/', '.org/', '.net/', '.edu/']):
            score += 0.5
        if 'github.io' in url:
            score += 0.3
    
    # 惩罚明显错误的URL
    if any(bad in url.lower() for bad in ['directory', 'search', 'random', 'example']):
        score -= 0.3
        
    return max(0.0, score)

def validate_social_link_for_author(platform: str, url: str, author_name: str) -> bool:
    """
    验证社交媒体链接是否真的属于目标作者
    
    Args:
        platform: 平台类型
        url: 链接URL
        author_name: 目标作者姓名
        
    Returns:
        是否有效
    """
    if not url or not url.startswith('http'):
        return False
    
    author_words = [word.lower() for word in author_name.split() if len(word) > 2]
    url_lower = url.lower()
    
    # Twitter/X 特殊验证
    if platform == 'twitter':
        # 提取用户名
        if 'x.com/' in url_lower or 'twitter.com/' in url_lower:
            # 排除明显错误的URL
            if any(bad in url_lower for bad in ['/status/', '/search', '/hashtag/', '?lang=', '/i/']):
                return False
            
            return True
            # 提取用户名部分
            username_part = url_lower.split('/')[-1].split('?')[0]
            
            # 检查用户名是否与作者相关
            if len(username_part) < 3 or len(username_part) > 20:
                return False
            
            # 检查是否包含作者名字的部分
            name_match = any(word in username_part for word in author_words)
            return name_match
    
    # LinkedIn验证
    elif platform == 'linkedin':
        if 'linkedin.com/in/' in url_lower:
            # 排除目录页面
            if '/directory/' in url_lower:
                return False
            
            username_part = url_lower.split('/in/')[-1].split('/')[0].split('?')[0]
            
            return True
            # 检查用户名长度
            if len(username_part) < 3:
                return False
            
            # 检查是否包含作者名字的部分
            name_match = any(word in username_part for word in author_words)
            return name_match
    
    # GitHub验证
    elif platform == 'github':
        if 'github.com/' in url_lower:
            # 排除组织和搜索页面
            if any(bad in url_lower for bad in ['/orgs/', '/search', '/topics/', '/trending']):
                return False
            
            username_part = url_lower.split('github.com/')[-1].split('/')[0].split('?')[0]
            
            return True
            
            if len(username_part) < 2:
                return False
            
            # GitHub用户名通常与作者名相关
            name_match = any(word in username_part for word in author_words)
            return name_match
    
    # Scholar验证
    elif platform == 'scholar':
        return 'citations?user=' in url_lower
    
    # 其他平台的基本验证
    return True

def extract_social_links_from_content(content: str, base_url: str = "") -> Dict[str, str]:
    """从页面内容中提取社交媒体链接 - 增强版"""
    social_links = {}
    
    # 更全面的社交媒体链接模式，包括更多变体
    patterns = {
        'scholar': [
            r'https?://scholar\.google\.com/citations\?user=([A-Za-z0-9_\-]+)',
            r'https?://scholar\.google\.com/citations\?hl=[^&]*&user=([A-Za-z0-9_\-]+)',
            r'scholar\.google\.com/citations\?user=([A-Za-z0-9_\-]+)',  # 无协议版本
        ],
        'github': [
            r'https?://github\.com/([A-Za-z0-9_\-]+)(?:/[^"\s]*)?',
            r'github\.com/([A-Za-z0-9_\-]+)',  # 无协议版本
        ],
        'linkedin': [
            r'https?://(?:www\.)?linkedin\.com/in/([A-Za-z0-9_\-]+)',
            r'linkedin\.com/in/([A-Za-z0-9_\-]+)',  # 无协议版本
        ],
        'twitter': [
            r'https?://(?:x\.com|twitter\.com)/([A-Za-z0-9_]+)',
            r'(?:x\.com|twitter\.com)/([A-Za-z0-9_]+)',  # 无协议版本
            r'@([A-Za-z0-9_]+)',  # @username 格式
        ],
        'orcid': [
            r'https?://orcid\.org/(\d{4}-\d{4}-\d{4}-\d{4})',
            r'orcid\.org/(\d{4}-\d{4}-\d{4}-\d{4})',
        ],
        'openreview': [
            r'https?://openreview\.net/profile\?id=([A-Za-z0-9_\-\.%~]+)',
            r'openreview\.net/profile\?id=([A-Za-z0-9_\-\.%~]+)',
        ],
        'huggingface': [
            r'https?://huggingface\.co/([A-Za-z0-9_\-]+)',
            r'huggingface\.co/([A-Za-z0-9_\-]+)',
        ],
    }
    
    print(f"[Regex Debug] Content length: {len(content)} characters")
    
    for platform, pattern_list in patterns.items():
        for pattern in pattern_list:
            matches = re.findall(pattern, content, re.IGNORECASE)
            if matches:
                print(f"[Regex Match] {platform}: {pattern} found {len(matches)} matches: {matches[:3]}")  # 显示前3个匹配
                
                # 取第一个匹配的链接，但排除明显错误的
                valid_match = None
                for match in matches:
                    # 对Twitter特殊处理@username格式
                    if platform == 'twitter' and pattern.startswith(r'@'):
                        # 排除过短或明显不是用户名的匹配
                        if len(match) >= 3 and not any(bad in match.lower() for bad in ['http', 'www', 'com']):
                            valid_match = match
                            break
                    else:
                        # 其他平台的常规处理
                        if match and len(match) > 2:
                            valid_match = match
                            break
                
                if valid_match:
                    # 构建完整URL
                    if platform == 'scholar':
                        social_links[platform] = f"https://scholar.google.com/citations?user={valid_match}"
                    elif platform == 'github':
                        social_links[platform] = f"https://github.com/{valid_match}"
                    elif platform == 'linkedin':
                        social_links[platform] = f"https://www.linkedin.com/in/{valid_match}"
                    elif platform == 'twitter':
                        social_links[platform] = f"https://x.com/{valid_match}"
                    elif platform == 'orcid':
                        social_links[platform] = f"https://orcid.org/{valid_match}"
                    elif platform == 'openreview':
                        social_links[platform] = f"https://openreview.net/profile?id={valid_match}"
                    elif platform == 'huggingface':
                        social_links[platform] = f"https://huggingface.co/{valid_match}"
                    
                    print(f"[Regex Success] {platform}: {social_links[platform]}")
                    break  # 找到有效匹配后跳出内层循环
    
    print(f"[Regex Summary] Extracted {len(social_links)} social links: {list(social_links.keys())}")
    return social_links

# ============================ PROFILE MERGING FUNCTIONS ============================

def _extract_homepage_insights(author_name: str, dump: str, llm_ext) -> Optional[Any]:
    """提取主页insights信息"""
    try:
        insights_prompt = HOMEPAGE_INSIGHTS_PROMPT(author_name, dump)
        return llm.safe_structured(llm_ext, insights_prompt, schemas.HomepageInsightsSpec)
    except Exception as e:
        print(f"[Homepage Insights] Extraction failed: {e}")
        return None

def _extract_homepage_highlights(author_name: str, dump: str, llm_ext) -> Optional[Any]:
    """提取主页highlights信息"""
    try:
        hl_prompt = HOMEPAGE_HIGHLIGHTS_PROMPT(author_name, dump)
        return llm.safe_structured(llm_ext, hl_prompt, schemas.HomepageHighlightsSpec)
    except Exception as e:
        print(f"[Homepage Highlights] Extraction failed: {e}")
        return None

def _extract_homepage_projects(author_name: str, dump: str, llm_ext) -> Optional[Any]:
    """提取主页开源项目/数据集信息"""
    try:
        proj_prompt = HOMEPAGE_PROJECTS_PROMPT(author_name, dump)
        return llm.safe_structured(llm_ext, proj_prompt, schemas.OpenSourceProjectsSpec)
    except Exception as e:
        print(f"[Homepage Projects] Extraction failed: {e}")
        return None

def _extract_homepage_service_talks(author_name: str, dump: str, llm_ext) -> Optional[Any]:
    """提取主页学术服务与受邀报告信息"""
    try:
        svc_prompt = HOMEPAGE_SERVICE_TALKS_PROMPT(author_name, dump)
        return llm.safe_structured(llm_ext, svc_prompt, schemas.AcademicServiceSpec)
    except Exception as e:
        print(f"[Homepage Service/Talks] Extraction failed: {e}")
        return None

def _extract_homepage_rep_papers(author_name: str, dump: str, llm_ext) -> Optional[Any]:
    """提取主页代表作信息"""
    try:
        rep_prompt = HOMEPAGE_REP_PAPERS_PROMPT(author_name, dump)
        return llm.safe_structured(llm_ext, rep_prompt, schemas.LLMRepresentativePapersSpec)
    except Exception as e:
        print(f"[Homepage Rep Papers] Extraction failed: {e}")
        return None

def process_homepage_candidate(candidate: ProfileCandidate, author_name: str, paper_title: str, 
                             profile: AuthorProfile, protected_platforms: set, llm_ext) -> bool:
    """
    处理homepage类型的候选者
    
    Args:
        candidate: 候选者信息
        author_name: 目标作者姓名
        paper_title: 论文标题
        profile: 当前作者档案
        protected_platforms: 受保护的平台集合
        llm_ext: LLM客户端
        
    Returns:
        是否成功处理
    """
    print(f"[Homepage Candidate] Processing: {candidate.url}")
    
    # Check if this is a trusted source (from OpenReview)
    is_trusted = getattr(candidate, 'trusted_source', False)
    
    # 1. 检查URL重定向
    final_url, redirected = check_url_redirect(candidate.url)
    working_url = final_url if redirected else candidate.url
    
    if redirected:
        print(f"[Homepage Redirect] Using final URL: {working_url}")
    
    # 2. 预验证身份（使用最终URL）
    # If from OpenReview, skip validation (trusted source)
    if is_trusted:
        print(f"[Homepage Trusted] From OpenReview, skipping validation, directly processing")
        is_target = True
        confidence = 1.0
        reason = "Trusted source from OpenReview profile"
    else:
        # For web-searched homepages, perform strict validation
        is_target, confidence, reason = verify_homepage_identity_before_fetch(
            author_name, paper_title, working_url, candidate.snippet, llm_ext
        )
        
        print(f"[Homepage Identity] {is_target} (conf: {confidence:.2f}, reason: {reason})")
        
        # Stricter threshold for web-searched homepages
        if not is_target or confidence < 0.6:
            print(f"[Homepage Rejected] Identity verification failed (web-searched homepage)")
            return False
    
    # 3. 身份验证通过，进行全面抓取（使用最终URL）
    print(f"[Homepage] Identity verified, starting comprehensive fetch")
    homepage_result = fetch_homepage_comprehensive(working_url, author_name, max_chars=50000, include_subpages=True, max_subpages=6)
    
    if not homepage_result['success']:
        print(f"[Homepage] Comprehensive fetch failed, using fallback")
        txt = fetch_text(working_url, max_chars=30000, snippet=candidate.snippet)
        if not txt or len(txt) < config.MIN_TEXT_LENGTH:
            return False
        
        # 对fallback内容也进行post-fetch验证
        print(f"[Homepage] Post-fetch validation for fallback content")
        is_personal_homepage, post_confidence, post_reason = verify_homepage_content_after_fetch(
            author_name, working_url, txt, llm_ext
        )
        
        if not is_personal_homepage:
            print(f"[Homepage Rejected] Post-fetch validation failed for fallback: {post_reason}")
            return False
        
        print(f"[Homepage] Post-fetch validation passed for fallback (conf: {post_confidence:.2f}, reason: {post_reason})")
    else:
        txt = homepage_result['text_content']
        
        # 4. 抓取后进行二次验证，确保是个人主页
        print(f"[Homepage] Post-fetch validation starting")
        is_personal_homepage, post_confidence, post_reason = verify_homepage_content_after_fetch(
            author_name, working_url, txt, llm_ext
        )
        
        if not is_personal_homepage:
            print(f"[Homepage Rejected] Post-fetch validation failed: {post_reason}")
            return False
        
        print(f"[Homepage] Post-fetch validation passed (conf: {post_confidence:.2f}, reason: {post_reason})")
        
        # 3. 直接从HTML提取的高质量链接
        html_social_links = homepage_result['social_platforms']
        html_emails = homepage_result['emails']
        
        print(f"[Homepage Integration] Adding {len(html_social_links)} social links and {len(html_emails)} emails")
        
        # 添加社交平台链接（最高优先级，但需要验证）
        for platform, url in html_social_links.items():
            if platform not in profile.platforms and validate_social_link_for_author(platform, url, author_name):
                profile.platforms[platform] = url
                protected_platforms.add(platform)
                print(f"[Homepage Direct] Added {platform}: {url}")
            elif not validate_social_link_for_author(platform, url, author_name):
                print(f"[Homepage Rejected] Invalid {platform} link: {url}")
        
        # 添加邮箱（经过过滤）
        for email in html_emails:
            if email not in profile.emails and is_email_relevant_to_author(email, author_name):
                profile.emails.append(email)
                print(f"[Homepage Direct] Added email: {email}")
    
    # 4. LLM内容提取 + Insights提取
    if len(txt) >= config.MIN_TEXT_LENGTH:
        dump = txt[:25000] if homepage_result['success'] else txt[:15000]
        prompt = HOMEPAGE_EXTRACT_PROMPT(author_name, dump)
        
        try:
            ext = llm.safe_structured(llm_ext, prompt, schemas.LLMAuthorProfileSpec)
            if ext:
                # 处理提取的信息
                process_extracted_profile_info(ext, candidate.url, author_name, profile, protected_platforms, is_homepage=True)
                # 并行提取所有主页数据
                try:
                    # 定义提取任务
                    extraction_tasks = [
                        ("insights", _extract_homepage_insights, (author_name, dump, llm_ext)),
                        ("highlights", _extract_homepage_highlights, (author_name, dump, llm_ext)),
                        ("projects", _extract_homepage_projects, (author_name, dump, llm_ext)),
                        ("service_talks", _extract_homepage_service_talks, (author_name, dump, llm_ext)),
                        ("rep_papers", _extract_homepage_rep_papers, (author_name, dump, llm_ext))
                    ]
                    
                    # 并行执行所有提取任务 - 增强调试信息
                    print(f"[Homepage LLM] Starting 5 parallel extraction tasks for {len(dump)} chars content")
                    successful_tasks = 0
                    failed_tasks = []
                    
                    # Dynamic concurrency for LLM extraction tasks (CPU-bound)
                    extraction_max_workers = get_llm_workers(5)
                    print(f"[Homepage LLM] Using {extraction_max_workers} workers for 5 extraction tasks")
                    with ThreadPoolExecutor(max_workers=extraction_max_workers) as executor:
                        # 提交所有任务
                        future_to_task = {
                            executor.submit(task_func, *args): task_name 
                            for task_name, task_func, args in extraction_tasks
                        }
                        
                        # 收集结果
                        for future in as_completed(future_to_task):
                            task_name = future_to_task[future]
                            try:
                                result = future.result(timeout=30)  # 添加超时
                                if result:
                                    setattr(profile, f'_homepage_{task_name}', result)
                                    successful_tasks += 1
                                    print(f"[Homepage {task_name.title()}] ✅ Extraction successful - {type(result).__name__}")
                                    
                                    # 详细输出结果信息
                                    if task_name == 'projects' and hasattr(result, 'items'):
                                        print(f"  → Projects found: {len(result.items) if result.items else 0}")
                                    elif task_name == 'service_talks' and hasattr(result, 'service_roles'):
                                        print(f"  → Service roles: {len(result.service_roles) if result.service_roles else 0}")
                                        print(f"  → Invited talks: {len(result.invited_talks) if result.invited_talks else 0}")
                                    elif task_name == 'rep_papers' and hasattr(result, 'papers'):
                                        print(f"  → Rep papers: {len(result.papers) if result.papers else 0}")
                                    elif task_name == 'insights' and hasattr(result, 'research_focus'):
                                        print(f"  → Research focus: {len(result.research_focus) if result.research_focus else 0}")
                                else:
                                    failed_tasks.append((task_name, "No result returned"))
                                    print(f"[Homepage {task_name.title()}] ❌ Extraction returned None")
                            except Exception as e:
                                failed_tasks.append((task_name, str(e)))
                                print(f"[Homepage {task_name.title()}] ❌ Extraction failed: {e}")
                    
                    print(f"[Homepage LLM] Summary: {successful_tasks}/5 tasks successful")
                    if failed_tasks:
                        print(f"[Homepage LLM] Failed tasks: {[f'{name}({reason})' for name, reason in failed_tasks]}")
                                
                except Exception as e:
                    print(f"[Homepage Parallel Extraction] Failed: {e}")
                return True
        except Exception as e:
            print(f"[Homepage LLM] Extraction failed: {e}")
    else:
        print(f"[Homepage LLM] Extraction failed: Length too short: {len(txt)}")
    
    
    return False

def process_regular_candidate(candidate: ProfileCandidate, author_name: str, 
                            profile: AuthorProfile, protected_platforms: set, llm_ext) -> bool:
    """
    处理非homepage类型的候选者
    
    Args:
        candidate: 候选者信息
        author_name: 目标作者姓名
        profile: 当前作者档案
        protected_platforms: 受保护的平台集合
        llm_ext: LLM客户端
        
    Returns:
        是否成功处理
    """
    # 1. 确定平台类型
    host = domain_of(candidate.url)
    platform_type = determine_platform_type(candidate.url, host)
    
    if not platform_type:
        return False
    
    # 2. 抓取内容
    max_chars = config.FETCH_MAX_CHARS
    txt = fetch_text(candidate.url, max_chars=max_chars, snippet=candidate.snippet)
    
    if not txt or len(txt) < config.MIN_TEXT_LENGTH:
        print(f"[Regular Candidate] Failed to fetch sufficient content from {candidate.url}")
        return False
    
    print(f"[Regular Candidate] Fetched {len(txt)} characters from {candidate.url}")
    
    # 3. 对社交平台进行身份验证
    if platform_type in ['linkedin', 'twitter', 'researchgate']:
        is_target, confidence, reason = verify_profile_identity(
            author_name, platform_type, candidate.url, txt[:1000], llm_ext
        )
        print(f"[Profile Verification] {platform_type}: {is_target} (conf: {confidence:.2f})")
        
        if not is_target or confidence < 0.6:
            print(f"[Profile Rejected] {platform_type} profile rejected")
            return False
    
    # 4. 更新平台URL
    if platform_type not in protected_platforms:
        update_platform_url(profile, platform_type, candidate.url, author_name)
    else:
        print(f"[Skipped Platform] {platform_type} already protected by homepage")
    
    # 5. LLM内容提取
    dump = txt[:8000]
    platform_hint = get_platform_hint(host)
    prompt = PROFILE_EXTRACT_PROMPT(author_name, dump, platform_hint)
    
    try:
        ext = llm.safe_structured(llm_ext, prompt, schemas.LLMAuthorProfileSpec)
        if ext:
            process_extracted_profile_info(ext, candidate.url, author_name, profile, protected_platforms, is_homepage=False)
            return True
    except Exception as e:
        print(f"[Regular LLM] Extraction failed for {candidate.url}: {e}")
    
    return False

def determine_platform_type(url: str, host: str) -> str:
    """确定平台类型 - 增强homepage检测"""
    url_lower = url.lower()
    
    # 权威学术平台
    if 'orcid.org' in host:
        return 'orcid'
    elif 'openreview.net' in host:
        return 'openreview'
    elif 'scholar.google.' in host:
        return 'scholar'
    elif 'semanticscholar.org' in host:
        return 'semanticscholar'
    elif 'dblp.org' in host:
        return 'dblp'
    
    # 机构网站
    elif host.endswith('.edu') or host.endswith('.ac.nz') or host.endswith('.ac.uk'):
        return 'university'
    
    # 个人网站检测 - 增强版
    elif 'github.io' in host:
        return 'homepage'
    elif any(personal_indicator in host for personal_indicator in [
        'personal', 'homepage', 'home', 'about', 'profile'
    ]):
        return 'homepage'
    elif any(domain_pattern in host for domain_pattern in [
        '.com', '.org', '.net', '.me', '.io'
    ]) and not any(platform in host for platform in [
        'github.com', 'linkedin.com', 'twitter.com', 'x.com', 'facebook.com',
        'instagram.com', 'youtube.com', 'medium.com', 'reddit.com'
    ]):
        # 可能是个人域名，进一步检查URL路径
        if any(indicator in url_lower for indicator in [
            'personal', 'homepage', 'home', 'about', 'profile', 'cv', 'resume'
        ]) or len(host.split('.')) <= 2:  # 简单域名如 yuzheyang.com
            return 'homepage'
    
    # 代码和专业平台
    elif 'github.com' in host:
        return 'github'
    elif 'huggingface.co' in host:
        return 'huggingface'
    elif 'researchgate.net' in host:
        return 'researchgate'
    
    # 社交媒体
    elif 'x.com' in host or 'twitter.com' in host:
        return 'twitter'
    elif 'linkedin.com' in host:
        return 'linkedin'
    
    # 排除明显不相关的网站
    elif any(blocked in host for blocked in [
        'wikipedia', 'news', 'blog', 'forum', 'reddit', 'youtube', 'facebook'
    ]):
        return None
    
    return None

def get_platform_hint(host: str) -> str:
    """获取平台提示"""
    if 'openreview.net' in host:
        return "openreview"
    elif 'scholar.google.' in host:
        return "google_scholar"
    elif 'orcid.org' in host:
        return "orcid"
    elif 'semanticscholar.org' in host:
        return "semantic_scholar"
    elif host.endswith('.edu') or host.endswith('.ac.uk') or host.endswith('.ac.nz'):
        return "university"
    elif 'github.com' in host:
        return "github"
    return "generic"

def process_extracted_profile_info(ext, url: str, author_name: str, profile: AuthorProfile, 
                                 protected_platforms: set, is_homepage: bool = False):
    """处理LLM提取的profile信息"""
    # 处理个人主页URL
    personal_homepage = getattr(ext, 'personal_homepage', '') or getattr(ext, 'homepage_url', '')
    if personal_homepage == url:
        personal_homepage = None  # 当前页面不是个人主页
    
    if is_homepage and not personal_homepage:
        personal_homepage = url
    
    if 'github.io' in url and not profile.homepage_url:
        profile.homepage_url = url
    
    # 处理社交链接
    social_links = getattr(ext, 'social_links', {}) or {}
    
    if is_homepage:
        # 个人网站：强制更新所有社交链接（但需要验证）
        for social_platform, social_url in social_links.items():
            if social_url and social_url != url and validate_social_link_for_author(social_platform, social_url, author_name):
                profile.platforms[social_platform] = social_url
                protected_platforms.add(social_platform)
                print(f"[Protected LLM] {social_platform}: {social_url}")
            elif social_url and not validate_social_link_for_author(social_platform, social_url, author_name):
                print(f"[LLM Rejected] Invalid {social_platform} link: {social_url}")
        
        # 从内容提取额外链接（如果还没有足够的链接）
        if len(social_links) < 3:  # 如果LLM提取的链接不够
            extracted_links = extract_social_links_from_content(fetch_text(url, max_chars=10000))
            for social_platform, social_url in extracted_links.items():
                if social_platform not in profile.platforms:
                    profile.platforms[social_platform] = social_url
                    protected_platforms.add(social_platform)
                    print(f"[Protected HTML] {social_platform}: {social_url}")
    else:
        # 非个人网站：只有在平台未被保护时才更新
        for social_platform, social_url in social_links.items():
            if social_url and social_url != url and social_platform not in protected_platforms:
                update_platform_url(profile, social_platform, social_url, author_name)
    
    # 创建incoming profile并合并
    cleaned_aliases = clean_aliases(getattr(ext, 'aliases', []) or [], author_name)
    
    incoming = AuthorProfile(
        name=getattr(ext, 'name', '') or author_name,
        aliases=cleaned_aliases,
        platforms={}, ids={}, 
        homepage_url=personal_homepage,
        affiliation_current=getattr(ext, 'affiliation_current','') or None,
        emails=list(getattr(ext, 'emails', []) or []),
        interests=list(getattr(ext, 'interests', []) or []),
        selected_publications=list(getattr(ext, 'selected_publications', []) or []),
        confidence=0.4,
        notable_achievements=list(getattr(ext, 'notable_achievements', []) or []),
        social_impact=getattr(ext, 'social_impact', '') or None,
        career_stage=getattr(ext, 'career_stage', '') or None,
        overall_score=0.0
    )
    
    # 合并profiles，但不返回值因为profile是引用传递
    merged = merge_profiles(profile, incoming)
    # 更新profile的属性
    for attr in ['name', 'aliases', 'platforms', 'ids', 'homepage_url', 'affiliation_current', 
                 'emails', 'interests', 'selected_publications', 'notable_achievements', 
                 'social_impact', 'career_stage', 'confidence']:
        setattr(profile, attr, getattr(merged, attr))

def clean_aliases(raw_aliases: List[str], author_name: str) -> List[str]:
    """清理aliases，只保留真正的作者别名"""
    cleaned_aliases = []
    author_words = set(author_name.lower().split())
    
    for alias in raw_aliases:
        if alias and alias != author_name:
            alias_words = set(alias.lower().split())
            # 如果别名与作者名有重叠词汇，可能是真正的别名
            if len(alias_words & author_words) > 0 or len(alias.split()) <= 3:
                cleaned_aliases.append(alias)
    
    return cleaned_aliases[:5]  # 限制别名数量

def merge_profiles(base: AuthorProfile, incoming: AuthorProfile, keep_base_platforms: bool = False) -> AuthorProfile:
    """Merge two author profiles with trust ranking"""
    # Merge platforms and IDs
    for k, v in incoming.platforms.items():
        if not keep_base_platforms:
            base.platforms.setdefault(k, v)
    for k, v in incoming.ids.items():
        if not keep_base_platforms:
            base.ids.setdefault(k, v)
    
    # 合并homepage_url - 优先保留非平台URL的个人网站
    if incoming.homepage_url:
        if not base.homepage_url:
            base.homepage_url = incoming.homepage_url
        elif 'github.io' in incoming.homepage_url and 'github.io' not in base.homepage_url:
            # 个人域名优于github.io
            base.homepage_url = incoming.homepage_url
        elif 'github.io' in base.homepage_url and 'github.io' not in incoming.homepage_url:
            pass
    
    # Merge names and aliases
    if not base.name and incoming.name:
        if not keep_base_platforms:
            base.name = incoming.name
    # Add aliased to base
    for a in incoming.aliases:
        if a and a not in base.aliases:
            base.aliases.append(a)

    # Merge basic fields (prefer non-empty)
    if not base.affiliation_current and incoming.affiliation_current:
        base.affiliation_current = incoming.affiliation_current
    if not base.social_impact and incoming.social_impact:
        base.social_impact = incoming.social_impact
    if not base.career_stage and incoming.career_stage:
        base.career_stage = incoming.career_stage
        
    # Merge list fields with deduplication
    for e in incoming.emails:
        if e and e not in base.emails:
            base.emails.append(e)
    for i in incoming.interests:
        if i and i not in base.interests:
            base.interests.append(i)
    
    # Merge notable achievements
    if hasattr(incoming, 'notable_achievements') and incoming.notable_achievements:
        for achievement in incoming.notable_achievements:
            if achievement and achievement not in base.notable_achievements:
                base.notable_achievements.append(achievement)

    # Merge publications with deduplication
    def key(pub):
        return re.sub(r'\s+', ' ', (pub.get('title','') or '').strip().lower())

    seen = {key(p) for p in base.selected_publications}
    for p in incoming.selected_publications:
        if key(p) not in seen:
            base.selected_publications.append(p)
            seen.add(key(p))

    # Update confidence
    base.confidence = min(1.0, base.confidence + 0.1)
    return base

# ============================ MAIN DISCOVERY FUNCTIONS ============================

def _evaluate_single_candidate(
    candidate: ProfileCandidate, 
    first_author: str, 
    paper_title: str, 
    llm_sel: Any
) -> ProfileCandidate:
    """
    Evaluate a single candidate using two-stage LLM evaluation.
    
    Args:
        candidate: ProfileCandidate to evaluate
        first_author: First author name for context
        paper_title: Paper title for context
        llm_sel: LLM instance for evaluation
    
    Returns:
        Updated ProfileCandidate with should_fetch and reason set
    """
    # Trusted source from OpenReview: always fetch
    if candidate.trusted_source:
        candidate.should_fetch = True
        candidate.reason = "Trusted source from OpenReview"
    # 高分直接通过
    elif candidate.score >= 2:
        candidate.should_fetch = True
        candidate.reason = "High rule-based score"
    # 极低分直接丢弃
    elif candidate.score <= 0.25:
        candidate.should_fetch = False
        candidate.reason = "Low rule-based score"
    else:
        # 第一阶段：判断是否包含作者信息
        prompt_has_info = PROMPT_HAS_AUTHOR_INFO(first_author, candidate.title, candidate.url, candidate.snippet)
        try:
            r1 = llm.safe_structured(llm_sel, prompt_has_info, schemas.LLMSelectSpecHasAuthorInfo)
            has_author_info = bool(r1 and getattr(r1, 'has_author_info', False))
            
            if not has_author_info:
                candidate.should_fetch = False
                candidate.reason = "No author info detected"
            else:
                # 第二阶段：判断抓取价值
                prompt_relevance = PROMPT_PROFILE_RELEVANCE(first_author, paper_title, candidate.title, candidate.url, candidate.snippet)
                r2 = llm.safe_structured(llm_sel, prompt_relevance, schemas.LLMSelectSpecWithValue)
                candidate.should_fetch = bool(r2 and getattr(r2, 'should_fetch', False))
                candidate.reason = getattr(r2, 'reason', 'LLM evaluation')
        except Exception as e:
            # LLM失败时使用规则兜底
            candidate.should_fetch = candidate.score >= 0.5
            candidate.reason = f"LLM failed, rule fallback: {e}"
    
    return candidate


def _evaluate_candidates_concurrent(
    candidates: List[ProfileCandidate], 
    first_author: str, 
    paper_title: str, 
    llm_sel: Any, 
    picked: List[ProfileCandidate],
    max_workers: int = None
) -> None:
    """
    Evaluate multiple candidates concurrently using ThreadPoolExecutor.
    
    Args:
        candidates: List of ProfileCandidate objects to evaluate
        first_author: First author name for context
        paper_title: Paper title for context
        llm_sel: LLM instance for evaluation
        picked: List to append selected candidates to
        max_workers: Maximum number of concurrent threads (default: config.AUTHOR_DISCOVERY_MAX_WORKERS)
    """
    if not candidates:
        return
    
    # Dynamic concurrency: LLM evaluation is CPU-bound
    if max_workers is None:
        max_workers = get_llm_workers(len(candidates))
        print(f"[_evaluate_candidates_concurrent] Using {max_workers} workers for {len(candidates)} candidate evaluations")
    
    # Use ThreadPoolExecutor for concurrent evaluation
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all evaluation tasks
        future_to_candidate = {
            executor.submit(_evaluate_single_candidate, candidate, first_author, paper_title, llm_sel): candidate
            for candidate in candidates
        }
        
        # Collect results as they complete
        for future in as_completed(future_to_candidate):
            try:
                evaluated_candidate = future.result()
                if evaluated_candidate.should_fetch:
                    picked.append(evaluated_candidate)
            except Exception as e:
                candidate = future_to_candidate[future]
                if config.VERBOSE:
                    print(f"[author-discovery.concurrent] error for {candidate.url}: {e}")
                # On error, use rule-based fallback
                candidate.should_fetch = candidate.score >= 0.5
                candidate.reason = f"Concurrent evaluation failed, rule fallback: {e}"
                if candidate.should_fetch:
                    picked.append(candidate)


def search_openreview_profile(author_name: str, api_key: str = None) -> Optional[Dict[str, Any]]:
    """Search specifically for OpenReview profile and extract homepage if available
    Returns:
        Dict with 'openreview_url', 'homepage_url', and 'profile_content' if found,
        None if no OpenReview profile exists
    """
    print(f"\n{'='*80}")
    print(f"[OpenReview Search DEBUG] Searching for: {author_name}")
    print(f"{'='*80}")
    
    # ========== 方法1: 直接使用OpenReview API搜索 (推荐) ==========
    openreview_url = None
    try:
        print(f"\n🚀 Method 1: Direct OpenReview API search")
        
        # OpenReview API搜索endpoint
        api_search_url = f"https://api2.openreview.net/profiles/search"
        params = {
            'fullname': author_name,
            'es': 'true'  # 使用Elasticsearch提高匹配准确度
        }
        
        print(f"   Calling: {api_search_url}?fullname={author_name}")
        
        # 添加延迟避免429
        time.sleep(0.5)
        
        response = requests.get(
            api_search_url, 
            params=params,
            timeout=10,
            headers={'User-Agent': config.UA.get('User-Agent', 'Mozilla/5.0')}
        )
        
        print(f"   Response status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            profiles = data.get('profiles', [])
            
            print(f"   Found {len(profiles)} profile(s)")
            
            if profiles:
                # 使用第一个匹配的profile
                profile = profiles[0]
                profile_id = profile.get('id', '')
                
                if profile_id:
                    # 构造profile URL
                    openreview_url = f"https://openreview.net/profile?id={profile_id}"
                    print(f"   ✅ Found via API: {openreview_url}")
                    
                    # 显示匹配的profile信息用于验证
                    profile_name = profile.get('content', {}).get('names', [{}])[0]
                    if profile_name:
                        first = profile_name.get('first', '')
                        last = profile_name.get('last', '')
                        print(f"   Profile name: {first} {last}")
                else:
                    print(f"   ⚠️  Profile found but no ID")
            else:
                print(f"   ❌ No profiles found via API")
        
        elif response.status_code == 429:
            print(f"   ⚠️  API rate limit (429), falling back to search engine")
        else:
            print(f"   ⚠️  API error ({response.status_code}), falling back to search engine")
    
    except Exception as e:
        print(f"   ❌ API search failed: {e}")
        print(f"   Falling back to search engine method")
    
    # ========== 方法2: 搜索引擎回退 (仅当API失败时) ==========
    if not openreview_url:
        print(f"\n🔍 Method 2: Search engine fallback")
        
        openreview_queries = [
            f'{author_name} site:openreview.net/profile',
            f'{author_name} OpenReview profile',
            f'{author_name} site:openreview.net',
        ]
        
        serp = []
        all_results = []  # 用于debug显示所有结果
        
        for i, query in enumerate(openreview_queries, 1):
            print(f"\n   Query {i}/3: {query}")
            results = docker_utils.run_search(query, pages=1, k_per_query=3, search_engines=config.SEARXNG_ENGINES_OPENREVIEW)
            print(f"      → Found {len(results)} results")
            
            # 显示前3个结果用于debug
            for j, item in enumerate(results[:3], 1):
                url = item.get('url', '')
                title = (item.get('title', '') or '')[:60]
                all_results.append((query, url, title))
                print(f"      {j}. {title[:40]}")
                print(f"         URL: {url[:70]}")
            
            serp.extend(results)
        
        print(f"\n   📊 Total results collected: {len(serp)}")
        
        # 查找OpenReview profile
        for item in serp:
            url = item.get('url', '')
            if 'openreview.net/profile' in url.lower():
                openreview_url = url
                print(f"   ✅ Found via search: {url}")
                break
        
        if not openreview_url:
            print(f"\n   ❌ No profile found via search either")
            print(f"\n   📝 All URLs found (not matching 'openreview.net/profile'):")
            for query, url, title in all_results[:10]:  # 显示前10个
                print(f"      • {url[:60]} ({title[:35]})")
            if len(all_results) > 10:
                print(f"      ... and {len(all_results) - 10} more URLs")
    
    # ========== 如果两种方法都失败 ==========
    if not openreview_url:
        print(f"\n❌ NO OPENREVIEW PROFILE FOUND (tried both API and search)")
        print(f"\n💡 Possible reasons:")
        print(f"   1. Author hasn't created an OpenReview profile")
        print(f"   2. Author name spelling differs (try variations/aliases)")
        print(f"   3. Profile exists but not indexed/accessible")
        print(f"   4. API rate limit + search engine failure")
        print(f"{'='*80}\n")
        return None
    
    print(f"{'='*80}\n")
    
    try:
        homepage_url = None
        content = None
        try:
            profile_id = None
            if 'id=' in openreview_url:
                profile_id = openreview_url.split('id=')[1].split('&')[0]
            if profile_id:
                api_url = f'https://api2.openreview.net/profiles/{profile_id}'
                print(f"[OpenReview API] Fetching profile data from API: {api_url}")

                response = requests.get(api_url, timeout=10)
                if response.status_code == 200:
                    data = response.json()

                    if data and 'profiles' in data and data['profiles']:
                        profile_data = data['profiles'][0] if isinstance(data['profiles'], list) else data['profiles']
                        content_obj = profile_data.get('content', {})
                        homepage_url = None
                        homepage_url = profile_data.get('homepage') or profile_data.get('website')
                        if not homepage_url and content_obj:
                            homepage_url = (
                                content_obj.get('homepage') or content_obj.get('website') or content_obj.get('personal_website')
                            )
                        if not homepage_url and content_obj.get('gscholar'):
                            gscholar_url = content_obj.get('gscholar')
                            if gscholar_url and 'scholar.google' not in gscholar_url:
                                homepage_url = gscholar_url
                        if not homepage_url and content_obj.get('history'):
                            history = content_obj.get('history', [])
                            if isinstance(history, list) and history:
                                latest = history[0] if history else {}
                                if isinstance(latest, dict):
                                    homepage_url = latest.get('homepage') or latest.get('website')
                        
                        if homepage_url:
                            homepage_url = homepage_url.strip()
                            if homepage_url and not homepage_url.startswith('http'):
                                homepage_url = 'https://' + homepage_url
                            print(f"[OpenReview API] Found homepage in API: {homepage_url}")
                        else:
                            print(f"[OpenReview API] No homepage found in API response")
                            print(f"[OpenReview API] Available profile_data keys: {list(profile_data.keys())[:10]}")
                            print(f"[OpenReview API] Available content fields: {list(content_obj.keys())}")

                        content = json.dumps(profile_data, ensure_ascii=False)
                else:
                    print(f"[OpenReview API] API returned status {response.status_code}")
        except Exception as e:
            print(f"[OpenReview API] Error fetching profile data: {e}")
        if not homepage_url:
            print(f"[OpenReview API] Fetching HTML content for BeautifulSoup + regex extraction...")
            try:
                response = requests.get(openreview_url, timeout=10, headers={'User-Agent': config.UA.get('User-Agent', '')})
                html_content = response.text
                content = html_content if not content else content
                soup = BeautifulSoup(html_content, 'html.parser')
                all_links = soup.find_all('a', href=True)
                external_links = [link['href'] for link in all_links if link['href'].startswith('http') and 'openreview.net' not in link['href']]
                print(f"[OpenReview API] Found {len(all_links)} total links, {len(external_links)} external links")

                for link in soup.find_all('a', href=True):
                    link_text = link.get_text().strip()
                    href = link['href']

                    if any(keyword in link_text.lower() for keyword in ['homepage', 'website', 'personal site', 'personal page', 'home']):
                        homepage_url = href
                        print(f"[OpenReview API] Found homepage in link text '{link_text}': {homepage_url}")
                        break
                
                if not homepage_url:
                    for link in soup.find_all('a', href=True):
                        href = link['href']
                        if 'github.io' in href or ('.edu/~' in href and 'openreview.net' not in href):
                            homepage_url = href
                            print(f"[OpenReview API] Found homepage in link href: {homepage_url}")
                            break
                if not homepage_url and external_links:
                    for links in external_links[:5]:
                        if any(platform in links for platform in ['scholar.google', 'semanticscholar', 'dblp', 'linkedin', 'twitter', 'x.com']):
                            continue
                        if any(platform in links for platform in ['github.io', '.me', 'personal', author_name.lower().replace(' ', '')]):
                            homepage_url = links
                            print(f"[OpenReview API] Found homepage in external link: {homepage_url}")
                            break
                if not homepage_url and ('homepage' in html_content.lower() or 'website' in html_content.lower()):
                    homepage_patterns = [
                        r'(?:homepage|website|personal\s*site\s*page)[:\s]*<a[^>]*href=["\']([^"\']+)["\']',
                        r'(?:homepage|website)[:\s]*(http?://[^\s<>"]+)',
                        r'(https?://[^\s]+\.github.io[^\s<>"]*)'
                        r'(https?://[^\s]+\.edu/~[^\s<>"]+)'
                    ]
                    for pattern in homepage_patterns:
                        matches = re.findall(pattern, html_content, re.IGNORECASE)
                        if matches:
                            for match in matches:
                                if isinstance(match, str) and 'openreview.net' not in match and match.startswith('http'):
                                    homepage_url = match
                                    print(f"[OpenReview API] Found homepage in HTML: {homepage_url}")
                                    break
                        if not homepage_url:
                            break
                
                if not homepage_url:
                    print(f"[OpenReview API] No homepage found in HTML")
            except Exception as e:
                print(f"[OpenReview API] Error fetching HTML content: {e}")

        return {
            'openreview_url': openreview_url,
            'homepage_url': homepage_url,
            'content': content or ''
        }
    except Exception as e:
        print(f"[OpenReview API] Error: {e}")
        return None

def discover_author_profile(first_author: str, paper_title: str, aliases: List[str] = None,
                         k_queries: int = 40, author_id: str = None, api_key: str = None) -> AuthorProfile:
    """Main function to discover comprehensive author profile with OpenReview priority"""
    aliases = aliases or []
    
    # Phase 0: MANDATORY OpenReview Check - If no OpenReview, skip the candidate entirely
    # 添加随机延迟避免并发请求同时触发限流
    import random
    delay = random.uniform(0.5, 2.0)  # 0.5-2秒随机延迟
    time.sleep(delay)
    
    print(f"[Author Discovery] Phase 0: Checking OpenReview for {first_author}...")
    openreview_result = search_openreview_profile(first_author, api_key=api_key)
    
    if not openreview_result:
        print(f"[Author Discovery] ❌ No OpenReview profile found for {first_author}, SKIPPING CANDIDATE")
        return None  # STRICT: No OpenReview = Skip candidate
    
    print(f"[Author Discovery] ✅ Found OpenReview profile: {openreview_result['openreview_url']}")
    
    # Initialize search results with OpenReview
    serp = []
    
    # Always add OpenReview profile as the primary source
    serp.append({
        'url': openreview_result['openreview_url'],
        'title': f'{first_author} - OpenReview Profile',
        'snippet': 'OpenReview academic profile (Primary Source)'
    })
    
    # Phase 1: Homepage handling - Use from OpenReview if available, otherwise search once
    has_homepage_from_openreview = bool(openreview_result.get('homepage_url'))
    
    if has_homepage_from_openreview:
        print(f"[Author Discovery] ✅ Homepage found in OpenReview: {openreview_result['homepage_url']}")
        print(f"[Author Discovery] 🚀 OPTIMIZATION: Skipping homepage search (using OpenReview link directly)")
        # Add homepage from OpenReview as highest priority
        # Mark it as trusted (from OpenReview) to skip validation
        serp.insert(0, {  # Insert at beginning for highest priority
            'url': openreview_result['homepage_url'],
            'title': f'{first_author} Homepage',
            'snippet': 'Personal homepage (from OpenReview profile)',
            'trusted_source': True  # ← 标记为可信来源，跳过验证
        })
        # NO NEED to search for additional homepages - SAVES 30 seconds!
    else:
        timeout_seconds = getattr(config, 'HOMEPAGE_SEARCH_TIMEOUT', 30)
        print(f"[Author Discovery] ⚠️ No homepage in OpenReview, starting OPTIMIZED search (max {timeout_seconds}s)...")
        print(f"[Author Discovery] 🎯 Using 3 high-quality strategies (reduced from 14 queries)")
        
        # Multiple search strategies to run concurrently - OPTIMIZED for high quality
        # Only keep the most effective queries that actually find homepages
        homepage_search_strategies = [
            (f'"{first_author}" site:github.io', 1, 5),      # Strategy 1: GitHub.io (HIGHEST success rate ~40%)
            (f'"{first_author}" personal homepage OR website', 1, 5),  # Strategy 2: Direct homepage (~30%)
            (f'{first_author} site:edu OR site:ac.uk homepage', 1, 3),  # Strategy 3: University pages (~20%)
        ]
        
        start_time = time.time()
        all_homepage_results = []
        
        try:
            # Calculate dynamic workers based on CPU resources
            num_strategies = len(homepage_search_strategies)
            max_workers = get_optimal_workers(num_strategies, 'io_bound')
            # Cap at number of strategies
            max_workers = min(max_workers, num_strategies, 6)
            
            print(f"[Homepage Search] Launching {num_strategies} strategies with {max_workers} workers (timeout: {timeout_seconds}s)")
            
            # Execute all strategies concurrently
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                # Submit all search tasks
                future_to_strategy = {}
                for idx, (query, pages, k) in enumerate(homepage_search_strategies):
                    future = executor.submit(_run_search_terms, [query], pages=pages, k_per_query=k, search_engines=config.SEARXNG_ENGINES_HOMEPAGE)
                    future_to_strategy[future] = (idx + 1, query)
                
                # Collect results with global timeout
                completed_count = 0
                for future in as_completed(future_to_strategy.keys(), timeout=timeout_seconds):
                    strategy_num, query = future_to_strategy[future]
                    elapsed = time.time() - start_time
                    
                    try:
                        res = future.result(timeout=1)  # Quick timeout for already-completed future
                        completed_count += 1
                        
                        if res:
                            all_homepage_results.extend(res)
                            print(f"[Homepage Search] Strategy {strategy_num} found {len(res)} results in {elapsed:.1f}s")
                        else:
                            print(f"[Homepage Search] Strategy {strategy_num} found nothing in {elapsed:.1f}s")
                            
                    except Exception as e:
                        print(f"[Homepage Search] Strategy {strategy_num} error: {e}")
                        completed_count += 1
                
                print(f"[Homepage Search] Completed {completed_count}/{num_strategies} strategies")
                
        except TimeoutError:
            # Global timeout reached
            elapsed = time.time() - start_time
            print(f"[Homepage Search] Global timeout after {elapsed:.1f}s, {len(all_homepage_results)} results collected")
            # Cancel remaining futures
            for future in future_to_strategy.keys():
                future.cancel()
                
        except Exception as e:
            print(f"[Author Discovery] Homepage search failed: {e}, proceeding without homepage")
        
        # Add all found results to serp
        if all_homepage_results:
            serp.extend(all_homepage_results)
            elapsed = time.time() - start_time
            print(f"[Author Discovery] Found {len(all_homepage_results)} homepage candidates in {elapsed:.1f}s total")
        else:
            elapsed = time.time() - start_time
            print(f"[Author Discovery] No homepage found after {elapsed:.1f}s search")
    
    # Phase 2: REMOVED - We don't need additional profiles anymore
    # Just OpenReview (+ optional homepage) is enough
    print(f"[Author Discovery] Proceeding with OpenReview{' + Homepage' if has_homepage_from_openreview or len(serp) > 1 else ' only'}")

    print(f'[Author Data Discovery] after search engine found {len(serp)} urls')
    # Deduplicate URLs
    seen, items = set(), []
    for r in serp:
        u = r.get('url') or ''
        if u and u not in seen:
            seen.add(u)
            items.append(r)

    print(f'[Author Data Discovery] after deduplicate urls found {len(items)} urls')

    # Phase 2: Score and filter candidates
    cand: List[ProfileCandidate] = []
    for it in items:
        sc = score_candidate(it, first_author, paper_title)
        cand.append(ProfileCandidate(
            url=it.get('url',''), 
            title=it.get('title',''),
            snippet=it.get('snippet',''), 
            score=sc,
            trusted_source=it.get('trusted_source', False)  # Pass through trusted flag
        ))
        
    print(f'[Author Data Discovery] after score and filter candidates found {len(cand)} urls')

    # Phase 3: 两阶段LLM评估 (并发处理)
    llm_sel = llm.get_llm("select", temperature=0.2, api_key=api_key)
    picked: List[ProfileCandidate] = []
    
    # 使用并发处理评估候选者
    _evaluate_candidates_concurrent(cand, first_author, paper_title, llm_sel, picked)
    
    print(f'[Author Data Discovery] after evaluate candidates urls found {len(picked)} urls')

    # Phase 4: Initialize base profile and fetch papers from Semantic Scholar
    profile = AuthorProfile(
        name=first_author, aliases=aliases[:], platforms={}, ids={},
        homepage_url=None, affiliation_current=None, emails=[],
        interests=[], selected_publications=[], confidence=0.3,
        notable_achievements=[], social_impact=None, career_stage=None, overall_score=0.0
    )
    
    # 如果提供了author_id，直接从Semantic Scholar获取论文和profile信息
    if author_id:
        try:
            from semantic_paper_search import SemanticScholarClient
            s2_client = SemanticScholarClient()
            
            # 获取作者的详细信息
            s2_profile = s2_client.get_author_profile_info(author_id)
            if s2_profile:
                if s2_profile.get('affiliations'):
                    profile.affiliation_current = s2_profile['affiliations'][0].get('name', '') if s2_profile['affiliations'] else None
                if s2_profile.get('aliases'):
                    profile.aliases.extend([alias for alias in s2_profile['aliases'] if alias not in profile.aliases])
                
                # 设置社交影响力信息
                h_index = s2_profile.get('hIndex', 0)
                citation_count = s2_profile.get('citationCount', 0)
                paper_count = s2_profile.get('paperCount', 0)
                
                if h_index > 0 or citation_count > 0:
                    profile.social_impact = f"h-index: {h_index}, citations: {citation_count}, papers: {paper_count}"
            
            # 获取作者的论文
            papers = s2_client.get_author_papers(author_id, limit=50, sort="citationCount")
            if papers:
                profile.selected_publications = [
                    {
                        'title': paper['title'],
                        'year': paper.get('year'),
                        'venue': paper.get('venue', ''),
                        'url': paper.get('url', ''),
                        'citations': paper.get('citationCount', 0)
                    }
                    for paper in papers[:20]  # 限制为前20篇
                ]
                
                print(f"[S2 Integration] Added {len(profile.selected_publications)} papers from Semantic Scholar")
            
        except Exception as e:
            print(f"[S2 Integration] Failed to fetch from Semantic Scholar: {e}")
    
    
    # 记录从个人网站提取的高质量平台链接，保护它们不被覆盖
    protected_platforms = set()

    # Phase 5: Process candidates using modular approach
    llm_ext = llm.get_llm("extract", temperature=0.1, api_key=api_key)
    
    # 按优先级排序候选者：个人网站优先
    def get_candidate_priority(candidate):
        url = candidate.url.lower()
        if 'github.io' in url or any(indicator in url for indicator in ['personal', 'homepage']):
            return 1  # 最高优先级：个人网站
        elif any(platform in url for platform in ['x.com', 'twitter.com', 'linkedin.com','orcid.org', 'openreview.net']):
            return 2  # 高优先级：权威学术平台
        elif any(platform in url for platform in ['researchgate.net', 'github.com', 'huggingface.co','scholar.google.', 'semanticscholar.org']):
            return 3  # 中高优先级：学术搜索平台
        else:
            return 4  # 低优先级：其他平台
    
    picked_sorted = sorted(picked[:20], key=get_candidate_priority)
    
    # Phase 5: 分离homepage和non-homepage候选者
    homepage_candidates = []
    non_homepage_candidates = []
    openreview_candidate = None  # Special handling for OpenReview
    
    print(f'[Author Data Discovery] Processing {len(picked_sorted)} this author: {first_author}')
    for c in picked_sorted:
        # 5.1: Extract IDs from URL (fast path)
        ids = extract_ids_from_url(c.url)
        for k, v in ids.items():
            profile.ids.setdefault(k, v)

        # 5.2: 确定是否为个人网站
        host = domain_of(c.url)
        platform_type = determine_platform_type(c.url, host)
        
        # Special handling for OpenReview - always process it
        if platform_type == 'openreview':
            openreview_candidate = c
            print(f"[Author Data Discovery] Found OpenReview candidate: {c.url}")
        elif platform_type == 'homepage' or 'github.io' in c.url:
            homepage_candidates.append(c)
        else:
            non_homepage_candidates.append(c)
            
    if len(homepage_candidates) == 0:
        print(f"[Author Data Discovery] No homepage candidates found - will use OpenReview profile only")
    
    print(f"[Author Data Discovery] Separated candidates: {len(homepage_candidates)} homepage, {len(non_homepage_candidates)} non-homepage")
    
    # Phase 5: 同时并行处理homepage和non-homepage候选者
    non_homepage_profiles = []
    homepage_processed = False
    homepage_profile = None
    
    def process_non_homepage_candidate(candidate):
        """处理单个non-homepage候选者并返回profile"""
        temp_profile = AuthorProfile(
            name=first_author,
            aliases=[],
            platforms={},
            ids={},
            homepage_url=None,
            affiliation_current=None,
            emails=[],
            interests=[],
            selected_publications=[],
            confidence=0.0
        )
        
        success = process_regular_candidate(
            candidate, first_author, temp_profile, protected_platforms, llm_ext
        )
        
        if success:
            print(f"[Author Data Discovery] Successfully processed non-homepage: {candidate.url}")
            return temp_profile
        return None
    
    def process_homepage_candidate_single(candidate):
        """处理单个homepage候选者并返回结果"""
        nonlocal homepage_processed, homepage_profile
        
        if homepage_processed:
            return False
            
        print(f"[Author Data Discovery] Trying homepage candidate: {candidate.url}")
        success = process_homepage_candidate(
            candidate, first_author, paper_title, profile, protected_platforms, llm_ext
        )
        
        if success:
            homepage_processed = True
            homepage_profile = profile  # 使用主profile作为homepage profile
            print(f"[Author Data Discovery] Successfully processed homepage: {candidate.url}")
            return True
        else:
            print(f"[Author Data Discovery] Failed to process homepage candidate: {candidate.url}")
            return False
    
    def process_homepage_candidates():
        """处理homepage候选者，直到找到一个成功的"""
        nonlocal homepage_processed, homepage_profile
        
        if not homepage_candidates:
            return
            
        print(f"[Author Data Discovery] Processing {len(homepage_candidates)} homepage candidates sequentially...")
        
        for i, c in enumerate(homepage_candidates):
            if homepage_processed:
                break
                
            print(f"[Author Data Discovery] Trying homepage candidate: {c.url} {i+1}/{len(homepage_candidates)}")
            success = process_homepage_candidate(
                c, first_author, paper_title, profile, protected_platforms, llm_ext
            )
            
            if success:
                homepage_processed = True
                homepage_profile = profile  # 使用主profile作为homepage profile
                print(f"[Author Data Discovery] Successfully processed homepage: {c.url}")
                break
            print(f"[Author Data Discovery] Failed to process homepage candidate: Start to process next one {i+1}/{len(homepage_candidates)}")
    
    # 同时启动homepage和non-homepage处理
    # homepage: 1个线程顺序处理
    # OpenReview: 必须处理
    # non-homepage: 多个线程并行处理
    # Dynamic concurrency: homepage processing is mixed (IO+CPU)
    # Homepage: 1 thread sequential, OpenReview: 1, non-homepage: multiple
    total_tasks = len(non_homepage_candidates) + 1  # +1 for homepage/OpenReview
    processing_max_workers = get_optimal_workers(total_tasks, 'mixed')
    processing_max_workers = min(processing_max_workers, 12)  # Cap at 12 for safety
    print(f"[Author Data Discovery] Using {processing_max_workers} workers for profile processing")
    
    with ThreadPoolExecutor(max_workers=processing_max_workers) as executor:
        futures = []
        
        # 启动homepage处理任务 (多个线程并行处理单个候选者)
        if homepage_candidates:
            homepage_future = executor.submit(process_homepage_candidates)
            futures.append(("homepage", homepage_future))
        
        # Process OpenReview if no homepage found
        if openreview_candidate and not homepage_candidates:
            print(f"[Author Data Discovery] Processing OpenReview as primary source...")
            openreview_future = executor.submit(process_non_homepage_candidate, openreview_candidate)
            futures.append(("openreview", openreview_future))
        
        # # 启动non-homepage处理任务 (多个线程并行)
        # if non_homepage_candidates:
        #     print(f"[Author Data Discovery] Processing {len(non_homepage_candidates)} non-homepage candidates in parallel...")
        #     for i, candidate in enumerate(non_homepage_candidates[:8]):  # 限制最多8个
        #         future = executor.submit(process_non_homepage_candidate, candidate)
        #         futures.append(("non_homepage", future))
        
        # 收集所有结果
        for task_type, future in futures:
            try:
                if task_type == "homepage":
                    future.result()
                elif task_type == "openreview":
                    result_profile = future.result()
                    if result_profile:
                        # Merge OpenReview data into main profile
                        profile = merge_profiles(profile, result_profile)
                        print("[Author Data Discovery] OpenReview profile merged into main profile")
                elif task_type == "non_homepage":
                    result_profile = future.result()
                    if result_profile:
                        non_homepage_profiles.append(result_profile)
            except Exception as e:
                print(f"[Author Data Discovery] {task_type} processing failed: {e}")
    
    print(f"[Author Data Discovery] Successfully processed {len(non_homepage_profiles)} non-homepage profiles")
    
    # Phase 6: Check if we have enough information (OpenReview is sufficient)
    if not homepage_processed:
        print("[Author Data Discovery] No personal homepage found, using OpenReview profile only")
    
    # Phase 5.3: 合并所有non-homepage profiles
    if non_homepage_profiles:
        print(f"[Author Data Discovery] Merging {len(non_homepage_profiles)} non-homepage profiles...")
        merged_non_homepage = non_homepage_profiles[0]
        for other_profile in non_homepage_profiles[1:]:
            merged_non_homepage = merge_profiles(merged_non_homepage, other_profile)
        
        # 将合并后的non-homepage profile合并到主profile 保留base的platforms
        profile = merge_profiles(profile, merged_non_homepage, keep_base_platforms=True)
        print(f"[Author Data Discovery] Successfully merged non-homepage profiles")

    # 最终档案精炼
    profile = refine_author_profile(profile, first_author)
    
    # 计算综合评分
    profile.overall_score = calculate_overall_score(profile)
    
    return profile

# ============================ S2 TOP PAPERS SELECTION ============================

def select_top3_recent_or_top_cited_papers(author_id: str, recent_years: int = 2) -> List[Dict[str, Any]]:
    """Return up to top-3 papers prioritizing recent years, otherwise top-cited."""
    try:
        from semantic_paper_search import SemanticScholarClient
        s2_client = SemanticScholarClient()
        # Fetch more than needed to allow filtering
        papers = s2_client.get_author_papers(author_id, limit=50, sort="citationCount")
        if not papers:
            return []

        import datetime
        current_year = datetime.datetime.utcnow().year
        recent_cutoff = current_year - max(1, recent_years)

        def to_pub(p):
            return {
                'title': p.get('title', ''),
                'year': p.get('year'),
                'venue': p.get('venue', ''),
                'url': p.get('url', ''),
                'citations': p.get('citationCount', 0)
            }

        pubs = [to_pub(p) for p in papers]
        recent_pubs = [p for p in pubs if isinstance(p.get('year'), int) and p['year'] >= recent_cutoff]
        # Sort recents by citations desc
        recent_pubs.sort(key=lambda x: x.get('citations', 0), reverse=True)
        top: List[Dict[str, Any]] = recent_pubs[:3]

        if len(top) < 3:
            # Fill remaining with global top-cited (excluding already chosen)
            remaining = 3 - len(top)
            chosen_titles = {p['title'] for p in top}
            others = [p for p in pubs if p['title'] not in chosen_titles]
            others.sort(key=lambda x: x.get('citations', 0), reverse=True)
            top.extend(others[:remaining])

        return top[:3]
    except Exception as e:
        print(f"[S2 Top3] Failed to select top papers: {e}")
        return []

# ============================ SCORING AGENT (7 DIMENSIONS) ============================

def evaluate_profile_7d(profile: AuthorProfile, top_pubs: List[Dict[str, Any]], api_key: str = None) -> schemas.EvaluationResult:
    """LLM-based 7-dimension evaluation with rule-based fallback."""
    try:
        # Prepare an evidence context
        context = {
            'name': profile.name,
            'affiliation': profile.affiliation_current,
            'emails': profile.emails,
            'interests': profile.interests,
            'notable': profile.notable_achievements,
            'social_impact': profile.social_impact,
            'career_stage': profile.career_stage,
            'platforms': profile.platforms,
            'top_pubs': top_pubs,
        }

        def fmt_pub(p):
            return f"{p.get('title','')} ({p.get('venue','')}, {p.get('year','?')}) citations={p.get('citations',0)}"

        pubs_text = "\n".join(["- " + fmt_pub(p) for p in top_pubs])
        notable_text = "; ".join(profile.notable_achievements)
        interests_text = ", ".join(profile.interests)
        impact_text = profile.social_impact or ""

        prompt = f"""
You are evaluating a candidate across seven dimensions. For each dimension, assign an integer score from 1 to 5 and provide 1–2 sentence justification.

Candidate:
- Name: {profile.name}
- Affiliation: {profile.affiliation_current}
- Interests: {interests_text}
- Notable: {notable_text}
- Social Impact: {impact_text}
- Career Stage: {profile.career_stage}
- Platforms: {profile.platforms}
- Top Publications:\n{pubs_text}

Return STRICT JSON with key "items": a list of 7 objects each with keys: dimension, score, justification.
Dimensions (in this exact order):
1) Academic Background
2) Research Output
3) Research Alignment
4) Technical Skills
5) Recognition & Impact
6) Communication & Collaboration
7) Initiative & Independence
"""
        llm_eval = llm.get_llm("extract", temperature=0.0, api_key=api_key)
        spec = schemas.LLMEvaluationResultSpec
        result = llm.safe_structured(llm_eval, prompt, spec)
        items = []
        if result and getattr(result, 'items', None):
            for it in result.items:
                try:
                    items.append(schemas.EvaluationItem(
                        dimension=getattr(it, 'dimension', ''),
                        score=int(getattr(it, 'score', 0)),
                        justification=getattr(it, 'justification', '')
                    ))
                except Exception:
                    continue
        # Fallback if LLM returned nothing
        if len(items) != 7:
            items = rule_based_evaluation_fallback(profile, top_pubs)
        radar = {it.dimension: it.score for it in items}
        
        # 计算加权总分 - Research Alignment权重 × 3
        dimension_weights = {
            "Academic Background": 1.0,
            "Research Output": 1.0,
            "Research Alignment": 3.0,  # 🎯 提高研究匹配度权重
            "Technical Skills": 1.0,
            "Recognition & Impact": 1.0,
            "Communication & Collaboration": 1.0,
            "Initiative & Independence": 1.0
        }
        
        # 加权求和
        weighted_sum = sum(
            it.score * dimension_weights.get(it.dimension, 1.0) 
            for it in items
        )
        
        # 🔧 归一化到35分：保持UI显示一致性
        # 当前最大值 = 6×5 + 1×5×3 = 45分
        # 归一化公式：(weighted_sum / 45) * 35
        max_weighted_score = sum(5 * w for w in dimension_weights.values())  # 理论最大值
        total = int((weighted_sum / max_weighted_score) * 35)  # 归一化到35分
        
        details = {it.dimension: f"{it.score}/5 - {it.justification}" for it in items}
        return schemas.EvaluationResult(items=items, radar=radar, total_score=total, details=details)
    except Exception as e:
        print(f"[Eval 7D] LLM evaluation failed: {e}")
        items = rule_based_evaluation_fallback(profile, top_pubs)
        radar = {it.dimension: it.score for it in items}
        
        # 计算加权总分 - Research Alignment权重 × 3 (与上面保持一致)
        dimension_weights = {
            "Academic Background": 1.0,
            "Research Output": 1.0,
            "Research Alignment": 3.0,  # 🎯 提高研究匹配度权重
            "Technical Skills": 1.0,
            "Recognition & Impact": 1.0,
            "Communication & Collaboration": 1.0,
            "Initiative & Independence": 1.0
        }
        
        # 加权求和
        weighted_sum = sum(
            it.score * dimension_weights.get(it.dimension, 1.0) 
            for it in items
        )
        
        # 🔧 归一化到35分：保持UI显示一致性
        # 当前最大值 = 6×5 + 1×5×3 = 45分
        # 归一化公式：(weighted_sum / 45) * 35
        max_weighted_score = sum(5 * w for w in dimension_weights.values())  # 理论最大值
        total = int((weighted_sum / max_weighted_score) * 35)  # 归一化到35分
        
        details = {it.dimension: f"{it.score}/5 - {it.justification}" for it in items}
        return schemas.EvaluationResult(items=items, radar=radar, total_score=total, details=details)


def rule_based_evaluation_fallback(profile: AuthorProfile, top_pubs: List[Dict[str, Any]]) -> List[schemas.EvaluationItem]:
    """Simple heuristic scoring as a safety net."""
    def clamp(x):
        return max(1, min(5, x))

    # Academic Background
    bg = 3
    if profile.affiliation_current:
        aff = profile.affiliation_current.lower()
        if any(k in aff for k in ['stanford', 'mit', 'berkeley', 'cmu', 'oxford', 'cambridge', 'tsinghua', 'pku']):
            bg = 5
        elif any(k in aff for k in ['university', 'institute']):
            bg = 4

    # Research Output
    out = 2
    num_pubs = len(top_pubs)
    high_cit = sum(1 for p in top_pubs if p.get('citations', 0) >= 100)
    if num_pubs >= 3:
        out = 4 if high_cit >= 1 else 3

    # Alignment
    align = 3
    interests = ' '.join(profile.interests).lower()
    if any(k in interests for k in ['social simulation', 'multi-agent', 'agent', 'llm', 'hci', 'social computing']):
        align = 5

    # Technical Skills
    tech = 3
    if 'github' in profile.platforms:
        tech += 1
    if any('code' in (p.get('title','').lower()) for p in top_pubs):
        tech += 1
    tech = clamp(tech)

    # Recognition & Impact
    rec = 2
    if profile.notable_achievements:
        rec = 4
        if any('fellow' in a.lower() or 'best paper' in a.lower() for a in profile.notable_achievements):
            rec = 5
    if profile.social_impact and any(x in profile.social_impact.lower() for x in ['h-index', 'citation']):
        rec = max(rec, 4)

    # Communication & Collaboration
    comm = 3
    if any(k in interests for k in ['hci', 'user study']):
        comm = 4

    # Initiative & Independence
    initv = 3
    if profile.homepage_url:
        initv = 4
        if any('founder' in a.lower() or 'lead' in a.lower() for a in profile.notable_achievements):
            initv = 5

    ordered = [
        ("Academic Background", bg, "Heuristic based on affiliation reputation."),
        ("Research Output", out, "Heuristic based on top publications and citations."),
        ("Research Alignment", align, "Heuristic based on interests overlap with focus."),
        ("Technical Skills", tech, "Heuristic using GitHub presence and project hints."),
        ("Recognition & Impact", rec, "Heuristic using notable achievements and metrics."),
        ("Communication & Collaboration", comm, "Heuristic proxy via HCI/teams signals."),
        ("Initiative & Independence", initv, "Heuristic based on homepage and leadership hints."),
    ]
    return [schemas.EvaluationItem(dimension=d, score=clamp(s), justification=j) for d, s, j in ordered]

# ============================ CANDIDATE OVERVIEW BUILDER ============================

def build_candidate_overview_lightweight(profile: AuthorProfile, eval_result: schemas.EvaluationResult, top_pubs: List[Dict[str, Any]], 
                                       trigger_paper_title: str = None, trigger_paper_url: str = None) -> schemas.CandidateOverview:
    """构建轻量级候选人概览 - 借鉴Targeted Search的简化模式，避免复杂LLM提取"""
    print(f"[Lightweight Mode] Building candidate overview for {profile.name}")
    
    # 基础信息（不依赖LLM）
    profiles_display: Dict[str, str] = {}
    if profile.homepage_url:
        profiles_display["Homepage"] = profile.homepage_url
    if 'scholar' in profile.platforms:
        profiles_display["Google Scholar"] = profile.platforms['scholar']
    if 'twitter' in profile.platforms:
        profiles_display["X (Twitter)"] = profile.platforms['twitter']
    if 'openreview' in profile.platforms:
        profiles_display["OpenReview"] = profile.platforms['openreview']
    if 'linkedin' in profile.platforms:
        profiles_display["LinkedIn"] = profile.platforms['linkedin']
    if 'github' in profile.platforms:
        profiles_display["GitHub"] = profile.platforms['github']

    # 简化的论文信息提取
    publication_overview_list = []
    rep_papers: List[schemas.RepresentativePaper] = []
    if top_pubs:
        publication_overview_list = [
            p.get('title', '').strip() for p in top_pubs[:5] 
            if isinstance(p, dict) and p.get('title', '').strip()
        ]
        # 简化代表作
        for p in top_pubs[:3]:
            if isinstance(p, dict) and p.get('title'):
                rep_papers.append(schemas.RepresentativePaper(
                    title=p.get('title',''),
                    venue=p.get('venue',''),
                    year=p.get('year'),
                    type="Conference Paper",  # 简化分类
                    links=p.get('url','')
                ))
    
    # 使用已有的基础信息
    research_focus = profile.interests[:6] if profile.interests else []
    research_keywords = profile.interests[:8] if profile.interests else []
    honors_list = list(profile.notable_achievements[:3]) if profile.notable_achievements else []
    
    # 简化的高光信息
    highlights = []
    if profile.social_impact:
        highlights.append(f"Impact: {profile.social_impact}")
    if profile.notable_achievements:
        highlights.extend(profile.notable_achievements[:2])
    
    # 构建轻量级概览
    overview = schemas.CandidateOverview(
        name=profile.name,
        email=profile.emails[0] if profile.emails else "",
        current_role_affiliation=profile.affiliation_current or "",
        current_status="",  # 轻量模式不提取详细状态
        research_keywords=research_keywords,
        research_focus=research_focus,
        profiles=profiles_display,
        publication_overview=publication_overview_list,
        top_tier_hits=[f"{p.get('venue', 'arXiv')} {p.get('year','')}" for p in top_pubs[:5]],
        honors_grants=honors_list,
        service_talks=[],  # 轻量模式暂不提取
        open_source_projects=["GitHub projects available" if 'github' in profile.platforms else ""],
        representative_papers=rep_papers,
        trigger_paper_title=trigger_paper_title or "",
        trigger_paper_url=trigger_paper_url or "",
        highlights=highlights,
        radar=eval_result.radar,
        total_score=eval_result.total_score,
        detailed_scores=eval_result.details
    )
    
    print(f"[Lightweight Mode] ✅ Successfully built overview with basic fields")
    return overview

def build_candidate_overview(profile: AuthorProfile, eval_result: schemas.EvaluationResult, top_pubs: List[Dict[str, Any]], 
                           trigger_paper_title: str = None, trigger_paper_url: str = None) -> schemas.CandidateOverview:
    """Assemble a candidate overview with comprehensive researcher profile data."""
    # Profiles mapping with friendly keys
    profiles_display: Dict[str, str] = {}
    if profile.homepage_url:
        profiles_display["Homepage"] = profile.homepage_url
    if 'scholar' in profile.platforms:
        profiles_display["Google Scholar"] = profile.platforms['scholar']
    if 'twitter' in profile.platforms:
        profiles_display["X (Twitter)"] = profile.platforms['twitter']
    if 'openreview' in profile.platforms:
        profiles_display["OpenReview"] = profile.platforms['openreview']
    if 'linkedin' in profile.platforms:
        profiles_display["LinkedIn"] = profile.platforms['linkedin']
    if 'github' in profile.platforms:
        profiles_display["GitHub"] = profile.platforms['github']

    # Representative papers: prefer homepage extraction, fallback to S2/top_pubs
    rep_papers: List[schemas.RepresentativePaper] = []
    rep_from_homepage = getattr(profile, '_homepage_rep_papers', None)
    if rep_from_homepage and getattr(rep_from_homepage, 'papers', None):
        for p in list(rep_from_homepage.papers)[:3]:
            try:
                rep_papers.append(p)
            except Exception:
                continue
    if not rep_papers:
        for p in top_pubs[:3]:
            rep_papers.append(schemas.RepresentativePaper(
                title=p.get('title',''),
                venue=p.get('venue','') or "",
                year=p.get('year'),
                type=("Preprint" if (p.get('venue','').lower() in ['arxiv']) else ("Journal Article" if any(v in (p.get('venue','')).lower() for v in ['nature','science']) else "Conference Paper")),
                links=p.get('url','')
            ))

    # Combine homepage insights if available
    insights = getattr(profile, '_homepage_insights', None)

    research_focus_from_insights = list(getattr(insights, 'research_focus', []) or []) if insights else []
    research_keywords_list = list(getattr(insights, 'research_keywords', []) or []) if insights else []
    # Fallback to profile.interests if insights empty
    if not research_focus_from_insights and profile.interests:
        research_focus_from_insights = profile.interests[:8]
    if not research_keywords_list and profile.interests:
        research_keywords_list = profile.interests[:6]

    # Lists for overview fields - 添加调试信息
    research_keywords_list_out = research_keywords_list[:]
    
    # Publication Overview 诊断
    print(f"[Publication Overview] top_pubs length: {len(top_pubs)}")
    if top_pubs:
        print(f"[Publication Overview] Sample entries: {[p.get('title', 'NO_TITLE')[:50] for p in top_pubs[:2]]}")
    
    publication_overview_list = [
        (p.get('title') or '').strip()
        for p in top_pubs[:5]
        if isinstance(p, dict) and (p.get('title') or '').strip()
    ]
    print(f"[Publication Overview] Final list length: {len(publication_overview_list)}")
    top_hits_list = [
        f"{(p.get('venue') or 'arXiv')} {p.get('year','')}".strip()
        for p in top_pubs[:5]
        if isinstance(p, dict)
    ]
    # Highlights: prefer curated
    curated = getattr(profile, '_homepage_highlights', None)
    curated_highlights = list(getattr(curated, 'curated_highlights', []) or []) if curated else []
    highlights_from_insights = curated_highlights or (list(getattr(insights, 'highlights', []) or []) if insights else [])
    honors_list = list(profile.notable_achievements[:5]) if profile.notable_achievements else []
    # Service and talks
    service_spec = getattr(profile, '_homepage_service_talks', None)
    service_roles = list(getattr(service_spec, 'service_roles', []) or []) if service_spec else []
    invited_talks = list(getattr(service_spec, 'invited_talks', []) or []) if service_spec else []
    service_list = service_roles + invited_talks

    # Open-source projects
    projects_spec = getattr(profile, '_homepage_projects', None)
    if projects_spec and getattr(projects_spec, 'items', None):
        proj_lines = []
        for item in projects_spec.items[:6]:
            name = item.name or ""
            typ = item.type or ""
            url = item.url or ""
            desc = item.description or ""
            pieces = [name]
            if typ:
                pieces.append(f"({typ})")
            if desc:
                pieces.append(f"- {desc}")
            if url:
                pieces.append(f"{url}")
            proj_lines.append(" ".join([p for p in pieces if p]))
        projects = proj_lines
    else:
        projects = ["GitHub projects available" if 'github' in profile.platforms else ""]

    current_status = getattr(insights, 'current_status', '') if insights else ''
    role_aff_detailed = getattr(insights, 'role_affiliation_detailed', '') if insights else ''

    overview = schemas.CandidateOverview(
        name=profile.name,
        email=profile.emails[0] if profile.emails else "",
        current_role_affiliation=role_aff_detailed or profile.affiliation_current or "",
        current_status=current_status,
        research_keywords=research_keywords_list_out,
        research_focus=research_focus_from_insights,
        profiles=profiles_display,
        publication_overview=publication_overview_list,
        top_tier_hits=top_hits_list,
        honors_grants=honors_list,
        service_talks=service_list,
        open_source_projects=projects,
        representative_papers=rep_papers,
        trigger_paper_title=trigger_paper_title or "",
        trigger_paper_url=trigger_paper_url or "",
        highlights=highlights_from_insights,
        radar=eval_result.radar,
        total_score=eval_result.total_score,
        detailed_scores=eval_result.details
    )
    
    # 🔍 完整的字段状态诊断
    print(f"[Candidate Overview] Final field status for {profile.name}:")
    print(f"  ✅ Research Focus: {len(research_focus_from_insights)} items")
    print(f"  ✅ Research Keywords: {len(research_keywords_list_out)} items")  
    print(f"  ✅ Highlights: {len(highlights_from_insights)} items")
    print(f"  {'✅' if publication_overview_list else '❌'} Publication Overview: {len(publication_overview_list)} items")
    print(f"  {'✅' if honors_list else '❌'} Honors/Grants: {len(honors_list)} items")
    print(f"  {'✅' if service_list else '❌'} Academic Service/Talks: {len(service_list)} items")
    print(f"  {'✅' if projects else '❌'} Open Source/Projects: {len([p for p in projects if p.strip()])} items")
    print(f"  {'✅' if rep_papers else '❌'} Representative Papers: {len(rep_papers)} items")
    print(f"  ✅ Total Score: {eval_result.total_score}")
    
    return overview

# ============================ ORCHESTRATOR ============================

def orchestrate_candidate_report(first_author: str, paper_title: str, paper_url: str = None, aliases: List[str] = None,
                                 k_queries: int = 40, author_id: str = None, api_key: str = None, 
                                 use_lightweight_mode: bool = False) -> Tuple[Optional[AuthorProfile], Optional[schemas.CandidateOverview], Optional[schemas.EvaluationResult]]:
    """Run discovery with homepage enforcement, select top papers, evaluate 7D, and return overview."""
    profile = discover_author_profile(first_author, paper_title, aliases, k_queries=k_queries, author_id=author_id, api_key=api_key)
    if profile is None:
        return None, None, None

    # Select top-3 papers (S2 author ID preferred)
    top3: List[Dict[str, Any]] = []
    if author_id:
        top3 = select_top3_recent_or_top_cited_papers(author_id)
    if not top3 and profile.selected_publications:
        # Fallback: use existing publications sorted by citations/year
        pubs = list(profile.selected_publications)
        pubs.sort(key=lambda x: (x.get('year') or 0, x.get('citations') or 0), reverse=True)
        top3 = pubs[:3]

    eval_res = evaluate_profile_7d(profile, top3, api_key=api_key)
    
    # 选择提取模式
    if use_lightweight_mode:
        overview = build_candidate_overview_lightweight(profile, eval_res, top3, paper_title, paper_url)
    else:
        # 尝试完整提取，失败时自动降级
        try:
            overview = build_candidate_overview(profile, eval_res, top3, paper_title, paper_url)
            # 检查关键字段是否为空，如果多数为空则认为提取失败
            empty_fields = 0
            if not overview.publication_overview: empty_fields += 1
            if not overview.honors_grants: empty_fields += 1  
            if not overview.service_talks: empty_fields += 1
            if not overview.open_source_projects or (len(overview.open_source_projects) == 1 and not overview.open_source_projects[0].strip()): empty_fields += 1
            if not overview.representative_papers: empty_fields += 1
            
            # 如果4个以上字段为空，降级到轻量模式
            if empty_fields >= 4:
                print(f"[Auto Fallback] {empty_fields}/5 key fields empty, switching to lightweight mode")
                overview = build_candidate_overview_lightweight(profile, eval_res, top3, paper_title, paper_url)
        except Exception as e:
            print(f"[Auto Fallback] Full extraction failed ({e}), using lightweight mode")
            overview = build_candidate_overview_lightweight(profile, eval_res, top3, paper_title, paper_url)
    
    return profile, overview, eval_res

# ============================ PROFILE REFINEMENT ============================

def enhance_career_stage_detection(profile: AuthorProfile) -> str:
    """
    增强的career stage检测，从多个来源综合判断
    
    Args:
        profile: 作者档案
        
    Returns:
        推断的career stage
    """
    stage_indicators = []
    
    # 1. 从affiliation中提取线索
    if profile.affiliation_current:
        affiliation_lower = profile.affiliation_current.lower()
        
        if any(keyword in affiliation_lower for keyword in ['professor', 'prof']):
            if 'assistant' in affiliation_lower:
                stage_indicators.append(('assistant_prof', 0.8))
            elif 'associate' in affiliation_lower:
                stage_indicators.append(('associate_prof', 0.8))
            elif 'full' in affiliation_lower or 'chair' in affiliation_lower:
                stage_indicators.append(('full_prof', 0.8))
            else:
                stage_indicators.append(('professor', 0.6))
        elif any(keyword in affiliation_lower for keyword in ['postdoc', 'postdoctoral', 'research fellow']):
            stage_indicators.append(('postdoc', 0.8))
        elif any(keyword in affiliation_lower for keyword in ['phd student', 'doctoral student', 'graduate student']):
            stage_indicators.append(('phd_student', 0.8))
        elif any(keyword in affiliation_lower for keyword in ['researcher', 'scientist']):
            if any(company in affiliation_lower for company in ['google', 'microsoft', 'amazon', 'meta', 'openai', 'anthropic']):
                stage_indicators.append(('industry_researcher', 0.7))
            else:
                stage_indicators.append(('researcher', 0.6))
        elif any(keyword in affiliation_lower for keyword in ['engineer', 'developer', 'manager']):
            stage_indicators.append(('industry', 0.7))
    
    # 2. 从notable achievements中提取线索
    for achievement in profile.notable_achievements:
        achievement_lower = achievement.lower()
        
        if any(keyword in achievement_lower for keyword in ['dissertation award', 'phd thesis']):
            stage_indicators.append(('recent_phd', 0.6))
        elif any(keyword in achievement_lower for keyword in ['young researcher', 'rising star', 'early career']):
            stage_indicators.append(('early_career', 0.7))
        elif any(keyword in achievement_lower for keyword in ['fellow', 'distinguished']):
            stage_indicators.append(('senior_researcher', 0.8))
    
    # 3. 从social impact中提取线索
    if profile.social_impact:
        impact_lower = profile.social_impact.lower()
        
        # 解析h-index和citations来推断career stage
        import re
        h_index_match = re.search(r'h-?index[:\s]*(\d+)', impact_lower)
        citation_match = re.search(r'citation[s]?[:\s]*(\d+)', impact_lower)
        paper_match = re.search(r'paper[s]?[:\s]*(\d+)', impact_lower)
        
        h_index = int(h_index_match.group(1)) if h_index_match else 0
        citations = int(citation_match.group(1)) if citation_match else 0
        papers = int(paper_match.group(1)) if paper_match else 0
        
        # 根据学术指标推断career stage
        if h_index >= 30 or citations >= 5000:
            stage_indicators.append(('senior_researcher', 0.7))
        elif h_index >= 15 or citations >= 1000:
            stage_indicators.append(('mid_career', 0.6))
        elif h_index >= 5 or citations >= 200:
            stage_indicators.append(('early_career', 0.6))
        elif papers <= 5 and citations <= 100:
            stage_indicators.append(('student_or_early', 0.5))
    
    # 4. 综合判断
    if not stage_indicators:
        return "unknown"
    
    # 按置信度排序，选择最可能的stage
    stage_indicators.sort(key=lambda x: x[1], reverse=True)
    best_stage, best_confidence = stage_indicators[0]
    
    # 如果有多个高置信度的指标，进行进一步判断
    high_confidence_stages = [stage for stage, conf in stage_indicators if conf >= 0.7]
    
    if len(high_confidence_stages) > 1:
        # 优先级：教授 > 研究员 > 博士后 > 学生
        priority_order = ['full_prof', 'associate_prof', 'assistant_prof', 'professor', 
                         'senior_researcher', 'industry_researcher', 'researcher', 
                         'postdoc', 'phd_student', 'student_or_early']
        
        for priority_stage in priority_order:
            if priority_stage in high_confidence_stages:
                return priority_stage
    
    return best_stage

def refine_author_profile(profile: AuthorProfile, target_author: str) -> AuthorProfile:
    """最终精炼作者档案，确保数据质量"""
    
    # 1. 清理aliases - 移除明显不相关的名字
    target_words = set(target_author.lower().split())
    refined_aliases = []
    
    for alias in profile.aliases:
        if not alias or alias == profile.name:
            continue
            
        alias_words = set(alias.lower().split())
        
        # 更严格的别名检查
        is_valid_alias = False
        
        # 1. 检查是否有共同的实质性词汇（长度>2）
        common_words = [word for word in (alias_words & target_words) if len(word) > 2]
        if len(common_words) > 0:
            is_valid_alias = True
        
        # 2. 检查是否是名字的部分或变体
        target_first = target_author.split()[0].lower() if target_author.split() else ""
        target_last = target_author.split()[-1].lower() if len(target_author.split()) > 1 else ""
        
        if (target_first and target_first in alias.lower()) or (target_last and target_last in alias.lower()):
            is_valid_alias = True
        
        # 3. 排除明显不相关的名字
        if any(bad_indicator in alias.lower() for bad_indicator in ['rex', 'cook', 'evans', 'dante', 'ortega', 'camerino']):
            is_valid_alias = False
        
        # 4. 排除过长的名字（可能是其他人）
        if len(alias.split()) > 4:
            is_valid_alias = False
        
        if is_valid_alias:
            refined_aliases.append(alias)
    
    profile.aliases = refined_aliases[:3]  # 限制为最多3个别名
    
    # 2. 验证和清理平台链接
    verified_platforms = {}
    for platform, url in profile.platforms.items():
        if url and url.startswith('http') and len(url) > 10:
            # 基本URL验证
            verified_platforms[platform] = url
    
    profile.platforms = verified_platforms
    
    # 3. 清理兴趣领域 - 去重和规范化
    refined_interests = []
    seen_interests = set()
    
    for interest in profile.interests:
        if interest:
            # 规范化兴趣描述
            normalized = interest.strip().lower()
            if normalized not in seen_interests and len(normalized) > 2:
                seen_interests.add(normalized)
                refined_interests.append(interest.strip())
    
    profile.interests = refined_interests[:8]  # 限制兴趣数量
    
    # 4. 清理论文列表
    refined_publications = []
    seen_titles = set()
    
    for pub in profile.selected_publications:
        if isinstance(pub, dict) and pub.get('title'):
            title_normalized = pub['title'].lower().strip()
            if title_normalized not in seen_titles:
                seen_titles.add(title_normalized)
                refined_publications.append(pub)
    
    # 限制论文数量 to 10
    profile.selected_publications = refined_publications[:10]  
    
    # 5. 清理Notable成就
    refined_achievements = []
    for achievement in profile.notable_achievements:
        if achievement and len(achievement.strip()) > 5:
            refined_achievements.append(achievement.strip())
    
    # 限制成就数量 to 10
    profile.notable_achievements = refined_achievements[:10] 
    
    # 6. 增强career stage检测
    if not profile.career_stage or profile.career_stage == "assistant_prof":  # 如果没有或者是默认值
        enhanced_stage = enhance_career_stage_detection(profile)
        if enhanced_stage and enhanced_stage != "unknown":
            profile.career_stage = enhanced_stage
            print(f"[Enhanced Career Stage] Updated to: {enhanced_stage}")
    
    return profile

# ============================ SCORING SYSTEM ============================

def calculate_overall_score(profile: AuthorProfile) -> float:
    """计算作者的综合评分 (0-100)"""
    score = 0.0
    
    # 1. 平台权威性评分 (0-25分)
    platform_score = 0
    platform_weights = {
        'orcid': 8, 'openreview': 7, 'scholar': 6, 'semanticscholar': 5, 
        'dblp': 4, 'university': 6, 'github': 3, 'homepage': 4
    }
    for platform in profile.platforms:
        if platform in platform_weights:
            platform_score += platform_weights[platform]
    score += min(25, platform_score)
    
    # 2. 信息完整性评分 (0-20分)
    completeness = 0
    if profile.affiliation_current: completeness += 4
    if profile.emails: completeness += 3
    if profile.interests: completeness += 4
    if profile.homepage_url: completeness += 3
    if len(profile.aliases) > 0: completeness += 2
    if len(profile.selected_publications) > 0: completeness += 4
    score += completeness
    
    # 3. Notable成就评分 (0-25分)
    notable_score = 0
    if profile.notable_achievements:
        for achievement in profile.notable_achievements:
            achievement_lower = achievement.lower()
            if any(keyword in achievement_lower for keyword in 
                   ['best paper', 'outstanding paper', 'award']):
                notable_score += 8
            elif any(keyword in achievement_lower for keyword in 
                     ['fellow', 'ieee fellow', 'acm fellow']):
                notable_score += 10
            elif any(keyword in achievement_lower for keyword in 
                     ['rising star', 'young researcher']):
                notable_score += 6
            elif any(keyword in achievement_lower for keyword in 
                     ['keynote', 'invited speaker']):
                notable_score += 5
            elif any(keyword in achievement_lower for keyword in 
                     ['startup', 'founder', 'entrepreneur']):
                notable_score += 4
            else:
                notable_score += 2
    score += min(25, notable_score)
    
    # 4. 学术影响力评分 (0-20分)
    impact_score = 0
    if profile.social_impact:
        impact_text = profile.social_impact.lower()
        # 解析h-index
        import re
        h_index_match = re.search(r'h-?index[:\s]*(\d+)', impact_text)
        if h_index_match:
            h_index = int(h_index_match.group(1))
            if h_index >= 50: impact_score += 20
            elif h_index >= 30: impact_score += 15
            elif h_index >= 20: impact_score += 12
            elif h_index >= 10: impact_score += 8
            elif h_index >= 5: impact_score += 5
        
        # 解析引用数
        citation_match = re.search(r'citation[s]?[:\s]*(\d+)', impact_text)
        if citation_match:
            citations = int(citation_match.group(1))
            if citations >= 10000: impact_score += 10
            elif citations >= 5000: impact_score += 8
            elif citations >= 1000: impact_score += 6
            elif citations >= 500: impact_score += 4
            elif citations >= 100: impact_score += 2
    
    # 论文数量作为影响力指标
    pub_count = len(profile.selected_publications)
    if pub_count >= 20: impact_score += 8
    elif pub_count >= 10: impact_score += 6
    elif pub_count >= 5: impact_score += 4
    elif pub_count >= 3: impact_score += 2
    
    score += min(20, impact_score)
    
    # 5. 职业阶段调整 (0-10分)
    stage_score = 0
    if profile.career_stage:
        stage_lower = profile.career_stage.lower()
        if 'full_prof' in stage_lower or 'professor' in stage_lower:
            stage_score += 10
        elif 'associate_prof' in stage_lower or 'associate professor' in stage_lower:
            stage_score += 8
        elif 'assistant_prof' in stage_lower or 'assistant professor' in stage_lower:
            stage_score += 6
        elif 'postdoc' in stage_lower:
            stage_score += 4
        elif 'phd' in stage_lower or 'student' in stage_lower:
            stage_score += 2
        elif 'industry' in stage_lower:
            stage_score += 7
    score += stage_score
    
    return min(100.0, score)

# ============================ ADDITIONAL PUBLICATIONS FUNCTIONS ============================

def fetch_author_publications_via_s2(author_id: str, k: int = 10) -> List[Dict[str, Any]]:
    """
    Fetch additional publications via Semantic Scholar API
    """
    publications = []

    try:
        from semantic_paper_search import SemanticScholarClient
        s2_client = SemanticScholarClient()
        
        papers = s2_client.get_author_papers(author_id, limit=k, sort="citationCount")
        
        for paper in papers:
            pub_info = {
                'title': paper.get('title', ''),
                'year': paper.get('year'),
                'venue': paper.get('venue', ''),
                'url': paper.get('url', ''),
                'citations': paper.get('citationCount', 0),
                'authors': paper.get('authors', [])
            }
            publications.append(pub_info)
            
        print(f"[S2 Publications] Fetched {len(publications)} papers for author {author_id}")
        
    except Exception as e:
        print(f"[S2 publications] Error: {e}")

    return publications

def fetch_author_pubs_fallback_arxiv(author_name: str, k: int = 10) -> List[Dict[str, Any]]:
    """Fallback publication discovery via arXiv"""
    publications = []

    try:
        # Search arXiv for author publications
        query = f'site:arxiv.org "{author_name}"'
        results = searxng_search(query, engines=config.SEARXNG_ENGINES_ARXIV, pages=2, k_per_query=10)

        for result in results[:k]:
            url = result.get('url', '')
            if 'arxiv.org' in url and ('abs' in url or 'pdf' in url):
                # Extract basic info from snippet
                title = result.get('title', '')
                snippet = result.get('snippet', '')

                pub_info = {
                    'title': title,
                    'url': url,
                    'venue': 'arXiv',
                    'year': None  # Would need more sophisticated extraction
                }
                publications.append(pub_info)

    except Exception as e:
        print(f"[arXiv publications] Error: {e}")

    return publications

# ============================ COMPREHENSIVE HOMEPAGE FETCHER ============================

def fetch_homepage_comprehensive(url: str, author_name: str = "", max_chars: int = 50000,
                                include_subpages: bool = True, max_subpages: int = 6) -> Dict[str, Any]:
    """
    专门处理homepage链接的全面抓取函数
    从整个HTML内容中提取各种社交媒体链接和其他作者信息
    支持自动发现和抓取subpage内容

    Args:
        url: homepage URL
        author_name: 作者姓名（用于验证和匹配）
        max_chars: 最大字符限制
        include_subpages: 是否包含subpage抓取（默认为True）
        max_subpages: 最大抓取的subpage数量

    Returns:
        Dict containing:
        - 'full_html': 完整的HTML内容（包含subpages）
        - 'extracted_links': 提取的各种链接
        - 'emails': 邮箱列表
        - 'social_platforms': 社交媒体平台链接
        - 'text_content': 文本内容
        - 'title': 页面标题
        - 'subpages': subpage信息（如果启用）
        - 'total_subpages': subpage总数
        - 'successful_subpages': 成功抓取的subpage数
    """
    print(f"[Homepage Fetcher] Starting comprehensive fetch for: {url}")
    print(f"[Homepage Fetcher] Subpages enabled: {include_subpages}")

    # 如果启用subpages，使用增强版函数
    if include_subpages:
        return fetch_homepage_comprehensive_with_subpages(
            url=url,
            author_name=author_name,
            max_chars=max_chars,
            max_subpages=max_subpages,
            subpage_timeout=8
        )

    # 否则使用原有逻辑（保持向后兼容）
    result = {
        'full_html': '',
        'extracted_links': {},
        'emails': [],
        'social_platforms': {},
        'text_content': '',
        'title': '',
        'success': False,
        'subpages': [],
        'total_subpages': 0,
        'successful_subpages': 0
    }

    try:
        # 使用requests获取完整HTML内容
        r = requests.get(url, timeout=15, headers=config.UA)

        if not r.ok:
            print(f"[Homepage Fetcher] HTTP error {r.status_code} for {url}")
            return result

        html_content = r.text
        result['full_html'] = html_content[:max_chars]  # 限制大小但保留完整性
        result['success'] = True

        # 使用BeautifulSoup解析HTML
        soup = BeautifulSoup(html_content, 'html.parser')

        # 1. 提取页面标题
        title = extract_title_unified(html_content)
        result['title'] = title
        print(f"[Homepage Fetcher] Extracted title: {title}")

        # 2. 提取所有链接
        all_links = extract_all_links_from_html(html_content, url)
        result['extracted_links'] = all_links

        # 3. 专门提取社交媒体平台链接
        social_platforms = extract_social_platforms_from_html(html_content, url)
        result['social_platforms'] = social_platforms
        print(f"[Homepage Fetcher] Found {len(social_platforms)} social platforms")

        # 4. 提取邮箱地址（带作者名过滤）
        emails = extract_emails_from_html(html_content, author_name)
        result['emails'] = emails
        print(f"[Homepage Fetcher] Found {len(emails)} email addresses")

        # 5. 提取主要文本内容（用于LLM处理）
        text_content = extract_main_text(html_content, url)
        result['text_content'] = text_content[:30000]  # 限制文本内容大小

        # 6. 打印提取结果摘要
        print(f"[Homepage Fetcher] Summary:")
        print(f"  - Title: {title}")
        print(f"  - Social platforms: {list(social_platforms.keys())}")
        print(f"  - Emails: {emails}")
        print(f"  - Total links found: {len(all_links)}")

        return result

    except Exception as e:
        print(f"[Homepage Fetcher] Error fetching {url}: {e}")
        return result


def extract_all_links_from_html(html_content: str, base_url: str = "") -> Dict[str, List[str]]:
    """
    从HTML内容中提取所有类型的链接

    Args:
        html_content: HTML内容
        base_url: 基础URL（用于相对链接转换）

    Returns:
        分类后的链接字典
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    links = {
        'all': [],
        'mailto': [],
        'http': [],
        'https': [],
        'relative': []
    }

    for a_tag in soup.find_all('a', href=True):
        href = a_tag['href'].strip()

        # 跳过空链接和JavaScript
        if not href or href.startswith('javascript:') or href == '#':
            continue

        links['all'].append(href)

        if href.startswith('mailto:'):
            links['mailto'].append(href)
        elif href.startswith('http://'):
            links['http'].append(href)
        elif href.startswith('https://'):
            links['https'].append(href)
        elif not href.startswith(('http://', 'https://', 'mailto:')):
            # 相对链接
            links['relative'].append(href)

    return links


def extract_social_platforms_from_html(html_content: str, base_url: str = "") -> Dict[str, str]:
    """
    从HTML内容中专门提取社交媒体和学术平台链接

    Args:
        html_content: HTML内容
        base_url: 基础URL

    Returns:
        平台名称到URL的映射字典
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    platforms = {}

    # 定义平台识别规则
    platform_patterns = {
        'scholar': [
            r'scholar\.google\.com/citations\?user=',
            r'scholar\.google\.com/citations/',
        ],
        'github': [
            r'github\.com/[A-Za-z0-9\-_]+',
        ],
        'twitter': [
            r'(?:x\.com|twitter\.com)/[A-Za-z0-9_]+',
        ],
        'linkedin': [
            r'linkedin\.com/in/[A-Za-z0-9\-_]+',
        ],
        'orcid': [
            r'orcid\.org/\d{4}-\d{4}-\d{4}-\d{4}',
        ],
        'openreview': [
            r'openreview\.net/profile\?id=',
        ],
        'semanticscholar': [
            r'semanticscholar\.org/author/',
        ],
        'dblp': [
            r'dblp\.org/pid/',
            r'dblp\.org/pers/',
        ],
        'researchgate': [
            r'researchgate\.net/profile/',
        ],
        'huggingface': [
            r'huggingface\.co/[A-Za-z0-9\-_]+',
        ]
    }

    for a_tag in soup.find_all('a', href=True):
        href = a_tag['href'].strip()

        for platform, patterns in platform_patterns.items():
            for pattern in patterns:
                if re.search(pattern, href, re.IGNORECASE):
                    if platform not in platforms:  # 保留第一个匹配的链接
                        # 确保URL是完整的
                        if not href.startswith(('http://', 'https://')):
                            if base_url:
                                if href.startswith('/'):
                                    from urllib.parse import urljoin
                                    href = urljoin(base_url, href)
                                else:
                                    href = f"{base_url.rstrip('/')}/{href}"
                        platforms[platform] = href
                        print(f"[Platform Found] {platform}: {href}")
                        break

    return platforms


def extract_emails_from_html(html_content: str, author_name: str = "") -> List[str]:
    """
    从HTML内容中提取邮箱地址，并过滤掉明显不属于目标作者的邮箱
    支持各种反爬虫邮箱格式，如 "name - at - domain.com"

    Args:
        html_content: HTML内容
        author_name: 目标作者姓名，用于过滤

    Returns:
        过滤后的邮箱地址列表
    """
    import urllib.parse
    soup = BeautifulSoup(html_content, 'html.parser')
    emails = set()  # 使用set去重

    # 1. 从mailto链接中提取
    for a_tag in soup.find_all('a', href=True):
        href = a_tag['href'].strip()
        if href.startswith('mailto:'):
            email = href[7:].split('?')[0]  # 移除可能的查询参数
            # 处理URL编码
            email = urllib.parse.unquote(email)
            if '@' in email and is_email_relevant_to_author(email, author_name):
                emails.add(email.lower())

    # 2. 从文本内容中提取（使用正则表达式）
    email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    text_content = soup.get_text()
    found_emails = re.findall(email_pattern, text_content, re.IGNORECASE)

    for email in found_emails:
        if is_email_relevant_to_author(email, author_name):
            emails.add(email.lower())

    # 3. 从特定属性中提取（有些网站把邮箱放在data属性中）
    for tag in soup.find_all(attrs={'data-email': True}):
        email = tag.get('data-email', '').strip()
        if '@' in email and is_email_relevant_to_author(email, author_name):
            emails.add(email.lower())

    # 4. 处理反爬虫邮箱格式（如 "name - at - domain.com"）
    # 查找可能的反爬虫邮箱模式
    obfuscated_patterns = [
        r'\b([A-Za-z0-9._%+-]+)\s*-\s*at\s*-\s*([A-Za-z0-9.-]+\.[A-Z|a-z]{2,})\b',  # name - at - domain.com
        r'\b([A-Za-z0-9._%+-]+)\s*\[at\]\s*([A-Za-z0-9.-]+\.[A-Z|a-z]{2,})\b',    # name [at] domain.com
        r'\b([A-Za-z0-9._%+-]+)\s*@\s*([A-Za-z0-9.-]+\.[A-Z|a-z]{2,})\b',         # name @ domain.com (文本中的@)
        r'\b([A-Za-z0-9._%+-]+)\s*\(at\)\s*([A-Za-z0-9.-]+\.[A-Z|a-z]{2,})\b',    # name (at) domain.com
    ]

    # 从所有文本内容中查找
    for pattern in obfuscated_patterns:
        matches = re.findall(pattern, text_content, re.IGNORECASE)
        for username, domain in matches:
            email = f"{username}@{domain}".lower()
            if is_email_relevant_to_author(email, author_name):
                emails.add(email)

    # 5. 处理HTML中的反爬虫格式（从href和文本内容）
    for a_tag in soup.find_all('a', href=True):
        href = a_tag['href'].strip()
        text = a_tag.get_text().strip()

        # 处理href中的URL编码反爬虫格式
        if 'mailto:' in href:
            decoded_href = urllib.parse.unquote(href)
            for pattern in obfuscated_patterns:
                matches = re.findall(pattern, decoded_href, re.IGNORECASE)
                for username, domain in matches:
                    email = f"{username}@{domain}".lower()
                    if is_email_relevant_to_author(email, author_name):
                        emails.add(email)

        # 处理文本中的反爬虫格式
        for pattern in obfuscated_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for username, domain in matches:
                email = f"{username}@{domain}".lower()
                if is_email_relevant_to_author(email, author_name):
                    emails.add(email)

    # 6. 处理其他可能的邮箱链接格式
    # 处理onclick事件中的邮箱
    for tag in soup.find_all(attrs={'onclick': True}):
        onclick = tag.get('onclick', '').strip()
        if 'mailto:' in onclick or 'email' in onclick.lower():
            # 提取onclick中的mailto链接
            mailto_match = re.search(r'mailto:([^\s\'"]+)', onclick, re.IGNORECASE)
            if mailto_match:
                email = urllib.parse.unquote(mailto_match.group(1))
                if '@' in email and is_email_relevant_to_author(email, author_name):
                    emails.add(email.lower())

    # 7. 处理JavaScript混淆的邮箱
    # 查找可能的JavaScript邮箱构造
    script_tags = soup.find_all('script')
    for script in script_tags:
        if script.string:
            script_content = script.string
            # 查找可能的邮箱构造模式
            js_email_patterns = [
                r'mailto:\s*[\'"]([^\'"]+)[\'"]',  # mailto:"email"
                r'([a-zA-Z0-9._%+-]+)\s*\+\s*[\'"](@[^\'"]+)[\'"]',  # name + "@domain"
                r'[\'"]([a-zA-Z0-9._%+-]+@[^\'"]+)[\'"]',  # "email@domain"
                r'var\s+email\s*=\s*[\'"]([^\'"]+)[\'"]',  # var email = "email"
                r'([a-zA-Z0-9._%+-]+)\s*\+\s*["\'](@[^"\']+)["\']',  # name + "@domain"
            ]
            for pattern in js_email_patterns:
                matches = re.findall(pattern, script_content, re.IGNORECASE)
                for match in matches:
                    if isinstance(match, tuple) and len(match) == 2:
                        # 处理 name + "@domain" 格式
                        username, domain_part = match
                        email = username + domain_part
                    else:
                        # 处理其他格式
                        email = match if isinstance(match, str) else ''.join(match)
                    email = urllib.parse.unquote(email)
                    if '@' in email and is_email_relevant_to_author(email, author_name):
                        emails.add(email.lower())

    # 8. 处理其他属性中的邮箱（如data-href, data-mail等）
    other_attrs = ['data-href', 'data-mail', 'data-email', 'data-contact']
    for attr in other_attrs:
        for tag in soup.find_all(attrs={attr: True}):
            attr_value = tag.get(attr, '').strip()
            if attr_value.startswith('mailto:'):
                email = urllib.parse.unquote(attr_value[7:].split('?')[0])
                if '@' in email and is_email_relevant_to_author(email, author_name):
                    emails.add(email.lower())
            elif '@' in attr_value:
                email = urllib.parse.unquote(attr_value)
                if is_email_relevant_to_author(email, author_name):
                    emails.add(email.lower())

    # 9. 处理实体编码的邮箱
    # BeautifulSoup会自动解码实体，所以直接从解码后的文本中提取
    decoded_text = soup.get_text()

    # 查找解码后的邮箱（已经被BeautifulSoup转换为<email>格式）
    decoded_email_pattern = r'<([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})>'
    matches = re.findall(decoded_email_pattern, decoded_text, re.IGNORECASE)
    for email in matches:
        if is_email_relevant_to_author(email, author_name):
            emails.add(email.lower())

    # 同时检查原始HTML中的实体编码（以防万一）
    raw_html = str(soup)
    entity_patterns = [
        r'&lt;([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})&gt;',  # &lt;email&gt;
        r'&#60;([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})&#62;',  # &#60;email&#62;
    ]
    for pattern in entity_patterns:
        matches = re.findall(pattern, raw_html, re.IGNORECASE)
        for email in matches:
            if is_email_relevant_to_author(email, author_name):
                emails.add(email.lower())

    # 10. 处理分段的反爬虫格式（如name[at]domain[dot]com）
    extended_obfuscated_patterns = [
        r'\b([A-Za-z0-9._%+-]+)\s*\[at\]\s*([A-Za-z0-9.-]+)\s*\[dot\]\s*([a-zA-Z]{2,})\b',  # name [at] domain [dot] com
        r'\b([A-Za-z0-9._%+-]+)\s*\(at\)\s*([A-Za-z0-9.-]+)\s*\(dot\)\s*([a-zA-Z]{2,})\b',  # name (at) domain (dot) com
        r'\b([A-Za-z0-9._%+-]+)\s*@\s*([A-Za-z0-9.-]+)\s*\.\s*([a-zA-Z]{2,})\b',         # name @ domain . com
    ]

    for pattern in extended_obfuscated_patterns:
        matches = re.findall(pattern, text_content, re.IGNORECASE)
        for match in matches:
            if len(match) == 3:
                username, domain, tld = match
                email = f"{username}@{domain}.{tld}".lower()
                if is_email_relevant_to_author(email, author_name):
                    emails.add(email)

    # 11. 处理图片alt文本中的邮箱（有些网站用图片显示邮箱）
    for img in soup.find_all('img', alt=True):
        alt_text = img.get('alt', '').strip()
        # 检查alt文本是否包含邮箱信息
        for pattern in obfuscated_patterns + extended_obfuscated_patterns:
            matches = re.findall(pattern, alt_text, re.IGNORECASE)
            for match in matches:
                if isinstance(match, tuple) and len(match) >= 2:
                    if len(match) == 2:
                        username, domain = match
                        email = f"{username}@{domain}".lower()
                    elif len(match) == 3:
                        username, domain, tld = match
                        email = f"{username}@{domain}.{tld}".lower()
                    if is_email_relevant_to_author(email, author_name):
                        emails.add(email)

    return list(emails)

def is_email_relevant_to_author(email: str, author_name: str) -> bool:
    """
    判断邮箱是否可能属于目标作者 - 增强版
    
    Args:
        email: 邮箱地址
        author_name: 目标作者姓名
        
    Returns:
        是否相关
    """
    if not author_name or not email:
        return False
    
    email_lower = email.lower().strip()
    
    # 排除明显的系统/通用邮箱，但要考虑上下文
    system_emails = [
        'admin@', 'support@', 'webmaster@',
        'noreply@', 'no-reply@', 'help@', 'service@', 'office@',
        'secretary@', 'dept@', 'department@', 'marketing@', 'sales@'
    ]

    # 对于'info@'和'contact@'，如果作者名匹配，则不视为系统邮箱
    author_words = [word.lower() for word in author_name.split() if len(word) > 2]
    email_username = email_lower.split('@')[0] if '@' in email_lower else ''

    # 检查是否是明显的系统邮箱
    is_system_email = False
    for prefix in system_emails:
        if email_lower.startswith(prefix):
            is_system_email = True
            break

    # 特殊处理'info@'和'contact@' - 如果用户名与作者名相关，则不视为系统邮箱
    if email_lower.startswith(('info@', 'contact@')):
        if any(word in email_username for word in author_words) or email_username in author_name.lower():
            is_system_email = False

    if is_system_email:
        return False
    
    # 排除明显的垃圾邮箱或占位符
    spam_patterns = ['****', 'xxx@', 'example@', 'dummy@', 'fake@']
    # 只过滤完全匹配的测试邮箱，不过滤包含'test'的一般邮箱
    if any(spam in email_lower for spam in spam_patterns) or email_lower == 'test@test.com':
        return False
    
    # 排除明显不是个人邮箱的地址
    if any(company in email_lower for company in [
        '@google.com', '@microsoft.com', '@amazon.com', '@meta.com', 
        '@apple.com', '@nvidia.com', '@openai.com', '@anthropic.com'
    ]):
        # 这些大公司邮箱通常不是学者的主要联系邮箱
        return False
    
    # 提取邮箱用户名和域名
    if '@' not in email_lower:
        return False
    
    email_username, email_domain = email_lower.split('@', 1)
    author_words = [word.lower() for word in author_name.split() if len(word) > 2]
    
    # 强匹配：邮箱用户名包含作者姓名的关键词
    name_match_score = 0
    for word in author_words:
        if word in email_username:
            name_match_score += 1
    
    # 如果有强名字匹配，直接接受
    if name_match_score >= len(author_words) * 0.5:
        return True
    
    # 检查是否是学术机构邮箱
    academic_domains = ['.edu', '.ac.uk', '.ac.nz', '.ac.jp', '.edu.cn', '.ac.cn', '.ac.']
    is_academic = any(domain in email_domain for domain in academic_domains)
    
    # 学术邮箱 + 有一定名字匹配度
    if is_academic and name_match_score > 0:
        return True
    
    # 如果没有名字匹配且不是学术邮箱，拒绝
    if name_match_score == 0 and not is_academic:
        return False
    
    # 其他情况保守接受
    return True

def validate_url_quality(url: str, platform: str, author_name: str) -> Tuple[bool, float, str]:
    """
    验证URL的整体质量和相关性
    
    Args:
        url: 待验证的URL
        platform: 平台类型
        author_name: 目标作者姓名
        
    Returns:
        (is_valid, quality_score, reason)
    """
    if not url or not url.startswith('http'):
        return False, 0.0, "Invalid URL format"
    
    url_lower = url.lower()
    
    # 基础质量检查
    if len(url) > 500:
        return False, 0.0, "URL too long"
    
    if any(bad in url_lower for bad in ['spam', 'fake', 'test', 'example', 'dummy']):
        return False, 0.0, "Contains suspicious keywords"
    
    # 平台特定验证
    if platform == 'twitter':
        return validate_social_link_for_author(platform, url, author_name), 0.8, "Twitter validation"
    elif platform == 'linkedin':
        return validate_social_link_for_author(platform, url, author_name), 0.8, "LinkedIn validation"
    elif platform == 'github':
        return validate_social_link_for_author(platform, url, author_name), 0.7, "GitHub validation"
    elif platform == 'scholar':
        is_valid = 'citations?user=' in url_lower
        return is_valid, 0.9 if is_valid else 0.0, "Scholar validation"
    elif platform == 'homepage':
        # 个人网站质量评估
        quality_indicators = [
            len(url.split('.')) <= 3,  # 简单域名结构
            any(tld in url_lower for tld in ['.com', '.org', '.net', '.io', '.me']),  # 常见TLD
            not any(platform in url_lower for platform in ['blogspot', 'wordpress.com', 'wix.com'])  # 非博客平台
        ]
        quality_score = sum(quality_indicators) / len(quality_indicators)
        return quality_score >= 0.5, quality_score, f"Homepage quality: {quality_score:.2f}"
    
    # 默认验证
    return True, 0.6, "Basic validation passed"


def discover_subpages(base_url: str, html_content: str, author_name: str = "", max_subpages: int = 10) -> List[Dict[str, str]]:
    """
    从主页面HTML内容中发现有价值的subpage链接

    Args:
        base_url: 基础URL
        html_content: 主页面的HTML内容
        author_name: 作者姓名（用于相关性判断）
        max_subpages: 最大抓取的subpage数量

    Returns:
        subpage信息列表，每个包含 'url', 'title', 'type' 等信息
    """
    from urllib.parse import urlparse, urljoin

    print(f"[Subpage Discovery] Discovering subpages for: {base_url}")

    subpages = []
    soup = BeautifulSoup(html_content, 'html.parser')

    # 解析基础URL
    parsed_base = urlparse(base_url)
    base_domain = parsed_base.netloc
    base_path = parsed_base.path.rstrip('/')

    # 定义有价值的subpage模式
    valuable_subpages = [
        # 研究相关
        'research', 'publications', 'papers', 'projects', 'work',
        # 个人信息
        'about', 'bio', 'biography', 'cv', 'resume', 'vitae',
        # 教学相关
        'teaching', 'courses', 'students', 'supervision',
        # 联系方式
        'contact', 'contact-me',
        # 其他有用页面
        'news', 'updates', 'blog', 'resources', 'software', 'code',
        'group', 'team', 'lab', 'collaborators', 'alumni'
    ]

    # 从链接中发现subpage
    for a_tag in soup.find_all('a', href=True):
        href = a_tag['href'].strip()
        link_text = a_tag.get_text().strip()

        # 跳过无效链接
        if not href or href.startswith(('javascript:', '#', 'mailto:')):
            continue

        # 转换为绝对URL
        if not href.startswith(('http://', 'https://')):
            if href.startswith('/'):
                href = f"{parsed_base.scheme}://{base_domain}{href}"
            else:
                href = urljoin(base_url, href)

        # 检查是否是同一域名的内部链接
        parsed_href = urlparse(href)
        if parsed_href.netloc != base_domain:
            continue

        # 检查是否是subpage（不是根路径）
        href_path = parsed_href.path.rstrip('/')
        if not href_path or href_path == base_path:
            continue

        # 判断是否是有价值的subpage
        is_valuable = False
        subpage_type = 'other'

        # 检查路径中的关键词
        path_lower = href_path.lower()
        for keyword in valuable_subpages:
            if f'/{keyword}' in path_lower or f'/{keyword}/' in path_lower or path_lower.endswith(f'/{keyword}'):
                is_valuable = True
                subpage_type = keyword
                break

        # 检查链接文本中的关键词
        text_lower = link_text.lower()
        for keyword in valuable_subpages:
            if keyword in text_lower:
                is_valuable = True
                if subpage_type == 'other':
                    subpage_type = keyword
                break

        # 检查是否可能是个人页面（不包含常见排除词）
        if not is_valuable:
            exclude_patterns = ['login', 'admin', 'wp-', 'category', 'tag', 'author', 'search', 'feed', 'rss']
            if not any(pattern in path_lower for pattern in exclude_patterns):
                # 检查路径深度（2-3级路径可能是个人页面）
                path_parts = [p for p in href_path.split('/') if p]
                if 1 <= len(path_parts) <= 3:
                    # 检查是否包含作者名字的缩写或相关词
                    if author_name:
                        author_parts = [part.lower() for part in author_name.split() if len(part) > 2]
                        for part in author_parts:
                            if part in path_lower:
                                is_valuable = True
                                subpage_type = 'personal'
                                break

        if is_valuable:
            # 避免重复
            if not any(sp['url'] == href for sp in subpages):
                subpages.append({
                    'url': href,
                    'title': link_text[:100] if link_text else f"Subpage: {subpage_type}",
                    'type': subpage_type,
                    'path': href_path
                })

    # 限制subpage数量
    subpages = subpages[:max_subpages]
    print(f"[Subpage Discovery] Found {len(subpages)} valuable subpages: {[sp['type'] for sp in subpages]}")

    return subpages


def fetch_subpage_content(subpage_info: Dict[str, str], timeout: int = 10) -> Dict[str, Any]:
    """
    抓取单个subpage的内容

    Args:
        subpage_info: subpage信息字典
        timeout: 请求超时时间

    Returns:
        subpage抓取结果
    """
    url = subpage_info['url']
    print(f"[Subpage Fetch] Fetching: {url}")

    result = {
        'url': url,
        'title': subpage_info['title'],
        'type': subpage_info['type'],
        'success': False,
        'html_content': '',
        'text_content': '',
        'links': {},
        'emails': [],
        'error': ''
    }

    try:
        r = requests.get(url, timeout=timeout, headers=config.UA)

        if not r.ok:
            result['error'] = f"HTTP {r.status_code}"
            return result

        html_content = r.text
        result['html_content'] = html_content[:50000]  # 限制大小
        result['success'] = True

        # 提取基本信息
        soup = BeautifulSoup(html_content, 'html.parser')

        # 更新标题
        if soup.title:
            result['title'] = soup.title.get_text().strip()[:100]

        # 提取文本内容
        result['text_content'] = extract_main_text(html_content, url)[:20000]

        # 提取链接
        result['links'] = extract_all_links_from_html(html_content, url)

        # 提取邮箱
        result['emails'] = extract_emails_from_html(html_content, "")

        print(f"[Subpage Fetch] Success: {url} ({len(result['text_content'])} chars)")

    except Exception as e:
        result['error'] = str(e)
        print(f"[Subpage Fetch] Error fetching {url}: {e}")

    return result


def merge_subpage_content(main_result: Dict[str, Any], subpage_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    将所有subpage内容合并到主结果中

    Args:
        main_result: 主页面抓取结果
        subpage_results: 所有subpage抓取结果

    Returns:
        合并后的完整结果
    """
    print(f"[Content Merge] Merging {len(subpage_results)} subpages into main content")

    # 合并HTML内容
    all_html_parts = [main_result['full_html']]
    all_text_parts = [main_result['text_content']]

    # 合并subpage信息
    subpage_summaries = []

    for subpage in subpage_results:
        if subpage['success']:
            # 添加到HTML集合中（用于后续LLM处理）
            if subpage['html_content']:
                all_html_parts.append(f"\n\n--- SUBPAGE: {subpage['title']} ({subpage['type']}) ---\n{subpage['html_content']}")

            # 添加到文本集合中
            if subpage['text_content']:
                all_text_parts.append(f"\n\n=== {subpage['title']} ({subpage['type']}) ===\n{subpage['text_content']}")

            # 收集subpage摘要信息
            subpage_summaries.append({
                'title': subpage['title'],
                'type': subpage['type'],
                'url': subpage['url'],
                'content_length': len(subpage['text_content']),
                'emails_found': len(subpage['emails'])
            })

            # 合并链接
            for link_type, links in subpage['links'].items():
                if link_type not in main_result['extracted_links']:
                    main_result['extracted_links'][link_type] = []
                main_result['extracted_links'][link_type].extend(links)

            # 合并邮箱（去重）
            for email in subpage['emails']:
                if email not in main_result['emails']:
                    main_result['emails'].append(email)

            # 合并社交平台链接
            subpage_social = extract_social_platforms_from_html(subpage['html_content'], subpage['url'])
            for platform, url in subpage_social.items():
                if platform not in main_result['social_platforms']:
                    main_result['social_platforms'][platform] = url

    # 更新合并后的内容
    main_result['full_html'] = '\n'.join(all_html_parts)[:100000]  # 限制总大小
    main_result['text_content'] = '\n'.join(all_text_parts)[:50000]  # 限制文本内容大小

    # 重要修复：从合并后的完整HTML中重新提取所有邮箱
    # 这确保了主页面和所有subpage的邮箱都被正确提取
    author_name_for_extraction = main_result.get('author_name', '')
    all_emails_in_merged_content = extract_emails_from_html(main_result['full_html'], author_name_for_extraction)

    # 合并所有找到的邮箱（包括主页面原始邮箱、subpage邮箱和重新提取的邮箱）
    original_emails = main_result.get('original_emails', [])
    final_emails = list(set(original_emails + main_result['emails'] + all_emails_in_merged_content))
    main_result['emails'] = final_emails

    # 从合并后的完整HTML中重新提取社交平台链接
    all_social_platforms = extract_social_platforms_from_html(main_result['full_html'], main_result.get('url', ''))
    # 合并社交平台（保留主页面原有的优先级）
    for platform, url in all_social_platforms.items():
        if platform not in main_result['social_platforms']:
            main_result['social_platforms'][platform] = url

    # 添加subpage信息
    main_result['subpages'] = subpage_summaries
    main_result['total_subpages'] = len(subpage_summaries)
    main_result['successful_subpages'] = len([s for s in subpage_summaries if s['content_length'] > 0])

    print(f"[Content Merge] Merged content: {len(main_result['full_html'])} chars HTML, {len(main_result['text_content'])} chars text")
    print(f"[Content Merge] Found additional {len([e for e in main_result['emails'] if e not in main_result.get('original_emails', [])])} emails")
    print(f"[Content Merge] Found additional {len([p for p in main_result['social_platforms'] if p not in main_result.get('original_platforms', [])])} social platforms")

    return main_result


# ============================ IMPROVED HOMEPAGE FETCHER WITH SUBPAGES ============================

def fetch_homepage_comprehensive_with_subpages(url: str, author_name: str = "", max_chars: int = 100000,
                                               max_subpages: int = 8, subpage_timeout: int = 8) -> Dict[str, Any]:
    """
    改进版的homepage抓取函数，能够自动发现和抓取subpage内容

    Args:
        url: homepage URL
        author_name: 作者姓名
        max_chars: 最大字符限制
        max_subpages: 最大抓取的subpage数量
        subpage_timeout: 单个subpage的超时时间

    Returns:
        包含主页面和所有subpage内容的完整结果字典
    """
    print(f"[Homepage Fetcher Enhanced] Starting comprehensive fetch with subpages for: {url}")

    result = {
        'full_html': '',
        'extracted_links': {},
        'emails': [],
        'social_platforms': {},
        'text_content': '',
        'title': '',
        'success': False,
        'subpages': [],
        'total_subpages': 0,
        'successful_subpages': 0,
        'error': ''
    }

    try:
        # 1. 首先抓取主页面
        print(f"[Homepage Fetcher Enhanced] Fetching main page...")
        r = requests.get(url, timeout=5, headers=config.UA)

        if not r.ok:
            result['error'] = f"Main page HTTP error {r.status_code}"
            print(f"[Homepage Fetcher Enhanced] {result['error']}")
            return result

        html_content = r.text
        result['full_html'] = html_content[:max_chars]
        result['success'] = True

        # 2. 解析主页面内容
        soup = BeautifulSoup(html_content, 'html.parser')
        title = extract_title_unified(html_content)
        result['title'] = title
        print(f"[Homepage Fetcher Enhanced] Main page title: {title}")

        # 3. 提取主页面信息
        result['extracted_links'] = extract_all_links_from_html(html_content, url)
        result['social_platforms'] = extract_social_platforms_from_html(html_content, url)
        result['emails'] = extract_emails_from_html(html_content, author_name)
        result['text_content'] = extract_main_text(html_content, url)[:30000]
        result['author_name'] = author_name  # 保存作者名以供后续使用
        result['url'] = url  # 保存URL以供后续使用

        # 记录原始信息（用于后续比较）
        result['original_emails'] = result['emails'].copy()
        result['original_platforms'] = list(result['social_platforms'].keys())

        # 4. 发现subpages
        subpages = discover_subpages(url, html_content, author_name, max_subpages)

        if not subpages:
            print(f"[Homepage Fetcher Enhanced] No valuable subpages found")
            return result

        # 5. 抓取subpage内容（并发处理以提高效率）
        subpage_results = []
        try:
            from concurrent.futures import ThreadPoolExecutor, as_completed
            # Dynamic concurrency: subpage fetching is IO-bound
            max_workers = get_extraction_workers(len(subpages))
            max_workers = min(max_workers, 10)  # Cap at 10 to avoid overwhelming the site
            print(f"[Subpage Fetch] Using {max_workers} workers for {len(subpages)} subpages")
            with ThreadPoolExecutor(max_workers=max_workers) as ex:
                fut2info = {ex.submit(fetch_subpage_content, sp, subpage_timeout): sp for sp in subpages}
                for fut in as_completed(fut2info):
                    try:
                        subpage_results.append(fut.result())
                    except Exception as e:
                        print(f"[Subpage Fetch] error: {e}")
        except Exception as e:
            print(f"[Subpage Parallel] Falling back to sequential due to error: {e}")
            for subpage_info in subpages:
                subpage_result = fetch_subpage_content(subpage_info, subpage_timeout)
                subpage_results.append(subpage_result)

        # 6. 合并所有内容
        result = merge_subpage_content(result, subpage_results)

        # 7. 最终统计
        print(f"[Homepage Fetcher Enhanced] Final summary:")
        print(f"  - Main page: {len(result['full_html'].split('--- SUBPAGE:')[0])} chars")
        print(f"  - Total content: {len(result['full_html'])} chars")
        print(f"  - Subpages found: {result['total_subpages']}")
        print(f"  - Subpages successful: {result['successful_subpages']}")
        print(f"  - Social platforms: {len(result['social_platforms'])}")
        print(f"  - Emails: {len(result['emails'])}")

        return result

    except Exception as e:
        result['error'] = str(e)
        print(f"[Homepage Fetcher Enhanced] Error: {e}")
        return result


# ============================ DEMO AND TESTING FUNCTIONS ============================

def test_homepage_subpage_fetching():
    """测试新的homepage subpage抓取功能"""
    print("=== Testing Homepage Subpage Fetching ===")

    # 测试用的URL（可以替换为实际的学术网站）
    test_urls = [
        "https://shenbinqian.github.io/"
    ]

    for i, url in enumerate(test_urls[:1]):  # 只测试第一个URL避免过多请求
        print(f"\n--- Test {i+1}: {url} ---")

        try:
            # 测试启用subpage的版本
            print("1. Testing with subpages enabled...")
            result_with_subpages = fetch_homepage_comprehensive(
                url=url,
                author_name="Ziyi Yang",  # 使用正确的作者名进行邮箱过滤
                include_subpages=True,
                max_subpages=6
            )

            print(f"   Success: {result_with_subpages['success']}")
            print(f"   Title: {result_with_subpages['title']}")
            # print(f'   HTML content: {result_with_subpages["full_html"]}')
            print(f'   Text content: {result_with_subpages["text_content"]}')
            print(f"   Social platforms: {len(result_with_subpages['social_platforms'])}")
            print(f"   Emails: {result_with_subpages['emails']}")
            print(f"   Original emails: {result_with_subpages.get('original_emails', [])}")
            print(f"   Subpages found: {result_with_subpages.get('total_subpages', 0)}")
            print(f"   Subpages successful: {result_with_subpages.get('successful_subpages', 0)}")
            print(f"   Total content length: {len(result_with_subpages['full_html'])}")

            # 调试信息：检查是否真的提取到了邮箱
            if result_with_subpages.get('original_emails'):
                print(f"   ✓ Main page emails found: {result_with_subpages['original_emails']}")
            else:
                print("   ✗ No emails found in main page extraction")
            
            # 显示找到的subpages
            if result_with_subpages.get('subpages'):
                print("   Subpages:")
                for sp in result_with_subpages['subpages'][:3]:  # 只显示前3个
                    print(f"     - {sp['type']}: {sp['title']} ({sp['content_length']} chars)")
                    
                    
            print(f'Found text content: {result_with_subpages["text_content"]}')

            # # 测试禁用subpage的版本进行对比
            # print("\n2. Testing with subpages disabled...")
            # result_without_subpages = fetch_homepage_comprehensive(
            #     url=url,
            #     author_name="Test Author",
            #     include_subpages=False
            # )

            # print(f"   Success: {result_without_subpages['success']}")
            # print(f"   Social platforms: {len(result_without_subpages['social_platforms'])}")
            # print(f"   Emails: {len(result_without_subpages['emails'])}")
            # print(f"   Content length: {len(result_without_subpages['full_html'])}")

            # # 对比结果
            # print("\n3. Comparison:")
            # print(f"   Subpages added content: {len(result_with_subpages['full_html']) - len(result_without_subpages['full_html'])} chars")
            # print(f"   Additional social platforms: {len(result_with_subpages['social_platforms']) - len(result_without_subpages['social_platforms'])}")
            # print(f"   Additional emails: {len(result_with_subpages['emails']) - len(result_without_subpages['emails'])}")

        except Exception as e:
            print(f"   Error testing {url}: {e}")

    print("\n=== Test Complete ===")


def demo_author_discovery():
    """Demo function for testing author discovery"""
    # Example usage
    first_author = "Yoshua Bengio"
    paper_title = "Deep Learning"
    aliases = ["Y. Bengio"]

    print(f"Discovering profile for: {first_author}")
    print(f"Paper: {paper_title}")

    profile = discover_author_profile(first_author, paper_title, aliases, k_queries=30)

    print("\n=== DISCOVERED PROFILE ===")
    print(f"Name: {profile.name}")
    print(f"Aliases: {profile.aliases}")
    print(f"Platforms: {profile.platforms}")
    print(f"IDs: {profile.ids}")
    print(f"Affiliation: {profile.affiliation_current}")
    print(f"Emails: {profile.emails}")
    print(f"Interests: {profile.interests}")
    print(f"Publications: {len(profile.selected_publications)}")
    print(f"Confidence: {profile.confidence}")

    return profile

if __name__ == "__main__":
    import sys

    # # 可以选择运行不同的测试
    # if len(sys.argv) > 1:
    #     test_type = sys.argv[1].lower()
    #     if test_type == "discovery":
    #         print("Running author discovery demo...")
    #         demo_author_discovery()
    #     elif test_type == "test_subpages":
    #         print("Running homepage subpage fetching test...")
    #         test_homepage_subpage_fetching()
    #     else:
    #         print("Usage: python author_discovery.py [discovery|test_subpages]")
    #         print("  discovery: Run full author discovery demo")
    #         print("  test_subpages: Test the new subpage fetching functionality")
    # else:
    #     print("Running default author discovery demo...")
    #     demo_author_discovery()

    c = ProfileCandidate(url='https://zehong-wang.github.io/', title='Zehong Wang: About Me', snippet='Github · LinkedIn. About Me. I am a second year Ph.D. student (2023 Fall ... Zehong Wang, Zheyuan Liu, Tianyi Ma, Jiazheng Li, Zheyuan Zhang, Xingbo Fu ...', score=0.75, should_fetch=True, reason='Personal research website with detailed academic information and publication list.')
    first_author = 'Zehong Wang'
    paper_title = 'GFT: Graph Foundation Model with Transferable Tree Vocabulary'
    profile = AuthorProfile(name='Zehong Wang', aliases=['Zehong Wang'], platforms={}, ids={}, homepage_url=None, affiliation_current=None, emails=[], interests=[], selected_publications=[{'title': 'Graph Prompting for Graph Learning Models: Recent Advances and Future Directions', 'year': 2025, 'venue': 'Proceedings of the 31st ACM SIGKDD Conference on Knowledge Discovery and Data Mining V.2', 'url': 'https://www.semanticscholar.org/paper/3835642207cafadd5761c7748e941c4ebd6a4ff3', 'citations': 0}, {'title': 'Graph Foundation Models: A Comprehensive Survey', 'year': 2025, 'venue': 'arXiv.org', 'url': 'https://www.semanticscholar.org/paper/54c37590a56adce8ce2536e572434cc104f5ec08', 'citations': 1}, {'title': 'Beyond Message Passing: Neural Graph Pattern Machine', 'year': 2025, 'venue': '', 'url': 'https://www.semanticscholar.org/paper/685d02c0e8fd09444d9ad369a9f5f3e5f25ff4e7', 'citations': 5}, {'title': 'LLM-Empowered Class Imbalanced Graph Prompt Learning for Online Drug Trafficking Detection', 'year': 2025, 'venue': 'Annual Meeting of the Association for Computational Linguistics', 'url': 'https://www.semanticscholar.org/paper/af5259343951babedb78636b4d1d16fc8b20f290', 'citations': 3}, {'title': 'AutoData: A Multi-Agent System for Open Web Data Collection', 'year': 2025, 'venue': 'arXiv.org', 'url': 'https://www.semanticscholar.org/paper/b8e98141a9d7eb7e01b4ec96f3b8ccfe73badc40', 'citations': 0}, {'title': 'Scalable Graph Generative Modeling via Substructure Sequences', 'year': 2025, 'venue': 'arXiv.org', 'url': 'https://www.semanticscholar.org/paper/c41884972240a059ceef06399904db10cbaca30b', 'citations': 0}, {'title': 'Subgraph Pooling: Tackling Negative Transfer on Graphs', 'year': 2024, 'venue': 'International Joint Conference on Artificial Intelligence', 'url': 'https://www.semanticscholar.org/paper/07b764c4df59b8739541bb4a321dbda04c095a17', 'citations': 13}, {'title': 'Training MLPs on Graphs without Supervision', 'year': 2024, 'venue': 'Web Search and Data Mining', 'url': 'https://www.semanticscholar.org/paper/3a2caaf04f08d838a0e111343490bdc06a3229f6', 'citations': 12}, {'title': 'Graph Inference Acceleration by Learning MLPs on Graphs without Supervision', 'year': 2024, 'venue': 'arXiv.org', 'url': 'https://www.semanticscholar.org/paper/60961d2d07e5163300d581691d63427ddfe7cd6e', 'citations': 0}, {'title': 'NGQA: A Nutritional Graph Question Answering Benchmark for Personalized Health-aware Nutritional Reasoning', 'year': 2024, 'venue': 'Annual Meeting of the Association for Computational Linguistics', 'url': 'https://www.semanticscholar.org/paper/67d0dba0de772ba0e0912e5f827b5da601e7ef2c', 'citations': 7}, {'title': 'Towards Graph Foundation Models: Learning Generalities Across Graphs via Task-Trees', 'year': 2024, 'venue': '', 'url': 'https://www.semanticscholar.org/paper/6a1e0241d29484eece376ecedf2a812ca0e1e46c', 'citations': 3}, {'title': 'Can LLMs Convert Graphs to Text-Attributed Graphs?', 'year': 2024, 'venue': 'North American Chapter of the Association for Computational Linguistics', 'url': 'https://www.semanticscholar.org/paper/75e9431252b7f656e66fcd1f652e7815e1da7393', 'citations': 11}, {'title': 'MOPI-HFRS: A Multi-objective Personalized Health-aware Food Recommendation System with LLM-enhanced Interpretation', 'year': 2024, 'venue': 'Knowledge Discovery and Data Mining', 'url': 'https://www.semanticscholar.org/paper/7cc3e02ef88084aeb289652b579ba579ee9cdc2b', 'citations': 14}, {'title': 'GFT: Graph Foundation Model with Transferable Tree Vocabulary', 'year': 2024, 'venue': 'Neural Information Processing Systems', 'url': 'https://www.semanticscholar.org/paper/9f6c1c8cd667d886d40bbd2ba9bb0d2e12ec7e5f', 'citations': 27}, {'title': 'Diet-ODIN: A Novel Framework for Opioid Misuse Detection with Interpretable Dietary Patterns', 'year': 2024, 'venue': 'Knowledge Discovery and Data Mining', 'url': 'https://www.semanticscholar.org/paper/a0111016c4a45bbb6afa57dc3eaf078457fdb894', 'citations': 13}, {'title': 'Learning Cross-Task Generalities Across Graphs via Task-trees', 'year': 2024, 'venue': 'arXiv.org', 'url': 'https://www.semanticscholar.org/paper/c229b225b2ffd96e7554086bb71758b285f1db3f', 'citations': 4}], confidence=0.3, notable_achievements=[], social_impact=None, career_stage=None, overall_score=0.0)
    protected_platforms = set()
    llm_ext = llm.get_llm("extract", temperature=0.1)
    success = process_homepage_candidate(
        c, first_author, paper_title, profile, protected_platforms, llm_ext
    )
    if success:
        homepage_processed = True
        print(f"[Homepage Success] Successfully processed homepage: {c.url}")
