"""IF-T133..IF-T142 (revision 9): the provider-specific documentation source (D-A35) and aggregated readiness
findings with stable identifiers (D-A36). Fake SDK modules and clients only; no HTTP, no provider."""
import sys
import pytest
from engram_interface import (ClaudeAdapter, OpenAIAdapter, check_real_run, RealRunRefused, source_findings,
                              readiness_findings, FAULTS, DOC_HOSTS, profile_hash)
from .helpers import FakeAnthropicClient, FakeOpenAIClient, fake_sdk
from .profiles_fake import claude_for, openai_for

CLAUDE_DOC = "https://platform.claude.com/docs/en/about-claude/models"
OPENAI_DOC = "https://developers.openai.com/api/docs/models"
DAY = "2026-11-25"


def ids(findings, status=None):
    return [(f.id, f.status) if status is None else f.id for f in findings if status is None or f.status == status]


def install(monkeypatch, sdk, version="2.0.0"):
    client = FakeAnthropicClient() if sdk == "anthropic" else FakeOpenAIClient()
    mod = fake_sdk(sdk, "Anthropic" if sdk == "anthropic" else "OpenAI", client)
    mod.__version__ = version
    monkeypatch.setitem(sys.modules, sdk, mod)
    return mod, client


def callable_for(provider, source, limit=8192, pinned=2, client=None):
    if provider == "anthropic":
        p = claude_for("claude-real-fake", max_tokens_limit=limit, source=source)
        return ClaudeAdapter(None, sdk_major=pinned, client=client).kit_callable(p.model, p)
    p = openai_for("openai-real-fake", max_tokens_limit=limit, source=source)
    return OpenAIAdapter(None, sdk_major=pinned, client=client).kit_callable(p.model, p)


# ---- D-A35: provider-specific documentation source ----
def test_t133_the_allowlist_is_reviewed_data_one_host_per_provider():
    assert DOC_HOSTS == {"anthropic": ("platform.claude.com",), "openai": ("developers.openai.com",)}


@pytest.mark.parametrize("provider,doc,ok", [("anthropic", CLAUDE_DOC, True), ("anthropic", OPENAI_DOC, False),
                                             ("openai", OPENAI_DOC, True), ("openai", CLAUDE_DOC, False)])
def test_t134_each_provider_accepts_only_its_own_documentation_host(provider, doc, ok, monkeypatch):
    found = source_findings(f"{doc} (read {DAY})", provider)
    assert (ids(found, "fault") == []) == ok
    if not ok:
        assert ids(found, "fault") == ["RR-07"]
    mod, client = install(monkeypatch, provider)
    fn = callable_for(provider, f"{doc} (read {DAY})")
    if ok:
        assert check_real_run(fn)["provider"] == provider
    else:
        with pytest.raises(RealRunRefused) as e:
            check_real_run(fn)
        assert [f.id for f in e.value.faults] == ["RR-07"]
    assert mod.made == [] and client.calls == []


DECEPTIVE = [  # (source URL, expected fault)
    ("https://platform.claude.com.evil.com/docs", "RR-07"),
    ("https://evil.com/platform.claude.com", "RR-07"),
    ("https://platform.claude.com@evil.com/docs", "RR-06"),
    ("https://user:pw@platform.claude.com/docs", "RR-06"),
    ("https://evilplatform.claude.com/docs", "RR-07"),
    ("https://claude.com/docs", "RR-07"),
    ("http://platform.claude.com/docs", "RR-06"),
    ("ftp://platform.claude.com/docs", "RR-06"),
    ("https://platform.c1aude.com/docs", "RR-07"),
    ("https://platform.claude.com./docs", "RR-06"),
    ("https://platform.claude.com:8443/docs", "RR-06"),
    ("https://platform.claude.com․evil/docs", "RR-06"),     # non-ASCII one-dot leader
    ("https://platform.сlaude.com/docs", "RR-06"),               # Cyrillic es
    ("https://xn--platform-claude-xyz.com/docs", "RR-06"),            # punycode label
    ("https://platform.xn--claude-abc.com/docs", "RR-06"),
    ("https://platform%2Eclaude.com/docs", "RR-06"),
    ("https://platform.claude.com\\@evil.com/docs", "RR-06"),
]


@pytest.mark.parametrize("url,fault", DECEPTIVE)
def test_t135_deceptive_urls_are_refused(url, fault):
    assert ids(source_findings(f"{url} (read {DAY})", "anthropic"), "fault") == [fault]


@pytest.mark.parametrize("url", ["https://platform.claude.com/docs/en/x", "https://PLATFORM.Claude.COM/docs",
                                 "https://platform.claude.com", "https://platform.claude.com/docs?x=1#y",
                                 "https://platform.claude.com:443/docs"])   # r10 (D-A38): moved from T135; :443 accepted
def test_t136_plain_https_urls_on_the_exact_host_are_accepted_case_insensitively(url):
    assert ids(source_findings(f"{url} (read {DAY})", "anthropic"), "fault") == []
    assert ids(source_findings(f"Read {DAY} at {url}.", "anthropic"), "fault") == []


@pytest.mark.parametrize("source,fault", [
    (f"no link, read {DAY}", "RR-05"),
    (f"{CLAUDE_DOC} and {CLAUDE_DOC}/other (read {DAY})", "RR-05"),
    (f"{CLAUDE_DOC} https://evil.com (read {DAY})", "RR-05"),
    (f"{CLAUDE_DOC} (no date)", "RR-08"),
    (f"{CLAUDE_DOC} read {DAY} and 2026-11-24", "RR-08"),
    (f"{CLAUDE_DOC} read 20261125", "RR-08"),
    (f"{CLAUDE_DOC}/2026-11-25/page (undated otherwise)", "RR-08"),      # a date inside the URL is not the reading date
    (f"{CLAUDE_DOC} read 2026-02-30", "RR-09"),
    (f"{CLAUDE_DOC} read 2026-13-01", "RR-09"),
    ("", "RR-05"), ("   ", "RR-05"),
])
def test_t137_exactly_one_url_and_exactly_one_real_date(source, fault):
    assert fault in ids(source_findings(source, "anthropic"), "fault")


# ---- D-A36: aggregated, ordered, structured findings ----
def test_t138_every_fault_is_reported_in_order_before_any_client_or_call(monkeypatch):
    mod, client = install(monkeypatch, "anthropic", "3.1.0")
    fn = callable_for("anthropic", f"{OPENAI_DOC} and {CLAUDE_DOC} read 2026-02-30", limit=None, pinned=2)
    with pytest.raises(RealRunRefused) as e:
        check_real_run(fn)
    assert ids(e.value.findings) == [("RR-04", "fault"), ("RR-05", "fault"), ("RR-06", "skipped"),
                                     ("RR-07", "skipped"), ("RR-09", "fault"), ("RR-14", "fault")]
    assert [f.id for f in e.value.faults] == ["RR-04", "RR-05", "RR-09", "RR-14"]
    assert mod.made == [] and client.calls == []
    text = str(e.value)
    assert text.index("RR-04") < text.index("RR-05") < text.index("RR-09") < text.index("RR-14")


def test_t139_dependencies_are_reported_as_skipped_not_invented(monkeypatch):
    mod, client = install(monkeypatch, "openai", "dev")
    a = OpenAIAdapter(None, sdk_major=None)
    found, _ = readiness_findings(a, profile=None)
    assert ids(found) == [("RR-01", "fault"), ("RR-02", "skipped"), ("RR-03", "fault"), ("RR-04", "skipped"),
                          ("RR-05", "skipped"), ("RR-06", "skipped"), ("RR-07", "skipped"), ("RR-08", "skipped"),
                          ("RR-09", "skipped"), ("RR-12", "fault"), ("RR-13", "fault"), ("RR-14", "skipped")]
    byid = {f.id: f for f in found}
    assert byid["RR-02"].because == ("RR-01", "RR-03") and byid["RR-14"].because == ("RR-12", "RR-13")
    assert all(f.because == ("RR-01",) for i, f in byid.items() if i in ("RR-04", "RR-05", "RR-06", "RR-07", "RR-08", "RR-09"))
    injected = callable_for("openai", f"{OPENAI_DOC} read {DAY}", client=FakeOpenAIClient())
    found, _ = readiness_findings(injected)
    assert ids(found) == [("RR-10", "fault"), ("RR-11", "skipped"), ("RR-12", "skipped"), ("RR-13", "skipped"),
                          ("RR-14", "skipped")]
    assert mod.made == [] and client.calls == []


def test_t140_findings_are_deterministic_and_use_the_stable_table(monkeypatch):
    install(monkeypatch, "anthropic", "1.0.0")
    fn = callable_for("anthropic", "https://evil.com 2026-02-30 2026-02-31", limit=None)
    runs = [ids(readiness_findings(fn)[0]) for _ in range(5)]
    assert all(r == runs[0] for r in runs)
    order = list(FAULTS)
    assert [order.index(i) for i, _ in runs[0]] == sorted(order.index(i) for i, _ in runs[0])
    assert list(FAULTS) == [f"RR-{n:02d}" for n in range(1, 15)]
    for f in readiness_findings(fn)[0]:
        assert f.id in FAULTS and f.status in ("fault", "skipped") and f.message.startswith(FAULTS[f.id])


@pytest.mark.parametrize("provider,doc", [("anthropic", CLAUDE_DOC), ("openai", OPENAI_DOC)])
def test_t141_a_ready_callable_returns_the_six_field_record(provider, doc, monkeypatch):
    mod, client = install(monkeypatch, provider, "2.5.0")
    fn = callable_for(provider, f"{doc} (read {DAY})")
    rec = check_real_run(fn)
    assert set(rec) == {"provider", "model", "sdk_version", "sdk_major", "profile_hash", "api_version"}
    assert rec["sdk_version"] == "2.5.0" and rec["profile_hash"] == profile_hash(fn.profile)
    assert (rec["api_version"] is None) == (provider == "openai")
    assert mod.made == [] and client.calls == []


def test_t142_an_sdk_that_is_not_installed_is_a_finding_not_a_crash(monkeypatch):
    monkeypatch.setitem(sys.modules, "anthropic", None)
    fn = callable_for("anthropic", f"{CLAUDE_DOC} (read {DAY})")
    with pytest.raises(RealRunRefused) as e:
        check_real_run(fn)
    assert ids(e.value.findings) == [("RR-11", "fault"), ("RR-13", "skipped"), ("RR-14", "skipped")]
