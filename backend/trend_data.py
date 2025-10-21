import json
import datetime
import re
import glob
from pathlib import Path
from typing import List, Dict
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

CRAWL_BASE_DIR = Path(__file__).resolve().parent / "crawl_info"

# 支持的国内源及其子目录映射
DOMESTIC_SOURCES = {
    "机器之心": "机器之心/data/articles.jsonl",
    "新智源": "新智源/data/AI_era.jsonl",
    "量子位": "量子位/data/qbitai.jsonl",
}

# 支持的国际源及其子目录映射
INTERNATIONAL_SOURCES = {
    "Huggingface Blog": "Huggingface_Blog/data/hf_blog.jsonl",             # 匹配前端显示名称
    "Huggingface Trending Papers": "Huggingface_trending_paper/data/hf_trending.jsonl",  # 匹配前端显示名称
    "Synced Review": "Synced_Review/data/synced.jsonl",                     # 匹配前端显示名称
    "TechCrunch AI": "TechCrunch_AI/data/techcrunch_ai.jsonl",              # 匹配前端显示名称
}

# 合并所有数据源
ALL_SOURCES = {**DOMESTIC_SOURCES, **INTERNATIONAL_SOURCES}

# 对应爬虫脚本路径（相对本文件）
CRAWLER_SCRIPTS = {
    # 国内源
    "机器之心": "机器之心/crawl_jqzx_api.py",
    "新智源": "新智源/crawl_xzy_api.py",
    "量子位": "量子位/crawl_lzw_api.py",
    # 国际源 - 更新名称匹配
    "Huggingface Blog": "Huggingface_Blog/crawl_hfb_api.py",
    "Huggingface Trending Papers": "Huggingface_trending_paper/crawl_hf_paper_api.py", 
    "Synced Review": "Synced_Review/crawl_sync_api.py",
    "TechCrunch AI": "TechCrunch_AI/crawl_tec_api.py",
}

def _refresh_source_json(source_key: str, limit: int = 100, days: int = 7) -> None:
    """Call the crawler script to refresh jsonl for given source."""
    script_rel = CRAWLER_SCRIPTS.get(source_key)
    if not script_rel:
        return
    script_path = CRAWL_BASE_DIR / script_rel
    out_path = CRAWL_BASE_DIR / ALL_SOURCES[source_key]
    try:
        import subprocess, sys
        # 爬虫现在会自动生成带时间戳的文件名，仍然传递 --out 作为基础文件名
        cmd = [sys.executable, str(script_path), "--out", str(out_path), "--days", str(days)]
        result = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True
        )
        print(f"[trend_data] {source_key}: crawl completed")
        # 可选：显示爬虫输出的最后几行
        if result.stdout:
            lines = result.stdout.strip().split('\n')
            if lines:
                print(f"[trend_data] {source_key}: {lines[-1]}")
    except subprocess.CalledProcessError as err:
        print(f"[trend_data] {source_key}: crawl failed with exit code {err.returncode}")
        if err.stderr:
            print(f"[trend_data] {source_key} error: {err.stderr.strip()}")
    except Exception as err:
        print(f"[trend_data] {source_key}: unexpected error: {err}")

# 常见日期格式
_DATE_FORMATS = [
    "%Y-%m-%d",         # 2025-09-19
]

def _parse_date(date_str: str) -> datetime.datetime:
    for fmt in _DATE_FORMATS:
        try:
            dt = datetime.datetime.strptime(date_str, fmt)
            return dt.replace(tzinfo=None)
        except ValueError:
            continue
    # fallback: try ISO format
    # 处理形如 2025-09-19T03:20:09.227Z / 2025-09-19T03:20:09Z
    iso_clean = re.sub(r"Z$", "", date_str)  # 去掉尾部 Z
    iso_clean = iso_clean.split(".")[0]  # 去掉微秒
    try:
        dt = datetime.datetime.fromisoformat(iso_clean)
        if dt.tzinfo is not None:
            dt = dt.astimezone(datetime.timezone.utc).replace(tzinfo=None)
        return dt
    except Exception:
        return None

def find_latest_data_file(source_key: str) -> Path:
    """查找最新的带时间戳的数据文件"""
    rel_path = ALL_SOURCES.get(source_key)
    if not rel_path:
        raise ValueError(f"Unsupported source: {source_key}. Supported sources: {list(ALL_SOURCES.keys())}")
    
    base_file_path = CRAWL_BASE_DIR / rel_path
    base_dir = base_file_path.parent
    base_name = base_file_path.stem
    extension = base_file_path.suffix
    
    # 查找所有带时间戳的文件：base_name_YYYYMMDD_HHMMSS.extension
    pattern = str(base_dir / f"{base_name}_*{extension}")
    timestamped_files = glob.glob(pattern)
    
    if timestamped_files:
        # 按文件名排序，最新的文件在最后
        timestamped_files.sort()
        return Path(timestamped_files[-1])
    else:
        # 如果没找到时间戳文件，返回原始路径（向后兼容）
        return base_file_path


def load_articles(source_key: str, days: int = 7) -> List[Dict]:
    """Load all articles for given source key (e.g., '机器之心', 'Synced Review')."""

    # 每次都调用爬虫脚本刷新数据，确保获取最新内容
    rel_path = ALL_SOURCES.get(source_key)
    if not rel_path:
        raise ValueError(f"Unsupported source: {source_key}. Supported sources: {list(ALL_SOURCES.keys())}")

    # 总是刷新数据以获取最新内容
    _refresh_source_json(source_key, days=days)

    # 查找最新的数据文件
    file_path = find_latest_data_file(source_key)
    
    print(f"[Trend Data] Reading from {file_path}")
    
    if not file_path.exists():
        print(f"[Trend Data] Warning: No data file found for {source_key}")
        return []

    articles = []
    with file_path.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                item = json.loads(line.strip())
                if "date" in item:
                    try:
                        item["parsed_date"] = _parse_date(item["date"])
                    except Exception as e:
                        print(f"[Trend Data] Warning: Failed to parse date '{item.get('date')}': {e}")
                        item["parsed_date"] = None
                articles.append(item)
            except json.JSONDecodeError as e:
                print(f"[Trend Data] Warning: Failed to parse JSON line: {e}")
                continue
            except Exception as e:
                print(f"[Trend Data] Warning: Unexpected error processing line: {e}")
                continue
    return articles

def _load_source_articles(source_key: str, days: int, cutoff_date: datetime.date) -> tuple[str, List[Dict]]:
    """
    单个数据源的加载函数（用于多线程）
    
    Returns:
        (source_key, recent_articles)
    """
    try:
        print(f"[Trend Data] Thread {threading.current_thread().name}: Loading {source_key}...")
        items = load_articles(source_key, days=days)
        recent = [
            a
            for a in items
            if a.get("parsed_date") and a["parsed_date"].date() >= cutoff_date
        ]
        # sort desc by date
        recent.sort(key=lambda x: x.get("parsed_date"), reverse=True)
        print(f"[Trend Data] Thread {threading.current_thread().name}: {source_key} completed - {len(recent)} articles")
        return (source_key, recent)
    except Exception as e:
        print(f"[Trend Data] Thread {threading.current_thread().name}: {source_key} failed - {e}")
        return (source_key, [])


def query_recent_articles(days: int = 7, include_international: bool = False, international_only: bool = False) -> Dict[str, List[Dict]]:
    """
    多线程爬取最近文章
    根据数据源数量自动创建线程池
    
    Args:
        days: Number of days to look back for articles
        include_international: If True, include international sources; if False, only domestic sources
        international_only: If True, query only international sources (overrides include_international)
    
    Returns:
        Dictionary mapping source names to lists of recent articles
    """
    cutoff_date = (datetime.datetime.now() - datetime.timedelta(days=days)).date()
    result = {}
    
    # 选择数据源
    if international_only:
        sources_to_query = list(INTERNATIONAL_SOURCES.keys())
        print(f"[Trend Data] International: Preparing to crawl {len(sources_to_query)} sources")
    elif include_international:
        sources_to_query = list(ALL_SOURCES.keys())
        print(f"[Trend Data] All sources: Preparing to crawl {len(sources_to_query)} sources (domestic + international)")
    else:
        sources_to_query = list(DOMESTIC_SOURCES.keys())
        print(f"[Trend Data] Domestic: Preparing to crawl {len(sources_to_query)} sources")
    
    # Multi-threaded crawling: threads = number of sources (one thread per source)
    num_threads = len(sources_to_query)
    print(f"[Trend Data] Creating thread pool: {num_threads} threads (one per source)")
    
    with ThreadPoolExecutor(max_workers=num_threads, thread_name_prefix="Crawler") as executor:
        # 提交所有爬取任务
        future_to_source = {
            executor.submit(_load_source_articles, src, days, cutoff_date): src 
            for src in sources_to_query
        }
        
        # 收集结果
        completed = 0
        for future in as_completed(future_to_source):
            source_key = future_to_source[future]
            try:
                src_key, articles = future.result()
                result[src_key] = articles
                completed += 1
                print(f"[Trend Data] Progress: {completed}/{num_threads} completed")
            except Exception as e:
                print(f"[Trend Data] ERROR: {source_key} thread execution failed - {e}")
                result[source_key] = []
    
    total_articles = sum(len(articles) for articles in result.values())
    print(f"[Trend Data] Multi-threaded crawling completed!")
    print(f"[Trend Data] Total: {total_articles} articles from {len(result)} sources")
    print(f"[Trend Data] Distribution: " + ", ".join([f"{src}({len(arts)})" for src, arts in result.items()]))
    
    return result

def query_recent_articles_domestic(days: int = 7) -> Dict[str, List[Dict]]:
    """Return recent articles from domestic sources only (backward compatibility)."""
    return query_recent_articles(days=days, include_international=False)

def query_recent_articles_all(days: int = 7) -> Dict[str, List[Dict]]:
    """Return recent articles from all sources (domestic + international).""" 
    return query_recent_articles(days=days, include_international=True)
