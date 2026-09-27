# Katkıda bulunma

Bu rehber ve sözlükler açık kaynaktır.
Herkes yeni bir kural ya da sözlük girdisi önerebilir.

## Sözlüğe kelime önermek

Sözlükler `src/kolaymetin/data/lexicon/` klasöründedir.

| Dosya | İçerik |
|---|---|
| `jargon.yaml` | Bürokratik ifadeler |
| `foreign.yaml` | Yabancı kelimeler |
| `idioms.yaml` | Deyimler |
| `abbreviations.yaml` | Kısaltmalar |
| `synonyms.yaml` | Eş anlamlı gruplar |
| `vague.yaml` | Belirsiz ifadeler |
| `common_words.txt` | Temel kelimeler |

Bir girdi eklemek için şu adımları izleyin:

1. İlgili dosyayı açın.
2. Yeni satırı diğer satırlar gibi yazın.
3. Bir öneri ekleyin. Öneri kısa ve günlük dilde olsun.
4. Testleri çalıştırın: `pytest`.
5. Değişikliğinizi gönderin.

Örnek bir jargon girdisi:

```yaml
- {ifade: encümen, oneri: "belediye kurulu"}
```

## Yeni kural önermek

Yeni bir kural önerirken şu soruları cevaplayın:

- Kural neyi bulur?
- Bu durum okur için neden sorun?
- Hangi kaynak bu kuralı destekliyor?
- Kural hangi durumda yanlış uyarı verir?

Kuralın rehber sayfasını da yazın.
Sayfada en az 2 kötü ve 2 iyi örnek olsun.
Örnekleri kamu duyurularından seçin.

## Rehberi yazarken

Rehberi de sade dille yazın.
Araç rehberi kendi kurallarıyla denetler.
Uzun cümle ve edilgen yapı testi geçemez.

- Kısa cümleler yazın.
- Okura "siz" diye seslenin.
- Kötü örnekleri alıntı bloğuna (>) koyun.

## Lisans

Sözlük ve rehber katkılarınız CC BY 4.0 lisansı taşır.
Kod katkılarınız Apache-2.0 lisansı taşır.
