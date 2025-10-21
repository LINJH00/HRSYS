import streamlit as st
import pandas as pd
import json
import sys
from pathlib import Path

current_dir = Path(__file__).parent
backend_dir = current_dir.parent / "backend"
sys.path.insert(0, str(backend_dir))

try:
    import config as backend_config
    config_available = True
except Exception as e:
    print(f"Config import error: {e}")
    config_available = False

def create_sidebar_navigation():
    """Create the sidebar navigation with attractive buttons"""
    st.sidebar.title("🎯 TalentScope")
    st.sidebar.markdown("---")

    # Page selection with attractive buttons
    st.sidebar.markdown("### 🧭 Navigation")

    # Initialize current page if not set
    if "current_page" not in st.session_state:
        st.session_state.current_page = "🏠 Home"

    # Get current page for button styling and determine the main page
    current_page = st.session_state.current_page

    # Map sub-pages to main pages for sidebar highlighting
    main_page_mapping = {
        "research_groups": "📊 Achievement Report",
        "edit_group": "📊 Achievement Report",
        "generate_report": "📊 Achievement Report",
        "view_reports": "📊 Achievement Report",
        "view_single_report": "📊 Achievement Report",
        "trend_groups": "📈 Trend Radar",
        "edit_trend_group": "📈 Trend Radar",
        "generate_trend_report": "📈 Trend Radar",
        "view_trend_reports": "📈 Trend Radar",
        "view_single_trend_report": "📈 Trend Radar",
        "🧑‍🔬 MSRA Talents": "📈 Trend Radar",
        "🔍 Talent Detail": "📈 Trend Radar",
        "🔍 Full Screen Results": "🔍 Targeted Search",
        "🔍 Full Screen Talent Results": "📈 Trend Radar"
    }
    
    # Special handling for Candidate Profile - check prev_page to determine correct highlight
    if current_page == "🧑 Candidate Profile":
        prev_page = st.session_state.get("prev_page", "")
        if prev_page == "📄 Resume Evaluation":
            sidebar_highlight_page = "📄 Resume Evaluation"
        else:
            sidebar_highlight_page = "🔍 Targeted Search"
    else:
        sidebar_highlight_page = main_page_mapping.get(current_page, current_page)

    # Track if any button was clicked to trigger rerun
    should_rerun = False
    new_page = current_page

    # Create navigation buttons with proper state management
    col1, col2 = st.columns(2)

    with col1:
        if st.sidebar.button("🏠 Home", use_container_width=True,
                     type="primary" if sidebar_highlight_page == "🏠 Home" else "secondary",
                     key="nav_home"):
            new_page = "🏠 Home"
            should_rerun = True

        if st.sidebar.button("🔍 Targeted Search", use_container_width=True,
                     type="primary" if sidebar_highlight_page == "🔍 Targeted Search" else "secondary",
                     key="nav_search"):
            new_page = "🔍 Targeted Search"
            should_rerun = True

        if st.sidebar.button("📊 Achievement Report", use_container_width=True,
                     type="primary" if sidebar_highlight_page == "📊 Achievement Report" else "secondary",
                     key="nav_report"):
            new_page = "research_groups"  # Use the sub-page directly
            should_rerun = True

    with col2:
        if st.sidebar.button("📄 Resume Evaluation", use_container_width=True,
                     type="primary" if sidebar_highlight_page == "📄 Resume Evaluation" else "secondary",
                     key="nav_resume"):
            new_page = "📄 Resume Evaluation"
            should_rerun = True

        if st.sidebar.button("📈 Trend Radar", use_container_width=True,
                     type="primary" if sidebar_highlight_page == "📈 Trend Radar" else "secondary",
                     key="nav_trend"):
            # 直接跳转到主页面 Emoji 名称，子页内部自行管理
            new_page = "📈 Trend Radar"
            should_rerun = True

    # Update session state and rerun if needed
    if should_rerun and new_page != current_page:
        st.session_state.current_page = new_page
        st.session_state.page_changed = True
        st.rerun()

    # Return the actual page for app.py routing; keep main-page highlight behavior separate
    # Don't override the current page if it's a sub-page that should be preserved
    if current_page in ["🧑 Candidate Profile", "🔍 Full Screen Results", "🔍 Full Screen Talent Results", "🧑 Trend Talent"]:
        return current_page
    return sidebar_highlight_page


def create_sidebar_settings():
    """Create the sidebar settings section with complete LLM provider support"""
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 🛠️ Settings")
    
    with st.sidebar.expander("🤖 LLM Configuration", expanded=False):
        llm_provider = "DashScope (Alibaba)"
        
        # 从 config 获取默认值
        default_api_key = getattr(backend_config, "LOCAL_OPENAI_API_KEY", "")
        default_model = getattr(backend_config, "LOCAL_OPENAI_MODEL", "qwen-turbo")
        default_base_url = getattr(backend_config, "LOCAL_OPENAI_URL", 
                                   "https://dashscope.aliyuncs.com/compatible-mode/v1") 

        if "llm_api_key" not in st.session_state:
            st.session_state.llm_api_key = default_api_key
        if "llm_base_url" not in st.session_state:
            st.session_state.llm_base_url = default_base_url
        if "llm_model" not in st.session_state:
            st.session_state.llm_model = default_model
        if "llm_provider_name" not in st.session_state:
            st.session_state.llm_provider_name = llm_provider
        if "use_custom_config" not in st.session_state:
            st.session_state.use_custom_config = False
        # API Key Input
        api_key_input = st.text_input(
            "API Key",
            type="password",
            value="" if not st.session_state.use_custom_config else st.session_state.llm_api_key,
            key="api_key_input",
            help="If empty, the default"
        )
        
        # Model Input
        model_input = st.text_input(
            "Model Name",
            value="" if not st.session_state.use_custom_config else st.session_state.llm_model,
            key="model_input_field",
            help="If empty, the default"
        )
        # 按钮行
        col_btn1, col_btn2 = st.columns(2)

        with col_btn1:
            if st.button("✅ Update Config", type="primary", use_container_width=True,
                        help="Update LLM configuration"):
                # 检查用户是否输入了自定义值
                has_custom_api_key = api_key_input and api_key_input.strip()
                has_custom_model = model_input and model_input.strip()
                
                if has_custom_api_key or has_custom_model:
                    # 👈 修正3：正确的逻辑结构
                    # 用户输入了自定义值
                    st.session_state.use_custom_config = True
                    st.session_state.llm_api_key = api_key_input.strip() if has_custom_api_key else default_api_key
                    st.session_state.llm_model = model_input.strip() if has_custom_model else default_model
                    st.session_state.llm_base_url = default_base_url
                    st.session_state.llm_provider_name = llm_provider

                    st.session_state.llm_config = {
                        "provider": llm_provider,
                        "api_key": st.session_state.llm_api_key,
                        "base_url": st.session_state.llm_base_url,
                        "model": st.session_state.llm_model
                    }
                    
                    st.success("✅ Custom configuration updated!")
                else:
                    # 用户没有输入，使用默认值
                    st.session_state.use_custom_config = False
                    st.session_state.llm_api_key = default_api_key
                    st.session_state.llm_model = default_model
                    st.session_state.llm_base_url = default_base_url
                    st.session_state.llm_provider_name = llm_provider

                    st.session_state.llm_config = {
                        "provider": llm_provider,
                        "api_key": default_api_key,
                        "base_url": default_base_url,
                        "model": default_model
                    }
                    
                    st.success("✅ Using default configuration from config.py!")
                
                # 同步到旧变量（向后兼容）
                st.session_state.openai_api_key = st.session_state.llm_api_key
                st.session_state.openai_base_url = st.session_state.llm_base_url
                st.session_state.openai_model = st.session_state.llm_model
                
                st.rerun()
        
        with col_btn2:
            if st.button("🔄 Reset to Default", type="secondary", use_container_width=True,
                        help="Reset to default configuration"):
                # 恢复默认配置
                st.session_state.use_custom_config = False
                st.session_state.llm_api_key = default_api_key
                st.session_state.llm_model = default_model
                st.session_state.llm_base_url = default_base_url
                st.session_state.llm_provider_name = llm_provider

                st.session_state.llm_config = {
                    "provider": llm_provider,
                    "api_key": default_api_key,
                    "base_url": default_base_url,
                    "model": default_model
                }
                
                # 同步到旧变量
                st.session_state.openai_api_key = default_api_key
                st.session_state.openai_base_url = default_base_url
                st.session_state.openai_model = default_model
                
                st.success("✅ Restored to default configuration!")
                st.rerun()
        
    # Return the API key for backward compatibility
    return st.session_state.get("llm_api_key", "")


def create_sidebar_export():
    """Create the sidebar export section"""
    st.sidebar.markdown("### 📤 Export")
    
    if st.sidebar.button("Export search results"):
        df = st.session_state.get("search_results")
        if isinstance(df, pd.DataFrame) and not df.empty:
            csv = df.to_csv(index=False)
            st.sidebar.download_button("Download CSV", csv, "candidates.csv", "text/csv")
