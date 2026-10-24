"""Overturn — denied claims, recovered. All local, all offline."""
import difflib
import html
import json
import re
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
# Streamlit's module watcher can purge overturn.* from sys.modules mid-import
# on save; retry briefly to ride out the race.
import time as _t
for _attempt in range(5):
    try:
        from overturn import db, llm  # noqa: E402
        from overturn.export import letter_to_docx  # noqa: E402
        from overturn.pipeline import (  # noqa: E402
            list_sample_cases,
            load_sample,
            run_pipeline,
        )
        from overturn.redact import re_identify  # noqa: E402
        break
    except KeyError:
        _t.sleep(0.3)
else:
    raise ImportError("could not import overturn package")

st.set_page_config(
    page_title="Overturn",
    page_icon=str(Path(__file__).resolve().parent / "assets" / "logo.png"),
    layout="wide",
)

# ---------------------------------------------------------------- styles
st.markdown(
    """
<style>
html, body, [data-testid="stAppViewContainer"], .stApp {
    background-color: #f4f6f8;
    font-family: 'Avenir Next', 'Segoe UI', system-ui, sans-serif;
}
[data-testid="stHeader"] { background: transparent; }
h1, h2, .ot-serif { font-family: 'DM Serif Display', Georgia, serif !important;
                    color: #3c4f63 !important; letter-spacing: 0.2px; }
h3 { color: #3c4f63 !important; }
p, label, .stMarkdown { color: #41566b; }

/* sidebar */
[data-testid="stSidebar"] { background: #e9edf1; border-right: 1px solid #d8e0e7; }
[data-testid="stSidebar"] h1, [data-testid="stSidebar"] p,
[data-testid="stSidebar"] label { color: #41566b; }

/* cards */
.ot-card {
    background: #fcfdfe;
    border: 1px solid #dde4ea;
    border-radius: 18px;
    padding: 20px 24px;
    box-shadow: 0 1px 3px rgba(31,52,45,.06);
    margin-bottom: 16px;
}
.ot-card-active { border: 1.5px solid #3c4f63; }
.ot-muted { color: #7d8a99; }
.ot-big { font-size: 28px; font-weight: 700; color: #3c4f63; }
.ot-title { font-family: 'DM Serif Display', Georgia, serif; font-size: 32px;
            color: #3c4f63; margin: 4px 0 12px 0; }
.ot-chip {
    display: inline-block; background: #e2e7ec; color: #54677c;
    border-radius: 8px; padding: 3px 10px; font-size: 12.5px; font-weight: 600;
    margin-right: 6px;
}
.ot-badge {
    display: inline-block; border-radius: 999px; padding: 4px 14px;
    font-size: 12.5px; font-weight: 600;
}
.b-denied   { background: #e9d6d1; color: #7d4a3c; }
.b-review   { background: #dfe7ee; color: #42566a; }
.b-appeal   { background: #3c4f63; color: #f4f6f8; }
.b-fix      { background: #e8e2cc; color: #776f42; }
.b-noappeal { background: #e4e7ea; color: #5c6673; }
.b-won      { background: #d4e0da; color: #3a5f48; }
.b-lost     { background: #e6cfd2; color: #7d4750; }
.b-draft    { background: #dde4ec; color: #3c4f63; }

/* metric bars */
.ot-metric-row { display:flex; justify-content:space-between; align-items:center;
                 margin: 10px 0 4px 0; font-size: 14.5px; }
.ot-bar { height: 7px; border-radius: 4px; margin-top: 2px; }

/* buttons */
.stButton > button, .stDownloadButton > button {
    border-radius: 999px !important; font-weight: 600 !important;
}
.stButton > button[kind="primary"], .stDownloadButton > button {
    background: #3c4f63 !important; color: #f4f6f8 !important; border: none !important;
}
.stButton > button[kind="secondary"] {
    background: transparent !important; color: #3c4f63 !important;
    border: 1.5px solid #3c4f63 !important;
}

/* tabs */
.stTabs [data-baseweb="tab-list"] { gap: 8px; }
.stTabs [data-baseweb="tab"] {
    background: #e9edf1; border-radius: 999px; padding: 6px 18px;
}
.stTabs [aria-selected="true"] { background: #3c4f63 !important; color: #f4f6f8 !important; }
.stTabs [aria-selected="true"] p { color: #f4f6f8 !important; }

/* radio as nav */
[data-testid="stSidebar"] .stRadio div[role="radiogroup"] label {
    background: transparent; border-radius: 12px; padding: 8px 14px; width: 100%;
}
[data-testid="stSidebar"] .stRadio div[role="radiogroup"] label:has(input:checked) {
    background: #3c4f63;
}
[data-testid="stSidebar"] .stRadio div[role="radiogroup"] label:has(input:checked) p {
    color: #f4f6f8 !important;
}
[data-testid="stSidebar"] .stRadio div[role="radiogroup"] label > div:first-child { display: none; }

/* dataframe */
[data-testid="stDataFrame"] { background: #fcfdfe; border-radius: 14px;
    border: 1px solid #dde4ea; padding: 6px; }
mark { background: #dfe7ee; color: #42566a; border-radius: 4px; padding: 0 3px; }

/* inline diff (approval) */
.df { font-family: ui-monospace, 'SF Mono', Menlo, monospace; font-size: 12.5px;
      max-height: 280px; overflow-y: auto; }
.df-del { background: #e9d6d1; color: #7d4a3c; padding: 1px 8px; border-radius: 6px; }
.df-add { background: #dfe7ee; color: #42566a; padding: 1px 8px; border-radius: 6px; }
.df-skip { color: #7d8a99; padding: 1px 8px; font-style: italic; }
.ot-receipt {
    background: #dfe7ee; color: #42566a; border: 1px solid #c2ced9;
    border-radius: 999px; padding: 8px 18px; font-size: 13px; font-weight: 600;
    display: inline-block;
}
</style>
""",
    unsafe_allow_html=True,
)

_PLACEHOLDER_RE = re.compile(r"<[A-Z]+_\d+>")

STATUS_META = {
    "denied":       ("Denied", "b-denied"),
    "appeal_ready": ("Awaiting HITL Review", "b-review"),
    "fix_resubmit": ("Fix & Resubmit", "b-fix"),
    "no_appeal":    ("Do Not Appeal", "b-noappeal"),
    "appealed":     ("Appeal Submitted", "b-appeal"),
    "won":          ("Recovered", "b-won"),
    "lost":         ("Appeal Lost", "b-lost"),
}

REVIEWERS = ["Anderson Memorial", "Riverbend Billing Co.", "Unassigned"]
SPECIALISTS = ["Sarah Jenkins", "Marcus Webb", "Priya Patel", "Unassigned"]


def badge(status: str) -> str:
    label, cls = STATUS_META.get(status, (status, "b-noappeal"))
    return f'<span class="ot-badge {cls}">{label}</span>'


def action_badge(action: str) -> str:
    cls = {"APPEAL": "b-appeal", "FIX_AND_RESUBMIT": "b-fix", "DO_NOT_APPEAL": "b-noappeal"}
    return f'<span class="ot-badge {cls.get(action, "b-noappeal")}">{action.replace("_", " ")}</span>'


def highlight_placeholders(text: str) -> str:
    escaped = html.escape(text).replace("\n", "<br>")
    return _PLACEHOLDER_RE.sub(lambda m: f"<mark>{m.group(0)}</mark>", escaped)


def resolution_text(case: dict) -> str:
    if case.get("action") == "APPEAL":
        return "Formal appeal letter — drafted"
    if case.get("action") == "FIX_AND_RESUBMIT":
        return "Correct and resubmit at supported level"
    if case.get("status") == "won":
        return "Recovered on appeal"
    return "No action recommended"


# ---------------------------------------------------------------- embeds
_ASSETS = Path(__file__).resolve().parent / "overturn" / "assets"


@st.cache_data(show_spinner=False)
def _hairline_src() -> str:
    return (_ASSETS / "hairline.js").read_text()


def hairline(figure: str = "riffle", height: int = 240, intensity: float = 0.55):
    """Pointer-reactive isometric figure (@lucasmarkes/hairline), themed to palette."""
    st.iframe(
        f"""<div id="hl" style="height:{height - 12}px;border-radius:14px;
            --hairline-plate:#fcfdfe;--hairline-hi:#3c4f63;--hairline-edge:#8a947f;
            --hairline-mid:#b9bfa8;--hairline-lo:#e2e7ec"></div>
        <script type="module">{_hairline_src()}
        const fig = {figure}(document.getElementById('hl'),
            {{intensity:{intensity}, theme:'light', play:true}});
        </script>""",
        height=height,
    )


# Port of ns-ui "airlift-slug-flow": air slugs rise through a conduit every
# 1.8s at 140px/s, dragging a liquid plug into the accumulator basin.
_AIRLIFT_HTML = """
<canvas id="al" width="48" height="300" style="display:block;margin:0 auto"></canvas>
<script>
const cv = document.getElementById('al'), x = cv.getContext('2d');
const W = 48, H = 300, CX = 24, RW = 10, TOP = 30, BOT = H - 6, SPEED = 140;
let slugs = [], basin = 0, last = performance.now(), lastInject = 0;
function rr(y, w, h, r) {
  x.beginPath(); x.roundRect(CX - w / 2, y, w, h, r); x.fill();
}
function tick(t) {
  const dt = (t - last) / 1000; last = t;
  if (t - lastInject > 1800) { slugs.push(BOT); lastInject = t; }
  for (let i = slugs.length - 1; i >= 0; i--) {
    slugs[i] -= SPEED * dt;
    if (slugs[i] - 18 < TOP) { slugs.splice(i, 1); basin = Math.min(basin + 1, 10); }
  }
  x.clearRect(0, 0, W, H);
  x.strokeStyle = '#b9bfa8'; x.lineWidth = 1.5;
  x.beginPath(); x.roundRect(CX - RW / 2, TOP, RW, H - TOP - 4, 5); x.stroke();
  // accumulator basin
  x.strokeStyle = '#8a947f';
  x.beginPath(); x.roundRect(CX - 14, 6, 28, 20, 5); x.stroke();
  if (basin) {
    x.fillStyle = '#5c7a8f';
    x.beginPath(); x.roundRect(CX - 12, 24 - 1.6 * basin, 24, 1.6 * basin, 3); x.fill();
  }
  for (const y of slugs) {
    x.fillStyle = '#5c7a8f'; rr(y - 16, 9, 13, 4);   // liquid plug
    x.fillStyle = '#3c4f63'; rr(y - 3, 7, 10, 3);    // air slug
  }
  requestAnimationFrame(tick);
}
requestAnimationFrame(tick);
</script>
"""


def claims_coverflow(cases: list[dict], height: int = 470):
    """Claims as coverflow 'field notes' — vanilla port of ns-ui CausticCoverflow."""
    src = (_ASSETS / "coverflow.html").read_text()
    items = [
        {
            "title": c.get("payer") or c["name"] or "Claim",
            "meta": f"{c.get('carc_code') or '—'} · #{c['id']:05d} · "
            f"{STATUS_META.get(c['status'], (c['status'],))[0].upper()}",
            "amount": f"${(c.get('claim_amount') or 0):,.0f}",
            "seed": c["id"] * 7 + 3,
        }
        for c in cases
    ]
    st.iframe(src.replace("__ITEMS__", json.dumps(items)), height=height)


def electric_arc(text: str, href: str | None = None, height: int = 95):
    """ns-ui border-electric-arc port: crackling border on a CTA or live panel."""
    src = (_ASSETS / "electric_arc.html").read_text()
    if href:
        inner = f'<a class="btn" href="{href}" target="_top">{html.escape(text)}</a>'
    else:
        inner = f'<div class="btn static">{html.escape(text)}</div>'
    st.iframe(src.replace("__INNER__", inner), height=height)


def inline_diff(old: str, new: str) -> str:
    """Line-level old→new diff as styled HTML (ns-ui approval-inline-diff port)."""
    if old == new:
        return ""
    sm = difflib.SequenceMatcher(None, old.splitlines(), new.splitlines())
    parts = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            if parts and (i1, i2) != (0, 0):
                parts.append('<div class="df-skip">· · ·</div>')
            continue
        for ln in old[i1:i2]:
            parts.append(f'<div class="df-del">− {html.escape(ln)}</div>')
        for ln in new[j1:j2]:
            parts.append(f'<div class="df-add">+ {html.escape(ln)}</div>')
    return "".join(parts)


db.migrate()
db.seed_if_empty()
ollama_up = llm.is_available()

def _render_case_detail(case: dict):
    info = json.loads(case["denial_info_json"]) if case.get("denial_info_json") else {}
    ev = json.loads(case["evidence_json"]) if case.get("evidence_json") else []
    st.markdown(
        f"""<div class="ot-card ot-card-active" style="margin-top:8px">
        <span class="ot-chip">DENIED CLAIM #{case['id']:05d}</span>
        <span class="ot-chip">{html.escape(case.get('carc_code') or '—')}</span>
        <div class="ot-title">{html.escape(case['name'] or 'Claim')}</div>
        <span class="ot-chip">Primary Payer: {html.escape(case.get('payer') or '—')}</span>
        {badge(case['status'])}
        <div class="ot-muted" style="margin-top:8px">{html.escape(info.get('denial_reason_text',''))}</div>
        </div>""",
        unsafe_allow_html=True,
    )
    c1, c2 = st.columns([2, 1])
    with c1:
        st.markdown("**Proposed resolution**")
        st.markdown(
            f'<div class="ot-card" style="padding:14px">'
            f'{action_badge(case.get("action") or "")}<br><br>'
            f'<b>{html.escape(resolution_text(case))}</b><br>'
            f'<span class="ot-muted">Winnability score: {case.get("score") or "—"}/100 · '
            f'Suggested payer action: {html.escape(case.get("payer") or "—")} (re-submission)</span>'
            f'</div>',
            unsafe_allow_html=True,
        )
        if ev:
            with st.expander("Chart evidence"):
                for e in ev:
                    icon = "✅" if e.get("supports") else "❌"
                    st.markdown(f'{icon} {e.get("fact","")} — *"{e.get("quote_from_note","")}"*')
    with c2:
        st.markdown("**Assign to**")
        st.markdown('<span class="ot-chip">HITL approval required</span>', unsafe_allow_html=True)
        reviewer = st.selectbox("Reviewer", REVIEWERS,
                                index=REVIEWERS.index(case.get("reviewer") or "Unassigned")
                                if (case.get("reviewer") or "Unassigned") in REVIEWERS else len(REVIEWERS) - 1,
                                key=f"rev_{case['id']}")
        assignee = st.selectbox("Claims Specialist", SPECIALISTS,
                                index=SPECIALISTS.index(case.get("assignee") or "Unassigned")
                                if (case.get("assignee") or "Unassigned") in SPECIALISTS else len(SPECIALISTS) - 1,
                                key=f"asg_{case['id']}")
        bc1, bc2 = st.columns(2)
        if bc1.button("Approve & Resubmit", key=f"appr_{case['id']}", type="primary"):
            db.update_status(case["id"], "appealed")
            db.update_assignment(case["id"], reviewer, assignee)
            st.toast("Marked as appeal submitted")
            st.rerun()
        if bc2.button("Reassign", key=f"reas_{case['id']}"):
            db.update_assignment(case["id"], reviewer, assignee)
            st.toast("Assignment updated")

    if case.get("letter"):
        with st.expander("📄 Appeal draft"):
            st.text(case["letter"])
            st.download_button(
                "Download .docx",
                data=letter_to_docx(case["letter"]),
                file_name=f"appeal_case_{case['id']}.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                key=f"dl_{case['id']}",
            )




# ---------------------------------------------------------------- sidebar
with st.sidebar:
    c_logo, c_name = st.columns([1, 2])
    with c_logo:
        st.image(str(Path(__file__).resolve().parent / "assets" / "logo.svg"), width=64)
    with c_name:
        st.markdown(
            '<div class="ot-serif" style="font-size:26px;margin:8px 0 2px 0">Overturn</div>'
            '<div class="ot-muted" style="font-size:12.5px">'
            "Denied claims, recovered — all local.</div>",
            unsafe_allow_html=True,
        )
    st.markdown('<div style="height:10px"></div>', unsafe_allow_html=True)
    PAGES = ["Overview", "Review Queue", "New Claim", "Settings"]
    default = PAGES.index("New Claim") if st.query_params.get("page") == "new" else 0
    st.query_params.clear()
    nav = st.radio("nav", PAGES, index=default, label_visibility="collapsed")
    st.divider()
    if ollama_up:
        st.caption("🟢 Local model connected — 0 bytes leave this machine")
    else:
        st.caption("🔴 Ollama offline — cached-sample mode")


# ================================================================ OVERVIEW
if nav == "Overview":
    c_title, c_cta = st.columns([4, 1])
    with c_title:
        st.markdown('<div class="ot-serif" style="font-size:30px">Claims Resolution Dashboard</div>',
                    unsafe_allow_html=True)
        st.caption("🔒 Local model: `localhost:11434` — **0 bytes of patient data sent externally.**")
    with c_cta:
        electric_arc("⚡ New Claim", href="?page=new", height=96)

    stats = db.dashboard_stats()
    cases = db.list_cases()
    awaiting = sum(1 for c in cases if c["status"] == "appeal_ready")

    with st.container(border=True):
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Denied claims", stats["n_cases"])
        c2.metric("Denied $", f"${stats['total_denied']:,.0f}")
        c3.metric("Recovered $", f"${stats['won_amt']:,.0f}")
        c4.metric("Projected recovery", f"${stats['projected']:,.0f}")
        c5.metric("Awaiting review", awaiting)

    if cases:
        claims_coverflow(cases)

    st.markdown("#### All claims")
    if not cases:
        st.info("No claims yet — hit **New Claim** to analyze a denial.")
    else:
        flt = st.multiselect(
            "Filter by status",
            list(STATUS_META.keys()),
            default=[],
            format_func=lambda s: STATUS_META[s][0],
        )
        view = [c for c in cases if not flt or c["status"] in flt]
        df = pd.DataFrame(view)[
            ["id", "name", "payer", "category", "carc_code", "claim_amount", "score", "action", "status"]
        ]
        df["status"] = df["status"].map(lambda s: STATUS_META.get(s, (s,))[0])
        event = st.dataframe(
            df, hide_index=True, width='stretch',
            on_select="rerun", selection_mode="single-row",
        )
        selected = event.selection.rows if event and event.selection else []
        if selected:
            case = db.get_case(int(df.iloc[selected[0]]["id"]))
            _render_case_detail(case)

    c_chart, c_met = st.columns([2, 1])
    with c_chart:
        st.markdown("#### Denied $ by category")
        if stats["by_category"]:
            st.bar_chart(pd.DataFrame({"amount": stats["by_category"]}).rename_axis("category"),
                         color="#3c4f63")
    with c_met:
        total = max(stats["n_cases"], 1)
        auto = sum(1 for c in cases if c.get("action") == "APPEAL")
        st.markdown(
            f"""<div class="ot-card">
            <div style="font-weight:700;margin-bottom:8px">Resolution Metrics</div>
            <div class="ot-metric-row"><span>Total Denied</span><b>{stats['n_cases']}</b></div>
            <div class="ot-bar" style="background:#a8897a;width:100%"></div>
            <div class="ot-metric-row"><span>Auto-Drafted</span><b>{auto}</b></div>
            <div class="ot-bar" style="background:#5c7a8f;width:{min(100, auto/total*100):.0f}%"></div>
            <div class="ot-metric-row"><span>Awaiting HITL Review</span><b>{awaiting}</b></div>
            <div class="ot-bar" style="background:#776f42;width:{min(100, awaiting/total*100):.0f}%"></div>
            <div class="ot-muted" style="margin-top:10px;font-size:12px">
            Recovered to date: ${stats['won_amt']:,.0f}</div>
            </div>""",
            unsafe_allow_html=True,
        )


# ================================================================ RESOLUTIONS
elif nav == "Review Queue":
    st.markdown('<div class="ot-serif" style="font-size:30px">Review Queue</div>',
                unsafe_allow_html=True)
    st.caption("Drafted appeals and resubmissions waiting for a human to sign off.")
    cases = [c for c in db.list_cases() if c["status"] in ("appeal_ready", "fix_resubmit", "denied")
             and c.get("action") in ("APPEAL", "FIX_AND_RESUBMIT")]
    if not cases:
        st.info("Nothing awaiting review. Run a new case — appeals land here for human sign-off.")
    for case in cases:
        with st.expander(
            f"#{case['id']:05d} · {case['name']} — ${case['claim_amount']:,.0f} · "
            f"{STATUS_META.get(case['status'], ('',))[0]}"
        ):
            _render_case_detail(case)


# ================================================================ NEW CASE
elif nav == "New Claim":
    st.markdown('<div class="ot-serif" style="font-size:30px">New Claim</div>',
                unsafe_allow_html=True)
    st.caption("🔒 Local model: `localhost:11434` — **0 bytes of patient data sent externally.**")

    tab_up, tab_priv, tab_an, tab_ap = st.tabs(["📤 Upload", "🛡️ Privacy", "📊 Analysis", "✉️ Appeal"])

    with tab_up:
        samples = list_sample_cases()
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("Denial letter")
            denial_file = st.file_uploader(
                "PDF, photo, or text", type=["pdf", "png", "jpg", "jpeg", "txt"], key="denial"
            )
        with c2:
            st.subheader("Visit note")
            note_file = st.file_uploader(
                "PDF, photo, or text", type=["pdf", "png", "jpg", "jpeg", "txt"], key="note"
            )
        sample = st.selectbox("…or load a sample case", ["(none)"] + samples)
        models = llm.list_models() or [llm.DEFAULT_MODEL]
        model = st.selectbox("Model", models)

        if st.button("Analyze case", type="primary",
                     disabled=not (denial_file and note_file) and sample == "(none)"):
            from overturn.ingest import extract_text

            with st.spinner("Extracting text…"):
                if sample != "(none)":
                    denial_text, note_text = load_sample(sample)
                else:
                    denial_text = extract_text(denial_file.getvalue(), denial_file.name)
                    note_text = extract_text(note_file.getvalue(), note_file.name)
            try:
                with st.container(border=True):
                    gyremote("searching", size=72,
                             label="Local model working — data stays on this machine")
                prog = st.status("Running pipeline…", expanded=True)
                with prog:
                    result = run_pipeline(
                        denial_text, note_text, model=model, on_step=st.write
                    )
                prog.update(label="Analysis complete", state="complete")
                st.session_state["result"] = result
                st.session_state["edited_letter"] = result.letter
                if result.used_fallback:
                    st.warning("Ollama offline — showing cached analysis for this sample case.")
                st.success("Done — check Privacy, Analysis, and Appeal.")
            except Exception as e:
                st.error(f"Pipeline failed: {e}")

        res = st.session_state.get("result")
        if res and res.display_info:
            st.markdown(
                f'<div class="ot-card"><b>{html.escape(res.display_info.payer)}</b>'
                f' · ${res.display_info.claim_amount:,.2f} · {res.display_info.carc_code}'
                f' ({res.display_info.category})</div>',
                unsafe_allow_html=True,
            )

    with tab_priv:
        res = st.session_state.get("result")
        if not res:
            st.info("Analyze a case first.")
        else:
            st.caption("What the model sees vs. what was uploaded — PHI is stripped first.")
            doc = st.radio("Document", ["Denial letter", "Visit note"], horizontal=True)
            orig = res.denial_text if doc == "Denial letter" else res.note_text
            red = res.redacted_denial if doc == "Denial letter" else res.redacted_note
            c1, c2 = st.columns(2)
            for col, title, body in (
                (c1, "**Original**", html.escape(orig).replace("\n", "<br>")),
                (c2, "**Redacted (sent to local LLM)**", highlight_placeholders(red)),
            ):
                with col:
                    st.markdown(title)
                    st.markdown(
                        f'<div class="ot-card" style="max-height:480px;overflow-y:auto;font-size:13px">{body}</div>',
                        unsafe_allow_html=True,
                    )
            with st.expander(f"Redaction vault — {len(res.vault)} placeholders (never leaves this machine)"):
                st.dataframe(
                    pd.DataFrame([{"placeholder": k, "real value": v} for k, v in res.vault.items()]),
                    hide_index=True, width='stretch',
                )

    with tab_an:
        res = st.session_state.get("result")
        if not res:
            st.info("Analyze a case first.")
        else:
            info = res.display_info
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Payer", info.payer)
            c2.metric("Denied amount", f"${info.claim_amount:,.2f}")
            c3.metric("Category", info.category.replace("_", " "))
            c4.metric("CARC", info.carc_code or "—")
            st.divider()
            c1, c2 = st.columns([1, 2])
            with c1:
                st.markdown('<div class="ot-card">', unsafe_allow_html=True)
                st.markdown("**Winnability**")
                st.progress(res.scoring.score / 100)
                st.markdown(f'<div class="ot-big">{res.scoring.score}/100</div>', unsafe_allow_html=True)
                st.markdown(action_badge(res.scoring.action), unsafe_allow_html=True)
                st.caption(info.denial_reason_text)
                st.markdown("</div>", unsafe_allow_html=True)
            with c2:
                st.markdown("**Evidence from the chart**")
                if res.evidence:
                    st.dataframe(
                        pd.DataFrame(
                            [{
                                "supports": "✅" if e.supports else "❌",
                                "fact": re_identify(e.fact, res.vault),
                                "chart quote": f'"{re_identify(e.quote_from_note, res.vault)}"',
                            } for e in res.evidence]
                        ),
                        hide_index=True, width='stretch',
                    )
                else:
                    st.warning("No chart evidence found.")
                with st.expander("How the score was computed"):
                    for r in res.scoring.reasons:
                        st.markdown(f"- {r}")

    with tab_ap:
        res = st.session_state.get("result")
        if not res:
            st.info("Analyze a case first.")
        elif res.scoring.action != "APPEAL":
            st.warning(f"Recommended action is **{res.scoring.action.replace('_',' ')}** — no appeal letter was generated.")
        else:
            already = (
                res.case_id and (db.get_case(res.case_id) or {}).get("status") == "appealed"
            )
            if already or st.session_state.get(f"receipt_{res.case_id}"):
                # ns-ui approval-inline-diff: decided rows collapse to a receipt
                st.markdown(
                    f'<div class="ot-receipt">✓ Approved — appeal submitted · '
                    f'#{res.case_id:05d} · ${res.display_info.claim_amount:,.0f} · '
                    f'{html.escape(res.display_info.payer)}</div>',
                    unsafe_allow_html=True,
                )
            else:
                show_redacted = st.toggle("Show redacted version (what the LLM wrote)", value=False)
                if show_redacted:
                    st.code(res.letter_redacted, language=None)
                letter = st.text_area(
                    "Appeal letter (editable before sending)",
                    value=st.session_state.get("edited_letter", res.letter),
                    height=420,
                )
                diff = inline_diff(res.letter, letter)
                if diff:
                    st.markdown("**Changes vs generated draft**")
                    st.markdown(f'<div class="ot-card df">{diff}</div>', unsafe_allow_html=True)
                c1, c2, c3 = st.columns(3)
                if c1.button("💾 Save edits"):
                    st.session_state["edited_letter"] = letter
                    if res.case_id:
                        db.update_letter(res.case_id, letter)
                    st.toast("Saved")
                c2.download_button(
                    "⬇️ Download .docx",
                    data=letter_to_docx(st.session_state.get("edited_letter", letter)),
                    file_name="appeal_letter.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
                if res.case_id:
                    if c3.button("Approve & Resubmit", type="primary"):
                        db.update_status(res.case_id, "appealed")
                        st.session_state[f"receipt_{res.case_id}"] = True
                        st.rerun()


# ================================================================ SETTINGS
elif nav == "Settings":
    st.markdown('<div class="ot-serif" style="font-size:30px">Settings</div>',
                unsafe_allow_html=True)
    st.markdown("**Local model**")
    st.code(f"Ollama: {llm.HOST} — {'connected' if ollama_up else 'offline'}")
    models = llm.list_models()
    st.write("Installed models:", ", ".join(models) if models else "none")
    if ollama_up and st.button("Warm up model"):
        with st.spinner("Loading…"):
            llm.warmup(models[0] if models else llm.DEFAULT_MODEL)
        st.toast("Model loaded")
    st.divider()
    st.markdown("**Demo data**")
    c1, c2 = st.columns(2)
    if c1.button("Seed 20 synthetic cases"):
        db.seed_if_empty()
        st.toast("Seeded")
    st.caption("Sample cases live in `data/samples/` — all synthetic, no real PHI.")
