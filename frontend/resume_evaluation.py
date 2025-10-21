import json
import time
import threading
import queue
import requests
from pathlib import Path
from typing import Dict, List, Any

import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

# Import candidate profile rendering function
from frontend.candidate_profile import render_candidate_profile_page


# Backend entry for direct homepage evaluation
try:
    from backend.talent_search_module.direct_homepage_evaluation import evaluate_homepage_to_candidate_overview
    _direct_eval_available = True
except Exception as _:
    _direct_eval_available = False

def detect_theme_base() -> str:
    return st.context.theme.type or "light"


# ------------------------ utils (新增的内部小工具，不改原函数名) ------------------------
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
            fg="#0f172a", muted="#6b7280",
            panel="#ffffff", border="#e5e7eb",
            chip="#f1f5f9", chip_bd="#e5e7eb", brand="#8b5e3c",
            bar="#64748b", line="#7c3aed",
            ring_fg="#16a34a", ring_bg="#e5e7eb",
            plotly_template="plotly_white"
        )


def _clamp01(x: float) -> float:
    try:
        v = float(x)
    except Exception:
        return 0.0
    return 0.0 if v < 0 else (1.0 if v > 1 else v)

def _load_json_from_text_or_file(text: str | None, uploaded) -> Dict[str, Any] | None:
    """
    优先用文件，其次用文本。解析失败返回 None。
    """
    if uploaded is not None:
        try:
            return json.loads(uploaded.read().decode("utf-8"))
        except Exception as e:
            st.error(f"JSON 文件解析失败：{e}")
            return None
    if text and text.strip():
        try:
            return json.loads(text)
        except Exception as e:
            st.error(f"JSON 文本解析失败：{e}")
            return None
    return None

def _normalize_result(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    防御式补缺省，确保渲染不炸。
    """
    data = data or {}
    data.setdefault("candidate", {})
    data.setdefault("character", {})
    data.setdefault("metrics", {})
    data.setdefault("notes", {})
    data.setdefault("time_series", [])
    data.setdefault("representative_paper", {}).setdefault("mention", {})
    # clamp 三条性格条
    ch = data["character"]
    ch["theoretical_vs_applied"] = _clamp01(ch.get("theoretical_vs_applied", 0.5))
    ch["depth_vs_breadth"] = _clamp01(ch.get("depth_vs_breadth", 0.5))
    ch["independent_vs_team"] = _clamp01(ch.get("independent_vs_team", 0.5))
    return data

def apply_resume_evaluation_styles(theme_base: str = "light") -> None:
    if theme_base == "dark":
        css_vars = """
        :root{
          --fg:#e5e7eb; --bg:#0b1017;
          --panel:#101722; --panel-2:#0f172a;
          --line:#263040; --muted:#a8b3c2;
          --accent:#c084fc; --accent-2:#10b981;
          --brand:#5b4637; --chip:#1f2937; --chip-bd:#334155;
          --bar-grad:linear-gradient(90deg,#5f6b87 0%,#0ea5e9 100%);
          --thumb:#f0f3f8;
        }"""
    else:  # light
        css_vars = """
        :root{
          --fg:#0f172a; --bg:#f6f7fb;
          --panel:#ffffff; --panel-2:#f8fafc;
          --line:#e5e7eb; --muted:#6b7280;
          --accent:#7c3aed; --accent-2:#16a34a;
          --brand:#8b5e3c; --chip:#f1f5f9; --chip-bd:#e5e7eb;
          --bar-grad:linear-gradient(90deg,#9fb3ff 0%,#38bdf8 100%);
          --thumb:#0f172a;
        }"""

    st.markdown(f"""
<style>
{css_vars}
html,body{{background:transparent;color:var(--fg)}}

/* Card */
.te-card{{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:16px;
  box-shadow:0 10px 28px rgba(0,0,0,.12);color:var(--fg)}}
.card-head{{display:flex;align-items:center;justify-content:space-between;margin-bottom:12px}}
.card-title{{display:flex;align-items:center;gap:8px;font-weight:800;font-size:18px}}
.card-ico{{width:22px;height:22px;display:inline-flex;align-items:center;justify-content:center;border-radius:6px;
  background:var(--chip);border:1px solid var(--chip-bd)}}
.share-pill{{display:inline-flex;gap:8px;align-items:center;background:var(--brand);color:#fff;border:0;
  padding:6px 12px;border-radius:999px;font-size:12px;cursor:pointer;opacity:.95}}
.share-pill:hover{{opacity:1}}
.card-foot{{margin-top:10px;text-align:center;font-size:12px;color:var(--muted)}}
.te-card.equal{{height:100%;display:flex;flex-direction:column}}
.te-card.equal .card-foot{{margin-top:auto}}

/* vertical stack 间距 */
.stack-gap{{height:14px}}

/* Character bars */
.char-row{{display:grid;grid-template-columns:170px 1fr 170px;gap:10px;align-items:center;margin:12px 0}}
.char-track{{height:14px;border-radius:999px;background:#2b3340;position:relative;overflow:hidden}}
.char-track:before{{content:"";position:absolute;inset:0;background:var(--bar-grad);opacity:.9}}
.char-label{{font-size:16px;color:var(--fg);opacity:.95}}
.char-thumb{{position:absolute;top:-4px;width:4px;height:22px;background:var(--thumb);border-radius:3px;
  box-shadow:0 0 0 2px rgba(0,0,0,.15)}}

/* KPI grids */
.kpi-3{{display:grid;grid-template-columns:repeat(3,1fr);gap:18px;margin:6px 0 8px}}
.kpi-3 .val{{font-size:24px;font-weight:800}}
.kpi-3 .lab{{font-size:12px;color:var(--muted)}}

.kpi-6{{display:grid;grid-template-columns:repeat(6,1fr);border-top:1px solid var(--line);
  border-bottom:1px solid var(--line);margin:12px 0 8px}}
.kpi-6 .cell{{padding:14px 6px;text-align:center;border-right:1px solid var(--line)}}
.kpi-6 .cell:last-child{{border-right:none}}
.kpi-6 .v{{font-size:22px;font-weight:800}}
.kpi-6 .l{{font-size:12px;color:var(--muted);margin-top:4px}}

/* Paper / Roast blocks */
.paper-head{{display:flex;gap:14px;align-items:center;padding:12px;border-left:4px solid #a77a4a;
  background:var(--panel-2);border-radius:12px;border:1px solid var(--chip-bd)}}
.sub-card{{background:var(--panel-2);border:1px solid var(--chip-bd);border-radius:12px;padding:16px}}
.roast-body{{background:var(--panel-2);border:1px solid var(--chip-bd);border-radius:12px;padding:16px;line-height:1.65}}

/* Note */
.note{{margin:0 0 10px;background:var(--chip);border:1px solid var(--chip-bd);border-radius:10px;padding:10px 12px;font-size:14px;color:var(--fg)}}

/* Overlay */
.eval-overlay{{position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:9999;display:flex;align-items:center;justify-content:center}}
.eval-modal{{width:560px;max-width:92vw;background:#111827;color:#e5e7eb;border-radius:14px;border:1px solid #374151;
  box-shadow:0 20px 80px rgba(0,0,0,.35)}}
.eval-modal-header{{padding:18px 20px;border-bottom:1px solid #374151;display:flex;align-items:center;justify-content:space-between}}
.eval-modal-title{{font-size:22px;font-weight:800}}
.eval-steps{{max-height:360px;overflow-y:auto;padding:8px 20px 18px}}
.eval-step{{display:flex;align-items:center;gap:10px;padding:10px 0;font-size:14px;border-bottom:1px dashed rgba(255,255,255,.06)}}
.eval-step:last-child{{border-bottom:none}}
.eval-dot{{width:10px;height:10px;border-radius:999px;background:#4b5563}}
.eval-step.done .eval-dot{{background:#10b981}}
.eval-step.active .eval-dot{{background:#60a5fa}}
</style>
    """, unsafe_allow_html=True)

# ========== 流程弹窗 ==========
def _render_analyzing_overlay(steps, active_idx:int)->str:
    items=[]
    for i,txt in enumerate(steps):
        state="done" if i<active_idx else ("active" if i==active_idx else "")
        items.append(f'<div class="eval-step {state}"><div class="eval-dot"></div><div>{txt}</div></div>')
    return (
      '<div class="eval-overlay"><div class="eval-modal">'
      '<div class="eval-modal-header"><div class="eval-modal-title">Analyzing</div><div>✖</div></div>'
      f'<div class="eval-steps">{"".join(items)}</div></div></div>'
    )

# ========== 基础条形（用于 Character）==========
def character_bar(label_left:str, label_right:str, position_ratio:float)->None:
    p = max(0.0, min(1.0, float(position_ratio or 0)))
    st.markdown(f"""
<div class="char-row">
  <div class="char-label">{label_left}</div>
  <div class="char-track"><div class="char-thumb" style="left:{p*100:.2f}%"></div></div>
  <div class="char-label" style="text-align:right">{label_right}</div>
</div>
""", unsafe_allow_html=True)

# ========== Researcher Character（整卡）==========
def researcher_character_card(character: dict, summary: str) -> None:
    t = _clamp01(character.get("theoretical_vs_applied", 0.5))
    d = _clamp01(character.get("depth_vs_breadth", 0.5))
    i = _clamp01(character.get("independent_vs_team", 0.5))

    html = f"""
<div class="te-card">
  <div class="card-head">
    <div class="card-title"><span class="ico">🔎</span>Researcher Character</div>
  </div>

  <div class="char-row">
    <div class="char-label">Theoretical Research</div>
    <div class="char-track"><div class="char-thumb" style="left:{t*100:.2f}%;"></div></div>
    <div class="char-label" style="text-align:right;">Applied Research</div>
  </div>

  <div class="char-row">
    <div class="char-label">Academic Depth</div>
    <div class="char-track"><div class="char-thumb" style="left:{d*100:.2f}%;"></div></div>
    <div class="char-label" style="text-align:right;">Academic Breadth</div>
  </div>

  <div class="char-row">
    <div class="char-label">Independent Research</div>
    <div class="char-track"><div class="char-thumb" style="left:{i*100:.2f}%;"></div></div>
    <div class="char-label" style="text-align:right;">Team Collaboration</div>
  </div>

  <div class="note" style="margin-top:8px;font-size:16px">{summary}</div>
</div>
"""
    # with st.expander(label="Researcher Character", expanded=True):
    st.markdown(html, unsafe_allow_html=True)


# ========== Representative Paper（整卡）==========
def representative_paper_card(paper: dict) -> None:
    title = paper.get("title", "Representative Paper")
    pid = paper.get("id", "")
    citations = paper.get("citations", 0)
    author_pos = paper.get("author_position", "-")
    m = paper.get("mention", {})
    m_title = m.get("title", "")
    m_date = m.get("date", "")
    m_sum = m.get("summary", "")

    st.markdown(f"""
<div class="te-card equal">
  <div class="card-head">
    <div class="card-title"><span class="card-ico">📑</span>Representative Paper</div>
  </div>

  <div class="paper-head">
    <div style="width:40px;height:40px;border-radius:12px;background:#f59e0b33;display:flex;align-items:center;justify-content:center">👤</div>
    <div>
      <div style="font-weight:800;font-size:20px">{pid}</div>
      <div style="font-weight:800;font-size:20px;margin-top:4px">{title}</div>
      <div class="paper-meta">💬 Citations : {citations}&nbsp;&nbsp; ✍️ Author Position : {author_pos}</div>
    </div>
  </div>

  <div class="sub-card" style="margin-top:16px">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
      <div style="font-weight:800">{m_title}</div>
      <div style="opacity:.85">{m_date}</div>
    </div>
    <div>{m_sum}</div>
  </div>
</div>
""", unsafe_allow_html=True)


# ========== Roast（整卡）==========
def roast_card(text: str) -> None:
    st.markdown(f"""
<div class="te-card equal">
  <div class="card-head">
    <div class="card-title"><span class="card-ico">🧯</span>Roast</div>
  </div>

  <div class="roast-body">{text}</div>
</div>
""", unsafe_allow_html=True)


# ========== Papers（整卡：上面 3 KPI + 下方大图）==========
def papers_chart_card(series: list, metrics: dict) -> None:
    T = _theme_tokens()
    years = [str(d.get("year")) for d in series]
    papers = [int(d.get("papers", 0) or 0) for d in series]
    cites  = [int(d.get("citations", 0) or 0) for d in series]
    # Use the actual total from metrics if available, otherwise sum
    tot_papers = int(metrics.get("total_papers", sum(papers)))
    tot_cites = int(metrics.get("total_citations", 56016))  # Default to the provided value
    h_index = int(metrics.get("h_index", 98))

    # 帮助函数：hex 转 rgba 字符串（带透明度）
    def _hex_rgba(hex_color: str, alpha: float) -> str:
        h = hex_color.lstrip('#')
        if len(h) == 3:
            h = ''.join([c*2 for c in h])
        try:
            r = int(h[0:2], 16); g = int(h[2:4], 16); b = int(h[4:6], 16)
        except Exception:
            r, g, b = 124, 58, 237  # fallback
        return f"rgba({r},{g},{b},{alpha})"

    # 构建图表：更清晰的对比色、柔和网格、面积填充
    fig = go.Figure()
    fig.add_bar(
        x=years,
        y=papers,
        name="Papers",
        marker_color=T["bar"],
        marker_line_width=0,
        opacity=0.55,
    )
    # area under citations
    fig.add_trace(
        go.Scatter(
            x=years,
            y=cites,
            mode="lines",
            line=dict(color="rgba(0,0,0,0)", width=0),
            fill="tozeroy",
            fillcolor=_hex_rgba(T["line"], 0.18),
            hoverinfo="skip",
            showlegend=False,
        )
    )
    fig.add_trace(
        go.Scatter(
            x=years,
            y=cites,
            name="Citations",
            mode="lines+markers",
            line=dict(color=T["line"], width=4),
            marker=dict(size=8, color=T["line"]),
        )
    )
    fig.update_xaxes(type="category", showgrid=False)
    ymax = max([0] + papers + cites)
    fig.update_yaxes(
        range=[0, max(100, int(ymax * 1.25))],
        gridcolor=_hex_rgba(T["muted"], 0.18),
        zeroline=False,
        tickformat=",",  # Format large numbers with commas
    )

    # 透明画布 + 主题字体色
    fig.update_layout(
        margin=dict(l=18, r=18, t=10, b=12),
        height=320,
        template=T["plotly_template"],
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0.0),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=T["fg"]),
    )
    fig_html = fig.to_html(include_plotlyjs="cdn", full_html=False,
                           config={"displayModeBar": False})

    # 采用与其它卡片一致的样式（te-card 等），在 iframe 内复刻同名类
    # 并内置 light/dark 两套 CSS 变量，通过 html[data-theme] 切换
    LT = _theme_tokens("light")
    DT = _theme_tokens("dark")
    theme_base = detect_theme_base()
    components.html(f"""
<!doctype html><html data-theme=\"{theme_base}\"><head><meta charset=\"utf-8\" />
<style>
  :root,[data-theme='light']{{
    --fg:{LT['fg']}; --muted:{LT['muted']};
    --panel:{LT['panel']}; --line:{LT['border']};
    --chip:{LT['chip']}; --chip-bd:{LT['chip_bd']}; --brand:{LT['brand']};
  }}
  [data-theme='dark']{{
    --fg:{DT['fg']}; --muted:{DT['muted']};
    --panel:{DT['panel']}; --line:{DT['border']};
    --chip:{DT['chip']}; --chip-bd:{DT['chip_bd']}; --brand:{DT['brand']};
  }}
  * {{ box-sizing: border-box; }}
  body {{ background: transparent; color: var(--fg); margin: 0; font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial; }}
  .te-card{{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:16px;box-shadow:0 10px 28px rgba(0,0,0,.12);color:var(--fg)}}
  .card-head{{display:flex;align-items:center;justify-content:space-between;margin-bottom:12px}}
  .card-title{{display:flex;align-items:center;gap:8px;font-weight:800;font-size:18px}}
  .card-ico{{width:22px;height:22px;display:inline-flex;align-items:center;justify-content:center;border-radius:6px;background:var(--chip);border:1px solid var(--chip-bd)}}
  .kpi-3{{display:grid;grid-template-columns:repeat(3,1fr);gap:18px;margin:6px 0 8px}}
  .kpi-3 .val{{font-size:24px;font-weight:800}}
  .kpi-3 .lab{{font-size:12px;color:var(--muted)}}
  .plot{{padding:0 6px 4px 6px}}
</style></head>
<body>
  <div class=\"te-card\">
    <div class=\"card-head\">
      <div class=\"card-title\"><span class=\"card-ico\">📚</span>Papers</div>
    </div>
    <div class=\"kpi-3\">
      <div style=\"text-align:center\"><div class=\"val\">{tot_papers:,}</div><div class=\"lab\">Total Papers</div></div>
      <div style=\"text-align:center\"><div class=\"val\">{tot_cites:,}</div><div class=\"lab\">Total Citations</div></div>
      <div style=\"text-align:center\"><div class=\"val\">{h_index}</div><div class=\"lab\">H Index</div></div>
    </div>
    <div class=\"plot\">{fig_html}</div>
  </div>
 </body></html>
""", height=450, scrolling=False)


# ========== Insight（整卡：提示 + 6 指标 + 环形图）==========
def insights_card(metrics: dict) -> None:
    T = _theme_tokens()
    tp  = int(metrics.get("total_papers", 0) or 0)
    tt  = int(metrics.get("top_tier_papers", 0) or 0)
    fa  = int(metrics.get("first_author_papers", 0) or 0)
    la  = int(metrics.get("last_author_papers", 0) or 0)
    fac = int(metrics.get("first_author_citations", 0) or 0)
    co  = int(metrics.get("total_coauthors", 0) or 0)

    # 环形：中心文字 + 透明画布，与卡片风格一致
    rest = max(0, tp - tt)
    pie = go.Figure(data=[go.Pie(
        values=[tt, rest],
        hole=0.74,
        marker=dict(colors=[T["ring_fg"], T["ring_bg"]]),
        textinfo="none",
        sort=False
    )])
    pie.update_layout(
        showlegend=False,
        margin=dict(l=10, r=10, t=10, b=10),
        height=240,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=T["fg"]),
        annotations=[
            dict(text=f"<b>{tt}</b><br>Top Tier", x=0.5, y=0.5, showarrow=False, font=dict(size=16, color=T["fg"]))
        ],
    )
    pie_html = pie.to_html(include_plotlyjs="cdn", full_html=False,
                           config={"displayModeBar": False})

    note = st.session_state.get("analysis_scope_note", "Only analyze 500 most influential academic paper.")
    LT = _theme_tokens("light")
    DT = _theme_tokens("dark")
    theme_base = detect_theme_base()
    components.html(f"""
<!doctype html><html data-theme=\"{theme_base}\"><head><meta charset=\"utf-8\" />
<style>
  :root,[data-theme='light']{{
    --fg:{LT['fg']}; --muted:{LT['muted']};
    --panel:{LT['panel']}; --line:{LT['border']};
    --chip:{LT['chip']}; --chip-bd:{LT['chip_bd']}; --brand:{LT['brand']};
  }}
  [data-theme='dark']{{
    --fg:{DT['fg']}; --muted:{DT['muted']};
    --panel:{DT['panel']}; --line:{DT['border']};
    --chip:{DT['chip']}; --chip-bd:{DT['chip_bd']}; --brand:{DT['brand']};
  }}
  * {{ box-sizing: border-box; }}
  body {{ background: transparent; color: var(--fg); margin: 0; font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial; }}
  .te-card{{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:16px;box-shadow:0 10px 28px rgba(0,0,0,.12);color:var(--fg)}}
  .card-head{{display:flex;align-items:center;justify-content:space-between;margin-bottom:12px}}
  .card-title{{display:flex;align-items:center;gap:8px;font-weight:800;font-size:18px}}
  .card-ico{{width:22px;height:22px;display:inline-flex;align-items:center;justify-content:center;border-radius:6px;background:var(--chip);border:1px solid var(--chip-bd)}}
  .note{{margin:0 0 10px;background:var(--chip);border:1px solid var(--chip-bd);border-radius:10px;padding:10px 12px;font-size:14px;color:var(--fg)}}
  .kpi-6{{display:grid;grid-template-columns:repeat(6,1fr);border-top:1px solid var(--line);border-bottom:1px solid var(--line);margin:12px 0 8px}}
  .kpi-6 .cell{{text-align:center;padding:14px 6px;border-right:1px solid var(--line)}}
  .kpi-6 .cell:last-child{{border-right:none}}
  .kpi-6 .v{{font-size:22px;font-weight:800}}
  .kpi-6 .l{{font-size:12px;color:var(--muted);margin-top:4px}}
  .ring{{padding: 6px 6px}}
</style></head>
<body>
  <div class=\"te-card\">
    <div class=\"card-head\">
      <div class=\"card-title\"><span class=\"card-ico\">💡</span>Insight</div>
    </div>
    <div class=\"note\">⚠️ {note}</div>
    <div class=\"kpi-6\">
      <div class=\"cell\"><div class=\"v\">{tp}</div><div class=\"l\">Total Papers</div></div>
      <div class=\"cell\"><div class=\"v\">{tt}</div><div class=\"l\">Top Tier Papers</div></div>
      <div class=\"cell\"><div class=\"v\">{fa}</div><div class=\"l\">First Author Papers</div></div>
      <div class=\"cell\"><div class=\"v\">{fac}</div><div class=\"l\">First Author Citations</div></div>
      <div class=\"cell\"><div class=\"v\">{co}</div><div class=\"l\">Total Coauthors</div></div>
      <div class=\"cell\"><div class=\"v\">{la}</div><div class=\"l\">Last Author Papers</div></div>
    </div>
    <div class=\"ring\">{pie_html}</div>
  </div>
</body></html>
""", scrolling=False, height=480)





def evaluate_resume_link_input(user_input: str):
    # first check if the user_input is a valid url
    if not user_input or not user_input.strip():
        st.warning("Please enter a homepage URL first.")
        st.stop()
    if not user_input.startswith("http"):
        user_input = "https://" + user_input
    
    # check if this is valid url by try to fetch the url
    try:
        response = requests.get(user_input)
        response.raise_for_status()
    except Exception as e:
        print(f"Error evaluating resume link input: {e}")
        st.warning("Please enter a valid homepage URL.")
        st.stop()
    
    return user_input
    
# ------------------------ 页面主渲染（函数名不动） ------------------------

def render_resume_evaluation_page() -> None:
    # 先探测主题，再注入样式
    theme_base = detect_theme_base()
    apply_resume_evaluation_styles(theme_base)

    col1, col2 = st.columns([1, 2])

    # ------- 左侧：输入与分析流程 -------
    with col1:
        st.subheader("Input Method")
        person_link = st.text_input("Enter Person Website Link", placeholder="https://example.github.io")

        # st.subheader("Evaluation Parameters")
        # _ = st.text_area("Role requirements (optional)", placeholder="Describe the role to tailor the evaluation...")

        if st.button("🔍 Evaluate Candidate", type="primary"):
            person_link = evaluate_resume_link_input(person_link)

            steps = [
                "Fetching homepage and subpages...",
                "Extracting profile fields...",
                "Deriving insights and highlights...",
                "Selecting representative papers...",
                "Scoring across 7 dimensions...",
                "Preparing profile view...",
            ]
            overlay = st.empty()
            prog = st.progress(0)
            
            # Map backend events to step index
            event_to_step = {
                "fetching_homepage": 0,
                "starting_extraction": 1,
                "extraction": 1,
                "evaluating_profile": 4,
                "building_overview": 5,
                "finalizing_payload": 5,
                "done": 5,
            }
            
            # Thread-safe progress channel
            progress_q: "queue.Queue[tuple[str, float]]" = queue.Queue()
            result_holder = {"payload": None, "error": None}
            
            def _on_progress(event: str, pct: float) -> None:
                try:
                    progress_q.put((event or "", float(pct or 0.0)))
                except Exception:
                    pass
            
            def _run_eval(api_key: str):
                try:
                    payload = evaluate_homepage_to_candidate_overview(person_link.strip(), author_hint="", api_key=api_key, on_progress=_on_progress)
                    result_holder["payload"] = payload
                except Exception as e:
                    result_holder["error"] = e
                finally:
                    try:
                        progress_q.put(("done", 1.0))
                    except Exception:
                        pass
            
            # Start background evaluation
            api_key = (st.session_state.get("llm_api_key", "") or 
                      st.session_state.get("openai_api_key", "") or None)
            worker = threading.Thread(target=_run_eval, daemon=True, args=(api_key,))
            worker.start()
            
            # Render overlay while consuming progress
            current_step = 0
            overlay.markdown(_render_analyzing_overlay(steps, current_step), unsafe_allow_html=True)
            last_pct = 0
            while worker.is_alive() or not progress_q.empty():
                try:
                    event, pct = progress_q.get(timeout=0.1)
                    # Determine step
                    base_evt = (event or "").split(":", 1)[0]
                    step_idx = event_to_step.get(base_evt, current_step)
                    if step_idx != current_step:
                        current_step = step_idx
                        overlay.markdown(_render_analyzing_overlay(steps, current_step), unsafe_allow_html=True)
                    # Update bar
                    p = max(0, min(100, int((pct or 0.0) * 100)))
                    if p != last_pct:
                        prog.progress(p)
                        last_pct = p
                except queue.Empty:
                    pass
                except Exception:
                    pass
                # small UI yield
                time.sleep(0.05)

            try:
                if not _direct_eval_available:
                    raise RuntimeError("Direct homepage evaluator not available")
                
                # Join worker and read result
                worker.join(timeout=0.1)
                if result_holder["error"] is not None:
                    raise result_holder["error"]
                profile_payload = result_holder["payload"]
                if not isinstance(profile_payload, dict):
                    raise RuntimeError("Evaluation did not return payload")

                # Store for candidate profile subpage
                st.session_state["candidate_overview"] = profile_payload
                st.session_state["demo_candidate_overview_json"] = json.dumps(profile_payload)

                # Minimal container data for this page’s legacy visuals
                st.session_state["resume_eval_v2"] = {
                    "candidate": {"name": profile_payload.get("name", "")},
                    "character": {},
                    "metrics": {},
                    "notes": {"analysis_scope": "Homepage-driven profile extraction."},
                    "time_series": [],
                    "representative_paper": {"mention": {}},
                }
                st.session_state["analysis_scope_note"] = "Homepage-driven profile extraction."
                overlay.empty()
                # st.toast("Evaluation complete!", icon="✅")
            except Exception as e:
                overlay.empty()
                st.error(f"Error during homepage evaluation: {e}")
                st.stop()

    # ------- 右侧：单列竖排 Card -------
    with col2:
        col2_header1, col2_header2 = st.columns([3, 1])
        
        with col2_header1:
            st.subheader("Evaluation Results")
        
        with col2_header2:
            if st.button("Full Screen", type="primary", use_container_width=True):
                # Store previous page for back navigation
                st.session_state["prev_page"] = st.session_state.get("current_page", "📄 Resume Evaluation")
                # Navigate to candidate profile page
                st.session_state.current_page = "🧑 Candidate Profile"
                st.session_state.page_changed = True
                st.rerun()

        data = st.session_state.get("resume_eval_v2")
        if not data:
          st.markdown("""
            <div class="st-info" style="
                background-color: rgb(238, 246, 255); 
                color: rgb(0, 51, 102); 
                padding: 1rem; 
                border-radius: 0.5rem; 
                border: 1px solid rgb(179, 219, 255);
            ">
                Enter at left side and click <strong>Evaluate Candidate</strong> to preview
            </div>
            """, unsafe_allow_html=True)
          return
        candidate_data = st.session_state.get("candidate_overview")
        render_candidate_profile_page(candidate_data, include_back_button=False)


