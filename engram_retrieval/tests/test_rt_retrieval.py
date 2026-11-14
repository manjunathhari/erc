"""Engram Retrieval Foundation (Roadmap B7, Plan Stage 4): tests written first.

A standalone package, engram_retrieval, beside the engine. It takes a unit (id, kind, text, day) and gives back ranked ids.
It reads no engine table and no engine module, and the engine does not import it. Entity retrieval is not in this package.

Run by name, from the repository root:   python -m pytest engram_retrieval/tests -q
It is not in pytest.ini's testpaths, so the engine's own suite and its recorded counts do not move.

Every expected number here is worked out in this file by a plain reference calculation, never copied from the package.
"""
import ast
import hashlib
import math
import os
import re
import sys

import numpy as np
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
ROOT = os.path.dirname(PKG)
NAME = "engram_retrieval"
TOKEN = re.compile(r"[a-z0-9]+")
PUBLIC = {"Unit", "Hit", "AddReport", "IndexMismatch", "VectorIndex", "LexicalIndex", "HybridSearch",
          "recall_at_k", "mrr", "ndcg_at_k"}

CORPUS = [
    ("s1", "sentence", "I started working at the city hospital in March", "2026-03-02"),
    ("s2", "sentence", "My sister moved to Pune last year", "2025-06-10"),
    ("s3", "sentence", "The operation took three hours and went well", "2026-05-20"),
    ("s4", "sentence", "We adopted a dog named Bruno", "2026-01-15"),
    ("s5", "sentence", "I prefer tea over coffee in the morning", "2026-02-01"),
    ("s6", "sentence", "Bruno the dog chased a cat in the park near the hospital on a long morning walk", "2026-04-11"),
    ("f1", "fact", "works at the city hospital", "2026-03-02"),
    ("f2", "fact", "sister lives in Pune", "2025-06-10"),
    ("n1", "sentence", "Bruno likes long walks", None),
]
QUERIES = ["dog Bruno", "where does my sister live", "hospital work", "morning tea", "long walks in the park"]


@pytest.fixture
def R():
    if ROOT not in sys.path: sys.path.insert(0, ROOT)
    import engram_retrieval
    return engram_retrieval


def toks(text):
    return TOKEN.findall(text.lower())


class FakeEmbedder:
    """Stands in for an embedding model. Words hashed into a fixed vector, so it is the same on every machine and needs no
    download. Vectors are deliberately not unit length: the index has to normalise them."""
    def __init__(self, name="fake-bow", version="1", dim=256):
        self.name, self.version, self.dim = name, version, dim
        self.calls = 0

    def one(self, text):
        if "POISON" in text: raise RuntimeError("the model refused this text")
        v = np.zeros(self.dim, dtype=np.float32)
        if "NANVEC" in text: return v + np.nan
        if "ZEROVEC" in text: return v
        for w in toks(text):
            h = hashlib.sha256(w.encode()).digest()
            v[int.from_bytes(h[:4], "big") % self.dim] += 1.0 if h[4] % 2 else -1.0
        return v * 3.0

    def embed(self, texts):
        self.calls += 1
        return np.stack([self.one(t) for t in texts])


def units(R, rows=CORPUS):
    return [R.Unit(*r) for r in rows]


def keep(rows, kinds=None, day_from=None, day_to=None):
    out = []
    for i, k, t, d in rows:
        if kinds and k not in kinds: continue
        if day_from or day_to:
            if d is None or (day_from and d < day_from) or (day_to and d > day_to): continue
        out.append((i, k, t, d))
    return out


def ref_vector(query, rows, k):
    e = FakeEmbedder()
    q = e.one(query); q = q / np.linalg.norm(q)
    scored = []
    for i, _, t, _ in rows:
        v = e.one(t); scored.append((i, float(q @ (v / np.linalg.norm(v)))))
    return sorted(scored, key=lambda x: (-x[1], x[0]))[:k]


def ref_bm25(query, rows, k, k1=1.2, b=0.75):
    docs = {i: toks(t) for i, _, t, _ in rows}
    n = len(docs); avg = sum(len(d) for d in docs.values()) / n if n else 0.0
    scored = []
    for i, d in docs.items():
        s = 0.0
        for w in dict.fromkeys(toks(query)):
            df = sum(1 for x in docs.values() if w in x); tf = d.count(w)
            if not tf: continue
            idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
            s += idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * len(d) / avg))
        if s > 0: scored.append((i, s))
    return sorted(scored, key=lambda x: (-x[1], x[0]))[:k]


def norm(scored):
    if not scored: return {}
    lo, hi = min(s for _, s in scored), max(s for _, s in scored)
    return {i: 1.0 if hi == lo else (s - lo) / (hi - lo) for i, s in scored}


def ref_hybrid(query, rows, k, wv=0.5, wl=0.5, pool=50):
    v, l = norm(ref_vector(query, rows, pool)), norm(ref_bm25(query, rows, pool))
    t = wv + wl
    fused = [(i, (wv * v.get(i, 0.0) + wl * l.get(i, 0.0)) / t) for i in set(v) | set(l)]
    return sorted(fused, key=lambda x: (-x[1], x[0]))[:k]


def pairs(hits):
    return [(h.id, h.score) for h in hits]


def same(got, want, tol=1e-6):
    assert [i for i, _ in got] == [i for i, _ in want]
    for (_, a), (_, b) in zip(got, want): assert abs(a - b) <= tol


def file_bytes(path):
    with open(path, "rb") as f: return f.read()


def rows_naming(path, ident):
    import sqlite3
    db = sqlite3.connect(path); n = 0
    for (t,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
        for row in db.execute(f'SELECT * FROM "{t}"').fetchall():
            n += any(c == ident for c in row)
    db.close(); return n


# ---------------------------------------------------------------- the package stays beside the engine

def test_the_package_exists_and_names_exactly_its_public_parts(R):
    assert set(R.__all__) == PUBLIC
    for n in PUBLIC: assert hasattr(R, n)


def test_the_package_imports_only_the_standard_library_numpy_and_itself():
    assert os.path.isdir(PKG) and os.path.basename(PKG) == NAME, "run from engram_retrieval/tests inside the package"
    files = [os.path.join(d, f) for d, _, fs in os.walk(PKG) for f in fs if f.endswith(".py") and os.sep + "tests" not in d]
    assert files, "the package has no code yet"
    bad = []
    for path in files:
        for node in ast.walk(ast.parse(open(path).read())):
            mods = [a.name for a in node.names] if isinstance(node, ast.Import) else \
                   [node.module or ""] if isinstance(node, ast.ImportFrom) and node.level == 0 else []
            for m in mods:
                top = m.split(".")[0]
                if top not in sys.stdlib_module_names and top not in ("numpy", NAME): bad.append((os.path.basename(path), m))
    assert not bad


def test_nothing_outside_the_package_names_it():
    """Passes before the build and must still pass after: the engine, the layers and ERC never reach into the retrieval package."""
    found = []
    for d, dirs, fs in os.walk(ROOT):
        dirs[:] = [x for x in dirs if x not in (NAME, ".git", "__pycache__", ".pytest_cache", "results")]
        for f in fs:
            if f.endswith((".py", ".ini", ".yml", ".json")) and NAME in open(os.path.join(d, f), errors="ignore").read():
                found.append(os.path.relpath(os.path.join(d, f), ROOT))
    assert not found


# ---------------------------------------------------------------- units

@pytest.mark.parametrize("bad", [("", "sentence", "text", None), ("x", "note", "text", None), ("x", "fact", "", None),
                                 ("x", "fact", "   ", None), ("x", "fact", "text", "12 March"), ("x", "fact", "text", "2026-13-40")])
def test_a_unit_needs_an_id_a_known_kind_some_text_and_a_real_day_or_none(R, bad):
    with pytest.raises(ValueError): R.Unit(*bad)


# ---------------------------------------------------------------- the vector index

@pytest.fixture
def vec(R, tmp_path):
    v = R.VectorIndex(str(tmp_path / "v.db"), FakeEmbedder())
    v.add(units(R)); return v


def test_an_empty_vector_index_finds_nothing(R, tmp_path):
    v = R.VectorIndex(str(tmp_path / "v.db"), FakeEmbedder())
    assert v.search("anything", 5) == [] and len(v) == 0


def test_adding_reports_what_was_embedded(R, tmp_path):
    v = R.VectorIndex(str(tmp_path / "v.db"), FakeEmbedder())
    rep = v.add(units(R))
    assert sorted(rep.embedded) == sorted(r[0] for r in CORPUS) and rep.failed == []
    assert len(v) == len(CORPUS) and sorted(v.ids()) == sorted(r[0] for r in CORPUS)
    assert v.status("s1") == "embedded" and v.status("nobody") is None


@pytest.mark.parametrize("q", QUERIES)
def test_vector_search_is_cosine_similarity_in_order(vec, q):
    same(pairs(vec.search(q, 5)), ref_vector(q, CORPUS, 5))


def test_a_vector_hit_carries_its_kind(vec):
    kinds = {r[0]: r[1] for r in CORPUS}
    assert all(h.kind == kinds[h.id] for h in vec.search("hospital", 9))


def test_the_same_text_scores_one(vec):
    h = vec.search("We adopted a dog named Bruno", 1)[0]
    assert h.id == "s4" and abs(h.score - 1.0) <= 1e-6


def test_k_is_a_ceiling_and_must_be_positive(vec):
    assert len(vec.search("dog", 2)) == 2 and len(vec.search("dog", 100)) == len(CORPUS)
    for k in (0, -1):
        with pytest.raises(ValueError): vec.search("dog", k)


def test_equal_scores_are_ordered_by_id(R, tmp_path):
    v = R.VectorIndex(str(tmp_path / "v.db"), FakeEmbedder())
    v.add([R.Unit("b", "sentence", "tea and toast"), R.Unit("a", "sentence", "tea and toast"), R.Unit("c", "sentence", "tea and toast")])
    assert [h.id for h in v.search("tea", 3)] == ["a", "b", "c"]


def test_adding_the_same_unit_again_changes_nothing(R, vec):
    before = pairs(vec.search("dog Bruno", 9)); e = vec.embedder.calls
    rep = vec.add([R.Unit(*CORPUS[0])])
    assert rep.embedded == [] and rep.failed == [] and vec.embedder.calls == e
    assert len(vec) == len(CORPUS) and pairs(vec.search("dog Bruno", 9)) == before


def test_an_id_cannot_be_given_different_text(R, vec):
    before = pairs(vec.search("hospital", 9))
    with pytest.raises(ValueError): vec.add([R.Unit("s1", "sentence", "something else entirely", "2026-03-02")])
    assert pairs(vec.search("hospital", 9)) == before


def test_a_refused_batch_adds_none_of_it(R, vec):
    with pytest.raises(ValueError): vec.add([R.Unit("new1", "sentence", "a new line"), R.Unit("s1", "sentence", "changed")])
    assert vec.status("new1") is None and len(vec) == len(CORPUS)


@pytest.mark.parametrize("kinds", [("fact",), ("sentence",), ("fact", "sentence")])
def test_vector_search_can_be_limited_to_kinds(vec, kinds):
    same(pairs(vec.search("sister Pune", 9, kinds=kinds)), ref_vector("sister Pune", keep(CORPUS, kinds=kinds), 9))


def test_an_unknown_kind_is_refused_in_a_search(vec):
    with pytest.raises(ValueError): vec.search("dog", 3, kinds=("note",))


@pytest.mark.parametrize("a,b", [("2026-01-15", "2026-03-02"), ("2026-03-03", None), (None, "2025-12-31"), ("2030-01-01", None)])
def test_vector_search_keeps_to_a_range_of_days_inclusive(vec, a, b):
    same(pairs(vec.search("dog hospital sister", 9, day_from=a, day_to=b)),
         ref_vector("dog hospital sister", keep(CORPUS, day_from=a, day_to=b), 9))


def test_a_unit_with_no_day_is_left_out_of_a_dated_search_and_kept_otherwise(vec):
    assert "n1" in [h.id for h in vec.search("Bruno walks", 9)]
    assert "n1" not in [h.id for h in vec.search("Bruno walks", 9, day_from="2000-01-01", day_to="2999-12-31")]


def test_a_range_that_ends_before_it_starts_is_refused(vec):
    with pytest.raises(ValueError): vec.search("dog", 3, day_from="2026-05-01", day_to="2026-04-01")


def test_a_removed_unit_is_gone_from_search_and_from_the_file(vec):
    assert vec.remove(["s4", "nobody"]) == 1
    assert "s4" not in [h.id for h in vec.search("dog Bruno", 9)] and vec.status("s4") is None and len(vec) == len(CORPUS) - 1
    same(pairs(vec.search("dog Bruno", 9)), ref_vector("dog Bruno", [r for r in CORPUS if r[0] != "s4"], 9))
    assert rows_naming(vec.path, "s4") == 0


def test_a_removed_unit_can_be_added_again(R, vec):
    vec.remove(["s4"]); rep = vec.add([R.Unit(*CORPUS[3])])
    assert rep.embedded == ["s4"]
    same(pairs(vec.search("dog Bruno", 9)), ref_vector("dog Bruno", CORPUS, 9))


def test_the_vector_index_never_keeps_the_text(vec):
    data = file_bytes(vec.path)
    for _, _, text, _ in CORPUS: assert text.encode() not in data


def test_the_vector_index_is_the_same_after_closing_and_opening(R, vec):
    before = [pairs(vec.search(q, 9)) for q in QUERIES]; path = vec.path; vec.close()
    again = R.VectorIndex(path, FakeEmbedder())
    assert [pairs(again.search(q, 9)) for q in QUERIES] == before and len(again) == len(CORPUS)


@pytest.mark.parametrize("other", [dict(name="another-model"), dict(version="2"), dict(dim=128)])
def test_an_index_made_with_one_model_refuses_another_and_is_left_unchanged(R, vec, other):
    path = vec.path; vec.close(); before = file_bytes(path)
    with pytest.raises(R.IndexMismatch): R.VectorIndex(path, FakeEmbedder(**other))
    assert file_bytes(path) == before


@pytest.mark.parametrize("marker", ["POISON", "NANVEC", "ZEROVEC"])
def test_a_text_the_model_cannot_embed_is_reported_and_the_rest_go_in(R, tmp_path, marker):
    v = R.VectorIndex(str(tmp_path / "v.db"), FakeEmbedder())
    rep = v.add(units(R) + [R.Unit("bad", "sentence", f"{marker} dog Bruno")])
    assert rep.failed == ["bad"] and sorted(rep.embedded) == sorted(r[0] for r in CORPUS)
    assert v.status("bad") is None and len(v) == len(CORPUS)
    same(pairs(v.search("dog Bruno", 9)), ref_vector("dog Bruno", CORPUS, 9))


def test_a_model_returning_the_wrong_shape_is_refused(R, tmp_path):
    class Wrong(FakeEmbedder):
        def embed(self, texts): return np.zeros((len(texts), self.dim + 1), dtype=np.float32) + 1
    v = R.VectorIndex(str(tmp_path / "v.db"), Wrong())
    rep = v.add([R.Unit("a", "sentence", "tea")])
    assert rep.failed == ["a"] and len(v) == 0


def test_a_question_the_model_cannot_embed_raises_and_never_returns_a_guess(vec):
    with pytest.raises(ValueError): vec.search("POISON", 3)
    with pytest.raises(ValueError): vec.search("   ", 3)


# ---------------------------------------------------------------- the keyword index

@pytest.fixture
def lex(R, tmp_path):
    l = R.LexicalIndex(str(tmp_path / "l.db"))
    l.add(units(R)); return l


def test_an_empty_keyword_index_finds_nothing(R, tmp_path):
    assert R.LexicalIndex(str(tmp_path / "l.db")).search("anything", 5) == []


@pytest.mark.parametrize("q", QUERIES + ["PUNE!", "hospital hospital"])
def test_keyword_search_is_bm25_in_order(lex, q):
    same(pairs(lex.search(q, 9)), ref_bm25(q, CORPUS, 9), 1e-9)


def test_words_the_index_has_never_seen_find_nothing(lex):
    assert lex.search("zebra xylophone", 5) == []


@pytest.mark.parametrize("k1,b", [(1.2, 0.75), (2.0, 0.0), (0.9, 0.4)])
def test_bm25_settings_are_used_as_given(R, tmp_path, k1, b):
    l = R.LexicalIndex(str(tmp_path / "l.db"), k1=k1, b=b); l.add(units(R))
    same(pairs(l.search("morning hospital walk", 9)), ref_bm25("morning hospital walk", CORPUS, 9, k1, b), 1e-9)


def test_the_keyword_index_reopened_with_other_settings_is_refused_unchanged(R, lex):
    path = lex.path; lex.close(); before = file_bytes(path)
    with pytest.raises(R.IndexMismatch): R.LexicalIndex(path, k1=2.0)
    assert file_bytes(path) == before
    assert pairs(R.LexicalIndex(path).search("dog Bruno", 9)) == [(i, pytest.approx(s, abs=1e-9)) for i, s in ref_bm25("dog Bruno", CORPUS, 9)]


def test_removing_from_the_keyword_index_changes_the_counts_it_scores_with(lex):
    assert lex.remove(["s6", "nobody"]) == 1
    rest = [r for r in CORPUS if r[0] != "s6"]
    for q in QUERIES: same(pairs(lex.search(q, 9)), ref_bm25(q, rest, 9), 1e-9)
    assert rows_naming(lex.path, "s6") == 0 and lex.status("s6") is None and len(lex) == len(rest)


def test_the_keyword_index_never_keeps_the_sentence(lex):
    data = file_bytes(lex.path)
    for _, _, text, _ in CORPUS: assert text.encode() not in data


def test_the_keyword_index_follows_the_same_adding_rules(R, lex):
    assert lex.add([R.Unit(*CORPUS[0])]).embedded == []
    with pytest.raises(ValueError): lex.add([R.Unit("s1", "sentence", "something else", "2026-03-02")])
    assert len(lex) == len(CORPUS)


@pytest.mark.parametrize("kw", [dict(kinds=("fact",)), dict(day_from="2026-01-15", day_to="2026-03-02"), dict(kinds=("sentence",), day_to="2025-12-31")])
def test_keyword_search_filters_but_scores_against_the_whole_index(lex, kw):
    """The filter chooses which units may be returned. It does not change how rare a word is."""
    allowed = {r[0] for r in keep(CORPUS, **kw)}
    want = [(i, s) for i, s in ref_bm25("hospital sister Pune morning", CORPUS, 99) if i in allowed][:9]
    same(pairs(lex.search("hospital sister Pune morning", 9, **kw)), want, 1e-9)


# ---------------------------------------------------------------- the two together

@pytest.fixture
def both(R, tmp_path):
    h = R.HybridSearch(R.VectorIndex(str(tmp_path / "v.db"), FakeEmbedder()), R.LexicalIndex(str(tmp_path / "l.db")))
    h.add(units(R)); return h


@pytest.mark.parametrize("q", QUERIES)
@pytest.mark.parametrize("wv,wl", [(0.5, 0.5), (0.8, 0.2), (1.0, 3.0)])
def test_the_fused_score_is_each_channel_scaled_to_one_then_weighted(R, tmp_path, q, wv, wl):
    h = R.HybridSearch(R.VectorIndex(str(tmp_path / "v.db"), FakeEmbedder()), R.LexicalIndex(str(tmp_path / "l.db")), w_vector=wv, w_lexical=wl)
    h.add(units(R))
    same(pairs(h.search(q, 5)), ref_hybrid(q, CORPUS, 5, wv, wl))


def test_each_hit_says_what_each_channel_gave_it(both):
    q = "dog Bruno"; v, l = norm(ref_vector(q, CORPUS, 50)), norm(ref_bm25(q, CORPUS, 50))
    for h in both.search(q, 9):
        assert set(h.parts) == {"vector", "lexical"}
        assert abs(h.parts["vector"] - v.get(h.id, 0.0)) <= 1e-6 and abs(h.parts["lexical"] - l.get(h.id, 0.0)) <= 1e-6


def test_with_one_weight_at_zero_the_order_is_the_other_channel_alone(R, tmp_path):
    v, l = R.VectorIndex(str(tmp_path / "v.db"), FakeEmbedder()), R.LexicalIndex(str(tmp_path / "l.db"))
    R.HybridSearch(v, l).add(units(R))
    for q in QUERIES:
        assert [h.id for h in R.HybridSearch(v, l, w_vector=1, w_lexical=0).search(q, 5)] == [i for i, _ in ref_vector(q, CORPUS, 5)]
        assert [h.id for h in R.HybridSearch(v, l, w_vector=0, w_lexical=1).search(q, 9)] == [i for i, _ in ref_bm25(q, CORPUS, 9)]


def test_a_channel_with_weight_zero_is_not_asked_at_all(R, tmp_path):
    e = FakeEmbedder()
    v, l = R.VectorIndex(str(tmp_path / "v.db"), e), R.LexicalIndex(str(tmp_path / "l.db"))
    R.HybridSearch(v, l).add(units(R) + [R.Unit("bad", "sentence", "POISON marmalade")])
    assert "bad" not in [h.id for h in R.HybridSearch(v, l, w_vector=1, w_lexical=0).search("marmalade", 99)]
    calls = e.calls
    assert [h.id for h in R.HybridSearch(v, l, w_vector=0, w_lexical=1).search("marmalade", 9)] == ["bad"] and e.calls == calls


@pytest.mark.parametrize("wv,wl", [(-0.1, 1.0), (1.0, -0.1), (0.0, 0.0)])
def test_weights_cannot_be_negative_or_both_zero(R, tmp_path, wv, wl):
    with pytest.raises(ValueError):
        R.HybridSearch(R.VectorIndex(str(tmp_path / "v.db"), FakeEmbedder()), R.LexicalIndex(str(tmp_path / "l.db")), w_vector=wv, w_lexical=wl)


def test_a_channel_that_finds_nothing_gives_nothing_and_breaks_nothing(both):
    q = "zebra xylophone"
    assert ref_bm25(q, CORPUS, 9) == []
    same(pairs(both.search(q, 5)), ref_hybrid(q, CORPUS, 5))


def test_the_pool_limits_how_many_each_channel_offers(both):
    same(pairs(both.search("dog hospital morning", 9, pool=3)), ref_hybrid("dog hospital morning", CORPUS, 9, pool=3))
    with pytest.raises(ValueError): both.search("dog", 3, pool=0)


@pytest.mark.parametrize("kw", [dict(kinds=("fact",)), dict(day_from="2026-01-15", day_to="2026-04-11")])
def test_fusion_passes_the_filters_to_both_channels(both, kw):
    ids = [h.id for h in both.search("dog hospital sister morning", 9, **kw)]
    assert ids and set(ids) <= {r[0] for r in keep(CORPUS, **kw)}


def test_adding_and_removing_through_the_pair_reaches_both(R, both):
    assert both.remove(["s4"]) == 1
    assert both.vector.status("s4") is None and both.lexical.status("s4") is None
    assert "s4" not in [h.id for h in both.search("dog Bruno adopted", 9)]
    both.add([R.Unit(*CORPUS[3])])
    same(pairs(both.search("dog Bruno", 5)), ref_hybrid("dog Bruno", CORPUS, 5))


def test_a_unit_the_model_cannot_embed_is_still_found_by_its_words(R, both):
    rep = both.add([R.Unit("bad", "sentence", "POISON marmalade")])
    assert rep.failed == ["bad"]
    assert [h.id for h in both.search("marmalade", 3)][0] == "bad" and both.vector.status("bad") is None


def test_the_same_question_twice_gives_the_same_answer(both):
    for q in QUERIES: assert pairs(both.search(q, 9)) == pairs(both.search(q, 9))


# ---------------------------------------------------------------- the measures

def test_recall_at_k(R):
    ranked, rel = ["a", "b", "c", "d"], {"b", "d", "x"}
    assert R.recall_at_k(ranked, rel, 2) == pytest.approx(1 / 3)
    assert R.recall_at_k(ranked, rel, 4) == pytest.approx(2 / 3)
    assert R.recall_at_k([], rel, 5) == 0.0
    with pytest.raises(ValueError): R.recall_at_k(ranked, set(), 2)
    with pytest.raises(ValueError): R.recall_at_k(ranked, rel, 0)


def test_mean_reciprocal_rank(R):
    assert R.mrr([(["a", "b"], {"b"}), (["c"], {"c"}), (["d"], {"e"})]) == pytest.approx(0.5)
    assert R.mrr([(["a", "b", "c"], {"c", "b"})]) == pytest.approx(0.5)
    with pytest.raises(ValueError): R.mrr([])


def test_ndcg_at_k(R):
    gains = {"a": 3, "b": 2, "c": 3, "d": 0}
    dcg = 3 / math.log2(2) + 2 / math.log2(3) + 3 / math.log2(4)
    ideal = 3 / math.log2(2) + 3 / math.log2(3) + 2 / math.log2(4)
    assert R.ndcg_at_k(["a", "b", "c"], gains, 3) == pytest.approx(dcg / ideal)
    assert R.ndcg_at_k(["a", "c", "b"], gains, 3) == pytest.approx(1.0)
    assert R.ndcg_at_k(["b"], gains, 3) == pytest.approx(2 / ideal)
    assert R.ndcg_at_k(["d", "zz"], gains, 2) == 0.0
    assert R.ndcg_at_k(["a"], {"a": 0}, 1) == 0.0
    with pytest.raises(ValueError): R.ndcg_at_k(["a"], gains, 0)
