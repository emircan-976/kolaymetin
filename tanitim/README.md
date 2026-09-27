# Tanıtım filmi

72 saniyelik, 1920×1080 tanıtım filmi. Görsel dil uygulamanın kendisiyle aynı: "Düzeltmen Masası"
(krem kâğıt, siyah mürekkep, kırmızı ve mavi nokta renk, fosforlu kalem, 1-bit dither, Atkinson Hyperlegible).

- `video.html` — bütün sahneler, zaman çizelgesi, müzik ve ses efektleri (Web Audio ile sentezlenir;
  dış ses dosyası yok). Tarayıcıda açıp "Sesli oynat" düğmesiyle önizlenebilir
  (`python -m http.server` ile proje kökünden sunun: `http://localhost:8000/tanitim/video.html`).
  `?t=33` ile belirli bir andan başlar.
- `hazirla.py` — projedeki dither görselleri renklendirip `gorsel/` klasörüne yazar.
- `kaydet.py` — kareleri Edge (Playwright) ile çizer, ffmpeg ile `kolaymetin-tanitim.mp4` üretir.

```bash
python tanitim/hazirla.py
```

```bash
python tanitim/kaydet.py
```

Hızlı taslak için `--fps 30 --taslak`, sesi yeniden sentezlememek için `--ses-var`,
tek kare denetimi için `--kareler 4,18.5,33` kullanın. Gerekenler: ffmpeg, Microsoft Edge, `playwright`.

## README için kısaltılmış sürümler

Film ya da arayüz değişince bu iki dosya da yeniden üretilmelidir; ikisi de `kaydet.py` çıktısından
ffmpeg ile alınır:

```bash
# 72 sn, 1280×720, 30 kare/sn, sesli (docs/readme/kolaymetin-tanitim.mp4)
ffmpeg -i tanitim/kolaymetin-tanitim.mp4 -vf scale=1280:720:flags=lanczos -r 30 \
  -c:v libx264 -profile:v high -preset slow -b:v 1100k -pix_fmt yuv420p \
  -c:a aac -b:a 96k -movflags +faststart docs/readme/kolaymetin-tanitim.mp4

# 11–23. saniye, 800×450, 10 kare/sn (docs/readme/tanitim.gif): logo ve ilk denetim.
# hqdn3d kâğıt grenini sabitler; yoksa her kare yeniden yazılır ve GIF iki kat büyür.
ffmpeg -ss 11 -t 12.2 -i tanitim/kolaymetin-tanitim.mp4 \
  -vf "fps=10,scale=800:450:flags=lanczos,hqdn3d=2:2:12:12,split[a][b];[a]palettegen=max_colors=48:stats_mode=diff[p];[b][p]paletteuse=dither=none:diff_mode=rectangle" \
  docs/readme/tanitim.gif
```
