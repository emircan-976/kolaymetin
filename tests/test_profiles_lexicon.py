from __future__ import annotations

from pathlib import Path

import pytest

from kolaymetin import analyze
from kolaymetin.api import InputTooLong
from kolaymetin.lexicon import LexiconError, builtin_counts, load_lexicon
from kolaymetin.profiles import Profile, ProfileError, RuleConfig, load_profile
from kolaymetin.rules import all_rules


def test_builtin_profiles_cover_all_rules() -> None:
    for name in ("kolay-dil", "sade-dil"):
        p = load_profile(name)
        for rule in all_rules():
            assert rule.id in p.rules, f"{name}: {rule.id} profilde yok"
    kolay, sade = load_profile("kolay-dil"), load_profile("sade-dil")
    assert kolay.compliance_k == 0.6
    assert kolay.rule("KD-C01").params == {"warn_above": 10, "error_above": 15}
    assert sade.rule("KD-C01").params == {"warn_above": 15, "error_above": 22}
    assert kolay.rule("KD-C04").severity == "uyarı" and sade.rule("KD-C04").severity == "bilgi"
    assert not sade.rule("KD-K06").enabled


def test_custom_profile_extends(tmp_path: Path) -> None:
    p = tmp_path / "belediye.yaml"
    p.write_text(
        "name: yesilova\nextends: kolay-dil\ncompliance_k: 0.4\nrules:\n"
        "  KD-C01: {params: {warn_above: 12}}\n  KD-K04: {enabled: false}\n  KD-C04: {severity: uyari}\n",
        encoding="utf-8",
    )
    prof = load_profile(str(p))
    assert prof.name == "yesilova" and prof.compliance_k == 0.4
    assert prof.rule("KD-C01").params == {"warn_above": 12, "error_above": 15}
    assert not prof.rule("KD-K04").enabled
    assert prof.rule("KD-C04").severity == "uyarı"
    text = "Bir iki üç dört beş altı yedi sekiz dokuz."
    assert not [f for f in analyze(text, profile=str(p)).findings if f.rule_id == "KD-C01"]


def test_profile_from_dict_and_object() -> None:
    prof = load_profile({"extends": "sade-dil", "rules": {"KD-C01": {"enabled": False}}})
    assert prof.name == "ozel" and not prof.rule("KD-C01").enabled
    assert load_profile(prof) is prof
    assert Profile(name="x").rule("KD-C01") == RuleConfig()


@pytest.mark.parametrize(
    ("content", "msg"),
    [
        ("- liste", "sözlük"),
        ("rules: [", "YAML"),
        ("rules:\n  KD-C01: {severity: kritik}", "geçersiz"),
        ("extends: yok-boyle.yaml", "bulunamadı"),
    ],
)
def test_profile_errors(tmp_path: Path, content: str, msg: str) -> None:
    p = tmp_path / "hatali.yaml"
    p.write_text(content, encoding="utf-8")
    with pytest.raises(ProfileError, match=f"(?i){msg}"):
        load_profile(str(p))


def test_profile_cycle(tmp_path: Path) -> None:
    a = tmp_path / "a.yaml"
    a.write_text(f"extends: {a}\n", encoding="utf-8")
    with pytest.raises(ProfileError, match="zinciri"):
        load_profile(str(a))


def test_lexicon_minimum_sizes() -> None:
    c = builtin_counts()
    assert c["jargon"] >= 150
    assert c["yabanci"] >= 100
    assert c["deyimler"] >= 80
    assert c["kisaltmalar"] >= 80
    assert c["es_anlamlilar"] >= 30
    assert c["sik_kelimeler"] >= 3000
    assert c["belirsiz"] >= 20 and c["dolayli_hitap"] >= 5


def test_custom_lexicon_all_sections(tmp_path: Path) -> None:
    p = tmp_path / "ek.yaml"
    p.write_text(
        "jargon:\n  - {ifade: encümen, oneri: belediye kurulu}\n"
        "yabanci:\n  - {kelime: brifing, oneri: bilgi toplantısı}\n"
        "deyimler:\n  - {ifade: kulak kabartmak, anlam: dinlemek}\n"
        "belirsiz:\n  - {ifade: münasip bir zaman, oneri: Tarih yazın.}\n"
        "kisaltmalar:\n  - {kisaltma: YBB, acilim: Yeşilova Büyükşehir Belediyesi}\n"
        "es_anlamlilar:\n  - {grup: [otobüs durağı, durak yeri], tercih: otobüs durağı}\n"
        "dolayli_hitap:\n  - {ad: arz ederiz, desen: 'arz\\s+ederiz', oneri: Sunuyoruz.}\n"
        "sik_kelimeler: [imece]\nbilinen: [yeşilovalı]\n",
        encoding="utf-8",
    )
    lex = load_lexicon(p)
    assert lex.find_abbreviation("YBB") is not None
    assert "imece" in lex.common_words and "yeşilovalı" in lex.known_words
    text = "Encümen toplandı. YBB karar verdi. Otobüs durağı taşındı. Durak yeri uzak."
    ids = {f.rule_id for f in analyze(text, custom_lexicon=str(p)).findings}
    assert {"KD-K01", "KD-K03", "KD-K08"} <= ids
    assert load_lexicon() is load_lexicon()  # yerleşik sözlük önbellekte


@pytest.mark.parametrize(
    "content",
    ["- liste", "jargon: [", "tanimsiz_bolum: []", "dolayli_hitap:\n  - {desen: '(bozuk'}"],
)
def test_custom_lexicon_errors(content: str) -> None:
    with pytest.raises(LexiconError):
        load_lexicon(content)


def test_lexicon_path_errors(tmp_path: Path) -> None:
    with pytest.raises(LexiconError, match="bulunamadı"):
        load_lexicon(tmp_path / "yok.yaml")
    assert load_lexicon("") is load_lexicon()
    assert load_lexicon("# boş\n").jargon  # yalnızca yorum → ek yok


def test_input_limit() -> None:
    with pytest.raises(InputTooLong, match=r"100\.000"):
        analyze("a" * 100_001)
    assert analyze("a" * 10, max_chars=None).stats.word_count == 1
