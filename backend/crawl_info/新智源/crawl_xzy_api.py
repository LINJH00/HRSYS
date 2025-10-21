"""Crawl @AI_era timeline on link.baai.ac.cn and fetch linked hub.baai articles."""

from __future__ import annotations

import json
import random
import time
from pathlib import Path
from typing import List, Optional

import re
import requests
from bs4 import BeautifulSoup
from tqdm import tqdm


# ----------------- Config -----------------
BASE = "https://link.baai.ac.cn"
ACCOUNT = "AI_era"
HEADERS = {"User-Agent": "baai-crawler/0.2"}
PER_PAGE = 40

# hub article link pattern
HUB_PATTERN = re.compile(r"https?://hub\.baai\.ac\.cn/view/\d+")
# ------------------------------------------


def lookup_uid(acct: str) -> str:
    resp = requests.get(
        f"{BASE}/api/v1/accounts/lookup", params={"acct": acct}, headers=HEADERS, timeout=10
    )
    resp.raise_for_status()
    return resp.json()["id"]


def fetch_statuses(uid: str, max_id: Optional[str] = None) -> List[dict]:
    params = {"limit": PER_PAGE}
    if max_id:
        params["max_id"] = max_id
    url = f"{BASE}/api/v1/accounts/{uid}/statuses"
    r = requests.get(url, params=params, headers=HEADERS, timeout=10)
    r.raise_for_status()
    return r.json()


def fetch_hub_article(url: str) -> tuple[str, str]:
    r = requests.get(url, headers=HEADERS, timeout=10)
    r.raise_for_status()

    # # --- DEBUG: 保存首包 HTML 便于本地查看 ----
    # try:
    #     Path("debug").mkdir(exist_ok=True)
    #     debug_path = Path("debug/debug.html")
    #     debug_path.write_text(r.text, encoding="utf-8")
    # except Exception as _:
    #     pass  # 调试辅助，失败可忽略

    soup = BeautifulSoup(r.text, "lxml")

    # Title: prefer #post-title then generic <h1>
    title_tag = soup.select_one("#post-title") or soup.select_one("h1")
    title = title_tag.get_text(strip=True) if title_tag else ""

    # Content: inside #js_content (nested html) or .article-content fallback
    content_node = soup.select_one("#js_content")
    if not content_node:
        inner_node = soup.select_one("#post-content html")
        if inner_node:
            content_node = BeautifulSoup(str(inner_node), "lxml").select_one("#js_content")
    if not content_node:
        content_node = soup.select_one("div.article-content")

    def absolutize(u: str) -> str:
        return u if u.startswith("http") else "https://hub.baai.ac.cn" + u

    parts = []
    if content_node:
        for node in content_node.descendants:
            # 图片处理逻辑已注释，只保留文字内容
            # if getattr(node, "name", None) == "img":
            #     u = node.get("src") or node.get("data-src")
            #     if u:
            #         parts.append(absolutize(u))
            # elif isinstance(node, str):
            if isinstance(node, str):
                txt = node.strip()
                if txt:
                    parts.append(txt)
    text = " ".join(parts).strip()
    return title, text


def parse_status(item: dict) -> dict:
    raw_html = item["content"]
    soup = BeautifulSoup(raw_html, "lxml")
    text_short = soup.get_text(" ", strip=True)

    hub_link: Optional[str] = None
    # 查找<a href="..."> 指向 hub.baai 的链接
    for a in soup.find_all("a", href=True):
        if HUB_PATTERN.match(a["href"]):
            hub_link = a["href"]
            break

    hub_match = HUB_PATTERN.search(text_short) if not hub_link else None
    if hub_match:
        hub_link = hub_match.group()

    # 标准化日期，仅保留 YYYY-MM-DD
    def _short_date(dt_str: str) -> str:
        try:
            return dt_str.split("T")[0]
        except Exception:
            return dt_str[:10]

    date_short = _short_date(item["created_at"])

    if hub_link:
        try:
            title, full_text = fetch_hub_article(hub_link)
            return {
                "url": hub_link,
                "title": title or full_text[:40],
                "date": date_short,
                "content": full_text or text_short,
            }
        except Exception as err:
            print("Hub fetch failed", hub_link, err)

    title = text_short[:40] + ("…" if len(text_short) > 40 else "")
    return {
        "url": item["url"],
        "title": title,
        "date": date_short,
        "content": text_short,
    }


def generate_timestamped_filename(base_filename: str) -> str:
    """生成带时间戳的文件名"""
    import datetime
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path_obj = Path(base_filename)
    name_without_ext = path_obj.stem
    extension = path_obj.suffix
    
    return str(path_obj.parent / f"{name_without_ext}_{timestamp}{extension}")


def crawl(out: str = "ai_era_full.jsonl", days: int | None = 7) -> None:
    uid = lookup_uid(ACCOUNT)
    # 生成带时间戳的文件名
    timestamped_out = generate_timestamped_filename(out)
    Path(timestamped_out).parent.mkdir(parents=True, exist_ok=True)

    saved = 0
    cutoff_date: str | None = None
    if days is not None and days > 0:
        import datetime
        cutoff_date = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()

    max_id: Optional[str] = None
    with open(timestamped_out, "w", encoding="utf-8") as fp:
        pbar = tqdm(desc=f"Crawling @{ACCOUNT}")
        stop = False
        while not stop:
            statuses = fetch_statuses(uid, max_id)
            if not statuses:
                break
            for st in statuses:
                record = parse_status(st)
                if cutoff_date and record["date"] < cutoff_date:
                    stop = True
                    break
                fp.write(json.dumps(record, ensure_ascii=False) + "\n")
                saved += 1
                pbar.update(1)
            if stop:
                break
            max_id = statuses[-1]["id"]
            time.sleep(random.uniform(1, 2))
        pbar.close()
    print(f"Saved {saved} posts into {timestamped_out}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Crawl AI_era timeline and hub articles")
    parser.add_argument("--days", type=int, default=7, help="Back-fill days window")
    parser.add_argument("--out", default="data/AI_era.jsonl", help="Output file")
    args = parser.parse_args()

    crawl(args.out, args.days)
