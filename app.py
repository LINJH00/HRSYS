import re
import json
import pandas as pd
import streamlit as st

# from backend.semantic_scholar import targeted_search
from frontend.theme import inject_global_css, header
from frontend.navigation import create_sidebar_navigation, create_sidebar_settings, create_sidebar_export
from frontend.home import render_home_page
from frontend.targeted_search import render_targeted_search_page, apply_targeted_search_styles
from frontend.candidate_profile import render_candidate_profile_page, apply_candidate_profile_styles
from frontend.achievement_report import render_achievement_report_page, apply_achievement_report_styles
from frontend.trend_radar import render_trend_radar_page, apply_trend_radar_styles
from frontend.trend_talent_profile import render_trend_talent_page, apply_trend_talent_styles, render_msra_talent_categories_page
from frontend.resume_evaluation import render_resume_evaluation_page, apply_resume_evaluation_styles
from frontend.fullscreen_results import render_fullscreen_results_page, apply_fullscreen_results_styles


st.set_page_config(page_title="TalentScope", page_icon="🎯", layout="wide", initial_sidebar_state="expanded")
inject_global_css()

# Session defaults
st.session_state.setdefault("search_results", pd.DataFrame())
st.session_state.setdefault("current_report", {})
st.session_state.setdefault("evaluation_result", {})
st.session_state.setdefault("trends_data", [])
st.session_state.setdefault("trends_summary", "")

# Create sidebar components
page = create_sidebar_navigation()
create_sidebar_settings()
create_sidebar_export()

# API key is automatically managed by Streamlit through the widget's key parameter
# No manual session state management needed

# Page content based on selection
if page == "🏠 主页":
    render_home_page()

elif page == "🔍 人才搜索":
    apply_targeted_search_styles()
    render_targeted_search_page()

# elif page == "📊 Achievement Report":
#     apply_achievement_report_styles()
#     render_achievement_report_page()

# elif page == "📄 Resume Evaluation":
#     import json
#     import streamlit as st
#     apply_resume_evaluation_styles()
#     render_resume_evaluation_page()
    
elif page == "🧑 Candidate Profile":
    apply_candidate_profile_styles()
    # Use demo data stored in session if available
    render_candidate_profile_page()
    
# elif page in ("📈 Trend Radar", "📋 Trend Report"):
#     apply_trend_radar_styles()
#     render_trend_radar_page()

elif page == "🧑 Trend Talent":
    apply_trend_talent_styles()
    render_trend_talent_page()

elif page == "🔍 Full Screen Results":
    apply_fullscreen_results_styles()
    render_fullscreen_results_page()

elif page == "🔍 Full Screen Talent Results":
    apply_trend_talent_styles()
    # 获取选中的方向数据并以全屏模式渲染
    if 'selected_direction' in st.session_state:
        from frontend.trend_talent_profile import render_trend_talent_detail_page
        card = st.session_state.selected_direction
        render_trend_talent_detail_page(card, is_fullscreen=True)
    else:
        st.error("No direction selected. Please go back and select a direction.")
        if st.button("← Back to Trend Radar"):
            st.session_state.current_page = "📈 Trend Radar"
            st.session_state.page_changed = True
            st.rerun()

elif page == "🧑‍🔬 MSRA Talents":
    apply_trend_talent_styles()
    render_msra_talent_categories_page()

elif page == "🔍 Talent Detail":
    apply_trend_talent_styles()
    # 这里可以后续添加具体的人才详情页面
    render_trend_talent_page()