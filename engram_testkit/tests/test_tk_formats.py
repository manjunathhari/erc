"""TK-F: conversation and question formats, consent and provenance."""
import json

import pytest

from engram_testkit import formats as F


def test_f01_synthetic_set_loads_and_validates(synthetic):
    convs, qs = synthetic
    assert set(convs) == {"syn-1", "syn-2", "syn-3"} and len(qs) == 13


@pytest.mark.parametrize("field", ["speaker", "role", "date", "text"])
def test_f02_every_turn_needs_speaker_role_date_text(conv, field):
    del conv["turns"][0][field]
    with pytest.raises(F.FormatError, match=field):
        F.validate_conversation(conv)


@pytest.mark.parametrize("change,match", [
    (lambda c: c["turns"][0].update(role="narrator"), "role"),
    (lambda c: c["turns"][1].update(id=c["turns"][0]["id"]), "duplicate"),
    (lambda c: c.update(source={"kind": "synthetic"}), "pointer"),
    (lambda c: c.update(provenance="scraped"), "provenance"),
], ids=["role", "duplicate-turn", "source-pointer", "provenance"])
def test_f03_malformed_conversation_refused(conv, change, match):
    change(conv)
    with pytest.raises(F.FormatError, match=match):
        F.validate_conversation(conv)


@pytest.mark.parametrize("consent", [None, {}, {"basis": ""}])
def test_f04_consent_required_on_every_conversation(conv, consent):
    conv["consent"] = consent
    with pytest.raises(F.FormatError, match="consent"):
        F.validate_conversation(conv)


def test_f05_real_provenance_refused_by_default_and_when_asked(conv):
    assert F.ACCESS_CONTROL_AVAILABLE is False
    conv["provenance"] = "real"
    with pytest.raises(F.RealDataRefused):
        F.validate_conversation(conv)
    with pytest.raises(F.RealDataRefused):
        F.validate_conversation(conv, access_control=True)


def test_f06_a_real_conversation_in_a_file_stops_the_whole_load(tmp_path):
    convs = F.read_records(F.SYNTHETIC + "/conversations.json")
    convs[2]["provenance"] = "real"
    (tmp_path / "c.json").write_text(json.dumps(convs))
    with pytest.raises(F.RealDataRefused):
        F.load_set(str(tmp_path / "c.json"), F.SYNTHETIC + "/questions.json")


def test_f07_question_evidence_must_be_turns_of_its_conversation(synthetic):
    convs, qs = synthetic
    with pytest.raises(F.FormatError, match="evidence"):
        F.validate_question(dict(qs[0], evidence=["s3:1"]), convs)


@pytest.mark.parametrize("pick,change,match", [
    ("single-hop", dict(category="trivia"), "category"),
    ("adversarial", dict(gold="Lisbon"), "not mentioned"),
    ("changed-fact", dict(evidence=["s1:4"]), "changed-fact"),
], ids=["category", "adversarial-gold", "changed-fact-evidence"])
def test_f08_malformed_question_refused(synthetic, pick, change, match):
    convs, qs = synthetic
    q = next(q for q in qs if q["category"] == pick)
    with pytest.raises(F.FormatError, match=match):
        F.validate_question(dict(q, **change), convs)


def test_f09_json_and_jsonl_load_the_same(tmp_path):
    convs = F.read_records(F.SYNTHETIC + "/conversations.json")
    qs = F.read_records(F.SYNTHETIC + "/questions.json")
    (tmp_path / "c.jsonl").write_text("\n".join(json.dumps(c) for c in convs))
    (tmp_path / "q.jsonl").write_text("\n".join(json.dumps(q) for q in qs))
    assert F.load_set(str(tmp_path / "c.jsonl"), str(tmp_path / "q.jsonl")) == F.load_synthetic()
