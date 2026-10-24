"""Evidence extraction: find chart facts that bear on the denial reason.

Every fact must carry a verbatim quote from the visit note. The appeal
generator may only use facts from this list, which keeps letters grounded.
"""
from pydantic import BaseModel, Field

from . import llm
from .classify import DenialInfo
from .prompts import load_prompt


class EvidenceItem(BaseModel):
    fact: str
    quote_from_note: str
    supports: bool = True


class EvidenceResult(BaseModel):
    items: list[EvidenceItem] = Field(default_factory=list)


def extract_evidence(
    redacted_note: str, denial: DenialInfo, model: str = llm.DEFAULT_MODEL
) -> list[EvidenceItem]:
    prompt = (
        load_prompt("evidence")
        .replace("<<<DENIAL_INFO>>>", denial.model_dump_json(indent=2))
        .replace("<<<VISIT_NOTE>>>", redacted_note)
    )
    data = llm.chat_json(prompt, model=model)
    result = EvidenceResult.model_validate(data)
    # Keep only quotes that actually appear in the note (anti-hallucination guard)
    return [
        item
        for item in result.items
        if _normalize(item.quote_from_note) in _normalize(redacted_note)
    ]


def _normalize(s: str) -> str:
    return " ".join(s.lower().split())
