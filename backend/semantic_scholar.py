from __future__ import annotations
import requests
from dataclasses import dataclass
from typing import List, Dict, Optional, Union, Any
import time
import re
import threading
from pathlib import Path
import sys

# Use pathlib for robust path handling
current_dir = Path(__file__).parent
talent_search_module_dir = current_dir / "talent_search_module"
sys.path.insert(0, str(talent_search_module_dir))

from talent_search_module.schemas import PaperAuthorsResult, AuthorWithId

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
        requests_per_second: float = 1.0,
        user_agent: str = "TalentSearch/0.1 (+https://example.com)"
    ):
        self.session = requests.Session()
        self.timeout = timeout
        self.max_retries = max_retries
        self.session.headers.update({"User-Agent": user_agent})
        if api_key:
            self.session.headers.update({"x-api-key": api_key})
        self._rps = max(0.01, requests_per_second)
        self._min_interval = 1.0 / self._rps
        self._last_call_ts = 0.0
        self._throttle_lock = threading.Lock()

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
        resp = None
        for attempt in range(self.max_retries):
            try:
                self._throttle()
                resp = self.session.get(url, params=params, timeout=self.timeout)
                if resp.status_code == 429:
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 8.0)
                    continue
                resp.raise_for_status()
                return resp.json()
            except requests.HTTPError:
                if resp is not None and resp.status_code in (400, 404):
                    return {}
                if attempt == self.max_retries - 1:
                    raise
                time.sleep(backoff)
                backoff = min(backoff * 2, 8.0)
        return {}

    @staticmethod
    def _normalize_title(t: str) -> str:
        t = re.sub(r"[-–—]+", " ", t)
        t = re.sub(r"\s+", " ", t).strip()
        return t

    def search_match(self, title: str, year: Optional[str] = None, venue: Optional[Union[str, List[str]]] = None,
                     fields_of_study: Optional[str] = None) -> Optional[MatchPaper]:
        q = self._normalize_title(title)
        params = {"query": q, "fields": "title,authors,url,year,venue"}
        if year:
            params["year"] = year
        if venue:
            params["venue"] = ",".join(venue) if isinstance(venue, (list, tuple)) else venue
        if fields_of_study:
            params["fieldsOfStudy"] = fields_of_study
        j = self._get("/paper/search/match", params)
        items = j.get("data", []) if isinstance(j, dict) else []
        if not items:
            return None
        item = items[0]
        authors = [Author(a.get("authorId", ""), a.get("name", "")) for a in item.get("authors", [])]
        return MatchPaper(
            paperId=item.get("paperId", ""),
            title=item.get("title", ""),
            matchScore=item.get("matchScore"),
            year=item.get("year"),
            venue=item.get("venue"),
            url=item.get("url"),
            authors=authors,
        )

    def search_paper_with_authors(self, url: str, paper_name: str, min_score: float = 0.80,
                                  year_hint: Optional[str] = None, venue_hint: Optional[str] = None) -> PaperAuthorsResult:
        m = self.search_match(paper_name, year=year_hint, venue=venue_hint)
        if not m or (m.matchScore is not None and m.matchScore < min_score):
            return PaperAuthorsResult(url=url, paper_name=paper_name, found=False)
        authors_with_id = [AuthorWithId(name=a.name, author_id=a.authorId) for a in m.authors]
        return PaperAuthorsResult(url=url, paper_name=paper_name, paper_id=m.paperId, match_score=m.matchScore,
                                  year=m.year, venue=m.venue, paper_url=m.url, authors=authors_with_id, found=True)

    def get_author_papers(self, author_id: str, limit: int = 50, sort: str = "citationCount",
                           year_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        params = {"limit": limit, "sort": sort, "fields": "title,year,venue,citationCount,url,abstract,authors"}
        if year_filter:
            params["year"] = year_filter
        try:
            response = self._get(f"/author/{author_id}/papers", params)
            data = response.get("data", []) if isinstance(response, dict) else []
            out = []
            for p in data:
                out.append({
                    "title": p.get("title", ""),
                    "year": p.get("year"),
                    "venue": p.get("venue", ""),
                    "citationCount": p.get("citationCount", 0),
                    "url": p.get("url", ""),
                    "abstract": p.get("abstract", ""),
                    "authors": [a.get("name", "") for a in p.get("authors", [])],
                })
            return out
        except Exception as e:
            print(f"[S2 Author Papers] error: {e}")
            return []

    def get_author_profile_info(self, author_id: str) -> Dict[str, Any]:
        params = {"fields": "name,aliases,affiliations,homepage,paperCount,citationCount,hIndex,url"}
        try:
            j = self._get(f"/author/{author_id}", params)
            if not j:
                return {}
            return {
                "name": j.get("name", ""),
                "aliases": j.get("aliases", []),
                "affiliations": j.get("affiliations", []),
                "homepage": j.get("homepage", ""),
                "paperCount": j.get("paperCount", 0),
                "citationCount": j.get("citationCount", 0),
                "hIndex": j.get("hIndex", 0),
                "url": j.get("url", ""),
            }
        except Exception as e:
            print(f"[S2 Author Profile] error: {e}")
            return {}