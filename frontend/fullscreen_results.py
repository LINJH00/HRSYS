# pyright: reportMissingImports=false
import streamlit as st
import json
import pandas as pd
from pathlib import Path
import sys
import copy
import plotly.graph_objects as go
import html

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
    print(f"FullScreenResults ImportError: {e}")
    backend_available = False


def render_research_focus(research_focus: list, current_theme: str, text_color: str):
    if not research_focus:
        return

    # 主题自适配的颜色
    if current_theme == "dark":
        chip_bg = "rgba(59,130,246,.15)"  # 蓝色半透明
        chip_border = "rgba(59,130,246,.35)"
        chip_fg = "#e5e7eb"
        link_color = "#93c5fd"
        section_fg = "#e5e7eb"
        muted = "#94a3b8"
    else:
        chip_bg = "#eef2ff"
        chip_border = "#c7d2fe"
        chip_fg = "#0f172a"
        link_color = "#2563eb"
        section_fg = "#0f172a"
        muted = "#475569"

    chips_html = "".join(
        f'<span style="'
        f"background: {chip_bg}; "
        f"color: {chip_fg}; "
        f"border: 1px solid {chip_border}; "
        f"padding: 4px 8px; "
        f"border-radius: 12px; "
        f"font-size: 0.85em; "
        f"margin: 2px; "
        f"display: inline-block; "
        f"white-space: nowrap;"
        f'">{html.escape(area)}</span>'
        for area in research_focus
    )

    st.markdown(
        f"""
        <div style="margin: 1rem 0;">
            <h4 style="color: {section_fg}; margin-bottom: 0.5rem;">🔬 Research Focus</h4>
            <div style="line-height: 1.8;">{chips_html}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_profiles(profiles: dict, current_theme: str, text_color: str):
    # 过滤空链接
    items = [(k, v.strip()) for k, v in (profiles or {}).items() if v and v.strip()]
    if not items:
        return

    icons = {
        "Homepage": "🏠",
        "Google Scholar": "📚",
        "X (Twitter)": "🐦",
        "LinkedIn": "💼",
        "GitHub": "💻",
        "OpenReview": "📝",
        "Stanford HAI": "🎓",
    }

    if current_theme == "dark":
        link_color = "#93c5fd"
        link_hover = "#bfdbfe"
        bullet = "#64748b"
    else:
        link_color = "#2563eb"
        link_hover = "#1d4ed8"
        bullet = "#94a3b8"

    links_html = "".join(
        f'<li><a href="{html.escape(url)}" target="_blank">'
        f'<span class="pr-ico">{icons.get(platform, "🔗")}</span>'
        f"{html.escape(platform)}</a></li>"
        for platform, url in items
    )

    st.markdown(
        f"""
        <div style="margin: 1rem 0;">
            <h4 style="color: {text_color}; margin-bottom: 0.5rem;">🔗 Profiles</h4>
            <ul style="list-style: none; padding: 0; margin: 0;">
                {links_html}
            </ul>
        </div>
        <style>
        .pr-ico {{ margin-right: 8px; }}
        ul li a {{ 
            color: {link_color}; 
            text-decoration: none; 
            display: flex; 
            align-items: center; 
            padding: 4px 0; 
            border-radius: 4px; 
            transition: color 0.2s; 
        }}
        ul li a:hover {{ color: {link_hover}; }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def apply_fullscreen_results_styles():
    """Apply custom styles for the fullscreen results page"""
    st.markdown(
        """
        <style>
        .main .block-container {
            padding-top: 1rem;
            padding-bottom: 1rem;
        }
        .stButton > button {
            width: 100%;
        }
        .stExpander {
            border: 1px solid #e0e0e0;
            border-radius: 8px;
            margin-bottom: 1rem;
        }
        .stExpander > div:first-child {
            background-color: #f8f9fa;
            border-radius: 8px 8px 0 0;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_fullscreen_results_page():
    """Render the full-screen search results page"""
    # Get theme settings
    current_theme = st.session_state.get("theme", "light")
    text_color = "#0f172a" if current_theme == "light" else "#e5e7eb"


    
    # with col_header2:
    if st.button("← Back to Search", type="primary", use_container_width=False):
        # Navigate back to the previous page
        prev_page = st.session_state.get("prev_page", "🔍 Targeted Search")
        prev_page = "🔍 Targeted Search" if prev_page == "🔍 Full Screen Results" else prev_page
        print(f"[fullscreen_results.py] prev_page: {prev_page}")
        st.session_state.current_page = prev_page
        st.session_state.page_changed = True
        st.rerun()

    # st.markdown("---")

    # Check if we have search results
    if not st.session_state.get("show_results", False) or not st.session_state.get("search_results"):
        st.warning("No search results available. Please go back and perform a search first.")
        return

    results = st.session_state.search_results

    # Handle both DataFrame and list types
    if isinstance(results, pd.DataFrame):
        results = results.to_dict("records") if not results.empty else []

    if not results or len(results) == 0:
        st.warning("No search results found.")
        return

    # Display each candidate
    for i, candidate in enumerate(results, 1):
        # If it's a Pydantic model, use attribute access; else, dict
        is_model = hasattr(candidate, "model_dump") or hasattr(candidate, "__fields__")
        if is_model:
            # Pydantic v2 alias fields are accessible via attributes defined in schema
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

        # Create candidate card with three-column layout
        with st.expander(f"#{i} {name}", expanded=True):
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

            # Middle Column: Radar Chart (smaller and better text)
            with middle_col:
                if isinstance(radar, dict) and len(radar) > 0:
                    categories = list(radar.keys())
                    values = [radar[k] for k in categories]

                    # Enhanced label wrapping for better readability
                    def _wrap_label(text):
                        if len(text) > 12:
                            # Split on common separators first
                            if " & " in text:
                                return text.replace(" & ", " &<br>")
                            elif " " in text:
                                words = text.split(" ")
                                if len(words) > 1:
                                    mid = len(words) // 2
                                    return " ".join(words[:mid]) + "<br>" + " ".join(words[mid:])
                        return text

                    display_categories = [_wrap_label(c) for c in categories]
                    # Close the loop for radar chart
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
                    # Add padding to prevent text from being covered
                    pad = 0.08  # 8% padding

                    fig.update_layout(
                        font=dict(size=13, family="Arial, sans-serif"),
                        hoverlabel=dict(font_size=16, font_family="Arial, sans-serif"),
                        margin=dict(l=70, r=70, t=40, b=55),  # Increased margins
                        polar=dict(
                            # Shrink polar plot domain to avoid edge crowding
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
                                layer="above traces"  # Labels always above traces
                            ),
                            bgcolor="rgba(0,0,0,0)"
                        ),
                        showlegend=False,
                        paper_bgcolor="rgba(0,0,0,0)",
                        plot_bgcolor="rgba(0,0,0,0)"
                    )
                    st.plotly_chart(
                        fig,
                        use_container_width=False,  # Fixed width to prevent text squeezing
                        key=f"radar_chart_{i}",  # Unique key for each radar chart
                        config={
                            "displayModeBar": True,
                            "displaylogo": False,
                            "scrollZoom": True,  # Enabled zoom functionality
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
                # Research Focus
                render_research_focus(research_focus, current_theme or "light", text_color)

                # Profiles
                render_profiles(profiles, current_theme or "light", text_color)

                # View full profile button -> open subpage using candidate_profile layout
                if st.button(
                    "🧑 View Full Profile",
                    key=f"view_profile_{i}",
                    use_container_width=True,
                    type="primary",
                ):
                    try:
                        # Build CandidateOverview-like dict for profile page
                        if is_model:
                            dump_fn = getattr(candidate, "model_dump", None)
                            if callable(dump_fn):
                                cdict = dump_fn(by_alias=True)
                            else:
                                # Fallback: try to use __dict__ or convert to dict via json
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

                        # Normalize representative papers to expected keys in candidate_profile
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

                        # Convert to the simple keys used by candidate_profile.py
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
                            "highlights": cdict.get("Highlights", []),
                            "radar": cdict.get("Radar", {}),
                            "total_score": cdict.get("Total Score", 0),
                            "detailed_scores": cdict.get("Detailed Scores", {}),
                        }

                        # Store JSON string for candidate_profile page to consume
                        st.session_state["demo_candidate_overview_json"] = json.dumps(profile_payload)
                        # Remember previous page for back navigation
                        st.session_state["prev_page"] = st.session_state.get("current_page", "🔍 Full Screen Results")
                        # Navigate to subpage and rerun
                        st.session_state.current_page = "🧑 Candidate Profile"
                        st.session_state.page_changed = True
                        st.rerun()
                    except Exception as _:
                        pass
