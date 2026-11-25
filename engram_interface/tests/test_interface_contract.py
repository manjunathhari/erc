"""IF-T01..IF-T04: the contract itself."""
import dataclasses, inspect, subprocess, sys
from pathlib import Path
import pytest
import engram_interface as ei

ROOT = Path(__file__).resolve().parents[2]


def test_t01_records_are_frozen():
    for cls in (ei.Turn, ei.IngestResult, ei.Fact, ei.Excerpt, ei.ProfileResult, ei.FeedbackResult,
                ei.Unavailable, ei.TraceEntry, ei.AuditTrace, ei.ModelContext, ei.RetrievalResult):
        assert dataclasses.is_dataclass(cls) and cls.__dataclass_params__.frozen, cls.__name__
    t = ei.Turn("Alice", "user", "hi")
    with pytest.raises(dataclasses.FrozenInstanceError):
        t.text = "changed"


def test_t02_interface_is_abstract_and_declares_every_call():
    with pytest.raises(TypeError):
        ei.MemoryInterface()
    names = {n for n, v in vars(ei.MemoryInterface).items() if getattr(v, "__isabstractmethod__", False)}
    assert names == {"ingest", "retrieve", "profile", "feedback", "trace", "forget", "access"}
    assert issubclass(ei.StubMemory, ei.MemoryInterface)
    assert list(inspect.signature(ei.MemoryInterface.retrieve).parameters) == ["self", "question", "budget", "speaker"]


def test_t03_context_has_the_five_parts_the_plan_names():
    fields = {f.name for f in dataclasses.fields(ei.ModelContext)}
    assert {"facts", "excerpts", "uncertain", "profile"} <= fields
    assert {"date"} <= {f.name for f in dataclasses.fields(ei.Fact)}
    assert {"date"} <= {f.name for f in dataclasses.fields(ei.Excerpt)}
    assert {"trace_id", "empty_reason", "tokens", "budget"} <= fields


def test_t04_importing_the_package_imports_no_sdk():
    code = ("import sys, engram_interface;"
            "from engram_interface import ClaudeAdapter, OpenAIAdapter;"
            "ClaudeAdapter(None, model='m'); OpenAIAdapter(None, model='m');"
            "print('anthropic' in sys.modules, 'openai' in sys.modules)")
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert out.stdout.split() == ["False", "False"]
