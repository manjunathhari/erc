"""TK-A: the arm protocol, the A to D registry and the stub memory."""
import pytest

from engram_testkit import arms as A


def test_a01_registry_has_slots_a_to_d_with_a_to_c_defined_and_d_reserved():
    assert list(A.SLOTS) == ["A", "B", "C", "D"]
    assert [A.SLOTS[k].status for k in "ABCD"] == ["defined", "defined", "defined", "reserved"]
    assert [A.SLOTS[k].stage for k in "ABCD"] == [4, 4, 4, 6]


def test_a02_registry_refuses_reserved_d_unknown_slots_and_non_arms():
    with pytest.raises(A.ReservedSlot):
        A.Registry().bind("D", A.StubMemory())
    with pytest.raises(KeyError):
        A.Registry().bind("E", A.StubMemory())

    class Half:
        def ingest(self, c): pass
    with pytest.raises(A.NotAnArm):
        A.Registry().bind("A", Half())


def test_a03_stub_memory_finds_the_evidence_turn(synthetic):
    convs, _ = synthetic
    m = A.StubMemory(k=3)
    m.ingest(convs["syn-1"])
    got = m.retrieve("What is the name of Ines's cat?", conversation="syn-1")
    assert "s1:2" in got.turn_ids and "Pepper" in got.context and got.tokens > 0


def test_a04_stub_retrieval_stays_inside_the_question_conversation(synthetic):
    convs, _ = synthetic
    m = A.StubMemory(k=10)
    for c in convs.values():
        m.ingest(c)
    got = m.retrieve("Where is Mara travelling in October?", conversation="syn-3")
    assert got.turn_ids and all(t.startswith("s3:") for t in got.turn_ids)


def test_a05_empty_memory_and_reset_give_nothing(synthetic):
    convs, _ = synthetic
    m = A.StubMemory()
    assert m.retrieve("anything at all").turn_ids == []
    m.ingest(convs["syn-2"])
    m.reset()
    assert m.retrieve("What is Rhea allergic to?").context == ""


def test_a06_kit_does_not_import_the_unbuilt_interface_package():
    import sys
    import engram_testkit.dry_run  # noqa: F401  (loads every module of the kit)
    assert "engram_interface" not in sys.modules
