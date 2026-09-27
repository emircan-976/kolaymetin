# KD-K06 Seyrek kelime

- Kategori: Kelime
- Kolay Dil: bilgi
- Sade Dil: kapalı
- Liste: `common_words.txt` (5.000'den fazla temel kök)

## Ne?

Araç, sık kullanılan temel kelimelerin bir listesini taşır.
Bu kural, kökü listede olmayan kelimeleri işaretler.

Araç kelimenin ekli hâlini değil, kökünü arar: "şekilde" → "şekil".
Anlamı kökten kolayca çıkan türemiş kelimeleri de bilinir sayar.
"Süreli" kelimesini "süre", "kuvvetli" kelimesini "kuvvet" bilen okur anlar.
"-lı", "-sız", "-lık", "-ki" ve küçültme ekleri buna girer.

## Neden?

Kolay Dil'de herkesin bildiği kelimeleri seçeriz.
Listede olmayan bir kelime bazı okurlara yabancı gelebilir.
Araç yalnızca bilgi verir, çünkü liste eksik olabilir.

## Örnekler

> **Kötü:** Şebekedeki bulanıklık kısa sürede giderilecek.
>
> **İyi:** Musluktan önce bulanık su akabilir. Su birkaç dakika sonra temizlenir.

> **Kötü:** Hanede ikamet eden bireylerin gelir belgesi gerekli.
>
> **İyi:** Evde yaşayan herkesin gelir belgesini getirin.

## Nasıl düzeltirim?

- Daha sık kullanılan bir kelime seçin.
- Kelime gerekliyse bir cümleyle açıklayın.

## Listeyi genişletin

Okurlarınızın iyi bildiği kelimeleri kendi sözlüğünüze ekleyin:

```yaml
sik_kelimeler: [muhtar, imece, pazar yeri]
```

## İstisnalar

Özel adlar, kısaltmalar ve sayılar bu kurala girmez.
Araç cümle başındaki adları da tanır:

- Sık kullanılan kişi adları ve soyadları (`names.txt`): "Ali", "Ayşe", "Korkmaz".
- Metnin başka bir yerinde kesme işaretiyle ek alan adlar: "Pıtır'ın".
- Cümle başında sık geçen, metinde hiç küçük harfle yazılmayan kelimeler.
