import streamlit as st, html
import plotly.graph_objects as go
from collections import Counter
import datetime, re
import sys
import os
from typing import List, Dict, Any

# optional backend trend_data
try:
    from backend import trend_data
except ImportError:
    trend_data = None

# 导入人才搜索功能
try:
    sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'backend'))
    from trend_talent_search import (
        search_talents_for_direction, 
        search_talents_by_names, 
        search_talents_with_fallback  # 新增智能搜索函数
    )  # type: ignore
    TALENT_SEARCH_AVAILABLE = True
except ImportError as e:
    print(f"Talent search not available: {e}")
    TALENT_SEARCH_AVAILABLE = False
    # 定义回退函数 - 返回空列表而非演示数据
    def search_talents_for_direction(*args, **kwargs):
        return []
    def search_talents_by_names(*args, **kwargs):
        return []
    def search_talents_with_fallback(*args, **kwargs):
        return []

# MSRA 研究领域分类系统
MSRA_RESEARCH_AREAS = {
    "Engineering Foundation": {
        "short": "EF",
        "color": "#667eea",
        "keywords": ["engineering", "foundation", "systems", "infrastructure"]
    },
    "General Artificial Intelligence": {
        "short": "GenAI", 
        "color": "#f093fb",
        "keywords": ["artificial intelligence", "AI", "general AI", "AGI", "machine intelligence"]
    },
    "Intelligent Multimedia": {
        "short": "IM",
        "color": "#4facfe",
        "keywords": ["multimedia", "video", "audio", "image", "media processing"]
    },
    "Internet Graphics": {
        "short": "IG", 
        "color": "#43e97b",
        "keywords": ["graphics", "rendering", "visualization", "3D", "computer graphics"]
    },
    "Machine Learning Area": {
        "short": "ML",
        "color": "#fa709a",
        "keywords": ["machine learning", "deep learning", "neural networks", "learning algorithms"]
    },
    "Media Computing": {
        "short": "MC",
        "color": "#fee140", 
        "keywords": ["media computing", "digital media", "content analysis", "media understanding"]
    },
    "Social Computing": {
        "short": "SC",
        "color": "#a8edea",
        "keywords": ["social computing", "social networks", "human behavior", "social simulation"]
    },
    "Systems and Networking Research": {
        "short": "SNR",
        "color": "#d299c2",
        "keywords": ["systems", "networking", "distributed systems", "cloud computing"]
    },
    "Visual Computing": {
        "short": "VC", 
        "color": "#89f7fe",
        "keywords": ["computer vision", "visual computing", "image processing", "pattern recognition"]
    },
    "Multi-Modal Interaction": {
        "short": "MMI",
        "color": "#66a6ff",
        "keywords": ["multimodal", "interaction", "human-computer interaction", "HCI"]
    },
    "Multimedia Search and Mining": {
        "short": "MSM",
        "color": "#89ffdd",
        "keywords": ["multimedia search", "data mining", "information retrieval", "content mining"]
    }
}


# 人才信息解析辅助函数
def _extract_field(text: str, pattern: str) -> str:
    """从文本中提取单个字段"""
    match = re.search(pattern, text, re.DOTALL)
    return match.group(1).strip() if match else ""

def _extract_list_section(text: str, pattern: str) -> List[str]:
    """从文本中提取列表项"""
    match = re.search(pattern, text, re.DOTALL)
    if not match:
        return []
    
    content = match.group(1).strip()
    # 分割成行并清理
    lines = [line.strip() for line in content.split('\n') if line.strip()]
    # 过滤掉空行和只包含符号的行
    items = []
    for line in lines:
        # 移除列表符号
        cleaned = re.sub(r'^[-•\*]\s*', '', line)
        if cleaned and not re.match(r'^[\s\-\*•]+$', cleaned):
            items.append(cleaned)
    return items

def _extract_numbered_list(text: str, pattern: str) -> List[str]:
    """从文本中提取编号列表项"""
    match = re.search(pattern, text, re.DOTALL)
    if not match:
        return []
    
    content = match.group(1).strip()
    # 查找编号项 1. 2. 3. 等
    numbered_items = re.findall(r'\d+\.\s*"([^"]+)"[^"]*?(\d+\+?\s*citations)', content)
    papers = []
    for title, citations in numbered_items:
        papers.append(f"{title} - {citations}")
    
    return papers

def parse_academic_details(full_description: str) -> Dict[str, Any]:
    """ Set to empty if not found """
    # 返回空字段结构，真实数据应该已经在 talent dict 中了
    result = {
        'highlights': [],
        'publication_overview': [],
        'honors_grants': [],
        'service_talks': [],
        'open_source_projects': [],
        'representative_papers': []
    }
    return result


def parse_markdown_talents_to_list(markdown_text: str, source_direction: str) -> List[Dict[str, Any]]:
    """
    将markdown格式的人才信息解析为结构化的人才列表
    
    Args:
        markdown_text: Stage2生成的markdown格式人才信息
        source_direction: 来源方向名称
        
    Returns:
        解析后的人才对象列表
    """
    talents = []
    
    # 使用正则表达式匹配人才信息
    # 匹配 #### 1.1 [Researcher Name] 格式
    talent_pattern = re.compile(r'####\s+\d+\.\d+\s+(.+?)(?=\n####|\n\n|\Z)', re.DOTALL)
    
    for match in talent_pattern.finditer(markdown_text):
        talent_block = match.group(1).strip()
        lines = talent_block.split('\n')
        
        # 第一行是姓名，可能包含方括号
        name_line = lines[0].strip()
        # 移除可能的方括号
        name = re.sub(r'[\[\]]', '', name_line).strip()
        
        # 解析其他字段
        talent = {
            'title': name,
            'name': name,
            'source_direction': source_direction,
            'affiliation': '',
            'current_role_affiliation': '',
            'status': '',
            'current_status': '',
            'research_interests': [],
            'research_focus': [],
            'research_keywords': [],
            'content': '',
            'highlights': [],
            'profiles': {},
            'total_score': 0,  # 默认未评分，待真实评分填充
            'radar': {}
        }
        
        # 获取完整的人才描述文本用于解析
        full_description = '\n'.join(lines[1:])
        
        
        # 解析基本字段
        for line in lines[1:]:
            line = line.strip()
            if line.startswith('**Affiliation**:'):
                affiliation = line.replace('**Affiliation**:', '').strip()
                talent['affiliation'] = affiliation
                talent['current_role_affiliation'] = affiliation
            elif line.startswith('**Role**:'):
                role = line.replace('**Role**:', '').strip()
                talent['status'] = role
                talent['current_status'] = role
            elif line.startswith('**Research Focus**:'):
                focus = line.replace('**Research Focus**:', '').strip()
                talent['research_focus'] = [focus] if focus else []
                talent['research_interests'] = [focus] if focus else []
                talent['content'] = focus
            elif line.startswith('**Contact Potential**:'):
                potential = line.replace('**Contact Potential**:', '').strip()
                if talent['content']:
                    talent['content'] += f"\n\nContact Potential: {potential}"
                else:
                    talent['content'] = f"Contact Potential: {potential}"
        
        # 解析学术详细信息
        academic_details = parse_academic_details(full_description)
        talent.update(academic_details)
        
        # 如果没有解析到基本信息，至少保证有名字
        if not talent['content']:
            talent['content'] = f"Researcher working in {source_direction}"
        # 不再在这里设置highlights，由parse_academic_details统一处理
        
        talents.append(talent)
    
    
    # 如果没有匹配到任何人才，尝试简单的解析
    if not talents and markdown_text.strip():
        # 简单fallback：将整个文本作为一个人才条目
        lines = [line.strip() for line in markdown_text.split('\n') if line.strip()]
        if lines:
            # 尝试从第一行提取姓名
            first_line = lines[0]
            name_match = re.search(r'(\w+\s+\w+)', first_line)
            name = name_match.group(1) if name_match else f"Researcher from {source_direction}"
            
            talent = {
                'title': name,
                'name': name,
                'source_direction': source_direction,
                'affiliation': 'Unknown Institution',
                'current_role_affiliation': 'Unknown Institution',
                'status': 'Researcher',
                'current_status': 'Researcher',
                'research_interests': [source_direction],
                'research_focus': [source_direction],
                'research_keywords': [source_direction],
                'content': '\n'.join(lines[:3]),  # 使用前3行作为内容
                # 'highlights': ['\n'.join(lines[:2])] if len(lines) >= 2 else [lines[0]], # 由parse_academic_details统一处理
                'profiles': {},
                'total_score': 0,  # 默认未评分，待真实评分填充
                'radar': {}
            }
            talents.append(talent)
    
    return talents


def classify_talent_by_research_areas(talent: Dict[str, Any]) -> List[str]:
    """
    根据研究者的关键词和研究兴趣，将其分类到相应的MSRA研究领域
    
    Args:
        talent: 研究者信息字典
        
    Returns:
        匹配的研究领域短名称列表
    """
    # 获取研究者的相关信息文本
    text_sources = [
        talent.get('content', ''),
        ' '.join(talent.get('research_interests', [])),
        ' '.join(talent.get('research_keywords', [])),
        ' '.join(talent.get('research_focus', [])),
        talent.get('title', ''),
        ' '.join(talent.get('highlights', []))
    ]
    
    # 合并所有文本并转换为小写
    combined_text = ' '.join(text_sources).lower()
    
    # 匹配研究领域
    matched_areas = []
    for area_name, area_info in MSRA_RESEARCH_AREAS.items():
        keywords = area_info['keywords']
        # 检查是否有关键词匹配
        if any(keyword in combined_text for keyword in keywords):
            matched_areas.append(area_info['short'])
    
    # 如果没有匹配到任何领域，默认分类为GenAI
    if not matched_areas:
        matched_areas = ['GenAI']
    
    return matched_areas[:3]  # 最多返回3个匹配的领域


def render_talent_tab_with_msra_classification(talent_groups: Dict[str, List[Dict]]):
    """
    在Trend Radar报告页面的Talent标签中使用MSRA研究领域分类系统
    
    Args:
        talent_groups: 从trend radar报告解析出的人才分组数据
    """
    apply_trend_talent_styles()
    
    # 将talent_groups转换为统一的人才列表
    all_talents = []
    
    for group_name, cards in talent_groups.items():
        for card in cards:
            # 将卡片数据转换为人才对象格式
            talent = {
                'title': card.get('title', 'Unknown Researcher'),
                'name': card.get('title', 'Unknown Researcher'),
                'source_direction': group_name,
                'affiliation': card.get('affiliation', 'Unknown Institution'),
                'current_role_affiliation': card.get('affiliation', 'Unknown Institution'),
                'status': card.get('status', 'Researcher'),
                'current_status': card.get('status', 'Researcher'),
                'research_interests': card.get('research_interests', []),
                'research_focus': card.get('research_focus', []),
                'research_keywords': card.get('research_keywords', []),
                'content': card.get('content', ''),
                'highlights': card.get('highlights', []),
                'profiles': card.get('profiles', {}),
                'total_score': card.get('total_score', card.get('score', 25)),
                'radar': card.get('radar', {}),
                'email': card.get('email', ''),
                'publication_overview': card.get('publication_overview', []),
                'top_tier_hits': card.get('top_tier_hits', []),
                'honors_grants': card.get('honors_grants', []),
                'service_talks': card.get('service_talks', []),
                'open_source_projects': card.get('open_source_projects', []),
                'representative_papers': card.get('representative_papers', []),
                'detailed_scores': card.get('detailed_scores', {})
            }
            
            # 分类到MSRA研究领域
            talent['research_areas'] = classify_talent_by_research_areas(talent)
            all_talents.append(talent)
    
    # 显示数据统计
    st.markdown(f"### 🧑‍🔬 Discovered Talents ({len(all_talents)} researchers)")
    
    if all_talents:
        # 显示数据来源分布
        source_counts = {}
        for talent in all_talents:
            source = talent.get('source_direction', 'Unknown')
            source_counts[source] = source_counts.get(source, 0) + 1
        
        if len(source_counts) > 1:
            source_info = " | ".join([f"{src}: {count}" for src, count in source_counts.items()])
            st.markdown(f"**Data sources:** {source_info}")
        
        # 研究领域标签过滤器
        st.markdown("#### 🏷️ Research Area Filters")
        
        # 创建标签按钮布局
        area_cols = st.columns(6)  # 6列布局
        selected_areas = []
        
        all_area_names = list(MSRA_RESEARCH_AREAS.keys())
        
        for i, area_name in enumerate(all_area_names):
            col_idx = i % 6
            area_info = MSRA_RESEARCH_AREAS[area_name]
            
            with area_cols[col_idx]:
                # 使用session state跟踪选中状态
                key = f"talent_tab_area_filter_{area_info['short']}"
                if key not in st.session_state:
                    st.session_state[key] = False
                    
                if st.button(area_name, key=f"talent_tab_btn_{area_info['short']}", 
                            type="primary" if st.session_state[key] else "secondary"):
                    st.session_state[key] = not st.session_state[key]
                    st.rerun()
                    
                if st.session_state[key]:
                    selected_areas.append(area_info['short'])
        
        # 如果没有选择任何领域，显示所有人才
        if not selected_areas:
            filtered_talents = all_talents
        else:
            # 过滤人才
            filtered_talents = []
            for talent in all_talents:
                talent_areas = talent.get('research_areas', [])
                if any(area in selected_areas for area in talent_areas):
                    filtered_talents.append(talent)
        
        # 显示过滤结果统计
        if selected_areas:
            area_names = [area for area, info in MSRA_RESEARCH_AREAS.items() if info['short'] in selected_areas]
            st.markdown(f"**Filtered by:** {', '.join(area_names)} | **Showing:** {len(filtered_talents)} researchers")
        
        # 显示人才卡片 - 4列网格布局
        if filtered_talents:
            st.markdown("---")
            render_talent_grid(filtered_talents[:20])  # 显示前20个研究者
        else:
            st.info("🔍 No talents found for the selected research areas.")
    else:
        st.info("📊 No talent data available in this report.")


def render_msra_talent_categories_page():
    """
    渲染按MSRA研究领域分类的人才展示页面
    """
    apply_trend_talent_styles()
    
    # 页面标题和原则说明
    st.title("🧑‍🔬 Talents")
    
    st.markdown("""
    **Principle:** Prioritize first authors/core contributors of papers or projects that trended/gained attention in the past 1-2 weeks; later supplement with GitHub activity and institutional info for cross-referenced scoring.
    """)
    
    # 获取所有方向的人才数据
    all_talents = []
    
    # 从trend radar的各个方向收集人才数据
    if 'trend_groups' in st.session_state:
        groups = st.session_state.trend_groups
        for group_id, group_data in groups.items():
            if 'three_stage_result' in group_data:
                three_stage = group_data['three_stage_result']
                
                # ⭐ 优先使用结构化数据（包含完整学术信息）
                stage2_structured = three_stage.get('stage2_talents_structured', {})
                if stage2_structured:
                    print(f"[Talent Profile] Using structured talent data from {group_id}")
                    for direction_name, talents_list in stage2_structured.items():
                        for talent in talents_list:
                            talent['research_areas'] = classify_talent_by_research_areas(talent)
                            talent['source_direction'] = direction_name
                            all_talents.append(talent)
                else:
                    # Fallback: 解析 markdown（向后兼容旧数据）
                    print(f"[Talent Profile] Parsing markdown talent data from {group_id}")
                    stage2_talents = three_stage.get('stage2_talents', {})
                    for direction_name, talents_markdown in stage2_talents.items():
                        if isinstance(talents_markdown, str):
                            parsed_talents = parse_markdown_talents_to_list(talents_markdown, direction_name)
                            for talent in parsed_talents:
                                talent['research_areas'] = classify_talent_by_research_areas(talent)
                                all_talents.append(talent)
                        elif isinstance(talents_markdown, list):
                            for talent in talents_markdown:
                                talent['research_areas'] = classify_talent_by_research_areas(talent)
                                talent['source_direction'] = direction_name
                                all_talents.append(talent)
    
    # 显示数据来源信息
    if all_talents:
        st.success(f"✅ **Found {len(all_talents)} talents from Trend Radar analysis**")
        
        # 显示数据来源分布
        source_counts = {}
        for talent in all_talents:
            source = talent.get('source_direction', 'Unknown')
            source_counts[source] = source_counts.get(source, 0) + 1
        
        if len(source_counts) > 1:
            source_info = " | ".join([f"{src}: {count}" for src, count in source_counts.items()])
            st.markdown(f"**Data sources:** {source_info}")
    
    # 如果没有人才数据，显示提示信息
    if not all_talents:
        st.warning("📊 **No talent data available from Trend Radar analysis**")
        st.markdown("""
        **To get talent data:**
        1. 🎯 Go to **Trend Radar** page
        2. 📊 Generate a trend report 
        3. 🔄 Return to this page to see talents classified by MSRA research areas
        
        **Next steps if the issue persists:**
        - Ensure you have run a Trend Radar analysis first
        - Check if the talent search modules are properly installed
        - Contact support if needed
        """)
        return
    
    # 研究领域标签过滤器
    st.markdown("### 🏷️ Research Areas")
    
    # 创建标签按钮布局
    area_cols = st.columns(6)  # 6列布局
    selected_areas = []
    
    all_area_names = list(MSRA_RESEARCH_AREAS.keys())
    
    for i, area_name in enumerate(all_area_names):
        col_idx = i % 6
        area_info = MSRA_RESEARCH_AREAS[area_name]
        
        with area_cols[col_idx]:
            # 使用session state跟踪选中状态
            key = f"area_filter_{area_info['short']}"
            if key not in st.session_state:
                st.session_state[key] = False
                
            if st.button(area_name, key=f"btn_{area_info['short']}", 
                        type="primary" if st.session_state[key] else "secondary"):
                st.session_state[key] = not st.session_state[key]
                st.rerun()
                
            if st.session_state[key]:
                selected_areas.append(area_info['short'])
    
    # 如果没有选择任何领域，显示所有人才
    if not selected_areas:
        filtered_talents = all_talents
    else:
        # 过滤人才
        filtered_talents = []
        for talent in all_talents:
            talent_areas = talent.get('research_areas', [])
            if any(area in selected_areas for area in talent_areas):
                filtered_talents.append(talent)
    
    # 显示过滤结果统计
    st.markdown(f"### 👥 Discovered Talents ({len(filtered_talents)} researchers)")
    
    if selected_areas:
        area_names = [area for area, info in MSRA_RESEARCH_AREAS.items() if info['short'] in selected_areas]
        st.markdown(f"**Filtered by:** {', '.join(area_names)}")
    
    # 显示人才卡片 - 4列网格布局
    if filtered_talents:
        render_talent_grid(filtered_talents[:20])  # 显示前20个研究者
    else:
        st.info("🔍 No talents found for the selected research areas.")


def render_talent_grid(talents: List[Dict[str, Any]]):
    """
    以4列网格布局渲染人才卡片
    """
    num_cols = 4
    
    for row_start in range(0, len(talents), num_cols):
        row_talents = talents[row_start:row_start + num_cols]
        cols = st.columns(num_cols)
        
        for i, talent in enumerate(row_talents):
            with cols[i]:
                render_talent_card(talent, card_index=row_start + i)


def render_talent_card(talent: Dict[str, Any], card_index: int):
    """渲染人才卡片 - 完全复用 Targeted Search 的卡片样式"""
    from frontend.targeted_search import _display_candidate_card
    
    # 获取主题（与 Targeted Search 完全一致的方式）
    try:
        current_theme = st.context.theme.type if hasattr(st.context, 'theme') else "light"
    except:
        current_theme = "light"
    
    # 使用与 Targeted Search 完全相同的颜色配置
    text_color = "#f1f5f9" if current_theme == "dark" else "#495057"
    
    # 转换数据格式为 Targeted Search 期望的字典格式
    # 注意：_display_candidate_card 的字典分支期望特定的键名（首字母大写，带空格）
    candidate_dict = {
        'Name': talent.get('title', talent.get('name', 'Unknown')),
        'Current Role & Affiliation': talent.get('affiliation', talent.get('current_role_affiliation', '')),
        'Research Focus': talent.get('research_focus', talent.get('research_interests', [])),
        'Profiles': talent.get('profiles', {}),
        'Total Score': talent.get('score', talent.get('total_score', 0)),
        'Radar': talent.get('radar', {}),
        'Notable': talent.get('highlights', []),
        'Email': talent.get('email', ''),
        'Current Status': talent.get('current_status', talent.get('status', 'Researcher')),
        'Research Keywords': talent.get('research_keywords', []),
        'Publication Overview': talent.get('publication_overview', []),
        'Top-tier Hits (Last 24 Months)': talent.get('top_tier_hits', []),
        'Honors/Grants': talent.get('honors_grants', []),
        'Academic Service / Invited Talks': talent.get('service_talks', []),
        'Open-source / Datasets / Projects': talent.get('open_source_projects', []),
        'Representative Papers': talent.get('representative_papers', []),
        'Highlights': talent.get('highlights', []),
        'Detailed Scores': talent.get('detailed_scores', {})
    }
    
    # 直接调用 Targeted Search 的卡片渲染函数
    _display_candidate_card(candidate_dict, card_index, current_theme, text_color)


# 直接复用 Targeted Search 详情页的样式
from frontend.candidate_profile import apply_candidate_profile_styles as _apply_cp_style


def apply_trend_talent_styles():
    """Apply styles aligned with Targeted Search"""
    _apply_cp_style()  # 复用相同 CSS，保持外观一致
    
    # Add Targeted Search alignment styles
    st.markdown(
        """
    <style>
    /* Enhanced button styling aligned with Targeted Search */
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
    
    /* Align column spacing with Targeted Search */
    .block-container .element-container .stColumns {
        gap: 1rem !important;
    }
    
    /* Talent card alignment styling */
    .talent-card {
        background: var(--background-color);
        border: 2px solid var(--secondary-background-color);
        border-radius: 12px;
        padding: 1.5rem;
        margin: 1rem 0;
        transition: all 0.3s ease;
        box-shadow: 0 2px 8px rgba(0,0,0,0.1);
    }
    
    .talent-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 8px 25px rgba(0,0,0,0.15);
        border-color: #667eea;
    }
    </style>
    """,
        unsafe_allow_html=True,
    )


def render_trend_talent_page():
    """Render trend direction detail page with talent results."""
    apply_trend_talent_styles()
    
    # 获取选中的方向数据
    if 'selected_direction' in st.session_state:
        card = st.session_state.selected_direction
        # 检查当前是否为全屏模式
        current_page = st.session_state.get("current_page", "")
        is_fullscreen = (current_page == "🔍 Full Screen Talent Results")
        render_trend_talent_detail_page(card, is_fullscreen=is_fullscreen)
    else:
        st.error("No direction selected. Please go back and select a direction.")
        if st.button("← Back to Trend Radar"):
            st.session_state.current_page = "📈 Trend Radar"
            st.session_state.page_changed = True
            st.rerun()


def render_trend_talent_detail_page(card: Dict[str, Any], is_fullscreen: bool = False):
    """
    渲染趋势人才详情页面
    
    Args:
        card: 趋势方向卡片数据
        is_fullscreen: 是否为全屏模式
    """
    apply_trend_talent_styles()
    
    # 导航栏处理
    if 'prev_page' in st.session_state:
        prev_page = st.session_state.prev_page
        back_target = st.session_state.get("prev_page", "📊 Trend Radar")
        
        # Check if coming from full screen mode
        if prev_page == "🔍 Full Screen Talent Results":
            # Special back button for full screen mode
            if st.button("← Back to Full Screen", type="secondary"):
                st.session_state.current_page = prev_page
                st.session_state.page_changed = True
                st.rerun()
        else:
            # Regular back button
            if st.button("← Back", type="secondary"):
                st.session_state.current_page = back_target
                st.session_state.page_changed = True
                st.rerun()

    # ---------- Data aggregation ----------
    art_cnt90 = 0
    weekly_series = {}
    inst_set = set()
    talent_mentions = 0
    direction_kw = [w.lower() for w in re.findall(r"[A-Za-z]{4,}", card.get("title", ""))]
    
    # ⭐ 跳过复杂的数据获取以避免程序卡住
    recent_map = None
    # 使用基础统计数据
    art_cnt90 = 15
    weekly_series = {40: 3, 41: 5, 42: 7}
    inst_set = {"AI Research Lab", "Tech Corp"}
    talent_mentions = 8

    # Main layout - Conditional based on full screen mode
    if is_fullscreen:
        # Full screen mode: only show talent results
        st.markdown("### 📊 Full Screen Talent Results")
        # Use the entire width for talent display
        right_col = st.container()
        left_col = None
    else:
        # Normal mode: Left side for direction details, right side for talents (aligned with Targeted Search)
        left_col, right_col = st.columns([1, 1.4])
    
    if left_col:
        with left_col:
            # Blue header with direction title in left column
            st.markdown(f"""
        <div style="background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%); 
                    color: white; 
                    padding: 2rem 1.5rem; 
                    border-radius: 12px; 
                    margin-bottom: 1.5rem;
                    text-align: left;">
            <h1 style="margin: 0; font-size: 2rem; font-weight: 600; line-height: 1.2;">
                {html.escape(card.get('title', 'Detail'))}
            </h1>
        </div>
            """, unsafe_allow_html=True)
            # Framework diagram placeholder
            st.markdown("""
            <div style="background: #f8fafc; 
                        border: 2px dashed #cbd5e1; 
                        border-radius: 12px; 
                        padding: 2rem; 
                        text-align: center; 
                        margin: 1rem 0;">
                <h4 style="color: #64748b; margin: 0;">Framework Diagram</h4>
                <p style="color: #94a3b8; margin: 0.5rem 0 0 0; font-size: 0.9rem;">Architecture/flow chart placeholder</p>
            </div>
            """, unsafe_allow_html=True)

            # Main content area
            summary = card.get("content", "")
            if summary:
                st.markdown(summary, unsafe_allow_html=True)

            # Representative projects section
            raw_md = card.get("raw_md", "")
            rep_projects = []
            lines = raw_md.splitlines()
            for idx, ln in enumerate(lines):
                if re.match(r"^\s*Representative\s+projects", ln, flags=re.IGNORECASE):
                    for sub in lines[idx+1:]:
                        sub = sub.strip()
                        if not sub or re.match(r"^\s*References", sub, flags=re.IGNORECASE):
                            break
                        # strip leading bullets or dashes
                        rep_projects.append(re.sub(r"^[\-*\d\.\s]+", "", sub))
                    break

            if rep_projects:
                st.markdown("**Representative projects**")
                for p in rep_projects:
                    if p.strip():
                        st.markdown(f"**{p.split('(')[0].strip()}**")
                        if '(' in p:
                            desc_parts = p.split('(', 1)[1].replace(')', '').split(';')
                            for desc in desc_parts:
                                if desc.strip():
                                    st.markdown(f"{desc.strip()};")

            # Date and reference at bottom
            links = card.get("links", [])
            date_match = re.search(r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},\s+\d{4}", summary + raw_md)
            
            st.markdown("---")
            if links:
                for l in links:
                    st.markdown(f"[{l['title']}]({l['url']})", unsafe_allow_html=True)
            if date_match:
                st.markdown(f"**{date_match.group(0)}**", unsafe_allow_html=True)

    with right_col:
        # Talent Results Section - Conditional header based on full screen mode  
        if not is_fullscreen:
            # Normal mode: show header with full screen button
            col2_header1, col2_header2 = st.columns([3, 1])
            
            with col2_header1:
                st.markdown("### 📊 Talent Results")
            
            with col2_header2:
                # Full screen button - only show when there are results
                talents = card.get("talents", [])
                search_key = f"talent_search_{card.get('title', 'unknown')}"
                has_talent_results = (
                    st.session_state.get(search_key) or 
                    talents or 
                    len(talents) > 0
                )
                
                if has_talent_results:
                    if st.button("🔍 Full Screen", type="primary", use_container_width=True):
                        # Store current page for back navigation
                        st.session_state["prev_page"] = st.session_state.get("current_page", "📊 Trend Radar")
                        # Navigate to full screen results page
                        st.session_state.current_page = "🔍 Full Screen Talent Results"
                        st.session_state.page_changed = True
                        st.rerun()
        else:
            # Full screen mode: just initialize variables
            talents = card.get("talents", [])
            search_key = f"talent_search_{card.get('title', 'unknown')}"
        
        # 检查是否有缓存的搜索结果
        if search_key not in st.session_state:
            st.session_state[search_key] = None
        
        
        # 保留原始逻辑但不显示按钮
        if False:  # 禁用搜索按钮
            if st.button("🔍 Search for actual talent", key="search_real_talents", help="Use SearXNG to search for real researchers in this direction"):
                direction_title = card.get("title", "")
                direction_content = card.get("content", "")
                
                if TALENT_SEARCH_AVAILABLE:
                    # 增强的搜索进度展示
                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    
                    try:
                        # 获取API密钥
                        api_key = (st.session_state.get("llm_api_key", "") or 
                  st.session_state.get("openai_api_key", ""))
                        
                        status_text.text("🔍 Analyzing research direction...")
                        progress_bar.progress(25)
                        
                        status_text.text("📊 Searching academic databases...")
                        progress_bar.progress(50)
                        
                        # 执行搜索
                        searched_talents = search_talents_for_direction(
                            direction_title=direction_title,
                            direction_content=direction_content,
                            max_candidates=1,
                            api_key=api_key
                        )
                        
                        status_text.text("🏆 Processing results...")
                        progress_bar.progress(75)
                        
                        if searched_talents and len(searched_talents) > 0:
                            # 缓存结果
                            st.session_state[search_key] = searched_talents
                            status_text.text("✅ Search completed!")
                            progress_bar.progress(100)
                            st.success(f"🎉 Found {len(searched_talents)} candidates! Check the results below.")
                        else:
                            # 空结果处理
                            status_text.text("⚠️ No results found")
                            progress_bar.progress(100)
                            st.warning("No candidates found for this direction. You can try:")
                            st.markdown("""
                            - 🎯 Use keyword search instead
                            - 🔄 Try different search terms  
                            - 🌐 Use the online talent search button for individual names
                            """)
                            st.session_state[search_key] = None
                            
                    except Exception as e:
                        status_text.text("❌ Search failed")
                        progress_bar.progress(0)
                        st.error(f"🚨 Search encountered an error: {e}")
                        st.markdown("""
                        **Troubleshooting suggestions:**
                        - Check your internet connection
                        - Ensure SearXNG service is running  
                        - Try the keyword search option
                        - Contact support if the issue persists
                        """)
                        st.session_state[search_key] = None
                        
                        # 提供重试按钮
                        if st.button("🔄 Retry Search", key="retry_search"):
                            st.rerun()
                    
                    # 清理进度显示
                    import time
                    time.sleep(1)
                    progress_bar.empty()
                    status_text.empty()
                    
                else:
                    st.warning("🔌 Search function is unavailable. Please ensure:")
                    st.markdown("""
                    - SearXNG service is running
                    - Docker containers are healthy
                    - Network connectivity is available
                    
                    Please try the keyword search or individual name search instead.
                    """)
        
        # 使用搜索结果或回退到默认数据
        if st.session_state[search_key]:
            talents = st.session_state[search_key]
        else:
            # ✅ 禁用自动填充：Stage 2混合搜索已提供完整人才信息
            # 不再进行额外的网络搜索来"增强"人才信息
            # talents 保持从报告解析得到的原始数据
            pass

        if not talents:
            # ✅ 智能人才数据获取：从session state中查找对应方向的人才
            direction_title = card.get("title", "")
            
            
            # 尝试从当前报告的人才数据中查找对应方向的人才
            try:
                # 检查是否有完整的报告数据缓存
                current_report = st.session_state.get("current_view_trend_report")
                if current_report and "sources" in current_report:
                    report_content = current_report["sources"][0].get("report", "")
                    
                    # 解析报告中的人才部分
                    talent_section_match = re.search(r"##\s+B\.\s*Talent\s*Analysis\s*([\s\S]*?)(?=##|$)", report_content)
                    if talent_section_match:
                        talent_md = talent_section_match.group(1)
                        
                        # 查找当前方向对应的人才组，使用更灵活的匹配
                        # 匹配 "### 1) 方向名称" 这样的格式
                        direction_keywords = [w.lower() for w in re.findall(r"\b[a-zA-Z]{3,}\b", direction_title)]
                        
                        talent_group_pattern = r"###\s+\d+\)\s+(.*?)\n(.*?)(?=###|\Z)"
                        talent_group_matches = re.finditer(talent_group_pattern, talent_md, re.DOTALL)
                        
                        best_match_content = None
                        for group_match in talent_group_matches:
                            group_title = group_match.group(1).lower()
                            # 检查是否包含方向的关键词
                            if any(keyword in group_title for keyword in direction_keywords):
                                best_match_content = group_match.group(2)
                                break
                        
                        if best_match_content:
                            # 解析个别人才信息 - 使用新格式 "#### X.Y 姓名\n描述"
                            talent_matches = re.finditer(r"####\s+\d+\.\d+\s+(.*?)\n(.*?)(?=####|\Z)", best_match_content, re.DOTALL)
                            
                            parsed_talents = []
                            for match in talent_matches:
                                name = match.group(1).strip()
                                description = match.group(2).strip()
                                
                                # 从描述中提取信息
                                # 尝试提取机构信息
                                affiliation_patterns = [
                                    r"at\s+([^,\.]+(?:University|Institute|College|Academy|Technologies?|Lab|Company|Corporation))",
                                    r"([^,\.]+(?:University|Institute|College|Academy|Technologies?|Lab|Company|Corporation))",
                                ]
                                
                                affiliation = "Research Institution"
                                for pattern in affiliation_patterns:
                                    match_aff = re.search(pattern, description, re.IGNORECASE)
                                    if match_aff:
                                        affiliation = match_aff.group(1).strip()
                                        break
                                
                                # 提取职位信息
                                role_patterns = [
                                    r"(Professor|Researcher|Scientist|Director|CEO|Founder|Student)",
                                    r"(Chair|Associate|Assistant|Senior|Principal)"
                                ]
                                
                                role = "Researcher"
                                for pattern in role_patterns:
                                    match_role = re.search(pattern, description, re.IGNORECASE)
                                    if match_role:
                                        role = match_role.group(1).strip()
                                        break
                                
                                # 提取研究领域
                                research_focus = []
                                focus_match = re.search(r"focus(?:es|ing)?\s+on\s+([^\.]+)", description, re.IGNORECASE)
                                if focus_match:
                                    research_focus = [focus_match.group(1).strip()]
                                
                                talent_data = {
                                    "title": name,
                                    "affiliation": affiliation,
                                    "current_role_affiliation": affiliation,
                                    "status": role,
                                    "research_focus": research_focus,
                                    # "highlights": [description[:200] + "..." if len(description) > 200 else description], # 由parse_academic_details统一处理
                                    "content": description,
                                    "source": "Report Analysis",
                                    "total_score": 0  # 默认未评分，待真实评分填充
                                }
                                
                                # 解析学术详细信息
                                academic_details = parse_academic_details(description)
                                talent_data.update(academic_details)
                                parsed_talents.append(talent_data)
                            
                            if parsed_talents:
                                talents = parsed_talents
                                st.success(f"✅ 找到该方向的 {len(talents)} 个人才信息！")
                            
            except Exception as e:
                pass
            
            # 如果仍然没有人才数据，显示友好提示
            if not talents:
                st.info("No talent profiles parsed.")
                talents = []
        
        # 渲染人才卡片
        if talents:
            current_theme = getattr(st.context, 'theme', None)
            current_theme = getattr(current_theme, 'type', 'light') if current_theme else 'light'
            
            # Theme-specific colors
            if current_theme == "dark":
                text_color = "#f1f5f9"
            else:
                text_color = "#495057"
            
            st.markdown(f"### 👥 Discovered Talents ({len(talents)} researchers)")
            
            from frontend.targeted_search import _display_candidate_card
            
            # Display each candidate using Targeted Search's card component
            for i, talent in enumerate(talents[:5], 1):
                # 转换数据格式为 Targeted Search 期望的字典格式（首字母大写，带空格）
                candidate_dict = {
                    'Name': talent.get('title', talent.get('name', f'Candidate {i}')),
                    'Current Role & Affiliation': talent.get('affiliation', talent.get('current_role_affiliation', 'N/A')),
                    'Research Focus': talent.get('research_focus', talent.get('research_interests', [])),
                    'Profiles': talent.get('profiles', {}),
                    'Total Score': talent.get('total_score', talent.get('score', 0)),
                    'Radar': talent.get('radar', {}),
                    'Notable': talent.get('highlights', []),
                    # ⭐ 使用 Targeted Search 期望的字段名格式（首字母大写，带空格）
                    'Email': talent.get('email', ''),
                    'Current Status': talent.get('current_status', talent.get('status', 'Researcher')),
                    'Research Keywords': talent.get('research_keywords', []),
                    'Publication Overview': talent.get('publication_overview', []),
                    'Top-tier Hits (Last 24 Months)': talent.get('top_tier_hits', []),
                    'Honors/Grants': talent.get('honors_grants', []),
                    'Academic Service / Invited Talks': talent.get('service_talks', []),
                    'Open-source / Datasets / Projects': talent.get('open_source_projects', []),
                    'Representative Papers': talent.get('representative_papers', []),
                    'Highlights': talent.get('highlights', []),
                    'Detailed Scores': talent.get('detailed_scores', {})
                }
                
                _display_candidate_card(candidate_dict, i, current_theme, text_color)

    # ---------- 导出功能（像targeted search一样） ----------
    if talents:
        st.markdown("### 📤 Export results")
        
        export_col1, export_col2 = st.columns(2)
        
        with export_col1:
            if st.button("📊 Export as CSV", type="secondary", use_container_width=True):
                # Convert to DataFrame for CSV export
                try:
                    import pandas as pd
                    df_data = []
                    for talent in talents:
                        df_data.append({
                            "Name": talent.get('title', talent.get('name', '')),
                            "Affiliation": talent.get('affiliation', talent.get('current_role_affiliation', '')),
                            "Status": talent.get('status', ''),
                            "Research Interests": ", ".join(talent.get('research_interests', talent.get('research_focus', []))),
                            "Total Score": talent.get('total_score', talent.get('score', 0)),  # 使用 total_score
                            "Homepage": talent.get('profiles', {}).get('Homepage', ''),
                            "Google Scholar": talent.get('profiles', {}).get('Google Scholar', ''),
                            "GitHub": talent.get('profiles', {}).get('GitHub', ''),
                            "LinkedIn": talent.get('profiles', {}).get('LinkedIn', ''),
                        })
                    
                    df = pd.DataFrame(df_data)
                    csv = df.to_csv(index=False, encoding='utf-8-sig')
                    st.download_button(
                        label="💾 Download CSV",
                        data=csv,
                        file_name=f"trend_talents_{card.get('title', 'unknown').replace(' ', '_')}.csv",
                        mime="text/csv",
                        use_container_width=True,
                    )
                except ImportError:
                    st.error("You need to install the pandas library to export CSV. Please run: pip install pandas")
        
        with export_col2:
            if st.button("📋 Export as JSON", type="secondary", use_container_width=True):
                export_data = {
                    "direction": card.get("title", ""),
                    "search_timestamp": datetime.datetime.now().isoformat(),
                    "talents": talents,
                    "source": "search" if st.session_state.get(search_key) else "report"
                }
                import json
                json_data = json.dumps(export_data, indent=2, ensure_ascii=False)
                st.download_button(
                    label="💾 Download JSON",
                    data=json_data,
                    file_name=f"trend_talents_{card.get('title', 'unknown').replace(' ', '_')}.json",
                    mime="application/json",
                    use_container_width=True,
                )
    


def render_research_focus(research_focus:list, current_theme:str, text_color:str):
    """渲染研究兴趣标签 - 从targeted_search.py复制"""
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

        <div class="section-title">🔬 研究方向:</div>
        <div class="rf-wrap">{chips_html}</div>
        """,
        unsafe_allow_html=True,
    )


def render_profiles(profiles:dict, current_theme:str, text_color:str):
    """渲染学术档案链接 - 从targeted_search.py复制"""
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

        <div class="pr-title">🔗 学术档案:</div>
        <ul class="pr-grid">{links_html}</ul>
        """,
        unsafe_allow_html=True,
    )

