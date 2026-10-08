# Değişiklik günlüğü

Biçim [Keep a Changelog](https://keepachangelog.com/tr/1.1.0/) önerisine, sürüm numaraları
[Anlamsal Sürümleme](https://semver.org/lang/tr/) kurallarına uyar.

## [Yayımlanmamış]

### Otomatik düzeltme (2026-10-08)

Araç artık yalnızca işaretlemiyor, sonucu kesin olan düzeltmeleri metne kendisi uyguluyor.
Testler: `tests/test_duzeltme.py`.

#### Eklendi
- `Finding.fix` (`Fix`: `start`, `end`, `text`): bulgunun otomatik düzeltmesi. Ofsetler
  `start`/`end` gibi özgün metindedir; web API'sinde UTF-16 birimidir.
- `kolaymetin.apply_fixes(metin, bulgular)` ve `Report.fixed_text()`: düzeltmeleri uygular.
  Aralığı çakışan düzeltmelerden önce başlayan uygulanır; öteki yeni denetimde yeniden önerilir.
- Düzeltme veren kurallar:
  - KD-B01: "yirmi beş" → "25", "1250000 lira" → "1.250.000 lira"
  - KD-B02: "XV." → "15."
  - KD-B03: "2.5 milyon" → "2,5 milyon"
  - KD-B04: "01.12.2026" → "1 Aralık 2026 Salı", "01.12.2026'da" → "1 Aralık 2026'da",
    "25 Aralık 2026" → "25 Aralık 2026 Cuma"
  - KD-B05: "14.30'da" → "saat 14.30'da"
  - KD-B06: "Okul kapandı; öğrenciler…" → "Okul kapandı. Öğrenciler…"
  - KD-B07: "LÜTFEN … ANKARA'DA SGK BİNASI" → "Lütfen … Ankara'da SGK binası"
- Kelime düzeltmeleri, ekler korunarak (`text/inflect.py`):
  - KD-K01: "Müracaatlarınızı" → "Başvurularınızı", "müracaat ediniz" → "başvurun",
    "tebliğ edildi" → "bildirildi", "riayet edilmesi" → "uyulması", "doldurunuz" → "doldurun"
  - KD-K02: "Aktivitelere" → "Etkinliklere"
  - KD-K03: "SGK" → "Sosyal Güvenlik Kurumu (SGK)", "vb." → "ve benzeri"
  - KD-K08: "Dokümanları" → "Belgeleri" (metnin tercih edilen terimi)

  Ekler morfem kimliklerinden ünlü uyumu ve ünsüz benzeşmesiyle yeniden kurulur; aday biçim
  zeyrek'e geri çözümletilir. Doğrulanamayan, birden çok anlama gelen ya da önerisi birden çok
  seçenek olan ("hemen, hızlıca") kelimeye düzeltme verilmez.
- Web arayüzü: her bulgu kartında **Düzelt**, bulgu listesinin üstünde **Hepsini düzelt (N)**
  (süzgeçlerde görünen bulgular). İkisi de Ctrl+Z ile geri alınır.
- Komut satırı: `kolaymetin denetle GİRDİ --duzelt` rapor yerine düzeltilmiş metni yazar. Metin
  raporu kaç bulgunun otomatik düzeltilebileceğini söyler.
- Markdown ve HTML raporlarında "Otomatik düzeltilmiş metin" bölümü.

#### Düzeltildi
- KD-B01, tırnak içindeki sayıdan sonra gelen "milyon"u ('"2,5" milyon') yazıyla yazılmış
  sayı sanıyordu.

### 9. tur: gerçek dünya denemesinden kalan eksikler (2026-10-08)

Regresyon testleri: `tests/test_kalan_eksikler.py`.

#### Düzeltildi: slayt (sunum) PDF'leri
- Noktasız başlık ve kısa bilgi satırları sonraki satırlarla birleşip 65–80 kelimelik "cümleler"
  oluşturuyordu. Kısa, noktasız bir satırdan sonra büyük harfle başlayan satır yeni paragraf;
  uzun düzyazı satırı (sayfadaki en uzun satırın %60'ından uzun) bölünmüyor.
- Harfleri aralıklı başlıklar birleşiyor: "G E Ç E N  Y I L" → "GEÇEN YIL".
- Sayfaların çoğunun kenarında yinelenen numaralı üst/alt bilgi ("Topluma Hizmet Uygulamaları 12")
  atılıyor. Yalnızca bazı sayfalarda geçen "Adım 1", "Adım 2" kalıyor.
- Noktalamadan önceki boşluk siliniyor: "dokunur ." → "dokunur.".
- Ders sunumu PDF'inde bulgu 510 → 421, uyum skoru 27 → 41. Kalan uzun cümleler PDF
  tablolarından geliyor: pypdf tablo satırlarını tek satıra döküyor.

#### Düzeltildi: cümle bölme
- Emoji cümleyi bitirebilir: "bekliyoruz 🎉 Ücretsiz!" iki cümle. Noktalamadan sonra gelen emoji
  ("Harika! 🎉 Gelin.") cümle bölmeyi tamamen engelliyordu. Cümle içindeki emoji ("Bugün 😊 güzel
  bir gün.") bölmez; emojiyle biten tek satır başlık sayılmıyor.

#### Düzeltildi: kelime ve cümle kuralları
- Birleşik adların çoğulu ("huzurevlerini", "buzdolaplarını") seyrek kelime sayılıyordu: zeyrek
  çoğulda kök olarak "huzurev" veriyor; artık sözlükteki ad ("huzurevi") kullanılıyor.
- "-mAzlIk" ile kurulan adlar ("böbrek yetmezliği", "anlaşmazlık") yan cümle ve adlaşmış eylem
  sayılıyordu (KD-C06, KD-C07).
- "açılmak" dönüşlü fiil listesinde: "Kütüphane pazartesi açılacak" yalnızca bilgi veriyor.
- KD-K07: ardından sayı gelen ifade belirsiz değil ("akşam saat 8'den sonra").

#### Değişti
- Türkçe olmayan metinde (Kiril, Arap yazısı, İngilizce) uyum skoru hesaplanmıyor ("—"). Önce
  "Türkçe görünmüyor" notuyla birlikte "100 / 100" gösteriliyordu.

### 8. tur: kelime listeleri (2026-10-08)

Regresyon testleri: `tests/test_profiles_lexicon.py` (listeler arası çelişki, sabit terimler,
listeden önceki belirsiz ifade).

#### Eklendi
- Jargon listesi 238 → 368 ifade: resmî yazışma kalıpları ("teşkil etmek", "riayet etmek",
  "muhafaza etmek", "takdirde", "ekte sunmak", "kayıt altına almak", "göz önünde bulundurmak",
  "hâlihazırda", "vefat etmek", "ihlal etmek", "sevk etmek" …).
- Yabancı kelime listesi 168 → 260: sağlık ("enfeksiyon", "kronik", "diyabet", bölüm adları
  "kardiyoloji", "nöroloji" …), teknoloji ("wifi", "laptop", "spam" …), kent ve para terimleri.
- Belirsiz ifade listesi 38 → 68 ("akşam saatlerinde", "birkaç gün", "gerekli görülürse" …).
- 26 kısaltma (QR, KBB, EKG, MR, HGS, YKS, LGS, KYK, GSS …), 6 eş anlamlı grubu, 17 bilinen uzun
  kelime ("havaalanı", "milletvekili", "uluslararası" …), temel listeye ~100 yaygın kelime ("veli",
  "tarım", "sinir", "yorum", "idrar", "vesikalık" …).
- Sözlük girdisinde `sabit: true`: herkesin bildiği resmî ad ("asgari ücret") uyarı vermez.

#### Düzeltildi
- 14 kelime hem temel listede hem jargon/yabancı listesindeydi. Herkesin bildiği "proje", "risk",
  "kontrol", "şarj", "tasarruf", "itiraz etmek", "emlak" artık işaretlenmiyor.
- "Gerekli belgeler:" ve altında madde listesi olan metne "Belgeleri madde madde yazın" denmiyor.
- Sade metinlerden oluşan bir deneme derleminde (26 metin, 901 kelime) yabancı kelime uyarısı
  6'dan 2'ye, seyrek kelime uyarısı 13'ten 2'ye indi.

### 7. tur: Vercel'deki sürümün ikinci denemesi (2026-10-02)

Regresyon testleri: `tests/test_vercel_deneme2.py`.

#### Düzeltildi: rapor güvenilirliği
- Yoksayılan bulgular skoru yükseltiyor ama rapor bunu gizliyordu. Rapor ve arayüz artık "3 bulgu
  yoksayıldı ve skora katılmadı. Yoksaymadan skor: 30" diyor; raporda "Yoksayılan bulgular"
  bölümü var (`Report.ignored_findings`, `ComplianceScore.raw_value`).
- Çetinkaya-Uzun 0'ın altına iniyordu (-1,4) ve ona sınıf düzeyi veriliyordu. Puan 0'da duruyor;
  ölçeğin altındaki değere sınıf düzeyi verilmiyor.
- Rapor tarihi UTC ve ISO biçimindeydi; gece indirilen rapor önceki günü gösteriyordu. Tarih
  Türkiye saatinde: "2 Ekim 2026 Cuma, 00.44".
- Rapordaki rehber bağlantıları göreli düz metindi ("/rehber/KD-C01"). Web'den indirilen raporda
  tam adresli gerçek bağlantı; CLI'de `KOLAYMETIN_ADRES` ortam değişkeniyle.
- Arayüz, raporun süzgeçlere bakmadığını söylüyor.

#### Düzeltildi: Türkçe metin işleme
- "Belediye TARAFINDAN": büyük harfli kelime çok kelimeli bir özel adın parçası sanılıyordu.
- Soru ya da ünlemden sonra küçük harfle başlayan cümle bölünüyor: "Su var mı? evet var.",
  "Dikkat! su kesilecek." "Geliyor musun? diye sordu." bölünmüyor.
- Markdown bağlantı adresi KD-C09'a, HTML etiketleri ("img", "src") KD-K06'ya takılıyordu; ikisi de
  denetlenmiyor.

#### Düzeltildi: kurallar
- KD-K05: "Kapı açıldı." gerçek anlam.
- KD-C04: yüklem olan "yok" işaretlenmiyor ("Yarın su yok.").
- KD-K06: "Kemeraltı" özel ad.
- KD-C03: "Okul yarın açılıyor." da "Okul açıldı." gibi edilgen okunuyor (zeyrek önce nadir
  "açılamak" fiilini seçiyordu).
- KD-K02: 37 yabancı kelime eklendi: "meeting", "password", "team" gibi.
- KD-B01: binlik ayırıcısız büyük sayı ("1250000 lira" → "1.250.000"); yalnızca ardından birim
  ya da "kişi", "adet" gibi bir ad gelince.

#### Düzeltildi: arayüz ve altyapı
- Cümleler sekmesi başlığı da sayıyordu ve 2'den başlıyordu; numara 1'den başlıyor.
- Örnek ya da dosya yüklendikten sonra Ctrl+Z eski metni geri getiriyor.
- Hız sınırı: Vercel'de IP başına dakikada 60 API isteği (`KOLAYMETIN_HIZ_SINIRI`), aşınca Türkçe
  429. "Yazarken denetle" uzun metinde daha geç başlıyor (100.000 karakterde 3 sn).
- `X-Frame-Options: DENY` (CSP'deki `frame-ancestors 'none'` eski tarayıcılar için).
- Yüklenen dosyanın adı yanıtta temizleniyor: klasör kısmı ve `<`, `>` gibi karakterler atılıyor.

### 6. tur: Vercel'deki sürüm tarayıcıda (2026-10-02)

Çevrim içi sürüm Chrome'da gezildi, API'si doğrudan denendi. Regresyon testleri:
`tests/test_vercel_deneme.py`.

#### Düzeltildi: arayüz
- Gizlilik metni yanlıştı: "bu bilgisayarın belleğinde kalır", "Metin bilgisayarınızdan çıkmaz".
  Metin denetim için sunucuya gönderilir ve saklanmaz; sayfa, meta açıklama ve README bunu söylüyor.
- Emojili metinde işaretler kayıyordu: Python kod noktası, tarayıcı UTF-16 sayar. `/api/analyze`
  ofsetleri UTF-16'ya çevirir.
- "Metinde göster" ve Cümleler sekmesi editörü ekrana getirmiyordu; seçili ama görünmeyen metin bir
  tuşla silinebiliyordu.
- Örnek seçmek ve dosya yüklemek yazılmış metni sormadan siliyordu; artık onay isteniyor. Örnek
  listesi seçimden sonra "Seçin…"e dönüyor, aynı örnek yeniden seçilebiliyor.
- Geniş ekranda editör yapışkan: bulgu kartlarında aşağı inince ekranda kalıyor.
- Sade Dil profilinde başlık "Sade Dil Uyum Skoru" (arayüz, CLI, Markdown ve HTML rapor).
- "Yoksayılanları geri al" düğmesi hiç yoksayma yokken de görünüyordu.
- Hata iletileri: "Sunucu çalışıyor mu?" yerine bağlantı iletisi; Vercel'in düz metin 413'ü
  "Dosya ya da metin çok büyük" oluyor. Dokunmatik ekranda "sürükleyip bırakın" yazmıyor.

#### Düzeltildi: sunucu
- Dosya yükleme: sınır 4 MB (Vercel 4,5 MB'ta kesiyor), metin 100.000 karakteri aşamaz, boş ve
  uzantısız dosya reddedilir.
- Bozuk JSON'a "Şu alanları kontrol edin: 1." yerine "gövde geçerli bir JSON değil".
- Bilinmeyen adresler İngilizce `{"detail":"Not Found"}` yerine Türkçe sayfa (API'de Türkçe JSON).
  `/robots.txt` ve `/favicon.ico` var; `/rehber/kd-c01` → `/rehber/KD-C01`.

#### Düzeltildi: skorlar ve kurallar
- Yalnızca noktalama ya da emoji içeren metin 100/100 alıyordu; artık skor "—" ve "Skor
  hesaplanamadı" notu.
- Ateşman 100'ü aşıyordu (146); puan 0–100 aralığına sınırlı.
- KD-B04: geçersiz tarihe öneri olarak sabit "15 Eylül 2026 Salı" verilmiyor.
- KD-B05: "09.00-17.00 saatleri arasında" uyarı almıyor; 'saat' kelimesi sonra da gelebilir.
- Noktasız, satır satır yazılmış metin ("Su kesilecek / Lütfen su biriktirin") tek cümle
  sayılıyordu; her satır ayrı cümle.

### 5. tur: çalışan uygulamada alışılmadık metinler (2026-09-30)

Web arayüzünün API'sine yaklaşık 90 metin ve dosya gönderildi: boş ve tek karakterlik metin,
emoji, Arapça, Rusça ve İngilizce metin, kod, HTML, şiir, Osmanlıca, Anayasa maddesi, yemek
tarifi, masal, SMS dili, geçersiz tarih, IBAN, boşluksuz 100.000 karakter, UTF-16 dosya.
Regresyon testleri: `tests/test_canli_deneme.py`.

#### Düzeltildi: cümle bölme
- Noktası unutulmuş tek satırlık metin başlık sayılıyordu ve cümle kurallarının hiçbiri
  çalışmıyordu: "Müracaatların … yapılması gerekmektedir" noktasız 17, noktalı 1 alıyordu.
  Metnin sonunda altında hiçbir cümle olmayan ve çekimli fiil taşıyan "başlık" artık cümle.
  Altında metin olan fiilli başlıklar ("Suyunuz 1 gün gelmeyecek") ve fiilsiz kapanış satırları
  ("Saygılarımızla") başlık olarak kalıyor.
- Satırın ortasında biten cümle tırnak ya da üç noktayla sürse de ("… dedi. 'Su' biriktirin")
  satır başlık sayılmıyor.
- Küçük harfle yazılmış metin ("yarın su kesilecek. lütfen su biriktirin.") cümlelere bölünüyor;
  tek cümle sayılıp "çok uzun cümle" uyarısı alıyordu. Kısaltma ("vb. belgeler") ve sıra sayısı
  ("3. kata") bölünmüyor.

#### Düzeltildi: KD-B04 tarih
- Geçersiz tarihe ("31.02.2026", "32.13.2026") öneri olarak sabit "15 Eylül 2026 Salı"
  veriliyordu. Artık "gerçek bir tarih değil" hatası; "31 Şubat 2026" da yakalanıyor.
- Tarihe uymayan haftanın günü hata: "1 Aralık 2026 Pazartesi" (Salı olmalı), "01.12.2026
  (Pazartesi)". Haftanın günü önerisi kapalı olsa da denetleniyor.
- "2026/10/01", "2026-10-05" ve "01-10-2026" de tarih olarak tanınıyor.

#### Düzeltildi: performans ve dosya okuma
- Boşluksuz uzun bir dizi (yapıştırılmış base64, uzun adres) sunucuyu kilitliyordu: 100.000
  karakterlik tek "kelime" 59 sn sürüyordu, artık 0,5 sn. E-posta düzenli ifadesi başa bağlı
  değildi (O(n²)); 80 harften uzun kelime biçimbilimsel çözümlemeye girmiyor.
- Not Defteri'nin "Unicode" (UTF-16) kaydettiği .txt dosyası bozuk okunuyordu.

#### Düzeltildi: kelime ve biçim kuralları
- "9dan", "5e" gibi kesmesiz sayı ekleri tek sözcük birimi; "dan" seyrek kelime sayılmıyor.
- IBAN'daki "TR" (ardından rakam gelen harfler) kısaltma sayılmıyor.
- KD-K01: resmî emir ("doldurunuz", "teslim ediniz" → "doldurun", "teslim edin"); "tarafımızca"
  ve "tarafınızca" sözlükte.
- KD-B03: noktayla yazılmış küsurat ("2.5 milyon" → "2,5 milyon").
- KD-C03: "Kim tarafından imzalanacak?" sorusunda ileti "İşi yapan ('Kim')" demiyor.
- KD-K06: "afiyet", "idare", "aynen", "mobil", "hür" temel kelime listesinde.
- KD-K04 ve KD-K06 Latin alfabesi dışındaki kelimeleri hecelemiyor ("المياه" 6 hece değil).

#### Değişti: notlar
- Metin Arap, Kiril gibi bir yazıyla ya da İngilizce yazılmışsa not: "Bu metin Türkçe
  görünmüyor."
- Güvenilirlik notu cümle sayısını söylüyor: "Metinde 1 cümle var. Skor en az 3 cümlede
  güvenilir olur." 55 kelimelik tek cümleye "Metin çok kısa" deniyordu.
- Ateşman açıklaması "0–100 arası" demiyordu; 6. turda puan 0–100 aralığına sınırlandı.

### Görünüm: işaret "dörtlü" (2026-09-28)

- Projenin işareti: 2×2 ızgarada ■ hata, □ uyarı, ○ bilgi ve boş kare (temiz metin). İşaretler
  16×16 piksel ızgarada, `scripts/ikonlar.py` ile üretilir (`ikonlar.svg` içinde `i-dortlu-*`).
- Künye logosu: dörtlü, adla aynı taban çizgisinde. Üzerine gelince döner. Ana sayfa, rehber ve
  stil rehberinde aynı.
- Sekme simgesi `isaret.svg`: renkleri `style.css`'ten gelir, koyu temada "negatif baskı".
- Yükleme göstergesi: dither taraması yerine dönen dörtlü (kayar yapboz, 12 adım, 2,4 sn). Sonuç
  panelinde ve Denetle düğmesinde görünür, çünkü dar ekranda panel metin alanının altında kalır.
  Denetim sürerken sonuç paneli `aria-busy`. Dosya okunurken "Dosya okunuyor…" yazar.
- HTML rapor: künyede dörtlü, gömülü sekme simgesi.
- Stil rehberine "İşaret: dörtlü" bölümü. README'de hareketli işaret görseli ve künyede logo.
- Tanıtım filmi: logoda dörtlü (açılışta ve kapanışta işaretler basılır, bir tur döner), denetim
  sırasında Denetle düğmesinde dönen dörtlü. README'deki GIF ve MP4 yeniden kaydedildi; üretim
  komutları `tanitim/README.md` içinde.

### Belgeler: README (2026-09-27)

- README "Düzeltmen Masası" diliyle yeniden dizildi: künye başlığı (dither güneş ve tepeler),
  canlandırılmış düzeltme provası (uyum skoru 1 → 100), kural sayfası, işlem hattı, renk şeridi ve kapanış künyesi. Her
  görselin açık ve koyu tema baskısı var; "hareketi azalt" tercihinde son hâl gösterilir.
- `scripts/readme_gorselleri.py`: bu SVG'leri `style.css` renkleri, gömülü Atkinson Hyperlegible
  ve projenin dither görselleriyle üretir.
- Ekran görüntüleri künye sahnesiyle yenilendi; tanıtım filminden GIF ve sıkıştırılmış MP4.

### Görünüm: künye sahnesi (2026-09-27)

- Üst şeride risograf baskı sahnesi: dither güneş (kırmızı) ve önünde yavaşça ilerleyen dither
  tepeler (`manzara.js`, canvas; uzak tepeler mavi, yakınlar mürekkep). "Hareketi azalt"
  tercihinde tek kare çizilir.
- Logoda kırmızı kalıp kayması; üzerine gelince mavi kalıba geçer.
- Bulgular panelinin boş durumuna mavi büyüteç görseli.
- Aynı künye rehber ve stil rehberi sayfalarında da kullanılır.

### 4. tur: yirmi farklı kaynaktan gerçek metin (2026-09-27)

Cuma hutbesi, Merkez Bankası faiz kararı, ÖSYM duyurusu, hastane blogu (kan bağışı), Ömer
Seyfettin'in "Kaşağı" öyküsü, iki Vikipedi maddesi (Fotosentez, Mimar Sinan), Tüketicinin
Korunması Hakkında Kanun, yemek tarifi ve okur yorumları, AA spor haberi, İETT duyuruları, İŞKUR
tanıtımı, e-ticaret iade koşulları, banka bilgilendirmesi, NVİ çerez politikası, DergiPark makale
özetleri, ilaç kullanma talimatı (PDF), çamaşır makinesi kılavuzu (PDF) ve Aile Bakanlığının kolay
okunur sözleşme metni denendi. Regresyon testleri: `tests/test_yirmi_kaynak.py`.

#### Düzeltildi: cümle bölme
- `normalize()` bütün tırnakları `"`, bütün tireleri `-` yapar; bölücü artık ikisini de tanıyor.
- Cümlenin içine gömülü alıntıdaki ünlem cümleyi bitirmiyor (“Ey insanlar! … koruyun”[2] sözü
  gereğince …). Konuşma çizgisi yeni bir konuşma açıyor ("… döverim! — Söylemem. — Peki …").
- Vikipedi kaynak işaretinden ("kullanılır.[1] Daha sonra …") ve dipnot yıldızından ("*Cayma
  hakkı …") sonra yeni cümle başlıyor. "II. Selim ve III. Murad" bölünmüyor.
- Numaralı ara başlıklar ("1. Bu Sözleşme" ardından düz metin) madde değil başlık; KD-M02 artık
  "başlık yok" demiyor. Arka arkaya numaralı satırlar liste olarak kalıyor.
- İçinde cümle biten noktalamasız satır ("Tam istediğim gibi oldu. Tşk ederim") başlık sayılmıyor.
- PDF'te simge yazı tipiyle basılmış madde işaretleri ("u Ürünün içinde …") "•" oluyor.

#### Düzeltildi: biçimbilim ve sözlük
- "yendi" (yenmek) "yemek"in edilgeni sanılıyordu; KD-C03 "'yedi' biçimini kullanın" diyordu.
  "bayılma", "eğilirdim", "boğulmak" ve "-il-er" çoğulları ("siyanobakteriler") edilgen değil.
- Çok kelimeli girdilerde ad durumu korunuyor: "haklara sahip" artık "hak sahibi" (→ "yardım
  alacak kişi") sayılmıyor; "önüne almak" "önünü almak" (engellemek), "eli altında" "el altından"
  (gizlice) değil. Tamlamanın baş adı ("hak sahiplerinin") her durumu alabilir.
- Sıfat-fiil girdisi ("çalışan") fiilin başka biçimleriyle ("çalışılır") eşleşmiyor.
- KD-K08: "ücret/bedel/fiyat/tutar" ve "yönetmelik/mevzuat" grupları kaldırıldı ya da daraltıldı;
  aynı metinde ayrı şeyleri anlatıyorlar ("iade edilecek bedelden kargo ücreti düşülür").
- abbreviations.yaml: tırnaksız virgül ÖSYM, EGO ve ESHOT açılımlarını bölüyordu ("Ölçme (ÖSYM)").
  Sözlük dosyalarında bilinmeyen alan kalmadığını bir test denetliyor. "s.a.s.", "s.a.v.", "a.s.",
  "r.a." eklendi; "(s.a.s)" tek kelime, "sayfa (s)" önerisi yok.
- Arap harfleriyle yazılmış kelimeler kısaltma sayılmıyor. "Peygamber Efendimiz (s.a.s)" bir
  açılım değil: parantezden önceki kelimelerden biri kısaltmanın ilk harfiyle başlamalı.
- Çok kelimeli özel adın içindeki sözlük kelimesi işaretlenmiyor ("Amed Sportif Faaliyetler").
- KD-K01: yönerge biçimli önerilerde ("tarafından") ileti "Yerine '(…)' yazın" demiyor.
- KD-K07: "beş iş günü içinde" belirsiz değil.

#### Düzeltildi: cümle kuralları
- Bölme önerisi: noktalı virgülden önce yüklem yoksa ("ortalama;", "itibaren;", "yoksa;")
  "nokta koyun" denmiyor; zarf-fiilden sonra ("edildiğinde,", "çizerek,") "bölün" deniyor;
  "ki" önünden bölünmüyor ("De ki:", "Unutmayalım ki"); "için," gibi edatlar yüklem değil.
- KD-C02: aktarılan söz ("…, dedi.", "…! diye haykırdı", "…, derdim.") ve yineleme ("Yok, yok!")
  ayrı bilgi değil. "ve" ile bağlanan sıfat-fiiller ("cevaplamış ve uygun bulunmuş kişiler",
  "bulunmuş ve … oluşmuş ise") yüklem sayılmıyor. Cümlenin ilk kelimesinde ad okuması tercih
  ediliyor ("Astım ve akciğerde …", "Ürünün, …").
- KD-C03: "X tarafından" varsa ileti "kimin yaptığı belli değil" demiyor, yapanı adıyla anıyor.
  Bu yalnızca "tarafından"dan hemen sonraki fiil için geçerli.
- KD-C06/C07/C10: "birey olarak", "olabildiğince", "dâhil olmak üzere" ve amaç bildiren "…mak
  için" yan cümle ya da isimleştirme sayılmıyor.
- KD-C05: aynı ekle sıralanmış iki olumsuz eylem ("ameliyat olmamış, dövme yaptırmamış") çifte
  olumsuzluk değil. KD-C04: alıntılanan söz yazarın olumsuzluğu sayılmıyor.
- KD-B03: "yüzde 35,5" 355 sanılıp "Önce 100 lira olan fiyat …" öneriliyordu.
- KD-M02: soru biçimli ara başlıklar (SSS) başlık sayılıyor.

#### Etki
Kaşağı öyküsü 50'den 56'ya, spor haberi 28'den 34'e çıktı; bürokratik metinler (TCMB, İŞKUR,
kanun, çerez politikası) 0–6 arasında kaldı. Kolay okunur sözleşme metni 36: puanı uzun cümleleri
(50 cümlenin 19'u 10 kelimeden uzun) ve uzun kelimeleri düşürüyor; yanlış bulgular ayıklandı.

### 3. tur: dört bağımsız deneme raporu (2026-09-26)

Dört ayrı denemede (belediye duyuruları, meteoroloji uyarısı, grip rehberi, KVKK ve tüketici
metinleri, haber, blog, çocuk masalı, Güneş Sistemi maddesi) bulunan hatalar düzeltildi.
Regresyon testleri: `tests/test_ajan_geri_bildirimi.py`.

#### Düzeltildi: altyapı
- Web arayüzü: 500 karakterden uzun bir cümlede "Yoksay" düğmesine basınca sonraki bütün
  denetimler 422 hatası veriyordu. Yoksayılan metin artık denetlenen metin kadar uzun olabilir;
  toplam sınır aşılırsa anlaşılır bir ileti çıkar. Aynı bulgu iki kez yoksay listesine eklenmiyor.
- Satır başındaki sıra sayısı ("15. yüzyılda …", "1. maddeye göre …", "3. Madde …") madde işareti
  sanılıp kırpılıyordu; kelime ve hece sayısı eksik çıkıyor, KD-C10 çalışmıyordu. Numaralı
  listeler (en az iki numaralı satır) eskisi gibi madde sayılıyor.
- Uyum skoru formülündeki "−" (U+2212) ve "Σ" karakterleri Türkçe Windows konsolunda (cp1254)
  `UnicodeEncodeError` veriyordu. `print(report)` artık kısa ve cp1254 uyumlu bir özet yazar.
- Windows'ta klasör verildiğinde "izin yok" yerine "Bu bir klasör, dosya değil" deniyor.
- Boş metin kütüphanede ve web arayüzünde de hata (`EmptyInput`, HTTP 422); önce 100 puan
  alıyordu. Komut satırı aynı iletiyi kullanıyor.
- Profil `extends: taban.yaml` dosyasını önce profilin kendi klasöründe arıyor.
- Çok kelimeli sözlük girdileri araya noktalama ya da sayı giren kelimelerle eşleşmiyor
  ("söz - konusu").
- `scripts/ikonlar.py --help` proje kökünde "--help" adlı klasör açıyordu. Betik artık argparse
  kullanıyor; `--kontrol` üretilmiş dosyaların güncel olup olmadığına bakar.
- Performans testi kararsızdı (3,5 sn). Test aslında ~3.100 kelime ölçüyordu; artık gerçekten
  5.000 farklı kelime ölçüyor, çöp toplayıcıyı durduruyor ve iki soğuk ölçümün iyisini alıyor.
  `KOLAYMETIN_PERF_SINIR` ile yavaş makinede sınır genişletilebilir.
- pytest'teki Starlette/httpx uyarısı süzülmüyordu (uyarı sınıfı `UserWarning`).
- `tanitim/kaydet.py` ruff RUF046.

#### Düzeltildi: yanlış pozitifler ve öneriler
- KD-C04: "Yılmaz", "Korkmaz", "Sönmez" gibi soyadları olumsuz fiil sayılıyordu. Cümle ortasında
  büyük harfle başlayan kelime ve bilinen adlar (`names.txt`) artık özel ad; fiil çözümlemesi
  alınmıyor. Aynı düzeltme "Birleşmiş Milletler" (KD-C06) ve "Korkmaz" (KD-C02) hatalarını da
  giderdi. KD-C04 cümle başına tek bulgu verir ve önerisini olumsuzluğun türüne göre seçer
  (yasak, "değil", "yok", "hiç", "-emez", soru).
- KD-C02: "boşa" (boşamak, emir) yüklem sayılıyordu ve "'boşa' kelimesinden sonra nokta koyun"
  gibi bozuk öneri çıkıyordu. Sıfattan türeyen adlar ("boşa", "iyiye") artık cezalı değil;
  cümle ortasındaki bir fiil ancak ardından virgül, bağlaç ya da cümle sonu gelirse yüklem sayılır.
- KD-C03: "korunun", "korunmak için" gibi okura seslenen dönüşlü fiiller işaretlenmiyor. Etken
  biçim önerisi yalnızca yüklemde veriliyor ("ambalajı açmış ürün", "öngörenden" gibi bozuk
  öneriler yok). "yeniliyor" (yenilemek) "yenmek" fiilinin edilgeni sanılıyordu. "yayılmak",
  "tıkanmak" edilgen sayılmıyor. KD-K01 kalıbının içindeki edilgen ("rica olunur") ayrıca
  sayılmıyor.
- KD-C10: Türkçenin olağan özne-nesne-yüklem dizilişi cezalandırılıyordu ("… tatlı bir kız
  yaşarmış"). Kural artık yalnızca yüklemden önce bir yan cümle varsa uyarır; devrik cümleye
  yönelten öneri kaldırıldı.
- KD-C01: Kolay Dil eşiği 8/12 kelimeden 10/15 kelimeye çıktı (bkz. KARARLAR).
- KD-K04: hece sayısı çekim ekleri atılmış gövdede ölçülüyor ("ellerinizi", "tüketiciye",
  "edebilirsiniz" uyarı almaz; "vatandaşlarımıza", "değerlendirilmesinden" alır). Uzun kökler
  bilinse de işaretlenir ("meteoroloji"). Her kelimede aynı sabit örnek yerine kelimeyi neyin
  uzattığına göre öneri çıkar. KD-K01/KD-K02 ifadesinin içindeki kelime ayrıca işaretlenmez.
- KD-K06: temel kelime listesi 3.089'dan 5.400'ü aşkın köke çıktı. Anlamı kökten çıkan türetmeler
  ("süreli", "kuvvetli", "sağlıklı") bilinir sayılıyor. Cümle başındaki adlar ("Ali", "Pıtır"),
  metinde kesme işaretiyle geçen adlar ve "New York" gibi ad parçaları işaretlenmiyor.
- KD-K05: gerçek anlamıyla da sık kullanılan 30 deyim `iki_anlamli` işaretlendi (yalnızca bilgi,
  "mecaz anlamda kullandıysanız"); `gercek` ipuçları ("Otobüs yola çıktı", "Kapıyı açın",
  "Kırmızı düğmeye basın") varsa uyarı yok. Öneri artık mastarı değil, düz anlamı veriyor.
- KD-K07: önünde sayı olan süre ("14 gün içinde", "3 iş günü içinde") belirsiz sayılmıyor.
- KD-B03: "100 kişiden X'i" önerisi yalnızca kişiler için; para için "100 lirada X lira", başka
  şeyler için kesir ("onda yedisi") öneriliyor.
- KD-B04: tarih aralıklarında ("6 Şubat - 2 Mart 2026", "15-20 Eylül") haftanın günü istenmiyor.
- KD-M02: metnin ilk satırındaki iki noktalı başlık ("Su kesintisi: 15 Eylül", "DUYURU: Su
  Kesintisi") başlık sayılıyor; kuralın kendi önerisi artık kendisiyle çelişmiyor.
- Hitap satırı ("Değerli Sakinlerimiz,") ardından gelen cümleye eklenmiyor.

#### Performans
- zeyrek arama döngüsü her yolda durumun bütün geçişlerini deniyordu. Geçişler artık (durum, ses
  özellikleri, kalan metnin ilk harfi) için önbelleğe alınıyor; sonuçlar ve sıraları birebir aynı
  (21.911 kelimede karşılaştırıldı), çözümleme ~%26 hızlı. 5.000 farklı kelime ~2,3 sn.
- Sözlük eşleşmeleri belge başına bir kez hesaplanıyor (KD-K06 dört sözlüğü yeniden eşliyordu).

#### Etki
Çocuk masalı Kolay Dil uyum skoru 16–33'ten 90'a, grip rehberi 18'den 87'ye, sadeleştirilmiş
su kesintisi duyurusu 28'den 80'e çıktı. Bürokratik duyurular 0–4 arasında kalıyor.

Gerçek kamu duyurularıyla (valilik meteoroloji uyarıları, belediye su kesintisi, SGK, AFAD,
Sağlık Bakanlığı) yapılan denemede bulunan hatalar düzeltildi. Regresyon testleri:
`tests/test_gercek_metinler.py`.

### Düzeltildi
- Edilgenden etken biçim önerisi: "bekleniyor" → "bekliyor" (önce "bekleyiyor"),
  "edildiği" → "ettiği" (önce "etdiği"), "yapıldı" → "yaptı".
- Büyük harfle vurgulanan kelimeler ("BUZLANMA VE DON UYARISI", "ÇÖK, KAPAN, TUTUN", "ACİL")
  artık kısaltma sayılmıyor. Küçük harfli "kit", "ego" gibi kelimeler de kısaltma sayılmıyor.
  ABD, ÇİMER, SUT, KİT, SİT kısaltma sözlüğüne eklendi.
- KD-C07: addan türeyen "-lık"lı kelimeler ("müdürlük", "sağlık", "güvenlik") ve "yağışlı" gibi
  sıfatlar artık isimleşmiş eylem sayılmıyor.
- "alan", "sandık", "çakmak", "düğme" gibi yalın adlara rastlantısal fiil çözümlemesinden
  sıfat-fiil / ad-fiil işareti eklenmiyor (KD-C06, KD-C07 yanlış pozitifleri).
- "dokunmak", "kaynaklanmak", "buzlanmak", "yaralanmak", "parçalanmak", "dökülmek",
  "yaşanmak" edilgen sayılmıyor; "toplanmak" dönüşlü fiillere eklendi.
- Virgülden önceki "göre" edatı, "yer yer" ikilemesi ve "Yaşlılar, bebekler …" gibi sıralama
  öğeleri artık yüklem sayılmıyor (KD-C02 ve bölme önerisi).
- KD-C01 bölme önerisi yalnızca bir yan cümlenin bittiği yeri gösteriyor ve özel adları küçük
  harfe çevirmiyor ("'belediyesi' kelimesinden sonra" yerine anlamlı bir yer).
- Web sayfasından ya da Word'den yapıştırılan, paragrafları tek satır sonuyla ayrılmış metin
  tek dev paragraf sayılmıyor (KD-M01 "46 cümle" yanlış pozitifi). Satırlar arasındaki ara
  başlıklar ("Bina içindeyseniz") sonraki cümleyle birleşmiyor. "-Güneş …" gibi boşluksuz tire
  madde işareti sayılıyor.
- KD-C11 "Kamuoyunun bilgisine sunulur" kalıbını yakalıyor.
- KD-K01 "suretiyle" için "kopya" yerine "yoluyla" öneriyor; eşit uzunluktaki sözlük
  eşleşmelerinde seçim artık her çalıştırmada aynı.

### Düzeltildi (2. tur: kolaydil.tr Kolay Dil metinleri, KVKK aydınlatma metinleri, MEB duyurusu, Vikipedi)
- Sezgisel çözümleyici: "-mAlI" gereklilik eki ("olmalıyım") artık olumsuzluk sayılmıyor.
  Edilgen kalıbı kelimenin sonunu da denetliyor; "Valdivia", "kontinü", "travertensert" gibi
  özel ad, yabancı ya da bozuk kelimeler edilgen sayılmıyor.
- Cümle sonundaki olumsuz emir ("Zarfını kapatmayı unutma.") isimleşme sayılmıyor.
  "gerek…/lazım/şart" önündeki ad-fiil ("korumam gerekiyor") olumsuz fiil sayılmıyor
  (KD-C04 ve KD-C05 yanlış pozitifleri).
- KD-C07 yalnızca yan cümle taşıyan ad-fiilleri sayıyor ("teslim edilmesi", "bilmesini").
  "Aydınlatma Metni", "temizleme işlemi", "düzenlemeler", "X ne demek?" artık sayılmıyor.
  "alınmaya başlanacaktır" kalıbı eklendi.
- KD-C02, KD-C10 ve bölme önerisi: "diye"den önceki, aktarılan sözdeki ("'UZAK DUR' derim")
  ve parantez içindeki yüklemler ayrı bilgi sayılmıyor. "Kimse görmesin diye …" için artık
  "'görmesin' kelimesinden sonra nokta koyun" gibi bozuk öneri çıkmıyor.
- KD-C03: "yüklenici" gibi "-ıcı" ile türemiş adlar edilgen sayılmıyor.
- Sözlük eşleşmesi: çekimli yazılmış tek kelimelik girdiler yalnızca kendi biçimiyle eşleşiyor.
  "Yükleme" → "işi yapan firma", "Kanun hükümleri" → "yerine geçer", "log" → "giriş yapmak"
  gibi yanlış öneriler giderildi.
- KD-K06: "-ki" ve küçültme ekli kelimeler köküyle aranıyor ("resimdeki", "aşağıdaki",
  "kutucuk"); emir kipleri ("Bul.", "Bas.") ve zeyrek'in tanımadığı çekimli fiiller
  ("olmalıyım") tanınıyor. Temel kelime listesine "şöyle, yine, diye, yani, metin, taraf,
  şekil …" gibi sık kelimeler eklendi.
- KD-K03: büyük harfle yazılmış özel adlar ("Keçiören/ANKARA") kısaltma sayılmıyor; açılımı
  hemen sonraki cümlede verilen kısaltma ("TBMM: Türkiye Büyük Millet Meclisi demek.")
  açıklanmış sayılıyor; "Bay" uyarı vermiyor.
- KD-K02: Kolay Dil okurunun bilmediği öztürkçe öneriler ("ölçün", "başarım", "gizil", "sığa",
  "eşgüdüm") yerine günlük kelimeler öneriliyor.
- KD-B01: rakamdan sonraki "milyon/milyar" ("100 milyon") işaretlenmiyor.
- KD-B02: ad baş harfleri ("Robert M.", "D. F.") ve "CD" gibi kısaltmalar Roma rakamı sayılmıyor.
- KD-B04: geçmiş yıllara ait tarihlere ("23 Nisan 1920") ve özel adın parçası olan tarihlere
  ("1 Kasım İlkokulu") haftanın günü önerilmiyor.
- KD-B08: doğrudan söz tırnakları ("“evet” veya “hayır” der", "“evet” dediğinde") işaretlenmiyor.
- KD-M03: "Örneğin," gibi giriş sözleri liste öğesi sayılmıyor.
- KD-M04: "Kaynak: …", "Metin: …" künye satırlarındaki adres ve tarihler önemli bilgi sayılmıyor.

## [1.0.0] - 2026-09-25

İlk sürüm. Aşağıdaki notlar geliştirme aşamalarını sırasıyla özetler.

### 1. İskelet
- `pyproject.toml` (hatchling), `src/kolaymetin` paket yapısı, ruff/mypy/pytest ayarları.
- pydantic modelleri: `Analysis`, `Token`, `Sentence`, `Paragraph`, `Finding`, `Scores`, `Report`.

### 2. Metin işleme
- Unicode NFC normalleştirme; tırnak, tire, boşluk birleştirme; karakter düzeyinde orijinal ofset eşlemesi.
- Türkçe büyük/küçük harf yardımcıları (`turkish_lower`, `turkish_upper`, `turkish_capitalize`).
- Kısaltma, sıra sayısı, tarih, saat, URL ve e-posta farkındalıklı cümle bölme; liste maddeleri, başlıklar, satır içi susturma.
- Sözcük birimlerine ayırma (kelime, sayı, tarih, saat, yüzde, URL, e-posta).
- Hece sayımı: sayılar okunuşa (`num2words`), kısaltmalar sözlük okunuşuna ya da harf harf.

### 3. Morfoloji
- zeyrek entegrasyonu (NLTK verisi gerekmeden), 3 kat hızlı arama döngüsü, yüzey biçim önbelleği.
- zeyrek'teki durum bozulması hatasının düzeltilmesi.
- Bağlama dayalı en olası çözümleme ve işaret başına güven; ek tabanlı sezgisel geri dönüş.

### 4. Okunabilirlik formülleri
- Ateşman (1997), Çetinkaya-Uzun (2010), Bezirci-Yılmaz (2010); katsayılar kaynaklardan doğrulandı.

### 5. Sözlükler
- Jargon (235), yabancı kelime (131), deyim (96), kısaltma (134), eş anlamlı grup (41),
  belirsiz ifade, dolaylı hitap deseni, dönüşlü fiil listesi, 3.000+ temel kelime.

### 6. Kurallar
- 32 kuralın tamamı: KD-C01…C11, KD-K01…K08, KD-B01…B08, KD-M01…M05.
- `kolay-dil` ve `sade-dil` profilleri; `extends` ile özel profil; `--sozluk` ile ek sözlük.

### 7. Uyum skoru ve rapor
- Kolay Dil Uyum Skoru (kategori bazında, katkı tablosuyla).
- JSON, Markdown ve bağımsız, yazdırılabilir HTML rapor.

### 8. Komut satırı
- `kolaymetin denetle | sunucu | kurallar | surum`; Türkçe yardım; renkli metin çıktısı; çıkış kodları 0/1/2.

### 9. Görsel sistem
- "Düzeltmen Masası" renk belirteçleri (açık/koyu), WCAG kontrast denetimi betiği.
- Atkinson Hyperlegible Next ve Mono yazı tipleri (yerel), 19 piksel ikon, Atkinson/Bayer dither betiği,
  dither görseller ve 17 seviyeli Bayer desenleri, stil denetim testleri, stil rehberi sayfası.

### 10. Web
- FastAPI sunucu ve çerçevesiz ön yüz: düzeltmen işaretleri, kenar boşluğu notları, bulgu kartları,
  dither skor çubukları, cümle görünümü, dosya yükleme, dışa aktarma, yoksayma, tema ve yazı boyutu.

### 11. Rehber
- Giriş, 32 kural sayfası, skorlar, kaynaklar, katkı; `/rehber` altında aynı görsel dille sunum.
- Rehberin kendi metnini denetleyen test.

### 12. Doğrulama
- 18 metinlik korpus (6 konu × bürokratik/sade/kolay) ve beklenen bulgular.
- Performans (5.000 kelime < 3 sn), ağ yalıtımı, yanlış pozitif ve erişilebilirlik gözden geçirmesi.
- Ekran görüntüleri ve öz değerlendirme.

### 13. Dağıtım
- `Dockerfile`, `docker-compose.yml`, README, CONTRIBUTING, KARARLAR, MİMARİ.
