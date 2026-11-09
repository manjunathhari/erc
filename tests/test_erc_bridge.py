"""Offline tests for the Engram -> ERC bridge (no model, no network)."""
import json

import engram_erc_bridge as B


def rec(kind, about, text, cat="other", date=None, lines=("D1:1",), polarity=True):
    return dict(type=kind, about=about, text=text, category=cat, date=date, polarity=polarity, lines=list(lines))


def reply(*rows):
    return json.dumps({"records": list(rows)})


def test_parse_repairs_and_drops_bad_records():
    out = B.parse_records(
        "Here you go: " + reply(
            rec("preference", "Coffee Creamer", "Makes own creamer with almond milk", cat="food", date="2023-05-01", lines=("D1:1", "bad")),
            rec("opinion", "x", "not a known type"),
            rec("event", "", "Ran a 5K charity run", date="last week"),
            {"type": "state", "text": ""},
        ),
        "2023-05-20", valid_lines={"D1:1"})
    assert [r["type"] for r in out] == ["preference", "event"]
    assert out[0]["about"] == "coffee creamer" and out[0]["category"] == "food and drink"
    assert out[0]["lines"] == ["D1:1"] and out[0]["said_on"] == "2023-05-20"
    assert out[1]["date"] is None and out[1]["about"]  # bad date dropped, missing topic filled


def test_parse_never_raises_on_garbage():
    assert B.parse_records("no json here", "2023-01-01") == []
    assert B.parse_records('{"records": "nope"}', "2023-01-01") == []
    assert B.parse_records("", "2023-01-01") == []


def test_newer_state_supersedes_older_on_same_topic_via_erc():
    state = B.build_memory_state({
        "a": B.parse_records(reply(rec("state", "bikes", "Owns three bikes", date="2023-05-01")), "2023-05-02"),
        "b": B.parse_records(reply(rec("state", "bikes", "Owns four bikes", date="2023-06-01")), "2023-06-02"),
        "c": B.parse_records(reply(rec("preference", "bikes", "Loves gravel riding", date="2023-06-01")), "2023-06-02"),
    })
    assert state.superseded == {"a#0": "b#0"}
    kinds = {n.subtype for n in state.graph.nodes}
    assert {"state", "preference", "category"} <= kinds
    assert all(e.relation.value == "is_a" for e in state.graph.edges)
    assert len(state.graph.graph_fingerprint) == 64


def test_preferences_are_not_functional():
    state = B.build_memory_state({
        "a": B.parse_records(reply(rec("preference", "music", "Likes jazz", date="2023-05-01")), "2023-05-02"),
        "b": B.parse_records(reply(rec("preference", "music", "Likes bluegrass", date="2023-06-01")), "2023-06-02"),
    })
    assert state.superseded == {}


def test_profile_ranks_by_relevance_and_respects_budget():
    state = B.build_memory_state({"a": B.parse_records(reply(
        rec("preference", "furniture", "Likes mid-century modern furniture and plans to replace the bedroom dresser", cat="home and furniture"),
        rec("preference", "podcasts", "Listens to history podcasts on the commute", cat="music"),
        rec("event", "5k", "Ran a 5K charity run", cat="sport and fitness"),
    ), "2023-05-20")})
    text = B.profile_section(state, "Any tips for rearranging the furniture in my bedroom?", budget=200)
    lines = text.splitlines()
    assert "dresser" in lines[1] and "5K" not in text  # events are not part of the preference profile
    assert B.count_tokens(text) <= 200
    small = B.profile_section(state, "bedroom furniture", budget=B.count_tokens(lines[0]) + B.count_tokens(lines[1]))
    assert len(small.splitlines()) == 2
    assert B.profile_section(state, "anything", budget=0) == ""


def test_writer_prompt_lists_taxonomy_and_lines():
    p = B.writer_prompt([("D3:1", "I love Hendrick's gin."), ("D3:2", "I took a mixology class.")], "2023-05-21")
    assert "D3:1 I love Hendrick's gin." in p and "2023-05-21" in p
    assert all(c in p for c in B.TAXONOMY)


def test_memory_profile_registered_and_core_untouched():
    from engram_erc.profiles import get_profile
    assert get_profile("engram-memory") is B.MEMORY_PROFILE
    assert "preference" in B.MEMORY_PROFILE.node_subtypes
    assert "preference" not in get_profile("general").node_subtypes


def test_line_references_are_normalised():
    valid = {"D7:1", "D7:2", "D7:3", "D7:4"}
    out = B.parse_records(reply(rec("event", "x", "Did a thing", lines=("7:1", "D7:2-D7:4", 3, "D9:1", "nonsense"))), "2023-05-20", valid)
    assert out[0]["lines"] == ["D7:1", "D7:2", "D7:3", "D7:4"]


def _facts_state():
    facts = {1: "The chairperson of Liverpool F.C. is John W. Henry.", 2: "John W. Henry is a citizen of United States of America.",
             3: "The chairperson of Liverpool F.C. is Ali Khan.", 4: "Ali Khan is a citizen of Pakistan.",
             5: "Ali Khan is a citizen of India."}
    reply = json.dumps({"facts": [
        {"n": 1, "subject": "Liverpool F.C.", "object": "John W. Henry"}, {"n": 2, "subject": "John W. Henry", "object": "United States of America"},
        {"n": 3, "subject": "Liverpool F.C.", "object": "Ali Khan"}, {"n": 4, "subject": "Ali Khan", "object": "Pakistan"},
        {"n": 5, "subject": "Ali Khan", "object": "India"}, {"n": 9, "subject": "x", "object": "y"},
        {"n": 2, "subject": "bad", "object": "not in sentence"}]})
    return B.build_fact_state(B.parse_fact_records(reply, facts))


def test_fact_versions_superseded_by_serial_via_erc():
    st = _facts_state()
    assert st.superseded == {1: 3, 4: 5} and st.keys_with_versions == 2
    assert 9 not in st.records  # unknown fact number dropped


def test_fact_walk_follows_current_chain_on_erc_graph():
    st = _facts_state()
    q = "What is the country of citizenship of the chairperson of Liverpool F.C.?"
    assert B.fact_walk(st, q) == [3, 5]
    assert B.fact_walk(st, q, current_only=False) == [1, 3, 2, 4, 5]
    assert B.fact_walk(st, q, hops=1) == [3]
    text = B.facts_section(st, B.fact_walk(st, q), 200, "[Current]")
    assert text.splitlines()[1] == "Fact 3: The chairperson of Liverpool F.C. is Ali Khan." and "India" in text


def test_fact_walk_seeds_from_search_results():
    st = _facts_state()
    assert B.fact_walk(st, "Where is the club's boss from?") == []
    assert B.fact_walk(st, "Where is the club's boss from?", seeds=[1]) == [3, 5]  # seed fact 1 -> subject Liverpool F.C. -> current chain
