/* kolaymetin web arayüzü — çerçevesiz, derleme adımı yok.
   Metin denetim için bu sayfayı sunan sunucuya gönderilir (yerel kurulumda aynı bilgisayar,
   çevrim içi sürümde Vercel); orada saklanmaz. Başka hiçbir yere gitmez. */
(function () {
  "use strict";

  var ONEM_SIRA = { "hata": 0, "uyarı": 1, "bilgi": 2 };
  var ONEM_SINIF = { "hata": "hata", "uyarı": "uyari", "bilgi": "bilgi" };
  var ONEM_AD = { "hata": "Hata", "uyarı": "Uyarı", "bilgi": "Bilgi" };
  var ONEM_IKON = { "hata": "isaret-hata", "uyarı": "isaret-uyari", "bilgi": "isaret-bilgi" };
  var KATEGORI_AD = { "cümle": "Cümle", "kelime": "Kelime", "biçim": "Biçim", "metin": "Metin" };
  var OLCEKLER = [1, 1.125, 1.25, 1.5, 1.75];
  var GECIKME = 600;
  var EN_BUYUK_DOSYA = 4 * 1024 * 1024;  // sunucudaki MAX_UPLOAD_BYTES ile aynı
  var BAGLANTI_HATASI = "Sunucuya ulaşılamadı. İnternet bağlantınızı denetleyip yeniden deneyin.";

  var $ = function (id) { return document.getElementById(id); };
  var metin = $("metin"), arka = $("arka"), kenar = $("kenar"), masa = $("masa");

  var durum = {
    rapor: null,          // son rapor
    raporMetni: "",       // raporun ait olduğu metin
    yoksay: [],           // oturum boyunca yoksayılan bulgular
    secili: -1,           // seçili bulgu sırası
    acik: {},             // açık kartlar
    profiller: {},
    istek: null,
    yuklenenMetin: null,  // son yüklenen örnek ya da dosya
    zamanlayici: null,
    yuklemeZamanlayici: null,
    saglayicilar: []      // yeniden yazma için kullanılabilen dil modeli sağlayıcıları
  };

  // ------------------------------------------------------------------ yardımcılar
  function saklaOku(anahtar) { try { return window.localStorage.getItem(anahtar); } catch (e) { return null; } }
  function saklaYaz(anahtar, deger) { try { window.localStorage.setItem(anahtar, deger); } catch (e) { /* yok say */ } }

  function el(etiket, sinif, metinIcerik) {
    var e = document.createElement(etiket);
    if (sinif) { e.className = sinif; }
    if (metinIcerik !== undefined && metinIcerik !== null) { e.textContent = metinIcerik; }
    return e;
  }

  function ikon(ad, ekSinif) {
    var ns = "http://www.w3.org/2000/svg";
    var svg = document.createElementNS(ns, "svg");
    svg.setAttribute("class", "ikon" + (ekSinif ? " " + ekSinif : ""));
    svg.setAttribute("aria-hidden", "true");
    var use = document.createElementNS(ns, "use");
    use.setAttribute("href", "/static/ikonlar.svg#i-" + ad);
    svg.appendChild(use);
    return svg;
  }

  function sayi(deger, basamak) {
    if (deger === null || deger === undefined) { return "—"; }
    return Number(deger).toLocaleString("tr-TR", { minimumFractionDigits: basamak || 0, maximumFractionDigits: basamak || 0 });
  }

  function ditherSeviye(skor) { return Math.max(0, Math.min(16, Math.round(skor / 6.25))); }

  function cubukAyarla(dolgu, skor, seviye) {
    dolgu.className = dolgu.className.replace(/\bd-\d\d\b/g, "").trim() + " d-" + String(seviye === undefined ? ditherSeviye(skor) : seviye).padStart(2, "0");
    dolgu.style.width = Math.max(0, Math.min(100, skor)) + "%";
  }

  function duyur(ileti) { $("duyuru").textContent = ileti; }

  function hataGoster(ileti) {
    var kutu = $("hata");
    if (!ileti) { kutu.hidden = true; kutu.textContent = ""; return; }
    kutu.textContent = ileti;
    kutu.hidden = false;
  }

  // Sunucunun Türkçe hata iletisi. Vercel gibi aradaki katmanlar JSON olmayan yanıt döndürür
  // (ör. 4,5 MB üstü istekte düz metin 413); o zaman iletiyi durum kodundan seçer.
  function sunucuHatasi(yanit) {
    var yedek = yanit.status === 413
      ? "Dosya ya da metin çok büyük. En fazla 4 MB'lık dosya ve 100.000 karakter denetlenebilir."
      : yanit.status >= 500
        ? "Sunucuda bir sorun çıktı. Birkaç saniye sonra yeniden deneyin."
        : "Denetim yapılamadı. Lütfen yeniden deneyin.";
    return yanit.json().then(function (veri) {
      var d = veri && veri.detail;
      return typeof d === "string" ? d : yedek;
    }, function () { return yedek; });
  }

  function ag(hata) {
    // fetch() ağ hatasında TypeError fırlatır; iletisi tarayıcıya göre İngilizcedir.
    return hata instanceof TypeError ? BAGLANTI_HATASI : (hata && hata.message) || BAGLANTI_HATASI;
  }

  // Yazılmış metin örnek ya da dosyayla değiştirilmeden önce sorulur. Son yüklenen örnek ya da
  // dosya hiç değiştirilmediyse sormaya gerek yok.
  function metinDegissinMi() {
    var yazi = metin.value;
    if (!yazi.trim() || yazi === durum.yuklenenMetin) { return true; }
    return window.confirm("Metin alanındaki yazı silinecek ve yerine yenisi gelecek. Devam edilsin mi?");
  }

  // Ctrl+Z ile eski metne dönülebilsin diye metin, tarayıcının geri alma geçmişine giren
  // insertText ile değiştirilir. Desteklemeyen tarayıcıda doğrudan atanır.
  function metniDegistir(yeni) {
    metin.focus({ preventScroll: true });
    metin.select();
    var yazildi = false;
    try { yazildi = document.execCommand("insertText", false, yeni); } catch (e) { yazildi = false; }
    if (!yazildi || metin.value !== yeni) { metin.value = yeni; }
    metin.setSelectionRange(0, 0);
    durum.yuklenenMetin = yeni;
    durum.yoksay = []; durum.acik = {}; durum.secili = -1;
    $("yoksay-temizle").hidden = true;
    metin.scrollTop = 0;
    arkaCiz();
    denetle(true);
  }

  // Bulguların otomatik düzeltmelerini metne uygular. Ofsetler son raporun metnine aittir: metin
  // o zamandan beri değiştiyse hiçbir şey yapılmaz. Aralıkları çakışan düzeltmelerden önce
  // başlayan uygulanır; öteki yeni denetimde yeniden önerilir. Ctrl+Z ile geri alınabilsin diye
  // değişiklik insertText ile yazılır.
  function duzeltmeleriUygula(fixler) {
    if (!durum.rapor || durum.raporMetni !== metin.value) { return; }
    var yazi = metin.value, secilen = [], konum = 0;
    fixler.slice().sort(function (a, b) { return a.start - b.start || a.end - b.end; }).forEach(function (fx) {
      if (fx.start >= konum && fx.end <= yazi.length) { secilen.push(fx); konum = fx.end; }
    });
    if (!secilen.length) { return; }
    var bas = secilen[0].start, son = secilen[secilen.length - 1].end;
    var parca = "", k = bas;
    secilen.forEach(function (fx) { parca += yazi.slice(k, fx.start) + fx.text; k = fx.end; });
    var yeni = yazi.slice(0, bas) + parca + yazi.slice(son);
    var kaydirma = metin.scrollTop;
    metin.focus({ preventScroll: true });
    metin.setSelectionRange(bas, son);
    var yazildi = false;
    try { yazildi = document.execCommand("insertText", false, parca); } catch (e) { yazildi = false; }
    if (!yazildi || metin.value !== yeni) { metin.value = yeni; }
    metin.setSelectionRange(bas + parca.length, bas + parca.length);
    metin.scrollTop = kaydirma;
    arka.scrollTop = kaydirma;
    durum.acik = {}; durum.secili = -1;
    arkaCiz();
    denetle(true);
    duyur(secilen.length === 1
      ? "Düzeltildi. Geri almak için Ctrl+Z."
      : secilen.length + " düzeltme uygulandı. Geri almak için Ctrl+Z.");
  }

  // ------------------------------------------------------------------ yapay zekâyla yeniden yazma
  // İsteğe bağlı: varsayılan "Kapalı". Sağlayıcı ve model tarayıcıda hatırlanır; API anahtarı
  // yalnızca kullanıcı "hatırla" derse saklanır. Cümle bu sunucuya, sunucu da seçilen sağlayıcıya
  // gönderir (adres sunucudaki sabit listeden gelir).
  function yzSaglayici() {
    var id = $("yz-saglayici").value;
    return durum.saglayicilar.filter(function (p) { return p.id === id; })[0] || null;
  }

  function yzAyarGuncelle(kaydet) {
    var p = yzSaglayici();
    $("yz-model-alani").hidden = !p;
    $("yz-anahtar-alani").hidden = !p || !p.needs_key;
    $("yz-hatirla-alani").hidden = !p || !p.needs_key;
    $("yz-anahtar-bagi").hidden = !p || !p.key_url;
    if (p && p.key_url) { $("yz-anahtar-linki").href = p.key_url; }
    $("yz-not").textContent = !p ? "Kapalı: metin hiçbir dil modeline gönderilmez."
      : p.local ? "Metin bu bilgisayardaki modele gider; bilgisayardan çıkmaz."
      : p.id === "sunucu" ? "Yeniden yazdığınız cümle, bu sunucuyu kuran kişinin ayarladığı dil modeline gönderilir."
      : "Yeniden yazdığınız cümle " + p.title.replace(/ \(.*\)$/, "") + " sunucularına gönderilir. " +
        "Ücretsiz katmanda sağlayıcı metni kendi ürünlerini geliştirmek için kullanabilir. " +
        "Kişisel bilgi içeren cümleleri göndermeyin.";
    if (kaydet) {
      saklaYaz("kolaymetin.yz", $("yz-saglayici").value);
      if (p) { saklaYaz("kolaymetin.yz.model." + p.id, $("yz-model").value); }
      if (p && $("yz-hatirla").checked) { saklaYaz("kolaymetin.yz.anahtar." + p.id, $("yz-anahtar").value); }
      else if (p) { saklaYaz("kolaymetin.yz.anahtar." + p.id, ""); }
    }
  }

  function yzSaglayiciDegisti() {
    var p = yzSaglayici();
    if (p) {
      $("yz-model").value = saklaOku("kolaymetin.yz.model." + p.id) || p.model || "";
      var anahtar = saklaOku("kolaymetin.yz.anahtar." + p.id) || "";
      $("yz-anahtar").value = anahtar;
      $("yz-hatirla").checked = !!anahtar;
    }
    yzAyarGuncelle(true);
    kartlarCiz();
  }

  function yzYukle() {
    fetch("/api/yz").then(function (y) { return y.json(); }).then(function (veri) {
      durum.saglayicilar = veri.saglayicilar || [];
      var secim = $("yz-saglayici");
      durum.saglayicilar.forEach(function (p) {
        var opt = el("option", null, p.title);
        opt.value = p.id;
        secim.appendChild(opt);
      });
      var onceki = saklaOku("kolaymetin.yz") || "";
      if (durum.saglayicilar.some(function (p) { return p.id === onceki; })) { secim.value = onceki; }
      yzSaglayiciDegisti();
    }).catch(function () { $("yz-ayar").hidden = true; });
  }

  function yenidenYaz(f, kutu) {
    var r = durum.rapor, p = yzSaglayici();
    if (!r || !p || durum.raporMetni !== metin.value) { return; }
    var s = r.sentences[f.sentence_index];
    if (!s) { return; }
    var cumle = metin.value.slice(s.start, s.end);
    var komsu = function (k) {
      var c = r.sentences[k];
      return c && !c.is_heading ? metin.value.slice(c.start, c.end) : "";
    };
    var sorunlar = r.findings.filter(function (x) { return x.sentence_index === f.sentence_index; })
      .map(function (x) { return x.message; });
    kutu.textContent = "";
    kutu.appendChild(el("p", "etiket", "Yeniden yazılıyor… Yerel modelde bu bir dakika sürebilir."));
    fetch("/api/yeniden-yaz", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        sentence: cumle, problems: sorunlar, before: komsu(f.sentence_index - 1),
        after: komsu(f.sentence_index + 1), profile: $("profil").value,
        provider: p.id, model: $("yz-model").value.trim(), key: $("yz-anahtar").value.trim()
      })
    }).then(function (yanit) {
      if (!yanit.ok) { return sunucuHatasi(yanit).then(function (ileti) { throw new Error(ileti); }); }
      return yanit.json();
    }).then(function (sonuc) {
      yzSonucCiz(kutu, sonuc, s, cumle, f);
      duyur("Yeniden yazma önerisi hazır.");
    }).catch(function (hata) {
      kutu.textContent = "";
      kutu.appendChild(el("p", "yz-sonuc__uyari", ag(hata)));
    });
  }

  function yzSonucCiz(kutu, sonuc, s, cumle, f) {
    kutu.textContent = "";
    var kart = el("div", "yz-sonuc");
    kart.appendChild(el("p", "etiket", "Öneri (" + sonuc.model + "):"));
    kart.appendChild(el("p", "yz-sonuc__metin", sonuc.text));
    var skor = function (y) { return y.findings + " bulgu, skor " + (y.score === null ? "—" : y.score); };
    kart.appendChild(el("p", "etiket", "Önce: " + skor(sonuc.before) + " · Sonra: " + skor(sonuc.after)));
    if (sonuc.note) { kart.appendChild(el("p", "yz-sonuc__uyari", sonuc.note)); }
    var eylem = el("div", "not-kagidi__eylem");
    if (sonuc.applicable) {
      var uygula = el("button", "baglanti-dugme", "Uygula");
      uygula.type = "button";
      uygula.addEventListener("click", function () {
        if (metin.value.slice(s.start, s.end) !== cumle || durum.raporMetni !== metin.value) {
          hataGoster("Metin değişti. Önce yeniden denetleyin, sonra yeniden yazdırın.");
          return;
        }
        duzeltmeleriUygula([{ start: s.start, end: s.end, text: sonuc.text }]);
      });
      eylem.appendChild(uygula);
    }
    var yeniden = el("button", "baglanti-dugme", "Yeniden dene");
    yeniden.type = "button";
    yeniden.addEventListener("click", function () { yenidenYaz(f, kutu); });
    eylem.appendChild(yeniden);
    var vazgec = el("button", "baglanti-dugme", "Vazgeç");
    vazgec.type = "button";
    vazgec.addEventListener("click", function () { kutu.textContent = ""; });
    eylem.appendChild(vazgec);
    kart.appendChild(eylem);
    kutu.appendChild(kart);
  }

  // ------------------------------------------------------------------ süzgeçler
  function seciliDegerler(ad) {
    var out = {};
    document.querySelectorAll("input[name='" + ad + "']").forEach(function (k) { if (k.checked) { out[k.value] = true; } });
    return out;
  }

  function gorunurBulgular() {
    if (!durum.rapor) { return []; }
    var onem = seciliDegerler("onem"), kat = seciliDegerler("kategori");
    var liste = [];
    durum.rapor.findings.forEach(function (f, i) {
      if (onem[f.severity] && kat[f.category]) { liste.push({ f: f, i: i }); }
    });
    return liste;
  }

  // ------------------------------------------------------------------ düzeltmen işaretleri
  function arkaCiz() {
    var yazi = metin.value;
    arka.textContent = "";
    var bos = $("bos");
    bos.hidden = yazi.length > 0;
    var rapor = durum.rapor;
    if (!rapor || durum.raporMetni !== yazi) {
      arka.appendChild(document.createTextNode(yazi + "\n"));
      kenarCiz();
      secimCiz();
      return;
    }
    var bulgular = gorunurBulgular();
    var sinirlar = { 0: true };
    sinirlar[yazi.length] = true;
    bulgular.forEach(function (b) { sinirlar[b.f.start] = true; sinirlar[b.f.end] = true; });
    var noktalar = Object.keys(sinirlar).map(Number).sort(function (a, b) { return a - b; });
    for (var k = 0; k < noktalar.length - 1; k++) {
      var a = noktalar[k], s = noktalar[k + 1];
      if (a >= s) { continue; }
      var parca = yazi.slice(a, s);
      var ortu = bulgular.filter(function (b) { return b.f.start <= a && s <= b.f.end; });
      if (!ortu.length) { arka.appendChild(document.createTextNode(parca)); continue; }
      ortu.sort(function (x, y) { return ONEM_SIRA[x.f.severity] - ONEM_SIRA[y.f.severity]; });
      var kalem = ortu.some(function (b) { return b.f.severity === "uyarı"; }) && ortu[0].f.severity !== "uyarı";
      var span = el("span", "imi imi--" + ONEM_SINIF[ortu[0].f.severity] + (kalem ? " imi--kalem" : ""), parca);
      span.setAttribute("data-bulgular", ortu.map(function (b) { return b.i; }).join(" "));
      ortu.forEach(function (b) {
        if (b.f.start === a) { span.setAttribute("data-ilk-" + b.i, ""); }
      });
      arka.appendChild(span);
    }
    arka.appendChild(document.createTextNode("\n"));
    kenarCiz();
    secimCiz();
  }

  // Seçili bulgunun etrafına, her satır için tek bir mavi dikdörtgen çizer ("şurası" kutusu).
  function secimCiz() {
    var katman = $("secim-katmani");
    katman.textContent = "";
    var f = durum.rapor && durum.secili >= 0 ? durum.rapor.findings[durum.secili] : null;
    if (!f || durum.raporMetni !== metin.value) { return; }
    var konum = metinDugumu(f.start), bitis = metinDugumu(f.end);
    if (!konum || !bitis) { return; }
    var aralik = document.createRange();
    aralik.setStart(konum.dugum, konum.ofset);
    aralik.setEnd(bitis.dugum, bitis.ofset);
    var taban = katman.getBoundingClientRect();
    var satirlar = [];
    var dortgenler = Array.prototype.slice.call(aralik.getClientRects())
      .filter(function (r) { return r.width >= 1; })
      .sort(function (a, b) { return a.top - b.top || a.left - b.left; });
    dortgenler.forEach(function (r) {
      var son = satirlar[satirlar.length - 1];
      if (son && r.top < son.bottom - 2 && r.bottom > son.top + 2) {
        son.top = Math.min(son.top, r.top);
        son.left = Math.min(son.left, r.left);
        son.right = Math.max(son.right, r.right);
        son.bottom = Math.max(son.bottom, r.bottom);
      } else {
        satirlar.push({ top: r.top, bottom: r.bottom, left: r.left, right: r.right });
      }
    });
    satirlar.forEach(function (r) {
      var kutu = el("div", "secim-kutusu");
      kutu.style.top = (r.top - taban.top - 3) + "px";
      kutu.style.left = (r.left - taban.left - 3) + "px";
      kutu.style.width = (r.right - r.left + 6) + "px";
      kutu.style.height = (r.bottom - r.top + 6) + "px";
      katman.appendChild(kutu);
    });
  }

  // Arka plandaki metinde karakter konumuna karşılık gelen metin düğümünü bulur.
  function metinDugumu(hedef) {
    var yuruyucu = document.createTreeWalker(arka, NodeFilter.SHOW_TEXT);
    var sayac = 0;
    var dugum = yuruyucu.nextNode();
    while (dugum) {
      var uzunluk = dugum.nodeValue.length;
      if (hedef <= sayac + uzunluk) { return { dugum: dugum, ofset: hedef - sayac }; }
      sayac += uzunluk;
      dugum = yuruyucu.nextNode();
    }
    return null;
  }

  function kenarCiz() {
    kenar.textContent = "";
    if (!durum.rapor || durum.raporMetni !== metin.value) { return; }
    var kaydirma = metin.scrollTop;
    var satirYuksekligi = parseFloat(getComputedStyle(metin).lineHeight) || 32;
    var konumlar = [];
    gorunurBulgular().forEach(function (b) {
      var span = arka.querySelector("[data-ilk-" + b.i + "]");
      if (!span) { return; }
      var kutu = span.getClientRects()[0];
      var yukseklik = kutu ? kutu.height : satirYuksekligi;
      var ust = Math.round(span.offsetTop - kaydirma + yukseklik / 2 - satirYuksekligi / 2);
      if (ust < -satirYuksekligi || ust > metin.clientHeight) { return; }
      konumlar.push({ ust: ust, b: b });
    });
    konumlar.sort(function (x, y) { return x.ust - y.ust || ONEM_SIRA[x.b.f.severity] - ONEM_SIRA[y.b.f.severity]; });
    // Aynı satıra düşen işaretler tek bir satırda yan yana dizilir; satırlar üst üste binmez.
    var satirlar = [];
    konumlar.forEach(function (k) {
      var son = satirlar[satirlar.length - 1];
      if (son && k.ust - son.ust < satirYuksekligi * 0.75) { son.liste.push(k.b); }
      else { satirlar.push({ ust: k.ust, liste: [k.b] }); }
    });
    var enFazla = window.matchMedia && window.matchMedia("(max-width: 900px)").matches ? 1 : 3;
    satirlar.forEach(function (satir) {
      var kutu = el("div", "kenar-satir");
      kutu.style.top = satir.ust + "px";
      kutu.style.height = satirYuksekligi + "px";
      satir.liste.sort(function (x, y) { return ONEM_SIRA[x.f.severity] - ONEM_SIRA[y.f.severity]; });
      var kimlikYazildi = false;
      satir.liste.slice(0, enFazla).forEach(function (b) {
        var sinif = ONEM_SINIF[b.f.severity];
        var d = el("button", "kenar-isaret kenar-isaret--" + sinif);
        d.type = "button";
        d.tabIndex = -1;
        d.title = b.f.rule_id + ": " + b.f.message;
        d.appendChild(ikon(ONEM_IKON[b.f.severity], sinif === "hata" ? "ikon--kirmizi" : (sinif === "bilgi" ? "ikon--mavi" : "")));
        if (b.f.severity === "hata" && !kimlikYazildi) {
          d.appendChild(el("span", "kenar-isaret__kimlik", b.f.rule_id));
          kimlikYazildi = true;
        }
        d.addEventListener("click", function () { kartAc(b.i, true); });
        kutu.appendChild(d);
      });
      if (satir.liste.length > enFazla) { kutu.appendChild(el("span", "kenar-isaret kenar-isaret--fazla", "+" + (satir.liste.length - enFazla))); }
      kenar.appendChild(kutu);
    });
  }

  // ------------------------------------------------------------------ skorlar
  // "Kolay Dil Uyum Skoru", "Sade Dil Uyum Skoru": başlık seçilen profile göre.
  function skorBasligi(r) { return (r.profile_title || "Kolay Dil") + " Uyum Skoru"; }

  function skorlarCiz(r) {
    var c = r.scores.compliance;
    // Metinde cümle yoksa skor hesaplanamaz (null): 100 yerine "—" gösterilir.
    var deger = c.value === null ? "—" : String(c.value);
    $("uyum-baslik").textContent = skorBasligi(r);
    $("uyum").textContent = deger;
    $("uyum-sayi").textContent = deger;
    cubukAyarla($("uyum-cubuk"), c.value || 0);
    var not = $("uyum-not");
    // Yoksayılan bulgular skoru yükseltir; kullanıcı bunu görmeli (rapor da söyler).
    var notlar = [];
    if (c.note) { notlar.push(c.note); }
    if (c.ignored_count) {
      notlar.push(c.ignored_count + " bulgu yoksayıldı ve skora katılmadı. Yoksaymadan skor: " +
        (c.raw_value === null ? "—" : c.raw_value) + ".");
    }
    not.hidden = !notlar.length;
    not.textContent = notlar.join(" ");
    var kats = $("kategoriler");
    kats.textContent = "";
    c.by_category.forEach(function (k) {
      var li = el("li");
      li.appendChild(el("span", "etiket", KATEGORI_AD[k.category]));
      var satir = el("div", "cubuk-satir");
      var cubuk = el("div", "cubuk cubuk--ince");
      cubuk.setAttribute("aria-hidden", "true");
      var dolgu = el("div", "cubuk__dolgu");
      cubukAyarla(dolgu, k.score || 0);
      cubuk.appendChild(dolgu);
      satir.appendChild(cubuk);
      var kSkor = k.score === null ? "—" : String(k.score);
      var deger = el("span", "cubuk__deger", kSkor);
      deger.setAttribute("aria-label", KATEGORI_AD[k.category] + " skoru " + (k.score === null ? "yok" : k.score) + ", " + k.finding_count + " bulgu");
      satir.appendChild(deger);
      li.appendChild(satir);
      kats.appendChild(li);
    });
    var nasil = $("nasil-icerik");
    nasil.textContent = "";
    nasil.appendChild(el("p", "formul", c.formula));
    nasil.appendChild(el("p", null,
      "Ağırlıklar: hata = " + sayi(c.weights["hata"], 2) + ", uyarı = " + sayi(c.weights["uyarı"], 2) +
      ", bilgi = " + sayi(c.weights["bilgi"], 2) + ". Her bulgunun ağırlığı güveniyle çarpılır. k = " + sayi(c.k, 2) +
      ". Cümle sayısı: " + c.sentence_count + ". Toplam ceza: " + sayi(c.penalty, 2) +
      ". Cümle başına ceza: " + sayi(c.normalized, 2) + "."));
    var tablo = el("table", "katki-tablosu");
    var baslik = el("tr");
    ["Kural", "Bulgu", "Ceza"].forEach(function (b) { baslik.appendChild(el("th", null, b)); });
    var thead = el("thead"); thead.appendChild(baslik); tablo.appendChild(thead);
    var tbody = el("tbody");
    if (!c.contributions.length) {
      var bos = el("tr"); var td = el("td", null, "Bulgu yok."); td.colSpan = 3; bos.appendChild(td); tbody.appendChild(bos);
    }
    c.contributions.forEach(function (k) {
      var tr = el("tr");
      tr.appendChild(el("td", null, k.rule_id + " " + k.rule_name));
      tr.appendChild(el("td", null, String(k.count)));
      tr.appendChild(el("td", null, sayi(k.penalty, 2)));
      tbody.appendChild(tr);
    });
    tablo.appendChild(tbody);
    nasil.appendChild(tablo);

    var s = r.scores;
    $("atesman").textContent = sayi(s.atesman.value, 1);
    $("atesman-duzey").textContent = s.atesman.level;
    $("cetinkaya").textContent = sayi(s.cetinkaya_uzun.value, 1);
    $("cetinkaya-duzey").textContent = s.cetinkaya_uzun.level + (s.cetinkaya_uzun.grade ? " (" + s.cetinkaya_uzun.grade + ")" : "");
    $("bezirci").textContent = sayi(s.bezirci_yilmaz.value, 1);
    $("bezirci-duzey").textContent = s.bezirci_yilmaz.level;
    $("s-kelime").textContent = r.stats.word_count;
    $("s-cumle").textContent = r.stats.sentence_count;
    $("s-ortalama").textContent = sayi(r.stats.avg_sentence_length, 1);
    $("s-enuzun").textContent = r.stats.longest_sentence_words;
  }

  // ------------------------------------------------------------------ bulgu kartları
  function kartlarCiz() {
    var liste = $("bulgular");
    liste.textContent = "";
    var gorunur = gorunurBulgular();
    var toplam = durum.rapor ? durum.rapor.findings.length : 0;
    $("bulgu-sayisi").textContent = durum.rapor ? "(" + gorunur.length + (gorunur.length !== toplam ? "/" + toplam : "") + ")" : "";
    var duzeltilebilir = gorunur.filter(function (b) { return b.f.fix; }).length;
    $("hepsini-duzelt").hidden = !duzeltilebilir;
    $("hepsini-duzelt-metni").textContent = "Hepsini düzelt (" + duzeltilebilir + ")";
    var yok = $("bulgu-yok");
    $("bulgu-yok-gorsel").hidden = !!durum.rapor;
    if (!durum.rapor) {
      yok.hidden = false;
      yok.textContent = "Metin yazın ya da yapıştırın. Bulgular burada görünür.";
      return;
    }
    yok.hidden = gorunur.length > 0;
    yok.textContent = toplam ? "Seçili süzgeçlerde bulgu yok." : "Bu profilde bulgu yok. Yine de metni hedef okurlarla test edin.";
    gorunur.forEach(function (b) { liste.appendChild(kart(b.f, b.i)); });
  }

  function kart(f, i) {
    var sinif = ONEM_SINIF[f.severity];
    var li = el("li");
    var art = el("article", "not-kagidi not-kagidi--" + sinif + (i === durum.secili ? " not-kagidi--secili" : ""));
    art.id = "bulgu-" + i;
    var ust = el("div", "not-kagidi__ust");
    var onem = el("span", "onem onem--" + sinif);
    onem.appendChild(ikon(ONEM_IKON[f.severity]));
    onem.appendChild(document.createTextNode(ONEM_AD[f.severity]));
    ust.appendChild(onem);
    ust.appendChild(el("span", "kimlik kimlik--" + sinif, f.rule_id));
    ust.appendChild(el("span", "not-kagidi__ad", f.rule_name + (f.confidence < 1 ? " · güven " + sayi(f.confidence, 2) : "")));
    art.appendChild(ust);

    var acik = !!durum.acik[i];
    var dugme = el("button", "not-kagidi__mesaj", f.message);
    dugme.type = "button";
    dugme.setAttribute("aria-expanded", acik ? "true" : "false");
    dugme.setAttribute("aria-controls", "bulgu-govde-" + i);
    dugme.addEventListener("click", function () {
      durum.acik[i] = !durum.acik[i];
      var govde = $("bulgu-govde-" + i);
      govde.hidden = !durum.acik[i];
      dugme.setAttribute("aria-expanded", durum.acik[i] ? "true" : "false");
      if (durum.acik[i]) { art.classList.remove("acilis"); void art.offsetWidth; art.classList.add("acilis"); sec(i, false); }
    });
    art.appendChild(dugme);

    var govde = el("div", "not-kagidi__govde");
    govde.id = "bulgu-govde-" + i;
    govde.hidden = !acik;
    if (f.text) {
      var yer = el("p");
      yer.appendChild(el("span", "etiket", "Yer: "));
      yer.appendChild(el("span", "not-kagidi__alinti", "“" + (f.text.length > 140 ? f.text.slice(0, 140) + "…" : f.text) + "”"));
      govde.appendChild(yer);
    }
    govde.appendChild(el("p", null, f.explanation));
    if (f.suggestion) {
      var oneri = el("p", "not-kagidi__oneri");
      oneri.appendChild(el("span", null, f.suggestion));
      govde.appendChild(oneri);
    }
    var eylem = el("div", "not-kagidi__eylem");
    if (f.fix) {
      var duzelt = el("button", "baglanti-dugme", "Düzelt");
      duzelt.type = "button";
      duzelt.setAttribute("aria-label", "Düzelt: “" + f.text + "” yerine “" + f.fix.text + "” yaz");
      duzelt.addEventListener("click", function () { duzeltmeleriUygula([f.fix]); });
      eylem.appendChild(duzelt);
    }
    if (f.category === "cümle" && f.sentence_index !== null && yzSaglayici()) {
      var yaz = el("button", "baglanti-dugme", "Yapay zekâyla yeniden yaz");
      yaz.type = "button";
      yaz.addEventListener("click", function () { yenidenYaz(f, sonucKutusu); });
      eylem.appendChild(yaz);
    }
    var goster = el("button", "baglanti-dugme", "Metinde göster");
    goster.type = "button";
    goster.addEventListener("click", function () { metindeGoster(i); });
    eylem.appendChild(goster);
    var neden = el("a", null, "Neden? → rehber");
    neden.href = f.rehber_url;
    neden.target = "_blank";
    neden.rel = "noopener";
    eylem.appendChild(neden);
    var yoksay = el("button", "baglanti-dugme", "Yoksay");
    yoksay.type = "button";
    yoksay.setAttribute("aria-label", "Bu bulguyu oturum boyunca yoksay: " + f.rule_id + " " + (f.text || ""));
    yoksay.addEventListener("click", function () {
      var zatenVar = durum.yoksay.some(function (y) { return y.rule_id === f.rule_id && y.text === f.text; });
      if (!zatenVar) { durum.yoksay.push({ rule_id: f.rule_id, text: f.text }); }
      $("yoksay-temizle").hidden = false;
      duyur(f.rule_id + " bulgusu yoksayıldı. Aynı ifade bu oturumda yeniden işaretlenmeyecek.");
      denetle(true);
    });
    eylem.appendChild(yoksay);
    govde.appendChild(eylem);
    var sonucKutusu = el("div");
    sonucKutusu.setAttribute("aria-live", "polite");
    govde.appendChild(sonucKutusu);
    art.appendChild(govde);
    li.appendChild(art);
    return li;
  }

  function sec(i, kaydir) {
    durum.secili = i;
    document.querySelectorAll(".not-kagidi--secili").forEach(function (k) { k.classList.remove("not-kagidi--secili"); });
    var k = $("bulgu-" + i);
    if (k) { k.classList.add("not-kagidi--secili"); }
    if (kaydir) {
      var ilk = arka.querySelector("[data-ilk-" + i + "]");
      if (ilk) {
        var hedef = ilk.offsetTop - metin.clientHeight / 3;
        if (ilk.offsetTop < metin.scrollTop || ilk.offsetTop > metin.scrollTop + metin.clientHeight - 40) {
          metin.scrollTop = Math.max(0, hedef);
          arka.scrollTop = metin.scrollTop;
        }
      }
    }
    secimCiz();
  }

  function kartAc(i, odakla) {
    sekmeSec("sekme-bulgular");
    durum.acik[i] = true;
    var art = $("bulgu-" + i);
    if (!art) { kartlarCiz(); art = $("bulgu-" + i); }
    if (!art) { return; }
    var govde = $("bulgu-govde-" + i);
    govde.hidden = false;
    var dugme = art.querySelector(".not-kagidi__mesaj");
    dugme.setAttribute("aria-expanded", "true");
    art.classList.remove("acilis"); void art.offsetWidth; art.classList.add("acilis");
    sec(i, false);
    art.scrollIntoView({ block: "nearest" });
    if (odakla) { dugme.focus({ preventScroll: true }); }
  }

  // Editör ekranın dışındaysa (kartlarda aşağı inilmiş, dar ekranda sonuçlar altta) onu
  // ekrana getirir. Seçili metin görünmeden odakta kalırsa bir tuşa basmak onu siler.
  function editoruGoster() {
    var kutu = masa.getBoundingClientRect();
    var ekran = window.innerHeight || document.documentElement.clientHeight;
    if (kutu.top < 0 || kutu.bottom > ekran) {
      masa.scrollIntoView({ block: kutu.height > ekran ? "start" : "nearest" });
    }
  }

  function metindeSec(bas, son) {
    editoruGoster();
    metin.focus({ preventScroll: true });
    metin.setSelectionRange(bas, son);
  }

  function metindeGoster(i) {
    var f = durum.rapor && durum.rapor.findings[i];
    if (!f) { return; }
    sec(i, true);
    metindeSec(f.start, f.end);
    arka.scrollTop = metin.scrollTop;
    kenarCiz();
  }

  // ------------------------------------------------------------------ cümle görünümü
  function cumlelerCiz(r) {
    var liste = $("cumleler");
    liste.textContent = "";
    var profil = durum.profiller[r.profile];
    var esik = 8;
    if (profil && profil.rules["KD-C01"] && profil.rules["KD-C01"].params) { esik = profil.rules["KD-C01"].params.warn_above || esik; }
    var enUzun = 1;
    r.sentences.forEach(function (s) { if (!s.is_heading) { enUzun = Math.max(enUzun, s.word_count); } });
    var olcek = Math.max(enUzun, esik * 2);
    // Başlıklar listelenmez; numara 1'den başlar ve özetteki cümle sayısıyla örtüşür.
    var sira = 0;
    r.sentences.forEach(function (s) {
      if (s.is_heading) { return; }
      var n = sira++;
      var li = el("li");
      li.appendChild(el("span", "cumle-sayi", String(n + 1)));
      var d = el("button", "cumle-dugme");
      d.type = "button";
      var uzun = s.word_count > esik;
      d.setAttribute("aria-label", (n + 1) + ". cümle, " + s.word_count + " kelime" + (uzun ? ", uzun" : "") + ": " + s.text);
      var cubuk = el("div", "cubuk cumle-cubugu" + (uzun ? " cumle-cubugu--uzun" : ""));
      var dolgu = el("div", "cubuk__dolgu");
      cubukAyarla(dolgu, (s.word_count / olcek) * 100, uzun ? 12 : 8);
      cubuk.appendChild(dolgu);
      var cizgi = el("span", "esik-cizgisi");
      cizgi.style.left = ((esik / olcek) * 100) + "%";
      cubuk.appendChild(cizgi);
      d.appendChild(cubuk);
      d.appendChild(el("span", "cumle-metni", s.text));
      d.addEventListener("click", function () { metindeSec(s.start, s.end); });
      li.appendChild(d);
      li.appendChild(el("span", "cumle-sayi" + (uzun ? " cumle-sayi--uzun" : ""), s.word_count + (uzun ? "!" : "")));
      liste.appendChild(li);
    });
  }

  // ------------------------------------------------------------------ denetim
  // Yükleme göstergesi: sonuç panelinde ve Denetle düğmesinde dönen dörtlü.
  // Kısa istekler göstergeyi hiç açmasın diye 150 ms beklenir.
  function yukleniyor(acik, ileti) {
    clearTimeout(durum.yuklemeZamanlayici);
    var panel = $("yukleniyor"), dugme = $("denetle"), sonuc = panel.parentNode;
    if (acik) {
      $("yukleniyor-metni").textContent = ileti || "Denetleniyor…";
      durum.yuklemeZamanlayici = setTimeout(function () {
        panel.hidden = false;
        dugme.classList.add("dugme--calisiyor");
        sonuc.setAttribute("aria-busy", "true");
      }, 150);
    } else {
      panel.hidden = true;
      dugme.classList.remove("dugme--calisiyor");
      sonuc.removeAttribute("aria-busy");
    }
  }

  function istekGovdesi() {
    return { text: metin.value, profile: $("profil").value, ignored: durum.yoksay };
  }

  // Uzun metinde her denetim daha uzun sürer ve sunucuyu daha çok yorar: yazarken denetim
  // metin uzadıkça daha geç başlar (10.000 karakterde ~0,8 sn, 100.000'de 3 sn).
  function gecikme() { return GECIKME + Math.min(2400, Math.round(metin.value.length / 40)); }

  function denetle(hemen) {
    clearTimeout(durum.zamanlayici);
    if (!hemen) { durum.zamanlayici = setTimeout(function () { denetle(true); }, gecikme()); return; }
    var yazi = metin.value;
    if (!yazi.trim()) {
      durum.rapor = null; durum.raporMetni = "";
      arkaCiz(); kartlarCiz(); hataGoster("");
      return;
    }
    if (durum.istek) { durum.istek.abort(); }
    var denetci = new AbortController();
    durum.istek = denetci;
    yukleniyor(true);
    fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(istekGovdesi()),
      signal: denetci.signal
    }).then(function (yanit) {
      if (!yanit.ok) { return sunucuHatasi(yanit).then(function (ileti) { throw new Error(ileti); }); }
      return yanit.json();
    }).then(function (rapor) {
      if (durum.istek !== denetci) { return; }
      durum.istek = null;
      yukleniyor(false);
      hataGoster("");
      if (metin.value !== yazi) { return; }
      durum.rapor = rapor;
      durum.raporMetni = yazi;
      if (durum.secili >= rapor.findings.length) { durum.secili = -1; }
      skorlarCiz(rapor);
      kartlarCiz();
      cumlelerCiz(rapor);
      arkaCiz();
      var skor = rapor.scores.compliance.value;
      duyur("Denetim bitti: " + rapor.findings.length + " bulgu. " + skorBasligi(rapor) + " " +
        (skor === null ? "hesaplanamadı" : skor) + ".");
    }).catch(function (hata) {
      if (hata && hata.name === "AbortError") { return; }
      durum.istek = null;
      yukleniyor(false);
      hataGoster(ag(hata));
    });
  }

  // ------------------------------------------------------------------ dosya, örnek, dışa aktarma
  function dosyaYukle(dosya) {
    if (!dosya) { return; }
    // Sunucu da denetler; burada denetlemek büyük dosyanın boşuna gönderilmesini önler.
    if (!/\.(txt|md|markdown|docx|pdf)$/i.test(dosya.name)) {
      hataGoster("Bu dosya türü desteklenmiyor. Desteklenen türler: .txt, .md, .docx, .pdf");
      return;
    }
    if (dosya.size > EN_BUYUK_DOSYA) {
      hataGoster("Dosya çok büyük. En fazla 4 MB yükleyebilirsiniz.");
      return;
    }
    var veri = new FormData();
    veri.append("file", dosya);
    yukleniyor(true, "Dosya okunuyor…");
    fetch("/api/upload", { method: "POST", body: veri }).then(function (yanit) {
      if (!yanit.ok) { return sunucuHatasi(yanit).then(function (ileti) { throw new Error(ileti); }); }
      return yanit.json();
    }).then(function (sonuc) {
      yukleniyor(false);
      hataGoster("");
      if (!metinDegissinMi()) { return; }
      metniDegistir(sonuc.text);
      duyur(dosya.name + " yüklendi. " + sonuc.karakter + " karakter.");
    }).catch(function (hata) {
      yukleniyor(false);
      hataGoster(ag(hata));
    });
  }

  function disaAktar(bicim) {
    if (!metin.value.trim()) { hataGoster("Önce bir metin yazın ya da yapıştırın."); return; }
    var govde = istekGovdesi();
    govde.format = bicim;
    fetch("/api/export", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(govde)
    }).then(function (yanit) {
      if (!yanit.ok) { return sunucuHatasi(yanit).then(function (ileti) { throw new Error(ileti); }); }
      return yanit.blob();
    }).then(function (blob) {
      var baglanti = document.createElement("a");
      baglanti.href = URL.createObjectURL(blob);
      baglanti.download = "kolaymetin-rapor." + bicim;
      document.body.appendChild(baglanti);
      baglanti.click();
      setTimeout(function () { URL.revokeObjectURL(baglanti.href); baglanti.remove(); }, 1000);
      duyur("Rapor indirildi: kolaymetin-rapor." + bicim);
    }).catch(function (hata) { hataGoster(ag(hata)); });
  }

  function ornekleriYukle() {
    fetch("/api/ornekler").then(function (y) { return y.json(); }).then(function (liste) {
      var secim = $("ornek");
      liste.forEach(function (o) {
        var opt = el("option", null, o.baslik);
        opt.value = o.id;
        secim.appendChild(opt);
      });
      secim.addEventListener("change", function () {
        var o = liste.filter(function (x) { return x.id === secim.value; })[0];
        // Seçim hemen "Seçin…"e döner: aynı örnek yeniden seçilebilsin.
        secim.value = "";
        if (!o || !metinDegissinMi()) { return; }
        metniDegistir(o.metin);
        duyur(o.baslik + " örneği yüklendi.");
      });
    }).catch(function () { /* örnekler isteğe bağlı */ });
  }

  function profilleriYukle() {
    fetch("/api/profiles").then(function (y) { return y.json(); }).then(function (liste) {
      liste.forEach(function (p) { durum.profiller[p.name] = p; });
      if (durum.rapor) { cumlelerCiz(durum.rapor); }
    }).catch(function () { /* varsayılan eşik kullanılır */ });
  }

  // ------------------------------------------------------------------ sekmeler
  function sekmeSec(id) {
    ["sekme-bulgular", "sekme-cumleler"].forEach(function (s) {
      var sekme = $(s), secili = s === id;
      sekme.setAttribute("aria-selected", secili ? "true" : "false");
      sekme.tabIndex = secili ? 0 : -1;
      $(sekme.getAttribute("aria-controls")).hidden = !secili;
    });
  }

  // ------------------------------------------------------------------ görünüm tercihleri
  function temaDugmesiGuncelle() {
    var koyu = document.documentElement.getAttribute("data-theme") === "dark" ||
      (!document.documentElement.getAttribute("data-theme") && window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches);
    var d = $("tema-dugmesi");
    d.setAttribute("aria-pressed", koyu ? "true" : "false");
    d.querySelector("span").textContent = koyu ? "Açık tema" : "Koyu tema";
  }

  function olcekDegistir(yon) {
    var simdiki = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--olcek")) || 1;
    var i = OLCEKLER.indexOf(simdiki);
    if (i < 0) { i = 0; }
    i = Math.max(0, Math.min(OLCEKLER.length - 1, i + yon));
    document.documentElement.style.setProperty("--olcek", String(OLCEKLER[i]));
    saklaYaz("kolaymetin.olcek", String(OLCEKLER[i]));
    $("yazi-kucult").disabled = i === 0;
    $("yazi-buyut").disabled = i === OLCEKLER.length - 1;
    duyur("Yazı boyutu: %" + Math.round(OLCEKLER[i] * 100));
    setTimeout(kenarCiz, 50);
  }

  // ------------------------------------------------------------------ olaylar
  function baslat() {
    var bugun = new Date();
    $("bugun").textContent = bugun.toLocaleDateString("tr-TR", { day: "numeric", month: "long", year: "numeric", weekday: "long" });

    metin.addEventListener("input", function () {
      arkaCiz();
      if ($("otomatik").checked) { denetle(false); }
    });
    metin.addEventListener("scroll", function () { arka.scrollTop = metin.scrollTop; kenarCiz(); secimCiz(); });
    metin.addEventListener("click", function () {
      if (!durum.rapor || durum.raporMetni !== metin.value) { return; }
      var konum = metin.selectionStart;
      if (metin.selectionEnd !== konum) { return; }
      var aday = gorunurBulgular().filter(function (b) { return b.f.start <= konum && konum < b.f.end; });
      if (!aday.length) { return; }
      aday.sort(function (x, y) { return ONEM_SIRA[x.f.severity] - ONEM_SIRA[y.f.severity] || (x.f.end - x.f.start) - (y.f.end - y.f.start); });
      kartAc(aday[0].i, false);
    });
    window.addEventListener("resize", function () { kenarCiz(); secimCiz(); });

    $("denetle").addEventListener("click", function () { denetle(true); });
    $("profil").addEventListener("change", function () { denetle(true); });
    document.querySelectorAll("input[name='onem'], input[name='kategori']").forEach(function (k) {
      k.addEventListener("change", function () { kartlarCiz(); arkaCiz(); });
    });

    $("yukle-dugmesi").addEventListener("click", function () { $("dosya").click(); });
    $("dosya").addEventListener("change", function (e) { dosyaYukle(e.target.files[0]); e.target.value = ""; });
    ["dragenter", "dragover"].forEach(function (ad) {
      masa.addEventListener(ad, function (e) { e.preventDefault(); masa.classList.add("surukle"); });
    });
    ["dragleave", "drop"].forEach(function (ad) {
      masa.addEventListener(ad, function () { masa.classList.remove("surukle"); });
    });
    masa.addEventListener("drop", function (e) {
      e.preventDefault();
      if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0]) { dosyaYukle(e.dataTransfer.files[0]); }
    });

    document.querySelectorAll("[data-bicim]").forEach(function (d) {
      d.addEventListener("click", function () { disaAktar(d.getAttribute("data-bicim")); });
    });
    $("yz-saglayici").addEventListener("change", yzSaglayiciDegisti);
    ["yz-model", "yz-anahtar"].forEach(function (id) {
      $(id).addEventListener("change", function () { yzAyarGuncelle(true); });
    });
    $("yz-hatirla").addEventListener("change", function () { yzAyarGuncelle(true); });
    $("hepsini-duzelt").addEventListener("click", function () {
      duzeltmeleriUygula(gorunurBulgular().filter(function (b) { return b.f.fix; }).map(function (b) { return b.f.fix; }));
    });
    $("yoksay-temizle").addEventListener("click", function () {
      durum.yoksay = [];
      $("yoksay-temizle").hidden = true;
      duyur("Yoksayılan bulgular geri alındı.");
      denetle(true);
    });

    ["sekme-bulgular", "sekme-cumleler"].forEach(function (id, n, hepsi) {
      var s = $(id);
      s.addEventListener("click", function () { sekmeSec(id); });
      s.addEventListener("keydown", function (e) {
        if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
          e.preventDefault();
          var sonraki = hepsi[(n + (e.key === "ArrowRight" ? 1 : hepsi.length - 1)) % hepsi.length];
          sekmeSec(sonraki);
          $(sonraki).focus();
        }
      });
    });

    $("tema-dugmesi").addEventListener("click", function () {
      var koyu = $("tema-dugmesi").getAttribute("aria-pressed") === "true";
      var yeni = koyu ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", yeni);
      saklaYaz("kolaymetin.tema", yeni);
      temaDugmesiGuncelle();
    });
    $("yazi-buyut").addEventListener("click", function () { olcekDegistir(1); });
    $("yazi-kucult").addEventListener("click", function () { olcekDegistir(-1); });

    temaDugmesiGuncelle();
    olcekDegistir(0);
    duyur("");
    // Çözümleyiciyi kullanıcı metni yazarken ısıtır; soğuk başlayan sunucuda ilk denetim beklemez.
    fetch("/saglik").catch(function () { /* ısıtma isteğe bağlı */ });
    ornekleriYukle();
    profilleriYukle();
    yzYukle();
    arkaCiz();
    kartlarCiz();
    if (metin.value.trim()) { denetle(true); }
  }

  baslat();
})();
