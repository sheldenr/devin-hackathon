"""PHI redaction via Presidio + custom medical-billing recognizers.

Produces (redacted_text, vault) where vault maps placeholders like
<PATIENT_1> back to the original strings. The vault never leaves the machine.
"""
import re

from pathlib import Path

from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer
from presidio_analyzer.nlp_engine import NlpEngineProvider

_ROOT = Path(__file__).resolve().parent.parent
_DENY_LIST_PATH = _ROOT / "data" / "deny_list.txt"

# Entity types whose labeled pattern captures the label text too
# (e.g. "MEMBER ID: MRK48291037"). Only the value becomes the placeholder.
_LABELED = {"MEMBER_ID", "CLAIM_NUMBER", "MRN", "NPI", "FAX_NUMBER"}
_LABEL_RE = re.compile(
    r"(?i)^(?:member|subscriber|enrollee|policy|group|claim|mrn|"
    r"medical\s+record|record|npi|fax)\b"
    r"(?:\s+(?:id|number|no\.?|#))?\s*[:#]?\s*"
)

# Entity type -> placeholder prefix
_PREFIX = {
    "PERSON": "PATIENT",
    "DATE_TIME": "DATE",
    "LOCATION": "ADDRESS",
    "PHONE_NUMBER": "PHONE",
    "EMAIL_ADDRESS": "EMAIL",
    "US_SSN": "SSN",
    "MEMBER_ID": "MEMBER_ID",
    "CLAIM_NUMBER": "CLAIM_NUM",
    "MRN": "MRN",
    "NPI": "NPI",
    "FAX_NUMBER": "FAX",
    "PATIENT_NAME": "PATIENT",
}


def _custom_recognizers() -> list[PatternRecognizer]:
    return [
        PatternRecognizer(
            supported_entity="MEMBER_ID",
            patterns=[
                Pattern("member_id_labeled", r"(?i)(member|subscriber|enrollee|policy|group)\s*(id|#|no\.?|number)\s*[:#]?\s*[A-Z]{1,4}[-\s]?\d{6,12}", 0.9),
                Pattern("member_id_generic", r"\b[A-Z]{3}\d{7,11}\b", 0.5),
            ],
            context=["member", "subscriber", "enrollee", "policy", "insured"],
            supported_language="en",
        ),
        PatternRecognizer(
            supported_entity="CLAIM_NUMBER",
            patterns=[
                Pattern("claim_labeled", r"(?i)claim\s*(#|no\.?|number|id)\s*[:#]?\s*\d{6,15}", 0.95),
                Pattern("claim_generic", r"\b\d{10,15}\b", 0.4),
            ],
            context=["claim", "remittance", "eob"],
            supported_language="en",
        ),
        PatternRecognizer(
            supported_entity="MRN",
            patterns=[
                Pattern("mrn_labeled", r"(?i)(mrn|medical record|record)\s*(#|no\.?|number)?\s*[:#]?\s*\d{5,12}", 0.95),
            ],
            context=["mrn", "record", "chart"],
            supported_language="en",
        ),
        PatternRecognizer(
            supported_entity="NPI",
            patterns=[
                Pattern("npi_labeled", r"(?i)npi\s*[:#]?\s*\d{10}", 0.95),
            ],
            context=["npi", "provider"],
            supported_language="en",
        ),
        PatternRecognizer(
            supported_entity="FAX_NUMBER",
            patterns=[
                Pattern("fax_labeled", r"(?i)fax\s*[:#]?\s*[\d\-(). ]{7,20}", 0.9),
            ],
            context=["fax"],
            supported_language="en",
        ),
    ]


_analyzer = None


def _get_analyzer() -> AnalyzerEngine:
    global _analyzer
    if _analyzer is None:
        provider = NlpEngineProvider(
            nlp_configuration={
                "nlp_engine_name": "spacy",
                "models": [{"lang_code": "en", "model_name": "en_core_web_lg"}],
            }
        )
        nlp_engine = provider.create_engine()
        _analyzer = AnalyzerEngine(nlp_engine=nlp_engine, supported_languages=["en"])
        for rec in _custom_recognizers():
            _analyzer.registry.add_recognizer(rec)
        # Deny-list for known sample patient names (demo safety net)
        if _DENY_LIST_PATH.exists():
            names = [
                l.strip()
                for l in _DENY_LIST_PATH.read_text().splitlines()
                if l.strip() and not l.startswith("#")
            ]
            if names:
                _analyzer.registry.add_recognizer(
                    PatternRecognizer(
                        supported_entity="PATIENT_NAME",
                        deny_list=names,
                        supported_language="en",
                    )
                )
    return _analyzer


def redact(text: str) -> tuple[str, dict[str, str]]:
    """Return (redacted_text, vault). Vault maps placeholder -> original value.

    The same original value always gets the same placeholder, so names and IDs
    stay consistent across the denial and the note.
    """
    analyzer = _get_analyzer()
    entities = list(_PREFIX.keys())
    results = analyzer.analyze(
        text=text,
        entities=entities,
        language="en",
        score_threshold=0.35,
    )
    # Drop obvious non-person false positives (e.g. "PO Box 55090")
    results = [
        r
        for r in results
        if not (
            r.entity_type == "PERSON"
            and re.search(r"(?i)\b(p\.?o\.?\s*)?box\b", text[r.start : r.end])
        )
    ]
    # Sort by start desc so replacements don't shift offsets; dedupe overlaps
    results = _dedupe(results)
    results.sort(key=lambda r: r.start, reverse=True)

    vault: dict[str, str] = {}
    value_to_ph: dict[tuple[str, str], str] = {}
    counters: dict[str, int] = {}
    redacted = text
    for r in results:
        raw = text[r.start : r.end]
        start_off = 0
        if r.entity_type in _LABELED:
            m = _LABEL_RE.match(raw)
            if m and len(raw.strip()) - m.end() >= 4:
                start_off = m.end()
                while start_off < len(raw) and raw[start_off] in " \t":
                    start_off += 1
        original = raw[start_off:]
        if not original.strip():
            continue
        key = (r.entity_type, original.strip().lower())
        if key in value_to_ph:
            ph = value_to_ph[key]
        else:
            prefix = _PREFIX.get(r.entity_type, r.entity_type)
            counters[prefix] = counters.get(prefix, 0) + 1
            ph = f"<{prefix}_{counters[prefix]}>"
            value_to_ph[key] = ph
            vault[ph] = original
        # Keep any label text outside the placeholder span
        redacted = redacted[: r.start] + raw[:start_off] + ph + redacted[r.end :]
    # Vault ends up unordered (desc traversal); re-sort by placeholder index
    vault = dict(
        sorted(
            vault.items(),
            key=lambda kv: (
                kv[0].strip("<>").rsplit("_", 1)[0],
                int(kv[0].rsplit("_", 1)[1].rstrip(">")),
            ),
        )
    )
    return redacted, vault


def _dedupe(results):
    """Drop lower-scored entities that overlap a higher-scored one."""
    results = sorted(results, key=lambda r: (-r.score, -(r.end - r.start)))
    kept = []
    for r in results:
        if all(r.end <= k.start or r.start >= k.end for k in kept):
            kept.append(r)
    return kept


def re_identify(text: str, vault: dict[str, str]) -> str:
    """Swap placeholders back to real values. Longest-first to be safe."""
    for ph in sorted(vault, key=len, reverse=True):
        text = text.replace(ph, vault[ph])
    return text


def merge_vaults(*vaults: dict[str, str]) -> dict[str, str]:
    """Merge per-document vaults, renumbering placeholders to stay unique."""
    merged: dict[str, str] = {}
    counters: dict[str, int] = {}
    value_to_ph: dict[str, str] = {}
    for vault in vaults:
        for ph, value in vault.items():
            if value.lower() in value_to_ph:
                continue
            prefix = ph.strip("<>").rsplit("_", 1)[0]
            counters[prefix] = counters.get(prefix, 0) + 1
            new_ph = f"<{prefix}_{counters[prefix]}>"
            merged[new_ph] = value
            value_to_ph[value.lower()] = new_ph
    return merged
