# semanticscholar_title2authors.py
from __future__ import annotations
import requests
from dataclasses import dataclass
from typing import List, Dict, Optional, Union, Any
import time
import re
import threading
from schemas import PaperAuthorsResult, AuthorWithId

BASE_URL = "https://api.semanticscholar.org/graph/v1"

@dataclass
class Author:
    authorId: str
    name: str

@dataclass
class MatchPaper:
    paperId: str
    title: str
    matchScore: Optional[float]
    year: Optional[int]
    venue: Optional[str]
    url: Optional[str]
    authors: List[Author]

class SemanticScholarClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        timeout: float = 10.0,
        max_retries: int = 3,
        requests_per_second: float = 1.0,   # ★ 新增：速率限制（默认 1 req/s）
        user_agent: str = "Title2Authors/0.1 (+https://example.com)"
    ):
        """
        requests_per_second: 全局速率限制（最小时间间隔 = 1 / rps），作用于所有请求（含重试）。
        """
        self.session = requests.Session()
        self.timeout = timeout
        self.max_retries = max_retries

        # headers
        self.session.headers.update({"User-Agent": user_agent})
        if api_key:
            self.session.headers.update({"x-api-key": api_key})

        # ★ 线程安全的节流器
        self._rps = max(0.01, requests_per_second)
        self._min_interval = 1.0 / self._rps
        self._last_call_ts = 0.0
        self._throttle_lock = threading.Lock()

    # ★ 节流：确保两次请求之间至少相隔 _min_interval 秒
    def _throttle(self):
        with self._throttle_lock:
            now = time.monotonic()
            wait = self._min_interval - (now - self._last_call_ts)
            if wait > 0:
                time.sleep(wait)
                now = time.monotonic()
            self._last_call_ts = now

    def _get(self, path: str, params: Dict) -> dict:
        url = f"{BASE_URL}{path}"
        backoff = 1.0
        for attempt in range(self.max_retries):
            try:
                # ★ 在每次实际请求前节流
                self._throttle()
                resp = self.session.get(url, params=params, timeout=self.timeout)

                if resp.status_code == 429:
                    # 命中官方限流，再做指数退避（与节流叠加更稳妥）
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 8.0)
                    continue

                resp.raise_for_status()
                # ★ 修复：返回完整 JSON（不同端点结构不同，这里不要提前取 ["data"]）
                return resp.json()

            except requests.HTTPError:
                # 400/404 等直接返回空；其他继续重试
                if resp is not None and resp.status_code in (400, 404):
                    return {}
                if attempt == self.max_retries - 1:
                    raise
                time.sleep(backoff)
                backoff = min(backoff * 2, 8.0)
        return {}

    @staticmethod
    def _normalize_title(t: str) -> str:
        # 经验：连字符在搜索里可能匹配差，替换为空格；去掉多余空白
        t = re.sub(r"[-–—]+", " ", t)
        t = re.sub(r"\s+", " ", t).strip()
        return t

    def search_match(
        self,
        title: str,
        year: Optional[str] = None,
        venue: Optional[Union[str, List[str]]] = None,
        fields_of_study: Optional[str] = None
    ) -> Optional[MatchPaper]:
        """
        调用 /paper/search/match 拿最接近标题的论文，并尽量直接把作者带回
        """
        q = self._normalize_title(title)
        params = {
            "query": q,
            # 直接要作者，省一次请求；顺便把常用元信息带回，便于做置信度与二次过滤
            "fields": "title,authors,url,year,venue"
        }
        if year:
            params["year"] = year           # 例如 "2025" 或 "2023-2025"
        if venue:
            # ★ 支持 list[str] 或 str；S2 用逗号分隔多个 venue
            if isinstance(venue, (list, tuple)):
                params["venue"] = ",".join(venue)
            else:
                params["venue"] = venue
        if fields_of_study:
            params["fieldsOfStudy"] = fields_of_study  # 例如 "Computer Science"

        j = self._get("/paper/search/match", params)
        # ★ 该端点返回 {"data": [ {paper...} ]}；可能 404 时前面已返回 {}
        items = j.get("data", []) if isinstance(j, dict) else []
        if not items:
            return None
        item = items[0]

        match_score = item.get("matchScore")
        authors = [Author(a.get("authorId", ""), a.get("name", "")) for a in item.get("authors", [])]
        return MatchPaper(
            paperId=item.get("paperId", ""),
            title=item.get("title", ""),
            matchScore=match_score,
            year=item.get("year"),
            venue=item.get("venue"),
            url=item.get("url"),
            authors=authors
        )

    def get_paper_authors(self, paper_id: str, limit: int = 1000) -> List[Author]:
        """
        兜底接口：/paper/{paper_id}/authors
        """
        params = {
            "limit": limit,
            "fields": "name"  # 默认还有 authorId
        }
        j = self._get(f"/paper/{paper_id}/authors", params)
        # ★ 该端点返回 {"offset":..., "next":..., "data":[ {...}, ... ]}
        data_list = j.get("data", []) if isinstance(j, dict) else []
        authors = []
        for item in data_list:
            authors.append(Author(item.get("authorId", ""), item.get("name", "")))
        return authors

    def authors_by_title(
        self,
        title: str,
        min_score: float = 0.80,
        year: Optional[str] = None,
        venue: Optional[str] = None,
        fields_of_study: Optional[str] = None
    ) -> List[str]:
        """
        给标题 -> 返回作者名字列表（置信度不够或找不到则返回 []）
        min_score: 如果返回里带 matchScore，就用它做阈值；没有则按存在就接受
        """
        m = self.search_match(title, year=year, venue=venue, fields_of_study=fields_of_study)
        if not m:
            return []
        if m.matchScore is not None and m.matchScore < min_score:
            return []
        # 如果已经带作者就直接用；否则再查一次
        authors = m.authors or self.get_paper_authors(m.paperId)
        # 去重 + 保序
        seen = set()
        names = []
        for a in authors:
            key = (a.name or "").strip()
            if key and key not in seen:
                seen.add(key)
                names.append(key)
        return names

    def authors_for_title_map(
        self,
        url_to_title: Dict[str, str],
        min_score: float = 0.80,
        year_hint: Optional[str] = None,
        venue_hint: Optional[str] = None
    ) -> Dict[str, List[str]]:
        """
        批量处理：输入 {任意键: 标题}，输出 {同样的键: 作者列表或 []}
        （批量方法自动遵循全局速率限制与 429 退避）
        """
        out: Dict[str, List[str]] = {}
        for k, t in url_to_title.items():
            try:
                out[k] = self.authors_by_title(
                    t, min_score=min_score, year=year_hint, venue=venue_hint
                )
            except Exception:
                out[k] = []
        return out

    def search_paper_with_authors(
        self,
        url: str,
        paper_name: str,
        min_score: float = 0.80,
        year_hint: Optional[str] = None,
        venue_hint: Optional[str] = None
    ) -> PaperAuthorsResult:
        """
        搜索论文并返回完整的 PaperAuthorsResult
        """
        # 使用现有的 search_match 方法
        match_paper = self.search_match(
            paper_name,
            year=year_hint,
            venue=venue_hint
        )

        if not match_paper or (match_paper.matchScore is not None and match_paper.matchScore < min_score):
            # 论文未找到或匹配度不够
            return PaperAuthorsResult(
                url=url,
                paper_name=paper_name,
                found=False
            )

        # 论文找到，转换作者信息
        authors_with_id = [
            AuthorWithId(name=author.name, author_id=author.authorId)
            for author in match_paper.authors
        ]

        return PaperAuthorsResult(
            url=url,
            paper_name=paper_name,
            paper_id=match_paper.paperId,
            match_score=match_paper.matchScore,
            year=match_paper.year,
            venue=match_paper.venue,
            paper_url=match_paper.url,
            authors=authors_with_id,
            found=True
        )

    def search_papers_with_authors_batch(
        self,
        url_to_title: Dict[str, str],
        min_score: float = 0.80,
        year_hint: Optional[str] = None,
        venue_hint: Optional[str] = None
    ) -> List['PaperAuthorsResult']:
        """
        批量搜索论文并返回完整的 PaperAuthorsResult 列表
        """
        results = []
        for url, paper_name in url_to_title.items():
            try:
                result = self.search_paper_with_authors(
                    url=url,
                    paper_name=paper_name,
                    min_score=min_score,
                    year_hint=year_hint,
                    venue_hint=venue_hint
                )
                results.append(result)
            except Exception as e:
                # 如果出错，返回未找到的结果
                from schemas import PaperAuthorsResult
                results.append(PaperAuthorsResult(
                    url=url,
                    paper_name=paper_name,
                    found=False
                ))
        return results

    def get_author_papers(
        self,
        author_id: str,
        limit: int = 50,
        sort: str = "citationCount",
        year_filter: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        根据作者ID获取该作者的所有论文
        
        Args:
            author_id: Semantic Scholar作者ID
            limit: 返回论文数量限制
            sort: 排序方式 ("citationCount", "publicationDate")
            year_filter: 年份过滤，如 "2020-2025"
            
        Returns:
            论文信息列表
        """
        params = {
            "limit": limit,
            "sort": sort,
            "fields": "title,year,venue,citationCount,url,abstract,authors"
        }
        
        if year_filter:
            params["year"] = year_filter
            
        try:
            response = self._get(f"/author/{author_id}/papers", params)
            papers_data = response.get("data", []) if isinstance(response, dict) else []
            
            papers = []
            for paper in papers_data:
                paper_info = {
                    "title": paper.get("title", ""),
                    "year": paper.get("year"),
                    "venue": paper.get("venue", ""),
                    "citationCount": paper.get("citationCount", 0),
                    "url": paper.get("url", ""),
                    "abstract": paper.get("abstract", ""),
                    "authors": [author.get("name", "") for author in paper.get("authors", [])]
                }
                papers.append(paper_info)
                
            return papers
            
        except Exception as e:
            print(f"[S2 Author Papers] Error fetching papers for author {author_id}: {e}")
            return []

    def get_author_profile_info(self, author_id: str) -> Dict[str, Any]:
        """
        获取作者的详细profile信息
        
        Args:
            author_id: Semantic Scholar作者ID
            
        Returns:
            作者详细信息
        """
        params = {
            "fields": "name,aliases,affiliations,homepage,paperCount,citationCount,hIndex,url"
        }
        
        try:
            response = self._get(f"/author/{author_id}", params)
            if not response:
                return {}
                
            profile_info = {
                "name": response.get("name", ""),
                "aliases": response.get("aliases", []),
                "affiliations": response.get("affiliations", []),
                "homepage": response.get("homepage", ""),
                "paperCount": response.get("paperCount", 0),
                "citationCount": response.get("citationCount", 0),
                "hIndex": response.get("hIndex", 0),
                "url": response.get("url", "")
            }
            
            return profile_info
            
        except Exception as e:
            print(f"[S2 Author Profile] Error fetching profile for author {author_id}: {e}")
            return {}
