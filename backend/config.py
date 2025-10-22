"""
Configuration module for Talent Search System
Contains all constants, configurations, and default values
"""

import os
from typing import Dict, List

# NOTE: TO BE DETELE:



# ============================ OUTPUT & STORAGE CONFIG ============================

# Output directory (Windows compatible)
SAVE_DIR = os.path.join(os.getcwd(), "results")

# ============================ SEARXNG CONFIG ============================
SEARXNG_BASE_URL = os.getenv("SEARXNG_BASE_URL", "http://localhost:8888")
SEARXNG_PAGES = 1         # Pages per query
# ========================================
# 场景化搜索引擎配置（Scene-based Engine Configuration）
# ========================================

# 阶段1: 论文搜索（Paper Discovery）
# 特点: 需要高质量学术结果 + arxiv可直接返回作者列表
# 调用量: 高频（50-100次/搜索）
# 注意: Google容易被限流，在Docker环境中不稳定，使用Brave+Bing+arXiv替代
SEARXNG_ENGINES_PAPER_SEARCH = ["google", "bing", "arxiv"]

# 阶段2: OpenReview查询（OpenReview Profile Search）
# 特点: 精准查找OpenReview profile，强制要求
# 调用量: 低频（1-3次/候选人）
SEARXNG_ENGINES_OPENREVIEW = ["google", "bing"]

# 阶段3: 个人主页搜索（Homepage Discovery）⭐ 最关键
# 特点: 极高频调用，必须完全避开Google避免限流
# 调用量: 极高频（400次/搜索，40次/候选人）
# 注意: 移除duckduckgo避免CAPTCHA，使用更稳定的引擎
SEARXNG_ENGINES_HOMEPAGE = ["google", "bing", "brave"]

# 阶段4: 社交平台搜索（Social Media Search）
# 特点: Bing对LinkedIn/GitHub有天然优势（Microsoft旗下）
# 调用量: 中频（150次/搜索）
SEARXNG_ENGINES_SOCIAL = ["bing", "google"]

# 阶段5: arXiv论文搜索（arXiv Author Papers）
# 特点: arxiv引擎返回完整元数据（作者、分类、摘要）
# 调用量: 低频（10次/搜索）
SEARXNG_ENGINES_ARXIV = ["arxiv", "google"]

# 阶段6: 学术平台Profile搜索（Academic Platform Profiles）⭐ 重要
# 特点: 避开Google Scholar Captcha，使用更稳定的引擎
# 调用量: 中频（100次/搜索）
# 注意: 移除startpage避免JSON解码错误，使用brave替代
SEARXNG_ENGINES_ACADEMIC_PROFILE = ["google", "bing", "brave"]

# 阶段7: Snippet兜底搜索（Fallback Snippet Retrieval）
# 特点: 三重冗余，URL抓取失败时的容错机制
# 调用量: 低频（3-5次/搜索）
# 注意: 使用稳定引擎组合，避免CAPTCHA问题
SEARXNG_ENGINES_SNIPPET = ["google", "bing", "brave"]

# 阶段8: 学术成就搜索（Notable Achievements）
# 特点: 新闻导向，查找获奖、荣誉等
# 调用量: 可选（0-5次/候选人）
# 注意: 使用稳定的新闻搜索引擎
SEARXNG_ENGINES_NOTABLE = ["google", "bing", "brave"]

# 默认引擎（向后兼容，使用论文搜索引擎）
SEARXNG_ENGINES = SEARXNG_ENGINES_PAPER_SEARCH

# ============================ LOCAL VLLM CONFIG ============================

# Local vLLM configuration (fixed)
# LOCAL_OPENAI_URL = "http://localhost:6006/v1"
# LOCAL_OPENAI_MODEL = "/root/autodl-tmp/model_folder/Qwen/Qwen3-8B-Base/"
LOCAL_OPENAI_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
LOCAL_OPENAI_MODEL = "qwen-flash"
LOCAL_OPENAI_API_KEY = "sk-b2a92fd3c2fa46048ee1a81c9a9b492a"


# ============================ SEARCH & PROCESSING PARAMETERS ============================

# Iteration and crawling parameters (fixed)
MAX_ROUNDS = 3
SEARCH_K = 10          # Results per page per query
SELECT_K = 16          # Max URLs to fetch per round
FETCH_MAX_CHARS = 15000
VERBOSE = True
DEFAULT_TOP_N = 10     # Default if query doesn't specify

# User Agent
UA = {"User-Agent": "Mozilla/5.0 (TalentSearch-LangGraph-vLLM)"}

# ============================ SEARXNG POWER-CYCLE ============================

# Restart containers after this many searxng_search calls
POWER_CYCLE_MAX_SEARCHES = 10000  # 增加重启间隔 

# Docker/container settings (Windows compatible)
SEARXNG_CONTAINER = "searxng"
VALKEY_CONTAINER = "valkey"
DOCKER_NETWORK = "searx-net"
# 使用正斜杠，Docker 在 Windows 上也支持
DOCKER_CONFIG_PATH = os.path.join(os.getcwd(), "backend", "searxng").replace("\\", "/")

# Batch search parameters
SEARCH_BATCH_CHUNK = 10


# ============================ LLM TOKEN LIMITS ============================

LLM_OUT_TOKENS = {
    "parse": 2048,
    "plan": 2048,
    "select": 2048,
    "authors": 2048,
    "synthesize": 3072,
    "paper_name": 2048,
    "degree_matcher": 50,
}

USE_LLM_PAPER_SCORING=True
ENABLE_LLM_DEGREE_MATCHING=True
# ============================ DEFAULT CONFERENCES & YEARS ============================

# Default conference library (used if user doesn't specify)
DEFAULT_CONFERENCES: Dict[str, List[str]] = {
    # 人工智能与机器学习
    "NeurIPS": ["NeurIPS"], "AAAI": ["AAAI"], "IJCAI": ["IJCAI"], "ICML": ["ICML"], "ICLR": ["ICLR"], 
    "KDD": ["KDD"], "ACL": ["ACL"], "EMNLP": ["EMNLP"], "NAACL": ["NAACL"],
    "AE": ["AE"], "IJCAR": ["IJCAR"],
    "CVPR": ["CVPR"], "ICCV": ["ICCV"], "ECCV": ["ECCV"],
    "COLING": ["COLING"],
    # 图形与可视化
    "SIGGRAPH": ["SIGGRAPH"], "ACM-MM": ["ACM MM"], "VIS": ["VIS"],
    # 数据与Web
    "SIGMOD": ["SIGMOD"], "VLDB": ["VLDB"], "SIGIR": ["SIGIR"],
    # 系统与并行计算
    "PODC": ["PODC"],
    # 网络与通信（从其他 CCF 分类）
    "SIGCOMM": ["SIGCOMM"],  # CCF A 类（已知网络顶级会议）
    "INFOCOM": ["INFOCOM"],  # CCF A 类（通信网络顶级会议）
    "NSDI": ["NSDI"],        # CCF A 类（系统设计与实现领域）
    # 人机交互
    "CHI": ["CHI"],
}

# 动态计算年份：今年、去年、明年（优先今年和去年的论文）
from datetime import datetime
_current_year = datetime.now().year
DEFAULT_YEARS = [_current_year, _current_year - 1, _current_year + 1]  # [2025, 2024, 2026]

# 固定的核心会议（始终包含）
CORE_CONFERENCES = ["ICLR", "ICML", "NeurIPS"]

# 顶级会议池（用于随机选择）- 排除核心会议
TOP_TIER_CONFERENCES = [
    "ACL", "EMNLP", "NAACL",  # NLP
    "CVPR", "ICCV", "ECCV",    # CV
    "KDD", "WWW", "SIGIR",     # Data Mining/IR
    "AAAI", "IJCAI",           # AI
    "CHI",                     # HCI
]

# ============================ CS TOP CONFERENCES BY RESEARCH AREA ============================
# 按研究方向分类的计算机科学顶级会议
CS_TOP_CONFERENCES = {
    "Artificial Intelligence": ["AAAI", "IJCAI"],
    "Computer Vision": ["CVPR", "ECCV", "ICCV"],
    "Machine Learning": ["ICLR", "ICML", "NeurIPS", "KDD"],
    "Natural Language Processing": ["ACL", "EMNLP", "NAACL"],
    "The Web & Information Retrieval": ["SIGIR", "WWW"],

    "Computer Architecture": ["ASPLOS", "ISCA", "MICRO", "HPCA"],
    "Computer Networks": ["SIGCOMM", "NSDI"],
    "Computer Security": ["CCS", "IEEE S&P", "USENIX Security", "NDSS"],
    "Databases": ["SIGMOD", "VLDB", "ICDE", "PODS"],
    "Design Automation": ["DAC", "ICCAD"],
    "Embedded & Real-Time Systems": ["EMSOFT", "RTAS", "RTSS"],
    "High-Performance Computing": ["HPDC", "ICS", "SC"],
    "Mobile Computing": ["MobiCom", "MobiSys", "SenSys"],
    "Measurement & Performance Analysis": ["IMC", "SIGMETRICS"],
    "Operating Systems": ["OSDI", "SOSP", "EuroSys", "FAST", "USENIX ATC"],
    "Programming Languages": ["PLDI", "POPL", "ICFP", "OOPSLA"],
    "Software Engineering": ["FSE", "ICSE", "ASE", "ISSTA"],

    "Algorithms & Complexity": ["FOCS", "SODA", "STOC"],
    "Cryptography": ["CRYPTO", "EuroCrypt"],
    "Logic & Verification": ["CAV", "LICS"],

    "Computational Biology & Bioinformatics": ["ISMB", "RECOMB"],
    "Computer Graphics": ["SIGGRAPH", "SIGGRAPH Asia", "Eurographics"],
    "Computer Science Education": ["SIGCSE"],
    "Economics & Computation": ["EC", "WINE"],
    "Human-Computer Interaction": ["CHI", "UbiComp/IMWUT", "UIST"],
    "Robotics": ["ICRA", "IROS", "RSS"],
    "Visualization": ["VIS", "VR"]
}

# Acceptance hints for conference papers
ACCEPT_HINTS = [
    "accepted papers", "accept", "acceptance", "program",
    "proceedings", "schedule", "paper list", "main conference", "research track",
]

# ============================ VALIDATION CONSTANTS ============================

# Maximum lengths for various fields
MAX_AUTHORS = 25
MAX_KEYWORDS = 32
MAX_VENUES = 32
MAX_DEGREE_LEVELS = 32
MAX_AUTHOR_PRIORITY = 32
MAX_EXTRA_CONSTRAINTS = 32
MAX_SEARCH_TERMS = 120
MAX_URLS = 16

# Text length thresholds
MIN_TEXT_LENGTH = 50
MIN_AUTHOR_NAME_LENGTH = 2
MAX_AUTHOR_NAME_LENGTH = 80

# ============================ CONCURRENT PROCESSING CONFIG ============================
# The system automatically adjusts worker counts based on:
# - CPU cores available
# - Current system load (CPU & memory)
# - Task type (IO-bound vs CPU-bound)
# - Number of tasks to process
# Dynamic concurrency control
ENABLE_DYNAMIC_CONCURRENCY = True  # Set to False to use fixed values below
DYNAMIC_CONCURRENCY_VERBOSE = True  # Show concurrency decisions in logs
# Legacy fixed values (now used as fallbacks when dynamic concurrency is disabled):
FETCH_MAX_WORKERS = 16  # Fallback for URL fetching
LLM_SELECT_MAX_WORKERS = 30  # Fallback for LLM-based URL selection
EXTRACTION_MAX_WORKERS = 30  # Fallback for paper name extraction
AUTHOR_DISCOVERY_MAX_WORKERS = 10  # Fallback for author discovery
CANDIDATE_PROCESSING_MAX_WORKERS = 10  # Fallback for candidate processing

# ============================ TIMEOUT CONFIG ============================

# 超时配置（避免慢速请求拖慢整体速度）
FETCH_TIMEOUT = 10  # URL抓取超时（秒）
LLM_TIMEOUT = 30  # LLM调用超时（秒）
CANDIDATE_BUILD_TIMEOUT = 60  # 单个候选人档案构建超时（秒）
SEARCH_QUERY_TIMEOUT = 15  # 搜索查询超时（秒）
HOMEPAGE_SEARCH_TIMEOUT = 30  # Homepage搜索超时（秒）