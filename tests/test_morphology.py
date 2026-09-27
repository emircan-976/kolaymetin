from __future__ import annotations

import pytest

from kolaymetin.text import morphology as m


def best(word: str, **ctx: bool) -> m.Analysis:
    a = m.best(word, m.WordContext(**ctx))
    assert a is not None
    return a


@pytest.mark.parametrize("word", ["alınacaktır", "kesilecek", "yapılması", "bildirilir", "görüldü", "edilmektedir"])
def test_passive(word: str) -> None:
    assert best(word, is_last=True).is_passive


@pytest.mark.parametrize("word", ["alacak", "gelecek", "bozuldu", "taşındı", "bulunan", "giyindi"])
def test_not_passive(word: str) -> None:
    assert not best(word, is_last=True).is_passive


def test_reflexive_ambiguity_lowers_confidence() -> None:
    a = best("yıkandı", is_last=True)
    assert a.is_passive and a.is_reflexive_candidate and a.conf("is_passive") <= 0.5


@pytest.mark.parametrize("word", ["gelmeyecek", "yapmamak", "değildir", "olmayacak", "alınmayacaktır"])
def test_negative(word: str) -> None:
    assert best(word, is_last=True).is_negative


@pytest.mark.parametrize("word", ["okuyarak", "gelince", "gitmeden", "gelip"])
def test_converb(word: str) -> None:
    assert best(word).is_converb


def test_participle_and_nominal_and_genitive() -> None:
    assert best("gördüğümüz").is_participle
    assert best("yapacağı").is_participle
    assert best("yapılması").is_nominalized
    assert best("belediyenin").is_genitive
    assert best("gerekmektedir", is_last=True).is_finite
    assert not best("gelen").is_finite


def test_proper_noun_only_when_capitalized() -> None:
    assert best("Karşıyaka", capitalized=True).is_proper
    assert not best("karşıyaka").is_proper


def test_analyze_word_and_unknown() -> None:
    assert len(m.analyze_word("gelen")) > 1
    unk = m.analyze_word("zzqxlarında")
    assert unk[0].source == "sezgisel"
    assert m.best("123") is None


def test_lemma_keys() -> None:
    assert "müracaat" in m.lemma_keys("müracaatınızı")
    assert "görevli" in m.lemma_keys("görevliye")
    assert "almak" in m.lemma_keys("alınacaktır")
    assert "implementasyon" in m.lemma_keys("implementasyonu")


def test_state_is_not_corrupted_by_repeated_calls() -> None:
    """zeyrek'in yerinde değişiklik hatasına karşı: aynı kelime hep aynı sonucu vermeli."""
    first = {a.lemma for a in m.analyze_word("gelen")}
    for w in ["alınacaktır", "bulunan", "gelen", "yapılacak", "gidecek"] * 3:
        m._analyze_cached.__wrapped__(w)  # önbelleği atlayarak zeyrek'i yeniden çalıştır
    m.clear_caches()
    assert {a.lemma for a in m.analyze_word("gelen")} == first


# --------------------------------------------------------------------- sezgisel geri dönüş


@pytest.mark.parametrize(
    ("word", "flag"),
    [
        ("alınacaktır", "is_passive"), ("yapılması", "is_passive"), ("kesildi", "is_passive"),
        ("gelmeyecek", "is_negative"), ("değil", "is_negative"), ("okuyarak", "is_converb"),
        ("gelince", "is_converb"), ("gitmeden", "is_converb"), ("yapılması", "is_nominalized"),
        ("okumak", "is_nominalized"), ("belediyenin", "is_genitive"),
    ],
)
def test_heuristic_flags(word: str, flag: str) -> None:
    a = m.heuristic_analyze(word)
    assert getattr(a, flag), (word, flag)
    assert a.source == "sezgisel" and a.confidence < 1


@pytest.mark.parametrize("word", ["okul", "gelin", "zaman", "insan", "bulundu"])
def test_heuristic_not_passive(word: str) -> None:
    assert not m.heuristic_analyze(word).is_passive


def test_heuristic_finite_and_stem() -> None:
    assert m.heuristic_analyze("gelecek", m.WordContext(is_last=True)).is_finite
    assert m.heuristic_stem("müracaatlarınızdan")[0] == "müracaat"
    assert m.heuristic_stem("kitabı")[0] == "kitap"
    assert m.heuristic_analyze("yıkandı").is_reflexive_candidate


def test_heuristic_backend_via_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """KOLAYMETIN_MORFOLOJI=sezgisel ile zeyrek hiç yüklenmez ve araç yine çalışır."""
    monkeypatch.setenv("KOLAYMETIN_MORFOLOJI", "sezgisel")
    state = m._ZeyrekState
    saved = (state.tried, state.analyzer, state.failed)
    try:
        state.tried, state.analyzer, state.failed = False, None, None
        m.clear_caches()
        assert m.backend_name() == "sezgisel"
        assert "sezgisel" in (m.backend_problem() or "")
        from kolaymetin import analyze

        report = analyze("Başvurular alınacaktır. Müracaatınızı ivedilikle yapın.")
        assert report.morphology == "sezgisel"
        ids = {f.rule_id for f in report.findings}
        assert {"KD-C03", "KD-K01"} <= ids
        assert any("sezgisel" in n for n in report.notes)
    finally:
        state.tried, state.analyzer, state.failed = saved
        m.clear_caches()
