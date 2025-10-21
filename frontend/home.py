import streamlit as st


def detect_theme_base() -> str:
    return st.context.theme.type


def _theme_tokens(base: str | None = None) -> dict:
    if not base:
        base = detect_theme_base()
    if base == "dark":
        return dict(
            fg="#e5e7eb", muted="#a8b3c2",
            panel="#101722", border="#263040",
            chip="#1f2937", chip_bd="#334155", brand="#5b4637",
            bar="#94a3b8", line="#c084fc",
            ring_fg="#10b981", ring_bg="#1f2937",
            plotly_template="plotly_dark"
        )
    else:  # light
        return dict(
            fg="#0f172a", muted="#374151",  # Darker text for better contrast in light theme
            panel="#ffffff", border="#e5e7eb",
            chip="#f1f5f9", chip_bd="#e5e7eb", brand="#8b5e3c",
            bar="#64748b", line="#7c3aed",
            ring_fg="#16a34a", ring_bg="#e5e7eb",
            plotly_template="plotly_white"
        )


@st.cache_data(ttl=0)  # Disable caching to ensure fresh rendering on theme change
def get_theme_colors():
    return _theme_tokens()

def render_home_page():
    # Check for theme changes and force rerun if needed
    current_theme = detect_theme_base()
    if 'last_theme' not in st.session_state:
        st.session_state.last_theme = current_theme
    elif st.session_state.last_theme != current_theme:
        st.session_state.last_theme = current_theme
        st.session_state.theme_changed = True
        # Clear cache to force fresh rendering
        get_theme_colors.clear()
        st.rerun()
    
    qp = st.query_params
    if "page" in qp:
        target = qp.get("page")
        # 把 query 参数映射到你的页面名
        mapping = {
            "targeted": "🔍 Targeted Search",
            "achieve": "📊 Achievement Report",
            "resume":  "📄 Resume Evaluation",
            "trend":   "📈 Trend Radar",
        }
        if target in mapping:
            st.session_state.current_page = mapping[target]
            st.session_state.page_changed = True
            # 清空参数避免回退再次触发
            st.query_params.clear()
            st.rerun()
    
    # Get theme-aware colors (with caching disabled for theme changes)
    theme = get_theme_colors()
    
    # Add a unique key to force CSS refresh when theme changes
    theme_key = f"theme_{current_theme}_{hash(str(theme))}"
    
    """Render the beautiful home page"""
    st.markdown("## 🚀 Core Features")
    
    # Stats section with clickable navigation buttons
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        if st.button("🔍 Targeted Search\n\nAI-powered candidate discovery", key="nav_smart_search", use_container_width=True, help="Click to go to Targeted Search"):
            st.session_state.current_page = "🔍 Targeted Search"
            st.session_state.page_changed = True
            st.rerun()

    with col2:
        if st.button("📊 Achievement Report\n\nGroup Performance insights", key="nav_analytics", use_container_width=True, help="Click to go to Achievement Report"):
            st.session_state.current_page = "📊 Achievement Report"
            st.session_state.page_changed = True
            st.rerun()

    with col3:
        if st.button("📄 Resume Evaluation\n\nTalent Resume analysis", key="nav_evaluation", use_container_width=True, help="Click to go to Resume Evaluation"):
            st.session_state.current_page = "📄 Resume Evaluation"
            st.session_state.page_changed = True
            st.rerun()

    with col4:
        if st.button("📈 Trends \n\n Radar", key="nav_trends", use_container_width=True, help="Click to go to Trend Radar"):
            st.session_state.current_page = "📈 Trend Radar"
            st.session_state.page_changed = True
            st.rerun()
    
        
    st.markdown(f"""
    <style data-theme-key="{theme_key}">
    /* Theme-specific CSS - {theme_key} */
    .feature-grid{{
    display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:20px;
    position: relative;
    }}
    @media (max-width:1100px){{ .feature-grid{{ grid-template-columns:1fr; }} }}

    .home-feature-card{{
    position:relative;                 /* 关键：让覆盖链接能够定位 */
    height:100%; min-height:300px;
    padding:24px; border-radius:14px;
    background:rgba(255,255,255,0.08);
    backdrop-filter:blur(4px);
    border:1px solid rgba(255,255,255,0.15);
    box-shadow:0 6px 18px rgba(0,0,0,0.15);
    display:flex; flex-direction:column;
    }}
    .home-feature-card::before{{
    content:""; display:block; height:4px; width:100%;
    background:linear-gradient(90deg,#a78bfa,#60a5fa);
    border-radius:12px 12px 0 0; margin:-24px -24px 16px -24px;
    }}
    .home-feature-icon{{ font-size:28px; line-height:1; margin-bottom:10px; opacity:.95; }}
    .home-feature-card h3{{ color:{theme['fg']} !important; font-size:1.25rem; margin:0 0 12px 0; }}
    .home-feature-card p{{ color:{theme['muted']} !important; line-height:1.6; margin:0 0 12px 0; }}
    .home-feature-card ul{{ color:{theme['muted']} !important; margin-left:18px; margin-top:0; }}
    .home-feature-card .grow{{ flex:1 1 auto;font-weight: bold; }}

    /* 覆盖整卡的可点击区域 */
    .cover-link{{
    position:absolute; inset:0; z-index:10; 
    border-radius:14px;               /* 与卡片一致，鼠标感知更自然 */
    text-decoration:none;
    }}
    /* hover 效果：轻微高亮 */
    .home-feature-card:hover{{ box-shadow:0 10px 24px rgba(0,0,0,0.22); border-color:rgba(255,255,255,0.25); cursor:pointer; }}

    /* Hide the overlay buttons */
    div[data-testid*="targeted_overlay"], div[data-testid*="resume_overlay"],
    div[data-testid*="achieve_overlay"], div[data-testid*="trend_overlay"] {{
        position: absolute !important;
        opacity: 0 !important;
        pointer-events: auto !important;
        z-index: 10 !important;
        width: 50% !important;
        height: 300px !important;
    }}

    /* Position buttons over cards */
    div[data-testid*="targeted_overlay"] {{ top: 0 !important; left: 0 !important; }}
    div[data-testid*="resume_overlay"] {{ top: 0 !important; right: 0 !important; }}
    div[data-testid*="achieve_overlay"] {{ top: 320px !important; left: 0 !important; }}
    div[data-testid*="trend_overlay"] {{ top: 320px !important; right: 0 !important; }}
    </style>
    """, unsafe_allow_html=True)

    st.markdown("## 🚀 Detailed Features")

    # Display the HTML cards (visual only - navigation handled by buttons above)
    st.markdown("""
    <div class="feature-grid">

    <div class="home-feature-card">
        <div class="home-feature-icon">🔍</div>
        <h3>Talent Search</h3>
        <p class="grow">AI-powered semantic search across research areas and roles, with customizable rules, competency insights, and rich profiles.</p>
        <hr>
        <ul>
        <li>Global Talent Discovery</li>
        <li>Customizable Search Rules</li>
        <li>Competency Radar Charts</li>
        <li>Comprehensive Candidate Profiles</li>
        </ul>
    </div>
    
    <div class="home-feature-card">
        <div class="home-feature-icon">📊</div>
        <h3>Achievement Report</h3>
        <p class="grow">Generate comprehensive achievement reports for a specific research group.</p>
        <hr>
        <ul>
        <li>Customizable group settings</li>
        <li>Team snapshot</li>
        <li>Group-level achievements</li>
        <li>Individual reports</li>
        </ul>
    </div>

    <div class="home-feature-card">
        <div class="home-feature-icon">📄</div>
        <h3>Resume Evaluation</h3>
        <p class="grow">AI-powered resume analysis with detailed scoring and recommendations.</p>
        <hr>
        <ul>
        <li>PDF resume parsing</li>
        <li>Skills assessment</li>
        <li>Role fit analysis</li>
        <li>Group Fit Analysis</li>
        </ul>
    </div>

    <div class="home-feature-card">
        <div class="home-feature-icon">📈</div>
        <h3>Trend Radar</h3>
        <p class="grow">Real-time trend and talent insights from open social data.</p>
        <hr>
        <ul>
        <li>Social media monitoring</li>
        <li>Direction analysis</li>
        <li>Market insights</li>
        <li>Talent recommendation</li>
        </ul>
    </div>

    </div>
    """, unsafe_allow_html=True)


    # Footer with better styling
    st.markdown("---")
