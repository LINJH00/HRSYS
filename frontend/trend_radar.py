import streamlit as st
import json
import pandas as pd
import time
from string import Template
import base64
from pathlib import Path
# ---------- NEW: LLM detail generator helper ----------
import os, textwrap
import re
import threading
import queue

# 新增：引入爬取数据封装模块
try:
    from backend import trend_data  # type: ignore
    from backend.report_storage import save_trend_radar_report, load_trend_radar_reports, delete_report, get_storage_stats
    storage_available = True
except ImportError:
    trend_data = None  # Fallback if backend not present
    storage_available = False

# Import MSRA talent classification function
try:
    from frontend.trend_talent_profile import render_talent_tab_with_msra_classification
except ImportError:
    def render_talent_tab_with_msra_classification(talent_groups):
        st.error("MSRA talent classification not available")

# ==================== 进度弹窗样式和渲染函数 ====================

def _inject_report_progress_styles(theme: str):
    """注入报告生成进度弹窗的CSS样式（复用Targeted Search样式）"""
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
    
    .report-overlay {{
        position: fixed;
        inset: 0;
        background: rgba(0,0,0,.55);
        z-index: 9999;
        display: flex;
        align-items: center;
        justify-content: center;
    }}
    
    .report-modal {{
        width: 560px;
        max-width: 92vw;
        background: {modal_bg};
        color: {text_color};
        border-radius: 14px;
        border: 1px solid {modal_border};
        box-shadow: 0 20px 80px rgba(0,0,0,.35);
    }}
    
    .report-modal-header {{
        padding: 18px 20px;
        border-bottom: 1px solid {modal_border};
        display: flex;
        align-items: center;
        justify-content: space-between;
    }}
    
    .report-modal-title {{
        font-size: 22px;
        font-weight: 800;
    }}
    
    .report-steps {{
        max-height: 360px;
        overflow-y: auto;
        padding: 8px 20px 18px;
    }}
    
    .report-step {{
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 10px 0;
        font-size: 14px;
        border-bottom: 1px dashed rgba(255,255,255,.06);
        transition: all 0.3s ease;
    }}
    
    .report-step:last-child {{
        border-bottom: none;
    }}
    
    .report-dot {{
        width: 10px;
        height: 10px;
        border-radius: 999px;
        background: {dot_default};
        transition: all 0.3s ease;
    }}
    
    .report-step.done .report-dot {{
        background: {dot_done};
    }}
    
    .report-step.active .report-dot {{
        background: {dot_active};
        animation: pulse 1.5s ease-in-out infinite;
    }}
    
    @keyframes pulse {{
        0%, 100% {{
            opacity: 1;
            transform: scale(1);
        }}
        50% {{
            opacity: 0.7;
            transform: scale(1.2);
        }}
    }}
    </style>
    """, unsafe_allow_html=True)

def _render_report_progress_overlay(steps: list, active_idx: int) -> str:
    """生成报告进度弹窗的HTML"""
    items = []
    
    for i, txt in enumerate(steps):
        if i < active_idx:
            state = "done"
        elif i == active_idx:
            state = "active"
        else:
            state = ""
        
        items.append(
            f'<div class="report-step {state}">'  
            f'  <div class="report-dot"></div>'   
            f'  <div>{txt}</div>'                 
            f'</div>'
        )
    
    return (
        '<div class="report-overlay">'          
        '  <div class="report-modal">'          
        '    <div class="report-modal-header">' 
        '      <div class="report-modal-title">📊 Generating Trend Report</div>'
        '    </div>'
        f'    <div class="report-steps">{"".join(items)}</div>'  
        '  </div>'
        '</div>'
    )

# Image utility functions for embedding images in markdown
def img_to_bytes(img_path):
    """Convert image file to base64 encoded bytes"""
    try:
        img_bytes = Path(img_path).read_bytes()
        encoded = base64.b64encode(img_bytes).decode()
        return encoded
    except Exception as e:
        print(f"Error loading image {img_path}: {e}")
        return None

def img_to_html(img_path, alt_text="", width="100%"):
    """Convert image to HTML with base64 encoding"""
    img_bytes = img_to_bytes(img_path)
    if img_bytes:
        img_html = f"<img src='data:image/png;base64,{img_bytes}' alt='{alt_text}' style='width: {width}; max-width: 100%; height: auto;' class='img-fluid'>"
        return img_html
    else:
        return f"<div style='color: red; padding: 10px; border: 1px solid red; border-radius: 5px;'>Image not found: {img_path}</div>"

# Default groups data
DEFAULT_GROUPS = {
    "domestic": {
        "name": "Domestic",
        "sources": [
            {"name": "机器之心", "url": "https://www.jiqizhixin.com/", "type": "news", "description": "AI Technology Media"},
            {"name": "新智源", "url": "https://link.baai.ac.cn/@AI_era", "type": "news", "description": "AI Era News"},
            {"name": "量子位", "url": "https://www.qbitai.com/", "type": "news", "description": "AI Technology News"}
        ],
        "description": "Chinese AI news and media platforms",
        "color": "#667eea"
    },
    "international": {
        "name": "International",
        "sources": [
            {"name": "Synced Review", "url": "https://syncedreview.com/", "type": "news", "description": "AI Technology & Industry Review"},
            {"name": "Huggingface Trending Papers", "url": "https://huggingface.co/papers/trending", "type": "research", "description": "Trending ML papers on Hugging Face"},
            {"name": "Huggingface Blog", "url": "https://huggingface.co/blog", "type": "blog", "description": "Hugging Face blog and updates"},
            {"name": "TechCrunch AI", "url": "https://techcrunch.com/category/artificial-intelligence/", "type": "news", "description": "TechCrunch AI coverage"}
        ],
        "description": "International AI news, research, and technology media platforms",
        "color": "#4facfe"
    }
}

def apply_trend_radar_styles():
    """Apply custom CSS for trend radar page"""
    st.markdown("""
    <style>
    /* Enhanced button styling for trend radar */
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
    
    /* Selectbox styling */
    .stSelectbox > div > div > div {
        border-radius: 10px !important;
        border: 2px solid #e1e5e9 !important;
    }
    
    /* Metric styling */
    .metric-container {
        background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
        color: white;
        padding: 1rem;
        border-radius: 12px;
        text-align: center;
        margin: 0.5rem;
        box-shadow: 0 4px 15px rgba(0,0,0,0.1);
        transition: all 0.3s ease;
    }
    
    .metric-container:hover {
        transform: translateY(-2px);
        box-shadow: 0 8px 25px rgba(0,0,0,0.2);
    }
    
    /* Ensure HTML content renders properly */
    .stMarkdown {
        overflow: visible !important;
    }
    
    /* Custom report card styling */
    .trend-report-card {
        background: linear-gradient(135deg, #667eea15 0%, #764ba205 100%);
        border: 2px solid #667eea;
        border-radius: 15px;
        padding: 1rem;
        margin: 1rem 0;
        box-shadow: 0 4px 15px rgba(0,0,0,0.1);
        transition: all 0.3s ease;
    }
    
    .trend-report-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 8px 25px rgba(0,0,0,0.2);
    }
    
    /* Tag styling for report cards */
    .tag-purple {
        background: #667eea !important;
        color: white !important;
        padding: 0.3rem 0.8rem !important;
        border-radius: 20px !important;
        font-size: 0.8rem !important;
        font-weight: bold !important;
        text-align: center !important;
        display: inline-block !important;
        margin: 0.2rem !important;
    }
    
    .tag-blue {
        background: #4facfe !important;
        color: white !important;
        padding: 0.3rem 0.8rem !important;
        border-radius: 20px !important;
        font-size: 0.8rem !important;
        font-weight: 500 !important;
        text-align: center !important;
        display: inline-block !important;
        margin: 0.2rem !important;
    }
    
    .tag-cyan {
        background: #00f2fe !important;
        color: white !important;
        padding: 0.3rem 0.8rem !important;
        border-radius: 20px !important;
        font-size: 0.8rem !important;
        font-weight: 500 !important;
        text-align: center !important;
        display: inline-block !important;
        margin: 0.2rem !important;
    }
    </style>
    """, unsafe_allow_html=True)


def load_groups():
    if "trend_groups" not in st.session_state:
        st.session_state.trend_groups = DEFAULT_GROUPS.copy()
    return st.session_state.trend_groups

def save_groups(groups):
    st.session_state.trend_groups = groups

def render_trend_groups_page():
    """Render the main trend groups page"""
    
    # Action buttons row
    col_actions1, col_actions2 = st.columns(2)

    with col_actions1:
        if st.button("➕ Create New Group", key="create_new_trend_group", type="primary", use_container_width=True):
            st.session_state.current_page = "edit_trend_group"
            st.session_state.editing_group = None
            # Force clear any cached state and rerun
            st.session_state.page_changed = True
            st.rerun()

    with col_actions2:
        if st.button("📋 View Existing Reports", key="view_trend_reports", type="primary", use_container_width=True):
            st.session_state.current_page = "📋 Trend Report"
            # Force clear any cached state and rerun
            st.session_state.page_changed = True
            st.rerun()
    

    st.markdown("---")

    # Load and display groups
    groups = load_groups()
    
    # Groups grid layout
    st.markdown("### 🎯 Trend Groups")
    
    # Create a responsive grid layout
    group_ids = list(groups.keys())
    num_groups = len(group_ids)
    
    # Calculate optimal grid layout
    if num_groups <= 3:
        cols = st.columns(num_groups)
    elif num_groups <= 6:
        cols = st.columns(3)
    else:
        cols = st.columns(4)
    
    for i, group_id in enumerate(group_ids):
        group_data = groups[group_id]
        col_idx = i % len(cols)
        
        with cols[col_idx]:
            # Group card
            st.markdown(f"""
            <div style="
                background: linear-gradient(135deg, {group_data['color']}15 0%, {group_data['color']}05 100%);
                border: 2px solid {group_data['color']};
                border-radius: 15px;
                padding: 1.5rem;
                margin: 1rem 0;
                transition: all 0.3s ease;
                box-shadow: 0 4px 15px rgba(0,0,0,0.1);
            ">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem;">
                    <h3 style="margin: 0; color: {group_data['color']}; font-size: 1.3rem;">{group_data['name']}</h3>
                    <div style="
                        background: {group_data['color']};
                        color: white;
                        padding: 0.3rem 0.8rem;
                        border-radius: 20px;
                        font-size: 0.8rem;
                        font-weight: bold;
                    ">
                        {len(group_data['sources'])} sources
                    </div>
                </div>
                <p style="margin: 0 0 1rem 0; color: #666; font-size: 0.9rem;">{group_data['description']}</p>
                <div style="display: flex; flex-wrap: wrap; gap: 0.5rem; margin-bottom: 1rem;">
            """, unsafe_allow_html=True)
            
            # Show first 3 sources as preview
            for source in group_data['sources'][:3]:
                st.markdown(f"""
                <div style="
                    background: {group_data['color']}20;
                    border: 1px solid {group_data['color']}40;
                    padding: 0.3rem 0.6rem;
                    border-radius: 12px;
                    font-size: 0.8rem;
                    color: {group_data['color']};
                ">
                    {source['name']}
                </div>
                """, unsafe_allow_html=True)
            
            if len(group_data['sources']) > 3:
                st.markdown(f"""
                <div style="
                    background: {group_data['color']}20;
                    border: 1px solid {group_data['color']}40;
                    padding: 0.3rem 0.6rem;
                    border-radius: 12px;
                    font-size: 0.8rem;
                    color: {group_data['color']};
                ">
                    +{len(group_data['sources']) - 3} more
                </div>
                """, unsafe_allow_html=True)
            
            st.markdown("</div></div>", unsafe_allow_html=True)
            
            # Action buttons for each group
            col_btn_view, col_btn_edit, col_btn_report = st.columns(3)

            # 查看详情
            with col_btn_view:
                if st.button("👁️ View", key=f"view_group_{group_id}", use_container_width=True):
                    st.session_state.selected_group = group_id
                    st.session_state.current_page = "view_single_trend_group"
                    st.session_state.page_changed = True
                    st.rerun()

            # 编辑
            with col_btn_edit:
                if st.button("✏️ Edit", key=f"edit_{group_id}", use_container_width=True):
                    st.session_state.current_page = "edit_trend_group"
                    st.session_state.editing_group = group_id
                    st.rerun()

            # 生成报告
            with col_btn_report:
                if st.button("📊 Generate Report", key=f"report_{group_id}", use_container_width=True):
                    st.session_state.current_page = "generate_trend_report"
                    st.session_state.selected_group = group_id
                    # Force clear any cached state and rerun
                    st.session_state.page_changed = True
                    st.rerun()

def render_edit_trend_group_page():
    """Render the edit trend group page"""

    # Back button
    if st.button("← Back to Groups", key="back_to_groups_edit", type="secondary"):
        st.session_state.current_page = "trend_groups"
        st.session_state.page_changed = True
        st.rerun()

    # Page header
    is_edit = st.session_state.get('editing_group') is not None
    if is_edit:
        st.markdown("### ✏️ Edit Trend Group")
    else:
        st.markdown("### ➕ Create New Trend Group")
    
    # Load groups
    groups = load_groups()
    editing_group_id = st.session_state.get('editing_group')
    
    if editing_group_id and editing_group_id in groups:
        group_data = groups[editing_group_id]
    else:
        group_data = {
            'name': '',
            'description': '',
            'color': '#667eea',
            'sources': []
        }
    
    # Group basic info
    st.markdown("#### 📝 Group Information")
    
    col_info1, col_info2 = st.columns(2)
    with col_info1:
        group_name = st.text_input("Group Name", value=group_data.get('name', ''), key="edit_group_name")
    with col_info2:
        available_colors = ["#667eea", "#764ba2", "#4facfe", "#00f2fe", "#f093fb", "#f5576c"]
        selected_color = st.selectbox("Group Color", available_colors, 
                                    index=available_colors.index(group_data.get('color', '#667eea')) if group_data.get('color') in available_colors else 0, 
                                    key="edit_group_color")
    
    group_description = st.text_area("Description", value=group_data.get('description', ''), 
                                    height=100, key="edit_group_description")
    
    # Sources management
    st.markdown("#### 🔗 Group Sources")
    
    if "temp_sources" not in st.session_state:
        st.session_state.temp_sources = group_data.get('sources', []).copy()
    
    # Display existing sources
    if st.session_state.temp_sources:
        # Add headers for source input fields
        col_header1, col_header2, col_header3, col_header4, col_header5 = st.columns([2, 2.5, 2, 3, 1])
        with col_header1:
            st.markdown("**🔗 Name**")
        with col_header2:
            st.markdown("**🌐 URL**")
        with col_header3:
            st.markdown("**📊 Type**")
        with col_header4:
            st.markdown("**📝 Description**")
        with col_header5:
            st.markdown("**Action**")

        st.markdown("---")

    for i, source in enumerate(st.session_state.temp_sources):
        st.markdown(f"**Source {i+1}:**")
        col_source1, col_source2, col_source3, col_source4, col_source5 = st.columns([2, 2.5, 2, 3, 1])

        with col_source1:
            source_name = st.text_input("Name", value=source.get('name', ''),
                                      key=f"source_name_{i}", label_visibility="collapsed",
                                      placeholder="e.g., 量子位")
        with col_source2:
            source_url = st.text_input("URL", value=source.get('url', ''),
                                     key=f"source_url_{i}", label_visibility="collapsed",
                                     placeholder="https://example.com")
        with col_source3:
            source_type = st.selectbox("Type", ["news", "platform", "institute", "social", "other"], 
                                     index=["news", "platform", "institute", "social", "other"].index(source.get('type', 'news')) if source.get('type') in ["news", "platform", "institute", "social", "other"] else 0,
                                     key=f"source_type_{i}", label_visibility="collapsed")
        with col_source4:
            source_description = st.text_area("Description", value=source.get('description', ''),
                                             key=f"source_description_{i}", label_visibility="collapsed",
                                             placeholder="e.g., Leading AI news platform in Chinese\nFocused on cutting-edge AI research and industry insights\nRegular coverage of top conferences and breakthroughs",
                                             height=60)
        with col_source5:
            if st.button("🗑️", key=f"remove_source_{i}", help="Remove source"):
                st.session_state.temp_sources.pop(i)
                st.rerun()

        # Update source data
        st.session_state.temp_sources[i] = {
            'name': source_name,
            'url': source_url,
            'type': source_type,
            'description': source_description
        }
    
    # Add new source
    if st.button("➕ Add Source", key="add_source"):
        st.session_state.temp_sources.append({
            'name': '',
            'url': '',
            'type': 'news',
            'description': ''
        })
        st.rerun()
    
    st.markdown("---")
    
    # Action buttons
    col_actions1, col_actions2, col_actions3 = st.columns([1, 1, 1])
    
    with col_actions1:
        if st.button("💾 Save", key="save_group", type="primary", use_container_width=True):
            # Validate input
            if not group_name.strip():
                st.error("Group name is required!")
                return

            if not st.session_state.temp_sources:
                st.error("Group must have at least one source!")
                return

            # Create/update group
            groups = load_groups()
            if editing_group_id:
                groups[editing_group_id] = {
                    'name': group_name.strip(),
                    'description': group_description.strip(),
                    'color': selected_color,
                    'sources': [s for s in st.session_state.temp_sources if s['name'].strip() and s['url'].strip()]
                }
            else:
                # Generate new ID
                new_id = f"trend_group_{len(groups) + 1}"
                groups[new_id] = {
                    'name': group_name.strip(),
                    'description': group_description.strip(),
                    'color': selected_color,
                    'sources': [s for s in st.session_state.temp_sources if s['name'].strip() and s['url'].strip()]
                }

            save_groups(groups)
            st.session_state.temp_sources = []
            st.session_state.current_page = "trend_groups"
            st.session_state.page_changed = True
            st.rerun()

    with col_actions2:
        if st.button("❌ Cancel", key="cancel_edit", type="secondary", use_container_width=True):
            st.session_state.temp_sources = []
            st.session_state.current_page = "trend_groups"
            st.session_state.page_changed = True
            st.rerun()
    
    with col_actions3:
        if editing_group_id:
            # Delete group functionality with proper state management
            delete_confirm_key = f"delete_confirm_{editing_group_id}"

            # Initialize delete confirmation state if not exists
            if delete_confirm_key not in st.session_state:
                st.session_state[delete_confirm_key] = False

            # Show delete button first
            if st.button("🗑️ Delete Group", key=f"delete_group_{editing_group_id}", type="secondary", use_container_width=True):
                # Toggle the confirmation state
                st.session_state[delete_confirm_key] = True
                st.rerun()

            # Show confirmation checkbox and final delete button only after initial click
            if st.session_state[delete_confirm_key]:
                st.markdown("---")
                st.markdown("⚠️ **Confirm Group Deletion**")
                st.markdown("*This action cannot be undone.*")

                confirm_delete = st.checkbox("I confirm I want to delete this group", key=f"confirm_checkbox_{editing_group_id}")

                col_confirm1, col_confirm2 = st.columns(2)
                with col_confirm1:
                    if st.button("✅ Yes, Delete Group", type="primary", use_container_width=True):
                        if confirm_delete:
                            try:
                                groups = load_groups()
                                group_name = groups[editing_group_id].get('name', 'Unknown')

                                # Delete the group
                                del groups[editing_group_id]
                                save_groups(groups)

                                # Clear all related state
                                st.session_state.temp_sources = []
                                if "editing_group" in st.session_state:
                                    del st.session_state.editing_group
                                st.session_state.current_page = "trend_groups"
                                st.session_state.page_changed = True

                                # Clear delete confirmation states
                                st.session_state[delete_confirm_key] = False
                                confirm_checkbox_key = f"confirm_checkbox_{editing_group_id}"
                                if confirm_checkbox_key in st.session_state:
                                    del st.session_state[confirm_checkbox_key]

                                st.success(f"Group '{group_name}' deleted successfully!")
                                st.rerun()
                            except KeyError:
                                st.error("Group not found. It may have already been deleted.")
                                st.session_state[delete_confirm_key] = False
                            except Exception as e:
                                st.error(f"Error deleting group: {str(e)}")
                                st.session_state[delete_confirm_key] = False
                        else:
                            st.warning("Please check the confirmation box to proceed with deletion.")

                with col_confirm2:
                    if st.button("❌ Cancel", key="cancel_delete", type="secondary", use_container_width=True):
                        # Reset confirmation state
                        st.session_state[delete_confirm_key] = False
                        st.rerun()

def render_generate_trend_report_page():
    """Render the generate trend report page"""

    # Back button
    if st.button("← Back to Groups", key="back_to_groups_generate", type="secondary"):
        st.session_state.current_page = "trend_groups"
        st.session_state.page_changed = True
        st.rerun()



    # Load groups
    groups = load_groups()

    if not groups:
        st.warning("No trend groups available. Please create a group first.")
        if st.button("Create Group", key="create_group_fallback"):
            st.session_state.current_page = "edit_trend_group"
            st.session_state.page_changed = True
            st.rerun()
        return

    # Check if we have a pre-selected group from the group card
    selected_group = st.session_state.get("selected_group")

    if selected_group:
        selected_group_data = groups[selected_group]
        
        # Display selected group info
        st.markdown(f"""
        <div style="
            background: linear-gradient(135deg, {selected_group_data['color']}15 0%, {selected_group_data['color']}05 100%);
            border: 2px solid {selected_group_data['color']};
            border-radius: 15px;
            padding: 1.5rem;
            margin: 1rem 0;
        ">
            <h4 style="margin: 0 0 1rem 0; color: {selected_group_data['color']};">{selected_group_data['name']}</h4>
            <p style="margin: 0 0 1rem 0;">{selected_group_data['description']}</p>
            <p style="margin: 0;"><strong>Sources:</strong> {', '.join([s['name'] for s in selected_group_data['sources']])}</p>
        </div>
        """, unsafe_allow_html=True)
        
        # Report configuration with enhanced styling
        st.markdown("#### ⚙️ Report Configuration")

        # Configuration cards - smaller and more compact (only time range)
        config_col1 = st.container()

        with config_col1:
            st.markdown('<h5 style="margin: 0; font-size: 1.2rem;">⏰ Time Range</h5>', unsafe_allow_html=True)

            time_range = st.selectbox(
                "Select time period:",
                ["Last 7 days", "Last 30 days", "Last 90 days", "Last 6 months", "Last year"],
                key="time_range_select",
                help="Choose the time period for trend monitoring"
            )

            # Default report type now fixed since UI removed
            report_type = "Full trend analysis"

            st.markdown("</div>", unsafe_allow_html=True)


        # Optional query input
        st.markdown("---")
        st.markdown("#### 🔍 Optional Query (Advanced)")
        
        custom_query = st.text_area(
            "Custom analysis query (optional):",
            placeholder="e.g., Focus on AI safety topics, exclude marketing content, prioritize technical discussions",
            height=100,
            help="Provide specific instructions for trend analysis (optional)"
        )

        
        # Additional options
        st.markdown("---")
        st.markdown("### 🚀 Generation Options")


        # Preview section
        with st.expander("👀 Preview Configuration", expanded=False):
            st.markdown("**Report Summary:**")
            st.info(f"""
            **Group:** {selected_group_data['name']}
            **Sources:** {len(selected_group_data['sources'])}
            **Time Range:** {time_range}
            **Custom Query:** {'Yes' if custom_query.strip() else 'No'}
            """)

        # Generate report button with enhanced styling
        st.markdown("---")
        if st.button("🚀 Generate Trend Report", key="generate_trend_report", type="primary", use_container_width=True):
            # Check if API key is available (support both new and old session variables)
            api_key_available = (st.session_state.get("llm_api_key", "") or 
                                st.session_state.get("openai_api_key", ""))
            if not api_key_available:
                st.error("⚠️ **API Key Required**")
                st.info("Please enter your API key in the sidebar settings (🛠️ LLM Configuration) to generate trend reports.")
                st.stop()
            
            # 🕒 Check for recent reports (within 7 days) before generating new one
            if storage_available:
                try:
                    # Determine report type (domestic or international) - more flexible logic
                    if selected_group == "international" or "international" in selected_group.lower():
                        report_type = "international"
                    else:
                        report_type = "domestic"
                    
                    # Load recent reports for this type
                    recent_reports = load_trend_radar_reports(report_type)
                    
                    # Filter reports by specific group (more precise than just domestic/international)
                    group_specific_reports = []
                    for report in recent_reports:
                        # 处理不同的数据结构
                        if 'data' in report:
                            report_group_id = report['data'].get('group_id', '')
                            report_title = report.get('title', '')
                        else:
                            report_group_id = report.get('group_id', '')
                            report_title = report.get('title', '')
                        
                        # Check multiple matching criteria
                        if (report_group_id == selected_group or 
                            selected_group in report_title or
                            report_title.replace('_', ' ').lower() in selected_group_data['name'].lower()):
                            group_specific_reports.append(report)
                    
                    # Check if there's a report within the last 7 days
                    from datetime import datetime, timedelta
                    seven_days_ago = datetime.now() - timedelta(days=7)
                    
                    recent_report = None
                    for report in group_specific_reports:
                        try:
                            # Parse the creation time - support both timestamp and ISO formats
                            report_time_value = report.get('created_at', '')
                            report_time = None
                            
                            if isinstance(report_time_value, (int, float)):
                                # Unix timestamp format
                                report_time = datetime.fromtimestamp(report_time_value)
                            elif isinstance(report_time_value, str) and report_time_value:
                                # ISO string format
                                report_time = datetime.fromisoformat(report_time_value.replace('Z', '+00:00'))
                                report_time = report_time.replace(tzinfo=None)  # Remove timezone for comparison
                            
                            if report_time and report_time > seven_days_ago:
                                recent_report = report
                                print(f"[trend_radar] ✅ Found recent report from {report_time.strftime('%Y-%m-%d %H:%M:%S')}")
                                break
                                
                        except Exception as e:
                            print(f"[trend_radar] ⚠️ Failed to parse timestamp for report: {e}")
                            continue  # Skip invalid timestamps
                    
                    # If recent report found, automatically use it (same as Achievement Report)
                    if recent_report:
                        # Format report date - support both timestamp and ISO formats
                        report_time_value = recent_report.get('created_at', '')
                        if isinstance(report_time_value, (int, float)):
                            # Unix timestamp format
                            report_date = datetime.fromtimestamp(report_time_value).strftime('%Y-%m-%d %H:%M')
                        elif isinstance(report_time_value, str) and report_time_value:
                            # ISO string format
                            report_time = datetime.fromisoformat(report_time_value.replace('Z', '+00:00'))
                            report_date = report_time.strftime('%Y-%m-%d %H:%M')
                        else:
                            report_date = "Unknown Date"
                        
                        st.success(f"📅 **Using Existing Report** - {report_date} (within 7 days)")
                        # Automatically navigate to existing report
                        # 处理不同的数据结构：有些报告数据在'data'子字段，有些直接在顶层
                        if 'data' in recent_report and 'sources' in recent_report['data']:
                            st.session_state.current_view_trend_report = recent_report['data']
                        else:
                            st.session_state.current_view_trend_report = recent_report
                        st.session_state.current_page = "view_single_trend_report"
                        st.session_state.page_changed = True
                        st.rerun()
                        
                except Exception as e:
                    # If checking fails, continue with normal generation
                    st.warning(f"⚠️ 无法检查最近报告: {e}")
                    pass
            
            try:
                # 获取主题
                try:
                    current_theme = st.context.theme.type if hasattr(st.context, 'theme') else "light"
                except:
                    current_theme = "light"
                
                # 注入进度弹窗样式
                _inject_report_progress_styles(current_theme)
                
                # 定义报告生成步骤
                report_steps = [
                    "Fetching latest articles",
                    "Analyzing trends and directions",
                    "Searching for talents",
                    "Generating detailed reports",
                    "Finalizing report"
                ]
                
                # 创建overlay占位符和进度条
                overlay = st.empty()
                prog = st.progress(0)
                
                # 事件到步骤的映射
                event_to_step = {
                    "fetching": 0,
                    "parsing": 1,
                    "searching": 2,
                    "analyzing": 2,
                    "finalizing": 3,
                    "done": 4
                }
                
                # 创建队列用于进度通信
                progress_q = queue.Queue()
                result_holder = {}
                
                def on_progress(stage, progress, message):
                    """进度回调：将进度放入队列
                    stage: 阶段编号 (0-4)
                    progress: 进度百分比 (0.0-1.0)
                    message: 进度消息
                    """
                    # 将stage转换为event名称
                    stage_to_event = {
                        0: "fetching",
                        1: "parsing",
                        2: "searching",
                        3: "finalizing",
                        4: "done"
                    }
                    event = stage_to_event.get(stage, "parsing")
                    progress_q.put((event, progress))
                
                def run_report_generation_in_background(days, clean_query, api_key, selected_group):
                    """后台线程：运行报告生成"""
                    try:
                        from backend import trend_report as tr
                        
                        print(f"[trend_radar] API Key status: {'Available' if api_key else 'Missing'}")
                        print(f"[trend_radar] Fetching data snapshot for report generation...")
                        on_progress(0, 0.15, "Fetching latest articles...")
                        
                        # 根据选择的group决定数据源类型并爬取数据
                        if selected_group == "international":
                            print(f"[trend_radar] Using international data sources")
                            data_snapshot = trend_data.query_recent_articles(days=days, include_international=False, international_only=True)
                            three_stage_result = tr.generate_three_stage_report(
                                days=days, 
                                query=clean_query, 
                                progress_callback=on_progress,
                                api_key=api_key,
                                include_international=False,
                                international_only=True,
                                data_snapshot=data_snapshot
                            )
                        elif selected_group == "domestic":
                            print(f"[trend_radar] Using domestic data sources")
                            data_snapshot = trend_data.query_recent_articles(days=days, include_international=False, international_only=False)
                            three_stage_result = tr.generate_three_stage_report(
                                days=days, 
                                query=clean_query, 
                                progress_callback=on_progress,
                                api_key=api_key,
                                include_international=False,
                                international_only=False,
                                data_snapshot=data_snapshot
                            )
                        else:
                            print(f"[trend_radar] Using all data sources")
                            data_snapshot = trend_data.query_recent_articles(days=days, include_international=True, international_only=False)
                            three_stage_result = tr.generate_three_stage_report(
                                days=days, 
                                query=clean_query, 
                                progress_callback=on_progress,
                                api_key=api_key,
                                include_international=True,
                                international_only=False,
                                data_snapshot=data_snapshot
                            )
                        
                        # 存储结果
                        result_holder["result"] = three_stage_result
                        result_holder["data_snapshot"] = data_snapshot
                        on_progress(4, 1.0, "Report generation complete")
                        
                    except Exception as e:
                        print(f"[trend_radar] Error in background thread: {e}")
                        result_holder["error"] = e
                        on_progress(4, 1.0, "Error occurred")
                
                # 根据时间范围转为天数
                time_range_mapping = {
                    "Last 7 days": 7,
                    "Last 30 days": 30,
                    "Last 90 days": 90,
                    "Last 6 months": 180,
                    "Last year": 365,
                }
                days = time_range_mapping.get(time_range, 30)
                
                # 清理 custom_query
                clean_query = custom_query
                if custom_query:
                    clean_query = (custom_query
                                 .replace('←', '<-')
                                 .replace('→', '->')
                                 .replace('↑', '^')
                                 .replace('↓', 'v')
                                 .replace('✓', 'v')
                                 .replace('✗', 'x')
                                 .replace('★', '*'))
                    clean_query = ''.join(c for c in clean_query if ord(c) < 127 or c.isspace())
                
                # 启动后台线程
                worker = threading.Thread(
                    target=run_report_generation_in_background,
                    daemon=True,
                    args=(days, clean_query, api_key_available, selected_group)
                )
                worker.start()
                
                # 主线程：实时更新UI
                current_step = 0
                last_pct = 0
                
                # 首次显示进度弹窗
                overlay.markdown(
                    _render_report_progress_overlay(report_steps, current_step),
                    unsafe_allow_html=True
                )
                
                # 循环：持续更新UI直到报告生成完成
                while worker.is_alive() or not progress_q.empty():
                    try:
                        # 从队列获取进度更新
                        event, pct = progress_q.get(timeout=0.1)
                        
                        # 更新步骤显示
                        base_event = (event or "").split(":", 1)[0]
                        step_idx = event_to_step.get(base_event, current_step)
                        
                        if step_idx != current_step:
                            current_step = step_idx
                            overlay.markdown(
                                _render_report_progress_overlay(report_steps, current_step),
                                unsafe_allow_html=True
                            )
                        
                        # 更新进度条
                        p = max(0, min(100, int((pct or 0.0) * 100)))
                        if p != last_pct:
                            prog.progress(p)
                            last_pct = p
                    
                    except queue.Empty:
                        pass
                    except Exception as e:
                        print(f"[Progress Update] Error: {e}")
                        pass
                    
                    time.sleep(0.05)
                
                # 等待线程完成并获取结果
                worker.join()
                
                # 清理overlay
                overlay.empty()
                prog.empty()
                
                if "error" in result_holder:
                    st.error(f"报告生成失败: {result_holder['error']}")
                elif "result" not in result_holder:
                    st.error("报告生成失败: 未获取到结果")
                else:
                    three_stage_result = result_holder["result"]
                    data_snapshot = result_holder["data_snapshot"]
                    
                    # 存储详细报告映射
                    if three_stage_result.get("stage3_detailed_reports"):
                        st.session_state["detailed_reports_cache"] = three_stage_result["stage3_detailed_reports"]
                    
                    # 获取报告内容
                    rpt_md = three_stage_result.get("final_report", "")
                    
                    # 生成HTML头部
                    html_header_tpl = Template("""# ${group_name} | Trend Radar Report

<table style="width: 100%; border-collapse: collapse; margin: 1rem 0;">
    <tr>
        <td style="padding: 0.5rem; border: 1px solid #ddd; font-weight: bold; background-color: #f8f9fa;">Group Description</td>
        <td style="padding: 0.5rem; border: 1px solid #ddd;">${group_desc}</td>
    </tr>
    <tr>
        <td style="padding: 0.5rem; border: 1px solid #ddd; font-weight: bold; background-color: #f8f9fa;">Total Sources</td>
        <td style="padding: 0.5rem; border: 1px solid #ddd;">${source_count}</td>
    </tr>
    <tr>
        <td style="padding: 0.5rem; border: 1px solid #ddd; font-weight: bold; background-color: #f8f9fa;">Report Generated</td>
        <td style="padding: 0.5rem; border: 1px solid #ddd;">${ts}</td>
    </tr>
</table>

---

""")
                    
                    html_header = html_header_tpl.substitute(
                        group_name=selected_group_data['name'],
                        group_desc=selected_group_data['description'],
                        source_count=len(selected_group_data['sources']),
                        ts=time.strftime('%Y-%m-%d %H:%M:%S'),
                    )
                    
                    final_rpt = html_header + rpt_md
                    
                    # Store results
                    all_reports = [{
                        'name': selected_group_data['name'],
                        'url': '',
                        'type': 'group',
                        'description': selected_group_data['description'],
                        'report': final_rpt
                    }]
                    
                    report_id = f"{selected_group}_{int(time.time())}"
                    report_type = "domestic" if "domestic" in selected_group.lower() else "international"
                    
                    new_report = {
                        'id': report_id,
                        'group_id': selected_group,
                        'group_name': selected_group_data['name'],
                        'sources': all_reports,
                        'original_sources': selected_group_data['sources'],
                        'report_type': report_type,
                        'time_range': time_range,
                        'custom_query': custom_query,
                        'data_snapshot_info': {
                            'total_articles': sum(len(articles) for articles in data_snapshot.values()),
                            'sources': list(data_snapshot.keys()),
                            'fetched_at': int(time.time()),
                            'days_param': days
                        },
                        'three_stage_result': three_stage_result,
                        'created_at': time.time()
                    }
                    
                    # 在 session state 中保留 data_snapshot
                    new_report_with_snapshot = new_report.copy()
                    new_report_with_snapshot['data_snapshot'] = data_snapshot
                    
                    # Initialize reports storage
                    if "stored_trend_reports" not in st.session_state:
                        st.session_state.stored_trend_reports = {}
                    st.session_state.stored_trend_reports[report_id] = new_report_with_snapshot
                    
                    # 更新 trend_groups
                    if 'trend_groups' not in st.session_state:
                        st.session_state.trend_groups = {}
                    if selected_group not in st.session_state.trend_groups:
                        st.session_state.trend_groups[selected_group] = selected_group_data.copy()
                    st.session_state.trend_groups[selected_group]['three_stage_result'] = three_stage_result
                    
                    # Save to persistent storage
                    if storage_available:
                        try:
                            title = f"{selected_group_data['name']}_{time_range}"
                            saved_path = save_trend_radar_report(new_report, title, report_type)
                            print(f"[trend_radar] Report saved successfully to: {saved_path}")
                            st.success(f"Report saved to: {saved_path}")
                        except Exception as e:
                            print(f"[trend_radar] Failed to save report: {e}")
                            st.warning(f"Report generated but failed to save to disk: {e}")
                    
                    # Set current report and redirect
                    st.session_state.current_view_trend_report = new_report_with_snapshot
                    st.session_state.current_page = "view_single_trend_report"
                    st.session_state.page_changed = True
                    
                    st.success(f"Trend report generated successfully!")
                    time.sleep(1)
                    st.rerun()
            
            except Exception as e:
                st.error(f"Error during trend report generation: {e}")
                import traceback
                traceback.print_exc()


def render_view_trend_reports_page():
    """Render the view trend reports page with persistent storage support"""

    # Back button
    if st.button("← Back to Groups", key="back_to_groups_view", type="secondary"):
        st.session_state.current_page = "trend_groups"
        st.session_state.page_changed = True
        st.rerun()

    # Load reports from both persistent storage
    all_reports = {}
    
    # Load domestic reports
    if storage_available:
        try:
            domestic_reports = load_trend_radar_reports("domestic")
            for report in domestic_reports:
                # 处理不同的数据结构：有些报告有'data'包装，有些没有
                if 'data' in report:
                    # 旧格式：有data包装层
                    report_data = report['data']
                    report_id = report_data.get('id', f"domestic_{report.get('filename', '')}")
                else:
                    # 新格式：直接在顶层
                    report_data = report
                    report_id = report.get('id', f"domestic_{report.get('filename', '')}")
                
                all_reports[report_id] = {
                    **report_data,
                    'is_persistent': True,
                    'filepath': report.get('filepath', ''),
                    'created_at_str': report.get('created_at', ''),
                    'report_category': 'domestic'
                }
        except Exception as e:
            st.warning(f"Failed to load domestic reports: {e}")
    
    # Load international reports  
    if storage_available:
        try:
            international_reports = load_trend_radar_reports("international")
            for report in international_reports:
                # 处理不同的数据结构：有些报告有'data'包装，有些没有
                if 'data' in report:
                    # 旧格式：有data包装层
                    report_data = report['data']
                    report_id = report_data.get('id', f"international_{report.get('filename', '')}")
                else:
                    # 新格式：直接在顶层
                    report_data = report
                    report_id = report.get('id', f"international_{report.get('filename', '')}")
                
                all_reports[report_id] = {
                    **report_data,
                    'is_persistent': True,
                    'filepath': report.get('filepath', ''),
                    'created_at_str': report.get('created_at', ''),
                    'report_category': 'international'
                }
        except Exception as e:
            st.warning(f"Failed to load international reports: {e}")
    
    # Get session stored reports (for backward compatibility)
    session_reports = st.session_state.get("stored_trend_reports", {})
    
    # Add session reports (if not already in persistent storage)
    for report_id, report_data in session_reports.items():
        if report_id not in all_reports:
            all_reports[report_id] = {
                **report_data,
                'is_persistent': False,
                'report_category': 'session'
            }
    
    stored_reports = all_reports

    if not stored_reports:
        st.info("No trend reports available. Generate some reports first using the 'Generate Report' button on group cards.")
        if st.button("Go to Groups", key="goto_groups_view_reports"):
            st.session_state.current_page = "trend_groups"
            st.session_state.page_changed = True
            st.rerun()
        return

    # Statistics and filters
    st.markdown("### 📈 Report Statistics")

    stats_col1, stats_col2, stats_col3, stats_col4 = st.columns(4)

    with stats_col1:
        st.metric("Total Reports", len(stored_reports))

    with stats_col2:
        # Handle nested data structure for group_id in stats
        unique_groups = len(set(
            report.get('group_id') or report.get('data', {}).get('group_id', 'unknown') 
            for report in stored_reports.values()
        ))
        st.metric("Unique Groups", unique_groups)

    with stats_col3:
        # Handle nested data structure for original_sources in stats
        total_sources = sum(
            len(report.get('original_sources') or report.get('data', {}).get('original_sources', []))
            for report in stored_reports.values()
        )
        st.metric("Total Sources", total_sources)

    with stats_col4:
        if stored_reports:
            latest_report = max(stored_reports.values(), key=lambda x: x.get('created_at', 0))
            latest_time = time.strftime('%m/%d', time.localtime(latest_report.get('created_at', time.time())))
            st.metric("Latest Report", latest_time)
        else:
            st.metric("Latest Report", "N/A")

    # Search and filter options
    st.markdown("---")
    st.markdown("### 🔍 Search & Filter")

    filter_col1, filter_col2 = st.columns(2)

    with filter_col1:
        search_term = st.text_input(
            "Search reports:",
            placeholder="Enter group name...",
            key="trend_report_search",
            help="Search for reports by group name"
        )

    with filter_col2:
        sort_options = ["Newest first", "Oldest first", "Group name A-Z", "Group name Z-A"]
        sort_by = st.selectbox("Sort by:", sort_options, key="trend_report_sort")

    # Apply search and sorting
    filtered_reports = stored_reports.values()

    if search_term:
        # Handle nested data structure for group_name in search
        filtered_reports = [
            report for report in filtered_reports
            if search_term.lower() in (
                report.get('group_name') or 
                report.get('data', {}).get('group_name', '')
            ).lower()
        ]

    # Apply sorting
    if sort_by == "Newest first":
        sorted_reports = sorted(filtered_reports, key=lambda x: x.get('created_at', 0), reverse=True)
    elif sort_by == "Oldest first":
        sorted_reports = sorted(filtered_reports, key=lambda x: x.get('created_at', 0))
    elif sort_by == "Group name A-Z":
        sorted_reports = sorted(filtered_reports, key=lambda x: x['group_name'].lower())
    elif sort_by == "Group name Z-A":
        sorted_reports = sorted(filtered_reports, key=lambda x: x['group_name'].lower(), reverse=True)

    # Display results
    st.markdown("---")
    if search_term or sort_by != "Newest first":
        st.markdown(f"#### 📊 Available Reports ({len(sorted_reports)} found)")
    else:
        st.markdown("#### 📊 Available Reports")

    if not sorted_reports:
        st.info("🔍 No reports match your search criteria. Try adjusting your filters.")

    for report_index, report in enumerate(sorted_reports):
        # Enhanced report card with more information
        created_time = time.localtime(report.get('created_at', time.time()))
        time_ago = time.time() - report.get('created_at', time.time())

        # Calculate time ago
        if time_ago < 3600:  # Less than 1 hour
            time_ago_text = f"{int(time_ago // 60)} minutes ago"
        elif time_ago < 86400:  # Less than 1 day
            time_ago_text = f"{int(time_ago // 3600)} hours ago"
        elif time_ago < 604800:  # Less than 1 week
            time_ago_text = f"{int(time_ago // 86400)} days ago"
        else:
            time_ago_text = time.strftime('%Y-%m-%d', created_time)

        # Get report type icon
        report_type_icons = {
            "Full trend analysis": "📊",
            "Hot topics only": "🔥",
            "Source comparison": "📈",
            "Trend timeline": "⏰"
        }
        # Handle nested data structure: report_type could be in data sub-dict
        report_type = report.get('report_type') or report.get('data', {}).get('report_type', 'Full trend analysis')
        type_icon = report_type_icons.get(report_type, "📋")

        # # Create a native Streamlit version instead of HTML
        # st.markdown("### 📊 Report Card")
        
        # Use Streamlit containers and columns for layout
        with st.container():
            # Header section
            col_header1, col_header2 = st.columns([3, 1])
            with col_header1:
                # Handle nested data structure for group_name
                group_name = report.get('group_name') or report.get('data', {}).get('group_name', 'Unknown Group')
                st.markdown(f"#### {group_name}")
            with col_header2:
                # Handle nested data structure for original_sources
                original_sources = report.get('original_sources') or report.get('data', {}).get('original_sources', [])
                st.markdown(f"**{len(original_sources)} sources**")
            
            # Tags section
            col_tags1, col_tags2, col_tags3 = st.columns(3)
            with col_tags1:
                st.markdown(f"""
                <div class="tag-blue">
                 {len(original_sources)} sources
                </div>
                """, unsafe_allow_html=True)
            
            with col_tags2:
                st.markdown(f"""
                <div class="tag-blue">
                    {type_icon} {report_type}
                </div>
                """, unsafe_allow_html=True)
            
            with col_tags3:
                # Handle nested data structure for time_range
                time_range = report.get('time_range') or report.get('data', {}).get('time_range', 'Unknown Period')
                st.markdown(f"""
                <div class="tag-blue">
                     {time_range}
                </div>
                """, unsafe_allow_html=True)
            
            # Divider
            st.markdown("---")
            
            # Footer section
            col_footer1, col_footer2 = st.columns(2)
            with col_footer1:
                st.caption(f"**Created:** {time.strftime('%Y-%m-%d %H:%M', created_time)} ({time_ago_text})")
            with col_footer2:
                # Handle nested data structure for id
                report_id = report.get('id') or report.get('data', {}).get('id', 'unknown')
                st.caption(f"**Report ID:** {report_id[:8]}...")

        # Action buttons for each report
        col_view, col_delete = st.columns(2)

        with col_view:
            if st.button("👁️ View Report", key=f"view_trend_{report_index}_{report_id[:8]}", use_container_width=True):
                # Set current report for viewing
                st.session_state.current_view_trend_report = report
                st.session_state.current_page = "view_single_trend_report"
                st.session_state.page_changed = True
                st.rerun()

        with col_delete:
            if st.button("🗑️ Delete", key=f"delete_trend_{report_index}_{report_id[:8]}", use_container_width=True):
                # Confirm deletion
                if st.checkbox(f"Confirm delete '{group_name}' report?", key=f"confirm_trend_{report_index}_{report_id[:8]}"):
                    if st.button("✅ Yes, Delete", key=f"confirm_yes_trend_{report_index}_{report_id[:8]}", type="secondary"):
                        try:
                            # Delete from session state
                            if report_id in st.session_state.get("stored_trend_reports", {}):
                                del st.session_state.stored_trend_reports[report_id]
                            
                            # Delete from persistent storage if applicable
                            if report.get('is_persistent', False) and report.get('filepath'):
                                if storage_available:
                                    delete_success = delete_report(report['filepath'])
                                    if delete_success:
                                        st.success(f"✅ Report '{group_name}' deleted from disk.")
                                    else:
                                        st.warning(f"⚠️ Report removed from session but failed to delete from disk.")
                                        
                        except Exception as e:
                            st.error(f"❌ Error deleting report: {e}")
                        
                        # Stay on the same page but refresh the list
                        st.rerun()

def render_view_single_trend_report_page():

    # Back button
    if st.button("← Back to Reports", key="back_to_reports_single", type="secondary"):
        st.session_state.current_page = "view_trend_reports"
        st.session_state.page_changed = True
        st.rerun()

    # Get the current report to view
    report_data = st.session_state.get("current_view_trend_report")

    if not report_data:
        st.error("No trend report selected.")
        if st.button("Go to Reports", key="goto_reports_single"):
            st.session_state.current_page = "view_trend_reports"
            st.session_state.page_changed = True
            st.rerun()
        return


    # Display the unified group report
    st.markdown("---")

    # Report内容字符串 - 处理不同的数据结构
    # 有些报告的sources在顶层，有些在data子字段中
    sources = report_data.get('sources') or report_data.get('data', {}).get('sources', [])
    if not sources:
        st.error("报告数据结构异常：找不到sources字段")
        if st.button("Go to Reports", key="goto_reports_error"):
            st.session_state.current_page = "view_trend_reports"
            st.session_state.page_changed = True
            st.rerun()
        return
    
    group_report = sources[0]  # Only one report for the entire group
    report_md = group_report['report']

    # ===== 新增：解析 Directions & Talent =====
    import re, textwrap

    def _parse_cards(section_md: str, heading_pat: str):
        pat = re.compile(heading_pat, re.MULTILINE)
        titles, poses = [], []
        
        for m in pat.finditer(section_md):
            raw_title = m.group(1).strip()
            # Remove trailing markdown link part if exists e.g. "Title [link](url)"
            raw_title = re.sub(r"\s*\[.*?\]\(.*?\)", "", raw_title).strip()
            # Remove markdown bold/italic markers
            raw_title = re.sub(r"\*\*(.*?)\*\*", r"\1", raw_title)  # **bold** -> bold
            raw_title = re.sub(r"\*(.*?)\*", r"\1", raw_title)      # *italic* -> italic
            raw_title = raw_title.strip()
            titles.append(raw_title)
            poses.append(m.start())
        
        if not titles:
            return []
        poses.append(len(section_md))
        cards = []
        
        for i, t in enumerate(titles):
            seg = section_md[poses[i]:poses[i+1]]
            raw_lines = seg.splitlines()[1:]  # Skip heading line
            # Preserve full raw markdown of this section (excluding heading)
            raw_md_block = "\n".join(raw_lines).strip()

            # Keep original content with minimal processing
            # Just remove the heading line and keep everything else
            
            # Extract references links if present
            links = []
            for ln in raw_lines:
                for m in re.finditer(r"\[([^\]]+)\]\((https?://[^)]+)\)", ln):
                    links.append({"title": m.group(1), "url": m.group(2)})
            
            # Keep content until next major section boundary (### or ##)
            clean_block = []
            for ln in raw_lines:
                stripped = ln.strip()
                # Stop at next major heading or end of sections
                if (re.match(r'^##\s+', stripped) or  # Major section
                    (re.match(r'^###\s+\d+\.', stripped) and clean_block)):  # Next numbered direction
                    break
                clean_block.append(ln)

            # Join content with minimal cleaning - preserve markdown formatting
            content = "\n".join(clean_block).strip()
            
            # Only remove the title if it appears at the very beginning
            if content.startswith(t):
                content = content[len(t):].strip()
            
            # 如果内容为空，提供默认内容
            if not content and not links:
                content = f"Details about {t} will be available soon."
            
            # Clean title by removing markdown formatting
            clean_title = re.sub(r'\*\*(.*?)\*\*', r'\1', t.strip())  # **bold** -> bold
            clean_title = re.sub(r'\*(.*?)\*', r'\1', clean_title)    # *italic* -> italic
            clean_title = clean_title.strip()
            
            cards.append({"title": clean_title, "content": content, "links": links, "raw_md": raw_md_block})
        
        return cards

    # 提取纯Markdown内容，跳过HTML表格头部
    # 查找Markdown内容的开始位置（跳过HTML表格）
    markdown_start_pattern = r"^##\s+A\.\s*Directions"
    markdown_start_match = re.search(markdown_start_pattern, report_md, flags=re.MULTILINE)
    
    if markdown_start_match:
        # 从找到的位置开始提取纯Markdown内容
        pure_markdown = report_md[markdown_start_match.start():]
        print(f"[frontend] Found markdown content starting at position {markdown_start_match.start()}")
    else:
        # 备用方案：如果没找到A. Directions，使用原始逻辑
        print("[frontend] No A. Directions found, using fallback parsing")
        pure_markdown = report_md
    
    # 分割成两大块
    sections = re.split(r"^##\s+B\.\s*Talent", pure_markdown, flags=re.MULTILINE)
    directions_md = sections[0]
    talent_md = sections[1] if len(sections) > 1 else ""

    # Remove trailing Sources section from talent_md to avoid pollution
    src_match_tal = re.search(r"^##\s+Sources Included", talent_md, flags=re.MULTILINE)
    if src_match_tal:
        talent_md = talent_md[:src_match_tal.start()]

    # 更新正则表达式以匹配新的三阶段生成格式
    # 尝试多种格式：### 1. **标题** 或 1. 标题
    directions = []
    direction_patterns = [
        r"^###\s+\d+\.\s+\*\*(.+?)\*\*",  # ### 1. **方向名称**
        r"^###\s+\d+\.\s+(.+)$",         # ### 1. 方向名称  
        r"^\s*(?:\d+\.\s+)(.+)$"         # 1. 方向名称 (原格式)
    ]
    
    for pattern in direction_patterns:
        directions = _parse_cards(directions_md, pattern)
        if directions:
            print(f"[frontend] Found {len(directions)} directions using pattern: {pattern}")
            break
    
    if not directions:
        print(f"[frontend] No directions found. First 500 chars of directions_md:")
        print(repr(directions_md[:500]))
        
    # ---- 解析 Talent 按方向分组 ----
    def _parse_talent_groups(md: str):
        group_pat = re.compile(r"^###\s+\d+\)\s+(.*)$", re.MULTILINE)
        cand_pat = re.compile(r"^####\s+\d+\.\d+\s+(.*)$", re.MULTILINE)

        g_titles, g_pos = [], []
        for m in group_pat.finditer(md):
            g_titles.append(m.group(1).strip())
            g_pos.append(m.end())  # content starts after heading line
        if not g_titles:
            return {}
        g_pos.append(len(md))

        groups = {}
        for idx, g_title in enumerate(g_titles):
            seg = md[g_pos[idx]:g_pos[idx+1]]
            # candidates inside
            c_titles, c_pos = [], []
            for m in cand_pat.finditer(seg):
                c_titles.append(m.group(1).strip())
                c_pos.append(m.start())
            if not c_titles:
                continue
            c_pos.append(len(seg))
            cards = []
            for j, ct in enumerate(c_titles):
                sub = seg[c_pos[j]:c_pos[j+1]]
                lines = sub.splitlines()[1:]
                clean_lines = []
                for ln in lines:
                    if (re.match(r"^\s*\d+\)\s+", ln) or             # 下一方向编号 (列表样式)
                        re.match(r"^###\s+\d+\)\s+", ln) or         # 新人才方向标题
                        re.match(r"^\s*</?div", ln) or                # div 边界（允许前导空白）
                        re.match(r"^\s*<button", ln) or               # button 边界
                        re.match(r"^\s*<hr", ln) or                  # html hr
                        re.match(r"^\s*---+\s*$", ln) or            # markdown hr
                        re.match(r"^\s*`{3}", ln) or                 # 代码块 fence
                        re.match(r"^####\s+\d+\.\d+", ln)):        # 下一个候选人标题防御
                        break
                    clean_lines.append(ln)

                def _clean_md(text: str):
                    text = re.sub(r"<[^>]+>", "", text)  # 移除HTML标签
                    text = re.sub(r"&[a-zA-Z]+;", "", text)  # 移除HTML实体
                    text = re.sub(r"\*\*|__", "", text)  # markdown 粗体/斜体
                    text = re.sub(r"^\s*\d+[\.\)]\s*", "", text)  # 行首编号
                    return text.strip()

                # 先粗清理行，再组合
                content_raw = "\n".join([_clean_md(l) for l in clean_lines]).strip()

                # 兜底：去掉任何仍然以 < 开头的 HTML 行
                content = "\n".join([
                    ln for ln in content_raw.splitlines()
                    if (not re.match(r"^\s*<", ln) and
                        not re.match(r"^\s*`{3}", ln) and
                        not re.match(r"^\s*---+\s*$", ln))
                ]).strip()

                # Convert bare URLs to markdown links
                def _linkify(txt: str):
                    # 1) Fix nested bracket links: [Title]([https://...]) -> [Title](https://...)
                    nested_pat = re.compile(r"\[([^\]]+)]\(\[\s*(https?://[^\]\)]+)\s*\]\)")
                    txt = nested_pat.sub(r"[\1](\2)", txt)

                    # 2) Convert bare URLs to links
                    url_pat = re.compile(r"(https?://[\w\-./?%&=:#]+)")
                    def _repl(m):
                        url = m.group(1)
                        # skip if already in markdown link syntax just before '['
                        if txt[max(0, m.start()-1)] == '(':  # crude check for markdown link
                            return url
                        return f"[{url}]({url})"
                    return url_pat.sub(_repl, txt)

                content = _linkify(content)

                if not content:
                    continue
                    
                # 创建包含完整学术字段的人才数据结构
                talent_name = _clean_md(ct)
                talent_card = {
                    "title": talent_name,
                    "content": content,
                    "email": "",
                    "affiliation": "",
                    "status": "",
                    "score": 0,
                    "profiles": {},
                    "research_interests": [],
                    "research_keywords": [],
                    "research_focus": [],
                    "notable_papers": [],
                    "publication_overview": [],
                    "top_tier_hits": [],
                    "honors_grants": [],
                    "service_talks": [],
                    "open_source_projects": [],
                    "representative_papers": [],
                    "highlights": [content] if content else [],
                    "radar": {},
                    "total_score": 0,
                    "detailed_scores": {},
                    "current_role_affiliation": "",
                    "current_status": ""
                }
                cards.append(talent_card)
            groups[g_title] = cards
        return groups

    # 优先使用 stage2_talents_structured（包含真实评分）
    three_stage_result = report_data.get('three_stage_result', {})
    stage2_talents_structured = three_stage_result.get('stage2_talents_structured', {})
    
    if stage2_talents_structured:
        talent_groups = stage2_talents_structured
    else:
        # 回退：从markdown解析（旧报告或数据丢失时）
        print("[Frontend] Fallback to parsing markdown")
        talent_groups = _parse_talent_groups(talent_md)
    
    # ---- Map talent groups to corresponding direction cards ----
    if directions and talent_groups:
        # Create a more flexible mapping by checking partial matches
        for c in directions:
            c["talents"] = []
            dir_title = c["title"].lower()
            for group_title, group_cards in talent_groups.items():
                group_lower = group_title.lower()
                # Try exact match first, then partial matches
                if (dir_title == group_lower or 
                    dir_title in group_lower or 
                    group_lower in dir_title or
                    any(word in group_lower for word in dir_title.split() if len(word) > 3)):
                    c["talents"].extend(group_cards)
                    break
 
    if not directions and not talent_groups:
        st.markdown(report_md, unsafe_allow_html=True)
        return

    tab_dirs, tab_talent = st.tabs(["📚 Directions", "🧑 Talents"])

    # ---------- Directions Tab ----------
    with tab_dirs:
        if directions:
            _render_card_grid(directions, prefix="dir")
        else:
            st.info("No directions parsed.")

    # ---------- Talent Tab ----------
    with tab_talent:
        if talent_groups:
            # 使用MSRA研究领域分类系统显示人才
            render_talent_tab_with_msra_classification(talent_groups)
        else:
            st.info("No talent profiles parsed.")

    # -------- Sources Included 已删除，不再显示 --------
    # src_match = re.search(r"##\s+Sources Included\s*([\s\S]*)", report_md)
    # if src_match:
    #     st.markdown("---")
    #     st.markdown("### 📑 Sources Included")
    #     st.markdown(src_match.group(1).strip(), unsafe_allow_html=True)

    return  # 已在 tabs 中渲染完成

def _render_direction_card_list(card_list):
    import streamlit as st, textwrap, html, re

    def _summary(txt: str, max_chars: int = 120):
        txt = re.sub(r"\*\*|__", "", txt)
        txt = re.sub(r"^\s*\d+[\.)]\s*", "", txt)
        txt = re.sub(r"\n+", " ", txt).strip()
        return textwrap.shorten(txt, width=max_chars, placeholder="…")

    for i, card in enumerate(card_list, 1):
        exp_key = f"exp_{i}"
        with st.expander(f"{i}. {card['title']}", expanded=False):
            left_col, middle_col, right_col = st.columns([1.4, 1, 1.2])
            with left_col:
                st.markdown(_summary(card.get('content', '')), unsafe_allow_html=True)
            with middle_col:
                st.markdown("_Add chart/visual here_", unsafe_allow_html=True)
            with right_col:
                pass  # placeholder
        # Button rendered outside to avoid expander collapse issue
        if st.button("📑 View Full Section", key=f"view_full_btn_{i}"):
            st.session_state['prev_page'] = st.session_state.get('current_page', 'view_single_trend_report')
            st.session_state.selected_direction = card
            try:
                st.session_state.selected_direction_json = json.dumps(card, ensure_ascii=False, default=str)
            except Exception:
                st.session_state.selected_direction_json = ""
            st.session_state.current_page = '🧑 Trend Talent'
            st.session_state.page_changed = True
            st.rerun()


def _render_card_grid(card_list, prefix="card"):
    import textwrap, streamlit as st, re, html

    def _summary(card):
        import re, html, textwrap
        raw = card.get('content','')
        
        # 只显示方向介绍，不包括Representative projects和References
        lines = [ln.strip() for ln in raw.split("\n") if ln.strip()]
        content_parts = []
        
        # 只处理方向介绍部分，遇到Representative projects或References就停止
        for ln in lines:
            # 停止条件：遇到Representative projects或References时停止
            if (re.match(r'^\s*Representative\s+[Pp]rojects', ln, re.IGNORECASE) or
                ln.startswith('**Representative') or
                re.match(r'^\s*References', ln, re.IGNORECASE) or
                ln.startswith('**References')):
                break
            
            # 清理markdown格式但保留重要结构
            clean_ln = re.sub(r"^\s*\d+[\.)]\s*", "", ln)  # 移除行首编号
            
            # 对于方向介绍文本，保留基本格式
            if ln.startswith('**') and not ln.startswith('**Representative'):
                # 保留重要标题（非Representative projects）
                clean_ln = clean_ln
            else:
                # 普通介绍文本
                clean_ln = clean_ln
            
            if clean_ln.strip() and not clean_ln.startswith('http'):
                content_parts.append(clean_ln.strip())
        
        # 合并内容
        full_content = "\n".join(content_parts)
        
        # 转换markdown格式为HTML显示
        def convert_markdown_to_html(text):
            # 转换粗体
            text = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', text)
            # 转换换行为HTML
            text = text.replace('\n', '<br>')
            return text
        
        return convert_markdown_to_html(full_content)

    num_per_row = 4
    for row_start in range(0, len(card_list), num_per_row):
        row_cards = card_list[row_start:row_start+num_per_row]
        # pad to fixed length for alignment
        while len(row_cards) < num_per_row:
            row_cards.append(None)
        cols = st.columns(num_per_row)
        for j, (col, card) in enumerate(zip(cols, row_cards)):
            idx = row_start + j
            with col:
                if card is None:
                    st.empty()
                    continue

                color = "#667eea"
                st.markdown(f"""
                <div style='border:2px solid {color}; border-radius:15px; padding:1rem; height:280px; display:flex; flex-direction:column; gap:0.5rem; background:#fafbfc;'>
                    <h5 style='margin:0; font-size:1.1rem; font-weight:600; color:#1e293b; border-bottom:1px solid #e1e5e9; padding-bottom:0.5rem;'>{card['title']}</h5>
                    <div style='font-size:0.85rem; line-height:1.4; overflow-y:auto; flex:1; padding-right:5px;'>
                        { _summary(card) if prefix.startswith('dir') else card['content'] }
                    </div>
                """, unsafe_allow_html=True)
                # Use Streamlit button instead of custom HTML to ensure click events work
                if st.button("Details", key=f"{prefix}_{idx}"):
                    # Remember previous page for back navigation
                    st.session_state["prev_page"] = st.session_state.get("current_page", "view_single_trend_report")
                    st.session_state.selected_direction = card
                    st.session_state.current_page = "🧑 Trend Talent"
                    st.session_state.page_changed = True
                    st.rerun()
                st.markdown("</div>", unsafe_allow_html=True)


def render_trend_radar_page():
    # Apply custom styles first
    apply_trend_radar_styles()

    # Initialize current page if not set
    if "current_page" not in st.session_state:
        # 与 Targeted Search 一致：使用 Emoji 作为主页面名称
        st.session_state.current_page = "📈 Trend Radar"

    # Clear any stale state when entering the page
    if "temp_sources" in st.session_state and st.session_state.current_page != "edit_trend_group":
        del st.session_state.temp_sources

    # Check if page was changed and clear any cached state
    if st.session_state.get('page_changed', False):
        st.session_state.page_changed = False
        # Force a clean state for the new page
        if "temp_sources" in st.session_state and st.session_state.current_page != "edit_trend_group":
            del st.session_state.temp_sources

    # Get current page and use exact matching
    current_page = st.session_state.get('current_page', '')
    
    # Use exact string matching for pages
    # 新增对 Emoji 名称的处理
    if current_page in ("trend_groups", "📈 Trend Radar"):
        target_page = "trend_groups"
    elif current_page == "edit_trend_group":
        target_page = "edit_trend_group"
    elif current_page == "generate_trend_report":
        target_page = "generate_trend_report"
    elif current_page in ("view_trend_reports", "📋 Trend Report"):
        target_page = "view_trend_reports"
    elif current_page == "view_single_trend_report":
        target_page = "view_single_trend_report"
    elif current_page == "view_single_trend_group":
        target_page = "view_single_trend_group"
    elif current_page == "view_direction_detail":
        target_page = "view_direction_detail"
    elif current_page == "🧑‍🔬 MSRA Talents":
        target_page = "msra_talents"
    else:
        # For main navigation pages, map them to sub-pages
        if current_page == "📈 Trend Radar":
            target_page = "trend_groups"
            st.session_state.current_page = "trend_groups"
        else:
            # Fallback: reset to trend groups page
            st.session_state.current_page = "trend_groups"
            target_page = "trend_groups"
    
    if target_page == "trend_groups":
        render_trend_groups_page()
    elif target_page == "edit_trend_group":
        render_edit_trend_group_page()
    elif target_page == "generate_trend_report":
        render_generate_trend_report_page()
    elif target_page == "view_trend_reports":
        render_view_trend_reports_page()
    elif target_page == "view_single_trend_report":
        render_view_single_trend_report_page()
    elif target_page == "view_direction_detail":
        render_view_direction_detail_page()
    elif target_page == "msra_talents":
        # 这个页面在app.py中处理，这里不需要额外处理
        # 但为了确保正确路由，我们保留这个分支
        pass
    else:
        # Fallback: reset to trend groups page
        st.session_state.current_page = "trend_groups"
        render_trend_groups_page()


#############################################
# 新增：查看单个 Trend Group 详情页
def render_view_single_trend_group_page():
    """Render detail page for a single trend group"""

    # Back button
    if st.button("← Back to Groups", key="back_to_groups_single_group", type="secondary"):
        st.session_state.current_page = "trend_groups"
        st.session_state.page_changed = True
        st.rerun()

    # 读取所选 group
    groups = load_groups()
    selected_group_id = st.session_state.get("selected_group")

    if not selected_group_id or selected_group_id not in groups:
        st.error("Group not found. Please go back and select again.")
        return

    group_data = groups[selected_group_id]

    # 页面标题
    st.markdown(f"## {group_data['name']} 详情")

    # 基本信息卡片
    st.markdown(f"""
    <div style="background: linear-gradient(135deg, {group_data['color']}15 0%, {group_data['color']}05 100%); border: 2px solid {group_data['color']}; border-radius: 15px; padding: 1.5rem; margin: 1rem 0;">
        <h4 style="margin: 0 0 1rem 0; color: {group_data['color']};">{group_data['name']}</h4>
        <p style="margin: 0 0 1rem 0;">{group_data['description']}</p>
        <p style="margin: 0;"><strong>Total Sources:</strong> {len(group_data['sources'])}</p>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("### 🔗 Sources")

    # 列表展示 source
    for idx, src in enumerate(group_data['sources'], 1):
        st.markdown(f"**{idx}. {src['name']}**  ({src['type'].title()})  ")
        st.markdown(f"URL: [{src['url']}]({src['url']})  ")
        st.markdown(f"Description: {src['description']}  ")
        st.markdown("---")


#############################################
# 新增：方向详情页
def render_view_direction_detail_page():
    """Show a single direction/full section with existing content directly."""

    import streamlit as st

    # Back navigation
    back_target = st.session_state.get("prev_page", "view_single_trend_report")
    if st.button("← Back", key="back_to_prev", type="secondary"):
        st.session_state.current_page = back_target
        st.session_state.page_changed = True
        st.rerun()

    d = st.session_state.get("selected_direction")
    if not d and "selected_direction_json" in st.session_state:
        try:
            d = json.loads(st.session_state.selected_direction_json)
            st.session_state.selected_direction = d
        except Exception:
            d = None

    if not d:
        st.error("No direction selected.")
        return

    st.markdown(f"## {d['title']}")

    # 调试：显示方向数据结构
    with st.expander("🔧 Debug: Direction Data Structure", expanded=False):
        st.json(d)

    # 显示方向的详细内容
    # 1. 优先显示缓存的详细报告
    detailed_reports_cache = st.session_state.get("detailed_reports_cache", {})
    direction_title = d.get("title", "")
    
    content_displayed = False
    
    if direction_title in detailed_reports_cache:
        # 如果有详细报告，显示详细报告内容
        detailed_content = detailed_reports_cache[direction_title]
        if detailed_content and detailed_content.strip():
            st.markdown("### Background & Details")
            st.markdown(detailed_content, unsafe_allow_html=True)
            content_displayed = True

    if not content_displayed:
        # 显示原始markdown内容（包含完整的方向描述）
        raw_content = d.get("raw_md", "").strip()
        if raw_content:
            st.markdown("### Direction Overview")
            st.markdown(raw_content, unsafe_allow_html=True)
            content_displayed = True

    if not content_displayed:
        # 显示解析后的基本内容
        content_to_show = d.get("content", "").strip()
        if content_to_show:
            st.markdown("### Direction Overview")
            st.markdown(content_to_show, unsafe_allow_html=True)
            content_displayed = True

    # 显示可用的链接
    links = d.get("links", [])
    if links:
        if content_displayed:
            st.markdown("---")
        st.markdown("### References")
        for link in links:
            st.markdown(f"• [{link.get('title', 'Link')}]({link.get('url', '#')})")
        content_displayed = True
    
    # 如果什么内容都没有，显示基本信息
    if not content_displayed:
        st.info("📋 **Direction Summary Available**")
        st.markdown("This direction contains valuable insights. The detailed analysis is being prepared.")
        
        # 至少显示可用的数据字段
        available_fields = []
        for key in d.keys():
            if key not in ['title'] and d.get(key):
                available_fields.append(key)
        
        if available_fields:
            st.markdown("**Available data fields:**")
            for field in available_fields:
                st.markdown(f"• {field}: {len(str(d.get(field, '')))[:50]}{'...' if len(str(d.get(field, ''))) > 50 else ''}")
    
    # 如果有人才信息，单独显示人才部分
    if "talents" in d and len(d.get("talents", [])) > 0:
        st.markdown("---")
        st.markdown("### 🧑‍🔬 Related Expert Talent")
        
        for i, talent in enumerate(d["talents"], 1):
            with st.expander(f"{i}. {talent.get('title', 'Unknown Researcher')}", expanded=False):
                # 显示人才详细信息
                col1, col2 = st.columns([2, 1])
                
                with col1:
                    affiliation = talent.get('affiliation', talent.get('current_role_affiliation', 'Unknown'))
                    status = talent.get('status', talent.get('current_status', 'Researcher'))
                    
                    st.markdown(f"**Institution:** {affiliation}")
                    st.markdown(f"**Position:** {status}")
                    
                    # 研究兴趣
                    interests = talent.get('research_interests', [])
                    if interests:
                        st.markdown(f"**Research Areas:** {', '.join(interests[:5])}")
                    
                    # 内容描述
                    content = talent.get('content', '')
                    if content:
                        st.markdown(f"**Profile:** {content}")
                    
                    # 研究亮点
                    highlights = talent.get('highlights', [])
                    if highlights:
                        st.markdown("**Research Highlights:**")
                        for highlight in highlights[:3]:
                            st.markdown(f"• {highlight}")
                
                with col2:
                    # 显示总分
                    total_score = talent.get('total_score', talent.get('score', 0))
                    if total_score:
                        st.metric("Overall Score", f"{total_score}/100")
                    
                    # 学术档案链接
                    profiles = talent.get('profiles', {})
                    if profiles:
                        st.markdown("**Academic Profiles:**")
                        for platform, url in profiles.items():
                            if url:
                                st.markdown(f"[{platform.title()}]({url})")

