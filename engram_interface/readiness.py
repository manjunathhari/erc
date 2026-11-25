"""The P-A side of the real comparison-run gate (sections 4.16 to 4.18; D-A31 to D-A43).

`check_real_run(target)` is called by the P-B gate for each callable after the freeze is loaded and before any
provider call. It runs every check, reports every finding in the fixed order of FAULTS with stable identifiers,
and reports a check whose input does not exist as `skipped`, naming what it depends on. Any fault raises
RealRunRefused. It never constructs a client and never calls a provider: the SDK module is imported and its version
read, nothing more. Test runs do not call it.
"""
import datetime
import re
import sys
import types
import urllib.parse
from dataclasses import dataclass

from .adapters import KitCallable, _Adapter, read_major
from .profiles import ClaudeProfile, profile_hash

# Reviewed data. Another documentation host needs an explicitly reviewed change (D-A35).
DOC_HOSTS = types.MappingProxyType({"anthropic": ("platform.claude.com",), "openai": ("developers.openai.com",)})
# Reviewed data (his decision of 25 Nov 2026, 19:25). Adding a top-level name needs a decision and tests.
BARE_TLDS = ("com", "org", "net", "io", "ai", "dev", "app", "co", "uk", "edu", "gov", "info")

# Build r2 (his review of build r1, point A): FAULTS and DOC_HOSTS are read-only mappings with immutable values, and
# findings are ordered by the separate FAULT_ORDER tuple, never by iterating a mapping.
FAULT_ORDER = ("RR-01", "RR-02", "RR-03", "RR-04", "RR-05", "RR-06", "RR-07", "RR-08", "RR-09", "RR-10", "RR-11",
               "RR-12", "RR-13", "RR-14")
FAULTS = types.MappingProxyType({
    "RR-01": "no profile, or a profile of the other provider's kind",
    "RR-02": "the profile names another model than the callable",
    "RR-03": "the callable names no model",
    "RR-04": "the profile does not state max_tokens_limit",
    "RR-05": "the source does not hold exactly one address (an explicit URL, a bare domain or a www address)",
    "RR-06": ("the source address is not a plain explicit https URL (a bare domain or www address, another scheme, "
              "user-info, a port other than 443 or a malformed port, a backslash, or a hostname with "
              "percent-encoding, non-ASCII, punycode, other characters or a trailing dot)"),
    "RR-07": "the source URL's hostname is not on the provider's allowlist",
    "RR-08": "the source does not hold exactly one YYYY-MM-DD date",
    "RR-09": "the source date is not a real calendar date",
    "RR-10": "an injected client: no SDK is loaded, so sdk_version is unknown",
    "RR-11": "the provider's SDK is not installed",
    "RR-12": "the SDK major version is not pinned",
    "RR-13": "the installed SDK version cannot be read",
    "RR-14": "the installed SDK major differs from the pin",
})
if tuple(FAULTS) != FAULT_ORDER:
    raise RuntimeError("FAULTS and FAULT_ORDER disagree")

EXPLICIT_URL = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://\S+")
TRAILING = ".,;:)]}>\"'"
LEADING = "([{<\"'"
LABEL = re.compile(r"[A-Za-z0-9-]+")
HOST_CHARS = re.compile(r"[A-Za-z0-9.-]+")
DATE = re.compile(r"(?<![A-Za-z0-9_-])(\d{4})-(\d{2})-(\d{2})(?![A-Za-z0-9_-])")
ALLOWED_PORT = "443"


@dataclass(frozen=True)
class Finding:
    id: str
    status: str             # "fault" or "skipped"
    message: str            # begins with FAULTS[id]
    because: tuple = ()     # for a skipped check: the failed checks it depends on


class RealRunRefused(ValueError):
    """At least one readiness fault. `.findings` holds every entry in order, `.faults` the faults only."""

    def __init__(self, findings):
        self.findings = tuple(findings)
        self.faults = tuple(f for f in self.findings if f.status == "fault")
        lines = "; ".join(f"{f.id} {f.status}: {f.message}" for f in self.findings)
        super().__init__(f"real comparison run refused ({len(self.faults)} faults): {lines}")


class _Checks:
    """Collects findings; a check whose inputs failed is recorded as skipped, naming them."""

    def __init__(self):
        self.found = []
        self.faults = set()          # checks that found a fault
        self.unmade = set()          # checks that found a fault or could not be made

    def fault(self, fid, detail=""):
        self.faults.add(fid)
        self.unmade.add(fid)
        self.found.append(Finding(fid, "fault", FAULTS[fid] + (f": {detail}" if detail else "")))

    def blocked(self, fid, needs):
        """True, with the check recorded as skipped, when a check it needs was not passed. `because` names the
        faults among `needs` (each table row lists its dependencies in full)."""
        if not any(n in self.unmade for n in needs):
            return False
        because = tuple(n for n in needs if n in self.faults)
        self.unmade.add(fid)
        self.found.append(Finding(fid, "skipped", f"{FAULTS[fid]} (not checked: depends on {', '.join(because)})",
                                  because))
        return True


# ---- the documentation source (section 4.17) ----
def _strip(token, leading=""):
    return token.lstrip(leading).rstrip(TRAILING)


def _is_bare_address(token):
    if token.lower().startswith("www."):
        return True
    labels = token.split("/", 1)[0].split(".")
    return (len(labels) >= 2 and all(LABEL.fullmatch(l) for l in labels) and labels[-1].lower() in BARE_TLDS)


def _addresses(source):
    """(explicit URLs, bare addresses, the text left once every address is removed)."""
    urls, rest = [], []
    last = 0
    for m in EXPLICIT_URL.finditer(source):
        urls.append(_strip(m.group(0)))
        rest.append(source[last:m.start()])
        last = m.end()
    rest.append(source[last:])
    bare, kept = [], []
    for token in " ".join(rest).split():
        cleaned = _strip(token, LEADING)
        if cleaned and _is_bare_address(cleaned):
            bare.append(cleaned)
        else:
            kept.append(token)
    return urls, bare, " ".join(kept)


def _url_problem(url):
    """Why the URL is not a plain explicit https URL, or "" with its hostname. Hostname checks look at the
    parsed hostname only (D-A42, D-A43); the backslash check looks at the whole URL."""
    if "\\" in url:
        return "a backslash", ""
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return "the URL cannot be parsed", ""
    if parts.scheme.lower() != "https":
        return f"scheme {parts.scheme!r}", ""
    authority = parts.netloc
    userinfo, at, hostport = authority.rpartition("@")       # user-info is everything before the last @
    if at:
        return "user-info", ""
    host, colon, port = hostport.rpartition(":")              # port text is everything after the last :
    if not colon:
        host = hostport
    elif port != ALLOWED_PORT:
        return f"port {port!r}", ""
    if not host:
        return "no hostname", ""
    if not host.isascii():
        return "a non-ASCII hostname", ""
    if "%" in host:
        return "a percent-encoded hostname", ""
    if not HOST_CHARS.fullmatch(host):
        return "other characters in the hostname", ""
    if host.endswith("."):
        return "a trailing dot", ""
    if any(label.lower().startswith("xn--") for label in host.split(".")):
        return "a punycode label", ""
    return "", host


def source_findings(source, provider):
    """RR-05 to RR-09 for one profile source and one provider."""
    if provider not in DOC_HOSTS:
        raise ValueError(f"provider must be one of {sorted(DOC_HOSTS)}, not {provider!r}")
    checks = _Checks()
    _source_checks(checks, source if isinstance(source, str) else "", provider)
    return checks.found


def _source_checks(checks, source, provider):
    urls, bare, rest = _addresses(source)
    if len(urls) + len(bare) != 1:
        checks.fault("RR-05", f"{len(urls)} explicit URLs and {len(bare)} bare or www addresses")
    if not checks.blocked("RR-06", ("RR-05",)):
        if bare:
            checks.fault("RR-06", f"{bare[0]!r} is a bare or www address")
            host = ""
        else:
            problem, host = _url_problem(urls[0])
            if problem:
                checks.fault("RR-06", problem)
    if not checks.blocked("RR-07", ("RR-05", "RR-06")):
        if host.lower() not in DOC_HOSTS[provider]:
            checks.fault("RR-07", f"{host!r} for {provider}; allowed: {', '.join(DOC_HOSTS[provider])}")
    dates = DATE.findall(rest)                     # outside every address, explicit or bare
    if len(dates) != 1:
        checks.fault("RR-08", f"{len(dates)} dates found")
    if not checks.blocked("RR-09", ("RR-08",)):
        y, m, d = dates[0]
        try:
            datetime.date(int(y), int(m), int(d))
        except ValueError:
            checks.fault("RR-09", f"{y}-{m}-{d}")


# ---- the whole check (sections 4.16, 4.18) ----
def _parts(target, profile):
    if isinstance(target, KitCallable):
        adapter = target.adapter
    elif isinstance(target, _Adapter):
        adapter = target
    else:
        raise ValueError(f"check_real_run takes a kit callable or a memory-backed adapter, not {target!r}")
    return adapter, target.model, (target.profile if profile is None else profile)


def readiness_findings(target, profile=None):
    """(findings, record): every finding in the fixed order, and the readiness record when there is no fault.
    Raises nothing for a fault."""
    adapter, model, profile = _parts(target, profile)
    checks = _Checks()
    if not isinstance(profile, adapter.profile_type):
        checks.fault("RR-01", f"{type(profile).__name__} given, {adapter.profile_type.__name__} needed")
    if not isinstance(model, str) or not model.strip():
        checks.fault("RR-03")
    if not checks.blocked("RR-02", ("RR-01", "RR-03")) and profile.model != model:
        checks.fault("RR-02", f"profile {profile.model!r}, callable {model!r}")
    if not checks.blocked("RR-04", ("RR-01",)) and profile.max_tokens_limit is None:
        checks.fault("RR-04")
    if "RR-01" in checks.faults:
        for fid in ("RR-05", "RR-06", "RR-07", "RR-08", "RR-09"):
            checks.blocked(fid, ("RR-01",))
    else:
        _source_checks(checks, profile.source, adapter.provider)
    version = _sdk_checks(checks, adapter)
    found = sorted(checks.found, key=lambda f: FAULT_ORDER.index(f.id))
    if any(f.status == "fault" for f in found):
        return found, None
    record = {"provider": adapter.provider, "model": model, "sdk_version": version, "sdk_major": adapter.sdk_major,
              "profile_hash": profile_hash(profile),
              "api_version": profile.api_version if isinstance(profile, ClaudeProfile) else None}
    return found, record


def _sdk_checks(checks, adapter):
    """RR-10 to RR-14. Imports the module and reads its version; constructs no client."""
    if adapter._client is not None:
        checks.fault("RR-10")
    module = None
    if not checks.blocked("RR-11", ("RR-10",)):
        try:
            module = adapter.import_sdk()
        except ImportError:
            checks.fault("RR-11", adapter.provider)
    if not checks.blocked("RR-12", ("RR-10",)) and adapter.sdk_major is None:
        checks.fault("RR-12")
    version = getattr(module, "__version__", None)
    if not checks.blocked("RR-13", ("RR-10", "RR-11")) and read_major(version) is None:
        checks.fault("RR-13", repr(version))
    if not checks.blocked("RR-14", ("RR-10", "RR-11", "RR-12", "RR-13")) and read_major(version) != adapter.sdk_major:
        checks.fault("RR-14", f"installed {version}, pinned major {adapter.sdk_major}")
    return version


def check_real_run(target, profile=None):
    """The readiness record {provider, model, sdk_version, sdk_major, profile_hash, api_version}, or
    RealRunRefused listing every finding. No client is constructed and no provider is called."""
    found, record = readiness_findings(target, profile)
    if record is None:
        raise RealRunRefused(found)
    return record


# ---- reviewed data may not be rebound through a module (build r2, point A) ----
PROTECTED = ("DOC_HOSTS", "FAULTS", "FAULT_ORDER", "BARE_TLDS")


class _ProtectedModule(types.ModuleType):
    """A module whose reviewed-data names, once bound, cannot be rebound or deleted."""

    def __setattr__(self, name, value):
        if name in PROTECTED and name in self.__dict__:
            raise AttributeError(f"{name} is reviewed data and cannot be rebound")
        super().__setattr__(name, value)

    def __delattr__(self, name):
        if name in PROTECTED:
            raise AttributeError(f"{name} is reviewed data and cannot be deleted")
        super().__delattr__(name)


def protect(module_name):
    sys.modules[module_name].__class__ = _ProtectedModule


protect(__name__)
