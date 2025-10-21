"""Crawl Hugging Face papers trending page and save papers title + abstract.

URL: https://huggingface.co/blog
首页含有多个博客卡片，卡片内的 <a href="/blog/xxx"> 指向具体文章。
进入文章详情页后，标题位于 <h1>，正文位于 <article> 或 div.markdown 内。
保存 JSONL: url,title,content
"""
from __future__ import annotations

import json
import random
import time
import datetime
from pathlib import Path
from typing import List, Optional

import requests
from requests.adapters import HTTPAdapter, Retry
from bs4 import BeautifulSoup
from tqdm import tqdm

BASE = "https://huggingface.co"
# Trending papers 列表页
LIST_URL = f"{BASE}/papers/trending"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}

# session with retry
session = requests.Session()
retry_cfg = Retry(total=5, backoff_factor=1, status_forcelist=[429, 502, 503, 504])
session.mount("https://", HTTPAdapter(max_retries=retry_cfg))


def fetch_html(url: str, timeout: int = 30) -> str:
    for i in range(3):  # extra retries for connection issues
        try:
            r = session.get(url, headers=HEADERS, timeout=timeout)
            r.raise_for_status()
            return r.text
        except Exception as e:
            if i == 2:
                raise
            print(f"Retry {i+1}/3 for {url}: {e}")
            time.sleep(2)


def parse_list(html: str) -> List[str]:
    """解析 Trending Papers 页面，返回论文详情页完整 URL 按页面顺序。"""
    soup = BeautifulSoup(html, "lxml")

    links: list[str] = []
    seen: set[str] = set()

    # 1) 尝试 card <article> 结构
    for art in soup.select("article"):
        a_tag = art.find("a", href=True)
        if not a_tag:
            continue
        href = a_tag["href"].split("?", 1)[0].split("#", 1)[0]
        if href.startswith("/papers/") and href not in seen:
            links.append(BASE + href)
            seen.add(href)

    # 2) 若仍为空，fallback 任意 <a href="/papers/...">
    if not links:
        for a_tag in soup.select("a[href^='/papers/']"):
            href = a_tag["href"].split("?", 1)[0].split("#", 1)[0]
            if href not in seen:
                links.append(BASE + href)
                seen.add(href)

    return links


def fetch_detail(url: str) -> tuple[str, str, str]:
    """返回 (title, date, context=abstract)"""
    html = fetch_html(url)
    soup = BeautifulSoup(html, "lxml")

    title_tag = soup.find("h1")
    title = title_tag.get_text(strip=True) if title_tag else ""

    # 尝试提取发布日期
    date = ""
    # 1. 尝试从 time 标签获取
    time_tag = soup.find("time")
    if time_tag and time_tag.has_attr("datetime"):
        date = time_tag["datetime"][:10]
    else:
        # 2. 尝试从 __NEXT_DATA__ 中提取日期
        script_tag = soup.find("script", id="__NEXT_DATA__")
        if script_tag and script_tag.string:
            try:
                import json as _json
                nxt = _json.loads(script_tag.string)
                def find_date(obj):
                    if isinstance(obj, dict):
                        # 查找可能的日期字段
                        for key in ["publishedAt", "createdAt", "updatedAt", "submittedAt"]:
                            if key in obj and isinstance(obj[key], str):
                                try:
                                    return obj[key][:10]  # 只取日期部分
                                except:
                                    pass
                        for v in obj.values():
                            res = find_date(v)
                            if res:
                                return res
                    elif isinstance(obj, list):
                        for v in obj:
                            res = find_date(v)
                            if res:
                                return res
                    return ""
                
                extracted_date = find_date(nxt)
                if extracted_date:
                    date = extracted_date
            except Exception:
                pass

    # 论文摘要位于 div.paper-details__abstract
    content_tag = soup.select_one("div.paper-details__abstract")

    def absolutize(src: str) -> str:
        return src if src.startswith("http") else BASE + src

    context = ""
    if content_tag:
        segments: list[str] = []
        for p in content_tag.find_all("p"):
            txt = p.get_text(" ", strip=True)
            if txt:
                segments.append(txt)
        context = "\n".join(segments).strip()

    # fallback: 从 __NEXT_DATA__ 中抽取摘要
    if not context:
        script_tag = soup.find("script", id="__NEXT_DATA__")
        if script_tag and script_tag.string:
            try:
                import json as _json
                nxt = _json.loads(script_tag.string)
                def find_abstract(obj):
                    if isinstance(obj, dict):
                        if "abstract" in obj and isinstance(obj["abstract"], str):
                            return obj["abstract"]
                        for v in obj.values():
                            res = find_abstract(v)
                            if res:
                                return res
                    elif isinstance(obj, list):
                        for v in obj:
                            res = find_abstract(v)
                            if res:
                                return res
                    return ""

                abstract = find_abstract(nxt)
                context = abstract.strip()
            except Exception:
                pass

    # 再次 fallback：根据 "Abstract" 标题定位
    if not context:
        import re
        h2_abs = soup.find("h2", string=re.compile(r"^\s*Abstract\s*$", re.I))
        if h2_abs:
            # 容器在父 div 内，找所有段落
            parent = h2_abs.find_parent()
            if parent:
                paras = [p.get_text(" ", strip=True) for p in parent.find_all("p") if p.get_text(strip=True)]
                context = "\n".join(paras).strip()

    return title, date, context


def generate_timestamped_filename(base_filename: str) -> str:
    """生成带时间戳的文件名"""
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path_obj = Path(base_filename)
    name_without_ext = path_obj.stem
    extension = path_obj.suffix
    
    return str(path_obj.parent / f"{name_without_ext}_{timestamp}{extension}")


def crawl(out: str = "data/hf_papers.jsonl", days: Optional[int] = 7) -> None:
    """
    主爬取函数，支持日期限制。
    每次爬取生成带时间戳的独立文件。
    """
    # 生成带时间戳的文件名
    timestamped_out = generate_timestamped_filename(out)
    Path(timestamped_out).parent.mkdir(parents=True, exist_ok=True)

    if days is not None and days > 0:
        cutoff_date = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    else:
        cutoff_date = None

    print(f"Fetching trending papers list: {LIST_URL}")
    try:
        list_html = fetch_html(LIST_URL)
    except Exception as err:
        print(f"[HuggingFace Papers] List page fetch failed: {err}")
        return

    # 获取所有论文链接
    urls = parse_list(list_html)
    
    # 第一步：爬取所有文章（因为页面文章不按时间顺序排列）
    all_records = []
    
    for url in tqdm(urls, desc="Crawling Papers"):
        try:
            # 抓取详情页
            title, date, context = fetch_detail(url)
        except Exception as e:
            print(f"Skip {url}: Failed to fetch or parse detail page: {e}")
            continue
            
        all_records.append({
            "url": url,
            "title": title,
            "date": date,
            "content": context,
        })
        time.sleep(random.uniform(1, 2)) # Be polite
    
    # 第二步：根据日期筛选文章
    saved_records = []
    for record in tqdm(all_records, desc="Filtering by date"):
        # 如果没有日期限制，或者没有日期信息，或者日期符合要求，则保留
        if cutoff_date is None or not record["date"] or record["date"] >= cutoff_date:
            saved_records.append(record)
        else:
            print(f"Filtered out: {record['date']} < {cutoff_date} - {record['title'][:50]}...")
    
    print(f"Total papers crawled: {len(all_records)}")
    print(f"Papers after date filtering: {len(saved_records)}")

    with open(timestamped_out, "w", encoding="utf-8") as fp:
        for rec in tqdm(saved_records, desc="Saving"):
            # 注意：输出字段包含 url, title, date, content
            fp.write(json.dumps(rec, ensure_ascii=False) + "\n")
            
    print(f"Successfully saved {len(saved_records)} papers into {timestamped_out}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Crawl HuggingFace trending papers with date limit")
    parser.add_argument("--days", type=int, default=7, help="Back-fill days window (0 for no date limit)")
    parser.add_argument("--out", default="data/hf_papers.jsonl", help="Output file")
    args = parser.parse_args()

    crawl(args.out, args.days)
