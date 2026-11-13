"""WR-A (Engram writing layer contract v1, rule S1): base 2's gate is told who the people in the chat are.

Today the gate asks the P2 interpreter about a sentence without saying who the people are, so only the usual labels
("User", "Human", ...) count as a person talking about their own life. A sentence said by a named speaker ("Asha")
never passes: 0 of 20 lasting facts (audit W2, measure T2). The interpreter already accepts a list of people; the gate
does not pass one. WR-A adds `people` to the gate and passes it on.

What must hold after WR-A:
  - told that the speaker is a person in the chat, the gate decides exactly as it does for "User" today;
  - not told, the gate decides exactly as it does today, for every speaker (callers that do not pass people,
    such as the benchmark runner, are unchanged);
  - only the people listed count; listing someone else does not make the speaker a person;
  - an assistant, system or tool label is never treated as a person, even if a caller lists it;
  - a named speaker's sentence, once picked, is filed under that speaker by the existing rules (already true).
"""
import pytest

import engram_chat as E
import engram_structure as S

SAID = "2:15 pm on 12 June, 2025"

# The audit's 40 sentences (wr_probe.py part G): 20 lasting facts, 20 that are not.
FACTS = [
    "I work at Manipal Hospital.", "I live in Bengaluru.", "I moved to Chennai in March 2023.", "I am a surgeon.",
    "I am married to Priya.", "I own a red Tata Nexon.", "I adopted a dog last year.", "I like filter coffee.",
    "I joined the cycling club in January.", "My daughter is called Meera.", "I left Apollo in 2021.",
    "I play chess every weekend.", "I ran a half marathon on 25 February 2023.", "I was diagnosed with asthma in 2015.",
    "I paid 42,000 rupees in rent on 1 March 2024.", "I am allergic to penicillin.",
    "My flight to Delhi was cancelled on 9 January 2024.", "I speak Kannada and Tamil.", "My blood group is O positive.",
    "I was born in Mysore.",
]
NOT_FACTS = [
    "Hello, how are you?", "Thanks a lot!", "Okay.", "Can you summarise this article?", "What time is it in London?",
    "I might move to Goa someday.", "If I get the job, I will move to Delhi.", "I wish I had a dog.",
    "I am so tired of this traffic today.", "I almost bought a Tesla.", "That sounds great.", "Haha, that is funny.",
    "Please write a poem about rain.", "It was fine.", "I think it might rain tomorrow.", "Wow, really?",
    "Let me know what you think.", "I am feeling a bit hungry now.", "Maybe I should learn French.", "Good morning!",
]
ALL = FACTS + NOT_FACTS


def passed(speaker, texts, **kw):
    return sum(S.gate(speaker, t, SAID, **kw)[0] for t in texts)


# ---------- T2: the measure WR-A moves ----------

def test_t2_a_named_speaker_told_who_the_people_are_passes_20_of_20_facts():
    assert passed("Asha", FACTS, people=("Asha",)) == 20


def test_t2_a_named_speaker_told_who_the_people_are_stops_what_user_stops():
    assert passed("Asha", NOT_FACTS, people=("Asha",)) == passed("User", NOT_FACTS) == 4


@pytest.mark.parametrize("text", ALL)
def test_told_the_gate_decides_for_a_named_speaker_exactly_as_for_user_today(text):
    """Same decision and the same content kind (the kind becomes the stored fact type)."""
    assert S.gate("Asha", text, SAID, people=("Asha",)) == S.gate("User", text, SAID)


# ---------- not told: unchanged ----------

@pytest.mark.parametrize("speaker,facts,stopped", [("User", 20, 16), ("Asha", 0, 20), ("Assistant", 0, 20)])
def test_not_told_the_gate_is_as_today(speaker, facts, stopped):
    assert passed(speaker, FACTS) == facts and len(NOT_FACTS) - passed(speaker, NOT_FACTS) == stopped


@pytest.mark.parametrize("text", ALL)
def test_user_is_the_same_told_or_not(text):
    assert S.gate("User", text, SAID, people=("User",)) == S.gate("User", text, SAID) == S.gate("User", text, SAID, people=())


# ---------- only the people listed ----------

def test_listing_someone_else_does_not_make_the_speaker_a_person():
    assert passed("Asha", FACTS, people=("Ravi",)) == 0


def test_a_chat_with_two_people_counts_both():
    assert passed("Asha", FACTS, people=("Asha", "Ravi")) == passed("Ravi", FACTS, people=("Asha", "Ravi")) == 20


def test_names_match_whatever_their_case_and_surrounding_spaces():
    assert passed("Asha", FACTS, people=(" asha ",)) == passed("ASHA", FACTS, people=("Asha",)) == 20


# ---------- never the assistant ----------

@pytest.mark.parametrize("label", ["Assistant", "assistant", "AI", "ChatGPT", "Model", "Bot", "System", "Developer", "tool:search"])
def test_an_assistant_system_or_tool_label_is_never_a_person_even_if_listed(label):
    assert passed(label, FACTS, people=(label,)) == 0


def test_listing_the_assistant_does_not_stop_the_real_people():
    assert passed("Asha", FACTS, people=("Asha", "Assistant")) == 20


# ---------- past the gate: filing for a named speaker (existing rules, kept) ----------

def test_a_named_speakers_picked_sentence_is_filed_under_that_speaker(tmp_path):
    m = E.ChatMemory(str(tmp_path / "m.db"), durable=False)
    m.open_chat(SAID)
    sid = m.add("Asha", "I work at Manipal Hospital.", date=SAID)
    picked, kind = S.gate("Asha", "I work at Manipal Hospital.", SAID, people=("Asha",))
    assert picked
    out = S.StructureLayer(m.db).file(sid, "I", "Manipal Hospital", kind)
    assert out.verdict == "accepted" and out.fact_id
    fact = S.StructureLayer(m.db).kb.get(out.fact_id).fact
    assert m.db.execute("SELECT canonical_name FROM entities WHERE entity_id=?", (fact.subject_id,)).fetchone()[0] == "Asha"
