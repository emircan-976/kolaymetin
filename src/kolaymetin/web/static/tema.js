/* Tema ve yazı boyutu tercihini sayfa çizilmeden önce uygular.
   Tercihler yalnızca bu tarayıcıda saklanır (localStorage); erişilemezse varsayılan kullanılır.

   Hazır temaların renkleri style.css içindeki :root[data-tema="…"] bloklarındadır (kontrastları
   scripts/kontrast_denetle.py denetler). Bu dosya temanın ölçülerini (yazı tipi, aralık, köşe,
   çizgi, gölge, yerleşim) ve kullanıcının kendi temalarının renklerini uygular.
   CSP satır içi <style> öğesine izin vermez; değerler CSSOM ile (adoptedStyleSheets) yazılır.
   Temalar panelinin arayüzü temalar.js'dedir; ikisi window.kolaymetinTema üzerinden konuşur. */
(function () {
  "use strict";
  var kok = document.documentElement;
  var SECIM_ANAHTARI = "kolaymetin.tema", OZEL_ANAHTARI = "kolaymetin.temalar";
  var EN_COK_OZEL = 30;

  var YAZILAR = {
    atkinson: { ad: "Atkinson", deger: "\"Atkinson Hyperlegible Next\", sans-serif" },
    genis: { ad: "Verdana (geniş)", deger: "Verdana, Tahoma, \"DejaVu Sans\", sans-serif" },
    serif: { ad: "Georgia (tırnaklı)", deger: "Georgia, \"Times New Roman\", \"DejaVu Serif\", serif" },
    mono: { ad: "Atkinson Mono", deger: "\"Atkinson Hyperlegible Mono\", monospace" }
  };
  var GOLGELER = {
    baski: { ad: "Baskı gölgesi (keskin)", dugme: "3px 3px 0 var(--murekkep-soluk)", kart: "none" },
    yumusak: {
      ad: "Yumuşak gölge",
      dugme: "0 2px 4px color-mix(in srgb, var(--murekkep) 30%, transparent)",
      kart: "0 1px 2px color-mix(in srgb, var(--murekkep) 12%, transparent), 0 6px 16px color-mix(in srgb, var(--murekkep) 8%, transparent)"
    },
    yok: { ad: "Gölge yok", dugme: "none", kart: "none" }
  };
  var YERLESIMLER = { iki: "Metin solda", ters: "Metin sağda", tek: "Tek sütun" };
  // [anahtar, CSS değişkeni, panelde görünen ad]
  var RENKLER = [
    ["kagit", "--kagit", "Zemin"],
    ["kagit2", "--kagit-2", "Kartlar ve paneller"],
    ["murekkep", "--murekkep", "Yazı ve çizgiler"],
    ["soluk", "--murekkep-soluk", "İkincil yazı"],
    ["kirmizi", "--kirmizi", "Hata"],
    ["mavi", "--mavi", "Bilgi ve bağlantı"],
    ["sari", "--sari", "Fosforlu kalem"]
  ];
  var OLCULER = {
    satir: { min: 1.3, max: 2.2 },
    harf: { min: 0, max: 0.12 },
    kelime: { min: 0, max: 0.32 },
    sikilik: { min: 0.75, max: 1.5 },
    yaricap: { min: 0, max: 16 },
    cizgi: { min: 1, max: 4 }
  };
  // Düzeltmen Masası'nın ölçüleri; style.css'teki :root varsayılanlarıyla aynı.
  var VARSAYILAN = {
    koyu: false, yazi: "atkinson", baslik: "atkinson", etiket: "mono",
    satir: 1.6, harf: 0, kelime: 0, sikilik: 1, yaricap: 0, cizgi: 2,
    golge: "baski", yerlesim: "iki", sus: true, hareket: true
  };

  function kopya(nesne) {
    var yeni = {};
    for (var k in nesne) { if (Object.prototype.hasOwnProperty.call(nesne, k)) { yeni[k] = nesne[k]; } }
    return yeni;
  }
  function ayar(ek) {
    var t = kopya(VARSAYILAN);
    for (var k in ek) { t[k] = ek[k]; }
    return t;
  }

  var HAZIR = [
    { id: "masa", ad: "Düzeltmen Masası", not: "Krem kâğıt, siyah mürekkep, kırmızı ve mavi. Varsayılan.", ayar: ayar({}) },
    { id: "negatif", ad: "Negatif Baskı", not: "Masanın koyu hâli: koyu zemin, açık mürekkep.", ayar: ayar({ koyu: true }) },
    { id: "ofis", ad: "Sade Ofis", not: "Beyaz zemin, yuvarlak köşeler, yumuşak gölge.", ayar: ayar({ etiket: "govde", yaricap: 10, cizgi: 1, golge: "yumusak", sus: false }) },
    { id: "kamu", ad: "Kamu Belgesi", not: "Resmî yazı görünümü, tırnaklı başlıklar.", ayar: ayar({ baslik: "serif", etiket: "govde", yaricap: 2, cizgi: 1, golge: "yok", sus: false }) },
    { id: "kontrast", ad: "Yüksek Kontrast", not: "Siyah zemin, kalın çizgiler, geniş satır aralığı.", ayar: ayar({ koyu: true, etiket: "govde", satir: 1.75, harf: 0.02, cizgi: 3, golge: "yok", sus: false }) },
    { id: "kenar", ad: "Kenar Notları", not: "Beyaz kâğıt, camgöbeği vurgu, ferah kartlar.", ayar: ayar({ etiket: "govde", yaricap: 12, cizgi: 1, golge: "yumusak", sikilik: 1.15, sus: false }) },
    { id: "sepya", ad: "Sepya", not: "Sıcak kâğıt rengi, uzun okumada göz yormaz.", ayar: ayar({ satir: 1.75, yaricap: 4, cizgi: 1, golge: "yok" }) },
    { id: "gece", ad: "Gece Mavisi", not: "Lacivert zemin, yumuşak köşeler.", ayar: ayar({ koyu: true, yaricap: 8, cizgi: 1, golge: "yok" }) },
    { id: "okuma", ad: "Okuma Kolaylığı", not: "Geniş harfler, bol aralık, canlandırma yok.", ayar: ayar({ yazi: "genis", baslik: "genis", etiket: "govde", satir: 1.9, harf: 0.04, kelime: 0.12, sikilik: 1.15, yaricap: 6, golge: "yok", sus: false, hareket: false }) }
  ];

  // ------------------------------------------------------------------ saklama
  function oku(anahtar) {
    try { return window.localStorage.getItem(anahtar); } catch (e) { return null; }
  }
  function yaz(anahtar, deger) {
    try { window.localStorage.setItem(anahtar, deger); return true; } catch (e) { return false; }
  }

  function yeniId() { return "ozel-" + Date.now().toString(36) + Math.floor(Math.random() * 1296).toString(36); }
  var ID_DESENI = /^ozel-[a-z0-9]{1,16}$/;
  var RENK_DESENI = /^#[0-9a-f]{6}$/i;

  /* Dışarıdan gelen (saklanan ya da içe aktarılan) temayı doğrular. CSS'e yalnızca bu
     tablolardaki değerler, sınırlandırılmış sayılar ve #RRGGBB renkler yazılır. */
  function temizle(v) {
    if (!v || typeof v !== "object") { return null; }
    var t = ayar({});
    t.renk = {};
    for (var i = 0; i < RENKLER.length; i++) {
      var r = v.renk && v.renk[RENKLER[i][0]];
      if (typeof r !== "string" || !RENK_DESENI.test(r)) { return null; }
      t.renk[RENKLER[i][0]] = r.toUpperCase();
    }
    t.koyu = v.koyu === true;
    if (YAZILAR[v.yazi]) { t.yazi = v.yazi; }
    if (YAZILAR[v.baslik]) { t.baslik = v.baslik; }
    if (v.etiket === "mono" || v.etiket === "govde") { t.etiket = v.etiket; }
    if (GOLGELER[v.golge]) { t.golge = v.golge; }
    if (YERLESIMLER[v.yerlesim]) { t.yerlesim = v.yerlesim; }
    t.sus = v.sus !== false;
    t.hareket = v.hareket !== false;
    for (var k in OLCULER) {
      var n = Number(v[k]);
      if (v[k] !== undefined && v[k] !== null && v[k] !== "" && isFinite(n)) {
        t[k] = Math.round(Math.min(OLCULER[k].max, Math.max(OLCULER[k].min, n)) * 100) / 100;
      }
    }
    t.ad = (typeof v.ad === "string" ? v.ad : "").replace(/\s+/g, " ").trim().slice(0, 40) || "Benim temam";
    t.id = typeof v.id === "string" && ID_DESENI.test(v.id) ? v.id : yeniId();
    return t;
  }

  function ozelTemalar() {
    var liste;
    try { liste = JSON.parse(oku(OZEL_ANAHTARI) || "[]"); } catch (e) { return []; }
    if (!Array.isArray(liste)) { return []; }
    return liste.map(temizle).filter(Boolean).slice(0, EN_COK_OZEL);
  }
  function ozelleriYaz(liste) { return yaz(OZEL_ANAHTARI, JSON.stringify(liste)); }

  function hazirBul(id) {
    for (var i = 0; i < HAZIR.length; i++) { if (HAZIR[i].id === id) { return HAZIR[i]; } }
    return null;
  }
  function ozelBul(id) {
    var liste = ozelTemalar();
    for (var i = 0; i < liste.length; i++) { if (liste[i].id === id) { return liste[i]; } }
    return null;
  }

  // ------------------------------------------------------------------ uygulama
  var sayfa = null;
  try {
    if (window.CSSStyleSheet && "adoptedStyleSheets" in document) {
      sayfa = new CSSStyleSheet();
      document.adoptedStyleSheets = document.adoptedStyleSheets.concat([sayfa]);
    }
  } catch (e) { sayfa = null; }
  var satirIci = [];  // adoptedStyleSheets yoksa kökün style özniteliğine yazılan değişkenler

  function bildirimler(a, renk) {
    var g = GOLGELER[a.golge];
    var liste = [
      ["--f-govde", YAZILAR[a.yazi].deger],
      ["--f-baslik", YAZILAR[a.baslik].deger],
      ["--f-mono", a.etiket === "mono" ? YAZILAR.mono.deger : "var(--f-govde)"],
      ["--satir", String(a.satir)],
      ["--harf", a.harf + "em"],
      ["--kelime", a.kelime + "em"],
      ["--sikilik", String(a.sikilik)],
      ["--yaricap", a.yaricap + "px"],
      ["--cizgi", a.cizgi + "px"],
      ["--golge-dugme", g.dugme],
      ["--golge-kart", g.kart]
    ];
    if (renk) {
      RENKLER.forEach(function (r) { liste.push([r[1], renk[r[0]]]); });
      liste.push(["color-scheme", a.koyu ? "dark" : "light"]);
    }
    return liste;
  }

  function stilYaz(liste) {
    if (sayfa) {
      // Yalnızca ekranda: yazdırırken style.css'in basılı prova kuralları geçerlidir.
      var govde = liste.map(function (b) { return b[0] + ": " + b[1] + ";"; }).join(" ");
      sayfa.replaceSync("@media screen { :root[data-tema][data-tema] { " + govde + " } }");
      return;
    }
    satirIci.forEach(function (ad) { kok.style.removeProperty(ad); });
    satirIci = liste.map(function (b) { kok.style.setProperty(b[0], b[1]); return b[0]; });
  }

  var secim = oku(SECIM_ANAHTARI);
  if (secim === "dark") { secim = "negatif"; }       // eski "Koyu tema" düğmesinin kaydı
  else if (secim === "light") { secim = "masa"; }
  else if (!secim) { secim = "otomatik"; }

  var sistemKoyu = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : { matches: false };

  function uygula(id) {
    var hedef = id === "otomatik" ? (sistemKoyu.matches ? "negatif" : "masa") : id;
    var hazir = hazirBul(hedef), ozel = hazir ? null : ozelBul(hedef);
    if (!hazir && !ozel) { hazir = hazirBul("masa"); }  // silinmiş ya da bozuk tema
    var a = hazir ? hazir.ayar : ozel;
    kok.setAttribute("data-tema", hazir ? hazir.id : "ozel");
    kok.setAttribute("data-theme", a.koyu ? "dark" : "light");
    kok.setAttribute("data-golge", a.golge);
    kok.setAttribute("data-yerlesim", a.yerlesim);
    kok.setAttribute("data-sus", a.sus ? "acik" : "kapali");
    kok.setAttribute("data-hareket", a.hareket ? "acik" : "az");
    stilYaz(bildirimler(a, ozel ? ozel.renk : null));
    var olay;
    try { olay = new CustomEvent("kolaymetin:tema", { detail: { id: id } }); } catch (e) { olay = null; }
    if (olay) { document.dispatchEvent(olay); }
  }

  function sec(id) {
    if (id !== "otomatik" && !hazirBul(id) && !ozelBul(id)) { id = "masa"; }
    secim = id;
    yaz(SECIM_ANAHTARI, id);
    uygula(id);
  }

  if (sistemKoyu.addEventListener) {
    sistemKoyu.addEventListener("change", function () { if (secim === "otomatik") { uygula(secim); } });
  }

  // ------------------------------------------------------------------ kontrast (WCAG 2.2)
  function parlaklik(renk) {
    var n = parseInt(renk.slice(1), 16);
    var kanallar = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map(function (c) {
      c /= 255;
      return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * kanallar[0] + 0.7152 * kanallar[1] + 0.0722 * kanallar[2];
  }
  function kontrast(a, b) {
    var la = parlaklik(a), lb = parlaklik(b);
    return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
  }

  /* Şu an görünen temanın bütün ayarları (Özelleştir bölümünü doldurmak için). Hazır temanın
     renkleri style.css'te olduğundan uygulanmış değişkenlerden okunur. */
  function etkinTema() {
    var hedef = secim === "otomatik" ? (sistemKoyu.matches ? "negatif" : "masa") : secim;
    var ozel = ozelBul(hedef);
    if (ozel) { return ozel; }
    var hazir = hazirBul(hedef) || hazirBul("masa");
    var t = kopya(hazir.ayar);
    var stil = getComputedStyle(kok);
    t.renk = {};
    RENKLER.forEach(function (r) { t.renk[r[0]] = stil.getPropertyValue(r[1]).trim().toUpperCase(); });
    t.ad = hazir.ad;
    t.id = null;
    return t;
  }

  uygula(secim);

  var olcek = parseFloat(oku("kolaymetin.olcek") || "");
  if (olcek >= 1 && olcek <= 2) { kok.style.setProperty("--olcek", String(olcek)); }

  window.kolaymetinTema = {
    HAZIR: HAZIR, YAZILAR: YAZILAR, GOLGELER: GOLGELER, YERLESIMLER: YERLESIMLER,
    RENKLER: RENKLER, OLCULER: OLCULER, EN_COK_OZEL: EN_COK_OZEL,
    secim: function () { return secim; },
    sec: sec,
    temizle: temizle,
    ozelTemalar: ozelTemalar,
    etkinTema: etkinTema,
    kontrast: kontrast,
    /* Temayı doğrular ve kaydeder; aynı kimlikli tema varsa yerine geçer. Kaydedilen temayı,
       sınıra ulaşıldıysa ya da tarayıcı yazmaya izin vermiyorsa null döndürür. */
    ozelKaydet: function (veri) {
      var t = temizle(veri);
      if (!t) { return null; }
      var liste = ozelTemalar(), yer = -1;
      for (var i = 0; i < liste.length; i++) { if (liste[i].id === t.id) { yer = i; } }
      if (yer >= 0) { liste[yer] = t; }
      else if (liste.length >= EN_COK_OZEL) { return null; }
      else { liste.push(t); }
      return ozelleriYaz(liste) ? t : null;
    },
    ozelSil: function (id) {
      ozelleriYaz(ozelTemalar().filter(function (t) { return t.id !== id; }));
      if (secim === id) { sec("masa"); }
    },
    yeniId: yeniId
  };
})();
