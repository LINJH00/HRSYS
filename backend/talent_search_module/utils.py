"""
Utility functions for Talent Search System
Includes logging, URL processing, text manipulation, and general helpers
"""

import os
import re
import sys
import time
import html
import datetime
from typing import List, Dict, Any, Optional, Set
from urllib.parse import urlparse

# ============================ TIMESTAMP & LOGGING UTILITIES ============================

def now_ts() -> str:
    """Generate timestamp string for file naming"""
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

class Tee:
    """Tee class for simultaneous console and file logging"""
    def __init__(self, stream, file_obj):
        self.stream = stream
        self.file_obj = file_obj

    def write(self, data):
        self.stream.write(data)
        self.file_obj.write(data)

    def flush(self):
        self.stream.flush()
        self.file_obj.flush()

def setup_tee_logging(save_dir: str, ts: str) -> str:
    """Setup tee logging to both console and file"""
    os.makedirs(save_dir, exist_ok=True)
    log_path = os.path.join(save_dir, f"{ts}_run.log")
    f = open(log_path, "a", encoding="utf-8")
    sys.stdout = Tee(sys.stdout, f)
    sys.stderr = Tee(sys.stderr, f)
    print(f"[log] tee to: {log_path}")
    return log_path

# ============================ URL PROCESSING UTILITIES ============================

def normalize_url(u: str) -> str:
    """Normalize URL by removing fragments and trailing slashes"""
    u = (u or "").strip()
    u = re.sub(r"#.*$", "", u)
    if len(u) > 1 and u.endswith("/"):
        u = u[:-1]
    return u

def domain_of(u: str) -> str:
    """Extract domain from URL"""
    try:
        return re.sub(r"^www\.", "", re.split(r"/+", u)[1])
    except Exception:
        return ""

def is_valid_url(url: str) -> bool:
    """Check if URL is valid and starts with http"""
    return url and url.startswith("http")

def looks_like_profile_url(u: str) -> bool:
    """Check if URL looks like a profile/personal page"""
    dom = domain_of(u)
    if any(x in dom for x in ["openreview.net", "semanticscholar.org",
                              "linkedin.com", "twitter.com", "x.com",
                              "github.io", "github.com"]):
        return True
    if re.search(r"/people/|/~|profile", u, flags=re.I):
        return True
    return False

def is_valid_profile_url(u: str) -> bool:
    """Check if URL is a valid profile URL"""
    if not u:
        return False
    ul = u.lower()
    allow = (
        "openreview.net/profile", "/author/", "linkedin.com/in/",
        "twitter.com/", "x.com/", "github.io", "github.com", "semanticscholar.org/author/"
    )
    return any(a in ul for a in allow)

# ============================ TEXT PROCESSING UTILITIES ============================

def clean_text(text: str, max_length: Optional[int] = None) -> str:
    """Clean and optionally truncate text"""
    if not text:
        return ""
    text = html.unescape(text).strip()
    if max_length and len(text) > max_length:
        text = text[:max_length] + "\n...[truncated]"
    return text

def strip_thinking(text: str) -> str:
    """Remove thinking tags from LLM responses"""
    if not isinstance(text, str):
        return text
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE).strip()

def normalize_whitespace(text: str) -> str:
    """Normalize whitespace in text"""
    return re.sub(r"\s+", " ", (text or "").strip())

def looks_like_student(text: str) -> bool:
    """Check if text indicates student status"""
    text = (text or "").lower()
    pats = [
        r"\bph\.?d\b", r"\bphd student\b", r"\bdoctoral\b",
        r"\bmsc\b", r"\bmaster'?s\b", r"\bgraduate student\b",
    ]
    return any(re.search(p, text) for p in pats)

# ============================ LIST PROCESSING UTILITIES ============================

def deduplicate_list(items: List[str], max_length: int = 32) -> List[str]:
    """Deduplicate list while preserving order and limiting length"""
    seen = set()
    out = []
    for item in items:
        item = normalize_whitespace(item)
        if item and item not in seen:
            seen.add(item)
            out.append(item)
            if len(out) >= max_length:
                break
    return out

def limit_list(items: List[str], max_length: int) -> List[str]:
    """Limit list length"""
    return items[:max_length] if items else []

# ============================ DELAY & TIMING UTILITIES ============================

def safe_sleep(seconds: float):
    """Sleep with error handling"""
    try:
        time.sleep(seconds)
    except Exception as e:
        print(f"[sleep] error: {e}")

# ============================ FILE SYSTEM UTILITIES ============================

def ensure_directory(path: str) -> bool:
    """Ensure directory exists, create if needed"""
    try:
        os.makedirs(path, exist_ok=True)
        return True
    except Exception as e:
        print(f"[mkdir] error creating {path}: {e}")
        return False
