# Overturn: 5-Hour Build Plan (Windows PC, fully local)

## Goal for demo day
With Wi-Fi off: upload a sample denial and visit note, show the redacted view, the denial classification, the winnability score and the generated appeal letter, then show a dashboard of recovered dollars.

---

## 1. Stack (chosen for speed on Windows)

| Layer | Choice | Why |
|---|---|---|
| LLM runtime | **Ollama for Windows** | One installer, uses NVIDIA GPUs automatically, local REST API at `localhost:11434` |
| Model | `qwen2.5:7b-instruct` or `llama3.1:8b` (GPU with at least 8GB VRAM); `llama3.2:3b` for CPU-only laptops | Reliable JSON output, fast enough for a live demo |
| UI | **Streamlit** | All Python, no frontend build step, upload widgets and charts built in |
| Patient-data redaction | **Presidio** (`presidio-analyzer`, `presidio-anonymizer`) + `en_core_web_lg` + custom regex | Runs offline and is reversible through a placeholder map |
| PDF text | **PyMuPDF** (`pymupdf`) | Pure pip install, no Poppler needed |
| Image OCR | **RapidOCR** (`rapidocr-onnxruntime`) | pip-only, so no Tesseract install on Windows |
| Storage | **SQLite** | Zero setup |
| Export | `python-docx` | Appeal letter as an editable .docx |

### Minimum hardware
- Windows 10/11, 16GB RAM
- NVIDIA GPU with at least 8GB VRAM recommended. Without one, use the 3B model on CPU (slower: about 15–40s per letter).

---

## 2. Setup (do this in the first 20 minutes, on every teammate's machine)

```powershell
# 1. Install Ollama from https://ollama.com/download (Windows installer), then:
ollama pull qwen2.5:7b-instruct
ollama pull llama3.2:3b          # CPU fallback

# 2. Python env
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install streamlit ollama pymupdf rapidocr-onnxruntime presidio-analyzer presidio-anonymizer python-docx pandas pydantic
python -m spacy download en_core_web_lg

# 3. Run
streamlit run app.py
```

**Do all downloads before the demo.** After setup, everything runs offline.

---

## 3. Repo layout

```
overturn/
├── app.py                  # Streamlit UI: Upload, Review, Appeal, Dashboard tabs
├── overturn/
│   ├── ingest.py           # PDF/image -> text (PyMuPDF, RapidOCR)
│   ├── redact.py           # Presidio + regex -> (redacted_text, vault)
│   ├── llm.py              # Ollama client, JSON-mode helper, model selection
│   ├── classify.py         # denial -> structured DenialInfo
│   ├── evidence.py         # visit note -> supporting facts for the denial reason
│   ├── score.py            # winnability score + recommendation
│   ├── appeal.py           # letter generation + re-identification
│   ├── export.py           # .docx export
│   ├── db.py               # SQLite: cases, status, amounts
│   └── prompts/            # prompt templates (.md)
├── data/
│   ├── samples/            # synthetic denial letters + visit notes (NO real PHI)
│   └── policies/           # short payer policy excerpts used for citations
├── README.md
└── PLAN.md
```

---

## 4. Pipeline

```
Denial PDF/photo + Visit note
        │
        ▼
 ingest.py ── text
        │
        ▼
 redact.py ── redacted text + vault {<PATIENT_1>: "Jane Doe", <MEMBER_ID_1>: "...", ...}
        │                    (vault stays in memory/SQLite, never sent anywhere)
        ▼
 classify.py (LLM, JSON) ── DenialInfo
        │   { payer, claim_amount, cpt_codes, icd10_codes, carc_code,
        │     category: medical_necessity | prior_auth | coding | timely_filing |
        │               not_covered | duplicate | missing_info, denial_reason_text }
        ▼
 evidence.py (LLM, JSON) ── [ {fact, quote_from_note, supports: true/false} ]
        │
        ▼
 score.py ── score 0–100 + action: APPEAL | FIX_AND_RESUBMIT | DO_NOT_APPEAL
        │   (rule-based adjustments + LLM rationale)
        ▼
 appeal.py (LLM) ── letter with placeholders ── re-identify with vault ── final letter
        │
        ▼
 export.py (.docx)  +  db.py (case saved, dashboard updated)
```

### Key design rules
- **Never send un-redacted text to the LLM**, even though it's local. That shows the redaction works and makes an optional cloud mode safe later.
- **Ground every claim in the chart.** The evidence step must return exact quotes from the note. The appeal prompt may only use facts from that list. This prevents made-up clinical details, which is the main legal and relationship risk.
- **Use JSON mode** (`format="json"` in Ollama) with Pydantic validation, and retry once if parsing fails.

### Winnability scoring (simple, explainable)
Start at the LLM's base estimate, then:
- +20 if 2+ supporting chart quotes match the payer's criteria
- +15 for `coding` or `missing_info` (usually fixable) → recommend FIX_AND_RESUBMIT
- −40 for `timely_filing` past the deadline → DO_NOT_APPEAL
- −30 if the evidence step found no supporting quotes
- Clamp to 0–100. Show the reasons as bullet points in the UI.

---

## 5. UI (Streamlit tabs)

1. **Upload**: two file uploaders (denial, visit note) plus a "Load sample case" dropdown (important for the demo).
2. **Privacy view**: original text and redacted text side by side, with placeholders highlighted. Banner: "Local model: localhost:11434. 0 bytes of patient data sent externally."
3. **Analysis**: denial category, payer, amount, CARC code, winnability gauge, recommended action, evidence quotes.
4. **Appeal**: generated letter (editable `st.text_area`), "Download .docx" button.
5. **Dashboard**: total denied $, appealed $, projected recovered $ (score-weighted), a cases table, and a bar chart by denial category. Seed it with about 20 synthetic cases so the numbers look real.

---

## 6. Synthetic data (needed for the demo; do not use real PHI)

Build 5 sample cases, each with a denial letter and a visit note:
1. MRI lumbar spine: **medical necessity** (strong chart, high score → APPEAL)
2. Physical therapy visits 13–20: **missing prior auth** (moderate)
3. Office visit 99215: **coding/level mismatch** → FIX_AND_RESUBMIT
4. Claim submitted 400 days late: **timely filing** → DO_NOT_APPEAL (shows honesty)
5. Behavioral health therapy: **not covered / out of network** (moderate)

Have the LLM draft them during hour 1, then hand-edit them. Make them look like real denial letters, with a payer letterhead, claim number, member ID and CARC code (e.g. CO-50 "not medically necessary", CO-197 "precertification absent", CO-29 "timely filing").

---

## 7. Timeline (team of 3–4)

| Time | Person A: Pipeline/LLM | Person B: Redaction/Ingest | Person C: UI | Person D: Data/Pitch |
|---|---|---|---|---|
| 0:00–0:30 | Ollama + models, `llm.py` JSON helper | Presidio setup, regex for member ID, claim #, record # | Streamlit skeleton with tabs | Write sample denials + notes |
| 0:30–2:00 | `classify.py`, `evidence.py` prompts | `ingest.py`, `redact.py` with vault + re-identify | Upload + Privacy view | Payer policy excerpts, 20 seeded dashboard cases |
| 2:00–3:00 | `score.py`, `appeal.py` | `export.py`, `db.py` | Analysis + Appeal tabs | Pitch deck draft (use README) |
| 3:00–3:45 | **Integration**: end-to-end on all 5 samples | Fix redaction misses | Dashboard + styling | Rehearse the story |
| 3:45–4:30 | Prompt tuning, speed (preload model, `keep_alive`) | Wi-Fi-off test | Polish, loading spinners | Record **backup demo video** |
| 4:30–5:00 | **Feature freeze.** Rehearse the demo twice, with Wi-Fi off. | | | |

If you're solo or a pair: skip the image OCR (use PDFs or pasted text) and skip the .docx export (copy the letter instead).

---

## 8. Demo script (3 minutes)

1. **Hook (20s):** "Insurers deny about 1 in 6 claims, under 1% get appealed, and most appeals win. Practices are leaving money on the table."
2. **Turn Wi-Fi off on screen (5s).**
3. **Load the MRI case (60s):** privacy view (redaction), then analysis (score 85, APPEAL, with quotes from the chart), then the generated appeal letter.
4. **Load the timely-filing case (20s):** "DO NOT APPEAL. We tell you when not to fight. That protects your insurer relationship."
5. **Dashboard (20s):** "$184K projected recovery across 20 claims."
6. **Business (40s):** contingency fee, plug-in box, billing companies as the scaling channel.
7. **Close (15s):** "Insurers have AI denying claims. Now providers have AI fighting back, and it never leaves the building."

---

## 9. Risks and fallbacks

| Risk | Fallback |
|---|---|
| LLM too slow on venue laptop | Use `llama3.2:3b`; pre-run the cases and cache results in SQLite; show cached output if needed |
| Malformed JSON | Pydantic validation + 1 retry + hard-coded default per sample |
| Redaction misses a name | Add a custom deny-list for the sample patient names; demo only synthetic data |
| Ollama not running | Start it before going on stage; check `curl localhost:11434/api/tags` |
| Live demo crashes | Backup video recorded in hour 4 |

## 10. Stretch goals (only if ahead of schedule)
- Optional "hybrid mode": send the **redacted** text to a cloud LLM for a stronger letter, then re-identify locally
- Look up CARC/RARC codes from a bundled CSV
- Track appeal deadlines and reminders
- Package as a single `.exe` with PyInstaller, or ship as a preconfigured mini PC
