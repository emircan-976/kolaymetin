from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from kolaymetin.cli import main

CORPUS = Path(__file__).parent / "corpus"
BUROKRATIK = CORPUS / "su-kesintisi-burokratik" / "metin.txt"
KOLAY = CORPUS / "su-kesintisi-kolay" / "metin.txt"


def run(*args: str, stdin: str | None = None, monkeypatch: pytest.MonkeyPatch | None = None) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    if stdin is not None and monkeypatch is not None:
        monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
    code = main(list(args), out=out, err=err)
    return code, out.getvalue(), err.getvalue()


def test_text_output() -> None:
    code, out, _ = run("denetle", str(BUROKRATIK))
    assert code == 0
    assert "Kolay Dil Uyum Skoru" in out and "KD-C01" in out and "■ Hata" in out


def test_markdown_output() -> None:
    code, out, _ = run("denetle", str(BUROKRATIK), "--cikti", "md")
    assert code == 0 and out.startswith("# kolaymetin denetim raporu")


def test_json_output_to_file(tmp_path: Path) -> None:
    target = tmp_path / "rapor.json"
    code, _, err = run("denetle", str(KOLAY), "--cikti", "json", "-o", str(target))
    assert code == 0 and "Rapor yazıldı" in err
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["scores"]["compliance"]["value"] >= 85


def test_html_and_text_to_file(tmp_path: Path) -> None:
    code, _, _ = run("denetle", str(KOLAY), "--cikti", "html", "-o", str(tmp_path / "r.html"))
    assert code == 0 and "<!DOCTYPE html>" in (tmp_path / "r.html").read_text(encoding="utf-8")
    code, _, _ = run("denetle", str(KOLAY), "-o", str(tmp_path / "r.txt"))
    assert code == 0 and "kolaymetin" in (tmp_path / "r.txt").read_text(encoding="utf-8")


def test_threshold_exit_codes() -> None:
    assert run("denetle", str(BUROKRATIK), "--esik-skor", "70")[0] == 1
    assert run("denetle", str(KOLAY), "--esik-skor", "70")[0] == 0


def test_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    code, out, _ = run("denetle", "-", "--cikti", "json", stdin="Su gelecek.", monkeypatch=monkeypatch)
    assert code == 0 and json.loads(out)["stats"]["word_count"] == 2
    code, _, err = run("denetle", "-", stdin="   ", monkeypatch=monkeypatch)
    assert code == 2 and "boş" in err


def test_profiles_and_lexicon(tmp_path: Path) -> None:
    prof = tmp_path / "ozel.yaml"
    prof.write_text("extends: kolay-dil\nrules:\n  KD-C01: {enabled: false}\n", encoding="utf-8")
    lex = tmp_path / "ek.yaml"
    lex.write_text("jargon:\n  - {ifade: encümen, oneri: belediye kurulu}\n", encoding="utf-8")
    code, out, _ = run("denetle", str(BUROKRATIK), "--profil", str(prof), "--sozluk", str(lex), "--cikti", "json")
    ids = {f["rule_id"] for f in json.loads(out)["findings"]}
    assert code == 0 and "KD-C01" not in ids
    code, out, _ = run("denetle", str(BUROKRATIK), "--profil", "sade-dil", "--cikti", "json")
    assert json.loads(out)["profile"] == "sade-dil"


@pytest.mark.parametrize(
    "args",
    [
        ("denetle", "yok-boyle-dosya.txt"),
        ("denetle", str(BUROKRATIK), "--profil", "yok.yaml"),
        ("denetle", str(BUROKRATIK), "--sozluk", "yok.yaml"),
        ("denetle", str(BUROKRATIK), "--cikti", "pdf"),
        ("bilinmeyen-komut",),
        ("kurallar", "--profil", "yok.yaml"),
    ],
)
def test_input_errors(args: tuple[str, ...]) -> None:
    assert run(*args)[0] == 2


def test_rules_version_help() -> None:
    code, out, _ = run("kurallar")
    assert code == 0 and "KD-C01" in out and "KD-M05" in out
    code, out, _ = run("kurallar", "--profil", "sade-dil")
    assert code == 0 and "hayır" in out
    assert run("surum")[1].strip() == "kolaymetin 1.0.0"
    code, out, _ = run()
    assert code == 0 and "denetle" in out


def test_help_is_turkish(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        from kolaymetin.cli import _build_parser

        _build_parser().parse_args(["--help"])
    out = capsys.readouterr().out
    assert "Kullanım:" in out and "Seçenekler" in out


def test_server_command(monkeypatch: pytest.MonkeyPatch) -> None:
    called = {}
    monkeypatch.setattr("kolaymetin.web.app.serve", lambda host, port: called.update(host=host, port=port))
    code, out, _ = run("sunucu", "--port", "8123")
    assert code == 0 and called == {"host": "127.0.0.1", "port": 8123} and "8123" in out
