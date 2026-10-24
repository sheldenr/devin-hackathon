# Overturn

**Denied claims, recovered. Patient data never leaves the building.**

Overturn is a local AI agent for medical practices. It reads insurance claim denials, finds the evidence in the patient's chart, and writes a ready-to-send appeal letter in under a minute. Everything runs on the practice's own computer. No patient data goes to the cloud.

---

## The problem

Insurers deny a large share of claims, and most of those denials are never challenged, even though appeals often succeed.

- **About 1 in 6** in-network claims on ACA marketplace plans were denied (KFF, 2021 plan-year data).
- **Under 1%** of denied claims were appealed (KFF).
- **More than 80%** of appealed Medicare Advantage prior-authorization denials were partly or fully overturned (KFF, 2023).
- Providers spent about **$19.7B** in a single year fighting denials (Premier Inc., 2024 survey).

> Check every figure against its source before presenting.

Practices don't skip appeals because they'd lose. They skip them because each appeal takes 30–60 minutes of staff time to pull the chart, look up the payer's policy and write the letter. Small practices don't have the staff, so they write the money off.

Meanwhile, insurers are using AI to deny claims faster. Providers have nothing comparable on their side.

## The solution

Overturn turns a denial into a winnable appeal in about 30 seconds:

1. **Upload** the denial letter (PDF or photo) and the visit note.
2. **Redact locally.** Names, dates of birth, member IDs and record numbers are removed on the device.
3. **Classify the denial**, for example "not medically necessary", "missing prior auth", "coding error" or "timely filing".
4. **Score winnability.** Overturn only recommends appealing when the chart supports it. Weak cases get a "don't appeal" or "fix and resubmit" recommendation instead.
5. **Generate the appeal.** The letter cites the clinical evidence from the chart and the payer's own policy language.
6. **Track recovered revenue** on a dashboard.

**Fewer, stronger, evidence-backed appeals.** That protects the practice's relationship with the insurer as well as its revenue.

## Why local

| | Cloud AI tools | Overturn |
|---|---|---|
| Patient data leaves the practice | Yes | **No** |
| Months-long security / vendor review | Usually | **Minimal: runs on their own PC** |
| Inference cost per appeal | Per-token fees | **About $0** |
| Works offline | No | **Yes** |

The demo runs with **Wi-Fi turned off**.

## Who it's for

1. **Small and mid-size practices (1–50 providers)**: physical therapy, behavioral health, dermatology, imaging, specialty clinics. They have lots of denials, little billing staff and quick buying decisions.
2. **Medical billing companies**: one customer serves hundreds of practices, and they are paid on what they collect.
3. **Hospitals (later)**: the biggest contracts, once there's proof it works.
4. **Patients (free tier)**: brings in users and data. "Your claim was denied? Appeal it in 30 seconds."

## Business model

- **Contingency fee:** a percentage of recovered revenue. No upfront cost, and we only get paid when they do.
- **Optional hardware:** a preconfigured local box (mini PC with a GPU) for practices that want plug-and-play.
- **Long-term advantage:** anonymized win/loss data by payer and denial type. Over time Overturn learns which arguments beat which insurer.

## Tech

- **Local LLM:** Ollama (Llama 3.1 8B / Qwen 2.5 7B) on a Windows PC
- **Patient-data redaction:** Microsoft Presidio plus custom rules for member IDs, claim numbers and record numbers
- **OCR:** PyMuPDF (for PDFs) and RapidOCR (for images), both fully offline
- **App:** Python, Streamlit and SQLite

See [PLAN.md](PLAN.md) for the build plan.

## Team

_Add names and roles here._

## Running on this machine

```bash
ollama serve &                    # installed at ~/.local/bin/ollama
.venv/bin/streamlit run app.py    # http://localhost:8501
```

Model: `llama3.2:3b` (pulled, CPU-friendly). Set `OVERTURN_MODEL` to use a
bigger model on GPU machines. If Ollama is offline, sample cases fall back
to cached `expected.json` analyses so the demo still works.
