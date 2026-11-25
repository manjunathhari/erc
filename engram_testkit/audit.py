"""The gold-answer audit record (TK-16). A run needs one for its exact question set.

An audit names its auditor and date, and gives each question a status (kept, corrected or dropped) with
a reason. Dropped questions are not asked.
"""
import hashlib
import json

from .formats import is_iso_day

STATUSES = ("kept", "corrected", "dropped")
SYNTHETIC_REASON = "gold set by construction (synthetic)"


class AuditMissing(ValueError):
    """No usable audit record for this question set."""


def question_set_sha(questions):
    """SHA-256 of the question list, in a fixed JSON form."""
    blob = json.dumps(list(questions), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def make_audit(questions, auditor, date, status="kept", reason=SYNTHETIC_REASON):
    """An audit giving every question the same status and reason. Used for the synthetic set, whose gold is set by construction."""
    return dict(auditor=auditor, date=date, question_set=question_set_sha(questions),
                entries={q["id"]: dict(status=status, reason=reason) for q in questions})


def check_audit(audit, questions):
    """Check the audit against the questions. Returns the questions to ask (dropped ones left out)."""
    if not audit:
        raise AuditMissing("a gold-answer audit record is required before a run")
    if not isinstance(audit, dict):
        raise AuditMissing("the audit record must be an object")
    if audit.get("question_set") != question_set_sha(questions):
        raise AuditMissing("the audit was made for another question set")
    if not isinstance(audit.get("auditor"), str) or not audit["auditor"].strip():
        raise AuditMissing("the audit must name its auditor")
    if not is_iso_day(audit.get("date")):
        raise AuditMissing("the audit needs an ISO date (YYYY-MM-DD)")
    entries = audit.get("entries")
    if not isinstance(entries, dict):
        raise AuditMissing("the audit needs an entry for each question")
    ids = [q["id"] for q in questions]
    missing = [i for i in ids if i not in entries]
    if missing:
        raise AuditMissing(f"the audit does not cover questions {missing}")
    extra = sorted(set(entries) - set(ids))
    if extra:
        raise AuditMissing(f"the audit names questions not in the set: {extra}")
    for qid in ids:
        e = entries[qid]
        if not isinstance(e, dict) or e.get("status") not in STATUSES:
            raise AuditMissing(f"question {qid}: audit status must be one of {', '.join(STATUSES)}")
        if not isinstance(e.get("reason"), str) or not e["reason"].strip():
            raise AuditMissing(f"question {qid}: the audit entry needs a reason")
    return [q for q in questions if entries[q["id"]]["status"] != "dropped"]


def audit_record(audit):
    """What goes into state.json: auditor, date, question set, and which questions were dropped or corrected."""
    if not audit:
        return dict(auditor=None, date=None, question_set=None, dropped=[], corrected=[])
    entries = audit["entries"]
    return dict(auditor=audit["auditor"], date=audit["date"], question_set=audit["question_set"],
                dropped=[k for k, e in entries.items() if e["status"] == "dropped"],
                corrected=[k for k, e in entries.items() if e["status"] == "corrected"])
