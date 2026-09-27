# KD-K01 Bürokratik ifade ve jargon

- Kategori: Kelime
- Kolay Dil ve Sade Dil: uyarı
- Sözlük: `jargon.yaml` (230'dan fazla girdi)

## Ne?

Resmî yazışmalar eski ve ağır kelimeler kullanır.
"Müracaat", "ivedilikle", "mezkûr", "tebliğ" bunlara örnektir.
Bu kural bu kelimeleri sözlükten bulur.
Çekimli hâlleri de tanır: "müracaatınız", "arz ederiz".

## Neden?

Birçok okur bu kelimeleri bilmez.
Bilenler de onları okurken yavaşlar.
Günlük dildeki karşılıkları herkes anlar.

## Örnekler

> **Kötü:** Müracaatlarınızı ivedilikle müdürlüğümüze ibraz ediniz.
>
> **İyi:** Başvurunuzu hemen müdürlüğümüze getirin.

> **Kötü:** Mezkûr tarihte su kesintisi vuku bulacaktır.
>
> **İyi:** O gün suyunuz kesilecek.

> **Kötü:** Aksi takdirde gecikme zammı tahakkuk ettirilecektir.
>
> **İyi:** Geç öderseniz borcunuz artar.

## Nasıl düzeltirim?

Araç her kelime için bir öneri verir.
Öneriyi cümleye uydurun.

## Kendi sözlüğünüzü ekleyin

Belediyenizin kendi resmî kelimeleri olabilir.
Bunları bir YAML dosyasına yazın:

```yaml
jargon:
  - ifade: encümen kararı
    oneri: belediye kurulunun kararı
```

Sonra aracı şöyle çalıştırın: `kolaymetin denetle metin.txt --sozluk ek.yaml`

## İstisnalar

Bazı kelimelerin sade karşılığı yoktur.
"İhale" bunlardan biridir.
Bu durumda kelimeyi kullanın ve bir cümleyle açıklayın.
