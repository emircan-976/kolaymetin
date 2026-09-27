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
