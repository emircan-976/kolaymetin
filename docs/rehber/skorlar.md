# Skorlar

kolaymetin dört skor gösterir.
Üçü bilinen okunabilirlik formülleridir.
Dördüncüsü kolaymetin'in kendi Kolay Dil Uyum Skoru'dur.

**Önemli:** Bu formüllerin yazarları Kolay Dil'i hedeflemedi.
Yalnızca hece ve cümle uzunluğunu ölçerler.
Kelimenin tanıdık olup olmadığını, cümlenin anlamını ölçmezler.

## Nasıl sayarız?

- Başlıkları saymayız. Başlık kısa ve noktalamasızdır, ortalamayı bozar.
- Liste maddelerini birer cümle sayarız.
- Sayılar, tarihler ve saatler birer kelimedir.
- Sayının hecelerini okunuşuna göre sayarız: "15" → "on beş" → 3 hece.
- İnternet ve e-posta adreslerini saymayız.

## Ateşman (1997)

Ateşman, Flesch formülünü Türkçeye uyarladı.

```
Ateşman = 198,825 − 40,175 × (hece / kelime) − 2,610 × (kelime / cümle)
```

| Puan | Düzey |
|---|---|
| 90–100 | çok kolay |
| 70–89 | kolay |
| 50–69 | orta güçlükte |
| 30–49 | zor |
| 1–29 | çok zor |

Yüksek puan daha kolay metin demektir.

## Çetinkaya-Uzun (2010)

```
Çetinkaya-Uzun = 118,823 − 25,987 × (hece / kelime) − 0,971 × (kelime / cümle)
```

| Puan | Düzey | Sınıf |
|---|---|---|
| 51 ve üstü | bağımsız okuma | 5, 6 ve 7. sınıf |
| 35–50 | eğitsel okuma | 8 ve 9. sınıf |
| 0–34 | engellenmiş okuma (zor) | 10, 11 ve 12. sınıf |

## Bezirci-Yılmaz (2010)

```
YOD = √( OKS × (H3 × 0,84 + H4 × 1,5 + H5 × 3,5 + H6 × 26,25) )
```

- OKS: cümle başına ortalama kelime sayısı
- H3: cümle başına düşen 3 heceli kelime sayısı
- H4: cümle başına düşen 4 heceli kelime sayısı
- H5: cümle başına düşen 5 heceli kelime sayısı
- H6: cümle başına düşen 6 ya da daha çok heceli kelime

Sonuç yaklaşık eğitim yılını gösterir.
Düşük değer daha kolay metin demektir.

| Değer | Düzey |
|---|---|
| 8 ve altı | ilköğretim |
| 8–12 | lise |
| 12–16 | lisans |
| 16'dan büyük | akademik |

## Kolay Dil Uyum Skoru

Bu skor kurallara dayanır.
Her bulgu bir ceza puanı getirir.

```
ceza      = Σ (ağırlık × güven)        ağırlık: hata = 3, uyarı = 1, bilgi = 0,25
normalize = ceza / cümle sayısı
skor      = 100 × e^(−k × normalize)   k: Kolay Dil 0,6 · Sade Dil 0,5
```

Güven, aracın bulgudan ne kadar emin olduğunu gösterir.
Emin olmadığı bulgular skoru daha az etkiler.

Araç skoru kategori bazında da gösterir: Cümle, Kelime, Biçim, Metin.
"Bu skor nasıl hesaplandı?" panelinde her kuralın katkısını görürsünüz.

Metin 3 cümleden kısaysa skor güvenilir değildir.
Araç bunu bir notla belirtir.

## Skoru nasıl yorumlarım?

Skor bir "geçti" ya da "kaldı" notu değildir.
Skor, metni düzeltirken ilerlemenizi görmenize yardım eder.
Son kararı her zaman hedef okurlarla yaptığınız test verir.

## Kaynaklar

- Ateşman, E. (1997). Türkçede okunabilirliğin ölçülmesi. *Dil Dergisi*, 58, 71–74.
- Çetinkaya, G. (2010). *Türkçe metinlerin okunabilirlik düzeylerinin tanımlanması ve sınıflandırılması* (Doktora tezi). Çukurova Üniversitesi.
- Bezirci, B. ve Yılmaz, A. E. (2010). Metinlerin okunabilirliğinin ölçülmesi üzerine bir yazılım kütüphanesi ve Türkçe için yeni bir okunabilirlik ölçütü. *DEÜ Mühendislik Fakültesi Fen ve Mühendislik Dergisi*, 12(3), 49–62.

Katsayıları ve düzeyleri nasıl doğruladığımızı `docs/KARARLAR.md` dosyasında anlatıyoruz.
