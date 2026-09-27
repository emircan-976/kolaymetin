"""Her kural için en az 3 pozitif ve 3 negatif örnek."""

from __future__ import annotations

import pytest

from conftest import rule_hits
from kolaymetin import analyze
from kolaymetin.rules import all_rules, get_rule
from kolaymetin.rules.format import format_thousands, parse_number_words, possessive, roman_to_int
from kolaymetin.rules.sentence import active_form

# (kural, metin, profil)
POSITIVE: list[tuple[str, str, str]] = [
    # --- KD-C01 uzun cümle
    ("KD-C01", "Belediyemiz mahallemizdeki bütün sokaklarda yarın sabahtan akşama kadar temizlik çalışması yapacak.", "kolay-dil"),
    ("KD-C01", "Aşı olmak isteyen yaşlı vatandaşlar kimlik kartlarıyla birlikte sağlık ocağına gelsin.", "kolay-dil"),
    ("KD-C01", "Seçim günü oy kullanacak bütün seçmenlerin yanlarında fotoğraflı resmî bir kimlik belgesi bulundurmaları ve sandık kuruluna göstermeleri ile birlikte oy pusulalarını gizlice kullanmaları zorunludur.", "sade-dil"),
    # --- KD-C02 birden fazla bilgi
    ("KD-C02", "Su kesilecek ve belediye boruyu onaracak.", "kolay-dil"),
    ("KD-C02", "Kimliğinizi getirin, çünkü görevli kimliğe bakacak.", "kolay-dil"),
    ("KD-C02", "Başvurular başladı, belgeler geldi, görevliler sizi bekliyor.", "sade-dil"),
    # --- KD-C03 edilgen yapı
    ("KD-C03", "Başvurular alınacaktır.", "kolay-dil"),
    ("KD-C03", "Su yarın kesilecek.", "kolay-dil"),
    ("KD-C03", "Belgelerin teslim edilmesi gerekir.", "kolay-dil"),
    ("KD-C03", "Toplanma alanları ilan edildi.", "sade-dil"),
    # --- KD-C04 olumsuz anlatım
    ("KD-C04", "Suyu boşa harcamayın.", "kolay-dil"),
    ("KD-C04", "Bu hizmet ücretli değil.", "kolay-dil"),
    ("KD-C04", "Evde su yok.", "kolay-dil"),
    ("KD-C04", "Kimse gelmeyecek.", "sade-dil"),
    # --- KD-C05 çifte olumsuzluk
    ("KD-C05", "Başvurmamak mümkün değildir.", "kolay-dil"),
    ("KD-C05", "Oy kullanmayan seçmen olmayacak.", "kolay-dil"),
    ("KD-C05", "Bu durum imkânsız değildir.", "kolay-dil"),
    ("KD-C05", "Katılmamak mümkün değildir.", "sade-dil"),
    # --- KD-C06 zarf-fiil / sıfat-fiil yığını
    ("KD-C06", "Belgelerini alarak gelen kişiler sıra bekleyecek.", "kolay-dil"),
    ("KD-C06", "Eve gelince yemeği yiyip uyudu.", "kolay-dil"),
    ("KD-C06", "Kapıyı açmadan önce gelen kişiyi sorarak kontrol edin.", "sade-dil"),
    # --- KD-C07 ad yığını
    ("KD-C07", "Belgelerin teslim edilmesi gerekmektedir.", "kolay-dil"),
    ("KD-C07", "Sel riskinin azaltılmasına yönelik çalışmalar sürüyor.", "kolay-dil"),
    ("KD-C07", "Okumanın ve yazmanın öğrenilmesi önemlidir.", "kolay-dil"),
    # --- KD-C08 tamlama zinciri
    ("KD-C08", "Belediyemizin müdürlüğünün ekibinin çalışması bitti.", "kolay-dil"),
    ("KD-C08", "Vatandaşlarımızın başvurularının sonucunun açıklanması yarın.", "kolay-dil"),
    ("KD-C08", "Kentin merkezinin parkının ağaçlarının bakımı yapıldı.", "sade-dil"),
    # --- KD-C09 parantez
    ("KD-C09", "Belgeleri (kimlik ve adres belgesi) getirin.", "kolay-dil"),
    ("KD-C09", "Aşı ücretsiz (65 yaş üstü için).", "kolay-dil"),
    ("KD-C09", "Başvuru (internetten de olur) yarın başlıyor.", "sade-dil"),
    # --- KD-C10 yüklem geç
    ("KD-C10", "Belediyemiz bu kış ihtiyacı olan ailelere yakacak ve yiyecek yardımı da yapacak.", "kolay-dil"),
    ("KD-C10", "Seçim günü sandık başında telefon ve fotoğraf makinesi gibi aletleri kullanmak yasaktır.", "kolay-dil"),
    ("KD-C10", "Görevlilerimiz yarın sabah çok erken saatlerde mahallenin bütün sokaklarındaki çöpleri tek tek toplayıp götürecek.", "sade-dil"),
    # --- KD-C11 dolaylı hitap
    ("KD-C11", "Vatandaşlarımızın su biriktirmeleri önemle rica olunur.", "kolay-dil"),
    ("KD-C11", "İlgililere duyurulur.", "kolay-dil"),
    ("KD-C11", "Kamuoyuna saygıyla duyurulur.", "sade-dil"),
    # --- KD-K01 jargon
    ("KD-K01", "Müracaatınızı yapın.", "kolay-dil"),
    ("KD-K01", "Belgeleri ivedilikle getirin.", "kolay-dil"),
    ("KD-K01", "Dilekçenizi arz ederiz.", "kolay-dil"),
    ("KD-K01", "Mezkûr tarihte gelin.", "sade-dil"),
    # --- KD-K02 yabancı kelime
    ("KD-K02", "Başvurular online yapılır.", "kolay-dil"),
    ("KD-K02", "Prosedür değişti.", "kolay-dil"),
    ("KD-K02", "Plan revize edildi.", "sade-dil"),
    # --- KD-K03 kısaltma
    ("KD-K03", "Başvurunuzu SGK'ya yapın.", "kolay-dil"),
    ("KD-K03", "AFAD ekipleri geldi.", "kolay-dil"),
    ("KD-K03", "Sonuçları ÖSYM açıklayacak.", "sade-dil"),
    # --- KD-K04 uzun kelime
    ("KD-K04", "Başvurularınızın sonucunu yazacağız.", "kolay-dil"),
    ("KD-K04", "Değerlendirilmesinden sonra ararız.", "kolay-dil"),
    ("KD-K04", "Yararlanabileceğiniz hizmetler şunlar.", "sade-dil"),
    # --- KD-K05 deyim
    ("KD-K05", "Belediye soruna el attı.", "kolay-dil"),
    ("KD-K05", "Bu hatalara göz yummayın.", "kolay-dil"),
    ("KD-K05", "Sorunu masaya yatırdık.", "sade-dil"),
    # --- KD-K06 seyrek kelime
    ("KD-K06", "Şebekedeki bulanıklık geçecek.", "kolay-dil"),
    ("KD-K06", "Mütevazı bir tören yapacağız.", "kolay-dil"),
    ("KD-K06", "Fırtınanın tahribatı büyük.", "kolay-dil"),
    # --- KD-K07 belirsiz ifade
    ("KD-K07", "Su en kısa sürede gelecek.", "kolay-dil"),
    ("KD-K07", "Yakında başvuru başlayacak.", "kolay-dil"),
    ("KD-K07", "Gerekli belgeleri getirin.", "sade-dil"),
    # --- KD-K08 terim tutarsızlığı
    ("KD-K08", "Başvuru yarın başlıyor. Müracaatınızı yapın.", "kolay-dil"),
    ("KD-K08", "Başvuru formunu doldurun. Müracaatınızı vezneye verin.", "kolay-dil"),
    ("KD-K08", "Doktor sizi görecek. Hekim ilaç yazacak.", "sade-dil"),
    # --- KD-B01 yazıyla sayı
    ("KD-B01", "Yardım on beş bin lira.", "kolay-dil"),
    ("KD-B01", "Yirmi beş kişi geldi.", "kolay-dil"),
    ("KD-B01", "İki bin kişi başvurdu.", "sade-dil"),
    # --- KD-B02 Roma rakamı
    ("KD-B02", "XIX. yüzyılda yapıldı.", "kolay-dil"),
    ("KD-B02", "Seçim XV. bölgede.", "kolay-dil"),
    ("KD-B02", "III. Bölge Müdürlüğü açık.", "sade-dil"),
    # --- KD-B03 yüzde ve kesir
    ("KD-B03", "Ailelerin %35'i yardım alıyor.", "kolay-dil"),
    ("KD-B03", "Seçmenlerin yüzde 50 kadarı geldi.", "kolay-dil"),
    ("KD-B03", "Pastanın 3/4 parçası kaldı.", "kolay-dil"),
    # --- KD-B04 tarih biçimi
    ("KD-B04", "Kesinti 15.09.2026 günü.", "kolay-dil"),
    ("KD-B04", "Başvuru 01/12/2026 tarihinde başlar.", "sade-dil"),
    ("KD-B04", "Aşı 1 Ekim 2026 günü başlıyor.", "kolay-dil"),
    # --- KD-B05 saat biçimi
    ("KD-B05", "Toplantı 14.30'da başlayacak.", "kolay-dil"),
    ("KD-B05", "Kesinti 09.00-17.00 arasında olacak.", "kolay-dil"),
    ("KD-B05", "Otobüs 7:45'te kalkar.", "sade-dil"),
    # --- KD-B06 noktalı virgül / iki nokta
    ("KD-B06", "Belgelerinizi getirin; yoksa başvuramazsınız.", "kolay-dil"),
    ("KD-B06", "Adres: Atatürk Caddesi. Saat: 9 ile 17 arası: her gün.", "kolay-dil"),
    ("KD-B06", "Su kesilecek; elektrik de kesilecek.", "sade-dil"),
    # --- KD-B07 büyük harf
    ("KD-B07", "SU KESİNTİSİ HAKKINDA ÖNEMLİ DUYURU", "kolay-dil"),
    ("KD-B07", "LÜTFEN BELGELERİNİZİ YANINIZDA GETİRİNİZ.", "kolay-dil"),
    ("KD-B07", "Dikkat: BU ALANA ARAÇ PARK ETMEK YASAKTIR.", "sade-dil"),
    # --- KD-B08 tırnak içinde vurgu
    ("KD-B08", 'Yardım "ücretsiz" dağıtılacak.', "kolay-dil"),
    ("KD-B08", 'Lütfen "zamanında" gelin.', "kolay-dil"),
    ("KD-B08", 'Bu "çözüm" işe yaramadı.', "kolay-dil"),
    # --- KD-M01 uzun paragraf
    ("KD-M01", "Su kesilecek. Kesinti sabah başlar. Akşam biter. Su biriktirin. Musluğu kapatın. Sonra bizi arayın.", "kolay-dil"),
    ("KD-M01", "Aşı var. Aşı ücretsiz. Randevu alın. Kimlik getirin. Erken gelin. Sırayı bekleyin. Aşı olun.", "kolay-dil"),
    ("KD-M01", "Bir. İki. Üç. Dört. Beş. Altı. Yedi. Sekiz. Dokuz.", "sade-dil"),
    # --- KD-M03 liste fırsatı
    ("KD-M03", "Kimlik kartı, adres belgesi, gelir belgesi ve fotoğraf getirin.", "kolay-dil"),
    ("KD-M03", "Elektriği, gazı, suyu ve kapıları kapatın.", "kolay-dil"),
    ("KD-M03", "Pazartesi, salı, çarşamba, perşembe açığız.", "sade-dil"),
]

NEGATIVE: list[tuple[str, str, str]] = [
    ("KD-C01", "Su yarın kesilecek.", "kolay-dil"),
    ("KD-C01", "Belediye su borusunu onaracak.", "kolay-dil"),
    ("KD-C01", "SU KESİNTİSİ HAKKINDA ÇOK ÖNEMLİ VE ACİL OLAN BİR DUYURU METNİ BURADA", "kolay-dil"),
    ("KD-C01", "Aşı olmak isteyen yaşlı vatandaşlar kimlik kartlarıyla gelsin.", "sade-dil"),
    ("KD-C02", "Belediye boruyu onaracak.", "kolay-dil"),
    ("KD-C02", "Su ve elektrik yarın kesilecek.", "kolay-dil"),
    ("KD-C02", "Kimliğinizi getirin.", "kolay-dil"),
    ("KD-C02", "Su kesilecek ve belediye boruyu onaracak.", "sade-dil"),
    ("KD-C03", "Belediye başvuruları alacak.", "kolay-dil"),
    ("KD-C03", "Su borusu bozuldu.", "kolay-dil"),
    ("KD-C03", "Ali taşındı.", "kolay-dil"),
    ("KD-C03", "Okunabilirlik önemlidir.", "kolay-dil"),
    ("KD-C04", "Suyu az kullanın.", "kolay-dil"),
    ("KD-C04", "Bu hizmet ücretsiz.", "kolay-dil"),
    ("KD-C04", "Suyunuz var.", "kolay-dil"),
    ("KD-C05", "Başvurmanız gerekir.", "kolay-dil"),
    ("KD-C05", "Hiç kimse gelmedi.", "kolay-dil"),
    ("KD-C05", "Katılmanız mümkün.", "kolay-dil"),
    ("KD-C06", "Belgelerinizi alın.", "kolay-dil"),
    ("KD-C06", "Eve gelince uyudu.", "kolay-dil"),
    ("KD-C06", "Belgeleri alarak gelen kişiler bekleyecek.", "sade-dil"),
    ("KD-C07", "Belgelerinizi teslim edin.", "kolay-dil"),
    ("KD-C07", "Başvuru yarın başlıyor.", "kolay-dil"),
    ("KD-C07", "Okumayı seviyorum.", "kolay-dil"),
    ("KD-C08", "Belediyenin ekibi çalışıyor.", "kolay-dil"),
    ("KD-C08", "Ekibimiz çalışıyor.", "kolay-dil"),
    ("KD-C08", "Belediyemizin müdürlüğünün ekibinin çalışması bitti.", "sade-dil"),
    ("KD-C09", "Sosyal Güvenlik Kurumu (SGK) açık.", "kolay-dil"),
    ("KD-C09", "Bizi arayın: (0232) 555 12 34", "kolay-dil"),
    ("KD-C09", "Belgelerinizi getirin.", "kolay-dil"),
    ("KD-C10", "Belediye yardım yapacak.", "kolay-dil"),
    ("KD-C10", "Seçim günü telefon kullanmak yasak.", "kolay-dil"),
    ("KD-C10", "Belediyemiz bu kış ihtiyacı olan ailelere yakacak yardımı yapacak.", "sade-dil"),
    ("KD-C11", "Lütfen su biriktirin.", "kolay-dil"),
    ("KD-C11", "Size duyuruyoruz.", "kolay-dil"),
    ("KD-C11", "Vatandaş olarak haklarınızı bilin.", "kolay-dil"),
    ("KD-K01", "Başvurunuzu yapın.", "kolay-dil"),
    ("KD-K01", "Belgeleri hemen getirin.", "kolay-dil"),
    ("KD-K01", "Evin katta olması iyi.", "kolay-dil"),
    ("KD-K01", "Temiz su akınca kullanın.", "kolay-dil"),
    ("KD-K02", "Başvuruyu internetten yapın.", "kolay-dil"),
    ("KD-K02", "Televizyonu kapatın.", "kolay-dil"),
    ("KD-K02", "Otobüs yarın çalışacak.", "kolay-dil"),
    ("KD-K03", "Sosyal Güvenlik Kurumu (SGK) açık. SGK yarın da açık.", "kolay-dil"),
    ("KD-K03", "Ücret 10 TL.", "kolay-dil"),
    ("KD-K03", "Adres: Atatürk Cad. No: 5", "kolay-dil"),
    ("KD-K03", "SU KESİNTİSİ DUYURUSU", "kolay-dil"),
    ("KD-K04", "Belediyemize gelin.", "kolay-dil"),
    ("KD-K04", "Karşıyaka Belediyesi açık.", "kolay-dil"),
    ("KD-K04", "Su gelecek.", "kolay-dil"),
    ("KD-K05", "Belediye soruna baktı.", "kolay-dil"),
    ("KD-K05", "Gözünüzü doktora gösterin.", "kolay-dil"),
    ("KD-K05", "Elinizi yıkayın.", "kolay-dil"),
    ("KD-K06", "Su yarın gelecek.", "kolay-dil"),
    ("KD-K06", "Belediye yardım yapacak.", "kolay-dil"),
    ("KD-K06", "Şebekedeki bulanıklık geçecek.", "sade-dil"),
    ("KD-K07", "Su saat 17'de gelecek.", "kolay-dil"),
    ("KD-K07", "Kimlik kartınızı getirin.", "kolay-dil"),
    ("KD-K07", "Başvuru 1 Aralık'ta başlıyor.", "kolay-dil"),
    ("KD-K08", "Başvuru yarın başlıyor. Başvurunuzu yapın.", "kolay-dil"),
    ("KD-K08", "Ücret 10 lira.", "kolay-dil"),
    ("KD-K08", "Doktor sizi görecek.", "kolay-dil"),
    ("KD-B01", "Yardım 15.000 lira.", "kolay-dil"),
    ("KD-B01", "Bir gün sonra gelin.", "kolay-dil"),
    ("KD-B01", "Yirmi beş kişi geldi.", "sade-dil"),
    ("KD-B02", "19. yüzyılda yapıldı.", "kolay-dil"),
    ("KD-B02", "VILLA kiralık.", "kolay-dil"),
    ("KD-B02", "Seçim 15. bölgede.", "kolay-dil"),
    ("KD-B03", "100 aileden 35'i yardım alıyor.", "kolay-dil"),
    ("KD-B03", "Yarısı geldi.", "kolay-dil"),
    ("KD-B03", "Ailelerin %35'i yardım alıyor.", "sade-dil"),
    ("KD-B04", "Kesinti 15 Eylül 2026 Salı günü.", "kolay-dil"),
    ("KD-B04", "Kesinti Salı günü, 15 Eylül'de.", "kolay-dil"),
    ("KD-B04", "Aşı 1 Ekim 2026 günü başlıyor.", "sade-dil"),
    ("KD-B05", "Toplantı saat 14.30'da başlayacak.", "kolay-dil"),
    ("KD-B05", "Su saat 09.00 ile 17.00 arasında kesilecek.", "kolay-dil"),
    ("KD-B05", "Ekmek 3.50 TL oldu.", "kolay-dil"),
    ("KD-B06", "Telefon: 185", "kolay-dil"),
    ("KD-B06", "Belgelerinizi getirin.", "kolay-dil"),
    ("KD-B06", "Saat: 9", "kolay-dil"),
    ("KD-B07", "SU KESİNTİSİ DUYURUSU", "kolay-dil"),
    ("KD-B07", "AFAD ve SGK ekipleri geldi.", "kolay-dil"),
    ("KD-B07", "Su kesintisi hakkında önemli duyuru", "kolay-dil"),
    ("KD-B08", 'Muhtar "Yarın gelin" dedi.', "kolay-dil"),
    ("KD-B08", '"Temiz Mahalle" kampanyası başladı.', "kolay-dil"),
    ("KD-B08", 'Yardım "ücretsiz" dağıtılacak.', "sade-dil"),
    ("KD-M01", "Su kesilecek. Kesinti sabah başlar. Akşam biter.", "kolay-dil"),
    ("KD-M01", "- Bir\n- İki\n- Üç\n- Dört\n- Beş\n- Altı\n- Yedi", "kolay-dil"),
    ("KD-M01", "Su kesilecek. Kesinti sabah başlar. Akşam biter. Su biriktirin. Musluğu kapatın. Sonra bizi arayın.", "sade-dil"),
    ("KD-M03", "Kimlik kartı ve adres belgesi getirin.", "kolay-dil"),
    ("KD-M03", "Su kesilecek, belediye boruyu onaracak, su gelecek.", "kolay-dil"),
    ("KD-M03", "- Kimlik kartı\n- Adres belgesi\n- Gelir belgesi\n- Fotoğraf", "kolay-dil"),
]


@pytest.mark.parametrize(("rule_id", "text", "profile"), POSITIVE)
def test_rule_fires(rule_id: str, text: str, profile: str) -> None:
    assert rule_hits(text, rule_id, profile), f"{rule_id} tetiklenmedi: {text!r}"


@pytest.mark.parametrize(("rule_id", "text", "profile"), NEGATIVE)
def test_rule_silent(rule_id: str, text: str, profile: str) -> None:
    hits = rule_hits(text, rule_id, profile)
    assert not hits, f"{rule_id} yanlışlıkla tetiklendi: {text!r} → {[h.text for h in hits]}"


def test_every_rule_has_three_positive_and_three_negative() -> None:
    pos = {r for r, _t, _p in POSITIVE}
    neg: dict[str, int] = {}
    for r, _t, _p in NEGATIVE:
        neg[r] = neg.get(r, 0) + 1
    for rule in all_rules():
        if rule.id in ("KD-M02", "KD-M04", "KD-M05"):
            continue  # uzun metin gerektirir; aşağıda ayrı testleri var
        assert sum(1 for r, _t, _p in POSITIVE if r == rule.id) >= 3, rule.id
        assert neg.get(rule.id, 0) >= 3, rule.id
        assert rule.id in pos


# --------------------------------------------------------------- uzun metin kuralları

LONG_BODY = " ".join(["Belediye yarın sokakları temizleyecek."] * 45)


def test_m02_no_heading_positive() -> None:
    assert rule_hits(LONG_BODY, "KD-M02")
    assert rule_hits(LONG_BODY, "KD-M02", "sade-dil")
    assert rule_hits("Metin\n" + LONG_BODY, "KD-M02")  # "Metin" tek satır değil, başlık değil


def test_m02_no_heading_negative() -> None:
    assert not rule_hits("Temizlik günü\n\n" + LONG_BODY, "KD-M02")
    assert not rule_hits("# Temizlik günü\n\n" + LONG_BODY, "KD-M02")
    assert not rule_hits("Belediye yarın sokakları temizleyecek.", "KD-M02")


def _late_info_text(position: str) -> str:
    filler = "\n".join(["Belediye çalışıyor.", "Ekipler hazır.", "Herkes yardım etsin.",
                        "Çöpleri dışarı koyun.", "Sokaklar temiz olsun.", "Teşekkür ederiz."])
    info = "Bizi arayın: 0232 555 12 34"
    return f"{filler}\n{info}" if position == "son" else f"{info}\n{filler}"


def test_m04_key_info_late() -> None:
    assert rule_hits(_late_info_text("son"), "KD-M04")
    assert rule_hits(_late_info_text("son"), "KD-M04", "sade-dil")
    late_date = "Belediye çalışıyor. Ekipler hazır. Herkes yardım etsin. Çöpleri koyun. Kesinti 15 Eylül'de."
    assert rule_hits(late_date, "KD-M04")


def test_m04_key_info_early() -> None:
    assert not rule_hits(_late_info_text("bas"), "KD-M04")
    assert not rule_hits("Belediye çalışıyor. Ekipler hazır.", "KD-M04")
    assert not rule_hits("Kesinti 15 Eylül'de. Belediye çalışıyor. Ekipler hazır. Herkes yardım etsin.", "KD-M04")


def test_m05_long_text() -> None:
    long_text = " ".join(["Belediye yarın sokakları temizleyecek."] * 110)
    assert rule_hits(long_text, "KD-M05")
    assert not rule_hits(long_text, "KD-M05", "sade-dil")  # sade-dil'de kapalı
    assert not rule_hits(LONG_BODY, "KD-M05")


# --------------------------------------------------------------- ayrıntılar


def test_c01_severity_levels() -> None:
    warn = rule_hits("Bir iki üç dört beş altı yedi sekiz dokuz on on bir.", "KD-C01")
    assert warn and warn[0].severity == "uyarı"
    err = rule_hits("a b c d e f g h i j k l m n o p.", "KD-C01")
    assert err and err[0].severity == "hata"
    assert err[0].suggestion


def test_c03_active_suggestion() -> None:
    hit = rule_hits("Başvurular alınacaktır.", "KD-C03")[0]
    assert "'alacak'" in (hit.suggestion or "")
    hit = rule_hits("Su kesilecektir.", "KD-C03")[0]
    assert "'kesecek'" in (hit.suggestion or "")


def test_c03_reflexive_ambiguity_is_info() -> None:
    hits = rule_hits("Çocuk yıkandı.", "KD-C03")
    assert hits and hits[0].severity == "bilgi" and hits[0].confidence < 1


def test_active_form_edge_cases() -> None:
    from kolaymetin.text.morphology import best

    assert active_form(best("edilmektedir")) == "etmektedir"
    assert active_form(best("sağlanacak")) == "sağlayacak"
    assert active_form(best("gelecek")) is None


def test_k01_suggestion_and_inflection() -> None:
    hit = rule_hits("Müracaatlarınızı bekliyoruz.", "KD-K01")[0]
    assert "başvuru" in hit.message


def test_k03_only_first_occurrence() -> None:
    hits = rule_hits("SGK açık. SGK yarın da açık.", "KD-K03")
    assert len(hits) == 1


def test_k03_expansion_after() -> None:
    assert not rule_hits("SGK (Sosyal Güvenlik Kurumu) açık.", "KD-K03")


def test_k08_prefers_dominant() -> None:
    hits = rule_hits("Başvuru yarın. Başvuru formu hazır. Müracaat edin.", "KD-K08")
    assert hits and all("üracaat" in h.text for h in hits)


def test_b01_digits() -> None:
    hit = rule_hits("Yardım on beş bin lira.", "KD-B01")[0]
    assert "15.000" in hit.message
    assert parse_number_words(["bin", "iki", "yüz", "elli"]) == 1250
    assert parse_number_words(["iki", "milyon"]) == 2_000_000
    assert format_thousands(1234567) == "1.234.567"


def test_b02_roman() -> None:
    assert roman_to_int("XIX") == 19
    assert roman_to_int("MCMXCIV") == 1994
    assert "'19.'" in rule_hits("XIX. yüzyıl", "KD-B02")[0].message


def test_b03_possessive() -> None:
    assert possessive(35) == "35'i"
    assert possessive(20) == "20'si"
    assert possessive(6) == "6'sı"
    assert possessive(40) == "40'ı"
    assert "yarısı" in (rule_hits("Seçmenlerin %50'si geldi.", "KD-B03")[0].suggestion or "")


def test_b04_weekday_suggestion() -> None:
    hit = rule_hits("Kesinti 15.09.2026 günü.", "KD-B04")[0]
    assert "15 Eylül 2026 Salı" in hit.message
    hit = rule_hits("Aşı 1 Ekim 2026 günü başlıyor.", "KD-B04")[0]
    assert hit.severity == "bilgi" and "Perşembe" in (hit.suggestion or "")


def test_b07_suggestion_lowercases() -> None:
    hit = rule_hits("SU KESİNTİSİ HAKKINDA ÖNEMLİ DUYURU", "KD-B07")[0]
    assert "Su kesintisi hakkında önemli duyuru" in (hit.suggestion or "")


def test_rule_registry() -> None:
    rules = all_rules()
    assert len(rules) == 32
    assert get_rule("KD-C01").name == "Uzun cümle"
    assert [r.level for r in rules][:11] == ["cümle"] * 11


def test_every_finding_has_rehber_url_and_texts() -> None:
    text = (
        "SU KESİNTİSİ HAKKINDA ÖNEMLİ DUYURU\n\nMüracaatlar 15.09.2026 tarihinde ivedilikle "
        "alınacaktır; aksi takdirde başvurmamak mümkün değildir."
    )
    report = analyze(text)
    assert report.findings
    for f in report.findings:
        assert f.rehber_url == f"/rehber/{f.rule_id}"
        assert f.message and f.explanation
        assert text[f.start : f.end] == f.text
        assert 0 < f.confidence <= 1
