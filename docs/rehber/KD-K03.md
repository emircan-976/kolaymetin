# KD-K03 Açıklanmamış kısaltma

- Kategori: Kelime
- Kolay Dil ve Sade Dil: uyarı
- Sözlük: `abbreviations.yaml` (130'dan fazla girdi)

## Ne?

Bu kural kısaltmaları bulur.
Tamamı büyük harf olan kelimeleri ve sözlükteki kısaltmaları tanır.
Kısaltmanın ilk geçtiği yerde açılımı yoksa uyarır.
İkinci kez geçtiğinde uyarmaz.

## Neden?

Okur kısaltmanın anlamını bilmeyebilir.
Ekran okuyucular kısaltmaları bazen harf harf, bazen yanlış okur.
Açılımı bir kez yazmak bu sorunu çözer.

## Örnekler

> **Kötü:** Başvurunuzu SGK'ya yapın.
>
> **İyi:** Başvurunuzu Sosyal Güvenlik Kurumuna (SGK) yapın.

> **Kötü:** Toplanma alanlarını AFAD belirleyecek.
>
> **İyi:** Toplanma alanlarını afet kurumu AFAD belirleyecek.

## Nasıl düzeltirim?

- Kısaltmanın açık hâlini ilk geçtiği yerde yazın.
- Kısaltmayı hemen arkasından parantez içinde verin.
- Kolay Dil metninde mümkünse kısaltmayı hiç kullanmayın.

## İstisnalar

Herkesin bildiği kısaltmalar uyarı almaz.
"TL", "T.C." ve adreslerdeki "Cad.", "Sok.", "No." bunlara örnektir.
Sözlükte bu kısaltmaların yanında `bilinir: true` yazar.
