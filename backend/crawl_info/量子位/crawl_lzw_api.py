"""Crawl qbitai.com home page and save article title + full text.o

The site renders static HTML (WordPress). Each article link in <article>.
"""
from __future__ import annotations

import json
import random
import time
from pathlib import Path
from typing import List

import requests
from bs4 import BeautifulSoup
import warnings
from bs4 import MarkupResemblesLocatorWarning

# suppress warning about URL-like strings in BeautifulSoup
warnings.filterwarnings("ignore", category=MarkupResemblesLocatorWarning)
from tqdm import tqdm

BASE = "https://www.qbitai.com"
LIST_URL = BASE + "/"  # 首页
HEADERS = {"User-Agent": "qbitai-crawler/0.1"}


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
    soup = BeautifulSoup(html, "lxml")
    results = []
    # Prefer explicit title selector (single-post listing)
    for a_tag in soup.select("h2.entry-title a[href]"):
        url = a_tag["href"]
        title = a_tag.get_text(strip=True)
        if not url.startswith("http"):
            url = BASE + url
        results.append({"url": url, "title": title})
    # Fallback to any <article><a>
    if not results:
        for art in soup.select("article"):
            a_tag = art.find("a", href=True)
            if not a_tag:
                continue
            url = a_tag["href"]
            title = a_tag.get_text(strip=True)
            if not url.startswith("http"):
                url = BASE + url
            results.append({"url": url, "title": title})
    # Second fallback: homepage blocks
    if not results:
        for a_tag in soup.select("div.article_list div.picture_text h4 a[href]"):
            url = a_tag["href"]
            title = a_tag.get_text(strip=True)
            if not url.startswith("http"):
                url = BASE + url
            results.append({"url": url, "title": title})
    return results


def fetch_detail(url: str) -> tuple[str, str, str]:
    """Return (title, date, content)"""
    html = fetch_html(url)
    soup = BeautifulSoup(html, "lxml")

    title_tag = soup.select_one("h1.entry-title") or soup.select_one("h1")
    title = title_tag.get_text(strip=True) if title_tag else ""

    content_node = (
        soup.select_one("div.entry-content")
        or soup.select_one("div.article-content")
        or soup.select_one("div.article__content")
        or soup.select_one("div.article")
    )

    def absolutize(u: str) -> str:
        return u if u.startswith("http") else BASE + u

    def collect_parts(node) -> str:
        segments = []
        for child in node.descendants:
            # 图片处理逻辑已注释，只保留文字内容
            # if getattr(child, "name", None) == "img":
            #     url = child.get("src") or child.get("data-src") or child.get("data-original")
            #     if url:
            #         segments.append(absolutize(url))
            # else:
            txt = BeautifulSoup(str(child), "lxml").get_text(" ", strip=True)
            if txt:
                segments.append(txt)
        return " ".join(segments).strip()

    if content_node:
        text = collect_parts(content_node)
    else:
        text = ""

    # date extraction: meta tag or span.single_date
    date_meta = soup.select_one('meta[property="article:published_time"]')
    date_span = soup.select_one('span.date') or soup.select_one('span.single_date')
    date = ""
    if date_meta and date_meta.has_attr('content'):
        date = date_meta['content'][:10]
    elif date_span:
        date = date_span.get_text(strip=True)[:10]

    return title, date, text


def generate_timestamped_filename(base_filename: str) -> str:
    """生成带时间戳的文件名"""
    import datetime
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path_obj = Path(base_filename)
    name_without_ext = path_obj.stem
    extension = path_obj.suffix
    
    return str(path_obj.parent / f"{name_without_ext}_{timestamp}{extension}")


def crawl(out: str = "qbitai_articles.jsonl", days: int | None = 7) -> None:
    # 生成带时间戳的文件名
    timestamped_out = generate_timestamped_filename(out)
    Path(timestamped_out).parent.mkdir(parents=True, exist_ok=True)

    if days is not None and days > 0:
        import datetime
        cutoff_date = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    else:
        cutoff_date = None

    def page_url(i: int) -> str:
        return LIST_URL if i == 1 else f"https://www.qbitai.com/page/{i}"

    saved_records = []
    page = 1
    stop = False
    while not stop:
        try:
            html = fetch_html(page_url(page))
        except Exception as err:
            print("[qbitai] page fetch failed", page, err)
            break
        items = parse_list(html)
        if not items:
            break
        for info in items:
            title2, date_tmp, content_tmp = fetch_detail(info["url"])
            if cutoff_date and date_tmp and date_tmp < cutoff_date:
                stop = True
                break
            saved_records.append({
                "url": info["url"],
                "title": title2 or info["title"],
                "date": date_tmp,
                "content": content_tmp,
            })
        if stop:
            break
        page += 1

    with open(timestamped_out, "w", encoding="utf-8") as fp:
        for rec in tqdm(saved_records, desc="Saving"):
            fp.write(json.dumps(rec, ensure_ascii=False) + "\n")
            time.sleep(random.uniform(1, 2))
    print(f"Saved {len(saved_records)} articles into {timestamped_out}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Crawl qbitai home page")
    parser.add_argument("--days", type=int, default=7, help="Back-fill days window")
    parser.add_argument("--out", default="data/qbitai.jsonl", help="output file")
    args = parser.parse_args()

    crawl(args.out, args.days)
