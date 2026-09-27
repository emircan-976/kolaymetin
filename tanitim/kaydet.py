"""kolaymetin tanıtım filmini kaydeder.

video.html sayfasını Edge (Playwright) ile açar, her kareyi renderAt(t) ile çizip ekran görüntüsü
alır ve ffmpeg'e aktarır. Ses aynı sayfada Web Audio ile sentezlenir (OfflineAudioContext).
Kareler birkaç işlemde paralel çizilir; parçalar sonunda sesle birleştirilir.

Kullanım:
    python tanitim/kaydet.py                       # tam film → tanitim/kolaymetin-tanitim.mp4
    python tanitim/kaydet.py --fps 30 --taslak     # hızlı taslak
    python tanitim/kaydet.py --kareler 4,18.7,33.5 # yalnızca seçili anların PNG'si
"""

from __future__ import annotations

import argparse
import base64
import functools
import http.server
import multiprocessing as mp
import subprocess
import threading
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

KOK = Path(__file__).resolve().parent.parent
BURASI = Path(__file__).resolve().parent
SURE = 72.0
SES_YOLU = BURASI / "ses.wav"
# seviye: sentez çıkışı ~-18 LUFS; +4 dB ve tepe sınırlayıcı (dinamik korunur)
SES_AYAR = ["-af", "volume=4dB,alimiter=limit=0.87:level=disabled", "-ar", "48000", "-c:a", "aac", "-b:a", "256k"]


class Sessiz(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a: object) -> None:
        pass


class Sunucu(http.server.ThreadingHTTPServer):
    request_queue_size = 256


def sunucu_baslat() -> tuple[http.server.ThreadingHTTPServer, int]:
    srv = Sunucu(("127.0.0.1", 0), functools.partial(Sessiz, directory=str(KOK)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


def sayfa_ac(p, port: int):  # type: ignore[no-untyped-def]
    tarayici = p.chromium.launch(channel="msedge", headless=True)
    sayfa = tarayici.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
    sayfa.on("pageerror", lambda e: print("[hata]", e, flush=True))
    for deneme in range(4):
        sayfa.goto(f"http://127.0.0.1:{port}/tanitim/video.html?kayit")
        try:
            sayfa.wait_for_function("window.HAZIR === true", timeout=30_000)
            break
        except Exception:
            if deneme == 3:
                raise
            print("sayfa yeniden yükleniyor", flush=True)
    return tarayici, sayfa


def ses_uret(port: int) -> None:
    with sync_playwright() as p:
        tarayici, sayfa = sayfa_ac(p, port)
        t0 = time.time()
        wav = base64.b64decode(sayfa.evaluate("sesBase64()"))
        SES_YOLU.write_bytes(wav)
        tarayici.close()
    print(f"ses hazır ({len(wav) / 1e6:.1f} MB, {time.time() - t0:.0f} sn)", flush=True)


def parca_isle(no: int, port: int, fps: int, ilk: int, son: int, bas: float, hedef: str, kodlama: list[str]) -> None:
    ffmpeg = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(fps), "-c:v", "mjpeg", "-i", "-",
         "-c:v", "libx264", *kodlama, "-pix_fmt", "yuv420p", hedef],
        stdin=subprocess.PIPE,
    )
    assert ffmpeg.stdin is not None
    with sync_playwright() as p:
        tarayici, sayfa = sayfa_ac(p, port)
        t0 = time.time()
        for i in range(ilk, son):
            sayfa.evaluate(f"renderAt({bas + i / fps})")
            ffmpeg.stdin.write(sayfa.screenshot(type="jpeg", quality=95))
            k = i - ilk
            if k and k % (fps * 5) == 0:
                hiz = k / (time.time() - t0)
                print(f"  isci {no}: {k}/{son - ilk} kare, kalan ~{(son - ilk - k) / hiz:.0f} sn", flush=True)
        tarayici.close()
    ffmpeg.stdin.close()
    ffmpeg.wait()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fps", type=int, default=60)
    ap.add_argument("--cikti", default=str(BURASI / "kolaymetin-tanitim.mp4"))
    ap.add_argument("--kareler", help="virgülle ayrılmış saniyeler; yalnızca PNG üretir")
    ap.add_argument("--taslak", action="store_true", help="hızlı kodlama")
    ap.add_argument("--bas", type=float, default=0.0)
    ap.add_argument("--bitis", type=float, default=SURE)
    ap.add_argument("--isci", type=int, default=max(1, min(6, (mp.cpu_count() or 2) - 2)))
    ap.add_argument("--ses-var", action="store_true", help="tanitim/ses.wav yeniden sentezlenmesin")
    ap.add_argument("--sadece-ses", action="store_true", help="yalnızca sesi yeniden üret ve mevcut videoya tak")
    args = ap.parse_args()

    srv, port = sunucu_baslat()

    if args.kareler:
        hedef = BURASI / "kareler"
        hedef.mkdir(exist_ok=True)
        with sync_playwright() as p:
            tarayici, sayfa = sayfa_ac(p, port)
            for s in args.kareler.split(","):
                t = float(s)
                sayfa.evaluate(f"renderAt({t})")
                sayfa.screenshot(path=str(hedef / f"t{t:06.2f}.png"))
                print("kare:", t)
            tarayici.close()
        srv.shutdown()
        return

    if args.sadece_ses:
        # görüntü değişmediyse: sesi yeniden sentezle, mevcut videonun görüntüsünü kopyalayıp yeni sesle birleştir
        ses_uret(port)
        srv.shutdown()
        eski = Path(args.cikti)
        gecici = eski.with_suffix(".yeni.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(eski), "-i", str(SES_YOLU),
             "-map", "0:v", "-map", "1:a", "-c:v", "copy", *SES_AYAR, "-shortest", "-movflags", "+faststart", str(gecici)],
            check=True,
        )
        gecici.replace(eski)
        print("bitti:", eski)
        return

    ses_is = None
    if not (args.ses_var and SES_YOLU.exists()):
        ses_is = mp.Process(target=ses_uret, args=(port,))  # kareler çizilirken ses de sentezlenir
        ses_is.start()

    kare_sayisi = round((args.bitis - args.bas) * args.fps)
    kodlama = ["-preset", "veryfast", "-crf", "22"] if args.taslak else ["-preset", "slow", "-crf", "14", "-tune", "animation"]
    parcalar = BURASI / "parcalar"
    parcalar.mkdir(exist_ok=True)
    n = args.isci
    sinir = [round(kare_sayisi * k / n) for k in range(n + 1)]
    print(f"{kare_sayisi} kare, {n} isci", flush=True)
    t0 = time.time()
    isler, yollar = [], []
    for k in range(n):
        yol = str(parcalar / f"parca{k:02d}.mp4")
        yollar.append(yol)
        pr = mp.Process(target=parca_isle, args=(k, port, args.fps, sinir[k], sinir[k + 1], args.bas, yol, kodlama))
        pr.start()
        isler.append(pr)
        time.sleep(2.5)  # tarayıcılar sırayla açılsın
    for pr in isler:
        pr.join()
    if ses_is:
        ses_is.join()
    print(f"kareler bitti ({time.time() - t0:.0f} sn)", flush=True)

    liste = parcalar / "liste.txt"
    liste.write_text("".join(f"file '{Path(y).name}'\n" for y in yollar), encoding="utf8")
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(liste),
         "-ss", str(args.bas), "-t", str(args.bitis - args.bas), "-i", str(SES_YOLU),
         "-map", "0:v", "-map", "1:a", "-c:v", "copy", *SES_AYAR, "-shortest", "-movflags", "+faststart", args.cikti],
        check=True,
    )
    srv.shutdown()
    print("bitti:", args.cikti)


if __name__ == "__main__":
    main()
