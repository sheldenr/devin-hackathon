"""Appeal letter generation (on redacted text) + re-identification."""
from . import llm
from .classify import DenialInfo
from .evidence import EvidenceItem
from .prompts import load_prompt
from .redact import re_identify
from .score import ScoreResult


def generate_appeal(
    redacted_note: str,
    denial: DenialInfo,
    evidence: list[EvidenceItem],
    scoring: ScoreResult,
    policy_excerpt: str,
    vault: dict[str, str],
    model: str = llm.DEFAULT_MODEL,
) -> tuple[str, str]:
    """Return (letter_with_placeholders, final_letter)."""
    facts = "\n".join(
        f'- {e.fact}\n  Chart quote: "{e.quote_from_note}"'
        for e in evidence
        if e.supports
    )
    prompt = (
        load_prompt("appeal")
        .replace("<<<DENIAL_INFO>>>", denial.model_dump_json(indent=2))
        .replace("<<<EVIDENCE>>>", facts or "No supporting chart facts were found.")
        .replace("<<<POLICY>>>", policy_excerpt or "No payer policy excerpt available.")
        .replace("<<<VISIT_NOTE>>>", redacted_note)
    )
    letter_redacted = llm.chat(prompt, model=model).strip()
    return letter_redacted, re_identify(letter_redacted, vault)


def fallback_letter(
    denial: DenialInfo, evidence: list[EvidenceItem], vault: dict[str, str]
) -> tuple[str, str]:
    """Template letter for when the LLM is unreachable. Still grounded in quotes."""
    facts = "\n".join(
        f'  - {e.fact} The chart states: "{e.quote_from_note}"'
        for e in evidence
        if e.supports
    )
    body = f"""Re: Appeal of denied claim {denial.claim_reference or '<CLAIM_NUM_1>'}
Patient: <PATIENT_1> | Member ID: <MEMBER_ID_1>
Payer: {denial.payer} | Amount: ${denial.claim_amount:,.2f}

Dear Appeals Department,

We are writing to formally appeal the denial of the above-referenced claim,
which was denied as: "{denial.denial_reason_text or 'see denial letter'}"
({denial.carc_code or 'CARC not specified'}).

The patient's medical record supports coverage of this service:

{facts or '  - See attached visit note.'}

We respectfully request that you reverse the denial and reprocess the claim
for payment. Please contact our office with any questions.

Sincerely,
Billing Department"""
    return body, re_identify(body, vault)
