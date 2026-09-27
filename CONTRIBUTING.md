# Katkıda bulunma

kolaymetin'e katkı verdiğiniz için teşekkürler. Bu belge geliştirme ortamını, testleri ve
katkı kurallarını anlatır. Sözlük ve rehber katkıları için ayrıca
[docs/rehber/katki.md](docs/rehber/katki.md) sayfasına bakın.

## Geliştirme ortamı

```bash
uv venv --python 3.12
uv pip install -e ".[dev]"
```

`uv` yoksa:

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

## Kontroller

Her değişiklikten sonra şunları çalıştırın:

```bash
pytest --cov
```

```bash
ruff check src tests scripts
```

```bash
mypy src
```

```bash
python scripts/kontrast_denetle.py
```

Beklenen: bütün testler geçer, kapsam en az %85, ruff ve mypy temiz, kontrast denetimi geçer.

## Kod kuralları

- Kod tanımlayıcıları İngilizce; kullanıcıya görünen her metin Türkçe.
- Kullanıcıya gösterilen mesajlar da Kolay Dil'e uyar: kısa cümle, doğrudan hitap, edilgen yok.
  "Edilgen çatı tespit edildi" değil, "Bu cümlede işi kimin yaptığı belli değil." yazın.
- Türkçe büyük/küçük harf için `str.lower()` kullanmayın; `turkish_lower()` ve `turkish_upper()`
  kullanın.
- Ağ çağrısı yapan hiçbir kod eklemeyin. Telemetri, CDN, dış yazı tipi yasaktır.
- Kodda `TODO` ya da `FIXME` bırakmayın (bir test bunu denetler).

## Yeni kural eklemek

1. Uygun dosyaya (`rules/sentence.py`, `word.py`, `format.py`, `text_level.py`) bir `Rule`
   alt sınıfı ekleyin ve `@register` ile kaydedin.
2. Kuralı iki profile de (`data/profiles/*.yaml`) ekleyin.
3. `tests/test_rules.py` dosyasına en az 3 pozitif ve 3 negatif örnek ekleyin.
4. `docs/rehber/KD-XNN.md` rehber sayfasını yazın (Ne? Neden? Örnekler, İstisnalar; en az 2
   kötü/iyi örnek çifti). Rehber metni kendi kurallarımızdan geçmelidir.
5. Korpus beklentilerini gerekirse güncelleyin: `python scripts/beklenen_uret.py tests/corpus/KLASOR`
   çıktısını gözden geçirip elle düzenleyin.

## Görsel dil

Arayüz "Düzeltmen Masası" görsel diline birebir uyar (bkz. README'deki Görsel dil bölümü).

- Renkler yalnızca `style.css` içindeki `:root` değişkenleriyle kullanılır.
- Köşe yarıçapı 0; bulanık gölge, gradyan, cam efekti yok.
- Tek yazı tipi ailesi: Atkinson Hyperlegible Next ve Mono.
- İkonlar `scripts/ikonlar.py` içinde 16×16 ASCII çizimle tanımlanır; ikon kütüphanesi ve emoji yok.
- Yeni bir bileşen önce `static/stil-rehberi.html` sayfasına eklenir.

`tests/test_stil.py` bu kuralların çoğunu otomatik denetler.

## Ekran görüntüleri

```bash
pip install -e ".[ekran]"
playwright install chromium
python scripts/ekran_goruntusu.py
```

Görüntüleri aldıktan sonra README'deki öz değerlendirme listesine göre bakın.

README görselleri (`docs/readme/`: künye, düzeltme provası, kural sayfası) renkleri `style.css`'ten
okur. Renk, sürüm ya da kural sayısı değişince yeniden üretin:

```bash
python scripts/readme_gorselleri.py
```

## Lisans

Kod katkıları Apache-2.0, rehber ve sözlük katkıları CC BY 4.0 lisansı taşır.
