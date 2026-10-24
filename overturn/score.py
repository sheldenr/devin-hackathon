"""Winnability scoring: LLM base estimate + explainable rule adjustments."""
from pydantic import BaseModel, Field

from . import llm
from .classify import DenialInfo
from .evidence import EvidenceItem
from .prompts import load_prompt


class ScoreResult(BaseModel):
    score: int = Field(ge=0, le=100)
    action: str  # APPEAL | FIX_AND_RESUBMIT | DO_NOT_APPEAL
    reasons: list[str] = Field(default_factory=list)
    base_estimate: int = 0


def score_winnability(
    denial: DenialInfo,
    evidence: list[EvidenceItem],
    policy_excerpt: str = "",
    model: str = llm.DEFAULT_MODEL,
) -> ScoreResult:
    supporting = [e for e in evidence if e.supports]

    prompt = (
        load_prompt("score")
        .replace("<<<DENIAL_INFO>>>", denial.model_dump_json(indent=2))
        .replace(
            "<<<EVIDENCE>>>",
            "\n".join(f"- {e.fact} (quote: \"{e.quote_from_note}\")" for e in evidence)
            or "No evidence found.",
        )
        .replace("<<<POLICY>>>", policy_excerpt or "No payer policy excerpt available.")
    )
    data = llm.chat_json(prompt, model=model)
    base = int(max(0, min(100, data.get("base_estimate", 50))))
    llm_rationale = data.get("rationale", "")

    score = base
    reasons = [f"Model's base assessment: {base}/100. {llm_rationale}".rstrip()]

    if len(supporting) >= 2:
        score += 20
        reasons.append("+20 — two or more supporting quotes found in the chart.")
    elif len(supporting) == 1:
        reasons.append("Only one supporting chart quote found — no bonus.")

    if not supporting:
        score -= 30
        reasons.append("-30 — no supporting evidence found in the chart.")

    if denial.category in ("coding", "missing_info"):
        score += 15
        reasons.append(
            f"+15 — '{denial.category}' denials are usually fixable without a formal appeal."
        )

    if denial.category == "timely_filing":
        score -= 40
        reasons.append("-40 — timely-filing denials past the deadline almost never overturn.")

    score = int(max(0, min(100, score)))

    # Recommended action
    if denial.category == "timely_filing" or score < 35:
        action = "DO_NOT_APPEAL"
    elif denial.category in ("coding", "missing_info"):
        action = "FIX_AND_RESUBMIT"
    elif score >= 55:
        action = "APPEAL"
    else:
        action = "FIX_AND_RESUBMIT"

    reasons.append(f"Final score {score}/100 → recommended action: {action}.")
    return ScoreResult(
        score=score, action=action, reasons=reasons, base_estimate=base
    )
