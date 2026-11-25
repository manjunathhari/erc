"""TK-D: the no-key dry run end to end."""
import socket

from engram_testkit.dry_run import FakeAnswer, FakeJudge, dry_run


def test_d01_dry_run_end_to_end_without_network(tmp_path, monkeypatch):
    def no_net(*a, **k):
        raise AssertionError("network used")
    monkeypatch.setattr(socket, "socket", no_net)
    monkeypatch.setattr(socket, "create_connection", no_net)
    state, summary, text = dry_run(str(tmp_path / "dry"))
    assert state["stopped"] is False
    assert sorted(summary["arms"]) == ["A", "B", "C"]
    assert summary["complete_questions"] == 13
    for word in ("Latency and token cost", "Generous run 1", "Strict run 2", "| D | erc-learned | 6 | reserved"):
        assert word in text, word
    assert state["answer_model"].startswith("fake-") and state["judge_model"].startswith("fake-")
    assert FakeAnswer.model.startswith("fake-") and FakeJudge.model.startswith("fake-")
    text, usage, _ = FakeAnswer()("Excerpts:\n(no excerpts)\n\nQuestion: x\nAnswer:")
    assert text == "not mentioned" and usage["prompt_tokens"] > 0
