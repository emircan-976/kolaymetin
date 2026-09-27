# KD-K05 Deyim ve mecaz

- Kategori: Kelime
- Kolay Dil: uyarı
- Sade Dil: bilgi
- Sözlük: `idioms.yaml` (90'dan fazla girdi)

## Ne?

Deyim, kelimelerin gerçek anlamıyla söylenmeyen kalıplardır.
"Göz yummak", "el atmak", "masaya yatırmak" bunlara örnektir.
Bu kural deyimleri çekimli hâlleriyle bulur.

## Neden?

Zihinsel engeli olan kişiler deyimi kelimesi kelimesine anlar.
"Sorunu masaya yatırdık" cümlesi onlar için bir masa ve bir sorun anlatır.
Türkçeyi yeni öğrenenler de deyimleri bilmez.

## Örnekler

> **Kötü:** Belediye çöp sorununa el attı.
>
> **İyi:** Belediye çöp sorununu çözmek için çalışıyor.

> **Kötü:** Ödemeleri son güne bırakmak borcunuzun artmasına yol açar.
>
> **İyi:** Son güne kadar ödemezseniz borcunuz artar.

## Nasıl düzeltirim?

Araç her deyimin düz anlamını verir.
Deyim yerine bu anlamı yazın.

## İstisnalar

Bazı kalıplar günlük dile yerleşmiştir.
Okurunuz bunları iyi biliyorsa uyarıyı yoksayabilirsiniz.

Bazı deyimler gerçek anlamıyla da sık geçer: "Otobüs yola çıktı", "Kapıyı açın", "Kırmızı düğmeye basın".
Sözlükte bu deyimlerin yanında `iki_anlamli: true` yazar.
Araç bunlar için yalnızca **bilgi** verir ve "Mecaz anlamda kullandıysanız" der.
Sözlükte `gercek` listesi de olabilir: `[otobüs, tren, kapıyı]`.
Cümlede bu kelimelerden biri geçerse araç deyimi gerçek anlamıyla okur ve uyarmaz.
