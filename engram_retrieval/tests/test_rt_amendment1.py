"""Engram Retrieval Foundation (Roadmap B7, Plan Stage 4): Amendment 1 tests, written first.

These are added beside the 95 accepted tests in test_rt_retrieval.py, which is not changed. They hold what build
revision 1 did without a test, and the two defects found at its review:

  1A1  an existing file is never turned into an index; only a path with no file makes a new one
  1A2  a change made through another object on the same file is seen, a removal above all
  1A3  the same id twice in one batch
  1A4  the keyword index keeps no word order
  1A5  the BM25 settings are checked
  1A6  argument checks
  1A7  what removing through the pair returns
  1A8  an index is not used in a `with` block
  1A10 the breakage script travels with the package, holds exactly the 52, and is not part of the package's code

Run by name, from the repository root:   python -m pytest engram_retrieval/tests -q
"""
import ast
import os
import re
import sqlite3
import sys

import pytest

from test_rt_retrieval import CORPUS, PKG, ROOT, FakeEmbedder, file_bytes, pairs, ref_bm25, ref_hybrid, ref_vector, same, toks, units

OPEN = {"vector": lambda R, path: R.VectorIndex(path, FakeEmbedder()),
        "keyword": lambda R, path: R.LexicalIndex(path)}
KINDS_OF_INDEX = sorted(OPEN)
THE_40 = ([f"V{n}" for n in range(1, 16)] + ["U1", "U2"] + [f"L{n}" for n in range(1, 9)] + [f"H{n}" for n in range(1, 10)]
          + ["M1", "M2", "M3", "I1", "I2", "I3"])
THE_12 = [f"A{n}" for n in range(1, 13)]
SCRIPT = os.path.join(PKG, "tests", "rt_build_break.py")


@pytest.fixture
def R():
    if ROOT not in sys.path: sys.path.insert(0, ROOT)
    import engram_retrieval
    return engram_retrieval


def pair(R, tmp_path, embedder=None):
    return R.HybridSearch(R.VectorIndex(str(tmp_path / "v.db"), embedder or FakeEmbedder()), R.LexicalIndex(str(tmp_path / "l.db")))


# ---------------------------------------------------------------- 1A1: an existing file is never turned into an index

@pytest.mark.parametrize("which", KINDS_OF_INDEX)
def test_a_path_with_no_file_makes_a_new_empty_index(R, tmp_path, which):
    path = str(tmp_path / "new.db")
    assert not os.path.exists(path)
    index = OPEN[which](R, path)
    assert len(index) == 0 and os.path.getsize(path) > 0


@pytest.mark.parametrize("which", KINDS_OF_INDEX)
def test_an_existing_empty_file_is_refused_and_left_empty(R, tmp_path, which):
    path = str(tmp_path / "empty.db"); open(path, "wb").close()
    with pytest.raises(R.IndexMismatch): OPEN[which](R, path)
    assert os.path.getsize(path) == 0


@pytest.mark.parametrize("which", KINDS_OF_INDEX)
def test_a_file_that_is_not_a_database_is_refused_unchanged(R, tmp_path, which):
    path = str(tmp_path / "notes.db")
    with open(path, "wb") as f: f.write(b"these are somebody's notes, not an index\n" * 20)
    before = file_bytes(path)
    with pytest.raises(R.IndexMismatch): OPEN[which](R, path)
    assert file_bytes(path) == before


@pytest.mark.parametrize("which", KINDS_OF_INDEX)
def test_somebody_elses_database_is_refused_unchanged(R, tmp_path, which):
    path = str(tmp_path / "other.db")
    db = sqlite3.connect(path); db.execute("CREATE TABLE sentences(sid INTEGER, text TEXT)"); db.execute("INSERT INTO sentences VALUES(1, 'kept')")
    db.commit(); db.close(); before = file_bytes(path)
    with pytest.raises(R.IndexMismatch): OPEN[which](R, path)
    assert file_bytes(path) == before


@pytest.mark.parametrize("which", KINDS_OF_INDEX)
def test_a_half_made_index_is_refused_unchanged(R, tmp_path, which):
    """The table that says what made the index is there, and says nothing."""
    path = str(tmp_path / "half.db")
    db = sqlite3.connect(path); db.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)"); db.commit(); db.close()
    before = file_bytes(path)
    with pytest.raises(R.IndexMismatch): OPEN[which](R, path)
    assert file_bytes(path) == before


@pytest.mark.parametrize("made,opened", [("vector", "keyword"), ("keyword", "vector")])
def test_one_kind_of_index_is_not_opened_as_the_other(R, tmp_path, made, opened):
    path = str(tmp_path / "index.db")
    index = OPEN[made](R, path); index.add(units(R)); index.close(); before = file_bytes(path)
    with pytest.raises(R.IndexMismatch): OPEN[opened](R, path)
    assert file_bytes(path) == before


# ---------------------------------------------------------------- 1A2: a change made through another object is seen

def test_the_vector_index_sees_what_another_object_added_and_removed(R, tmp_path):
    path = str(tmp_path / "v.db"); rows = list(CORPUS)
    first = R.VectorIndex(path, FakeEmbedder()); first.add(units(R, rows[:4]))
    same(pairs(first.search("dog Bruno hospital", 9)), ref_vector("dog Bruno hospital", rows[:4], 9))
    second = R.VectorIndex(path, FakeEmbedder()); second.add(units(R, rows[4:]))
    same(pairs(first.search("dog Bruno hospital", 9)), ref_vector("dog Bruno hospital", rows, 9))
    assert second.remove(["s4"]) == 1
    assert "s4" not in [h.id for h in first.search("We adopted a dog named Bruno", 9)]
    same(pairs(first.search("dog Bruno hospital", 9)), ref_vector("dog Bruno hospital", [r for r in rows if r[0] != "s4"], 9))
    assert len(first) == len(rows) - 1 and first.status("s4") is None


def test_the_keyword_index_sees_what_another_object_added_and_removed(R, tmp_path):
    path = str(tmp_path / "l.db"); rows = list(CORPUS)
    first = R.LexicalIndex(path); first.add(units(R, rows[:4])); first.search("dog Bruno hospital", 9)
    second = R.LexicalIndex(path); second.add(units(R, rows[4:]))
    same(pairs(first.search("dog Bruno hospital", 9)), ref_bm25("dog Bruno hospital", rows, 9), 1e-9)
    assert second.remove(["s4"]) == 1
    same(pairs(first.search("dog Bruno hospital", 9)), ref_bm25("dog Bruno hospital", [r for r in rows if r[0] != "s4"], 9), 1e-9)


def test_the_pair_never_returns_what_another_pair_removed(R, tmp_path):
    first = pair(R, tmp_path); first.add(units(R)); first.search("dog Bruno", 9)
    second = pair(R, tmp_path)
    assert second.remove(["s4", "s6"]) == 2
    rest = [r for r in CORPUS if r[0] not in ("s4", "s6")]
    same(pairs(first.search("dog Bruno", 9)), ref_hybrid("dog Bruno", rest, 9))


# ---------------------------------------------------------------- 1A3: the same id twice in one batch

@pytest.mark.parametrize("which", KINDS_OF_INDEX)
def test_the_same_unit_twice_in_one_batch_is_held_once(R, tmp_path, which):
    index = OPEN[which](R, str(tmp_path / "i.db"))
    report = index.add([R.Unit("a", "sentence", "tea and toast"), R.Unit("b", "fact", "likes tea"), R.Unit("a", "sentence", "tea and toast")])
    assert report.embedded == ["a", "b"] and report.failed == [] and index.ids() == ["a", "b"]


@pytest.mark.parametrize("which", KINDS_OF_INDEX)
def test_one_id_with_two_texts_in_one_batch_is_refused_and_nothing_is_written(R, tmp_path, which):
    index = OPEN[which](R, str(tmp_path / "i.db")); index.add([R.Unit("kept", "fact", "likes tea")])
    with pytest.raises(ValueError):
        index.add([R.Unit("new", "sentence", "a new line"), R.Unit("a", "sentence", "tea and toast"), R.Unit("a", "sentence", "coffee and cake")])
    assert index.ids() == ["kept"]


def test_the_pair_refuses_one_id_with_two_texts_and_writes_to_neither(R, tmp_path):
    both = pair(R, tmp_path)
    with pytest.raises(ValueError): both.add([R.Unit("a", "sentence", "tea and toast"), R.Unit("a", "sentence", "coffee and cake")])
    assert len(both.vector) == 0 and len(both.lexical) == 0
    assert both.add([R.Unit("a", "sentence", "tea and toast"), R.Unit("a", "sentence", "tea and toast")]).embedded == ["a"]
    assert both.vector.ids() == ["a"] and both.lexical.ids() == ["a"]


# ---------------------------------------------------------------- 1A4: the keyword index keeps no word order

def stored(path):
    """Every row of every table, in the order the file gives them. Fingerprints are masked: they differ whenever the text does."""
    db = sqlite3.connect(path); out = {}
    for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name").fetchall():
        out[table] = [tuple("<fingerprint>" if isinstance(c, str) and re.fullmatch(r"[0-9a-f]{64}", c) else c for c in row)
                      for row in db.execute(f'SELECT * FROM "{table}"').fetchall()]
    db.close(); return out


def test_the_keyword_index_stores_the_same_thing_whatever_order_the_words_came_in(R, tmp_path):
    said = ["zebra apple mango apple kiwi", "kiwi apple apple mango zebra", "apple kiwi zebra apple mango"]
    dumps = []
    for n, text in enumerate(said):
        index = R.LexicalIndex(str(tmp_path / f"l{n}.db"))
        index.add([R.Unit("a", "sentence", text, "2026-01-15"), R.Unit("b", "fact", "likes kiwi")]); index.close()
        dumps.append(stored(index.path))
    assert dumps[0] == dumps[1] == dumps[2]


def test_no_cell_of_the_keyword_index_holds_two_words_of_a_sentence(R, tmp_path):
    index = R.LexicalIndex(str(tmp_path / "l.db")); index.add(units(R)); index.close()
    cells = [toks(str(c)) for rows in stored(index.path).values() for row in rows for c in row]
    for _, _, text, _ in CORPUS:
        words = set(toks(text))
        assert all(len(words & set(cell)) <= 1 for cell in cells)


# ---------------------------------------------------------------- 1A5: the BM25 settings are checked

@pytest.mark.parametrize("bad", [dict(k1=-0.1), dict(k1=float("nan")), dict(k1=float("inf")), dict(b=-0.1), dict(b=1.1), dict(b=float("nan"))])
def test_a_meaningless_bm25_setting_is_refused_and_no_file_is_made(R, tmp_path, bad):
    path = str(tmp_path / "l.db")
    with pytest.raises(ValueError): R.LexicalIndex(path, **bad)
    assert not os.path.exists(path)


@pytest.mark.parametrize("good", [dict(k1=0.0), dict(b=0.0), dict(b=1.0)])
def test_the_ends_of_the_allowed_bm25_settings_are_accepted(R, tmp_path, good):
    index = R.LexicalIndex(str(tmp_path / "l.db"), **good); index.add(units(R))
    k1, b = good.get("k1", 1.2), good.get("b", 0.75)
    same(pairs(index.search("morning hospital walk", 9)), ref_bm25("morning hospital walk", CORPUS, 9, k1, b), 1e-9)


# ---------------------------------------------------------------- 1A6: argument checks

@pytest.mark.parametrize("which", KINDS_OF_INDEX)
@pytest.mark.parametrize("thing", [("a", "sentence", "tea and toast"), "tea and toast", None])
def test_only_a_unit_can_be_added_and_a_refused_batch_writes_nothing(R, tmp_path, which, thing):
    index = OPEN[which](R, str(tmp_path / "i.db"))
    with pytest.raises(ValueError): index.add([R.Unit("ok", "sentence", "a good unit"), thing])
    assert len(index) == 0


@pytest.mark.parametrize("which", KINDS_OF_INDEX + ["pair"])
def test_true_is_not_a_number_of_results(R, tmp_path, which):
    index = pair(R, tmp_path) if which == "pair" else OPEN[which](R, str(tmp_path / "i.db"))
    index.add(units(R))
    with pytest.raises(ValueError): index.search("dog", True)


def test_true_is_not_a_pool_and_the_refusal_names_the_pool(R, tmp_path):
    """Each channel would refuse it too, as a number of results. The refusal has to say what was actually wrong."""
    both = pair(R, tmp_path); both.add(units(R))
    for bad in (True, 0, 2.5):
        with pytest.raises(ValueError, match="pool"): both.search("dog", 3, pool=bad)


@pytest.mark.parametrize("which,question", [("vector", None), ("vector", 5), ("keyword", None), ("keyword", 5), ("pair", None)])
def test_a_question_must_be_text(R, tmp_path, which, question):
    index = pair(R, tmp_path) if which == "pair" else OPEN[which](R, str(tmp_path / "i.db"))
    index.add(units(R))
    with pytest.raises(ValueError): index.search(question, 3)


# ---------------------------------------------------------------- 1A7: what removing through the pair returns

def test_removing_through_the_pair_counts_a_unit_only_the_keyword_index_holds(R, tmp_path):
    both = pair(R, tmp_path); both.add(units(R) + [R.Unit("bad", "sentence", "POISON marmalade")])
    assert both.vector.status("bad") is None and both.lexical.status("bad") == "embedded"
    assert both.remove(["bad"]) == 1 and both.lexical.status("bad") is None


def test_removing_through_the_pair_counts_a_unit_only_the_vector_index_holds(R, tmp_path):
    both = pair(R, tmp_path); both.add(units(R)); both.vector.add([R.Unit("only", "sentence", "held by one index")])
    assert both.remove(["only"]) == 1 and both.vector.status("only") is None


def test_removing_through_the_pair_counts_each_id_once_and_unknown_ids_not_at_all(R, tmp_path):
    both = pair(R, tmp_path); both.add(units(R))
    assert both.remove(["nobody"]) == 0
    assert both.remove(["s1", "s1", "s2", "nobody"]) == 2
    assert both.remove(["s1"]) == 0 and len(both.vector) == len(CORPUS) - 2 == len(both.lexical)


# ---------------------------------------------------------------- 1A8: an index is not used in a `with` block

@pytest.mark.parametrize("which", KINDS_OF_INDEX)
def test_an_index_is_closed_by_close_and_is_not_a_with_block(R, tmp_path, which):
    index = OPEN[which](R, str(tmp_path / "i.db"))
    assert not hasattr(index, "__enter__") and not hasattr(index, "__exit__")
    index.close()
    with pytest.raises(sqlite3.ProgrammingError): len(index)


# ---------------------------------------------------------------- 1A10: the breakage script travels with the package

def test_the_breakage_script_is_in_the_package_and_no_package_code_names_it():
    assert os.path.isfile(SCRIPT)
    code = [os.path.join(d, f) for d, _, fs in os.walk(PKG) for f in fs if f.endswith(".py") and os.sep + "tests" not in d]
    assert code and not [p for p in code if "rt_build_break" in open(p).read()]


def test_the_breakage_script_holds_exactly_the_52_breakages_in_order():
    """The 40 of the accepted package, then the 12 this amendment added. None dropped, none renumbered, none twice.
    A later amendment that adds a breakage has to change this test, in the open."""
    tree = ast.parse(open(SCRIPT).read())
    lists = [n.value for n in ast.walk(tree) if isinstance(n, ast.Assign) and [t.id for t in n.targets if isinstance(t, ast.Name)] == ["B"]]
    assert len(lists) == 1
    ids = [entry[0] for entry in ast.literal_eval(lists[0])]
    assert len(ids) == 52 and len(set(ids)) == 52
    assert ids[:40] == THE_40
    assert ids[40:] == THE_12
