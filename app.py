"""Overturn — denied claims, recovered. All local, all offline."""
import html
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

_PLACEHOLDER_RE = re.compile(r"<[A-Z]+_\d+>")


def highlight_placeholders(text: str) -> str:
    """Escape text and wrap <PLACEHOLDER_n> tokens in <mark>."""
    escaped = html.escape(text)
    escaped = escaped.replace("\n", "<br>")
    return _PLACEHOLDER_RE.sub(lambda m: f"<mark>{m.group(0)}</mark>", escaped)


def action_badge(action: str) -> str:
    colors = {
        "APPEAL": "#16a34a",
        "FIX_AND_RESUBMIT": "#d97706",
        "DO_NOT_APPEAL": "#dc2626",
    }
    return (
        f'<span style="background:{colors.get(action, "#555")};color:white;'
        f'padding:4px 14px;border-radius:12px;font-weight:600">{action}</span>'
    )


# ---------- sidebar ----------
with st.sidebar:
    st.title("⚖️ Overturn")
    st.caption("Denied claims, recovered.\nPatient data never leaves the building.")

    ollama_up = llm.is_available()
    if ollama_up:
        st.success("Ollama: connected — localhost:11434", icon="🟢")
    else:
        st.error("Ollama: offline — cached-sample mode", icon="🔴")

    models = llm.list_models() or [llm.DEFAULT_MODEL]
    model = st.selectbox("Model", models, index=0)
    if ollama_up and st.button("Warm up model", help="Pre-load the model so the first request is fast"):
        with st.spinner("Loading model…"):
            llm.warmup(model)
        st.toast("Model loaded")

    st.divider()
    if st.button("Seed dashboard demo data"):
        db.seed_if_empty()
        st.toast("Seeded 20 synthetic cases")

st.caption(
    "🔒 Local model: `localhost:11434` — **0 bytes of patient data sent externally.** "
    "Works with Wi-Fi off."
)

tab_upload, tab_privacy, tab_analysis, tab_appeal, tab_dash = st.tabs(
    ["📤 Upload", "🛡️ Privacy", "📊 Analysis", "✉️ Appeal", "💰 Dashboard"]
)

# ---------- Upload ----------
with tab_upload:
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

    if st.button("Analyze case", type="primary", disabled=not (denial_file and note_file) and sample == "(none)"):
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
                result = run_pipeline(
                    denial_text, note_text, model=model, on_step=st.write
                )
            prog.update(label="Analysis complete", state="complete")
            st.session_state["result"] = result
            st.session_state["edited_letter"] = result.letter
            if result.used_fallback:
                st.warning("Ollama offline — showing cached analysis for this sample case.")
            st.success("Done — check the Privacy, Analysis, and Appeal tabs.")
        except Exception as e:
            st.error(f"Pipeline failed: {e}")

    res = st.session_state.get("result")
    if res:
        st.info(f"Loaded case: **{res.display_info.payer}** — ${res.display_info.claim_amount:,.2f} — "
                f"{res.display_info.carc_code} ({res.display_info.category})")

# ---------- Privacy ----------
with tab_privacy:
    res = st.session_state.get("result")
    if not res:
        st.info("Analyze a case on the Upload tab first.")
    else:
        st.caption("What the model sees vs. what was uploaded — PHI is stripped before any AI touches it.")
        c1, c2 = st.columns(2)
        doc = st.radio("Document", ["Denial letter", "Visit note"], horizontal=True)
        orig = res.denial_text if doc == "Denial letter" else res.note_text
        red = res.redacted_denial if doc == "Denial letter" else res.redacted_note
        with c1:
            st.markdown("**Original**")
            st.markdown(
                f'<div style="border:1px solid #444;border-radius:8px;padding:12px;'
                f'max-height:480px;overflow-y:auto;font-size:13px">{html.escape(orig).replace(chr(10), "<br>")}</div>',
                unsafe_allow_html=True,
            )
        with c2:
            st.markdown("**Redacted (sent to local LLM)**")
            st.markdown(
                f'<div style="border:1px solid #444;border-radius:8px;padding:12px;'
                f'max-height:480px;overflow-y:auto;font-size:13px">{highlight_placeholders(red)}</div>',
                unsafe_allow_html=True,
            )
        with st.expander(f"Redaction vault — {len(res.vault)} placeholders (never leaves this machine)"):
            st.dataframe(
                pd.DataFrame(
                    [{"placeholder": k, "real value": v} for k, v in res.vault.items()]
                ),
                hide_index=True,
                use_container_width=True,
            )

# ---------- Analysis ----------
with tab_analysis:
    res = st.session_state.get("result")
    if not res:
        st.info("Analyze a case on the Upload tab first.")
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
            st.subheader("Winnability")
            st.progress(res.scoring.score / 100)
            st.markdown(f"## {res.scoring.score}/100")
            st.markdown(action_badge(res.scoring.action), unsafe_allow_html=True)
            st.caption(f"Reason: {info.denial_reason_text}")
        with c2:
            st.subheader("Evidence from the chart")
            if res.evidence:
                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "supports": "✅" if e.supports else "❌",
                                "fact": re_identify(e.fact, res.vault),
                                "chart quote": f'"{re_identify(e.quote_from_note, res.vault)}"',
                            }
                            for e in res.evidence
                        ]
                    ),
                    hide_index=True,
                    use_container_width=True,
                )
            else:
                st.warning("No chart evidence found.")
            with st.expander("How the score was computed"):
                for r in res.scoring.reasons:
                    st.markdown(f"- {r}")

# ---------- Appeal ----------
with tab_appeal:
    res = st.session_state.get("result")
    if not res:
        st.info("Analyze a case on the Upload tab first.")
    elif res.scoring.action != "APPEAL":
        st.warning(
            f"Recommended action is **{res.scoring.action.replace('_', ' ')}** — "
            "no appeal letter was generated."
        )
        if res.scoring.action == "FIX_AND_RESUBMIT":
            st.markdown(
                "Correct the claim and resubmit rather than appealing. "
                "Check the Analysis tab for what the documentation supports."
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
            with c3:
                new_status = st.selectbox(
                    "Mark case as", ["appealed", "won", "lost"], key="mark_status"
                )
                if st.button("Update status"):
                    recovered = res.display_info.claim_amount if new_status == "won" else None
                    db.update_status(res.case_id, new_status, recovered)
                    st.toast(f"Marked {new_status}")

# ---------- Dashboard ----------
with tab_dash:
    db.seed_if_empty()
    stats = db.dashboard_stats()
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Cases", stats["n_cases"])
    c2.metric("Denied $", f"${stats['total_denied']:,.0f}")
    c3.metric("Appealed $", f"${stats['appealed_amt']:,.0f}")
    c4.metric("Recovered $", f"${stats['won_amt']:,.0f}")
    c5.metric("Projected recovery", f"${stats['projected']:,.0f}")

    c1, c2 = st.columns([2, 1])
    with c1:
        st.subheader("Cases")
        cases = db.list_cases()
        if cases:
            st.dataframe(
                pd.DataFrame(cases)[
                    ["id", "name", "payer", "category", "claim_amount", "score", "action", "status"]
                ],
                hide_index=True,
                use_container_width=True,
            )
    with c2:
        st.subheader("Denied $ by category")
        if stats["by_category"]:
            st.bar_chart(
                pd.DataFrame(
                    {"amount": stats["by_category"]}
                ).rename_axis("category")
            )
