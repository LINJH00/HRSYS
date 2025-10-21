from __future__ import annotations

import json
import random
import time
import datetime
from pathlib import Path
from typing import List

import requests
from bs4 import BeautifulSoup
import warnings
from bs4 import MarkupResemblesLocatorWarning

# suppress warning about URL-like strings in BeautifulSoup
warnings.filterwarnings("ignore", category=MarkupResemblesLocatorWarning)
from tqdm import tqdm

BASE = "https://techcrunch.com"
# TechCrunch Artificial Intelligence category page
LIST_URL = f"{BASE}/category/artificial-intelligence/"
HEADERS = {"User-Agent": "qbitai-crawler/0.1"} # Switched back to a less common crawler user agent


def fetch_html(url: str, timeout: int = 20, retry: int = 3) -> str:
    """Fetch URL with simple retry to handle occasional disconnects."""
    last_err = None
    for _ in range(retry):
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout)
            r.raise_for_status()
            return r.text
        except requests.RequestException as err:
            last_err = err
            time.sleep(random.uniform(1, 2))
            continue
    # if still failing, raise the last error
    raise last_err


def parse_list(html: str) -> List[dict]:
    """
    Returns a list of dicts: [{"url": url, "title": title, "date": date_from_url}].
    Extract date directly from URL for better reliability.
    """
    import re
    
    soup = BeautifulSoup(html, "lxml")
    results = []
    seen = set()

    # Find all links that look like TechCrunch article URLs
    for a_tag in soup.select("a[href]"):
        href = a_tag.get("href", "")
        
        # Ensure it's a full TechCrunch URL
        if not href.startswith("https://techcrunch.com/"):
            continue
            
        # Clean URL (remove query params and fragments)
        url = href.split("?", 1)[0].split("#", 1)[0]
        
        if url in seen:
            continue
        
        # Extract date from URL pattern: /YYYY/MM/DD/
        date_match = re.search(r'/(\d{4}/\d{2}/\d{2})/', url)
        if not date_match:
            continue  # Skip URLs without date pattern
            
        # Convert to YYYY-MM-DD format
        date_from_url = date_match.group(1).replace('/', '-')
        
        # Extract title from link text, fallback to URL parsing
        title = a_tag.get_text(strip=True)
        if not title:
            # Extract title from URL as fallback
            title = url.split("/")[-2].replace("-", " ").title() if "/" in url else "Unknown Title"
            
        seen.add(url)
        
        results.append({"url": url, "title": title, "date": date_from_url})

    return results


def fetch_detail(url: str) -> tuple[str, str]:
    """Return (title, content) for TechCrunch article. Date is already extracted from URL."""
    html = fetch_html(url)
    soup = BeautifulSoup(html, "lxml")

    # Title: Extract from detail page
    title_tag = soup.find("h1")
    title = title_tag.get_text(strip=True) if title_tag else ""

    # Content block: Use common TechCrunch content selectors
    content_node = (
        soup.select_one("div.article-content")
        or soup.select_one("div.article__content")
        or soup.select_one("div.entry-content")
    )

    # Collect content: Only collect paragraphs
    def collect_paragraphs(node) -> str:
        pieces = [p.get_text(" ", strip=True) for p in node.find_all("p") if p.get_text(strip=True)]
        return "\n".join(pieces).strip()

    content = collect_paragraphs(content_node) if content_node else ""

    return title, content


def generate_timestamped_filename(base_filename: str) -> str:
    """生成带时间戳的文件名"""
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path_obj = Path(base_filename)
    name_without_ext = path_obj.stem
    extension = path_obj.suffix
    
    return str(path_obj.parent / f"{name_without_ext}_{timestamp}{extension}")


def crawl(out: str = "data/techcrunch_ai.jsonl", days: int | None = 7) -> None:
    """
    Main crawl logic using URL-based date filtering.
    Much more reliable than parsing dates from article content.
    每次爬取生成带时间戳的独立文件。
    """
    # 生成带时间戳的文件名
    timestamped_out = generate_timestamped_filename(out)
    Path(timestamped_out).parent.mkdir(parents=True, exist_ok=True)

    if days is not None and days > 0:
        cutoff_date = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    else:
        cutoff_date = None

    def page_url(i: int) -> str:
        # TechCrunch category page uses "/page/N/" for pagination
        return LIST_URL if i == 1 else f"{LIST_URL}page/{i}/"

    final_records = []
    page = 1
    max_pages = 20

    while page <= max_pages:
        page_list_url = page_url(page)
        print(f"\nFetching page {page}: {page_list_url}")
        
        try:
            html = fetch_html(page_list_url)
        except Exception as err:
            print(f"[TechCrunch] Page fetch failed for {page_list_url}: {err}")
            break
        
        items = parse_list(html)
        if not items:
            print(f"[TechCrunch] No articles found on page {page}. Stopping.")
            break
        
        # 在列表页就进行日期过滤
        articles_to_crawl = []
        old_articles_found = False
        
        for info in items:
            article_date = info["date"]
            
            # 检查日期是否在范围内
            if cutoff_date is None or article_date >= cutoff_date:
                articles_to_crawl.append(info)
            else:
                print(f"Old article found: {article_date} < {cutoff_date} - {info['title'][:50]}...")
                old_articles_found = True
        
        print(f"Page {page}: {len(articles_to_crawl)} articles to crawl, {len(items) - len(articles_to_crawl)} filtered by date")
        
        # 如果这页有旧文章，处理完当前符合条件的文章后就停止
        if old_articles_found:
            print(f"Found old articles on page {page}. Will stop after processing current articles.")
        
        # 爬取符合日期要求的文章详情
        failed_count = 0
        for i, info in enumerate(tqdm(articles_to_crawl, desc=f"Fetching Details - Page {page}")):
            url = info["url"]
            
            try:
                title_detail, content = fetch_detail(url)
            except Exception as e:
                failed_count += 1
                print(f"Failed to fetch article {i+1}/{len(articles_to_crawl)}: {url} - {e}")
                continue
            
            final_records.append({
                "url": url,
                "title": title_detail or info["title"],
                "date": info["date"],
                "content": content,
            })
            
            time.sleep(random.uniform(1, 2))
        
        print(f"Page {page} results: {len(articles_to_crawl) - failed_count} successful, {failed_count} failed")
        
        # 如果这页有旧文章，停止爬取
        if old_articles_found:
            print("Stopping crawl due to old articles found.")
            break
            
        page += 1
        time.sleep(random.uniform(2, 4))
    
    print(f"\n=== Final Results ===")
    print(f"Successfully saved articles: {len(final_records)}")

    with open(timestamped_out, "w", encoding="utf-8") as fp:
        for rec in tqdm(final_records, desc="Saving"):
            fp.write(json.dumps(rec, ensure_ascii=False) + "\n")
            
    print(f"\nSuccessfully saved {len(final_records)} articles into {timestamped_out}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Crawl TechCrunch AI category with pagination and date limit.")
    parser.add_argument("--days", type=int, default=7, help="Back-fill days window (0 for no date limit)")
    parser.add_argument("--out", default="data/techcrunch_ai.jsonl", help="output file")
    args = parser.parse_args()

    crawl(args.out, args.days)