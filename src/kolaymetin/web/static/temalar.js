/* Temalar paneli: hazır temalar, kendi temalarınız ve özelleştirme.
   Temayı uygulayan ve saklayan tema.js'dir (window.kolaymetinTema); bu dosya yalnızca arayüzdür.
   Hazır temalar değişmez: birinde ayar değiştirilince kopyası "Kendi temalarınız" altına kaydedilir. */
(function () {
  "use strict";

  var T = window.kolaymetinTema;
  var $ = function (id) { return document.getElementById(id); };
  var panel = $("tema-paneli"), dugme = $("tema-dugmesi");
  if (!T || !panel || !dugme) { return; }

  // Metin çiftleri; scripts/kontrast_denetle.py'deki PAIRS ile aynı eşik (4,5:1).
  var CIFTLER = [
    ["murekkep", "kagit", "Yazı / zemin"],
    ["murekkep", "kagit2", "Yazı / kart"],
    ["soluk", "kagit", "İkincil yazı / zemin"],
    ["soluk", "kagit2", "İkincil yazı / kart"],
    ["kirmizi", "kagit", "Hata / zemin"],
    ["kirmizi", "kagit2", "Hata / kart"],
    ["mavi", "kagit", "Bağlantı / zemin"],
    ["mavi", "kagit2", "Bağlantı / kart"],
    ["murekkep", "sari", "Yazı / fosforlu kalem"]
  ];
  var ESIK = 4.5;
  var EN_BUYUK_DOSYA = 64 * 1024;

  function sayi(deger, basamak) {
    return Number(deger).toLocaleString("tr-TR", { minimumFractionDigits: 0, maximumFractionDigits: basamak });
  }
  var BICIM = {
    satir: function (v) { return sayi(v, 2); },
    sikilik: function (v) { return "%" + Math.round(v * 100); },
    harf: function (v) { return sayi(v, 2) + " em"; },
    kelime: function (v) { return sayi(v, 2) + " em"; },
    yaricap: function (v) { return v + " px"; },
    cizgi: function (v) { return v + " px"; }
  };

  var taslak = null;  // Özelleştir bölümünde görünen tema

  function el(etiket, sinif, metin) {
    var e = document.createElement(etiket);
    if (sinif) { e.className = sinif; }
    if (metin !== undefined) { e.textContent = metin; }
    return e;
  }
  function durum(ileti) { $("tema-durum").textContent = ileti; }

  // ------------------------------------------------------------------ tema listesi
  /* Renk örneği. Hazır temanın renkleri style.css'teki .tema-ornek[data-tema] bloğundan,
     kullanıcı temasınınkiler örneğin kendi değişkenlerinden gelir. */
  function ornek(id, a, renk) {
    var o = el("span", "tema-ornek");
    o.setAttribute("aria-hidden", "true");
    if (renk) { T.RENKLER.forEach(function (r) { o.style.setProperty(r[1], renk[r[0]]); }); }
    else { o.setAttribute("data-tema", id); }
    o.style.borderRadius = Math.min(a.yaricap, 6) + "px";
    var yazi = el("span", "tema-ornek__yazi", "Aa");
    yazi.style.fontFamily = T.YAZILAR[a.yazi].deger;
    o.appendChild(yazi);
    ["kirmizi", "mavi", "sari"].forEach(function (r) { o.appendChild(el("span", "tema-ornek__renk--" + r)); });
    return o;
  }

  function secenek(id, ad, not, ornekEl) {
    var li = el("li");
    var etiket = el("label", "tema-secenek");
    var girdi = el("input");
    girdi.type = "radio"; girdi.name = "tema"; girdi.value = id;
    girdi.checked = T.secim() === id;
    girdi.addEventListener("change", function () {
      if (!girdi.checked) { return; }
      T.sec(id);
      doldur();
      durum(ad + " uygulandı.");
    });
    var yazilar = el("span");
    yazilar.appendChild(el("span", "tema-secenek__ad", ad));
    yazilar.appendChild(el("span", "tema-secenek__not", not));
    etiket.appendChild(girdi);
    etiket.appendChild(ornekEl);
    etiket.appendChild(yazilar);
    li.appendChild(etiket);
    return li;
  }

  function listeleriCiz() {
    var hazir = $("tema-listesi");
    hazir.textContent = "";
    hazir.appendChild(secenek("otomatik", "Sistemle aynı",
      "Bilgisayarınız açık temadaysa Düzeltmen Masası, koyu temadaysa Negatif Baskı.",
      ornek("masa", T.HAZIR[0].ayar, null)));
    T.HAZIR.forEach(function (h) { hazir.appendChild(secenek(h.id, h.ad, h.not, ornek(h.id, h.ayar, null))); });

    var ozel = $("ozel-listesi"), liste = T.ozelTemalar();
    ozel.textContent = "";
    $("ozel-bos").hidden = liste.length > 0;
    liste.forEach(function (t) {
      var li = secenek(t.id, t.ad, "Kendi temanız", ornek(t.id, t, t.renk));
      var sil = el("button", "dugme dugme--kucuk tema-sil", "Sil");
      sil.type = "button";
      sil.setAttribute("aria-label", t.ad + " temasını sil");
      sil.addEventListener("click", function () {
        if (!window.confirm("\"" + t.ad + "\" teması silinsin mi? Bu geri alınamaz.")) { return; }
        T.ozelSil(t.id);
        listeleriCiz();
        doldur();
        durum("\"" + t.ad + "\" silindi.");
        var secili = panel.querySelector("input[name=\"tema\"]:checked");
        if (secili) { secili.focus(); }
      });
      li.appendChild(sil);
      ozel.appendChild(li);
    });
  }

  // ------------------------------------------------------------------ özelleştir
  function seceneklerDoldur() {
    Array.prototype.forEach.call(panel.querySelectorAll("select[data-secenek]"), function (secim) {
      var tablo = T[secim.getAttribute("data-secenek")];
      Object.keys(tablo).forEach(function (anahtar) {
        var ad = typeof tablo[anahtar] === "string" ? tablo[anahtar] : tablo[anahtar].ad;
        secim.appendChild(new Option(ad, anahtar));
      });
    });
  }

  function olcuYaz(girdi) {
    var k = girdi.getAttribute("data-olcu");
    $(girdi.id + "-deger").textContent = BICIM[k](Number(girdi.value));
  }

  function doldur() {
    taslak = T.etkinTema();
    $("tema-ad").value = taslak.ad;
    Array.prototype.forEach.call(panel.querySelectorAll("[data-renk]"), function (g) {
      g.value = taslak.renk[g.getAttribute("data-renk")].toLowerCase();
    });
    $("tema-koyu").checked = taslak.koyu;
    $("tema-yazi").value = taslak.yazi;
    $("tema-baslik").value = taslak.baslik;
    $("tema-etiket").value = taslak.etiket;
    $("tema-golge").value = taslak.golge;
    $("tema-yerlesim").value = taslak.yerlesim;
    $("tema-sus").checked = taslak.sus;
    $("tema-hareket").checked = taslak.hareket;
    Array.prototype.forEach.call(panel.querySelectorAll("[data-olcu]"), function (g) {
      g.value = String(taslak[g.getAttribute("data-olcu")]);
      olcuYaz(g);
    });
    kontrastCiz();
  }

  function editordenOku() {
    var t = {
      id: taslak.id, ad: $("tema-ad").value, renk: {},
      koyu: $("tema-koyu").checked,
      yazi: $("tema-yazi").value, baslik: $("tema-baslik").value, etiket: $("tema-etiket").value,
      golge: $("tema-golge").value, yerlesim: $("tema-yerlesim").value,
      sus: $("tema-sus").checked, hareket: $("tema-hareket").checked
    };
    Array.prototype.forEach.call(panel.querySelectorAll("[data-renk]"), function (g) {
      t.renk[g.getAttribute("data-renk")] = g.value;
    });
    Array.prototype.forEach.call(panel.querySelectorAll("[data-olcu]"), function (g) {
      t[g.getAttribute("data-olcu")] = Number(g.value);
    });
    return t;
  }

  function degisti(olay) {
    if (olay.target.getAttribute("data-olcu")) { olcuYaz(olay.target); }
    var t = editordenOku(), yeni = !t.id;
    if (yeni) {
      // Hazır tema değişmez: kopyası oluşur.
      t.id = T.yeniId();
      var ad = t.ad.trim();
      if (!ad || ad === taslak.ad) { t.ad = taslak.ad + " (kişisel)"; }
    }
    var kayitli = T.ozelKaydet(t);
    if (!kayitli) {
      durum("Tema kaydedilemedi. En çok " + T.EN_COK_OZEL + " tema saklanabilir; tarayıcınız kaydetmeye izin vermiyor da olabilir.");
      return;
    }
    taslak = kayitli;
    T.sec(kayitli.id);
    if (yeni) {
      $("tema-ad").value = kayitli.ad;
      durum("\"" + kayitli.ad + "\" oluşturuldu. Değişiklikler bu temaya kaydediliyor.");
    }
    listeleriCiz();
    kontrastCiz();
  }

  function kontrastCiz() {
    var liste = $("kontrast-listesi"), sorun = 0, satirlar = [];
    CIFTLER.forEach(function (c) {
      var oran = T.kontrast(taslak.renk[c[0]], taslak.renk[c[1]]);
      var li = el("li");
      if (oran < ESIK) { li.className = "kontrast--yetersiz"; sorun++; }
      li.appendChild(el("span", "", c[2]));
      li.appendChild(el("span", "mono", oran.toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ":1"));
      satirlar.push(li);
    });
    liste.textContent = "";
    var ozet = el("li", sorun ? "kontrast--yetersiz" : "");
    ozet.appendChild(el("strong", "", sorun
      ? sorun + " renk çifti okunaklı değil: en az 4,5:1 olmalı."
      : "Bütün renk çiftleri 4,5:1 eşiğini geçiyor."));
    liste.appendChild(ozet);
    satirlar.forEach(function (li) { liste.appendChild(li); });
  }

  // ------------------------------------------------------------------ paylaş
  function dosyaAdi(ad) {
    var harita = { "ı": "i", "ğ": "g", "ü": "u", "ş": "s", "ö": "o", "ç": "c", "â": "a", "î": "i", "û": "u" };
    var kok = ad.toLocaleLowerCase("tr-TR").replace(/[ığüşöçâîû]/g, function (h) { return harita[h]; });
    return "kolaymetin-tema-" + (kok.replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "ozel") + ".json";
  }

  function disaAktar() {
    var t = editordenOku(), veri = {};
    ["ad", "koyu", "renk", "yazi", "baslik", "etiket", "satir", "harf", "kelime", "sikilik",
     "yaricap", "cizgi", "golge", "yerlesim", "sus", "hareket"].forEach(function (k) { veri[k] = t[k]; });
    veri.ad = (veri.ad || "").trim() || taslak.ad;
    var blob = new Blob([JSON.stringify(veri, null, 2) + "\n"], { type: "application/json" });
    var baglanti = document.createElement("a");
    baglanti.href = URL.createObjectURL(blob);
    baglanti.download = dosyaAdi(veri.ad);
    panel.appendChild(baglanti);
    baglanti.click();
    setTimeout(function () { URL.revokeObjectURL(baglanti.href); baglanti.remove(); }, 1000);
    durum("Tema indirildi: " + baglanti.download);
  }

  function iceAktar(dosya) {
    if (dosya.size > EN_BUYUK_DOSYA) { durum("Dosya çok büyük. Tema dosyası en çok 64 KB olabilir."); return; }
    dosya.text().then(function (metin) {
      var veri = JSON.parse(metin), liste = Array.isArray(veri) ? veri : [veri], son = null, sayac = 0;
      liste.slice(0, T.EN_COK_OZEL).forEach(function (v) {
        if (!v || typeof v !== "object") { return; }
        var kopya = JSON.parse(JSON.stringify(v));
        kopya.id = T.yeniId();  // var olan bir temanın üzerine yazılmasın
        var kayitli = T.ozelKaydet(kopya);
        if (kayitli) { son = kayitli; sayac++; }
      });
      if (!son) {
        durum("Dosyada geçerli bir tema bulunamadı. Yedi rengin hepsi #RRGGBB biçiminde olmalı.");
        return;
      }
      T.sec(son.id);
      listeleriCiz();
      doldur();
      durum(sayac === 1 ? "\"" + son.ad + "\" içe aktarıldı ve uygulandı." : sayac + " tema içe aktarıldı.");
    }).catch(function () {
      durum("Dosya okunamadı. kolaymetin'den dışa aktarılmış bir .json dosyası seçin.");
    });
  }

  // ------------------------------------------------------------------ olaylar
  function ac() {
    listeleriCiz();
    doldur();
    durum("");
    if (typeof panel.showModal === "function") { panel.showModal(); } else { panel.setAttribute("open", ""); }
    var secili = panel.querySelector("input[name=\"tema\"]:checked");
    if (secili) { secili.focus(); }
  }
  function kapat() {
    if (typeof panel.close === "function") { panel.close(); } else { panel.removeAttribute("open"); dugme.focus(); }
  }

  seceneklerDoldur();
  dugme.addEventListener("click", ac);
  $("tema-kapat").addEventListener("click", kapat);
  panel.addEventListener("close", function () { dugme.focus(); });
  // Panelin dışına (karartılmış alana) tıklayınca kapanır.
  panel.addEventListener("click", function (olay) {
    var kutu = panel.getBoundingClientRect();
    if (olay.target === panel && (olay.clientX < kutu.left || olay.clientX > kutu.right ||
        olay.clientY < kutu.top || olay.clientY > kutu.bottom)) { kapat(); }
  });

  Array.prototype.forEach.call(panel.querySelectorAll("[data-renk], [data-olcu]"), function (g) {
    g.addEventListener("input", degisti);
  });
  ["tema-koyu", "tema-yazi", "tema-baslik", "tema-etiket", "tema-golge", "tema-yerlesim", "tema-sus", "tema-hareket"]
    .forEach(function (id) { $(id).addEventListener("change", degisti); });
  $("tema-ad").addEventListener("change", degisti);

  $("tema-disa").addEventListener("click", disaAktar);
  $("tema-ice").addEventListener("click", function () { $("tema-dosya").click(); });
  $("tema-dosya").addEventListener("change", function () {
    var dosya = this.files && this.files[0];
    this.value = "";
    if (dosya) { iceAktar(dosya); }
  });
  $("tema-sifirla").addEventListener("click", function () {
    T.sec("otomatik");
    listeleriCiz();
    doldur();
    durum("Varsayılan temaya dönüldü. Kendi temalarınız silinmedi.");
  });
})();
