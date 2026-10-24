"""SQLite storage: cases, statuses, amounts. Zero setup, fully local."""
import json
import sqlite3
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = _ROOT / "data" / "overturn.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    name TEXT,
    payer TEXT,
    category TEXT,
    carc_code TEXT,
    claim_amount REAL DEFAULT 0,
    status TEXT DEFAULT 'denied',
    score INTEGER,
    action TEXT,
    denial_text TEXT,
    note_text TEXT,
    redacted_denial TEXT,
    redacted_note TEXT,
    vault_json TEXT,
    denial_info_json TEXT,
    evidence_json TEXT,
    letter TEXT,
    recovered_amount REAL DEFAULT 0
);
"""

STATUSES = [
    "denied",
    "appeal_ready",
    "fix_resubmit",
    "no_appeal",
    "appealed",
    "won",
    "lost",
]


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(_SCHEMA)
    return conn


def migrate():
    """Add columns introduced after the initial schema."""
    conn = _conn()
    cols = {r[1] for r in conn.execute("PRAGMA table_info(cases)")}
    for col, ddl in (("reviewer", "TEXT"), ("assignee", "TEXT")):
        if col not in cols:
            conn.execute(f"ALTER TABLE cases ADD COLUMN {col} {ddl}")
    conn.commit()
    conn.close()


def get_case(case_id: int) -> dict | None:
    conn = _conn()
    row = conn.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def update_assignment(case_id: int, reviewer: str = "", assignee: str = ""):
    conn = _conn()
    with conn:
        conn.execute(
            "UPDATE cases SET reviewer=?, assignee=? WHERE id=?",
            (reviewer, assignee, case_id),
        )
    conn.close()


def save_case(case: dict) -> int:
    conn = _conn()
    cols = [
        "name", "payer", "category", "carc_code", "claim_amount", "status",
        "score", "action", "denial_text", "note_text", "redacted_denial",
        "redacted_note", "vault_json", "denial_info_json", "evidence_json",
        "letter", "recovered_amount",
    ]
    row = {"created_at": datetime.now().isoformat(timespec="seconds")}
    for c in cols:
        row[c] = case.get(c)
    for json_col in ("vault_json", "denial_info_json", "evidence_json"):
        if row[json_col] is not None and not isinstance(row[json_col], str):
            row[json_col] = json.dumps(row[json_col])
    with conn:
        cur = conn.execute(
            f"INSERT INTO cases (created_at, {', '.join(cols)}) "
            f"VALUES (:created_at, {', '.join(':' + c for c in cols)})",
            row,
        )
    case_id = cur.lastrowid
    conn.close()
    return case_id


def update_status(case_id: int, status: str, recovered_amount: float | None = None):
    conn = _conn()
    with conn:
        if recovered_amount is None:
            conn.execute("UPDATE cases SET status=? WHERE id=?", (status, case_id))
        else:
            conn.execute(
                "UPDATE cases SET status=?, recovered_amount=? WHERE id=?",
                (status, recovered_amount, case_id),
            )
    conn.close()


def update_letter(case_id: int, letter: str):
    conn = _conn()
    with conn:
        conn.execute("UPDATE cases SET letter=? WHERE id=?", (letter, case_id))
    conn.close()


def list_cases() -> list[dict]:
    conn = _conn()
    rows = conn.execute("SELECT * FROM cases ORDER BY id DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def dashboard_stats() -> dict:
    cases = list_cases()
    total_denied = sum(c["claim_amount"] or 0 for c in cases)
    appealed = [c for c in cases if c["status"] in ("appealed", "won", "lost")]
    appealed_amt = sum(c["claim_amount"] or 0 for c in appealed)
    won_amt = sum(c["recovered_amount"] or 0 for c in cases if c["status"] == "won")
    # Score-weighted projection on cases we recommend appealing
    proj = sum(
        (c["claim_amount"] or 0) * (c["score"] or 0) / 100.0
        for c in cases
        if c["action"] == "APPEAL" or c["status"] in ("appealed", "appeal_ready")
    )
    by_cat: dict[str, float] = {}
    for c in cases:
        cat = c["category"] or "unknown"
        by_cat[cat] = by_cat.get(cat, 0) + (c["claim_amount"] or 0)
    return {
        "n_cases": len(cases),
        "total_denied": total_denied,
        "appealed_amt": appealed_amt,
        "won_amt": won_amt,
        "projected": proj,
        "by_category": by_cat,
    }


def seed_if_empty():
    """Populate ~20 synthetic cases so the dashboard looks real on first run."""
    conn = _conn()
    n = conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
    conn.close()
    if n:
        return
    import random

    random.seed(7)
    payers = [
        "Meridian Health Plan", "Cascade Mutual Insurance", "BluePeak Benefits",
        "Atlantic Surety Health", "Summit Care Alliance",
    ]
    cats = [
        ("medical_necessity", "CO-50"), ("prior_auth", "CO-197"),
        ("coding", "CO-150"), ("timely_filing", "CO-29"),
        ("not_covered", "CO-96"), ("missing_info", "CO-16"),
    ]
    weights = [("appeal_ready", .25), ("appealed", .15), ("won", .3),
               ("lost", .1), ("fix_resubmit", .1), ("no_appeal", .05), ("denied", .05)]
    for i in range(20):
        cat, carc = random.choice(cats)
        status = random.choices([w for w, _ in weights], [p for _, p in weights])[0]
        amount = round(random.uniform(180, 4200), 2)
        score = random.randint(20, 95)
        if status == "no_appeal":
            score = random.randint(10, 35)
        action = (
            "APPEAL" if score >= 55 and cat != "timely_filing"
            else "FIX_AND_RESUBMIT" if score >= 35
            else "DO_NOT_APPEAL"
        )
        recovered = round(amount * random.uniform(0.6, 1.0), 2) if status == "won" else 0
        save_case({
            "name": f"Seeded case {i + 1:02d}",
            "payer": random.choice(payers),
            "category": cat,
            "carc_code": carc,
            "claim_amount": amount,
            "status": status,
            "score": score,
            "action": action,
            "recovered_amount": recovered,
        })
