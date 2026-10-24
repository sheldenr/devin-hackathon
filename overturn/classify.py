"""Denial classification: redacted denial letter -> structured DenialInfo."""
from typing import Literal, Optional

from pydantic import BaseModel, Field

from . import llm
from .prompts import load_prompt

CATEGORIES = Literal[
    "medical_necessity",
    "prior_auth",
    "coding",
    "timely_filing",
    "not_covered",
    "duplicate",
    "missing_info",
]


class DenialInfo(BaseModel):
    payer: str = "Unknown payer"
    claim_amount: float = 0.0
    cpt_codes: list[str] = Field(default_factory=list)
    icd10_codes: list[str] = Field(default_factory=list)
    carc_code: str = ""
    category: CATEGORIES = "missing_info"
    denial_reason_text: str = ""
    service_date: Optional[str] = None
    claim_reference: str = ""  # placeholder like <CLAIM_NUM_1>


def classify(redacted_denial: str, model: str = llm.DEFAULT_MODEL) -> DenialInfo:
    prompt = load_prompt("classify").replace("<<<DENIAL_TEXT>>>", redacted_denial)
    data = llm.chat_json(prompt, model=model)
    return DenialInfo.model_validate(data)
