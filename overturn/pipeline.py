"""End-to-end pipeline: text -> redaction -> classify -> evidence -> score -> appeal.

If Ollama is unreachable and the case ships with an expected.json (sample
cases do), the cached analysis is used and `used_fallback` is set — this is
the plan's "pre-cached results" safety net for the live demo.
"""
import json
from dataclasses import dataclass, field
from pathlib import Path

from . import llm
from .appeal import fallback_letter, generate_appeal
from .classify import DenialInfo, classify
from .evidence import EvidenceItem, extract_evidence
from .redact import merge_vaults, redact, re_identify
from .score import ScoreResult, score_winnability

_ROOT = Path(__file__).resolve().parent.parent
POLICY_DIR = _ROOT / "data" / "policies"
SAMPLES_DIR = _ROOT / "data" / "samples"


@dataclass
class CaseResult:
    denial_text: str = ""
    note_text: str = ""
    redacted_denial: str = ""
    redacted_note: str = ""
    vault: dict = field(default_factory=dict)
    denial_info: DenialInfo | None = None
    evidence: list[EvidenceItem] = field(default_factory=list)
    scoring: ScoreResult | None = None
    policy_excerpt: str = ""
    letter_redacted: str = ""
    letter: str = ""
    case_id: int | None = None
    used_fallback: bool = False
    display_info: DenialInfo | None = None  # re-identified copy for UI/DB


def list_sample_cases() -> list[str]:
    if not SAMPLES_DIR.exists():
        return []
    return sorted(
        d.name for d in SAMPLES_DIR.iterdir() if (d / "denial.txt").exists()
    )


def load_sample(name: str) -> tuple[str, str]:
    d = SAMPLES_DIR / name
    return (d / "denial.txt").read_text(), (d / "note.txt").read_text()


def find_policy(payer: str) -> str:
    """Match a payer name to a policy excerpt file on its distinctive first word."""
    if not POLICY_DIR.exists():
        return ""
    payer_l = (payer or "").lower()
    best = None
    for path in POLICY_DIR.glob("*.md"):
        first = path.stem.split("_")[0]
        if first and first in payer_l and (
            best is None or len(first) > len(best.stem.split("_")[0])
        ):
            best = path
    return best.read_text() if best else ""


def _load_expected(denial_text: str) -> dict | None:
    """Find a sample expected.json matching this denial text (sha256)."""
    import hashlib

    if not SAMPLES_DIR.exists():
        return None
    digest = hashlib.sha256(denial_text.encode()).hexdigest()
    for exp in SAMPLES_DIR.glob("*/expected.json"):
        try:
            data = json.loads(exp.read_text())
            if data.get("denial_sha256") == digest:
                return data
        except Exception:
            continue
    return None


def run_pipeline(
    denial_text: str,
    note_text: str,
    model: str = llm.DEFAULT_MODEL,
    save: bool = True,
    on_step=None,
) -> CaseResult:
    step = on_step or (lambda msg: None)
    res = CaseResult(denial_text=denial_text, note_text=note_text)

    # 1. Redact both documents (never send unredacted text to the LLM)
    step("Redacting PHI locally (Presidio + custom rules)…")
    res.redacted_denial, vault_d = redact(denial_text)
    res.redacted_note, vault_n = redact(note_text)
    # Renumber the note vault so its placeholders don't collide with denial's,
    # then rewrite the note's placeholders accordingly.
    merged, remap = _merge(vault_d, vault_n)
    for old, new in remap.items():
        if old != new:
            res.redacted_note = res.redacted_note.replace(old, new)
    res.vault = merged

    # 2-4. LLM steps — with cached fallback when Ollama is down
    try:
        if not llm.is_available():
            raise ConnectionError("Ollama is not reachable at " + llm.HOST)
        step("Classifying the denial…")
        res.denial_info = classify(res.redacted_denial, model=model)
        res.policy_excerpt = find_policy(res.denial_info.payer)
        step("Pulling supporting evidence from the chart…")
        res.evidence = extract_evidence(res.redacted_note, res.denial_info, model=model)
        step("Scoring winnability…")
        res.scoring = score_winnability(
            res.denial_info, res.evidence, res.policy_excerpt, model=model
        )
    except Exception:
        expected = _load_expected(denial_text)
        if expected is None:
            raise
        res.used_fallback = True
        res.denial_info = DenialInfo.model_validate(expected["denial_info"])
        res.policy_excerpt = find_policy(res.denial_info.payer)
        res.evidence = [
            EvidenceItem.model_validate(e) for e in expected["evidence"]
        ]
        res.scoring = ScoreResult.model_validate(expected["scoring"])

    # Re-identified copy for display/storage — the LLM only ever saw the
    # redacted version above.
    res.display_info = res.denial_info.model_copy()
    for f in ("payer", "denial_reason_text", "service_date", "claim_reference", "carc_code"):
        v = getattr(res.display_info, f)
        if isinstance(v, str):
            setattr(res.display_info, f, re_identify(v, res.vault))

    # 5. Appeal letter (or skip if action isn't APPEAL)
    if res.scoring.action == "APPEAL":
        step("Drafting the appeal letter…")
        try:
            res.letter_redacted, res.letter = generate_appeal(
                res.redacted_note,
                res.denial_info,
                res.evidence,
                res.scoring,
                res.policy_excerpt,
                res.vault,
                model=model,
            )
        except Exception:
            res.used_fallback = True
            res.letter_redacted, res.letter = fallback_letter(
                res.denial_info, res.evidence, res.vault
            )

    # 6. Persist
    if save:
        from . import db

        status = {
            "APPEAL": "appeal_ready",
            "FIX_AND_RESUBMIT": "fix_resubmit",
            "DO_NOT_APPEAL": "no_appeal",
        }[res.scoring.action]
        res.case_id = db.save_case(
            {
                "name": _case_name(res.display_info),
                "payer": res.display_info.payer,
                "category": res.display_info.category,
                "carc_code": res.display_info.carc_code,
                "claim_amount": res.display_info.claim_amount,
                "status": status,
                "score": res.scoring.score,
                "action": res.scoring.action,
                "denial_text": denial_text,
                "note_text": note_text,
                "redacted_denial": res.redacted_denial,
                "redacted_note": res.redacted_note,
                "vault_json": res.vault,
                "denial_info_json": res.display_info.model_dump(),
                "evidence_json": [e.model_dump() for e in res.evidence],
                "letter": res.letter,
            }
        )
    return res


def _case_name(info: DenialInfo) -> str:
    return f"{info.payer} — {info.category} — ${info.claim_amount:,.2f}"


def _merge(vault_a: dict, vault_b: dict) -> tuple[dict, dict]:
    """Merge two vaults; returns (merged_vault, remap_for_vault_b)."""
    merged = dict(vault_a)
    counters: dict[str, int] = {}
    for ph in merged:
        prefix, _, n = ph.strip("<>").rpartition("_")
        counters[prefix] = max(counters.get(prefix, 0), int(n))
    value_to_ph = {v.lower(): k for k, v in merged.items()}
    remap = {}
    for ph, value in vault_b.items():
        if value.lower() in value_to_ph:
            remap[ph] = value_to_ph[value.lower()]
            continue
        prefix, _, _ = ph.strip("<>").rpartition("_")
        counters[prefix] = counters.get(prefix, 0) + 1
        new_ph = f"<{prefix}_{counters[prefix]}>"
        merged[new_ph] = value
        remap[ph] = new_ph
    return merged, remap


__all__ = [
    "CaseResult",
    "run_pipeline",
    "list_sample_cases",
    "load_sample",
    "find_policy",
    "re_identify",
]
