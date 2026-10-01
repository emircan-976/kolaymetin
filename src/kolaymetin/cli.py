"""Komut satırı aracı.

    kolaymetin denetle GİRDİ [--profil kolay-dil|sade-dil|DOSYA] [--sozluk DOSYA]
                             [--cikti metin|json|md|html] [-o DOSYA] [--esik-skor 70]
    kolaymetin sunucu [--port 8000] [--host 127.0.0.1]
    kolaymetin kurallar [--profil ...]
    kolaymetin surum

Çıkış kodları: 0 başarılı, 1 skor eşiğin altında, 2 girdi hatası.
"""

from __future__ import annotations

import argparse
import contextlib
import sys
from pathlib import Path
from typing import TextIO

EXIT_OK = 0
EXIT_BELOW_THRESHOLD = 1
EXIT_INPUT_ERROR = 2

_TR = {
    "usage: ": "Kullanım: ",
    "positional arguments": "Konumsal argümanlar",
    "options": "Seçenekler",
    "optional arguments": "Seçenekler",
    "show this help message and exit": "Bu yardım iletisini gösterir ve çıkar",
    "the following arguments are required: %s": "şu argümanlar gerekli: %s",
    "invalid choice: %(value)r (choose from %(choices)s)": "geçersiz seçim: %(value)r (seçenekler: %(choices)s)",
    "argument %(argument_name)s: %(message)s": "%(argument_name)s argümanı: %(message)s",
    "unrecognized arguments: %s": "tanınmayan argümanlar: %s",
    "invalid %(type)s value: %(value)r": "geçersiz %(type)s değeri: %(value)r",
    "expected one argument": "bir değer bekleniyordu",
    "%(prog)s: error: %(message)s\n": "%(prog)s: hata: %(message)s\n",
}


def _translate(text: str) -> str:
    return _TR.get(text, text)


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        self.print_usage(sys.stderr)
        self.exit(EXIT_INPUT_ERROR, f"{self.prog}: hata: {message}\n")


def _build_parser() -> argparse.ArgumentParser:
    argparse._ = _translate  # type: ignore[attr-defined]
    p = _Parser(
        prog="kolaymetin",
        description="Türkçe Kolay Dil / Sade Dil denetim aracı. Metin makineden çıkmaz.",
        epilog="Bu araç yardımcıdır, hakem değildir. Metni hedef okurlarla test edin.",
    )
    sub = p.add_subparsers(dest="komut", metavar="KOMUT", parser_class=_Parser)

    d = sub.add_parser("denetle", help="Bir metni denetler")
    d.add_argument("girdi", metavar="GİRDİ", help=".txt, .md, .docx, .pdf dosyası ya da - (standart girdi)")
    d.add_argument("--profil", default="kolay-dil", help="kolay-dil, sade-dil ya da profil YAML dosyası")
    d.add_argument("--sozluk", action="append", default=[], metavar="DOSYA",
                   help="Ek sözlük YAML dosyası (birden fazla verilebilir)")
    d.add_argument("--cikti", choices=["metin", "json", "md", "html"], default="metin",
                   help="Çıktı biçimi (varsayılan: metin)")
    d.add_argument("-o", "--dosya", metavar="DOSYA", help="Çıktıyı bu dosyaya yaz")
    d.add_argument("--esik-skor", type=int, default=None, metavar="SAYI",
                   help="Uyum skoru bu sayının altındaysa çıkış kodu 1 olur (CI için)")

    s = sub.add_parser("sunucu", help="Yerel web arayüzünü başlatır")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--host", default="127.0.0.1")

    k = sub.add_parser("kurallar", help="Bütün kuralları ve eşikleri listeler")
    k.add_argument("--profil", default="kolay-dil")

    sub.add_parser("surum", help="Sürümü gösterir")
    return p


def _print_text_report(report: object, stream: TextIO) -> None:
    from rich.console import Console
    from rich.text import Text

    from kolaymetin.io.exporters import SEV_LABEL, score_title, score_value
    from kolaymetin.models import Report

    assert isinstance(report, Report)
    con = Console(file=stream, highlight=False)
    styles = {"hata": "bold red", "uyarı": "bold yellow", "bilgi": "bold blue"}
    under = {"hata": "underline red", "uyarı": "black on yellow", "bilgi": "underline blue"}
    marks = {"hata": "■", "uyarı": "□", "bilgi": "○"}
    c = report.scores.compliance
    con.print(Text("kolaymetin", style="bold") + Text(f" · {report.profile_title} profili", style="dim"))
    con.print(f"{score_title(report)}: [bold]{score_value(c.value)}[/bold] / 100" + (f"  ({c.note})" if c.note else ""))
    sc = report.scores
    for r in (sc.atesman, sc.cetinkaya_uzun, sc.bezirci_yilmaz):
        val = "—" if r.value is None else f"{r.value:.1f}"
        con.print(f"  {r.name}: {val} ({r.level})")
    st = report.stats
    con.print(f"  {st.word_count} kelime · {st.sentence_count} cümle · ortalama {st.avg_sentence_length} kelime")
    con.print()
    by_sentence: dict[int | None, list] = {}
    for f in report.findings:
        by_sentence.setdefault(f.sentence_index, []).append(f)
    for idx, items in by_sentence.items():
        if idx is not None and idx < len(report.sentences):
            s = report.sentences[idx]
            line = Text(s.text.replace("\n", " "))
            for f in sorted(items, key=lambda f: -["hata", "uyarı", "bilgi"].index(f.severity)):
                a, b = f.start - s.start, f.end - s.start
                if 0 <= a < b <= len(s.text):
                    line.stylize(under[f.severity], a, b)
            con.print(Text(f"[{idx + 1}] ", style="dim") + line)
        for f in items:
            con.print(
                Text(f"  {marks[f.severity]} {SEV_LABEL[f.severity]} ", style=styles[f.severity])
                + Text(f"{f.rule_id} ", style="bold")
                + Text(f.message)
            )
            if f.suggestion:
                con.print(Text(f"    → {f.suggestion}", style="dim"))
        con.print()
    if not report.findings:
        con.print("Bu profilde bulgu yok.")
    for note in report.notes:
        con.print(Text(note, style="italic dim"))


def _cmd_denetle(args: argparse.Namespace, out: TextIO, err: TextIO) -> int:
    from kolaymetin.api import EmptyInput, InputTooLong, analyze
    from kolaymetin.io.readers import ReaderError, read_file
    from kolaymetin.lexicon import LexiconError
    from kolaymetin.profiles import ProfileError

    try:
        text = sys.stdin.read() if args.girdi == "-" else read_file(args.girdi)
    except ReaderError as exc:
        err.write(f"Hata: {exc}\n")
        return EXIT_INPUT_ERROR
    try:
        report = analyze(text, profile=args.profil, custom_lexicon=list(args.sozluk) or None)
    except (ProfileError, LexiconError, InputTooLong, EmptyInput) as exc:
        err.write(f"Hata: {exc}\n")
        return EXIT_INPUT_ERROR

    if args.cikti == "metin" and not args.dosya:
        _print_text_report(report, out)
    else:
        if args.cikti == "json":
            content = report.to_json()
        elif args.cikti == "md":
            content = report.to_markdown()
        elif args.cikti == "html":
            content = report.to_html()
        else:
            import io

            buf = io.StringIO()
            _print_text_report(report, buf)
            content = buf.getvalue()
        if args.dosya:
            Path(args.dosya).write_text(content, encoding="utf-8")
            err.write(f"Rapor yazıldı: {args.dosya}\n")
        else:
            out.write(content)
    value = report.scores.compliance.value
    if args.esik_skor is not None and value is not None and value < args.esik_skor:
        err.write(
            f"Uyum skoru ({report.scores.compliance.value}) eşiğin ({args.esik_skor}) altında.\n"
        )
        return EXIT_BELOW_THRESHOLD
    return EXIT_OK


def _cmd_kurallar(args: argparse.Namespace, out: TextIO, err: TextIO) -> int:
    from rich.console import Console
    from rich.table import Table

    from kolaymetin.profiles import ProfileError, load_profile
    from kolaymetin.rules import all_rules

    try:
        profile = load_profile(args.profil)
    except ProfileError as exc:
        err.write(f"Hata: {exc}\n")
        return EXIT_INPUT_ERROR
    table = Table(title=f"Kurallar — {profile.title or profile.name} profili", show_lines=False)
    for col in ("Kimlik", "Ad", "Düzey", "Önem", "Açık", "Eşikler"):
        table.add_column(col)
    for rule in all_rules():
        cfg = profile.rule(rule.id)
        params = ", ".join(f"{k}={v}" for k, v in cfg.params.items()) or "—"
        table.add_row(
            rule.id, rule.name, rule.level, cfg.severity or rule.default_severity,
            "evet" if cfg.enabled else "hayır", params,
        )
    Console(file=out, highlight=False, width=140).print(table)
    return EXIT_OK


def _cmd_sunucu(args: argparse.Namespace, out: TextIO, err: TextIO) -> int:
    from kolaymetin.web.app import serve

    out.write(f"kolaymetin arayüzü: http://{args.host}:{args.port}  (durdurmak için Ctrl+C)\n")
    out.flush()
    serve(host=args.host, port=args.port)
    return EXIT_OK


def main(argv: list[str] | None = None, out: TextIO | None = None, err: TextIO | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            with contextlib.suppress(ValueError, OSError):
                stream.reconfigure(encoding="utf-8")
    out = out or sys.stdout
    err = err or sys.stderr
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else EXIT_INPUT_ERROR
    if args.komut == "denetle":
        return _cmd_denetle(args, out, err)
    if args.komut == "kurallar":
        return _cmd_kurallar(args, out, err)
    if args.komut == "sunucu":
        return _cmd_sunucu(args, out, err)
    if args.komut == "surum":
        from kolaymetin import __version__

        out.write(f"kolaymetin {__version__}\n")
        return EXIT_OK
    parser.print_help(out)
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
