"""Shared test data for the engram_interface tests. No network, no keys, no SDKs."""
import types
from engram_interface import StubMemory, Turn, Fact


def memory_with_facts():
    """Alice says two things; the assistant says one. One validated fact, one uncertain fact."""
    m = StubMemory()
    e1 = m.ingest(Turn("Alice", "user", "I moved to Leeds last spring.", "2026-04-10", "conv0:1")).stored[0]
    e2 = m.ingest(Turn("Assistant", "assistant", "You said you might move to Bristol.", "2026-04-10", "conv0:2")).stored[0]
    e3 = m.ingest(Turn("Alice", "user", "My sister may be visiting in June, not sure.", "2026-05-02", "conv1:1")).stored[0]
    m.seed_fact(Fact("f1", "Alice", "lives in Leeds", "2026-04-10", (e1,)))
    m.seed_fact(Fact("f2", "Alice", "sister visiting in June", "2026-05-02", (e3,), "uncertain", "Alice was not sure"))
    return m, (e1, e2, e3)


class FakeAnthropicClient:
    def __init__(self, reply="Leeds."):
        self.calls, self.reply = [], reply
        self.messages = types.SimpleNamespace(create=self._create)

    def _create(self, **kw):
        self.calls.append(kw)
        return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text=self.reply)],
                                     usage=types.SimpleNamespace(input_tokens=10, output_tokens=2))


class FakeOpenAIClient:
    """r5: a fake of the Responses API (client.responses.create), in place of r1-r4's Chat Completions fake."""
    def __init__(self, reply="Leeds."):
        self.calls, self.reply = [], reply
        self.responses = types.SimpleNamespace(create=self._create)

    def _create(self, **kw):
        self.calls.append(kw)
        part = types.SimpleNamespace(type="output_text", text=self.reply)
        return types.SimpleNamespace(output_text=self.reply, model=kw.get("model"),
                                     output=[types.SimpleNamespace(type="message", content=[part])],
                                     usage=types.SimpleNamespace(input_tokens=10, output_tokens=2))


def fake_sdk(name, client_cls_name, client):
    """A stand-in module for anthropic/openai that counts constructions of its client class."""
    mod = types.ModuleType(name)
    mod.made = []
    mod.__version__ = "2.0.0"      # r7 (D-A27): a fake installed version, read by the adapter's SDK pin check

    def make(*a, **kw):
        mod.made.append((a, kw))
        return client
    setattr(mod, client_cls_name, make)
    return mod


def claude_adapter(memory, model="model-under-test", **kw):
    """r6 (D-A21): answer() needs a frozen profile and reasoning; this gives a legacy-shaped fake for any name."""
    from engram_interface import ClaudeAdapter
    from .profiles_fake import claude_for
    kw.setdefault("profile", claude_for(model) if model else None)
    kw.setdefault("reasoning", {"mode": "none"})
    kw.setdefault("sdk_major", 2)  # r7 (D-A27): the freeze pins the SDK major; the fake SDK reports 2.0.0
    return ClaudeAdapter(memory, model=model, **kw)


def openai_adapter(memory, model="model-under-test", **kw):
    from engram_interface import OpenAIAdapter
    from .profiles_fake import openai_for
    kw.setdefault("profile", openai_for(model) if model else None)
    kw.setdefault("reasoning", {"mode": "default"})
    kw.setdefault("sdk_major", 2)  # r8 (D-A32): the OpenAI SDK major is pinned too; the fake SDK reports 2.0.0
    return OpenAIAdapter(memory, model=model, **kw)


def make(cls, memory, **kw):
    """r6: build cls's memory-backed adapter through the profile-adding helper."""
    from engram_interface import ClaudeAdapter
    return (claude_adapter if cls is ClaudeAdapter else openai_adapter)(memory, **kw)
