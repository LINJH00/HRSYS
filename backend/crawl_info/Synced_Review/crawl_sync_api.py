from __future__ import annotations

import json
import random
import time
import datetime
from pathlib import Path
from typing import List, Optional

import requests
from bs4 import BeautifulSoup
import warnings
from bs4 import MarkupResemblesLocatorWarning

# suppress warning about URL-like strings in BeautifulSoup
warnings.filterwarnings("ignore", category=MarkupResemblesLocatorWarning)
from tqdm import tqdm
from urllib.parse import urljoin


# ----------------- Config -----------------
BASE = "https://syncedreview.com"
LIST_URL = f"{BASE}/"
HEADERS = {"User-Agent": "synced-crawler/0.1"}
# ------------------------------------------


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
    解析首页HTML，返回包含 URL, Title, Date 的字典列表。
    由于 SyncedReview 首页文章不提供 time tag，因此仅返回 URL 和 Title。
    """
    soup = BeautifulSoup(html, "lxml")
    results = []
    
    # SyncedReview 使用 h2.entry-title a[href] 包含文章链接
    for h2 in soup.select("h2.entry-title a[href]"):
        href = h2["href"]
        url = urljoin(BASE, href) # 确保链接为绝对路径
        title = h2.get_text(strip=True)
        
        # SyncedReview 首页列表没有时间信息，所以日期暂时为空
        results.append({"url": url, "title": title, "date": ""})
        
    return results


def fetch_detail(url: str) -> tuple[str, str, str]:
    """Return (title, date, content)"""
    html = fetch_html(url)
    soup = BeautifulSoup(html, "lxml")

    # Title: 使用 h1.entry-title 优先级更高
    title_tag = soup.select_one("h1.entry-title") or soup.find("h1") or soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else ""

    # Date: 从 time 标签或 post-date span 中提取
    date = ""
    time_tag = soup.find("time")
    if time_tag and time_tag.has_attr("datetime"):
        date = time_tag["datetime"][:10]
    else:
        # 尝试其他日期选择器
        date_span = soup.select_one("span.post-date") or soup.select_one(".post-meta span")
        if date_span:
            # 简单提取前10个字符，假设日期格式一致
            date = date_span.get_text(strip=True)[:10].replace('/', '-').strip()
            # 简单的日期格式校验，确保提取到的是像 YYYY-MM-DD 的内容
            if not date.replace('-', '').isdigit() or len(date) < 8: 
                 date = ""


    # Content block: 核心内容区域
    content_node = (
        soup.select_one("div.entry-content")
        or soup.select_one("div.article-content")
    )

    # Content extraction: 提取所有段落文本
    def collect_paragraphs(node) -> str:
        """从内容节点中收集所有段落文本，用换行符分隔"""
        pieces = []
        for p in node.find_all("p"):
            text = p.get_text(" ", strip=True)
            if text:
                pieces.append(text)
        return "\n".join(pieces).strip()

    content = collect_paragraphs(content_node) if content_node else ""

    return title, date, content


def generate_timestamped_filename(base_filename: str) -> str:
    """生成带时间戳的文件名"""
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path_obj = Path(base_filename)
    name_without_ext = path_obj.stem
    extension = path_obj.suffix
    
    return str(path_obj.parent / f"{name_without_ext}_{timestamp}{extension}")


def crawl(out: str = "data/synced.jsonl", days: int | None = 7) -> None:
    """
    主爬取函数，支持日期限制。
    注意：SyncedReview 首页没有传统分页（如 /page/2/），因此只抓取首页文章。
    每次爬取生成带时间戳的独立文件。
    """
    # 生成带时间戳的文件名
    timestamped_out = generate_timestamped_filename(out)
    Path(timestamped_out).parent.mkdir(parents=True, exist_ok=True)

    if days is not None and days > 0:
        cutoff_date = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    else:
        cutoff_date = None

    print(f"Fetching list page: {LIST_URL}")
    try:
        list_html = fetch_html(LIST_URL)
    except Exception as err:
        print(f"[SyncedReview] List page fetch failed: {err}")
        return

    # 从首页提取文章列表 (info 包含 url, title, date='')
    items = parse_list(list_html)
    
    saved_records = []
    
    # SyncedReview 首页文章数量有限，直接遍历
    for info in tqdm(items, desc="Crawling Articles"):
        url = info["url"]
        
        try:
            # 抓取详情页
            title_detail, date_detail, content_detail = fetch_detail(url)
        except requests.RequestException as e:
            print(f"Skip {url}: {e} (Network Error)")
            continue
        except Exception as e:
            print(f"Skip {url}: {e} (Parsing Error)")
            continue
        
        # 使用详情页的日期进行截止检查
        final_date = date_detail or info["date"] 
        if cutoff_date and final_date and final_date < cutoff_date:
            print(f"Date cutoff reached: {final_date} < {cutoff_date}. Stopping crawl.")
            break
            
        saved_records.append({
            "url": url,
            "title": title_detail or info["title"],
            "date": final_date,
            "content": content_detail,
        })
        time.sleep(random.uniform(1, 2)) # Be polite

    # 保存到带时间戳的文件
    with open(timestamped_out, "w", encoding="utf-8") as fp:
        for rec in tqdm(saved_records, desc="Saving"):
            fp.write(json.dumps(rec, ensure_ascii=False) + "\n")
            
    print(f"\nSuccessfully saved {len(saved_records)} articles into {timestamped_out}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Crawl SyncedReview homepage articles.")
    parser.add_argument("--days", type=int, default=7, help="Back-fill days window (0 for no date limit)")
    parser.add_argument("--out", default="data/synced.jsonl", help="Output file")
    args = parser.parse_args()

    crawl(args.out, args.days)