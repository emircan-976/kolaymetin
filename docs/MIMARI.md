# Mimari

kolaymetin tek bir Python paketidir. Kütüphane, komut satırı ve web arayüzü aynı
`analyze()` işlevini kullanır. Hiçbir bileşen ağa çıkmaz; tek istisna, kullanıcının açtığı
isteğe bağlı yeniden yazmadır (`rewrite.py`, aşağıda).

## İşlem hattı

```
metin (kullanıcının yapıştırdığı hâli)
  │
  ▼  text/normalize.py     NFC, tırnak/tire/boşluk birleştirme + karakter ofset eşlemesi
  │
  ▼  text/segment.py       yorumları maskeleme, susturma işaretleri, paragraf, başlık,
  │                        liste maddesi ve cümle bölme (kısaltma/sayı/URL farkındalığı)
  ▼  text/tokenize.py      kelime, sayı, tarih, saat, yüzde, URL, e-posta, noktalama
  │   text/syllables.py    hece sayımı (sayılar okunuşa, kısaltmalar okunuşa/harf harf)
  ▼  text/morphology.py    zeyrek (hızlandırılmış) → en olası çözümleme + işaret güvenleri
  │                        yoksa ek tabanlı sezgisel çözümleyici
  ▼  models.Document       normalleştirilmiş koordinatlarda paragraf/cümle/sözcük birimleri
  │
  ├─▶ rules/*              32 kural; profil (YAML) ile açılır/kapanır, eşikler ayarlanır
  │     lexicon.py         sözlük eşleme (kök ve çekim farkındalıklı, en uzun eşleşme)
  │
  ├─▶ readability/*        Ateşman, Çetinkaya-Uzun, Bezirci-Yılmaz, Kolay Dil Uyum Skoru
  │
  ▼  api.analyze()         bulguları orijinal metin ofsetlerine çevirir → models.Report
        │
        ├─ io/exporters.py  JSON · Markdown · bağımsız HTML (yazı tipleri ve desenler gömülü)
        ├─ cli.py           `kolaymetin denetle | sunucu | kurallar | surum`
        └─ web/app.py       FastAPI: /api/analyze, /api/upload, /api/export, /rehber/…
```

## Ofsetler

Normalleştirme metnin uzunluğunu değiştirebilir (ör. `\r\n` → `\n`, birleşik aksanlar,
art arda boşluklar). `NormalizedText` her normalleştirilmiş karakter için orijinal metindeki
başlangıç ve bitiş konumunu tutar. Kurallar normalleştirilmiş metinde çalışır; `api.analyze`
en sonda bütün bulguları ve cümleleri orijinal koordinatlara çevirir. Böylece web arayüzü
işaretleri kullanıcının yazdığı metnin tam üstüne çizer.

## Kurallar

Her kural `rules/base.py` içindeki `Rule` sınıfından türer ve `@register` süsleyicisiyle kayda
girer:

```python
@register
class LongSentence(Rule):
    id = "KD-C01"
    name = "Uzun cümle"
    level = "cümle"
    default_severity = "uyarı"

    def check(self, doc: Document, cfg: RuleConfig) -> Iterable[Finding]:
        ...
```

Sonucu kesin olan kurallar `self.finding(..., fix="yeni metin")` ile otomatik düzeltme de
verir. Metin verilirse bulgunun aralığının yerine geçer; başka bir aralık gerekiyorsa
(noktalı virgül ardından gelen harfi de büyütür) `Fix(start, end, text)` verilir. Düzeltme
ofsetleri de `api._to_original` ile özgün metne çevrilir. `models.apply_fixes` düzeltmeleri
çakışmadan uygular; `Report.fixed_text()`, `kolaymetin denetle --duzelt` ve web arayüzündeki
"Düzelt" düğmeleri onu (arayüz aynı mantığın JavaScript karşılığını) kullanır.

Kelime düzeltmeleri `text/inflect.py`deki `inflect_like(yeni, eski_kelime, eski_lemma)` ile
eski kelimenin eklerini yeni kelimeye taşır: eklerin morfem kimlikleri (zeyrek) kalıplara
çevrilir (`lAr`, `~InIz`, `YI` …), adaylar uyumla kurulur ve zeyrek'e geri çözümletilerek
doğrulanır. Doğrulanamayan aday için `None` döner; kural düzeltme vermez.

`cfg` profil dosyasındaki kural ayarıdır (`enabled`, `severity`, `params`). Kural motoru
(`api.run_rules`) kapalı kuralları atlar, satır içi susturmayı ve kullanıcının yoksaydığı
bulguları süzer, aynı yeri iki kez işaretleyen bulguları birleştirir.

Kural dosyaları:

| Dosya | Kurallar |
|---|---|
| `rules/sentence.py` | KD-C01 … KD-C11 |
| `rules/word.py` | KD-K01 … KD-K08 |
| `rules/format.py` | KD-B01 … KD-B08 |
| `rules/text_level.py` | KD-M01 … KD-M05 |

## Morfoloji

`morphology.best(kelime, bağlam)` her kelime için bir `Analysis` döndürür: kök, lemma, sözcük
türü, ek dizisi, işaretler (`is_passive`, `is_negative`, `is_converb`, `is_participle`,
`is_nominalized`, `is_finite`, `is_genitive`…) ve güven. Bağlam; kelimenin cümle sonunda mı,
yan cümle sınırında mı, büyük harfle mi başladığını söyler. Sonuçlar `lru_cache` ile önbelleğe
alınır; aynı metin ikinci kez neredeyse anında çözümlenir.

zeyrek'e iki düzeltme uygularız (bkz. `KARARLAR.md`): günlük çağrısı olmayan arama döngüsü ve
ses özelliği kümelerinin kopyalanması. Algoritma zeyrek'inkiyle aynıdır.

## Sözlükler ve profiller

Veriler `src/kolaymetin/data/` altındadır ve CC BY 4.0 lisanslıdır:

- `profiles/kolay-dil.yaml`, `profiles/sade-dil.yaml`: kural ayarları. Özel profil
  `extends: kolay-dil` ile yalnızca farkları yazar.
- `lexicon/*.yaml|txt`: jargon, yabancı kelime, deyim, kısaltma, eş anlamlı grup, belirsiz
  ifade, dolaylı hitap deseni, temel kelime listesi, bilinir kelimeler, dönüşlü fiiller.
- `ornekler/`: arayüzdeki örnek metinler (kurgusal).

Sözlük girdisinin her kelimesi için "anahtar kümesi" (yüzey biçim + en olası lemma + türetilmiş
gövde) hesaplanır. Metindeki her kelime için de aynı anahtarlar çıkarılır. Eşleşme, ardışık
kelimelerin anahtar kümeleri kesişince olur; böylece "arz etmek" girdisi "arz ederiz", "müracaat"
girdisi "müracaatlarınızı" biçimini yakalar.

## Web uygulaması

- Sunucu: FastAPI + Uvicorn. Açılışta zeyrek ve sözlük arka planda yüklenir.
- Güvenlik: sıkı İçerik Güvenliği Politikası (yalnızca `'self'`), metin günlüğe yazılmaz,
  profil adı yalnızca yerleşik profiller arasından seçilebilir (sunucuda dosya okunamaz).
- Ön yüz: derleme adımı olmayan HTML + CSS + JavaScript. Metin alanının arkasında aynı
  yazı tipiyle dizilmiş bir "arka plan" katmanı düzeltmen işaretlerini çizer; seçim kutusu
  ayrı bir katmanda satır başına tek dikdörtgen olarak çizilir.
- Görsel dil: `static/style.css` tek renk kaynağıdır; `stil-rehberi.html` bütün parçaları
  gösterir. `tests/test_stil.py` yasak listesini, `scripts/kontrast_denetle.py` WCAG
  kontrastını denetler.

## Performans

Gerçekçi 5.000 kelimelik metin yaklaşık 1 saniyede, kelimelerinin çoğu farklı olan en kötü
durum yaklaşık 2 saniyede çözümlenir (zeyrek yükleme süresi hariç). Darboğaz morfolojidir;
yüzey biçim önbelleği ve kelime önbelleği bu süreyi belirler.

## Yeniden yazma (isteğe bağlı dil modeli)

`rewrite.py`, `/api/yeniden-yaz` ile bir cümleyi OpenAI uyumlu bir sohbet API'sine gönderir
(`/chat/completions`, yalnızca standart kütüphane: `urllib`). Sağlayıcı istekte kimliğiyle
(`ollama`, `gemini` …) gelir; adres sunucudaki sabit listeden (`PROVIDERS`) ya da
`KOLAYMETIN_LLM_URL`den okunur. Kullanıcı adres veremez (SSRF). Vercel'de (`VERCEL=1`) yerel
sağlayıcılar kapalıdır.

Gelen öneri temizlenir (`<think>`, kod çiti, tırnak), sonra `check()` iki şeyi yapar:
`facts()` tarih, yıl, saat, sayı ve adresleri karşılaştırılabilir biçime getirir ("01.12.2026"
ile "1 Aralık 2026" aynıdır) ve özgün cümleyle öneriyi karşılaştırır; özel adlar
`build_document` ile bulunur. Ardından iki metin `analyze()` ile denetlenir ve bulgu sayısı ile
uyum skoru önce/sonra olarak döner. Eksik ya da yeni bilgi varsa `applicable: false` olur.

## Gizlilik

- Metin yalnızca istek süresince bellekte durur; diske ve günlüğe yazılmaz.
- Hiçbir dış kaynak (yazı tipi, betik, görsel) yüklenmez; HTML rapor bile bağımsızdır.
- `tests/test_performance_network.py` dış bağlantı ve DNS çağrılarını engelleyerek bütün
  işlem hattını çalıştırır.
