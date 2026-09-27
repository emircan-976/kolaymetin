# Proje tanıtım sunumu

Topluma Hizmet Uygulamaları dersi için kolaymetin tanıtım sunumu (17 slayt, 16:9).

- Canlı sunum: <https://claude.ai/artifact/7dJTHinGHBUTEQwAE5cFBZ>
- Bu klasör, sunumun 28 Eylül 2026 tarihli (sürüm `1790544018-0b95`) yedeğidir.

## İçerik

| Dosya | Ne |
|---|---|
| `project/deck.json` | Başlık, slayt sırası, bölümler, yazı tipleri |
| `project/slides/*.html` | Her slayt bir dosya; tek bir `<section>` |

Slayt sırası: kapak, soru, ihtiyac, ceviri, amac, arastirma, surec, once, sonra, kurallar,
masa, erisim, sinama, etki, etik, film, kapanis.

## Görseller

Slaytlardaki `/_blob/<kimlik>` adresleri sunucudaki yüklenmiş dosyalardır. Hepsinin kaynağı bu
depodadır; sunum kaybolursa aynı dosyaları yeniden yükleyip adresleri değiştirmek yeterli.

| Kimlik | Kaynak dosya | Kullanıldığı slayt |
|---|---|---|
| `94dcdb2444eaa58e28ae86f0b87ed99d` | `tanitim/gorsel/bos-durum.png` | kapak |
| `0de8d0fcf41e65f338f47e863bc14b5f` | `docs/ekran/rehber.png` | arastirma |
| `434a72379947e1870a47c1582be4fc19` | `tanitim/gorsel/kapak-cumle.png` | kurallar |
| `5cf4cc14fd5599f7ebff00f0821b85fb` | `tanitim/gorsel/kapak-kelime.png` | kurallar |
| `5988fb8a289e1602cc757e1929de2587` | `tanitim/gorsel/kapak-bicim.png` | kurallar |
| `5052f3f20f09a3f753f9910fd2e34e0b` | `tanitim/gorsel/kapak-metin.png` | kurallar |
| `cece9b19cc5635dd714d02a3240ff153` | `docs/ekran/dolu.png` | masa |
| `d590659ee7a9da1cb887ce9c76f02fea` | `docs/ekran/koyu.png` | erisim |
| `786e84e4b41b10acd5b9dd2ea7a7222c` | `docs/ekran/gri-tonlu.png` | erisim |
| `e03cf89166f3ec6258c7455b617ff7c3` | `docs/ekran/mobil.png` | erisim |
| `f6009f514af1e5d113eaaadf301680af` | `tanitim/kareler/t024.80.png` | film (kapak karesi) |
| `5c25709a3294c0cfc84e4d985c65ec79` | `docs/readme/kolaymetin-tanitim.mp4` | film (sessiz oynar) |

Yüklenen ama şu an kullanılmayan: `ff0b87b1f1f24cad6e8a52e37c8d1f99` (`docs/ekran/rapor.png`).

## Görsel dil

Uygulamanın "Düzeltmen Masası" dili: kâğıt `#F3EEE3` / `#E9E2D3`, mürekkep `#1B1A17`, soluk
mürekkep `#55504A`, kırmızı `#B42D26`, mavi `#23408E`, sarı `#FFE14D`. Koyu slaytlar (film,
kapanış): zemin `#1B1A17`, yazı `#EFE8D8`, soluk `#B8AE9C`, kırmızı `#FF6B5E`. Yazı tipleri
Atkinson Hyperlegible Next ve Mono (Google Fonts).
