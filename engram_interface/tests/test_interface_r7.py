"""IF-T107..IF-T122 (revision 7): profile schema integrity (R7-A, his revision 7 scope), the canonical profile hash (D-A28), the
Anthropic SDK major-version pin (D-A27) and the five extra kinds (D-A30).
Profiles are checked when constructed, before any SDK client is made or called. The adapter tests check the
arguments given to fake SDK clients and their constructors, not HTTP traffic or provider acceptance."""
import hashlib
import json
import sys
import pytest
from engram_interface import (ClaudeAdapter, OpenAIAdapter, ClaudeProfile, OpenAIProfile, profile_hash, profile_canon,
                              canonical_json, CANON_SCHEMA)
from .helpers import FakeAnthropicClient, FakeOpenAIClient, fake_sdk, memory_with_facts, claude_adapter
from .profiles_fake import LEGACY, ADAPTIVE, O_PLAIN, NONE, DEFAULT, OLD_VERSION, claude_for, openai_for

PROMPT = "Excerpts:\n- Alice: I moved to Leeds.\n\nQuestion: Where does Alice live?\n"
NAN, INF = float("nan"), float("inf")


def claude(**kw):
    return claude_for("m", **kw)


def openai(**kw):
    return openai_for("m", **kw)


# ---- R7-A: profile schema integrity ----
@pytest.mark.parametrize("value", ["off", "", "Disabled", 0, True, ("omit",)])
def test_t107_none_sends_must_be_a_supported_value(value):
    with pytest.raises(ValueError):
        claude(none_sends=value)
    for ok in ("omit",):
        assert claude(none_sends=ok).none_sends == ok


@pytest.mark.parametrize("deprecated", [("adaptive",), ("manual", "adaptive"), ("unknown",)])
def test_t108_deprecated_modes_must_be_supported_modes(deprecated):
    with pytest.raises(ValueError):
        claude(modes=("none", "manual"), deprecated=deprecated)
    assert claude(modes=("none", "manual"), deprecated=("manual",)).deprecated == ("manual",)


@pytest.mark.parametrize("v", ["2026-13-01", "2026-02-30", "2026-1-21", "20261021", "2026-10-21x", " 2026-10-21",
                               "latest", "2026/10/21", 20261021, None, "0000-00-00"])
def test_t109_api_version_must_be_a_real_yyyy_mm_dd_date(v):
    with pytest.raises(ValueError):
        claude(api_version=v, temperature=None, extras=())   # no temperature or extras, so only the version is tested
    assert claude(api_version="2024-02-29").api_version == "2024-02-29"      # a real leap day


@pytest.mark.parametrize("make", [claude, openai])
@pytest.mark.parametrize("t", [("0", "1"), (0, NAN), (0, INF), (-INF, 1), (1, 0), (-0.5, 1), (0,), (0, 1, 2),
                               [0, 1], (True, 1), "0-1", 1])
def test_t110_temperature_range_must_be_valid(make, t):
    with pytest.raises(ValueError):
        make(temperature=t)
    assert make(temperature=(0, 1)).temperature == (0, 1) and make(temperature=None).temperature is None
    assert make(temperature=(0.5, 0.5)).temperature == (0.5, 0.5)


@pytest.mark.parametrize("field", ["min_budget", "min_output_tokens"])
@pytest.mark.parametrize("bad", [0, -1, 1.5, "16", True, None])
def test_t111_token_limits_must_be_whole_numbers_above_zero(field, bad):
    make = claude if field == "min_budget" else openai
    with pytest.raises(ValueError):
        make(**{field: bad})
    with pytest.raises(ValueError):
        make(max_tokens_limit=bad if bad is not None else 0)
    with pytest.raises(ValueError):
        make(**{field: 2048, "max_tokens_limit": 1024})                       # least above most
    assert make(**{field: 1024, "max_tokens_limit": 1024}).max_tokens_limit == 1024


@pytest.mark.parametrize("make", [claude, openai])
@pytest.mark.parametrize("c", [
    ("k", "int"), ("k", "int", 1), ("k", "int", 1, 2, 3), ("k", "int", 1.0, 2), ("k", "int", "1", "2"),
    ("k", "int", True, 5), ("k", "int", 5, 1),
    ("k", "number"), ("k", "number", 0), ("k", "number", 0, NAN), ("k", "number", "0", 1), ("k", "number", 2, 1),
    ("k", "dict", 1), ("k", "dict", ()),
    ("k", "choice"), ("k", "choice", ()), ("k", "choice", "ab"), ("k", "choice", ("a",), ("b",)),
    ("k", "choice", (["a"],)), ("k", "choice", (NAN,)),
    ("k", "str", 1), ("k", "str", "x"),
])
def test_t112_extra_constraints_need_the_right_arguments_for_their_kind(make, c):
    with pytest.raises(ValueError):
        make(extras=(c,))


@pytest.mark.parametrize("make", [claude, openai])
def test_t113_valid_constraints_of_each_kind_are_accepted(make):
    p = make(extras=(("a", "int", 1, 5), ("b", "number", 0, 1.5), ("c", "dict"), ("d", "choice", ("x", 1, True)),
                     ("e", "str")))
    assert [c[0] for c in p.extras] == ["a", "b", "c", "d", "e"]


@pytest.mark.parametrize("make", [claude, openai])
@pytest.mark.parametrize("extras", [(("k", "dict"), ("k", "str")), (("", "dict"),), (("  ", "dict"),),
                                    ((None, "dict"),), ((1, "dict"),)])
def test_t114_extra_names_must_be_non_empty_and_unique(make, extras):
    with pytest.raises(ValueError):
        make(extras=extras)


@pytest.mark.parametrize("make", [claude, openai])
@pytest.mark.parametrize("kind", ["list", "nested", "object", "bool", "INT", "", None])
def test_t115_only_the_five_extra_kinds_are_supported(make, kind):
    with pytest.raises(ValueError):
        make(extras=(("k", kind),))


def test_t116_an_invalid_profile_fails_at_construction_before_any_client(monkeypatch):
    client = FakeAnthropicClient()
    mod = fake_sdk("anthropic", "Anthropic", client)
    monkeypatch.setitem(sys.modules, "anthropic", mod)
    o = FakeOpenAIClient()
    omod = fake_sdk("openai", "OpenAI", o)
    monkeypatch.setitem(sys.modules, "openai", omod)
    bad = [lambda: claude(none_sends="off"), lambda: claude(deprecated=("adaptive",)), lambda: claude(api_version="2026-02-30"),
           lambda: claude(temperature=(1, 0)), lambda: claude(min_budget=0), lambda: claude(extras=(("k", "int"),)),
           lambda: claude(extras=(("k", "dict"), ("k", "dict"))), lambda: openai(extras=(("k", "list"),)),
           lambda: openai(temperature=(0, INF)), lambda: openai(min_output_tokens=0)]
    for build in bad:
        with pytest.raises(ValueError):
            ClaudeAdapter(None, sdk_major=2).kit_callable("m", build())
    assert mod.made == [] and client.calls == [] and omod.made == [] and o.calls == []


# ---- D-A28: the canonical profile hash ----
def oracle(profile, schema=CANON_SCHEMA):
    """The test's own statement of the canonical form: written out here, not taken from the sketch."""
    fields = {k: (list(map(lambda v: list(v) if isinstance(v, tuple) else v, val)) if isinstance(val, tuple) else val)
              for k, val in vars(profile).items()}
    body = {"schema": schema, "kind": type(profile).__name__, "fields": fields}
    text = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_t117_the_hash_is_sha256_over_the_stated_canonical_json():
    for p in (LEGACY, ADAPTIVE, O_PLAIN, claude(source="Café — docs read 25 Nov 2026")):
        assert profile_hash(p) == oracle(p)
        canon = profile_canon(p)
        assert set(canon) == {"schema", "kind", "fields"} and canon["schema"] == CANON_SCHEMA
        assert canon["kind"] == type(p).__name__ and "source" in canon["fields"]
    text = canonical_json(profile_canon(claude(source="Café")))
    assert "Café" in text and "\\u00e9" not in text and ", " not in text and ": " not in text


def test_t118_same_profile_same_hash_and_changes_show():
    assert profile_hash(claude()) == profile_hash(claude())
    assert profile_hash(claude(source="a")) != profile_hash(claude(source="b"))
    assert profile_hash(LEGACY, schema=CANON_SCHEMA) != profile_hash(LEGACY, schema="engram-profile-canon/2")
    assert profile_hash(claude(min_budget=1024)) != profile_hash(claude(min_budget=2048))
    assert profile_hash(claude_for("m")) != profile_hash(openai_for("m"))       # the kind is part of the hash


def test_t119_canonical_json_ignores_key_order_and_tuple_versus_list_and_refuses_non_finite():
    assert canonical_json({"a": 1, "b": (2, 3)}) == canonical_json({"b": [2, 3], "a": 1}) == '{"a":1,"b":[2,3]}'
    for bad in ({"x": NAN}, {"x": INF}, {"x": (1, -INF)}, [NAN]):
        with pytest.raises(ValueError):
            canonical_json(bad)


def test_t120_the_hash_travels_with_each_call():
    c = FakeAnthropicClient()
    fn = ClaudeAdapter(None, client=c).kit_callable(LEGACY.model, LEGACY)
    _, usage, _ = fn(PROMPT, max_tokens=60, temperature="default", reasoning=NONE)
    assert usage["profile_hash"] == profile_hash(LEGACY) == fn.profile_hash
    m, _ = memory_with_facts()
    r = claude_adapter(m, client=FakeAnthropicClient()).answer("Where does Alice live?", 500)
    assert r.profile_hash == profile_hash(claude_for("model-under-test"))


# ---- D-A27: the Anthropic SDK major version is pinned ----
@pytest.mark.parametrize("installed,pinned,ok", [("2.0.0", 2, True), ("2.7.1", 2, True), ("1.99.0", 2, False),
                                                  ("3.0.0", 2, False), ("2.0.0", None, False), (None, 2, False),
                                                  ("dev", 2, False)])
def test_t121_the_sdk_major_is_pinned_and_the_exact_version_recorded(installed, pinned, ok, monkeypatch):
    client = FakeAnthropicClient()
    mod = fake_sdk("anthropic", "Anthropic", client)
    mod.__version__ = installed
    monkeypatch.setitem(sys.modules, "anthropic", mod)
    fn = ClaudeAdapter(None, sdk_major=pinned).kit_callable(LEGACY.model, LEGACY)
    if ok:
        _, usage, _ = fn(PROMPT, max_tokens=60, temperature="default", reasoning=NONE)
        assert usage["sdk_version"] == installed and len(mod.made) == 1
    else:
        with pytest.raises(ValueError):
            fn(PROMPT, max_tokens=60, temperature="default", reasoning=NONE)
        assert mod.made == [] and client.calls == []


def test_t122_the_profiles_token_limit_ceiling_is_checked_before_the_call():
    c = FakeAnthropicClient()
    p = claude(max_tokens_limit=4096)
    fn = ClaudeAdapter(None, client=c).kit_callable("m", p)
    with pytest.raises(ValueError):
        fn(PROMPT, max_tokens=4097, temperature="default", reasoning=NONE)
    fn(PROMPT, max_tokens=4096, temperature="default", reasoning=NONE)
    o = FakeOpenAIClient()
    q = openai(max_tokens_limit=100)
    gn = OpenAIAdapter(None, client=o).kit_callable("m", q)
    with pytest.raises(ValueError):
        gn(PROMPT, max_tokens=101, temperature="default", reasoning=DEFAULT)
    assert len(c.calls) == 1 and o.calls == []
