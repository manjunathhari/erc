"""TK-S: the synthetic conversation set itself."""
import os

from engram_testkit import formats as F


def test_s01_every_conversation_is_synthetic_with_consent_and_pointer(synthetic):
    convs, _ = synthetic
    for c in convs.values():
        assert c["provenance"] == "synthetic"
        assert "invented" in c["consent"]["basis"]
        assert c["source"]["pointer"].endswith("#" + c["id"])


def test_s02_set_covers_changed_fact_temporal_and_adversarial(synthetic):
    _, qs = synthetic
    cats = [q["category"] for q in qs]
    for need in ("changed-fact", "temporal", "adversarial"):
        assert cats.count(need) >= 2, need


def test_s03_changed_fact_evidence_runs_from_earlier_to_later_date(synthetic):
    convs, qs = synthetic
    for q in qs:
        if q["category"] != "changed-fact":
            continue
        turns = {t["id"]: t for t in convs[q["conversation"]]["turns"]}
        dates = [turns[e]["date"] for e in q["evidence"]]
        assert dates[0] < dates[-1], q["id"]


def test_s04_assistant_turns_carry_the_assistant_role(synthetic):
    convs, _ = synthetic
    roles = {t["role"] for t in convs["syn-2"]["turns"]}
    assert roles == {"user", "assistant"}
    assert all(t["role"] == "assistant" for t in convs["syn-2"]["turns"] if t["speaker"] == "Assistant")


def test_s05_package_holds_only_synthetic_data_and_no_benchmark_text():
    """LoCoMo text (CC BY-NC 4.0) is never committed: only the synthetic files, no locomo10.json."""
    assert sorted(os.listdir(os.path.dirname(F.SYNTHETIC))) == ["synthetic"]
    assert sorted(os.listdir(F.SYNTHETIC)) == ["conversations.json", "questions.json"]
    root = os.path.dirname(os.path.dirname(os.path.abspath(F.__file__))) + "/engram_testkit"
    for dirpath, _, files in os.walk(root):
        assert "locomo10.json" not in files, dirpath
