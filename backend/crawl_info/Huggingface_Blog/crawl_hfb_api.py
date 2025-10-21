from __future__ import annotations

import json
import random
import time
import datetime
from pathlib import Path
from typing import List, Optional, Union # 导入 Optional 和 Union

import requests
from requests.adapters import HTTPAdapter, Retry
from bs4 import BeautifulSoup
from tqdm import tqdm

BASE = "https://huggingface.co"
# 目标：博客列表页
LIST_URL = f"{BASE}/blog"
HEADERS = {"User-Agent": "HuggingFace-blog-crawler/0.1"}

# session with retry
session = requests.Session()
retry_cfg = Retry(total=5, backoff_factor=1, status_forcelist=[429, 502, 503, 504])
session.mount("https://", HTTPAdapter(max_retries=retry_cfg))


def fetch_html(url: str, timeout: int = 30) -> str:
    """Fetch URL with simple retry to handle occasional disconnects."""
    last_err = None
    for i in range(3):
        try:
            r = session.get(url, headers=HEADERS, timeout=timeout)
            r.raise_for_status()
            return r.text
        except Exception as e:
            if i == 2:
                # 在达到最大重试次数时，抛出最后一个错误
                raise last_err if last_err else e 
            last_err = e
            print(f"Retry {i+1}/3 for {url}: {e}")
            time.sleep(2)
    raise last_err


def parse_list(html: str) -> List[dict]:
    """
    解析博客首页Card，返回文章详情页的 URL 和 Title。
    为了适应新的 crawl 逻辑，返回 List[dict] 结构，日期暂时为空。
    """
    soup = BeautifulSoup(html, "lxml")

    results: list[dict] = []
    seen: set[str] = set()

    # 1) 优先从首页 BlogThumbnail 卡片结构提取
    for thumb in soup.select("div[data-target='BlogThumbnail']"):
        a = thumb.find("a", href=True)
        if not a:
            continue
        
        href = a["href"].split("?", 1)[0].split("#", 1)[0]
        if href.rstrip("/") == "/blog":
            continue
        
        if href not in seen and href.startswith("/blog/"):
            url = BASE + href
            # 尝试提取标题
            title_tag = thumb.select_one("h2") or thumb.select_one("h3")
            title = title_tag.get_text(strip=True) if title_tag else ""
            
            results.append({"url": url, "title": title, "date": ""})
            seen.add(href)

    # 2) fallback：任何指向 /blog/xxx 的链接
    if not results:
        for a in soup.select("a[href^='/blog/']"):
            href = a["href"].split("?", 1)[0].split("#", 1)[0]
            if href.rstrip("/") == "/blog":
                continue
            
            if href not in seen:
                url = BASE + href
                title = a.get_text(strip=True)
                results.append({"url": url, "title": title, "date": ""})
                seen.add(href)

    return results


def fetch_detail(url: str) -> tuple[str, str, str]:
    """返回 (title, date, content)"""
    html = fetch_html(url)
    soup = BeautifulSoup(html, "lxml")

    # 标题位于 <h1>
    title_tag = soup.find("h1")
    title = title_tag.get_text(strip=True) if title_tag else ""

    # **新增：日期提取**
    date = ""
    time_tag = soup.select_one("time[datetime]")
    if time_tag:
        date = time_tag["datetime"][:10]


    # 各种正文容器
    content_tag = (
        soup.find("article")
        or soup.find("div", class_="markdown")
        or soup.find("div", attrs={"data-target": "MarkdownRenderer"})
        or soup.find("div", class_="prose")
        or soup.select_one("main div")
    )

    def absolutize(src: str) -> str:
        return src if src.startswith("http") else BASE + src

    if content_tag:
        segments: list[str] = []
        for elem in content_tag.descendants:
            # 图片 - 注释掉图片爬取逻辑，只保留文字内容
            # if getattr(elem, "name", None) == "img":
            #     src = elem.get("src") or elem.get("data-src") or elem.get("data-original")
            #     if src:
            #         segments.append(absolutize(src))
            # 段落/文本
            if getattr(elem, "name", None) == "p":
                txt = elem.get_text(" ", strip=True)
                if txt:
                    segments.append(txt)
        content = "\n".join(segments).strip()
    else:
        content = ""

    # 返回 (title, date, content)
    return title, date, content


def generate_timestamped_filename(base_filename: str) -> str:
    """生成带时间戳的文件名"""
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path_obj = Path(base_filename)
    name_without_ext = path_obj.stem
    extension = path_obj.suffix
    
    return str(path_obj.parent / f"{name_without_ext}_{timestamp}{extension}")


def crawl(out: str = "data/hf_blog.jsonl", days: Optional[int] = 7) -> None:
    """
    主爬取函数，只抓取首页文章，并应用days时间限制。
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
        print(f"[HuggingFace] List page fetch failed: {err}")
        return

    # 从首页提取文章列表 (info 包含 url, title, date='')
    items = parse_list(list_html)
    
    saved_records = []
    
    # 遍历首页文章列表
    for info in tqdm(items, desc="Crawling Articles"):
        url = info["url"]
        
        try:
            # 抓取详情页
            title_detail, date_detail, content_detail = fetch_detail(url)
        except Exception as e:
            print(f"Skip {url}: Failed to fetch or parse detail page: {e}")
            continue
        
        # 使用详情页的日期进行截止检查
        final_date = date_detail or info.get("date")
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
            
    print(f"\nSuccessfully saved {len(saved_records)} posts into {timestamped_out}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Crawl HuggingFace blog posts with date limit")
    parser.add_argument("--days", type=int, default=7, help="Back-fill days window (0 for no date limit)")
    parser.add_argument("--out", default="data/hf_blog.jsonl", help="Output file")
    args = parser.parse_args()

    crawl(args.out, args.days)