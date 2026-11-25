"""IF-T143..IF-T152 (revision 10): explicit :443 only, judged on the parsed authority (D-A38); bare domains and
www addresses counted as addresses (D-A40); percent-encoding, non-ASCII and punycode judged on the hostname only
(D-A42, D-A43); exact host match, user-info rejection, backslash rejection and the allowlist unchanged.
No network; fake SDK modules only."""
import sys
import pytest
from engram_interface import (ClaudeAdapter, OpenAIAdapter, check_real_run, RealRunRefused, source_findings, FAULTS)
from .helpers import FakeAnthropicClient, FakeOpenAIClient, fake_sdk
from .profiles_fake import claude_for, openai_for

DAY = "2026-11-25"
CLAUDE = "https://platform.claude.com/docs/en/about-claude/models"
OPENAI = "https://developers.openai.com/api/docs/models"


def faults(source, provider="anthropic"):
    return [f.id for f in source_findings(source, provider) if f.status == "fault"]


def install(monkeypatch, sdk):
    client = FakeAnthropicClient() if sdk == "anthropic" else FakeOpenAIClient()
    mod = fake_sdk(sdk, "Anthropic" if sdk == "anthropic" else "OpenAI", client)
    monkeypatch.setitem(sys.modules, sdk, mod)
    return mod, client


# ---- D-A38: explicit :443 only, judged on the parsed authority ----
@pytest.mark.parametrize("provider,url", [("anthropic", "https://platform.claude.com:443/docs"),
                                          ("openai", "https://developers.openai.com:443/api/docs"),
                                          ("anthropic", "https://platform.claude.com:443"),
                                          ("anthropic", "https://Platform.Claude.Com:443/docs?x=1")])
def test_t143_an_explicit_443_is_accepted_on_the_exact_host(provider, url, monkeypatch):
    assert faults(f"{url} (read {DAY})", provider) == []
    mod, client = install(monkeypatch, provider)
    if provider == "anthropic":
        p = claude_for("c", max_tokens_limit=8192, source=f"{url} (read {DAY})")
        fn = ClaudeAdapter(None, sdk_major=2).kit_callable("c", p)
    else:
        p = openai_for("o", max_tokens_limit=8192, source=f"{url} (read {DAY})")
        fn = OpenAIAdapter(None, sdk_major=2).kit_callable("o", p)
    assert check_real_run(fn)["provider"] == provider and mod.made == [] and client.calls == []


@pytest.mark.parametrize("authority", ["platform.claude.com:8443", "platform.claude.com:80", "platform.claude.com:0443",
                                       "platform.claude.com:443x", "platform.claude.com:", "platform.claude.com:abc",
                                       "platform.claude.com:443:443", "platform.claude.com:+443", "platform.claude.com:4430",
                                       "[::1]:443"])
def test_t144_every_other_or_malformed_port_is_refused(authority):
    assert faults(f"https://{authority}/docs (read {DAY})") == ["RR-06"]


@pytest.mark.parametrize("url", ["https://platform.claude.com/docs:8443", "https://platform.claude.com/docs?p=:8443",
                                 "https://platform.claude.com/docs#:8443", "https://platform.claude.com/a:b/c:0443",
                                 "https://platform.claude.com?port=:80"])
def test_t145_port_like_text_outside_the_authority_is_not_a_port(url):
    assert faults(f"{url} (read {DAY})") == []


# ---- D-A40: bare domains and www addresses are addresses ----
@pytest.mark.parametrize("source,expected", [
    (f"www.example.com (read {DAY})", ["RR-06"]),                  # a lone www address: not an explicit https URL
    (f"WWW.platform.claude.com/docs (read {DAY})", ["RR-06"]),
    (f"www.example.xyz (read {DAY})", ["RR-06"]),                  # www counts whatever its top-level label
    (f"{CLAUDE} and www.example.museum (read {DAY})", ["RR-05"]),
    (f"platform.claude.com/docs (read {DAY})", ["RR-06"]),         # even the right host, written bare
    (f"Platform.Claude.COM (read {DAY})", ["RR-06"]),
    (f"{CLAUDE} and www.example.com (read {DAY})", ["RR-05"]),     # a URL plus a bare address: two candidates
    (f"{CLAUDE} see evil.com (read {DAY})", ["RR-05"]),
    (f"{CLAUDE} (mirror: claude.com/docs) read {DAY}", ["RR-05"]),
    (f"({CLAUDE}), read {DAY}", []),                               # one URL, one date
])
def test_t146_bare_domains_and_www_addresses_count_as_addresses(source, expected):
    assert faults(source) == expected


@pytest.mark.parametrize("extra", ["SDK 2.0.0", "notes.md", "report.pdf", "v1.2", "e.g.", "i.e.", "a@b.com",
                                   "section 4.17", "3.14", "file.tar.gz", "model claude-x.5", "cfg.json"])
def test_t147_version_numbers_file_names_and_emails_are_not_addresses(extra):
    assert faults(f"{CLAUDE} {extra} (read {DAY})") == []


# ---- correction A: percent-encoding judged on the hostname only ----
@pytest.mark.parametrize("url", ["https://platform.claude.com/docs?next=%2Fmodels",
                                 "https://platform.claude.com?next=%2Fmodels",
                                 "https://platform.claude.com/docs#%E2%9C%93",
                                 "https://platform.claude.com/docs/a%20b"])
def test_t148_percent_encoding_outside_the_hostname_is_accepted(url):
    assert faults(f"{url} (read {DAY})") == []


@pytest.mark.parametrize("url", ["https://platform%2Eclaude.com/docs", "https://platform.claude.co%6D/docs",
                                 "https://%70latform.claude.com/"])
def test_t149_percent_encoding_in_the_hostname_is_still_refused(url):
    assert faults(f"{url} (read {DAY})") == ["RR-06"]


# ---- correction B: non-ASCII and punycode judged on the hostname only ----
@pytest.mark.parametrize("url", ["https://platform.claude.com/docs/café", "https://platform.claude.com/docs?q=naïve",
                                 "https://platform.claude.com/docs#✓", "https://platform.claude.com/xn--path/page"])
def test_t150_a_unicode_or_punycode_path_query_or_fragment_is_accepted_when_the_host_is_exact(url):
    assert faults(f"{url} (read {DAY})") == []


@pytest.mark.parametrize("url", ["https://platform.сlaude.com/docs", "https://xn--platform-x.claude.com/docs",
                                 "https://platform.claude.cöm/", "https://platform.XN--claude.com/"])
def test_t151_a_unicode_or_punycode_hostname_is_still_refused(url):
    assert faults(f"{url} (read {DAY})") == ["RR-06"]


# ---- not weakened: exact host, user-info, backslash, allowlist ----
@pytest.mark.parametrize("source,expected", [
    (f"https://u@platform.claude.com:443/docs {DAY}", ["RR-06"]),
    (f"https://platform.claude.com:443@evil.com/docs {DAY}", ["RR-06"]),
    (f"https://platform.claude.com/docs\\x {DAY}", ["RR-06"]),           # a backslash anywhere, path included
    (f"https://platform.claude.com.evil.com:443/docs {DAY}", ["RR-07"]),
    (f"https://evilplatform.claude.com:443/ {DAY}", ["RR-07"]),
    (f"{OPENAI} {DAY}", ["RR-07"]),
    (f"https://developers.openai.com:443/x?y=%2F {DAY}", ["RR-07"]),
])
def test_t152_exact_host_user_info_backslash_and_allowlist_are_unchanged(source, expected):
    assert faults(source) == expected
    assert FAULTS["RR-05"].startswith("the source does not hold exactly one address")
    assert "bare domain" in FAULTS["RR-06"] and "port other than 443" in FAULTS["RR-06"]
