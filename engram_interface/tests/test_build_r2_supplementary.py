"""BUILD-STAGE SUPPLEMENTARY CHECKS (P-A build revision 2). Not part of the frozen r10 tests-first package.

Added at his review of build revision 1 (25 Nov 2026, 20:29), points A and B:
  A. DOC_HOSTS and FAULTS are read-only mappings with immutable values; FAULT_ORDER is a separate tuple and
     findings follow it, not the iteration order of a mapping; the reviewed data cannot be rebound through the
     package or the module.
  B. Profile fields the r10 specification describes only as values "drawn from" a set (section 4.12: modes,
     deprecated, efforts, none_efforts) accept a tuple or a list and are stored as tuples, so the profile and its
     hash cannot change when the caller's list changes later. Fields the specification states as tuples
     (temperature, extras, each extra constraint, a choice's values) stay tuple-only.
No frozen r10 test or assertion is changed by this file. Fake SDK modules only; no network, no key.
Supplementary test ids are S01 to S12.
"""
import sys
import types
import pytest
import engram_interface
from engram_interface import (readiness, ClaudeProfile, OpenAIProfile, ClaudeAdapter, FAULTS, FAULT_ORDER, DOC_HOSTS,
                              BARE_TLDS, profile_hash, source_findings, readiness_findings)
from .helpers import FakeAnthropicClient, fake_sdk
from .profiles_fake import claude_for, openai_for

CLAUDE_DOC = "https://platform.claude.com/docs/en/about-claude/models (read 2026-11-25)"
def _restore(mapping, snapshot):
    """If a mutation got through (the rule is broken), put the contents back so no other test sees it."""
    if isinstance(mapping, dict) and dict(mapping) != snapshot:
        mapping.clear()
        mapping.update(snapshot)


MUTATORS = (
    lambda m: m.__setitem__("RR-99", "x"),
    lambda m: m.__delitem__(next(iter(m))),
    lambda m: m.update({"RR-99": "x"}),
    lambda m: m.pop(next(iter(m))),
    lambda m: m.clear(),
    lambda m: m.setdefault("RR-99", "x"),
)


# ---- A: immutable reviewed data ----
@pytest.mark.parametrize("mutate", MUTATORS)
def test_s01_faults_cannot_be_modified(mutate):
    before = dict(FAULTS)
    try:
        assert isinstance(FAULTS, types.MappingProxyType)
        with pytest.raises((TypeError, AttributeError)):
            mutate(FAULTS)
        assert dict(FAULTS) == before and all(isinstance(v, str) for v in FAULTS.values())
    finally:
        _restore(FAULTS, before)


@pytest.mark.parametrize("mutate", MUTATORS)
def test_s02_doc_hosts_cannot_be_modified(mutate):
    before = dict(DOC_HOSTS)
    try:
        assert isinstance(DOC_HOSTS, types.MappingProxyType)
        with pytest.raises((TypeError, AttributeError)):
            mutate(DOC_HOSTS)
        assert dict(DOC_HOSTS) == {"anthropic": ("platform.claude.com",), "openai": ("developers.openai.com",)}
    finally:
        _restore(DOC_HOSTS, before)


def test_s03_a_host_tuple_cannot_be_mutated_and_the_rule_is_unchanged_after_attempts():
    before = {k: (list(v) if isinstance(v, list) else v) for k, v in DOC_HOSTS.items()}
    try:
        for hosts in DOC_HOSTS.values():
            assert isinstance(hosts, tuple)
            with pytest.raises(AttributeError):
                hosts.append("evil.com")
            with pytest.raises(TypeError):
                hosts[0] = "evil.com"
        with pytest.raises(TypeError):
            DOC_HOSTS["anthropic"] += ("evil.com",)
        assert [f.id for f in source_findings("https://evil.com/docs (read 2026-11-25)", "anthropic")] == ["RR-07"]
        assert source_findings(CLAUDE_DOC, "anthropic") == []
    finally:
        for k, v in before.items():                     # undo any mutation that got through
            if isinstance(DOC_HOSTS, dict):
                DOC_HOSTS[k] = v
            elif isinstance(DOC_HOSTS[k], list):
                DOC_HOSTS[k][:] = v


def test_s04_fault_order_is_a_separate_immutable_tuple():
    assert isinstance(FAULT_ORDER, tuple) and FAULT_ORDER == tuple(f"RR-{n:02d}" for n in range(1, 15))
    assert tuple(FAULTS) == FAULT_ORDER and isinstance(BARE_TLDS, tuple)
    with pytest.raises(AttributeError):
        FAULT_ORDER.append("RR-15")
    with pytest.raises(TypeError):
        FAULT_ORDER[0] = "RR-99"


@pytest.mark.parametrize("module", [engram_interface, readiness], ids=["package", "readiness"])
@pytest.mark.parametrize("name", ["DOC_HOSTS", "FAULTS", "FAULT_ORDER", "BARE_TLDS"])
def test_s05_reviewed_data_cannot_be_rebound_or_deleted_through_a_module(module, name):
    original = getattr(module, name)
    # Build r3: a private MonkeyPatch, not the fixture. pytest records the restoration before the guarded module
    # refuses the assignment; with the fixture, that failed restoration was replayed at teardown as an error.
    # The refusal is still asserted; the recorded restoration is discarded here, under the test's control.
    mp = pytest.MonkeyPatch()
    try:
        with pytest.raises(AttributeError):
            setattr(module, name, {"anthropic": ("evil.com",)})
        with pytest.raises(AttributeError):
            delattr(module, name)
        with pytest.raises(AttributeError):
            mp.setattr(module, name, {})
        assert getattr(module, name) is original
        assert getattr(engram_interface, name) is getattr(readiness, name)
    finally:      # if the guard failed, put the original back so no other test sees the rebinding
        try:
            mp.undo()     # restoring the unchanged original is itself refused by the guard; nothing to undo
        except AttributeError:
            pass
        if module.__dict__.get(name) is not original:
            types.ModuleType.__setattr__(module, name, original)


def test_s06_findings_follow_fault_order_not_the_iteration_order_of_faults(monkeypatch):
    """A low-level bypass of the module guard stands in a FAULTS whose iteration order is reversed. The findings
    must still come in FAULT_ORDER."""
    client = FakeAnthropicClient()
    monkeypatch.setitem(sys.modules, "anthropic", fake_sdk("anthropic", "Anthropic", client))
    sys.modules["anthropic"].__version__ = "1.0.0"
    p = claude_for("c", source="https://evil.com 2026-02-30 2026-02-31")      # RR-04, RR-07, RR-08, RR-09, RR-14
    fn = ClaudeAdapter(None, sdk_major=2).kit_callable("c", p)
    original = readiness.FAULTS
    reversed_faults = types.MappingProxyType({k: original[k] for k in reversed(FAULT_ORDER)})
    types.ModuleType.__setattr__(readiness, "FAULTS", reversed_faults)
    try:
        found, _ = readiness_findings(fn)
    finally:
        types.ModuleType.__setattr__(readiness, "FAULTS", original)
    ids = [f.id for f in found]
    assert ids == sorted(ids, key=FAULT_ORDER.index) and ids[0] == "RR-04" and ids[-1] == "RR-14"
    assert readiness.FAULTS is original and client.calls == []


# ---- B: profile sequences ----
LIST_FIELDS = {"modes": ["none", "manual", "adaptive"], "efforts": ["low", "high"], "none_efforts": ["low"],
               "deprecated": ["manual"]}


def claude_lists():
    return dict(modes=list(LIST_FIELDS["modes"]), efforts=list(LIST_FIELDS["efforts"]),
                none_efforts=list(LIST_FIELDS["none_efforts"]), deprecated=list(LIST_FIELDS["deprecated"]))


def test_s07_claude_lists_are_accepted_where_permitted_and_stored_as_tuples():
    from_lists = claude_for("m", **claude_lists())
    from_tuples = claude_for("m", **{k: tuple(v) for k, v in LIST_FIELDS.items()})
    for name in LIST_FIELDS:
        assert isinstance(getattr(from_lists, name), tuple) and getattr(from_lists, name) == tuple(LIST_FIELDS[name])
    assert from_lists == from_tuples and profile_hash(from_lists) == profile_hash(from_tuples)


def test_s08_openai_efforts_list_is_accepted_and_stored_as_a_tuple():
    a = openai_for("o", efforts=["low", "medium"])
    b = openai_for("o", efforts=("low", "medium"))
    assert a.efforts == ("low", "medium") and isinstance(a.efforts, tuple)
    assert a == b and profile_hash(a) == profile_hash(b)


def test_s09_mutating_the_callers_lists_afterwards_changes_neither_the_profile_nor_its_hash():
    given = claude_lists()
    p = claude_for("m", **given)
    before, digest = {n: getattr(p, n) for n in LIST_FIELDS}, profile_hash(p)
    given["modes"].append("bogus"); given["modes"].remove("adaptive")
    given["efforts"].clear(); given["none_efforts"].append("max"); given["deprecated"][0] = "none"
    assert {n: getattr(p, n) for n in LIST_FIELDS} == before and profile_hash(p) == digest
    efforts = ["low", "medium"]
    q = openai_for("o", efforts=efforts)
    h = profile_hash(q)
    efforts.append("high")
    assert q.efforts == ("low", "medium") and profile_hash(q) == h


def test_s10_list_values_are_still_checked():
    with pytest.raises(ValueError):
        claude_for("m", modes=["none", "manual", "bogus"])
    with pytest.raises(ValueError):
        claude_for("m", modes=["none", "manual"], deprecated=["adaptive"])
    with pytest.raises(ValueError):
        openai_for("o", efforts=["low", "extreme"])
    with pytest.raises(ValueError):
        claude_for("m", efforts=["low", 3])


@pytest.mark.parametrize("bad", ["none", {"none", "manual"}, frozenset({"none"}), None, 3])
def test_s11_other_input_types_are_refused_for_the_drawn_from_fields(bad):
    with pytest.raises(ValueError):
        claude_for("m", modes=bad, none_sends=None)
    with pytest.raises(ValueError):
        openai_for("o", efforts=bad)


@pytest.mark.parametrize("make,kw", [
    (claude_for, dict(temperature=[0, 1])),
    (openai_for, dict(temperature=[0, 2])),
    (claude_for, dict(extras=[("top_k", "int", 1, 500)])),
    (openai_for, dict(extras=[("metadata", "dict")])),
    (claude_for, dict(extras=(["top_k", "int", 1, 500],))),
    (openai_for, dict(extras=(("tier", "choice", ["auto", "default"]),))),
])
def test_s12_fields_the_specification_states_as_tuples_stay_tuple_only(make, kw):
    with pytest.raises(ValueError):
        make("m", **kw)
