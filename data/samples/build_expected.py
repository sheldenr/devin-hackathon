"""Generate expected.json fallback files + PDF versions of sample docs.

Run:  python data/samples/build_expected.py
expected.json lets the demo show correct analysis when Ollama is offline
(the plan's "cache results in SQLite / hard-coded defaults" fallback).
"""
import hashlib
import json
from pathlib import Path

import pymupdf

SAMPLES = Path(__file__).resolve().parent

EXPECTED = {
    "case1_mri": {
        "denial_info": {
            "payer": "Meridian Health Plan",
            "claim_amount": 1840.00,
            "cpt_codes": ["72148"],
            "icd10_codes": ["M54.5", "M51.26"],
            "carc_code": "CO-50",
            "category": "medical_necessity",
            "denial_reason_text": "MRI of the lumbar spine denied as not medically necessary; payer policy requires 6 weeks of failed conservative management or progressive neurological findings.",
            "service_date": "03/14/2026",
            "claim_reference": "<CLAIM_NUM_1>",
        },
        "evidence": [
            {"fact": "Patient completed 8 weeks of structured physical therapy with minimal improvement — exceeds the payer's 6-week requirement.",
             "quote_from_note": "She has completed eight (8) weeks of structured physical therapy (01/05/2026–02/27/2026) with minimal improvement.",
             "supports": True},
            {"fact": "New progressive neurological findings: diminished left Achilles reflex and 4/5 EHL strength.",
             "quote_from_note": "Left Achilles reflex diminished (1+) versus right (2+). Strength 4/5 left extensor hallucis longus.",
             "supports": True},
            {"fact": "Positive tension sign with dermatomal sensory loss — meets the payer's red-flag criterion.",
             "quote_from_note": "Straight-leg raise positive on the left at 40 degrees, reproducing her calf pain.",
             "supports": True},
            {"fact": "Ordering clinician explicitly tied the MRI to failed conservative care and progressive findings.",
             "quote_from_note": "Given eight weeks of failed conservative management and new progressive motor and reflex findings on exam, I am ordering an MRI",
             "supports": True},
        ],
        "scoring": {
            "score": 85, "base_estimate": 65, "action": "APPEAL",
            "reasons": [
                "Model's base assessment: 65/100 — medical-necessity denials overturn often when documented.",
                "+20 — two or more supporting quotes found in the chart.",
                "Chart shows 8 weeks of failed PT (payer requires 6) plus progressive neuro findings — meets both policy prongs.",
                "Final score 85/100 → recommended action: APPEAL.",
            ],
        },
    },
    "case2_pt_auth": {
        "denial_info": {
            "payer": "Cascade Mutual Insurance",
            "claim_amount": 1120.00,
            "cpt_codes": ["97110", "97140"],
            "icd10_codes": [],
            "carc_code": "CO-197",
            "category": "prior_auth",
            "denial_reason_text": "PT visits 13–20 denied because pre-authorization beyond the initial 12 visits was absent.",
            "service_date": "03/03/2026–03/31/2026",
            "claim_reference": "<CLAIM_NUM_1>",
        },
        "evidence": [
            {"fact": "The office states an authorization request was submitted before the denied visits.",
             "quote_from_note": "Authorization request for visits 13–20 was submitted by our office on 02/26/2026; we have not received a determination.",
             "supports": True},
            {"fact": "Progress notes document measurable improvement consistent with the post-op ACL protocol.",
             "quote_from_note": "Right knee ROM 0–128 degrees (was 0–115 at visit 8).",
             "supports": True},
            {"fact": "Treating therapist states continued skilled PT is medically necessary; premature discharge risks graft strain.",
             "quote_from_note": "unassisted discharge now risks graft strain and poor long-term outcome.",
             "supports": True},
            {"fact": "Persistent strength and movement-quality deficits remain.",
             "quote_from_note": "quad strength deficit and movement quality deficits persist.",
             "supports": True},
        ],
        "scoring": {
            "score": 68, "base_estimate": 48, "action": "APPEAL",
            "reasons": [
                "Model's base assessment: 48/100 — auth was genuinely absent, but the policy allows retroactive auth.",
                "+20 — two or more supporting quotes found in the chart.",
                "Payer policy PT-02 allows retrospective authorization when a timely request is documented — the note says one was submitted 02/26/2026.",
                "Final score 68/100 → recommended action: APPEAL.",
            ],
        },
    },
    "case3_coding": {
        "denial_info": {
            "payer": "BluePeak Benefits",
            "claim_amount": 210.00,
            "cpt_codes": ["99215"],
            "icd10_codes": ["I10"],
            "carc_code": "CO-150",
            "category": "coding",
            "denial_reason_text": "99215 denied — documentation supports only level 3 (99213); claim denied rather than downcoded.",
            "service_date": "04/02/2026",
            "claim_reference": "<CLAIM_NUM_1>",
        },
        "evidence": [
            {"fact": "The visit was a routine follow-up for one stable chronic condition — level-3 complexity per policy EM-07.",
             "quote_from_note": "Hypertension diagnosed 2023, controlled on lisinopril 10 mg daily.",
             "supports": False},
            {"fact": "Assessment confirms stable disease — supports the payer's 99213 position, not 99215.",
             "quote_from_note": "Essential hypertension (I10), stable and well-controlled on current regimen.",
             "supports": False},
            {"fact": "Plan was low-risk: continue medication and routine labs — not high-complexity MDM.",
             "quote_from_note": "Continue lisinopril 10 mg daily. Continue home BP monitoring. Routine labs ordered",
             "supports": False},
        ],
        "scoring": {
            "score": 45, "base_estimate": 30, "action": "FIX_AND_RESUBMIT",
            "reasons": [
                "Model's base assessment: 30/100 — the chart supports the payer's position, not 99215.",
                "-30 — no supporting evidence found in the chart (all quotes undermine the billed level).",
                "+15 — 'coding' denials are usually fixable without a formal appeal.",
                "Payer says the claim is payable if resubmitted at the documented level (99213).",
                "Final score 45/100 → recommended action: FIX_AND_RESUBMIT.",
            ],
        },
    },
    "case4_timely": {
        "denial_info": {
            "payer": "Atlantic Surety Health",
            "claim_amount": 385.00,
            "cpt_codes": ["99283"],
            "icd10_codes": ["S52.501A", "W00.0XXA"],
            "carc_code": "CO-29",
            "category": "timely_filing",
            "denial_reason_text": "Claim denied for expired filing limit — received 423 days after service; contract requires submission within 90 days.",
            "service_date": "02/11/2025",
            "claim_reference": "<CLAIM_NUM_1>",
        },
        "evidence": [
            {"fact": "Note documents a straightforward fracture visit — nothing bearing on the timeliness issue.",
             "quote_from_note": "Non-displaced distal radius fracture, right wrist.",
             "supports": False},
            {"fact": "No documentation of an earlier timely submission or payer system failure exists in the record.",
             "quote_from_note": "Volar splint applied. Ice, elevation, OTC analgesia.",
             "supports": False},
        ],
        "scoring": {
            "score": 5, "base_estimate": 15, "action": "DO_NOT_APPEAL",
            "reasons": [
                "Model's base assessment: 15/100 — the visit itself is clean but the denial is procedural.",
                "-30 — no supporting evidence found in the chart.",
                "-40 — timely-filing denials past the deadline almost never overturn.",
                "Claim was 333 days past the 90-day contractual limit with no proof of timely submission.",
                "Final score 5/100 → recommended action: DO_NOT_APPEAL.",
            ],
        },
    },
    "case5_oon": {
        "denial_info": {
            "payer": "Summit Care Alliance",
            "claim_amount": 1050.00,
            "cpt_codes": ["90837"],
            "icd10_codes": ["F41.1"],
            "carc_code": "PR-96",
            "category": "not_covered",
            "denial_reason_text": "Out-of-network psychotherapy denied — plan has no out-of-network behavioral health benefit.",
            "service_date": "02/24/2026–03/31/2026",
            "claim_reference": "<CLAIM_NUM_1>",
        },
        "evidence": [
            {"fact": "Patient documented a network-adequacy problem: no in-network therapist available within access standards.",
             "quote_from_note": "no in-network therapist within 40 miles had a new-patient opening before June; she contacted four listed providers",
             "supports": True},
            {"fact": "Objective improvement on standardized measure — treatment is effective and ongoing need remains.",
             "quote_from_note": "GAD-7 score improved from 15 (severe) at intake in January to 9 (moderate) today.",
             "supports": True},
            {"fact": "Treatment is still clinically incomplete.",
             "quote_from_note": "Good progress on measurable goals but not yet at treatment completion.",
             "supports": True},
        ],
        "scoring": {
            "score": 62, "base_estimate": 42, "action": "APPEAL",
            "reasons": [
                "Model's base assessment: 42/100 — out-of-network exclusions are hard, but parity/network-adequacy arguments exist.",
                "+20 — two or more supporting quotes found in the chart.",
                "Payer's own policy BH-N1 allows a network-adequacy override; the note documents 4 failed in-network attempts.",
                "Final score 62/100 → recommended action: APPEAL.",
            ],
        },
    },
}


def write_pdf(src: Path, dst: Path, title: str = ""):
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    margin, y, line_h = 54, 54, 11.5
    if title:
        page.insert_text((margin, y), title, fontsize=14, fontname="hebo")
        y += line_h * 2
    for raw in src.read_text().splitlines():
        for line in _wrap(raw, 92):
            if y > 780 - margin:
                page = doc.new_page(width=612, height=792)
                y = margin
            if line.strip():
                page.insert_text((margin, y), line, fontsize=9.5)
            y += line_h
    doc.save(dst)
    doc.close()


def _wrap(line: str, width: int):
    if len(line) <= width:
        yield line
        return
    while len(line) > width:
        cut = line.rfind(" ", 0, width)
        cut = cut if cut > 0 else width
        yield line[:cut]
        line = line[cut:].lstrip()
    if line:
        yield line


def main():
    for case, data in EXPECTED.items():
        d = SAMPLES / case
        denial = (d / "denial.txt").read_text()
        data = dict(data)
        data["denial_sha256"] = hashlib.sha256(denial.encode()).hexdigest()
        (d / "expected.json").write_text(json.dumps(data, indent=2))
        write_pdf(d / "denial.txt", d / "denial.pdf")
        write_pdf(d / "note.txt", d / "note.pdf")
        print(f"{case}: expected.json + PDFs written")


if __name__ == "__main__":
    main()
