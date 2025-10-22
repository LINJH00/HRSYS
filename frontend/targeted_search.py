# pyright: reportMissingImports=false
import streamlit as st
import json
import pandas as pd
from pathlib import Path
import sys
import copy
import plotly.graph_objects as go
import html
import threading
import queue
import time

# Use pathlib for robust path handling
current_dir = Path(__file__).parent
backend_dir = current_dir.parent / "backend"
talent_search_module_dir = backend_dir / "talent_search_module"

# Add backend and talent_search_module to path
sys.path.insert(0, str(backend_dir))
sys.path.insert(0, str(talent_search_module_dir))
try:
    import agents
    from schemas import QuerySpec

    backend_available = True
except Exception as e:
    print(f"TargetedSearch ImportError: {e}")
    backend_available = False


def squash_top_gap():
    st.markdown(
        """
    <style>
    .appview-container .main .block-container{{
            padding-top: {padding_top}rem;    }}
    </style>
    """,
        unsafe_allow_html=True,
    )

def _inject_search_progress_stytles(theme: str):
    """
        Inject CSS style of search progress pop-up
    """
    if theme == "dark":
        modal_bg = "#111827"
        modal_border = "#374151"    
        text_color = "#e5e7eb"      
        dot_default = "#4b5563"     
        dot_done = "#10b981"        
        dot_active = "#60a5fa"      
    else:
        modal_bg = "#ffffff"
        modal_border = "#e5e7eb"
        text_color = "#0f172a"
        dot_default = "#d1d5db"
        dot_done = "#10b981"
        dot_active = "#3b82f6"

    st.markdown(f"""
    <style>
    /* ========== 进度弹窗样式 ========== */
    
    /* Overlay - 全屏半透明遮罩 */
    .search-overlay {{
        position: fixed;           /* 固定定位，覆盖整个屏幕 */
        inset: 0;                 /* 上下左右都是0，占满全屏 */
        background: rgba(0,0,0,.55);  /* 半透明黑色背景 */
        z-index: 9999;            /* 最高层级，确保在最上面 */
        display: flex;            /* 使用flex布局 */
        align-items: center;      /* 垂直居中 */
        justify-content: center;  /* 水平居中 */
    }}
        /* Modal - 弹窗主容器 */
    .search-modal {{
        width: 560px;             /* 固定宽度 */
        max-width: 92vw;          /* 响应式：最大不超过屏幕92% */
        background: {modal_bg};   /* 背景色（根据主题） */
        color: {text_color};      /* 文字颜色 */
        border-radius: 14px;      /* 圆角 */
        border: 1px solid {modal_border};  /* 边框 */
        box-shadow: 0 20px 80px rgba(0,0,0,.35);  /* 阴影，增加立体感 */
    }}
    
    /* Modal Header - 弹窗头部 */
    .search-modal-header {{
        padding: 18px 20px;       /* 内边距 */
        border-bottom: 1px solid {modal_border};  /* 底部分割线 */
        display: flex;
        align-items: center;
        justify-content: space-between;  /* 两端对齐 */
    }}
        .search-modal-title {{
        font-size: 22px;          /* 大标题 */
        font-weight: 800;         /* 加粗 */
    }}
    
    /* Steps Container - 步骤列表容器 */
    .search-steps {{
        max-height: 360px;        /* 最大高度，超出滚动 */
        overflow-y: auto;         /* 纵向滚动 */
        padding: 8px 20px 18px;   /* 内边距 */
    }}
    
    /* Single Step - 单个步骤 */
    .search-step {{
        display: flex;            /* flex布局 */
        align-items: center;      /* 垂直居中 */
        gap: 10px;               /* 元素间距 */
        padding: 10px 0;         /* 上下内边距 */
        font-size: 14px;         /* 字体大小 */
        border-bottom: 1px dashed rgba(255,255,255,.06);  /* 虚线分割 */
        transition: all 0.3s ease;  /* 过渡动画 */
    }}

        .search-step:last-child {{
        border-bottom: none;      /* 最后一个不需要底部边框 */
    }}
    
    /* Step Dot - 步骤圆点（状态指示器） */
    .search-dot {{
        width: 10px;
        height: 10px;
        border-radius: 999px;     /* 圆形 */
        background: {dot_default};  /* 默认颜色：灰色（未开始） */
        transition: all 0.3s ease;  /* 颜色变化动画 */
    }}
    
    /* 已完成的步骤 - 绿色圆点 */
    .search-step.done .search-dot {{
        background: {dot_done};   /* 绿色 */
    }}
        /* 进行中的步骤 - 蓝色圆点 + 脉动动画 */
    .search-step.active .search-dot {{
        background: {dot_active}; /* 蓝色 */
        animation: pulse 1.5s ease-in-out infinite;  /* 脉动效果 */
    }}
    
    /* 脉动动画 - 让进行中的圆点有呼吸效果 */
    @keyframes pulse {{
        0%, 100% {{
            opacity: 1;
            transform: scale(1);
        }}
        50% {{
            opacity: 0.7;
            transform: scale(1.2);  /* 放大1.2倍 */
        }}
    }}
    </style>
    """, unsafe_allow_html=True)

def _render_search_progress_overlay(steps: list, active_idx: int, 
                                     candidates_found: int = 0,
                                     target_count: int = 10,
                                     current_action: str = "",
                                     detail_info: str = "")->str:
    """
    Generate HTML code for search progress pop-up window with status display
    
    Args:
        steps: List of search steps
        active_idx: Index of current active step
        candidates_found: Number of candidates found so far
        target_count: Target number of candidates
        current_action: Current operation (e.g., "正在评分论文")
        detail_info: Detail information (e.g., paper title)
    """
    items = []

    for i, txt in enumerate(steps):
        if i < active_idx:
            state = "done"
        elif i == active_idx:
            state = "active"
        else :
            state = ""

        items.append(
            f'<div class="search-step {state}">'  
            f'  <div class="search-dot"></div>'   
            f'  <div>{txt}</div>'                 
            f'</div>'
        )
    
    # 简洁的两行状态显示（英文版） - 视觉优化版（无进度条）
    status_html = (
        '<div style="'
        '    margin-top: 1.5rem;'
        '    padding: 1.2rem;'
        '    background: linear-gradient(135deg, rgba(102, 126, 234, 0.1), rgba(96, 165, 250, 0.05));'
        '    border-radius: 10px;'
        '    border: 1px solid rgba(102, 126, 234, 0.3);'
        '    backdrop-filter: blur(10px);'
        '    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);'
        '">'
        # 第一行：候选人进度（固定）
        '  <div style="'
        '      display: flex;'
        '      align-items: center;'
        '      gap: 0.6rem;'
        '      margin-bottom: 0.8rem;'
        '      padding-bottom: 0.8rem;'
        '      border-bottom: 1px dashed rgba(102, 126, 234, 0.2);'
        '  ">'
        '    <span style="'
        '        font-size: 1.3em;'
        '        filter: drop-shadow(0 0 4px rgba(102, 126, 234, 0.5));'
        '    ">👥</span>'
        '    <span style="'
        '        color: #e2e8f0;'
        '        font-weight: 600;'
        '        font-size: 1.05em;'
        '    ">Found</span>'
        '    <span style="'
        '        color: #667eea;'
        '        font-weight: 700;'
        '        font-size: 1.25em;'
        '        text-shadow: 0 0 10px rgba(102, 126, 234, 0.3);'
        f'    ">{candidates_found}/{target_count}</span>'
        '    <span style="'
        '        color: #e2e8f0;'
        '        font-weight: 600;'
        '        font-size: 1.05em;'
        '    ">candidates</span>'
        '  </div>'
        # 第二行：当前操作（动态变化）
        '  <div style="'
        '      display: flex;'
        '      align-items: center;'
        '      gap: 0.6rem;'
        '      min-height: 1.5rem;'
        '  ">'
        '    <span style="'
        '        color: #60a5fa;'
        '        font-size: 1.1em;'
        '        animation: spin 2s linear infinite;'
        '        display: inline-block;'
        '    ">⟳</span>'
        '    <span style="'
        '        color: #cbd5e1;'
        '        font-size: 0.95em;'
        '        flex: 1;'
        '        display: flex;'
        '        align-items: center;'
        '        gap: 0.5rem;'
        '    ">'
        f'      <span style="font-weight: 500;">{current_action if current_action else "Initializing..."}</span>'
        f'      {("<span style=\"color: #64748b; font-style: italic; font-size: 0.9em; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 60%;\">" + detail_info + "</span>") if detail_info else ""}'
        '    </span>'
        '  </div>'
        '</div>'
        # CSS动画
        '<style>'
        '  @keyframes spin {'
        '    from { transform: rotate(0deg); }'
        '    to { transform: rotate(360deg); }'
        '  }'
        '</style>'
        )

    return (
        '<div class="search-overlay">'          
        '  <div class="search-modal">'          
        '    <div class="search-modal-header">' 
        '      <div class="search-modal-title">🔍 Searching for Talents</div>'
        '    </div>'
        f'    <div class="search-steps">{"".join(items)}</div>'  
        f'    {status_html}'  # 添加状态显示
        '  </div>'
        '</div>'
    )


# Chat processing state management
class ChatState:
    IDLE = "idle"
    VALIDATING = "validating"  # New state for search validation
    PREVIEW = "preview"
    SEARCHING = "searching"
    RESULTS = "results"


def get_current_state():
    """Get current chat state based on session state"""
    if st.session_state.get("awaiting_confirmation", False):
        return ChatState.SEARCHING
    elif st.session_state.get("show_results", False):
        return ChatState.RESULTS
    elif st.session_state.get("show_para_preview", False):
        return ChatState.PREVIEW
    elif st.session_state.get("validating_search", False):
        return ChatState.VALIDATING
    else:
        return ChatState.IDLE


def filter_chat_history_for_llm(chat_history):
    """Filter chat history to remove system messages before sending to LLM"""
    if not isinstance(chat_history, list):
        return []
    return [msg for msg in chat_history if msg.get("role") != "system"]


def process_user_message(user_input):
    """Process user message based on current state"""
    current_state = get_current_state()

    if current_state == ChatState.PREVIEW:
        handle_parameter_adjustment(user_input)
    elif current_state == ChatState.RESULTS:
        handle_results_feedback(user_input)
    elif current_state == ChatState.VALIDATING:
        handle_search_validation_response(user_input)
    else:
        handle_new_search_request(user_input)


def handle_parameter_adjustment(user_input):
    """Handle parameter adjustments when in preview state"""
    current_spec = st.session_state.query_spec.copy()
    user_lower = user_input.lower()

    # Handle satisfaction responses first
    if any(
        word in user_lower
        for word in ["satisfied", "good", "looks good", "perfect", "great", "excellent"]
    ):
        st.session_state.chat_history.append(
            {
                "role": "assistant",
                "content": "🎉 Wonderful! I'm glad the parameters look good. Click 'Looks Good! Start Search' to proceed with the search.",
            }
        )
        return

    # Handle dissatisfaction or change requests
    if any(
        word in user_lower
        for word in [
            "not satisfied",
            "change",
            "different",
            "adjust",
            "modify",
            "not good",
        ]
    ):
        st.session_state.chat_history.append(
            {
                "role": "assistant",
                "content": "I understand you'd like to make some changes. Please tell me specifically what you'd like to adjust. For example:<br>• 'Change the number of candidates to 15'<br>• 'Add computer vision as a research area'<br>• 'Only focus on PhD students'<br>• 'Include more recent years like 2022'",
            }
        )
        return

    # Try backend-powered adjustment
    if backend_available:
        try:
            recent_history = (
                filter_chat_history_for_llm(st.session_state.chat_history[-10:])
                if isinstance(st.session_state.get("chat_history", []), list)
                else []
            )

            # Step 1: classify whether the message is an adjustment
            cls = agents.agent_classify_user_adjustment(
                current_spec, user_input, recent_history
            )
            if isinstance(cls, dict) and not cls.get("is_adjustment", False):
                help_msg = cls.get(
                    "help_instruction",
                    "Please specify what you want to change, e.g., 'set top_n to 15' or 'add venues: ACL'.",
                )
                st.session_state.chat_history.append(
                    {"role": "assistant", "content": help_msg}
                )
                return

            # Step 2: request a partial diff and merge
            diff = agents.agent_diff_search_parameters(
                current_spec, user_input, recent_history
            )
            if diff:
                merged = agents.merge_query_spec_with_diff(current_spec, diff)
                current_spec = merged

                # allow preview extracted search parameters card
                st.session_state.show_preview = False

                st.session_state.chat_history.append(
                    {
                        "role": "assistant",
                        "content": "✅ I've updated the search parameters based on your request.",
                    }
                )
            else:
                st.session_state.chat_history.append(
                    {
                        "role": "assistant",
                        "content": "I couldn't determine what to change. For example, say 'top_n 15', 'add keywords: graph learning', or 'only venues: ACL, EMNLP'.",
                    }
                )
                return
        except Exception as e:
            # Fallback to simple heuristic adjustments if backend fails
            if not try_simple_adjustment(current_spec, user_input):
                st.session_state.chat_history.append(
                    {
                        "role": "assistant",
                        "content": f"I encountered an error adjusting the parameters: {e}<br>Could you be more specific? For example, tell me what number of candidates you want, or which research areas to add/remove.",
                    }
                )
                return
    else:
        # Backend not available: minimal heuristic fallback
        if not try_simple_adjustment(current_spec, user_input):
            st.session_state.chat_history.append(
                {
                    "role": "assistant",
                    "content": "I'm not sure how to adjust the parameters based on that request. Could you be more specific? For example, tell me what number of candidates you want, or which research areas to add/remove.",
                }
            )
            return

    # Update the session state with adjusted parameters
    st.session_state.query_spec = current_spec
    st.session_state.show_preview = True
    st.session_state.show_results = False  # Hide old results
    # Reset preview_in_history so the updated parameters get added to chat history
    st.session_state.preview_in_history = False


def try_simple_adjustment(current_spec, user_input):
    """Try simple heuristic adjustments. Returns True if successful."""
    import re

    user_lower = user_input.lower()

    # Handle number adjustments
    number_match = re.search(r"(\d+)\s*(?:candidates?|people|results?)", user_lower)
    if number_match:
        new_count = int(number_match.group(1))
        current_spec["top_n"] = new_count
        st.session_state.chat_history.append(
            {
                "role": "assistant",
                "content": f"✅ Updated! I'll now search for {new_count} candidates. Here are the updated parameters:",
            }
        )
        return True

    return False


def handle_results_feedback(user_input):
    """Handle feedback when search results are shown"""
    user_lower = user_input.lower()

    # Handle satisfaction responses
    if any(
        word in user_lower
        for word in ["satisfied", "good", "looks good", "perfect", "great", "excellent"]
    ):
        st.session_state.chat_history.append(
            {
                "role": "assistant",
                "content": "🎉 Wonderful! I'm glad you're satisfied with the search results. If you need to run another search with different criteria, just let me know what you're looking for!",
            }
        )
        return

    # Handle requests for new search
    if any(
        word in user_lower for word in ["new search", "different search", "start over"]
    ):
        # Reset to idle state
        st.session_state.show_results = False
        st.session_state.show_preview = False
        st.session_state.query_spec = None
        st.session_state.search_results = None
        st.session_state.chat_history.append(
            {
                "role": "assistant",
                "content": "Sure! I've cleared the previous search. Please tell me what kind of talent you're looking for in your new search.",
            }
        )
        return

    # Handle general dissatisfaction - treat as new search request
    if any(
        word in user_lower
        for word in [
            "not satisfied",
            "change",
            "different",
            "adjust",
            "modify",
            "not good",
        ]
    ):
        st.session_state.chat_history.append(
            {
                "role": "assistant",
                "content": "I understand the current results don't meet your needs. Let me help you create a new search. Please describe what you're looking for, and I'll extract new search parameters.",
            }
        )
        # Reset to allow new search
        st.session_state.show_results = False
        st.session_state.show_preview = False
        st.session_state.query_spec = None
        st.session_state.search_results = None
        return

    # Otherwise treat as a new search request
    handle_new_search_request(user_input)


def handle_search_validation_response(user_input):
    """Handle user response when in validation state"""
    # User is responding to validation feedback, treat as new search request
    st.session_state.validating_search = False
    handle_new_search_request(user_input)
    
    
def _display_reference_papers(reference_papers, current_theme, text_color):
    """Display reference papers list with scores and associated candidates"""
    import html
    
    with st.container(border=True):
        for i, paper in enumerate(reference_papers, 1):
            url = getattr(paper, 'url', '') if hasattr(paper, 'url') else paper.get('url', '')
            title = getattr(paper, 'title', '') if hasattr(paper, 'title') else paper.get('title', '')
            score = getattr(paper, 'score', 0) if hasattr(paper, 'score') else paper.get('score', 0)
            candidates = getattr(paper, 'associated_candidates', []) if hasattr(paper, 'associated_candidates') else paper.get('associated_candidates', [])
            
            # Score color based on relevance
            if score >= 8:
                score_color = "#10b981"  # Green
                score_bg = "rgba(16, 185, 129, 0.1)"
            elif score >= 6:
                score_color = "#f59e0b"  # Orange
                score_bg = "rgba(245, 158, 11, 0.1)"
            else:
                score_color = "#ef4444"  # Red
                score_bg = "rgba(239, 68, 68, 0.1)"
            
            # Display paper card
            st.markdown(
                f"""
                <div style="
                    background: {'#1e293b' if current_theme == 'dark' else '#f8fafc'};
                    border-left: 4px solid {score_color};
                    border-radius: 8px;
                    padding: 1rem;
                    margin-bottom: 0.8rem;
                ">
                    <div style="display: flex; justify-content: space-between; align-items: start; margin-bottom: 0.5rem;">
                        <div style="flex: 1;">
                            <div style="font-size: 0.9rem; font-weight: 600; color: {text_color}; margin-bottom: 0.3rem;">
                                Paper {i}
                            </div>
                            <div style="font-size: 1rem; color: {text_color}; margin-bottom: 0.5rem;">
                                {html.escape(title or 'Untitled')}
                            </div>
                            <a href="{url}" target="_blank" style="
                                font-size: 0.85rem; 
                                color: #3b82f6; 
                                text-decoration: none;
                                word-break: break-all;
                            ">{html.escape(url[:80] + '...' if len(url) > 80 else url)}</a>
                        </div>
                        <div style="
                            background: {score_bg};
                            border: 2px solid {score_color};
                            border-radius: 8px;
                            padding: 0.5rem 1rem;
                            margin-left: 1rem;
                            text-align: center;
                            min-width: 80px;
                        ">
                            <div style="font-size: 0.75rem; color: {text_color};">Relevance</div>
                            <div style="font-size: 1.5rem; font-weight: bold; color: {score_color};">{score}/10</div>
                        </div>
                    </div>
                    {f'''<div style="font-size: 0.85rem; color: {text_color}; margin-top: 0.5rem;">
                        <span style="font-weight: 600;">Associated Candidates:</span> {', '.join(candidates) if candidates else 'None'}
                    </div>''' if candidates else ''}
                </div>
                """,
                unsafe_allow_html=True
            )

def _display_candidate_card(candidate, index, current_theme, text_color):
    """Display a single candidate card with all details"""
    # Extract candidate data
    is_model = hasattr(candidate, "model_dump") or hasattr(candidate, "__fields__")
    if is_model:
        name = getattr(candidate, "name", None) or "Unknown"
        role = getattr(candidate, "current_role_affiliation", None) or "N/A"
        research_focus = getattr(candidate, "research_focus", None) or []
        profiles = getattr(candidate, "profiles", None) or {}
        total_score = getattr(candidate, "total_score", None)
        radar = getattr(candidate, "radar", None)
        notable = getattr(candidate, "highlights", None)
    else:
        name = candidate.get("Name", "Unknown")
        role = candidate.get("Current Role & Affiliation", "N/A")
        research_focus = candidate.get("Research Focus", [])
        profiles = candidate.get("Profiles", {})
        total_score = candidate.get("Total Score", "N/A")
        radar = candidate.get("Radar")
        notable = candidate.get("Notable", "")
    
    # Display complete candidate card with three-column layout
    with st.expander(f"#{index} {name}", expanded=True):
        # Three-column layout: Left (name/role/score), Middle (radar), Right (research focus/profiles)
        left_col, middle_col, right_col = st.columns([1.2, 1.5, 1.3])
        
        # Left Column: Name, Role, and Final Score
        with left_col:
            st.markdown(f"### {name}")
            st.markdown(f"**📍 Role:** {role}")
            
            # Final Score with enhanced styling
            if isinstance(total_score, (int, float)):
                score_percentage = (float(total_score) / 35) * 100
                score_color = "#10b981" if score_percentage >= 80 else "#f59e0b" if score_percentage >= 60 else "#ef4444"
                
                st.markdown(
                    f"""
                <div style="
                    background: {'#065f46' if current_theme == 'dark' else '#d1fae5'};
                    border: 2px solid {score_color};
                    border-radius: 12px;
                    padding: 1rem;
                    text-align: center;
                    margin: 1rem 0;
                    box-shadow: 0 4px 12px rgba(0,0,0,0.1);
                ">
                    <div style="font-size: 0.9rem; color: {text_color}; margin-bottom: 0.5rem;">Final Score</div>
                    <div style="font-size: 2rem; font-weight: bold; color: {score_color};">{total_score}/35</div>
                    <div style="font-size: 0.8rem; color: {text_color}; margin-top: 0.5rem;">({score_percentage:.1f}%)</div>
                </div>
                """,
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f"""
                <div style="
                    background: {'#374151' if current_theme == 'dark' else '#f3f4f6'};
                    border: 2px solid {'#6b7280' if current_theme == 'dark' else '#d1d5db'};
                    border-radius: 12px;
                    padding: 1rem;
                    text-align: center;
                    margin: 1rem 0;
                ">
                    <div style="font-size: 0.9rem; color: {text_color};">Final Score</div>
                    <div style="font-size: 2rem; font-weight: bold; color: {'#9ca3af' if current_theme == 'dark' else '#6b7280'};">N/A</div>
                </div>
                """,
                    unsafe_allow_html=True,
                )
        
        # Middle Column: Radar Chart
        with middle_col:
            if isinstance(radar, dict) and len(radar) > 0:
                categories = list(radar.keys())
                values = [radar[k] for k in categories]
                
                # Enhanced label wrapping
                def _wrap_label(text):
                    if len(text) > 12:
                        if " & " in text:
                            return text.replace(" & ", " &<br>")
                        elif " " in text:
                            words = text.split(" ")
                            if len(words) > 1:
                                mid = len(words) // 2
                                return " ".join(words[:mid]) + "<br>" + " ".join(words[mid:])
                    return text
                
                display_categories = [_wrap_label(c) for c in categories]
                categories_closed = display_categories + [display_categories[0]]
                values_closed = values + [values[0]]
                
                fig = go.Figure()
                fig.add_trace(
                    go.Scatterpolar(
                        r=values_closed,
                        theta=categories_closed,
                        fill="toself",
                        name="Profile",
                        line=dict(color="#667eea", width=2),
                        fillcolor="rgba(102, 126, 234, 0.2)"
                    )
                )
                
                pad = 0.08
                fig.update_layout(
                    font=dict(size=13, family="Arial, sans-serif"),
                    hoverlabel=dict(font_size=16, font_family="Arial, sans-serif"),
                    margin=dict(l=70, r=70, t=40, b=55),
                    polar=dict(
                        domain=dict(x=[pad, 1 - pad], y=[pad + 0.02, 1 - pad]),
                        radialaxis=dict(
                            visible=True,
                            range=[0, 5],
                            ticks="outside",
                            ticklen=6,
                            tickfont=dict(size=12, color=text_color),
                            gridcolor="rgba(0,0,0,0.1)",
                            linecolor="rgba(0,0,0,0.2)"
                        ),
                        angularaxis=dict(
                            tickfont=dict(size=12, color=text_color),
                            rotation=90,
                            direction="clockwise",
                            layer="above traces"
                        ),
                        bgcolor="rgba(0,0,0,0)"
                    ),
                    showlegend=False,
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)"
                )
                st.plotly_chart(
                    fig,
                    use_container_width=False,
                    key=f"radar_chart_{index}",
                    config={
                        "displayModeBar": True,
                        "displaylogo": False,
                        "scrollZoom": True,
                        "doubleClick": "reset",
                        "modeBarButtonsToAdd": ["zoomIn", "zoomOut", "resetScale"],
                        "modeBarButtonsToRemove": ["pan", "select", "lasso", "autoScale"]
                    },
                )
            else:
                st.markdown(
                    """
                <div style="
                    height: 300px;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    background: rgba(0,0,0,0.05);
                    border-radius: 10px;
                    color: #6b7280;
                    font-style: italic;
                ">
                    No radar data available
                </div>
                """,
                    unsafe_allow_html=True,
                )
        
        # Right Column: Research Focus and Profiles
        with right_col:
            render_research_focus(research_focus, current_theme or "light", text_color)
            render_profiles(profiles, current_theme or "light", text_color)
            
            # View full profile button
            if st.button(
                "🧑 View Full Profile",
                key=f"view_profile_{index}",
                use_container_width=True,
                type="primary",
            ):
                try:
                    # Build profile payload - same logic as before
                    if is_model:
                        dump_fn = getattr(candidate, "model_dump", None)
                        if callable(dump_fn):
                            cdict = dump_fn(by_alias=True)
                        else:
                            try:
                                cdict = dict(candidate)
                            except Exception:
                                cdict = getattr(candidate, "__dict__", {}) or {}
                    else:
                        cdict = {
                            "Name": name,
                            "Email": candidate.get("Email", ""),
                            "Current Role & Affiliation": role,
                            "Current Status": candidate.get("Current Status", ""),
                            "Research Keywords": candidate.get("Research Keywords", []),
                            "Research Focus": research_focus or [],
                            "Profiles": profiles or {},
                            "Publication Overview": candidate.get("Publication Overview", []),
                            "Top-tier Hits (Last 24 Months)": candidate.get("Top-tier Hits (Last 24 Months)", []),
                            "Honors/Grants": candidate.get("Honors/Grants", []),
                            "Academic Service / Invited Talks": candidate.get("Academic Service / Invited Talks", []),
                            "Open-source / Datasets / Projects": candidate.get("Open-source / Datasets / Projects", []),
                            "Representative Papers": candidate.get("Representative Papers", []),
                            "Highlights": candidate.get("Highlights", notable or []),
                            "Radar": radar or {},
                            "Total Score": total_score or 0,
                            "Detailed Scores": candidate.get("Detailed Scores", {}),
                        }
                    
                    # Normalize representative papers
                    reps_src = cdict.get("Representative Papers", []) or []
                    normalized_reps = []
                    for rp in reps_src:
                        if isinstance(rp, dict):
                            normalized_reps.append({
                                "title": rp.get("Title") or rp.get("title", ""),
                                "venue": rp.get("Venue") or rp.get("venue", ""),
                                "year": rp.get("Year") if rp.get("Year") is not None else rp.get("year", ""),
                                "type": rp.get("Type") or rp.get("type", ""),
                                "links": rp.get("Links") or rp.get("links", ""),
                            })
                        else:
                            normalized_reps.append({
                                "title": getattr(rp, "title", ""),
                                "venue": getattr(rp, "venue", ""),
                                "year": getattr(rp, "year", ""),
                                "type": getattr(rp, "type", ""),
                                "links": getattr(rp, "links", ""),
                            })
                    
                    profile_payload = {
                        "name": cdict.get("Name", name),
                        "email": cdict.get("Email", ""),
                        "current_role_affiliation": cdict.get("Current Role & Affiliation", role),
                        "current_status": cdict.get("Current Status", ""),
                        "research_keywords": cdict.get("Research Keywords", []),
                        "research_focus": cdict.get("Research Focus", []),
                        "profiles": cdict.get("Profiles", {}),
                        "publication_overview": cdict.get("Publication Overview", []),
                        "top_tier_hits": cdict.get("Top-tier Hits (Last 24 Months)", []),
                        "honors_grants": cdict.get("Honors/Grants", []),
                        "service_talks": cdict.get("Academic Service / Invited Talks", []),
                        "open_source_projects": cdict.get("Open-source / Datasets / Projects", []),
                        "representative_papers": normalized_reps,
                        "trigger_paper_title": cdict.get("Trigger Paper Title", "") or candidate.get("Trigger Paper Title", "") if not is_model else getattr(candidate, "trigger_paper_title", ""),
                        "trigger_paper_url": cdict.get("Trigger Paper URL", "") or candidate.get("Trigger Paper URL", "") if not is_model else getattr(candidate, "trigger_paper_url", ""),
                        "highlights": cdict.get("Highlights", []),
                        "radar": cdict.get("Radar", {}),
                        "total_score": cdict.get("Total Score", 0),
                        "detailed_scores": cdict.get("Detailed Scores", {}),
                    }
                    
                    st.session_state["demo_candidate_overview_json"] = json.dumps(profile_payload)
                    st.session_state["prev_page"] = st.session_state.get("current_page", "🔍 Targeted Search")
                    st.session_state.current_page = "🧑 Candidate Profile"
                    st.session_state.page_changed = True
                    st.rerun()
                except Exception as e:
                    print(f"[View Profile] Error: {e}")
                    pass
        # Display trigger paper below the three-column layout
        # Extract trigger paper info
        if is_model:
            trigger_title = getattr(candidate, "trigger_paper_title", "")
            trigger_url = getattr(candidate, "trigger_paper_url", "")
        else:
            trigger_title = candidate.get("Trigger Paper Title", "") or candidate.get("trigger_paper_title", "")
            trigger_url = candidate.get("Trigger Paper URL", "") or candidate.get("trigger_paper_url", "")
        
        if trigger_title and trigger_title.strip():
            st.markdown("---")
            st.markdown("**📄 Paper that led to this candidate discovery:**")
            if trigger_url and trigger_url.strip():
                # Truncate title if too long for display
                import html
                display_title = trigger_title if len(trigger_title) <= 120 else trigger_title[:117] + "..."
                st.markdown(f"[{html.escape(display_title)}]({trigger_url})", unsafe_allow_html=True)
            else:
                st.markdown(f"_{trigger_title}_")


def render_research_focus(research_focus:list, current_theme:str, text_color:str):
    if not research_focus:
        return

    # 主题自适配的颜色
    if current_theme == "dark":
        chip_bg     = "rgba(59,130,246,.15)"   # 蓝色半透明
        chip_border = "rgba(59,130,246,.35)"
        chip_fg     = "#e5e7eb"
        link_color  = "#93c5fd"
        section_fg  = "#e5e7eb"
        muted       = "#94a3b8"
    else:
        chip_bg     = "#eef2ff"
        chip_border = "#c7d2fe"
        chip_fg     = "#0f172a"
        link_color  = "#2563eb"
        section_fg  = "#0f172a"
        muted       = "#475569"

    chips_html = "".join(
        f'<span class="rf-chip">{html.escape(item)}</span>'
        for item in research_focus
    )

    st.markdown(
        f"""
        <style>
        .rf-wrap {{
            display:flex; flex-wrap:wrap; gap:.4rem;
            margin:.2rem 0 .5rem 0;
            overflow-wrap: break-word;
            word-wrap: break-word;
            hyphens: auto;
        }}
        .rf-chip {{
            display:inline-block;
            padding:.2rem .6rem;
            border-radius:9999px;
            background:{chip_bg};
            border:1px solid {chip_border};
            color:{chip_fg};
            font-size:.8rem; font-weight:600;
            line-height:1.2;
            white-space:nowrap;
            max-width: 100%;
            overflow: hidden;
            text-overflow: ellipsis;
        }}
        .rf-chip:hover {{ border-color:{link_color}; }}
        .section-title {{
            color:{section_fg};
            font-weight:700;
            margin-bottom: .3rem;
        }}
        .section-title span {{ color:{muted}; font-weight:700; }}

        /* Responsive breakpoints */
        @media (max-width: 768px) {{
            .rf-wrap {{ gap:.3rem; }}
            .rf-chip {{ font-size:.75rem; padding:.18rem .5rem; }}
        }}
        @media (max-width: 480px) {{
            .rf-wrap {{ gap:.25rem; }}
            .rf-chip {{ font-size:.7rem; padding:.15rem .4rem; }}
        }}
        </style>

        <div class="section-title">🔬 Research Focus:</div>
        <div class="rf-wrap">{chips_html}</div>
        """,
        unsafe_allow_html=True,
    )


def render_profiles(profiles:dict, current_theme:str, text_color:str):
    # 过滤空链接
    items = [(k, v.strip()) for k, v in (profiles or {}).items() if v and v.strip()]
    if not items:
        return

    icons = {
        "Homepage":"🏠", "Google Scholar":"📚", "X (Twitter)":"🐦",
        "LinkedIn":"💼", "GitHub":"💻", "OpenReview":"📝", "Stanford HAI":"🎓"
    }

    if current_theme == "dark":
        link_color = "#93c5fd"; link_hover = "#bfdbfe"; bullet = "#64748b"
    else:
        link_color = "#2563eb"; link_hover = "#1d4ed8"; bullet = "#94a3b8"

    links_html = "".join(
        f'<li><a href="{html.escape(url)}" target="_blank">'
        f'<span class="pr-ico">{icons.get(platform,"🔗")}</span>'
        f'{html.escape(platform)}</a></li>'
        for platform, url in items
    )

    st.markdown(
        f"""
        <style>
        .pr-title {{
            font-weight:700;
            margin:.2rem 0 .3rem 0;
            padding: 0;
        }}
        .pr-grid {{
            display:grid;
            grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
            gap:.3rem .5rem;
            margin:.2rem 0 .4rem 0;
            padding:0;
            list-style:none;
            width: 100%;
            box-sizing: border-box;
        }}
        .pr-grid li {{
            break-inside:avoid;
            padding:0;
            margin:0;
            min-width: 0; /* Allow flex items to shrink below content size */
        }}
        .pr-grid a {{
            color:{link_color};
            text-decoration:none;
            font-size:.85rem; font-weight:500;
            display:inline-flex; align-items:center; gap:.3rem;
            padding: .2rem .3rem;
            border-radius: 6px;
            transition: background-color 0.2s ease;
            word-break: break-word;
            overflow-wrap: break-word;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            max-width: 100%;
        }}
        .pr-grid a:hover {{
            text-decoration:underline;
            color:{link_hover};
            background-color: rgba(0,0,0,0.05);
        }}
        .pr-ico {{
            width:1rem;
            text-align:center;
            flex-shrink: 0;
        }}

        /* Enhanced responsive breakpoints */
        @media (max-width: 768px) {{
            .pr-grid {{ grid-template-columns: repeat(2, 1fr); gap:.25rem .4rem; }}
            .pr-grid a {{ font-size:.8rem; gap:.25rem; }}
            .pr-ico {{ width:.9rem; }}
        }}
        @media (max-width: 480px) {{
            .pr-grid {{ grid-template-columns: 1fr; gap:.2rem .3rem; }}
            .pr-grid a {{ font-size:.75rem; gap:.2rem; }}
            .pr-ico {{ width:.8rem; }}
        }}
        @media (max-width: 360px) {{
            .pr-grid a {{ font-size:.7rem; }}
            .pr-ico {{ width:.7rem; }}
        }}
        </style>

        <div class="pr-title">🔗 Profiles:</div>
        <ul class="pr-grid">{links_html}</ul>
        """,
        unsafe_allow_html=True,
    )


def handle_new_search_request(user_input):
    """Handle new search requests"""
    if backend_available:
        # First validate if the input contains searchable content
        validation_result = agents.agent_validate_search_request(
            user_input,
            filter_chat_history_for_llm(st.session_state.get("chat_history", [])),
        )

        if not validation_result["is_valid_search"]:
            # Input doesn't contain enough searchable content
            st.session_state.validating_search = True
            st.session_state.chat_history.append(
                {
                    "role": "assistant",
                    "content": f"I need more specific information to help you find the right talent. {validation_result['suggestion']}<br><br>"
                    f"<strong>Missing elements:</strong> {', '.join(validation_result['missing_elements'])}<br>"
                    f"Please provide more details about what you're looking for.",
                }
            )
            return

        # Input is valid, proceed with parsing
        # Get API key from session state
        api_key = (st.session_state.get("llm_api_key", "") or 
                   st.session_state.get("openai_api_key", ""))
        query_spec = agents.agent_parse_search_query(user_input, api_key)

        if query_spec:
            # Store the parsed query spec
            st.session_state.query_spec = query_spec.dict()
            st.session_state.show_preview = True
            st.session_state.search_query = user_input
            st.session_state.preview_in_history = False
            st.session_state.show_results = False  # Clear any previous results
            st.session_state.validating_search = False  # Clear validation state

            # Add AI response
            st.session_state.chat_history.append(
                {
                    "role": "assistant",
                    "content": "Great! I've analyzed your request and extracted the search parameters below. Please review them and let me know if they look correct, or if you'd like me to adjust anything.",
                }
            )
        else:
            st.session_state.chat_history.append(
                {
                    "role": "assistant",
                    "content": "I had trouble understanding your request. Could you please provide more details about the type of talent you're looking for? For example:<br>• Research areas of interest<br>• Degree level (PhD, Master's, etc.)<br>• Number of candidates needed<br>• Preferred conferences or publication venues",
                }
            )
    else:
        # Backend not available
        st.session_state.chat_history.append(
            {
                "role": "assistant",
                "content": "❌ I'm sorry, but the search functionality is currently unavailable. The talent search backend is not accessible.<br><br>**Possible solutions:**<br>• Check if the talent search module is properly installed<br>• Verify network connectivity<br>• Contact system administrator for configuration help",
            }
        )


def render_targeted_search_page():
    """Render the enhanced targeted search page with MSRA demo"""
    current_theme = st.context.theme.type

    # Theme-specific styling
    if current_theme == "dark":
        header_style = "background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white;"
        card_style = "background: #1e293b; border: 2px solid #334155; color: #f1f5f9;"
        tag_style = "background: #1e40af; color: #dbeafe; border: 1px solid #3b82f6;"
        text_color = "#f1f5f9"
        success_bg = "#065f46"
        success_border = "#10b981"
        preview_bg = "#1e293b"
        preview_border = "#334155"

        user_message_background = "#5F656D"
        user_message_text_color = "#ffffff"
        assistant_message_background = "#2c2f35"
        assistant_message_border = "#3d4147"
        assistant_message_text_color = "#e2e8f0"
        system_message_background = "#CF8627"
    else:
        header_style = "background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white;"
        card_style = "background: white; border: 2px solid #e1e5e9; color: #000000;"
        tag_style = "background: #e3f2fd; color: #1976d2; border: 1px solid #bbdefb;"
        text_color = "#495057"
        success_bg = "#d4edda"
        success_border = "#28a745"
        preview_bg = "#f8f9fa"
        preview_border = "#dee2e6"

        user_message_background = "#667eea"
        user_message_text_color = "#ffffff"
        assistant_message_background = "#f5f5f5"
        assistant_message_border = "#e0e0e0"
        assistant_message_text_color = "#2c3e50"
        system_message_background = "#f8f9fa"
    squash_top_gap()

    _inject_search_progress_stytles(current_theme)

    # Main layout - Left side for search and preview, right side for results
    col1, col2 = st.columns([1, 1.4])

    with col1:
        # Initialize chat history if not exists
        if "chat_history" not in st.session_state:
            st.session_state.chat_history = []
        if "awaiting_confirmation" not in st.session_state:
            st.session_state.awaiting_confirmation = False
        if "preview_in_history" not in st.session_state:
            st.session_state.preview_in_history = False

        # Chat History Display
        chat_container = st.container()

        with chat_container:
            # Display chat history
            
            for i, message in enumerate(st.session_state.chat_history):
                if message["role"] == "user":
                    # User message bubble (right-aligned)
                    # Use <pre> tag to display content as-is without HTML parsing
                    raw_content = message["content"].replace("<", "&lt;").replace(">", "&gt;")
                    
                    st.markdown(
                        f"""
                    <div style="
                        background: {user_message_background};
                        border-radius: 18px 18px 4px 18px;
                        padding: 0.8rem 1.2rem;
                        margin: 0.5rem 0 0.5rem auto;
                        max-width: 80%;
                        width: fit-content;
                        margin-left: 20%;
                        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
                        border: 1px solid {user_message_background};
                        color: {user_message_text_color};
                    ">
                        <div style="margin-bottom: 0.3rem; font-size: 0.85em; opacity: 0.8;">
                            <strong>👤 You</strong>
                        </div>
                        <pre style="
                            margin: 0;
                            padding: 0;
                            font-family: inherit;
                            font-size: inherit;
                            line-height: 1.6;
                            white-space: pre-wrap;
                            word-wrap: break-word;
                            background: transparent;
                            border: none;
                        ">{raw_content}</pre>
                    </div>
                    """,
                        unsafe_allow_html=True,
                    )

                elif message["role"] == "assistant":
                    # Assistant message bubble (left-aligned)
                    content = message["content"]
                    
                    # Check if content contains intentional HTML formatting
                    has_html = ("<div" in content or "<p>" in content or "<strong>" in content)
                    
                    if has_html:
                        # Keep HTML formatting for system messages
                        content_html = content
                    else:
                        # Escape user-generated content
                        content_html = f'<pre style="margin: 0; padding: 0; font-family: inherit; font-size: inherit; line-height: 1.6; white-space: pre-wrap; word-wrap: break-word; background: transparent; border: none;">{content.replace("<", "&lt;").replace(">", "&gt;")}</pre>'
                    
                    st.markdown(
                        f"""
                    <div style="
                        background: {assistant_message_background};
                        border-radius: 18px 18px 18px 4px;
                        padding: 0.8rem 1.2rem;
                        margin: 0.5rem auto 0.5rem 0;
                        max-width: 80%;
                        width: fit-content;
                        margin-right: 20%;
                        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
                        border: 1px solid {assistant_message_border};
                        color: {assistant_message_text_color};
                    ">
                        <div style="margin-bottom: 0.3rem; font-size: 0.85em; opacity: 0.8;">
                            <strong>🤖 AI Assistant</strong>
                        </div>
                        <div style="line-height: 1.6;">
                            {content_html}
                        </div>
                    </div>
                    """,
                        unsafe_allow_html=True,
                    )

                elif message["role"] == "system":
                    # System message (search parameters, progress, etc.) - neutral styling
                    st.markdown(
                        f"""
                    <div style="
                        margin: 0.5rem 0;
                    ">
                        {message["content"]}
                    </div>
                    """,
                        unsafe_allow_html=True,
                    )

        # Show search parameters if available
        if st.session_state.get("show_preview", False) and st.session_state.get(
            "query_spec"
        ):
            query_spec = st.session_state.query_spec

            # Display extracted parameters in a nice format
            params_html = "<h4>📊 Extracted Search Parameters:</h4>"

            if query_spec.get("top_n"):
                params_html += (
                    f"<p><strong>👥 Candidates:</strong> {query_spec['top_n']}</p>"
                )
            
            # Display research field if available
            if query_spec.get("research_field"):
                params_html += (
                    f"<p><strong>🎯 Research Field:</strong> {query_spec['research_field']}</p>"
                )

            kw_bg = "#536833"
            kw_border = "#334155"
            kw_color = "#dbeafe"
            if query_spec.get("keywords"):
                # Theme-specific tag styling for research areas
                if current_theme == "dark":
                    kw_bg = "#536833"
                    kw_border = "#334155"
                    kw_color = "#dbeafe"
                else:
                    kw_bg = "#e3f2fd"
                    kw_border = "#bbdefb"
                    kw_color = "#1976d2"
                keywords_str = ", ".join(
                    [
                        f"<span style='background: {kw_bg}; color: {kw_color}; border: 1px solid {kw_border}; padding: 2px 6px; border-radius: 10px; font-size: 0.9em;'>{k}</span>"
                        for k in query_spec["keywords"]
                    ]
                )
                params_html += (
                    f"<p><strong>🔬 Research Areas:</strong> {keywords_str}</p>"
                )

            if query_spec.get("degree_levels"):
                degrees_str = ", ".join(
                    [
                        f"<span style='background: {kw_bg}; color: {kw_color}; border: 1px solid {kw_border}; padding: 2px 6px; border-radius: 10px; font-size: 0.9em;'>{d}</span>"
                        for d in query_spec["degree_levels"]
                    ]
                )
                params_html += f"<p><strong>🎓 Degrees:</strong> {degrees_str}</p>"

            # Add preview to chat history once so it persists
            if not st.session_state.get("preview_in_history", False):
                st.session_state.preview_in_history = True

                st.session_state.chat_history.append(
                    {
                        "role": "system",
                        "content": f"""
                    <div style="
                        background: {preview_bg};
                        border: 1px solid {preview_border};
                        border-radius: 10px;
                        padding: 1rem;
                        margin: 0.5rem 0;
                    ">
                        {params_html}
                    </div>
                    """,
                    }
                )

            # Always render the preview card
            preview_card_html = f"""
            <div style="
                background: {preview_bg};
                border: 1px solid {preview_border};
                border-radius: 10px;
                padding: 1rem;
                margin: 0.5rem 0;
            ">
                {params_html}
            </div>
            """

            # show the preview card in html
            st.markdown(preview_card_html, unsafe_allow_html=True)

            # default session state set show_para_preview = True
            st.session_state.show_para_preview = True

            # Confirmation buttons (always visible while awaiting confirmation)
            if not st.session_state.get("awaiting_confirmation", False):
                col_confirm1,  = st.columns(1)
                with col_confirm1:
                    if st.button(
                        "✅ Looks Good! Start Search",
                        type="primary",
                        use_container_width=True,
                    ):
                        # Add confirmation to chat
                        st.session_state.chat_history.append(
                            {
                                "role": "user",
                                "content": "✅ Yes, these parameters look good. Please start the search!",
                            }
                        )
                        st.session_state.awaiting_confirmation = True
                        st.session_state.show_preview = False

                        st.session_state.show_para_preview = False

                        st.rerun()

        # Handle user decision for paused search (continue or finish)        
        if st.session_state.get("search_action") in ["continue", "finish"]:
            action = st.session_state.search_action
            task_id = st.session_state.get("current_task_id")
            
            # Clear the action from session state
            del st.session_state.search_action
            print("="*100 + "\n")
            if action == "continue":
                # User chose to continue - resume search for 2 more rounds (1 cycle)
                st.session_state.chat_history.append({
                    "role": "user",
                    "content": "🔄 Continue to the next search cycle (2 rounds)"
                })
                st.session_state.chat_history.append({
                    "role": "assistant",
                    "content": "✅ Great! Starting a new search cycle, will conduct 2 rounds of search..."
                })

                # Load task state and resume
                try:
                    # Import task_manager dynamically to avoid scope issues
                    sys.path.insert(0, str(talent_search_module_dir))
                    from task_manager import load_task_state

                    task_state = load_task_state(task_id)
                    
                    if task_state:
                        # 验证候选人是否与 partial_search_results 一致
                        partial_count = st.session_state.partial_search_results.total_candidates_found
                        task_count = len(task_state.candidates_accum)
                        print(f"  - partial_search_results show: {partial_count} candidates")
                        print(f"  - task_state actually contains: {task_count} candidates")
                        if partial_count == task_count:
                            print(f"  ✅ Data consistent! Will continue to search with these {task_count} candidates")
                        else:
                            print(f"  ⚠️ Data inconsistent! Possible synchronization issue")

                        # Resume search - set awaiting_confirmation to trigger search
                        st.session_state.awaiting_confirmation = True
                        st.session_state.resume_task_state = task_state
                        st.session_state.show_preview = False
                        st.session_state.show_results = False
                        if "_finishing_in_progress" in st.session_state:
                            del st.session_state._finishing_in_progress
                        st.rerun()
                    else:
                        st.error("Cannot resume search task, please start again")
                        # Clean up states on error
                        if "awaiting_confirmation" in st.session_state:
                            del st.session_state.awaiting_confirmation
                        if "resume_task_state" in st.session_state:
                            del st.session_state.resume_task_state
                        if "_finishing_in_progress" in st.session_state:
                            del st.session_state._finishing_in_progress
                        return
                except Exception as e:
                    st.error(f"Failed to resume task: {e}")
                    import traceback
                    traceback.print_exc()
                    # Clean up states on error
                    if "awaiting_confirmation" in st.session_state:
                        del st.session_state.awaiting_confirmation
                    if "resume_task_state" in st.session_state:
                        del st.session_state.resume_task_state
                    if "_finishing_in_progress" in st.session_state:
                        del st.session_state._finishing_in_progress
                    return
                    
            elif action == "finish":
                # Check if already finishing to prevent duplicate execution
                if st.session_state.get("_finishing_in_progress", False):
                    return
                # Set finishing flag
                st.session_state._finishing_in_progress = True                
                # User chose to finish - finalize results from current candidates
                st.session_state.chat_history.append({
                    "role": "user",
                    "content": "✅ Finish search, sort the current candidates"
                })
                # Load task state and finalize
                try:
                    # Import modules dynamically to avoid scope issues
                    sys.path.insert(0, str(talent_search_module_dir))
                    from task_manager import load_task_state, delete_task_state
                    task_state = load_task_state(task_id)
                    
                    if task_state:
                        # 验证候选人是否与 partial_search_results 一致
                        partial_count = st.session_state.partial_search_results.total_candidates_found
                        task_count = len(task_state.candidates_accum)
                        # Finalize results by calling finish function
                        api_key = (st.session_state.get("llm_api_key", "") or
                                  st.session_state.get("openai_api_key", ""))
                        # Show progress message
                        with st.spinner("Sorting and scoring candidates..."):
                            final_results = agents.agent_finish_search(task_state, api_key)
                        # Store results and show them
                        st.session_state.search_results = final_results
                        st.session_state.full_search_results = final_results
                        st.session_state.show_results = True
                        delete_task_state(task_id)
                        # Delete search execution states
                        states_to_delete = ["awaiting_confirmation", "resume_task_state", "_search_started", "show_preview"]
                        for state in states_to_delete:
                            if state in st.session_state:
                                del st.session_state[state]
                        # Add success message to chat
                        st.session_state.chat_history.append({
                            "role": "assistant",
                            "content": f"✅ Search completed! Found {final_results.total_candidates_found} candidates, sorted by relevance."
                        })
                        # Force rerun to render results immediately
                        st.rerun()
                    else:
                        st.error("Cannot resume search task, please start again")
                        # Clear states even on error
                        if "awaiting_confirmation" in st.session_state:
                            del st.session_state.awaiting_confirmation
                        if "_finishing_in_progress" in st.session_state:
                            del st.session_state._finishing_in_progress
                        if "resume_task_state" in st.session_state:
                            del st.session_state.resume_task_state
                        if "_search_started" in st.session_state:
                            del st.session_state._search_started
                        if "partial_search_results" in st.session_state:
                            del st.session_state.partial_search_results
                        return
                        
                except Exception as e:
                    st.error(f"Failed to process results: {e}")
                    import traceback
                    traceback.print_exc()
                    # Clear states even on error
                    if "awaiting_confirmation" in st.session_state:
                        del st.session_state.awaiting_confirmation
                    if "_finishing_in_progress" in st.session_state:
                        del st.session_state._finishing_in_progress
                    if "resume_task_state" in st.session_state:
                        del st.session_state.resume_task_state
                    if "_search_started" in st.session_state:
                        del st.session_state._search_started
                    if "partial_search_results" in st.session_state:
                        del st.session_state.partial_search_results
                    return
        
        # Execute search if confirmed
        # Only execute search if not finishing and user confirmed       
        should_launch = (st.session_state.get("awaiting_confirmation", False) and 
                        not st.session_state.get("_finishing_in_progress", False) and
                        not st.session_state.get("showing_decision_dialog", False))
        if should_launch:
            if st.session_state.get("resume_task_state"):
                resume_state = st.session_state.resume_task_state
        if should_launch:         
            # Check if we're resuming - don't add duplicate messages
            is_resuming = st.session_state.get("resume_task_state", None) is not None
            # Add AI response and start search (only if not resuming)
            if not is_resuming and not st.session_state.get("_search_started", False):
                st.session_state.chat_history.append(
                    {
                        "role": "assistant",
                        "content": "🚀 Perfect! Starting the targeted search now. This may take a few moments...",
                    }
                )
                st.session_state._search_started = True

            # Define search steps and event mapping
            search_steps = [
                "Planning search strategy...",           # Step 0: parsing
                "Searching and analyzing...",            # Step 1: searching papers and analyzing candidates
                "Ranking and scoring...",                # Step 3: sorting by relevance
                "Finalizing results...",                 # Step 4: preparing output
            ]

            # Define event mapping (backend progress events -> UI step index)
            event_to_step = {
                "parsing": 0,           # 0-10%: Planning search terms
                "searching": 1,         # 10-45%: Searching, fetching, extracting
                "analyzing": 1,         # 45-75%: Analyzing candidates
                "ranking": 2,           # 75-90%: Ranking results
                "finalizing": 3,        # 90-100%: Final preparation
                "done": 3,              # Completion
            }
            

            # ========== UI container initialization ==========
            overlay = st.empty()  # for displaying progress popup
            prog = st.progress(0)  # progress bar
            
            # ========== thread-safe progress channel ==========
            progress_q = queue.Queue()  # queue: store (event name, progress percentage)
            result_holder = {"results": None, "error": None}  # store search results
            status_info = {"candidates": 0, "current_action": "", "detail": ""}  # status info
            
            # ========== progress callback function ==========
            def on_progress(event: str, pct: float):
                """
                background thread calls this function to report progress
                parameters：
                - event: event name, like "searching", "analyzing"
                - pct: progress percentage 0.0-1.0
                """
                try:
                    progress_q.put((event or "", float(pct or 0.0)))
                except Exception:
                    pass  # silent failure, do not interrupt search
            
            # ========== 后台搜索函数 ==========
            def run_search_in_background(query_spec_dict, api_key, resume_state=None):
                """
                execute search in background thread
                this function will run in another thread, not block UI
                
                Args:
                    query_spec_dict: Query specification dictionary
                    api_key: API key for LLM
                    resume_state: Optional SearchTaskState to resume from
                """
                # Import at function level to avoid scope issues
                import sys
                from pathlib import Path
                
                # Ensure paths are in sys.path
                current_dir = Path(__file__).parent
                backend_dir = current_dir.parent / "backend"
                talent_search_module_dir = backend_dir / "talent_search_module"
                sys.path.insert(0, str(backend_dir))
                sys.path.insert(0, str(talent_search_module_dir))
                
                try:
                    # Import modules at function level
                    import agents as agents_module
                    from schemas import QuerySpec, PartialSearchResults
                    
                    # convert to QuerySpec object
                    cp_query_spec = query_spec_dict.copy()
                    search_query_spec = QuerySpec(**cp_query_spec)
                    
                    if backend_available:
                        try:
                            # Real search with progress callback
                            # The backend will now report real progress through on_progress
                            search_results_obj = agents_module.agent_execute_search(
                                search_query_spec, 
                                api_key=api_key,
                                progress_callback=on_progress,  # Pass progress callback to backend
                                resume_state=resume_state  # Resume from saved state if provided
                            )
                            
                            # Check if we got partial results (need user decision)
                            if isinstance(search_results_obj, PartialSearchResults):
                                # Partial results - need user decision
                                result_holder["partial_results"] = search_results_obj
                                on_progress("paused", 0.5)  # Signal that we're paused
                                return
                            
                            # Store the complete SearchResults object
                            search_results = search_results_obj
                            
                        except Exception as search_error:
                            # real search failed
                            print(f"[Search] Real search failed: {search_error}, please try again")
                            on_progress("done", 1.0)
                            result_holder["error"] = search_error
                            return
                    else:
                        # backend not available
                        print(f"Please try again later!")
                        on_progress("done", 1.0)
                        result_holder["error"] = Exception("Backend not available")
                        return
                    
                    # store results
                    result_holder["results"] = search_results
                    # Also store the full results object for displaying paper list
                    if 'search_results_obj' in locals():
                        result_holder["full_results"] = search_results_obj
                    
                except Exception as e:
                    # error occurred, store error
                    result_holder["error"] = e
                    print(f"[Search] Error in background thread: {e}")
                    # Ensure we signal completion even on error
                    on_progress("done", 1.0)
            
            # ========== start background thread ==========
            query_spec = st.session_state.query_spec
            api_key = (st.session_state.get("llm_api_key", "") or 
                      st.session_state.get("openai_api_key", ""))
            
            # Check if we're resuming from a paused state
            # IMPORTANT: Don't delete it yet, just get a reference
            resume_state = st.session_state.get("resume_task_state", None)
            if resume_state:
                print(f"[Frontend] Found resume_task_state in session!")
                print(f"[Frontend]   - Task ID: {resume_state.task_id}")
                print(f"[Frontend]   - Candidates: {len(resume_state.candidates_accum)}")
                print(f"[Frontend]   - Position: {resume_state.pos}/{len(resume_state.terms)}")
                # Don't delete it here - we need it for the search thread
            else:
                print(f"[Frontend] No resume_task_state found, starting new search")
            
            # create and start background thread
            worker = threading.Thread(
                target=run_search_in_background,
                daemon=True,  # daemon thread: automatically end when main program exits
                args=(query_spec, api_key, resume_state)
            )
            worker.start()
            
            # Now clear the resume_task_state since we've used it
            if "resume_task_state" in st.session_state:
                del st.session_state.resume_task_state
                print(f"[Frontend] Cleared resume_task_state from session after starting thread")
            
            # ========== main thread: real-time update UI ==========
            current_step = 0  # current step index
            last_pct = 0      # last progress percentage
            target_count = query_spec.get('top_n', 10)  # 获取目标候选人数量
            
            # first display progress popup with initial status
            overlay.markdown(
                _render_search_progress_overlay(
                    search_steps, 
                    current_step,
                    candidates_found=0,
                    target_count=target_count,
                    current_action="Initializing search...",
                    detail_info="Preparing search parameters"
                ),
                unsafe_allow_html=True
            )
            
            # loop: continuously update UI until search is completed
            # condition: worker is alive or queue has data
            paused_for_decision = False  # Track if we're paused waiting for user decision
            
            while worker.is_alive() or not progress_q.empty():
                try:
                    # get progress update from queue (wait up to 0.1 seconds)
                    event, pct = progress_q.get(timeout=0.1)
                    
                    # ========== Check for pause event ==========
                    if event == "paused":
                        paused_for_decision = True
                        break  # Exit loop to show decision dialog
                    
                    # ========== Parse event information ==========
                    # Event format examples:
                    # - "searching"
                    # - "analyzing:candidate_name"
                    # - "scoring:paper_title"
                    # - "found:5" (found 5 candidates)
                    
                    event_str = event or ""
                    base_event = event_str.split(":", 1)[0]
                    event_detail = event_str.split(":", 1)[1] if ":" in event_str else ""
                    
                    # ========== Update status information ==========
                    # Extract candidate count if event contains "found"
                    if "found:" in event_str:
                        try:
                            status_info["candidates"] = int(event_detail)
                        except:
                            pass
                    
                    # Map events to readable English descriptions
                    action_map = {
                        "searching": "Searching papers",
                        "fetching": "Fetching paper content",
                        "scoring": "Scoring papers",
                        "extracting": "Extracting paper info",
                        "analyzing": "Analyzing candidate",
                        "discovering": "Discovering candidates",
                        "ranking": "Ranking candidates",
                        "finalizing": "Generating results",
                        "done": "Search completed"
                    }
                    
                    current_action = action_map.get(base_event, "Processing...")
                    detail_info = event_detail if event_detail else ""
                    
                    # Update status info
                    status_info["current_action"] = current_action
                    status_info["detail"] = detail_info
                    
                    # ========== update step display ==========
                    # find corresponding step index
                    step_idx = event_to_step.get(base_event, current_step)
                    
                    # Always update popup with current status (not just when step changes)
                    # This ensures the status info is always up-to-date
                    if step_idx != current_step:
                        current_step = step_idx
                    
                    # Update overlay with both step and status information
                        overlay.markdown(
                        _render_search_progress_overlay(
                            search_steps, 
                            current_step,
                            candidates_found=status_info["candidates"],
                            target_count=target_count,
                            current_action=current_action,
                            detail_info=detail_info
                        ),
                            unsafe_allow_html=True
                        )
                    
                    # ========== update progress bar ==========
                    p = max(0, min(100, int((pct or 0.0) * 100)))
                    if p != last_pct:
                        prog.progress(p)
                        last_pct = p
                
                except queue.Empty:
                    # queue is empty, continue loop
                    pass
                except Exception as e:
                    # other exceptions, print but do not interrupt
                    print(f"[Progress Update] Error: {e}")
                    pass
                
                # small delay, avoid high CPU usage
                time.sleep(0.05)
            
            # ========== Handle paused state - show user decision dialog ==========
            # First, save partial results to session if just paused
            if paused_for_decision and "partial_results" in result_holder:
                st.session_state.partial_search_results = result_holder["partial_results"]
                # CRITICAL: Clear search trigger flags ONCE when first pausing
                # This prevents accidental search restart, but only do it the first time
                if "awaiting_confirmation" in st.session_state:
                    del st.session_state.awaiting_confirmation
                if "resume_task_state" in st.session_state:
                    del st.session_state.resume_task_state
                if "_search_started" in st.session_state:
                    del st.session_state._search_started
                
                st.session_state.showing_decision_dialog = True
            
            # Check if we should show decision dialog
            print(f"\n[Decision Dialog Check]")
            print(f"  - partial_search_results in session: {st.session_state.get('partial_search_results') is not None}")
            print(f"  - showing_decision_dialog: {st.session_state.get('showing_decision_dialog', False)}")
            
            should_show_dialog = st.session_state.get("showing_decision_dialog", False) and st.session_state.get("partial_search_results") is not None
            print(f"  → should_show_dialog: {should_show_dialog}\n")
            
            if should_show_dialog:                
                # Get partial_results from session_state (already saved above)
                partial_results = st.session_state.partial_search_results
                print(f"[Paused State] Partial results information:")
                print(f"  - task_id: {partial_results.task_id}")
                print(f"  - rounds_completed: {partial_results.rounds_completed} 轮")
                print(f"  - total_candidates_found: {partial_results.total_candidates_found} 个")
                print(f"  - current_candidates number: {len(partial_results.current_candidates)} 个")
                print(f"  - message: {partial_results.message}")
                
                # Clear progress overlay
                overlay.empty()
                prog.empty()                
                # Calculate current cycle number (2 rounds = 1 cycle)
                current_cycle = partial_results.rounds_completed // 2
                
                # Show info message
                research_field_str = f"\n                - 🎯 Research Field：{st.session_state.query_spec.get('research_field', 'N/A')}" if st.session_state.query_spec.get('research_field') else ""
                st.info(f"""
                ### 🔍 Search cycle completed
                
                Completed the **{current_cycle}** search cycle (2 rounds per cycle)
                
                **Current progress：**
                - 📊 Round completed：{partial_results.rounds_completed} 轮
                - 👥 Candidate found：{partial_results.total_candidates_found} 位
                - 🎯 Target number of people：{st.session_state.query_spec.get('top_n', 10)} 位{research_field_str}
                """)
                
                st.markdown("---")
                st.markdown("### 💡 Please select the next action")
                st.markdown("*Tip: Each cycle includes 2 rounds of searches. You can choose to continue to the next cycle or view the current results.*")
                # Show decision buttons
                print(f"  - partial_search_results: {st.session_state.partial_search_results.task_id}")
                print(f"  - showing_decision_dialog: {st.session_state.showing_decision_dialog}")
                col1, col2, col3 = st.columns([1, 1, 1])
                
                with col1:
                    # Use on_click callback to ensure state is set BEFORE rerun
                    def handle_continue():
                        st.session_state.search_action = "continue"
                        st.session_state.current_task_id = st.session_state.partial_search_results.task_id
                        if "showing_decision_dialog" in st.session_state:
                            del st.session_state.showing_decision_dialog                    
                    st.button(
                        "🔄 Continue", 
                        key="continue_search", 
                        use_container_width=True, 
                        type="primary",
                        on_click=handle_continue
                    )
                    
                    # Check if button was just clicked (for debugging)
                    if st.session_state.get("search_action") == "continue":
                        print(f"  ✅ Detected search_action='continue', will continue searching")
                
                with col2:
                    print(f"  - Render the 'Complete' button (key=finish_search)")
                    # Use on_click callback to ensure state is set BEFORE rerun
                    def handle_finish():
                        st.session_state.search_action = "finish"
                        st.session_state.current_task_id = st.session_state.partial_search_results.task_id
                        if "showing_decision_dialog" in st.session_state:
                            del st.session_state.showing_decision_dialog                    
                    st.button(
                        "✅ Finish", 
                        key="finish_search", 
                        use_container_width=True,
                        on_click=handle_finish
                    )
                    
                    # Check if button was just clicked (for debugging)
                    if st.session_state.get("search_action") == "finish":
                        print(f"  ✅ Detected search_action='finish', will enter the sorting process")
                
                with col3:
                    st.markdown("")  # Empty column for spacing
                
                # Exit here - wait for user decision
                return
            
            # ========== search completed, process results ==========
            try:
                # wait for thread to completely finish
                worker.join(timeout=0.1)
                
                # check if there is an error
                if result_holder["error"] is not None:
                    raise result_holder["error"]
                
                # get search results
                results = result_holder["results"]
                
                # Check if we have valid results - handle both SearchResults object and list
                has_valid_results = False
                if results is not None:
                    if hasattr(results, 'recommended_candidates'):
                        # New SearchResults structure
                        has_valid_results = (
                            (results.recommended_candidates and len(results.recommended_candidates) > 0) or
                            (results.additional_candidates and len(results.additional_candidates) > 0)
                        )
                    elif isinstance(results, list):
                        # Old list structure
                        has_valid_results = len(results) > 0
                    else:
                        has_valid_results = True  # Unknown structure, try to process
                
                if has_valid_results:
                    # ========== success: store and display results ==========
                    st.session_state.search_results = results
                    # Store the full results object if available
                    if "full_results" in result_holder:
                        st.session_state.full_search_results = result_holder["full_results"]
                    st.session_state.show_preview = False
                    st.session_state.show_results = True
                    st.session_state.awaiting_confirmation = False
                    
                    # ========== generate summary ==========
                    try:
                        # Get total candidate count
                        if hasattr(results, 'recommended_candidates'):
                            total_count = len(results.recommended_candidates or []) + len(results.additional_candidates or [])
                            all_candidates = (results.recommended_candidates or []) + (results.additional_candidates or [])
                        else:
                            total_count = len(results) if isinstance(results, list) else 0
                            all_candidates = results if isinstance(results, list) else []
                        
                        if backend_available:
                            summary = agents.agent_generate_search_summary(results, query_spec)
                            st.session_state.search_summary = summary if summary else \
                                f"I found {total_count} candidates that match your criteria."
                        else:
                            # easy summary
                            top_areas = []
                            for candidate in all_candidates[:3]:
                                if hasattr(candidate, "research_focus"):
                                    areas = getattr(candidate, "research_focus", [])
                                else:
                                    areas = candidate.get("Research Focus", [])
                                top_areas.extend(areas[:2] if areas else [])
                            
                            unique_areas = list(set(top_areas))[:4]
                            areas_text = ", ".join(unique_areas) if unique_areas else "machine learning and AI"
                            
                            st.session_state.search_summary = \
                                f"Great! I found {total_count} promising candidates for you. " \
                                f"The search returned researchers specializing in {areas_text}. " \
                                f"Most candidates are PhD students or recent graduates from top universities."
                    except Exception as e:
                        print(f"[Summary] Error generating summary: {e}")
                        # Fallback summary
                        try:
                            if hasattr(results, 'recommended_candidates'):
                                count = len(results.recommended_candidates or []) + len(results.additional_candidates or [])
                            else:
                                count = len(results) if isinstance(results, list) else 0
                            st.session_state.search_summary = f"I found {count} candidates that match your criteria."
                        except:
                            st.session_state.search_summary = "I found candidates that match your criteria."
                    
                    # ========== add completion message ==========
                    st.session_state.chat_history.append({
                        "role": "assistant",
                        "content": f"✅ Search Completed!\n\n📊 Summary: {st.session_state.search_summary}\n\n"
                                  f"You can review all {total_count} candidates in the results panel on the right. "
                                  f"Are you satisfied with these results, or would you like me to adjust the search parameters?"
                    })
                    
                    # clear progress display
                    overlay.empty()
                    prog.empty()
                    
                    # reload page
                    st.rerun()
                else:
                    # Search failed or no results found
                    overlay.empty()
                    prog.empty()
                    st.error("Search failed or returned no results. Please try again.")
                    st.session_state.awaiting_confirmation = False
            
            except Exception as e:
                # Error handling
                overlay.empty()
                prog.empty()
                st.error(f"❌ Error during search: {str(e)}")
                print(f"[Search] Error processing results: {e}")
                st.session_state.awaiting_confirmation = False

        # Chat Input
        st.markdown("---")

        # Text input for new messages
        if not st.session_state.get("awaiting_confirmation", False):
            # If previous send requested a clear, do it BEFORE widget instantiation
            if st.session_state.get("clear_chat_input", False):
                st.session_state.chat_input = ""
                st.session_state.clear_chat_input = False

            user_input = st.text_area(
                "💬 Your message:",
                height=300,
                placeholder="Describe the talent you're looking for, or ask me to adjust the search parameters...",
                key="chat_input",
            )

            col_send1, col_send2 = st.columns([2, 1])

            with col_send1:
                if st.button(
                    "📤 Send Message", type="primary", use_container_width=True
                ):
                    if user_input and user_input.strip():
                        cp_user_input = copy.deepcopy(user_input)

                        # request clearing the input on next rerun (must happen before widget instantiation)
                        st.session_state.clear_chat_input = True

                        # Add user message to chat history
                        st.session_state.chat_history.append(
                            {"role": "user", "content": cp_user_input}
                        )

                        # Check if API key is set - support both new and old format
                        api_key_available = (st.session_state.get("llm_api_key", "") or 
                                           st.session_state.get("openai_api_key", ""))
                        if not api_key_available:
                            st.session_state.chat_history.append(
                                {
                                    "role": "assistant",
                                    "content": "⚠️ **LLM API Key Required**<br>Please configure your LLM API settings in the sidebar (🛠️ Settings → 🤖 LLM Configuration) to use AI-powered search features.",
                                }
                            )
                            st.rerun()

                        # Process the message
                        with st.spinner("🤖 AI is thinking..."):
                            try:
                                process_user_message(cp_user_input)
                                st.rerun()

                            except Exception as e:
                                st.session_state.chat_history.append(
                                    {
                                        "role": "assistant",
                                        "content": f"I encountered an error while processing your request: {e}<br>Please try again or rephrase your query.",
                                    }
                                )
                                st.rerun()
                    else:
                        st.warning("Please enter a message!")

            with col_send2:
                if st.button(
                    "🔄 Clear Chat", type="secondary", use_container_width=True
                ):
                    st.session_state.chat_history = []
                    st.session_state.show_preview = False
                    st.session_state.query_spec = None
                    st.session_state.search_query = None
                    st.session_state.awaiting_confirmation = False
                    st.session_state.show_para_preview = False
                    st.session_state.show_results = False
                    st.session_state.validating_search = False

                    if "preview_in_history" in st.session_state:
                        del st.session_state.preview_in_history
                    if "candidate_count" in st.session_state:
                        del st.session_state.candidate_count
                    st.rerun()

    with col2:
        # Results Section - Right side for search results
        col2_header1, col2_header2 = st.columns([3, 1])
        
        with col2_header1:
            # Check if we have the new structured results
            full_results = st.session_state.get("full_search_results", None)
            if full_results and hasattr(full_results, "recommended_candidates"):
                st.markdown("### 📊 Search Results")
            else:
                st.markdown("### 📊 Search Results")
        
        with col2_header2:
            # Full screen button - only show when there are results
            search_results = st.session_state.get("search_results")
            has_results = search_results is not None and (
                (isinstance(search_results, list) and len(search_results) > 0) or
                (hasattr(search_results, 'empty') and not search_results.empty) or
                (isinstance(search_results, dict) and len(search_results) > 0)
            )
            
            if st.session_state.get("show_results", False) and has_results:
                if st.button("🔍 Full Screen", type="primary", use_container_width=True):
                    # Store current page for back navigation
                    st.session_state["prev_page"] = st.session_state.get("current_page", "🔍 Targeted Search")
                    # Navigate to full screen results page
                    st.session_state.current_page = "🔍 Full Screen Results"
                    st.session_state.page_changed = True
                    st.rerun()

        # Check if we should show results
        will_show = st.session_state.get("show_results", False) and st.session_state.get("search_results") is not None
        if st.session_state.get("show_results", False) and st.session_state.get(
            "search_results"
        ):
            # Clean up finishing flag when displaying results
            if "_finishing_in_progress" in st.session_state:
                del st.session_state._finishing_in_progress
            if "partial_search_results" in st.session_state:
                del st.session_state.partial_search_results
            results = st.session_state.search_results
            print(f"\n[Results Display] Get result object")
            print(f"  - Result type: {type(results)}")
            if hasattr(results, 'total_candidates_found'):
                print(f"  - Total candidate number: {results.total_candidates_found}")
                print(f"  - Recommended: {len(results.recommended_candidates)} ")
                print(f"  - Additional: {len(results.additional_candidates)} ")
                print(f"  - Reference papers: {len(results.reference_papers)} ")

            # Handle new SearchResults structure or old list format
            if hasattr(results, 'recommended_candidates'):
                # New structure with SearchResults object
                recommended = results.recommended_candidates or []
                additional = results.additional_candidates or []
                reference_papers = results.reference_papers or []
                
                # Display Recommended Candidates section
                if recommended and len(recommended) > 0:
                    st.markdown("---")
                    st.markdown("## 🎯 Recommended Candidates")
                    st.markdown(f"*Top {len(recommended)} candidates highly matching your requirements*")
                    st.markdown("")
                    
                    for i, candidate in enumerate(recommended, 1):
                        _display_candidate_card(candidate, i, current_theme, text_color)
                
                # Display Additional Candidates section
                if additional and len(additional) > 0:
                    st.markdown("---")
                    st.markdown("## 💡 People You May Be Interested In")
                    st.markdown(f"*{len(additional)} additional candidates that may be relevant*")
                    st.markdown("")
                    
                    for i, candidate in enumerate(additional, len(recommended) + 1):
                        _display_candidate_card(candidate, i, current_theme, text_color)
                
                # Display Reference Papers section
                if reference_papers and len(reference_papers) > 0:
                    st.markdown("---")
                    st.markdown("## 📚 Reference Paper List")
                    st.markdown(f"*All {len(reference_papers)} papers scored by relevance (highest to lowest)*")
                    st.markdown("")
                    
                    _display_reference_papers(reference_papers, current_theme, text_color)
            
            else:
                # Old format - backward compatibility
                if isinstance(results, pd.DataFrame):
                    results = results.to_dict("records") if not results.empty else []

                if results and len(results) > 0:
                    # Display each candidate; support CandidateOverview object with dot access
                    for i, candidate in enumerate(results, 1):
                        _display_candidate_card(candidate, i, current_theme, text_color)
                
                # Export options
                st.markdown("### 📤 Export Results")

                col2_1, col2_2 = st.columns(2)

                with col2_1:
                    if st.button(
                        "📊 Export as CSV", type="secondary", use_container_width=True
                    ):
                        # Convert to DataFrame for CSV export
                        df_data = []
                        for candidate in results:
                            is_model = hasattr(candidate, "model_dump") or hasattr(candidate, "__fields__")
                            if is_model:
                                df_data.append(
                                    {
                                        "Name": getattr(candidate, "name", ""),
                                        "Current Role & Affiliation": getattr(candidate, "current_role_affiliation", ""),
                                        "Research Focus": ", ".join(getattr(candidate, "research_focus", []) or []),
                                        "Homepage": (getattr(candidate, "profiles", {}) or {}).get("Homepage", ""),
                                        "Google Scholar": (getattr(candidate, "profiles", {}) or {}).get("Google Scholar", ""),
                                        "GitHub": (getattr(candidate, "profiles", {}) or {}).get("GitHub", ""),
                                        "LinkedIn": (getattr(candidate, "profiles", {}) or {}).get("LinkedIn", ""),
                                    }
                                )
                            else:
                                df_data.append(
                                    {
                                        "Name": candidate.get("Name", ""),
                                        "Current Role & Affiliation": candidate.get(
                                            "Current Role & Affiliation", ""
                                        ),
                                        "Research Focus": ", ".join(
                                            candidate.get("Research Focus", [])
                                        ),
                                        "Homepage": candidate.get("Profiles", {}).get(
                                            "Homepage", ""
                                        ),
                                        "Google Scholar": candidate.get("Profiles", {}).get(
                                            "Google Scholar", ""
                                        ),
                                        "GitHub": candidate.get("Profiles", {}).get(
                                            "GitHub", ""
                                        ),
                                        "LinkedIn": candidate.get("Profiles", {}).get(
                                            "LinkedIn", ""
                                        ),
                                    }
                                )

                        df = pd.DataFrame(df_data)
                        csv = df.to_csv(index=False)
                        st.download_button(
                            label="💾 Download CSV",
                            data=csv,
                            file_name="msra_targeted_search_results.csv",
                            mime="text/csv",
                            use_container_width=True,
                        )

                with col2_2:
                    if st.button(
                        "📋 Export as JSON", type="secondary", use_container_width=True
                    ):
                        json_data = json.dumps(results, indent=2, ensure_ascii=False)
                        st.download_button(
                            label="💾 Download JSON",
                            data=json_data,
                            file_name="msra_targeted_search_results.json",
                            mime="application/json",
                            use_container_width=True,
                        )


        else:
            # Empty state - show when no results yet
            st.info(
                "After confirming the search parameters, click '✅ Looks Good! Start Search' to start the search", icon="ℹ️"
            )


def apply_targeted_search_styles():
    """Apply custom CSS for targeted search page"""
    st.markdown(
        """
    <style>
    /* Enhanced button styling for targeted search */
    .stButton > button {
        border-radius: 12px !important;
        font-weight: 600 !important;
        transition: all 0.3s ease !important;
        border: none !important;
        box-shadow: 0 4px 15px rgba(0,0,0,0.1) !important;
    }
    
    .stButton > button:hover {
        transform: translateY(-2px) !important;
        box-shadow: 0 8px 25px rgba(0,0,0,0.2) !important;
    }
    
    /* Primary button with gradient */
    .stButton > button[data-testid="baseButton-primary"] {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%) !important;
        color: white !important;
    }
    
    /* Secondary button styling */
    .stButton > button[data-testid="baseButton-secondary"] {
        background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%) !important;
        color: white !important;
    }
    
    /* Progress bar styling */
    .stProgress > div > div > div {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%) !important;
    }
    
    /* Text area styling */
    .stTextArea > div > div > textarea {
        border-radius: 10px !important;
        border: 2px solid #e1e5e9 !important;
        transition: all 0.3s ease !important;
    }
    
    .stTextArea > div > div > textarea:focus {
        border-color: #667eea !important;
        box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1) !important;
    }
    
    /* Multiselect styling */
    .stMultiSelect > div > div > div {
        border-radius: 10px !important;
        border: 2px solid #e1e5e9 !important;
    }
    
    /* Slider styling */
    .stSlider > div > div > div > div {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%) !important;
    }
    
    /* Slider track styling */
    .stSlider > div > div > div {
        background: #e1e5e9 !important;
        border-radius: 10px !important;
    }
    
    /* Slider thumb styling */
    .stSlider > div > div > div > div {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%) !important;
        border: 2px solid white !important;
        box-shadow: 0 2px 8px rgba(0,0,0,0.3) !important;
    }
    
    /* Slider tick bar min/max labels styling for both themes */
    [data-testid="stSliderTickBarMin"], [data-testid="stSliderTickBarMax"] {
        background: rgba(255, 255, 255, 0.9) !important;
        color: #1e293b !important;
        padding: 4px 8px !important;
        border-radius: 6px !important;
        font-weight: 600 !important;
        font-size: 0.875rem !important;
        border: 1px solid rgba(0, 0, 0, 0.1) !important;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1) !important;
        backdrop-filter: blur(10px) !important;
    }
    
    /* Dark theme specific styling for slider labels */
    [data-testid="stSliderTickBarMin"], [data-testid="stSliderTickBarMax"] {
        background: rgba(255, 255, 255, 0.95) !important;
        color: #0f172a !important;
        border: 1px solid rgba(255, 255, 255, 0.2) !important;
        text-shadow: 0 1px 2px rgba(0, 0, 0, 0.1) !important;
    }
    
    /* Light theme specific styling for slider labels */
    [data-testid="stSliderTickBarMin"], [data-testid="stSliderTickBarMax"] {
        background: rgba(255, 255, 255, 0.95) !important;
        color: #1e293b !important;
        border: 1px solid rgba(0, 0, 0, 0.1) !important;
        text-shadow: 0 1px 2px rgba(255, 255, 255, 0.8) !important;
    }
    </style>
    """,
        unsafe_allow_html=True,
    )
