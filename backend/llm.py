"""
LLM configuration and wrapper functions for Talent Search System
Handles vLLM setup, structured output, and safe LLM interactions
"""

import json
from typing import Optional, Dict, Any
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from pathlib import Path
import sys

# Use pathlib for robust path handling
current_dir = Path(__file__).parent
talent_search_module_dir = current_dir / "talent_search_module"
sys.path.insert(0, str(talent_search_module_dir))

try:
    import utils
    import schemas
    from langchain_community.chat_models.tongyi import ChatTongyi
    from langchain_community.llms import VLLMOpenAI
    import config
    import streamlit as st
except Exception as e:
    print(f"LLM ImportError: {e}")

# ============================ LLM CONFIGURATION ============================

def get_llm_config_from_session() -> Dict[str, Any]:
    """Get complete LLM configuration from Streamlit session state"""
    import os
    try:
        # 优先从新的session state变量获取（修复页面切换时丢失配置的问题）
        api_key = (st.session_state.get("llm_api_key", "") or 
                   st.session_state.get("openai_api_key", "") or 
                   os.environ.get("OPENAI_API_KEY", "") or
                   os.environ.get("DASHSCOPE_API_KEY", ""))
        
        base_url = (st.session_state.get("llm_base_url", "") or
                    st.session_state.get("openai_base_url", "") or
                    os.environ.get("OPENAI_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"))
        
        model = (st.session_state.get("llm_model", "") or
                 st.session_state.get("openai_model", "") or
                 os.environ.get("OPENAI_MODEL", "qwen-turbo"))
        
        provider = (st.session_state.get("llm_provider_name", "") or
                   st.session_state.get("llm_provider", "") or
                   os.environ.get("LLM_PROVIDER", "DashScope (Alibaba)"))
        
        # 构建配置对象
        config = {
            "provider": provider,
            "api_key": api_key,
            "base_url": base_url,
            "model": model
        }
        
        # 如果配置完整，同时更新llm_config为向后兼容（可选）
        if api_key and base_url and model:
            st.session_state.llm_config = config
            # 同时更新旧的session state变量以保持向后兼容
            if not st.session_state.get("openai_api_key"):
                st.session_state.openai_api_key = api_key
            if not st.session_state.get("openai_base_url"):
                st.session_state.openai_base_url = base_url
            if not st.session_state.get("openai_model"):
                st.session_state.openai_model = model
        
        return config
        
    except Exception as e:
        print(f"[get_llm_config_from_session] Error: {e}")
        # 安全回退配置
        return {
            "provider": "OpenAI",
            "api_key": os.environ.get("OPENAI_API_KEY", ""),
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4o-mini"
        }

# def get_llm(role: str, temperature: float = 0.4) -> ChatOpenAI:
#     """Get configured LLM instance for specific role"""
#     max_tokens = config.LLM_OUT_TOKENS.get(role, 2048)
#     return ChatOpenAI(
#         model=config.LOCAL_OPENAI_MODEL,
#         api_key=config.LOCAL_OPENAI_API_KEY,
#         base_url=config.LOCAL_OPENAI_BASE_URL,
#         temperature=temperature,
#         max_tokens=max_tokens,
#     )
    
    
# def get_llm(role: str, temperature: float = 0.4, api_key: str = None) -> VLLMOpenAI:
#     """Get configured LLM instance for specific role
    
#     Args:
#         role: The role/context for the LLM (affects max_tokens)
#         temperature: Temperature setting for response randomness
#         api_key: Optional explicit API key (not used for VLLMOpenAI)
    
#     Returns:
#         VLLMOpenAI: Configured LLM instance
#     """
#     max_tokens = config.LLM_OUT_TOKENS.get(role, 2048)
    
#     # Current implementation using VLLMOpenAI
#     return VLLMOpenAI(
#         openai_api_key="EMPTY",
#         openai_api_base="http://localhost:8000/v1",
#         model_name="qwen3",
#         temperature=temperature,
#         max_tokens=max_tokens,
#     )

def get_llm(role: str, temperature: float = 0.4, api_key: str = None):
    """Get configured LLM instance for specific role with multi-provider support
    
    Args:
        role: The role/context for the LLM (affects max_tokens)
        temperature: Temperature setting for response randomness  
        api_key: Optional explicit API key. If not provided, will get from session state.
    
    Returns:
        ChatOpenAI or ChatTongyi: Configured LLM instance based on provider
        
    Raises:
        ValueError: If no API key is available or unsupported provider
    """
    max_tokens = config.LLM_OUT_TOKENS.get(role, 2048)
    
    # Get complete LLM configuration
    llm_config = get_llm_config_from_session()
    
    # Override with explicit API key if provided
    if api_key:
        llm_config["api_key"] = api_key
        
    # Validate configuration
    if not llm_config.get("api_key"):
        raise ValueError("API key is required. Please configure your LLM settings in the sidebar (🛠️ Settings → 🤖 LLM Configuration).")
    
    provider = llm_config.get("provider", "OpenAI")
    api_key_to_use = llm_config["api_key"]
    base_url = llm_config.get("base_url", "https://api.openai.com/v1")
    model = llm_config.get("model", "gpt-4o-mini")
    
    # Create appropriate LLM instance based on provider
    try:
        if provider == "DashScope (Alibaba)":
            # Use ChatTongyi for DashScope
            return ChatTongyi(
                model=model,
                api_key=api_key_to_use,
                streaming=False,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        else:
            # Use ChatOpenAI for all OpenAI-compatible providers (OpenAI, Azure, Custom)
            return ChatOpenAI(
                model=model,
                api_key=api_key_to_use,
                base_url=base_url,
                temperature=temperature,
                max_tokens=max_tokens,
            )
    except Exception as e:
        # Fallback error with configuration details
        raise ValueError(
            f"Failed to initialize {provider} LLM client. "
            f"Please check your configuration (Provider: {provider}, Model: {model}, Base URL: {base_url}). "
            f"Error: {str(e)}"
        )

# ============================ JSON EXTRACTION UTILITIES ============================

def extract_json_block(s: str) -> Optional[dict]:
    """Extract JSON block from text response"""
    s = utils.strip_thinking(s)
    
    # Handle ChatTongyi nested format: "{'text': 'actual_json'}"  
    import re
    match = re.match(r"^\{'text': '(.+?)'\}$", s, re.DOTALL)
    if match:
        inner_json = match.group(1)
        inner_json = inner_json.replace('\\n', '\n').replace('\\"', '"').replace("\\'", "'")
        try:
            return json.loads(inner_json)
        except Exception as e:
            if config.VERBOSE:
                print(f"[extract_json_block] ChatTongyi inner parse failed: {e}")
    
    # Standard JSON parsing
    try:
        return json.loads(s)
    except Exception:
        pass

    # Fallback: search for JSON blocks
    start = s.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(s)):
            ch = s[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(s[start:i+1])
                    except Exception:
                        break
        start = s.find("{", start + 1)
    return None

# ============================ MINIMAL FALLBACKS ============================

def minimal_by_schema(schema_cls):
    """Return minimal valid instance of schema class"""
    if schema_cls is schemas.QuerySpec:
        return schemas.QuerySpec()
    if schema_cls is schemas.PlanSpec:
        return schemas.PlanSpec(search_terms=["accepted papers program proceedings schedule"], selection_hint="Prefer accepted/program/proceedings pages")
    if schema_cls is schemas.SelectSpec:
        return schemas.SelectSpec(urls=[])
    if schema_cls is schemas.CandidatesSpec:
        return schemas.CandidatesSpec(candidates=[], citations=[], need_more=True, followups=["Need more/better sources."])
    if schema_cls is schemas.AuthorListSpec:
        return schemas.AuthorListSpec(authors=[])
    if schema_cls is schemas.LLMSelectSpec:
        return schemas.LLMSelectSpec(should_fetch=False)
    if schema_cls is schemas.LLMSelectSpecWithValue:
        return schemas.LLMSelectSpecWithValue(should_fetch=False, value_score=0.0, reason="Default")
    if schema_cls is schemas.LLMSelectSpecHasAuthorInfo:
        return schemas.LLMSelectSpecHasAuthorInfo(has_author_info=False, confidence=0.0, reason="Default")
    if schema_cls is schemas.LLMPaperNameSpec:
        return schemas.LLMPaperNameSpec(paper_name="", have_paper_name=False)
    if schema_cls is schemas.LLMAuthorProfileSpec:
        return schemas.LLMAuthorProfileSpec()
    if schema_cls is schemas.HomepageInsightsSpec:
        return schemas.HomepageInsightsSpec(
            current_status="",
            role_affiliation_detailed="",
            research_focus=[],
            research_keywords=[],
            highlights=[],
        )
    if schema_cls is schemas.SearchValidationResult:
        return schemas.SearchValidationResult(
            is_valid_search=False, 
            search_terms_found=[], 
            missing_elements=["LLM service error"], 
            suggestion="Please check your network connection and API configuration, or try again later."
        )

    raise ValueError(f"Unknown schema class: {schema_cls}")

# ============================ SAFE STRUCTURED OUTPUT ============================

def safe_get(obj, path, default=None):
    """Safely extract nested values from response objects"""
    if not isinstance(path, (list, tuple)):
        path = [path]
    
    cur = obj
    for key in path:
        if hasattr(cur, key):
            cur = getattr(cur, key)
        elif isinstance(cur, dict) and key in cur:
            cur = cur[key]
        else:
            return default
    return cur

def safe_structured(llm: ChatOpenAI | ChatTongyi | VLLMOpenAI, prompt: str, schema_cls):
    """Safely get structured output from LLM with fallbacks"""
    import time
    
    # Try up to 3 times
    for attempt in range(3):
        try:
            txt = ""
            data = None
            
            # First try structured output for OpenAI
            if isinstance(llm, ChatOpenAI) and attempt == 0:
                try:
                    return llm.with_structured_output(schema_cls).invoke(prompt)
                except Exception as e:
                    if config.VERBOSE:
                        print(f"[safe_structured] structured output failed: {e}")
            
            # Standard invoke with error handling
            resp = None
            if isinstance(llm, ChatOpenAI):
                resp = llm.invoke(prompt)
            elif isinstance(llm, ChatTongyi):
                try:
                    resp = llm.invoke(prompt, enable_thinking=False)
                except (KeyError, TypeError):
                    # Retry with minimal kwargs - still need enable_thinking=False
                    resp = llm.invoke(prompt, enable_thinking=False)
            elif isinstance(llm, VLLMOpenAI):
                resp = llm.invoke(prompt)
            else:
                raise ValueError("Invalid LLM type")
            
            # Safe content extraction - handle ChatTongyi nested response format
            txt = safe_get(resp, "content", "") or safe_get(resp, "text", "") or str(resp)
            
            # Handle ChatTongyi's nested dict response format: {'text': 'actual_content'}
            if isinstance(txt, dict) and 'text' in txt:
                txt = txt['text']
            elif isinstance(txt, list):
                txt = "\n".join(str(item) for item in txt)
            elif not isinstance(txt, str):
                txt = str(txt)
            

            # Try to extract JSON
            data = extract_json_block(txt)
            if data is not None:
                return schema_cls.model_validate(data)
                
            if config.VERBOSE:
                print(f"[safe_structured] attempt {attempt+1}: no valid JSON, response: {txt[:200]}...")
                
        except Exception as e:
            if config.VERBOSE:
                print(f"[safe_structured] attempt {attempt+1} failed: {e}")
                print(f"[safe_structured] response type: {type(resp) if 'resp' in locals() else 'undefined'}")
                
            if attempt < 2:  # Don't sleep on last attempt
                time.sleep(0.5 * (attempt + 1))
            continue
    
    # All attempts failed, use minimal fallback
    if config.VERBOSE:
        print("[safe_structured] all attempts failed, using minimal fallback")
    return minimal_by_schema(schema_cls)
