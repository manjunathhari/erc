"""TK-L: LoCoMo dev from outside the repository; conversations 5 to 9 held out behind a gate flag."""
import builtins
import os

import pytest

from engram_testkit import locomo as L

from .conftest import fake_locomo


@pytest.mark.parametrize("i", L.HELD_OUT)
def test_l01_each_held_out_conversation_refused_without_gate(tmp_path, i):
    path = fake_locomo(str(tmp_path / "fake.json"))
    with pytest.raises(L.HeldOutRefused):
        L.load(path, indices=[i])


def test_l02_refusal_comes_before_the_file_is_opened(monkeypatch):
    opened = []
    monkeypatch.setattr(builtins, "open", lambda *a, **k: opened.append(a) or (_ for _ in ()).throw(AssertionError("opened")))
    with pytest.raises(L.HeldOutRefused):
        L.load("/no/such/locomo10.json", indices=[0, 5])
    assert opened == []


def test_l03_gate_flag_must_be_exactly_true(tmp_path):
    path = fake_locomo(str(tmp_path / "fake.json"))
    for flag in (1, "yes", "True"):
        with pytest.raises(L.HeldOutRefused):
            L.load(path, indices=[7], held_out_gate=flag)
    convs, _ = L.load(path, indices=[7], held_out_gate=True)
    assert list(convs) == ["locomo-7"]


def test_l04_dev_default_is_conversations_0_to_4(tmp_path):
    assert L.DEV == (0, 1, 2, 3, 4) and L.HELD_OUT == (5, 6, 7, 8, 9)
    convs, qs = L.load(fake_locomo(str(tmp_path / "fake.json")))
    assert sorted(convs) == [f"locomo-{i}" for i in range(5)]
    assert len(qs) == 15


def test_l05_converted_conversation_has_provenance_consent_and_pointers(tmp_path):
    convs, qs = L.load(fake_locomo(str(tmp_path / "fake.json")), indices=[0])
    c = convs["locomo-0"]
    assert c["provenance"] == "benchmark" and "never committed" in c["consent"]["basis"]
    assert c["turns"][0]["source"] == "locomo10.json#0/D1:1"
    assert c["turns"][2]["date"] == "2:00 pm on 9 June, 2023" and c["turns"][2]["session"] == 2
    cats = {q["category"]: q for q in qs}
    assert cats["adversarial"]["gold"] == "not mentioned"
    assert cats["temporal"]["evidence"] == ["D2:1"]


def test_l06_no_path_gives_a_clear_error(monkeypatch):
    monkeypatch.delenv(L.ENV, raising=False)
    with pytest.raises(FileNotFoundError, match=L.ENV):
        L.load(L.path_from_env())


def test_l07_real_locomo_dev_loads_when_given_else_skips():
    path = L.path_from_env()
    if not path or not os.path.exists(path):
        pytest.skip(f"LoCoMo not given ({L.ENV} unset); kept outside the repository")
    convs, qs = L.load(path)
    assert len(convs) == 5 and qs
