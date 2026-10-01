# KD-B04 Tarih biçimi

- Kategori: Biçim
- Kolay Dil: rakamla yazılmış tarih için uyarı, haftanın günü yoksa bilgi
- Sade Dil: rakamla yazılmış tarih için bilgi

## Ne?

Bu kural "15.09.2026" gibi rakamlı tarihleri bulur.
"2026-09-15" ve "15-09-2026" yazımlarını da tanır.
Kolay Dil profilinde haftanın günü eksik olan tarihlere de bakar.

İki yanlışı hata olarak işaretler.
Takvimde olmayan tarih: "31 Şubat 2026".
Tarihe uymayan gün: 1 Aralık 2026 bir Salı günüdür, "Pazartesi" yazmak yanlıştır.

## Neden?

Rakamlı tarihte gün ile ay karışabilir.
Ayın adı tarihi hemen anlaşılır yapar.
Birçok kişi günlerini haftanın günüyle takip eder.
"Salı günü" bilgisi okura hazırlanma kolaylığı sağlar.

## Örnekler

> **Kötü:** Kesinti 15.09.2026 tarihinde yapılacaktır.
>
> **İyi:** Kesinti 15 Eylül 2026 Salı günü.

> **Kötü:** Başvurular 1 Aralık'ta başlıyor.
>
> **İyi:** Başvurular 1 Aralık 2026 Salı günü başlıyor.

> **Kötü:** Başvurular 1 Aralık 2026 Pazartesi günü başlıyor.
>
> **İyi:** Başvurular 1 Aralık 2026 Salı günü başlıyor.

## Nasıl düzeltirim?

Araç tarihi ayın adıyla ve haftanın günüyle yazar.
Öneriyi kullanın.

## İstisnalar

Yıl yazmazsanız araç haftanın gününü hesaplayamaz.
Bu durumda günü kendiniz ekleyin.

Tarih aralıklarında araç haftanın gününü istemez: "6 Şubat - 2 Mart 2026".
İki uca da gün eklemek metni uzatır.
Geçmiş yıllara ait tarihlerde de istemez: "23 Nisan 1920".
