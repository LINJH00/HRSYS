import json
import html
import re
import streamlit as st
import plotly.graph_objects as go

from .targeted_search import render_research_focus, render_profiles




def apply_candidate_profile_styles():
    st.markdown(
        """
<style>
.profile-wrap { display: grid; grid-template-columns: 1.1fr 1.4fr; gap: 1rem; }
@media (max-width: 1100px) { .profile-wrap { grid-template-columns: 1fr; } }
.panel { background: white; border-radius: 12px; padding: 1rem 1.25rem; border: 1px solid #e5e7eb; }
.section-title { font-weight: 700; margin: .5rem 0; }
.badge { display:inline-block; background:#eef2ff; color:#3730a3; border:1px solid #c7d2fe; border-radius:9999px; padding:.15rem .5rem; font-size:.8rem; margin:.15rem .25rem .15rem 0; }
.divider { height: 1px; background: #e5e7eb; margin: .75rem 0; }
.hl-item { margin-left: 1rem; list-style: disc; }
.list-compact { margin:.25rem 0 .5rem 1rem; }
.rep-item { margin:.4rem 0; }
.score-box { background:#d1fae5; border:2px solid #10b981; border-radius:12px; padding: .75rem; text-align:center; }
/* Ensure long links and text wrap inside Streamlit markdown */
.stMarkdown p, .stMarkdown li { overflow-wrap:anywhere; word-break:break-word; }
.stMarkdown a { word-break: break-all; }
</style>
        """,
        unsafe_allow_html=True,
    )


def _get_theme_text_color():
    return "#e5e7eb" if st.get_option("theme.base") == "dark" else "#111827"


def _render_radar(radar: dict, text_color: str):
    if not radar:
        return
    categories = list(radar.keys())
    values = [radar[k] for k in categories]
    categories_closed = categories + [categories[0]]
    values_closed = values + [values[0]]
    fig = go.Figure()
    fig.add_trace(
        go.Scatterpolar(
            r=values_closed,
            theta=categories_closed,
            fill="toself",
            name="Profile",
            line=dict(color="#667eea", width=2),
            fillcolor="rgba(102, 126, 234, 0.2)",
        )
    )
    fig.update_layout(
        margin=dict(l=40, r=40, t=30, b=30),
        polar=dict(
            radialaxis=dict(visible=True, range=[0, 5], tickfont=dict(size=12, color=text_color)),
            angularaxis=dict(tickfont=dict(size=12, color=text_color)),
        ),
        showlegend=False,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(fig, use_container_width=True, config={"displaylogo": False})


def _linkify(text: str) -> str:
    """Escape text but convert URLs to clickable anchors.
    Keeps wrapping intact via CSS set on parent container.
    """
    return text

def render_candidate_profile_page(candidate_data: dict | None = None, include_back_button: bool = True):
    apply_candidate_profile_styles()

    # Check if we have any candidate data
    data: dict
    if not candidate_data:
        demo_str = st.session_state.get("demo_candidate_overview_json")
        if demo_str:
            data = json.loads(demo_str)
        else:
            # No candidate data available, show error message
            st.error("❌ No candidate data available to display.")
            st.markdown("""
            **To view a candidate profile:**
            1. 🔍 Go to the **Targeted Search** page
            2. 📊 Perform a search to find candidates
            3. 👥 Click on a candidate to view their profile
            """)
            return
    else:
        data = candidate_data

    text_color = _get_theme_text_color()

    # Back button to previous page (e.g., targeted search)
    if include_back_button:
        back_col, _ = st.columns([1, 6])
        with back_col:
            if st.button("← Back", key="candidate_back_button", type="primary"):
                prev = st.session_state.get("prev_page", "🔍 Targeted Search")
                st.session_state.current_page = prev
                st.session_state.page_changed = True
                st.rerun()

    left, right = st.columns([1.1, 1.4], gap="small")

    with left:
        with st.container(border=True):
            name = data.get("name", "")
            role = data.get("current_role_affiliation", "")
            total_score = data.get("total_score")
            st.markdown(f"### {html.escape(name)}")
            if role:
                st.markdown(f"**📍 {html.escape(role)}**")
            if isinstance(total_score, int):
                pct = total_score / 35 * 100
                st.markdown(
                    f"""
<div class="score-box">
  <div style="font-size:.9rem;color:{text_color}">Final Score</div>
  <div style="font-size:1.6rem;font-weight:700;color:#10b981">{total_score}/35</div>
  <div style="font-size:.8rem;color:{text_color}">({pct:.1f}%)</div>
</div>
                    """,
                    unsafe_allow_html=True,
                )

        with st.container(border=True):
            st.markdown("#### Research Profile")
            _render_radar(data.get("radar", {}), text_color)
            render_research_focus(data.get("research_focus", []), "dark" if st.get_option("theme.base") == "dark" else "light", text_color)
            render_profiles(data.get("profiles", {}), "dark" if st.get_option("theme.base") == "dark" else "light", text_color)

    with right:
        if data.get("highlights"):
            with st.container(border=True):
                st.markdown("#### Highlights")
                highs = data.get("highlights", [])
                if highs:
                    st.markdown("\n".join([f"- {_linkify(x)}" for x in highs]), unsafe_allow_html=True)
                else:
                    st.caption("No highlights")

        if data.get("publication_overview"):
            with st.container(border=True):
                st.markdown("#### Publication Overview")
                pubs = data.get("publication_overview", [])
                if pubs:
                    st.markdown("\n".join([f"- {_linkify(x)}" for x in pubs]), unsafe_allow_html=True)
                hits = data.get("top_tier_hits", [])
                if hits:
                    st.markdown("<div class=divider></div>", unsafe_allow_html=True)
                    st.markdown("**Acceptances (last 24 months):** " + ", ".join([_linkify(x) for x in hits]), unsafe_allow_html=True)
        if data.get("honors_grants"):
            with st.container(border=True):
                st.markdown("#### Honors/Funding")
                honors = data.get("honors_grants", [])
                if honors:
                    st.markdown("\n".join([f"- {_linkify(x)}" for x in honors]), unsafe_allow_html=True)

        if data.get("service_talks"):
            with st.container(border=True):
                st.markdown("#### Academic Service/Invited Talks")
                svc = data.get("service_talks", [])
                if svc:
                    st.markdown("\n".join([f"- {_linkify(x)}" for x in svc]), unsafe_allow_html=True)
                else:
                    st.caption("No service records")

        if data.get("open_source_projects"):
            with st.container(border=True):
                st.markdown("#### Open Source/Datasets/Projects")
                proj = data.get("open_source_projects")
                if isinstance(proj, list):
                    st.markdown("\n".join([f"- {_linkify(x)}" for x in proj]), unsafe_allow_html=True)
                elif isinstance(proj, str) and proj.strip():
                    st.markdown(_linkify(proj), unsafe_allow_html=True)
        if data.get("representative_papers"):
            with st.container(border=True):
                st.markdown("#### Representative Papers")
                reps = data.get("representative_papers", [])
                for item in reps or []:
                    title = item.get("title", "")
                    venue = item.get("venue", "")
                    year = item.get("year", "")
                    links = item.get("links", "")
                    
                    if links:
                        st.markdown("- " + f"{html.escape(title)} — {html.escape(venue)} {html.escape(str(year))} ({_linkify(links)})", unsafe_allow_html=True)
                    else:
                        st.markdown("- " + f"{html.escape(title)} — {html.escape(venue)} {html.escape(str(year))}", unsafe_allow_html=True)
                
                # Display trigger paper below representative papers
                trigger_title = data.get("trigger_paper_title", "")
                trigger_url = data.get("trigger_paper_url", "")
                if trigger_title:
                    st.markdown("---")
                    st.markdown("**Paper that led to this candidate discovery:**")
                    if trigger_url:
                        st.markdown(f"- {html.escape(trigger_title)} ([Link]({trigger_url}))", unsafe_allow_html=True)
                    else:
                        st.markdown(f"- {html.escape(trigger_title)}", unsafe_allow_html=True)

