"""Overturn — denied claims, recovered. All local, all offline."""
import html
import json
import re
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
from overturn import db, llm  # noqa: E402
from overturn.export import letter_to_docx  # noqa: E402
from overturn.pipeline import list_sample_cases, load_sample, run_pipeline  # noqa: E402
from overturn.redact import re_identify  # noqa: E402

st.set_page_config(page_title="Overturn", page_icon="⚖️", layout="wide")

# ---------------------------------------------------------------- styles
st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=Inter:wght@400;500;600;700&display=swap');

html, body, [data-testid="stAppViewContainer"], .stApp {
    background-color: #f3efe4;
    font-family: 'Inter', sans-serif;
}
[data-testid="stHeader"] { background: transparent; }
h1, h2, .ot-serif { font-family: 'DM Serif Display', Georgia, serif !important;
                    color: #1f342d !important; letter-spacing: 0.2px; }
h3 { color: #1f342d !important; }
p, label, .stMarkdown { color: #24352e; }

/* sidebar */
[data-testid="stSidebar"] { background: #ece6d5; border-right: 1px solid #ddd5c0; }
[data-testid="stSidebar"] h1, [data-testid="stSidebar"] p,
[data-testid="stSidebar"] label { color: #24352e; }

/* cards */
.ot-card {
    background: #fcf9f1;
    border: 1px solid #e3dccb;
    border-radius: 18px;
    padding: 20px 24px;
    box-shadow: 0 1px 3px rgba(31,52,45,.06);
    margin-bottom: 16px;
}
.ot-card-active { border: 1.5px solid #1c453a; }
.ot-muted { color: #7d8a80; }
.ot-big { font-size: 28px; font-weight: 700; color: #1f342d; }
.ot-title { font-family: 'DM Serif Display', Georgia, serif; font-size: 32px;
            color: #1f342d; margin: 4px 0 12px 0; }
.ot-chip {
    display: inline-block; background: #e6e0cd; color: #4d5f55;
    border-radius: 8px; padding: 3px 10px; font-size: 12.5px; font-weight: 600;
    margin-right: 6px;
}
.ot-badge {
    display: inline-block; border-radius: 999px; padding: 4px 14px;
    font-size: 12.5px; font-weight: 600;
}
.b-denied   { background: #f2d4c8; color: #8c4a2f; }
.b-review   { background: #d8e4d2; color: #2f5d40; }
.b-appeal   { background: #1c453a; color: #f3efe4; }
.b-fix      { background: #efe0b8; color: #8a6d1f; }
.b-noappeal { background: #e0ddd2; color: #5c665e; }
.b-won      { background: #c4dbc4; color: #1e4620; }
.b-lost     { background: #e8c9c9; color: #7d3131; }
.b-draft    { background: #dde4ec; color: #33506e; }

/* metric bars */
.ot-metric-row { display:flex; justify-content:space-between; align-items:center;
                 margin: 10px 0 4px 0; font-size: 14.5px; }
.ot-bar { height: 7px; border-radius: 4px; margin-top: 2px; }

/* buttons */
.stButton > button, .stDownloadButton > button {
    border-radius: 999px !important; font-weight: 600 !important;
}
.stButton > button[kind="primary"], .stDownloadButton > button {
    background: #1c453a !important; color: #f3efe4 !important; border: none !important;
}
.stButton > button[kind="secondary"] {
    background: transparent !important; color: #1c453a !important;
    border: 1.5px solid #1c453a !important;
}

/* tabs */
.stTabs [data-baseweb="tab-list"] { gap: 8px; }
.stTabs [data-baseweb="tab"] {
    background: #ece6d5; border-radius: 999px; padding: 6px 18px;
}
.stTabs [aria-selected="true"] { background: #1c453a !important; color: #f3efe4 !important; }
.stTabs [aria-selected="true"] p { color: #f3efe4 !important; }

/* radio as nav */
[data-testid="stSidebar"] .stRadio div[role="radiogroup"] label {
    background: transparent; border-radius: 12px; padding: 8px 14px; width: 100%;
}
[data-testid="stSidebar"] .stRadio div[role="radiogroup"] label:has(input:checked) {
    background: #1c453a;
}
[data-testid="stSidebar"] .stRadio div[role="radiogroup"] label:has(input:checked) p {
    color: #f3efe4 !important;
}
[data-testid="stSidebar"] .stRadio div[role="radiogroup"] label > div:first-child { display: none; }

/* dataframe */
[data-testid="stDataFrame"] { background: #fcf9f1; border-radius: 14px;
    border: 1px solid #e3dccb; padding: 6px; }
mark { background: #d8e4d2; color: #2f5d40; border-radius: 4px; padding: 0 3px; }
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
    st.markdown(
        '<div class="ot-serif" style="font-size:26px;margin-bottom:2px">⚖️ Overturn</div>'
        '<div class="ot-muted" style="font-size:12.5px;margin-bottom:18px">'
        "Denied claims, recovered — all local.</div>",
        unsafe_allow_html=True,
    )
    nav = st.radio(
        "nav",
        ["Overview", "Denied Claims", "Resolutions (Pending Approval)", "New Case", "Settings"],
        label_visibility="collapsed",
    )
    st.divider()
    if ollama_up:
        st.caption("🟢 Local model connected — 0 bytes leave this machine")
    else:
        st.caption("🔴 Ollama offline — cached-sample mode")


# ================================================================ OVERVIEW
if nav == "Overview":
    st.markdown('<div class="ot-serif" style="font-size:30px">Claims Resolution Dashboard</div>',
                unsafe_allow_html=True)
    stats = db.dashboard_stats()
    cases = db.list_cases()
    awaiting = sum(1 for c in cases if c["status"] == "appeal_ready")

    left, right = st.columns([3, 1])
    with left:
        st.markdown('<div class="ot-card">', unsafe_allow_html=True)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Denied claims", stats["n_cases"])
        c2.metric("Denied $", f"${stats['total_denied']:,.0f}")
        c3.metric("Recovered $", f"${stats['won_amt']:,.0f}")
        c4.metric("Projected recovery", f"${stats['projected']:,.0f}")
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("#### Denied $ by category")
        if stats["by_category"]:
            st.bar_chart(pd.DataFrame({"amount": stats["by_category"]}).rename_axis("category"),
                         color="#1c453a")

    with right:
        total = max(stats["n_cases"], 1)
        auto = sum(1 for c in cases if c.get("action") == "APPEAL")
        st.markdown(
            f"""<div class="ot-card">
            <div style="font-weight:700;margin-bottom:8px">Resolution Metrics</div>
            <div class="ot-metric-row"><span>Total Denied</span><b>{stats['n_cases']}</b></div>
            <div class="ot-bar" style="background:#c98a6b;width:{min(100, total/total*100):.0f}%"></div>
            <div class="ot-metric-row"><span>Auto-Drafted</span><b>{auto}</b></div>
            <div class="ot-bar" style="background:#3f7a5c;width:{min(100, auto/total*100):.0f}%"></div>
            <div class="ot-metric-row"><span>Awaiting HITL Review</span><b>{awaiting}</b></div>
            <div class="ot-bar" style="background:#8a6d1f;width:{min(100, awaiting/total*100):.0f}%"></div>
            <div class="ot-muted" style="margin-top:10px;font-size:12px">
            Recovered to date: ${stats['won_amt']:,.0f}</div>
            </div>""",
            unsafe_allow_html=True,
        )

    st.markdown("#### Recent cases")
    recent = cases[:6]
    for c in recent:
        st.markdown(
            f"""<div class="ot-card" style="padding:14px 20px">
            <div style="display:flex;justify-content:space-between;align-items:center">
              <div>
                <span class="ot-chip">{html.escape(c['category'] or '—')}</span>
                <b>{html.escape(c['name'] or 'Case')}</b>
                <span class="ot-muted"> · {html.escape(c['payer'] or '')} · {c['carc_code'] or ''}</span>
              </div>
              <div><b>${(c['claim_amount'] or 0):,.0f}</b>&nbsp;&nbsp;{badge(c['status'])}</div>
            </div></div>""",
            unsafe_allow_html=True,
        )


# ================================================================ DENIED CLAIMS
elif nav == "Denied Claims":
    st.markdown('<div class="ot-serif" style="font-size:30px">Denied Claims</div>',
                unsafe_allow_html=True)
    cases = db.list_cases()
    if not cases:
        st.info("No claims yet — run a case or seed demo data from Settings.")
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


# ================================================================ RESOLUTIONS
elif nav == "Resolutions (Pending Approval)":
    st.markdown('<div class="ot-serif" style="font-size:30px">Resolutions — Pending Approval</div>',
                unsafe_allow_html=True)
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
elif nav == "New Case":
    st.markdown('<div class="ot-serif" style="font-size:30px">New Case</div>',
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
                prog = st.status("Running pipeline…", expanded=True)
                with prog:
                    result = run_pipeline(denial_text, note_text, model=model, on_step=st.write)
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
            show_redacted = st.toggle("Show redacted version (what the LLM wrote)", value=False)
            if show_redacted:
                st.code(res.letter_redacted, language=None)
            letter = st.text_area(
                "Appeal letter (editable before sending)",
                value=st.session_state.get("edited_letter", res.letter),
                height=420,
            )
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
                    st.toast("Marked as appeal submitted")


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
