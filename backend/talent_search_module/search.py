"""
Search functionality for Talent Search System
Handles SearXNG searches, URL fetching, and content extraction
"""
import re, json, io, logging
import io
from typing import Optional, Tuple, List, Dict, Any, Union
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode
from pathlib import Path
import sys

# Use pathlib for robust imports
current_dir = Path(__file__).parent
backend_dir = current_dir.parent
sys.path.insert(0, str(backend_dir))
sys.path.insert(0, str(current_dir))

import requests
from bs4 import BeautifulSoup
from trafilatura import extract

from backend import config
from utils import normalize_url, domain_of, safe_sleep, clean_text, looks_like_profile_url

try:
    # 可选：若未安装 readability-lxml，会自动回退
    from readability import Document  # type: ignore
    HAS_READABILITY = True
except Exception:
    HAS_READABILITY = False

# ============================ SEARXNG SEARCH FUNCTIONS ============================

import time
import threading

_SEARX_COUNTER = 0
# 全局速率限制：确保任何时候只有一个请求在发送
_SEARX_LOCK = threading.Lock()
_LAST_SEARX_REQUEST_TIME = 0
_MIN_REQUEST_INTERVAL = 0.8  # 每个请求之间至少间隔 0.8 秒（避免 429 错误）

def searxng_search(query: str, engines: List[str] = config.SEARXNG_ENGINES,
                   pages: int = config.SEARXNG_PAGES, k_per_query: int = config.SEARCH_K) -> List[Dict[str, str]]:
    """Search using SearXNG API with rate limiting and retry logic."""
    global _LAST_SEARX_REQUEST_TIME
    
    out: List[Dict[str, str]] = []
    base = config.SEARXNG_BASE_URL.rstrip("/")
    url_set = set()
    
    # Debug: 打印使用的 SearXNG URL
    print(f"[searxng] Using base URL: {base}")
    
    for p in range(1, pages + 1):
        # 速率限制：确保请求间隔
        with _SEARX_LOCK:
            current_time = time.time()
            elapsed = current_time - _LAST_SEARX_REQUEST_TIME
            if elapsed < _MIN_REQUEST_INTERVAL:
                sleep_time = _MIN_REQUEST_INTERVAL - elapsed
                print(f"[searxng] Rate limiting: sleeping {sleep_time:.2f}s")
                time.sleep(sleep_time)
            _LAST_SEARX_REQUEST_TIME = time.time()
        
        # 重试逻辑：429 错误时自动重试
        max_retries = 3
        retry_delay = 2.0
        
        for attempt in range(max_retries):
            try:
                params = {
                    "q": query,
                    "format": "json",
                    "engines": engines,
                    "categories": "general",  # 指定类别为general，提高结果相关性
                    "pageno": p,
                    "page": p,
                }
                
                if "google" in engines:
                    params["gl"] = ""
                
                search_url = f"{base}/search"
                if attempt == 0:
                    print(f"[searxng] Searching: {search_url} with query: {query[:50]}...")
                else:
                    print(f"[searxng] Retry {attempt}/{max_retries} for query: {query[:50]}...")
                
                r = requests.get(search_url, params=params, timeout=35, headers=config.UA)
                
                print(f"[searxng] Response status: {r.status_code}, content-length: {len(r.content)}")
                
                # 处理 429 错误
                if r.status_code == 429:
                    if attempt < max_retries - 1:
                        wait_time = retry_delay * (2 ** attempt)  # 指数退避
                        print(f"[searxng] 429 Too Many Requests, waiting {wait_time:.1f}s before retry...")
                        time.sleep(wait_time)
                        continue
                    else:
                        print(f"[searxng] Max retries reached for 429 error, skipping this query")
                        break
                
                r.raise_for_status()
                data = r.json() or {}
                rows = data.get("results") or []
                
                print(f"[searxng] Got {len(rows)} results for page {p}")
                break  # 成功，跳出重试循环
            
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 429 and attempt < max_retries - 1:
                    continue  # 继续重试
                if config.VERBOSE:
                    print(f"[searxng] HTTPError: {e!r} for query: {query} page={p}")
                break
            except Exception as e:
                if config.VERBOSE:
                    print(f"[searxng] error: {e!r} for query: {query} page={p}")
                break
        
        # 只有在成功获取数据后才处理结果
        try:
            if 'data' in locals() and 'rows' in locals():
                for it in rows[:k_per_query]:
                    u = it.get("url") or ""
                    if not u.startswith("http"):
                        continue
                    if u in url_set:
                        continue
                    url_set.add(u)
                    
                    # if arxiv search authors will contain a list of authors
                    out.append({
                        "title": (it.get("title") or "").strip(),
                        "url": u,
                        "snippet": (it.get("content") or "").strip(),
                        "engine": it.get("engine") or "",
                        "authors": it.get("authors") or [],
                    })
        except Exception as e:
            if config.VERBOSE:
                print(f"[searxng] error: {e!r} for query: {query} page={p}")

    # _SEARX_COUNTER += 1
    return out

# ============================ CONTENT FETCHING FUNCTIONS ============================


# ---- 通用：将 engines 既支持 str 也支持 list/tuple（修复你代码里传 ["bing"] 的用法）----
def _normalize_engines(engines: Union[str, List[str], Tuple[str, ...]]) -> str:
    if isinstance(engines, (list, tuple)):
        return ",".join(engines)
    return engines

# ---- URL 规范化：去除追踪参数，保留结构一致性 ----
_TRACKING_KEYS = {"utm_source","utm_medium","utm_campaign","utm_term","utm_content",
                  "gclid","fbclid","mc_cid","mc_eid","oly_anon_id","oly_enc_id"}

def canonicalize_url(u: str) -> str:
    try:
        p = urlparse(u)
        q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if k.lower() not in _TRACKING_KEYS]
        p2 = p._replace(query=urlencode(q, doseq=True))
        p2 = p2._replace(fragment="")
        return urlunparse(p2)
    except Exception:
        return u

# ---- HTTP 获取：带重试、合理头、编码处理 ----
def _http_get(url: str, timeout: int = 15) -> requests.Response:
    sess = requests.Session()
    # 比默认更像浏览器，提升可达性
    headers = dict(config.UA or {})
    headers.setdefault("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8")
    headers.setdefault("Accept-Language", "en-US,en;q=0.9")
    headers.setdefault("Cache-Control", "no-cache")
    r = sess.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    # 让 requests 自动以 apparent_encoding 回填（对 text/html 有帮助）
    if not r.encoding or r.encoding.lower() == "iso-8859-1":
        r.encoding = r.apparent_encoding or r.encoding
    return r

# ---- JSON-LD 标题提取（优先级最高，常见于新闻/学术/博客）----
def _title_from_jsonld(soup: BeautifulSoup) -> Optional[str]:
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = tag.string or tag.get_text() or ""
            if not data.strip():
                continue
            obj = json.loads(data)
            items = obj if isinstance(obj, list) else [obj]
            for it in items:
                if not isinstance(it, dict):
                    continue
                # 常见类型
                typ = it.get("@type")
                if isinstance(typ, list):
                    types = [t.lower() for t in typ if isinstance(t, str)]
                else:
                    types = [typ.lower()] if isinstance(typ, str) else []
                if any(t in ("article","newsarticle","blogposting","webpage","scholarlyarticle","report") for t in types):
                    t1 = it.get("headline") or it.get("name") or it.get("alternativeHeadline")
                    if isinstance(t1, str) and t1.strip():
                        return t1.strip()
                # 某些站点把主体包到 mainEntity
                main = it.get("mainEntity")
                if isinstance(main, dict):
                    t2 = main.get("headline") or main.get("name")
                    if isinstance(t2, str) and t2.strip():
                        return t2.strip()
        except Exception:
            continue
    return None

# ---- Meta 标题：OpenGraph / Twitter ----
def _title_from_meta(soup: BeautifulSoup) -> Optional[str]:
    # og:title
    og = soup.find("meta", attrs={"property": "og:title"}) or soup.find("meta", attrs={"name": "og:title"})
    if og and og.get("content"):
        return og["content"].strip()
    # twitter:title
    tw = soup.find("meta", attrs={"name": "twitter:title"})
    if tw and tw.get("content"):
        return tw["content"].strip()
    # dc.title
    dc = soup.find("meta", attrs={"name": "dc.title"})
    if dc and dc.get("content"):
        return dc["content"].strip()
    return None

# ---- 可见 <h1> 回退（过滤导航/登录等噪声）----
_NAV_WORDS = {"menu","navigation","nav","search","login","sign","home","about","contact","subscribe","cookie"}

def _title_from_headings(soup: BeautifulSoup) -> Optional[str]:
    # 优先找“像文章标题”的 h1
    for h in soup.find_all("h1"):
        txt = h.get_text(" ", strip=True)
        if 10 <= len(txt) <= 200 and not any(w in txt.lower() for w in _NAV_WORDS):
            return txt
    # 再尝试 h2（有些站标题在 h2）
    for h in soup.find_all("h2")[:3]:
        txt = h.get_text(" ", strip=True)
        if 10 <= len(txt) <= 200:
            return txt
    return None

# ---- <title> 标签兜底 ----
def _title_from_title_tag(soup: BeautifulSoup) -> Optional[str]:
    if soup.title and soup.title.string:
        t = soup.title.string.strip()
        # 去掉网站名常用分隔
        t = re.split(r"\s+[|-]\s+|\s+·\s+|\s+–\s+", t)[0].strip() or t
        return t
    return None

def extract_title_unified(html_doc: str) -> str:
    soup = BeautifulSoup(html_doc, "html.parser")
    for fn in (_title_from_jsonld, _title_from_meta, _title_from_headings, _title_from_title_tag):
        t = fn(soup)
        if t:
            return t
    return ""

# ---- 正文抽取：trafilatura → readability → 轻量回退 ----
def extract_main_text(html_doc: str, base_url: Optional[str] = None) -> str:
    from trafilatura import extract as t_extract
    # 先尝试多种提取方式，但不提前返回；最后进行合并去重，确保覆盖完整
    extracted_parts: List[str] = []
    try:
        # favor_recall=True 能从结构复杂页多拿点正文；不需要注释/表格
        t_text = t_extract(html_doc, include_comments=False, favor_recall=True, url=base_url) or ""
        if t_text.strip():
            extracted_parts.extend([s for s in t_text.split("\n\n") if s.strip()])
    except Exception:
        pass

    if HAS_READABILITY:
        try:
            doc = Document(html_doc)
            summary_html = doc.summary(html_partial=True)
            r_text = BeautifulSoup(summary_html, "html.parser").get_text("\n", strip=True)
            if r_text.strip():
                extracted_parts.extend([s for s in r_text.split("\n\n") if s.strip()])
        except Exception:
            pass

    # 结构化回退：遍历文档重要标签，过滤导航/页脚，尽可能保留各 section 的内容
    soup = BeautifulSoup(html_doc, "html.parser")

    # 移除明显无关的标签
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    def is_noise(node) -> bool:
        # 检查自身及祖先是否属于噪声区域
        noise_names = {"nav", "header", "footer", "aside"}
        noise_keys = [
            "nav", "menu", "breadcrumb", "sidebar", "footer", "cookie", "subscribe",
            "advert", "ads", "toc", "pagination"
        ]
        cur = node
        while cur and getattr(cur, "name", None) not in (None, "body"):
            name = getattr(cur, "name", "") or ""
            if name in noise_names:
                return True
            cls = " ".join(cur.get("class", [])).lower()
            idv = (cur.get("id", "") or "").lower()
            if any(k in cls for k in noise_keys) or any(k in idv for k in noise_keys):
                return True
            cur = cur.parent
        return False

    # 选择重要标签：标题、段落、列表项、定义列表、引用、表格单元、span（用于新闻条目）、a（带较长文本的链接）
    tag_order = ["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "dt", "dd", "blockquote", "td", "th", "span", "a"]
    parts: List[str] = []

    # 文档标题
    if soup.title and soup.title.string:
        title_text = soup.title.string.strip()
        if title_text:
            parts.append(title_text)

    # 顺序遍历并采集可见文本
    for tag in soup.find_all(tag_order):
        if is_noise(tag):
            continue
        txt = tag.get_text(" ", strip=True)
        if not txt:
            continue
        # 简单过滤：跳过过短/无信息片段
        if len(txt) < 2:
            continue
        # 列表项前缀
        if tag.name == "li" and not txt.startswith("-"):
            txt = f"- {txt}"
        parts.append(txt)

    # 去重并保序
    seen = set()
    uniq_parts: List[str] = []
    for s in parts:
        if s not in seen:
            seen.add(s)
            uniq_parts.append(s)

    # 合并不同提取器与结构化内容，做最终去重
    combined = []
    seen = set()
    for chunk in extracted_parts + uniq_parts:
        c = chunk.strip()
        if not c:
            continue
        if c in seen:
            continue
        seen.add(c)
        combined.append(c)

    text = "\n\n".join(combined).strip()
    return text or "[Empty after parse]"

# ---- 受限/动态站点识别（不给你突破登录，只做优雅退化）----
_BLOCK_HINTS = (
    "please enable javascript", "sign in", "log in", "subscribe", "are you a robot",
    "access denied", "verify you are human", "captcha"
)

def looks_likely_blocked(text: str) -> bool:
    t = text.lower()
    return any(k in t for k in _BLOCK_HINTS) or len(text.strip()) < 300

def _pick_snippet_for_url(url: str, snippet: str = "", prefer_same_domain: bool = True) -> str:
    """
    返回用于该 URL 的 snippet（优先使用调用方传入的 snippet；否则用 SearXNG 搜索结果里的一段预览文字）。
    - snippet（参数）通常来自你在 SERP 阶段拿到的 result["content"]。
    - 若未传入，则对 URL 本身做一次搜索，取同域命中或首条结果的 content 作为兜底。
    """
    if snippet:
        return snippet.strip()
    try:
        engines = config.SEARXNG_ENGINES_SNIPPET
        rows = searxng_search(url, engines=engines, pages=1, k_per_query=3) or []
        if not rows:
            return ""
        dom = domain_of(url)
        if prefer_same_domain:
            for it in rows:
                u = normalize_url(it.get("url") or "")
                if domain_of(u) == dom:
                    return (it.get("snippet") or "").strip()
        return (rows[0].get("snippet") or "").strip()
    except Exception:
        return ""


def fetch_text(url: str, max_chars: int = config.FETCH_MAX_CHARS, snippet: str = "") -> str:
    """
    Fetch & extract 主内容（HTML/PDF）。
    统一输出结构，**始终把 SNIPPET 放在最前**：
        SNIPPET: <来自搜索引擎的可见预览文字>
        TITLE:   <页面标题/推断标题>
        BODY:    <抽取到的正文，可能为空；若为受限/被拦截站点，此段可能缺失或极短>
        SOURCE:  <原始 URL>

    说明：
    - SNIPPET = search engine 结果页对该链接的简短预览文本（通常是标题+摘要片段），
      代表“用户在不点开网页时最能看到/认到的信息”。我们用它在被 403/登录墙 时兜底。
    """

    url_l = url.lower()

    # ---------- 1) 明确受限域：ResearchGate / X(Twitter) 等，直接走 snippet 预览 ----------
    if "researchgate.net/publication/" in url_l:
        # 只做“可公开识别”的摘要拼装：从 slug 推断标题 + snippet 置顶 + 源地址
        try:
            slug = url.split("/publication/")[1].split("/")[0]
        except Exception:
            slug = url.split("/publication/")[-1]
        # 从 slug 推断一个人类可读标题
        guessed_title = slug.replace("_", " ").strip()
        sn = _pick_snippet_for_url(url, snippet)

        parts = []
        if sn:
            parts.append(f"SNIPPET: {sn}")
        if guessed_title:
            parts.append(f"TITLE: {guessed_title}")
        parts.append(f"SOURCE: {url}")
        return clean_text("\n\n".join(parts), max_chars)

    if "x.com/" in url_l or "twitter.com/" in url_l or "researchgate.net/" in url_l or "scholar.google.com" in url_l:
        # 其它 RG/X 页面：同样不抓正文，直接走 snippet 兜底
        sn = _pick_snippet_for_url(url, snippet)
        parts = []
        if sn:
            parts.append(f"SNIPPET: {sn}")
        parts.append(f"SOURCE: {url}")
        return clean_text("\n\n".join(parts), max_chars)

    # ---------- 2) Scholar citations 页面直接跳过 ----------
    if "scholar.google.com/citations" in url_l:
        return "[Skip] Google Scholar citations page (JS-heavy)"

    # ---------- 3) 常规抓取（HTML/PDF），若 40x/429 则回退 snippet ----------
    try:
        r = requests.get(url, timeout=5, headers=config.UA)
        if not r.ok:
            # 403/401/429 等都走 snippet 兜底
            sn = _pick_snippet_for_url(url, snippet)
            parts = []
            if sn:
                parts.append(f"SNIPPET: {sn}")
            parts.append(f"[FetchError] HTTP {r.status_code} for {url}")
            parts.append(f"SOURCE: {url}")
            return clean_text("\n\n".join(parts), max_chars)

        ct = (r.headers.get("content-type") or "").lower()
        is_pdf = ("application/pdf" in ct) or url_l.endswith(".pdf")

        if is_pdf:
            try:
                from pdfminer.high_level import extract_text as pdf_extract
                text = pdf_extract(io.BytesIO(r.content)) or ""
                sn = _pick_snippet_for_url(url, snippet)
                parts = []
                if sn:
                    parts.append(f"SNIPPET: {sn}")
                if text.strip():
                    parts.append("TITLE: (from PDF)")
                    parts.append("BODY:\n" + text.strip())
                parts.append(f"SOURCE: {url}")
                return clean_text("\n\n".join(parts), max_chars)
            except Exception as e:
                sn = _pick_snippet_for_url(url, snippet)
                parts = []
                if sn:
                    parts.append(f"SNIPPET: {sn}")
                parts.append(f"[Skip] PDF extract failed: {e!r}")
                parts.append(f"SOURCE: {url}")
                return clean_text("\n\n".join(parts), max_chars)

        # HTML
        if ("text/html" not in ct) and ("application/xhtml" not in ct):
            sn = _pick_snippet_for_url(url, snippet)
            parts = []
            if sn:
                parts.append(f"SNIPPET: {sn}")
            parts.append(f"[Skip] Content-Type not HTML/PDF: {ct}")
            parts.append(f"SOURCE: {url}")
            return clean_text("\n\n".join(parts), max_chars)

        html_doc = r.text
        title = extract_title_unified(html_doc)  # 使用统一的标题提取函数
        body  = extract(html_doc) or ""  # trafilatura 主体抽取

        if not body.strip():
            # 轻量回退：取 <title> 与 h1/h2
            soup = BeautifulSoup(html_doc, "html.parser")
            heads = []
            if soup.title and soup.title.string:
                heads.append(soup.title.string.strip())
            for h in soup.find_all(["h1", "h2"])[:2]:
                heads.append(h.get_text(" ", strip=True))
            body = "\n".join(heads) or "[Empty after parse]"

        # ---- 统一拼装，**SNIPPET 始终放最前** ----
        sn = _pick_snippet_for_url(url, snippet)
        parts = []
        if sn:
            parts.append(f"SNIPPET: {sn}")
        if title:
            parts.append(f"TITLE: {title}")
        parts.append("BODY:\n" + body.strip())
        parts.append(f"SOURCE: {url}")

        return clean_text("\n\n".join(parts), max_chars)

    except Exception as e:
        sn = _pick_snippet_for_url(url, snippet)
        parts = []
        if sn:
            parts.append(f"SNIPPET: {sn}")
        parts.append(f"[FetchError] {e!r}")
        parts.append(f"SOURCE: {url}")
        return clean_text("\n\n".join(parts), max_chars)


def generate_natural_keyword_combinations(keywords: List[str]) -> List[str]:
    """
    Use commas to separate keywords for search queries
    For example: ["text generation", "diffusion model"] -> ["text generation, diffusion model"]
    
    Also normalizes keywords by removing hyphens and special characters.
    """
    if not keywords:
        return []
    
    # Normalize keywords: remove hyphens, replace with spaces
    normalized = []
    for kw in keywords:
        # Remove hyphens and normalize
        kw_normalized = kw.replace("-", " ").replace("_", " ")
        # Remove extra spaces
        kw_normalized = " ".join(kw_normalized.split())
        normalized.append(kw_normalized)
    
    # Join with comma
    return [", ".join(normalized)]


def build_conference_queries(spec: Any, default_confs: Dict[str, List[str]], cap: int = 120) -> List[str]:
    """Build search queries for conferences"""
    import schemas

    if isinstance(spec, dict):
        spec = schemas.QuerySpec.model_validate(spec)

    venues = spec.venues if spec.venues else list(default_confs.keys())
    aliases = []
    for v in venues:
        if v in default_confs:
            aliases += default_confs[v]
        else:
            aliases.append(v)
    aliases = [a for a in aliases if a]

    keywords = [k.strip('"') for k in (spec.keywords or [])]
    years = spec.years if spec.years else config.DEFAULT_YEARS
    years = sorted(years, reverse=True)

    # 生成自然的关键词组合
    keyword_combinations = generate_natural_keyword_combinations(keywords) if keywords else [""]
    # Build per-alias queues of (query, combined_keywords)
    per_alias: Dict[str, List[Tuple[str, str]]] = {}
    
    for alias in aliases:
        items: List[Tuple[str, str]] = []
        for year in years:
            if keyword_combinations:
                # 直接搜索论文：keywords + venue + year
                # 不加"conference", "accepted papers"等词，让搜索引擎返回具体论文
                for kw_combo in keyword_combinations:
                    if kw_combo:
                        # 直接搜论文：关键词 + 会议名 + 年份
                        items.append((f"{kw_combo} {alias} {year}", kw_combo))
                    else:
                        # 无关键词时，搜会议+年份（返回该会议当年的论文）
                        items.append((f"{alias} {year}", ""))
            else:
                # 没有关键词时，只用会议+年份
                items.append((f"{alias} {year}", ""))
        per_alias[alias] = items

    # Round-robin across aliases, prioritize newest years (already ordered),
    # and try to avoid repeating the same keyword consecutively.
    out: List[str] = []
    last_kw: str = ""
    indices: Dict[str, int] = {a: 0 for a in aliases}

    while len(out) < cap:
        progressed = False
        for alias in aliases:
            idx = indices.get(alias, 0)
            items = per_alias.get(alias, [])
            if idx >= len(items):
                continue

            # Prefer next item with a keyword different from last_kw if possible
            pick_idx = idx
            if keywords and last_kw:
                # Search ahead within a small window to find a different keyword
                window_end = min(idx + max(1, len(keywords)), len(items))
                found = False
                for j in range(idx, window_end):
                    _q, _kw = items[j]
                    if _kw != last_kw:
                        pick_idx = j
                        found = True
                        break
                if not found:
                    pick_idx = idx

            q, kw = items[pick_idx]
            # Advance index appropriately
            indices[alias] = pick_idx + 1

            # Deduplicate
            if not out or q != out[-1]:
                out.append(q)
                last_kw = kw or last_kw
                progressed = True
                if len(out) >= cap:
                    break
        if not progressed:
            break

    return out

# ============================ LLM-BASED PAPER SCORING ============================

def score_paper_with_llm(title: str, abstract: str, user_query: str, llm) -> int:
    """
    Use LLM to score paper relevance for academic talent search
    
    Args:
        title: Paper title
        abstract: Paper abstract or snippet
        user_query: User's search query (keywords, conferences, research areas)
        llm: LLM instance
        
    Returns:
        int: Score from 1-10 (10 being most relevant and worth crawling)
    """
    try:
        # Prepare the prompt
        prompt = f"""You are evaluating research papers for an academic talent search system. Score this paper's relevance to help find researchers working on specific topics.

Paper Title: {title}
Paper Abstract/Snippet: {abstract}

Target Research Query: {user_query}

Scoring Criteria (1-10 scale):

9-10 (Excellent Match - Must Crawl):
  • Paper directly addresses the query's topic/method/conference
  • Likely contains author information and research details
  • Academic publication (conference paper, journal article, or proceedings)
  • High value for finding relevant researchers

7-8 (Highly Relevant - Should Crawl):
  • Covers the main topic with strong overlap
  • Clearly a research paper with identifiable authors
  • Likely conference/journal publication or academic list
  • Good chance of finding relevant talent

5-6 (Moderately Relevant - Worth Considering):
  • Related to the research area but different focus
  • Could be academic content (workshop papers, surveys, lists)
  • May contain useful author information
  • Reasonable value if crawl budget allows

3-4 (Loosely Relevant - Low Priority):
  • Tangentially related or covers peripheral topics
  • Uncertain if it contains author/research details
  • May be informal content (blogs, news, slides)
  • Low expected value for talent search

1-2 (Not Relevant - Skip):
  • Different research domain or non-academic content
  • Unlikely to contain researcher information
  • Social media posts, general news, or spam
  • Not worth crawling resources

Key Evaluation Factors:
1. Topic Relevance: How well does it match the research query?
2. Author Discovery Value: Likely to contain author names and affiliations?
3. Content Type: Academic paper/proceedings vs informal content?
4. Information Completeness: Does the snippet provide enough signal?

Note: If the abstract/snippet is very short or vague, be slightly generous (give benefit of doubt) if the title suggests relevance.

Output ONLY a single integer from 1 to 10. No explanation, no other text."""

        # Get response from LLM
        response = llm.invoke(prompt)
        
        # Extract the score
        try:
            # Handle different response formats
            if hasattr(response, 'content'):
                score_text = response.content
            elif isinstance(response, dict) and 'text' in response:
                score_text = response['text']
            else:
                score_text = str(response)
            
            # Clean and extract numeric score
            score_text = score_text.strip()
            score = int(score_text)
            
            # Ensure score is within valid range
            if score < 1:
                score = 1
            elif score > 10:
                score = 10
                
            return score
            
        except (ValueError, TypeError):
            # If parsing fails, return a default middle score
            if config.VERBOSE:
                print(f"[score_paper_with_llm] Failed to parse score from: {score_text}")
            return 5
            
    except Exception as e:
        if config.VERBOSE:
            print(f"[score_paper_with_llm] Error scoring paper: {e}")
        return 5  # Default middle score on error


def llm_pick_urls(serp: List[Dict[str, str]], user_query: str, llm,
                  need: int = 20, max_per_domain: int = 6) -> List[Tuple[str, int]]:
    """
    Use LLM to score and pick top URLs based on title and abstract relevance
    
    Args:
        serp: Search engine results
        user_query: Original user query
        llm: LLM instance to use for scoring
        need: Number of top papers to return
        max_per_domain: Maximum papers per domain
        
    Returns:
        List of (url, score) tuples, sorted by score descending
    """
    import schemas
    from collections import defaultdict
    
    # Collect unique papers with their info
    papers_to_score = []
    seen_urls = set()
    
    for result in serp:
        url = normalize_url(result.get("url", "") or "")
        if not url.startswith("http") or url in seen_urls:
            continue
            
        seen_urls.add(url)
        
        # Extract title and abstract/snippet
        title = result.get("title", "").strip()
        abstract = result.get("snippet", "").strip()
        
        # Skip if no title
        if not title:
            continue
            
        papers_to_score.append({
            "url": url,
            "title": title,
            "abstract": abstract,
            "domain": domain_of(url)
        })
    
    # Score each paper using LLM (并发处理提高速度)
    scored_papers = []
    
    #  使用并发加速LLM打分
    from concurrent.futures import ThreadPoolExecutor, as_completed
    max_workers = getattr(config, "LLM_SELECT_MAX_WORKERS", 20)
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # 提交所有打分任务
        future_to_paper = {
            executor.submit(
                score_paper_with_llm,
                paper["title"],
                paper["abstract"],
                user_query,
                llm
            ): paper
            for paper in papers_to_score
        }
        
        # 收集结果
        for future in as_completed(future_to_paper):
            paper = future_to_paper[future]
            try:
                score = future.result()
                scored_papers.append({
                    **paper,
                    "score": score
                })
            except Exception as e:
                if config.VERBOSE:
                    print(f"[LLM Paper Scoring] Error scoring paper: {e}")
                # 失败时给默认分数
                scored_papers.append({
                    **paper,
                    "score": 5  # 中等分数
                })
    # 计算信息完整度得分 (completeness_score)
    def calc_completeness(paper):
        """计算论文信息的完整度得分"""
        completeness = 0.0
        title = paper.get("title", "")
        abstract = paper.get("abstract", "")
        
        # 标题存在且足够长 (+2分)
        if title and len(title) >= 20:
            completeness += 2.0
        
        # 摘要存在且足够长 (+3分)
        if abstract:
            if len(abstract) >= 300:
                completeness += 3.0
            elif len(abstract) >= 150:
                completeness += 2.0
            elif len(abstract) >= 50:
                completeness += 1.0
        
        # 标题中包含年份信息 (+0.5分)
        import re
        if re.search(r'20\d{2}', title):
            completeness += 0.5
        
        # URL 质量判断 (+1分)
        url = paper.get("url", "").lower()
        high_quality_domains = ["arxiv.org", "openreview.net", "aclanthology.org", 
                               "proceedings.neurips.cc", "proceedings.mlr.press"]
        if any(domain in url for domain in high_quality_domains):
            completeness += 1.0
        
        return completeness
    
    # 为每篇论文添加 completeness_score 和 relevant_tier
    for paper in scored_papers:
        paper["completeness_score"] = calc_completeness(paper)
        # 分桶：9分及以上为第一桶(tier=1)，其他为第二桶(tier=0)
        paper["relevant_tier"] = 1 if paper["score"] >= 9 else 0
    
    # 分层排序：先按 relevant_tier 降序，再按 completeness_score 降序，最后按 score 降序
    scored_papers.sort(
        key=lambda x: (x["relevant_tier"], x["completeness_score"], x["score"]),
        reverse=True
    )
    
    # 修改分数过滤：只处理分数 > 6 的论文（不包括6分）
    MIN_SCORE_THRESHOLD = 6
    scored_papers_filtered = [p for p in scored_papers if p["score"] > MIN_SCORE_THRESHOLD]
    
    if config.VERBOSE:
        tier1_count = sum(1 for p in scored_papers_filtered if p["relevant_tier"] == 1)
        tier0_count = len(scored_papers_filtered) - tier1_count
        print(f"[llm_pick_urls] Scored {len(scored_papers)} papers")
        print(f"[llm_pick_urls] Filtered: {len(scored_papers_filtered)} papers (score > {MIN_SCORE_THRESHOLD})")
        print(f"[llm_pick_urls]   - Tier 1 (score >= 9): {tier1_count} papers")
        print(f"[llm_pick_urls]   - Tier 0 (6 < score < 9): {tier0_count} papers")
    
    # Apply domain limits and select top papers
    domain_counts = defaultdict(int)
    selected = []
    
    for paper in scored_papers_filtered:
        domain = paper["domain"]
        
        # Check domain limit
        if domain_counts[domain] >= max_per_domain:
            continue
            
        selected.append((paper["url"], paper["score"]))
        domain_counts[domain] += 1
        
        if len(selected) >= need:
            break
    
    return selected
# ============================ URL SELECTION FUNCTIONS ============================

def heuristic_pick_urls(serp: List[Dict[str, str]], keywords: List[str],
                       need: int = 16, max_per_domain: int = 4) -> List[str]:
    """Heuristically pick URLs worth fetching"""

    count_by_dom: Dict[str, int] = {}
    seen_url = set()
    cand = []
    kws_l = [k.lower() for k in keywords] if keywords else []

    for r in serp:
        u = normalize_url(r.get("url", "") or "")
        if not u.startswith("http"):
            continue
        if u in seen_url:
            continue
        dom = domain_of(u)
        seen_url.add(u)
        cand.append((u, dom, (r.get("title") or ""), (r.get("snippet") or "")))

    def score(item):
        _u, dom, title, snip = item
        text = (title + " " + snip).lower()
        s = 0
        s += sum(2 for k in config.ACCEPT_HINTS if k in text)
        s += sum(1 for k in kws_l if k and k in text)
        s += min(len(title) // 40, 3)
        if looks_like_profile_url(_u):
            s += 1
        return s

    cand.sort(key=score, reverse=True)
    out = []
    for u, dom, _t, _s in cand:
        if count_by_dom.get(dom, 0) >= max_per_domain:
            continue
        out.append(u)
        count_by_dom[dom] = count_by_dom.get(dom, 0) + 1
        if len(out) >= need:
            break
    return out