You are a clinical documentation specialist. A claim was denied and we need to know whether the patient's visit note contains facts that support overturning the denial.

DENIAL DETAILS (JSON):
<<<DENIAL_INFO>>>

VISIT NOTE (patient identifiers are placeholders — keep them verbatim):
<<<VISIT_NOTE>>>

Return a JSON object with one key, "items": a list of objects, each with:
- "fact": short description of a clinically relevant fact found in the note
- "quote_from_note": an EXACT verbatim quote copied from the note (max ~30 words) that proves the fact
- "supports": true ONLY if the fact helps overturn THIS SPECIFIC denial reason — a fact that merely describes the patient's condition but doesn't bear on why the claim was denied is "supports": false

Only include facts whose quote literally appears in the note. Do not invent findings.
Focus on facts that address the stated denial reason (e.g., for medical necessity: failed conservative treatment, objective exam findings, red flags, functional impairment; for timely filing: proof of timely submission or good cause; for missing authorization: evidence an auth request was submitted).
Return 2 to 6 items. Reply with ONLY the JSON object.
