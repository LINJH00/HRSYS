"""Crawl jiqizhixin.com via public JSON API v4.

This version avoids dynamic rendering by directly requesting
https://www.jiqizhixin.com/api/v4/articles.json

For each article we still访问真正的详情 HTML 以获取完整正文。"""
from __future__ import annotations

import json
import random
import time
from pathlib import Path
from typing import List

import requests
# HTML parser for list 'content' and for detail page
from bs4 import BeautifulSoup
from tqdm import tqdm

BASE = "https://www.jiqizhixin.com"
API = f"{BASE}/api/v4/articles.json"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Ubuntu; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

# 文章详情 API，根据 slug 返回完整正文 HTML
DETAIL_API = f"{BASE}/api/v4/articles/{{slug}}"


def fetch_json(page: int, per: int = 20) -> dict:
    params = {"sort": "time", "page": page, "per": per}
    r = requests.get(API, params=params, headers=HEADERS, timeout=10)
    r.raise_for_status()
    return r.json()


def parse_article_from_json(item: dict) -> dict:
    """Fetch full text via detail API and build structured record."""
    slug = item["slug"]
    url = f"{BASE}/articles/{slug}"

    # 调用详情 API 获取完整 HTML 正文
    try:
        detail_json = requests.get(
            DETAIL_API.format(slug=slug), headers=HEADERS, timeout=10
        ).json()
        raw_html = detail_json.get("content", "")
    except Exception:
        # 回退到列表接口的 content 字段（可能只有摘要）
        raw_html = item.get("content", "")

    soup = BeautifulSoup(raw_html, "lxml")

    def absolutize(u: str) -> str:
        return u if u.startswith("http") else BASE + u

    parts = []
    for node in soup.descendants:
        # 图片处理逻辑已注释，只保留文字内容
        # if getattr(node, "name", None) == "img":
        #     u = node.get("src") or node.get("data-src") or node.get("data-original")
        #     if u:
        #         parts.append(absolutize(u))
        # elif isinstance(node, str):
        if isinstance(node, str):
            txt = node.strip()
            if txt:
                parts.append(txt)

    text = " ".join(parts).strip()

    # 仅保留日期
    raw_date = item.get("publishedAt", "")
    base_part = raw_date.split("T")[0] if "T" in raw_date else raw_date[:10]
    date_short = base_part.replace("/", "-")

    return {
        "url": url,
        "title": item.get("title", ""),
        "date": date_short,
        "content": text,
    }


def generate_timestamped_filename(base_filename: str) -> str:
    """生成带时间戳的文件名"""
    import datetime
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path_obj = Path(base_filename)
    name_without_ext = path_obj.stem
    extension = path_obj.suffix
    
    return str(path_obj.parent / f"{name_without_ext}_{timestamp}{extension}")


def crawl(out: str = "articles.jsonl", days: int | None = 7) -> None:
    # 生成带时间戳的文件名
    timestamped_out = generate_timestamped_filename(out)
    Path(timestamped_out).parent.mkdir(parents=True, exist_ok=True)
    saved = 0
    page = 1
    per = 20
    cutoff_date: str | None = None
    if days is not None and days > 0:
        cutoff_date = (time.strftime("%Y-%m-%d", time.localtime(time.time() - days * 86400)))

    with open(timestamped_out, "w", encoding="utf-8") as fp:
        pbar = tqdm(desc="Crawling")
        stop = False
        while not stop:
            data = fetch_json(page, per)
            articles: List[dict] = data.get("articles", [])
            # 确保最新文章在前，便于遇到日期越界时立即停止
            articles.sort(key=lambda x: x.get("publishedAt", ""), reverse=True)
            if not articles:
                break  # no more pages
            for art in articles:
                try:
                    record = parse_article_from_json(art)
                    if cutoff_date and record["date"] < cutoff_date:
                        stop = True
                        break
                    fp.write(json.dumps(record, ensure_ascii=False) + "\n")
                    saved += 1
                    pbar.update(1)
                    time.sleep(random.uniform(1.5, 2.5))
                except Exception as err:
                    print(f"Failed {art.get('slug')}: {err}")
            if stop:
                break
            page += 1
        pbar.close()
    print(f"Saved {saved} articles into {timestamped_out}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Crawl jiqizhixin via API v4")
    parser.add_argument("--out", default="data/articles.jsonl", help="Output jsonl path")
    parser.add_argument("--days", type=int, default=7, help="Back-fill days window")
    args = parser.parse_args()

    crawl(args.out, args.days)
