/* Künye manzarası: dither'lı tepeler.
   Yöntem "Voxel Space" (Comanche, 1992): yükseklik haritası bir kez üretilir; her karede ekran
   sütunları önden arkaya taranır, görünen her parçanın tonu Bayer 8×8 eşiğiyle 1-bit'e çevrilir.
   Yakın arazi düzleştirilir, uzaktakiler tam yükseklikte kalır: önde düz ova, ufukta sıradağlar.
   Yatay ölçek dikey ölçeğe bağlıdır: geniş ekran daha geniş bir panorama görür, tepeler sıkışmaz.
   Uzak tepeler mavi kalıpla, yakınlar mürekkeple basılır; gökyüzü saydam kâğıttır (arkadaki güneş görünür).
   Renkler CSS değişkenlerinden okunur. Hareketi azalt tercihinde tek kare çizilir. Süstür, metin içermez. */
(function () {
  "use strict";
  var tuval = document.getElementById("manzara");
  if (!tuval || !tuval.getContext) { return; }
  var ctx = tuval.getContext("2d");
  if (!ctx) { return; }

  var BOYUT = 512, MASKE = BOYUT - 1;
  var YUKSEK = 190;        // haritadaki en yüksek tepe
  var IRTIFA = 18;         // kameranın yüksekliği
  var UZAK = 720;          // görüş uzaklığı
  var YATAY = 4.3;         // tepeler yatayda kaç kat geniş çizilir (panorama)
  var PIKSEL = 2;          // bir dither pikseli kaç CSS pikseli
  var KARE_MS = 90;        // yaklaşık 11 kare/sn: basamaklı, sakin hareket

  var yukseklik = new Float32Array(BOYUT * BOYUT);
  var isik = new Float32Array(BOYUT * BOYUT);

  // ---------------------------------------------------------------- Bayer 8×8 eşikleri
  function bayer(n) {
    if (n === 1) { return [[0]]; }
    var yarim = bayer(n / 2), s = n / 2, m = [], r, c;
    for (r = 0; r < n; r++) { m.push(new Array(n)); }
    for (r = 0; r < s; r++) {
      for (c = 0; c < s; c++) {
        var v = yarim[r][c] * 4;
        m[r][c] = v; m[r][c + s] = v + 2; m[r + s][c] = v + 3; m[r + s][c + s] = v + 1;
      }
    }
    return m;
  }
  var ESIK = new Float32Array(64);
  (function () {
    var m = bayer(8);
    for (var r = 0; r < 8; r++) { for (var c = 0; c < 8; c++) { ESIK[r * 8 + c] = (m[r][c] + 0.5) / 64; } }
  })();

  // ---------------------------------------------------------------- yükseklik haritası (döşenebilir değer gürültüsü)
  function karma(x, y) {
    var h = (Math.imul(x, 374761393) + Math.imul(y, 668265263)) | 0;
    h = Math.imul(h ^ (h >>> 13), 1274126177);
    return ((h ^ (h >>> 16)) >>> 0) / 4294967296;
  }
  function yumusat(t) { return t * t * (3 - 2 * t); }
  function gurultu(x, y, donem) {
    var hucre = BOYUT / donem, gx = x / hucre, gy = y / hucre;
    var x0 = Math.floor(gx), y0 = Math.floor(gy), fx = yumusat(gx - x0), fy = yumusat(gy - y0);
    var xa = x0 % donem, xb = (x0 + 1) % donem, ya = y0 % donem, yb = (y0 + 1) % donem;
    var a = karma(xa, ya), b = karma(xb, ya), c = karma(xa, yb), d = karma(xb, yb);
    return (a + (b - a) * fx) + ((c + (d - c) * fx) - (a + (b - a) * fx)) * fy;
  }
  (function haritaUret() {
    var enAz = Infinity, enCok = -Infinity, i, x, y;
    for (y = 0; y < BOYUT; y++) {
      for (x = 0; x < BOYUT; x++) {
        var v = 0, genlik = 0.6, donem = 4;
        for (var o = 0; o < 3; o++) { v += gurultu(x, y, donem) * genlik; genlik *= 0.55; donem *= 2; }
        yukseklik[y * BOYUT + x] = v;
        if (v < enAz) { enAz = v; }
        if (v > enCok) { enCok = v; }
      }
    }
    for (i = 0; i < yukseklik.length; i++) {
      var n = (yukseklik[i] - enAz) / (enCok - enAz);
      yukseklik[i] = Math.pow(n, 2.1);
    }
    // Işık: sol önden, yüksek. Eğim ışığa döndükçe açık (kâğıt), uzaklaştıkça koyu (mürekkep).
    var lx = -0.55, ly = 0.35, lz = 0.76;
    for (y = 0; y < BOYUT; y++) {
      for (x = 0; x < BOYUT; x++) {
        var dx = (yukseklik[y * BOYUT + ((x + 2) & MASKE)] - yukseklik[y * BOYUT + ((x - 2) & MASKE)]) * YUKSEK * 0.25;
        var dy = (yukseklik[((y + 2) & MASKE) * BOYUT + x] - yukseklik[((y - 2) & MASKE) * BOYUT + x]) * YUKSEK * 0.25;
        var nz = 1 / Math.sqrt(dx * dx + dy * dy + 1);
        var d = (-dx * lx - dy * ly + lz) * nz;
        isik[y * BOYUT + x] = d < 0 ? 0 : d;
      }
    }
  })();

  // ---------------------------------------------------------------- renkler
  var kok = document.documentElement;
  function renk(ad) {
    var s = getComputedStyle(kok).getPropertyValue(ad).trim();
    var n = parseInt(s.slice(1), 16);
    if (s.charAt(0) !== "#" || s.length !== 7 || isNaN(n)) { return 0; }
    return ((255 << 24) | ((n & 255) << 16) | (n & 0xff00) | ((n >> 16) & 255)) >>> 0;
  }

  // ---------------------------------------------------------------- çizim
  var goruntu = null, pikseller = null, ybuf = null, zbuf = null;
  var kamX = 180, kamY = 0;

  function boyutla() {
    var kutu = tuval.getBoundingClientRect();
    var g = Math.max(1, Math.round(kutu.width / PIKSEL)), y = Math.max(1, Math.round(kutu.height / PIKSEL));
    if (g === tuval.width && y === tuval.height && goruntu) { return; }
    tuval.width = g; tuval.height = y;
    goruntu = ctx.createImageData(g, y);
    pikseller = new Uint32Array(goruntu.data.buffer);
    ybuf = new Int32Array(g);
    zbuf = new Float32Array(g);
  }

  function aralik(a, b, t) {
    var v = (t - a) / (b - a);
    return v <= 0 ? 0 : v >= 1 ? 1 : v * v * (3 - 2 * v);
  }

  function ciz() {
    if (!goruntu) { return; }
    var G = tuval.width, Y = tuval.height;
    var kagit = renk("--kagit"), murekkep = renk("--murekkep"), mavi = renk("--mavi");
    var ufuk = Y * 0.66, olcek = Y * 1.35;
    var i, y, z, dz;
    pikseller.fill(0);
    ybuf.fill(Y);
    zbuf.fill(0);
    for (z = 3, dz = 0.35; z < UZAK; z += dz, dz += 0.01) {
      var zo = z / UZAK;
      var duz = 0.03 + 0.97 * aralik(0.05, 0.85, zo);  // yakın arazi düz, uzak tam yükseklik
      var sis = aralik(0.45, 1, zo) * 0.55;              // uzaklık sisi: ton kâğıda yaklaşır
      var maviOran = aralik(0.2, 0.7, zo);
      var adim = z / (olcek * YATAY), sol = kamX - adim * G / 2;
      var my = (Math.floor(kamY - z) & MASKE) * BOYUT;
      var iz = 1 / z;
      for (i = 0; i < G; i++) {
        var idx = my + (Math.floor(sol + adim * i) & MASKE);
        var ys = ((IRTIFA - yukseklik[idx] * YUKSEK * duz) * iz * olcek + ufuk) | 0;
        if (ys < 0) { ys = 0; }
        var alt = ybuf[i];
        if (ys >= alt) { continue; }
        var ton = 0.12 + 0.88 * isik[idx];
        ton = ton * (1 - sis) + 0.9 * sis;
        for (y = ys; y < alt; y++) {
          var e = ESIK[((y & 7) << 3) | (i & 7)];
          var p;
          if (ton < e) {
            p = maviOran > ESIK[(((y + 3) & 7) << 3) | ((i + 5) & 7)] ? mavi : murekkep;
          } else {
            p = kagit;
          }
          pikseller[y * G + i] = p;
        }
        // Kontur: arkadaki tepe öndekinin üstünden belirgin biçimde görünmeye başlıyorsa üst kenarı çiz.
        if (z - zbuf[i] > z * 0.2 && alt < Y) {
          pikseller[alt * G + i] = zbuf[i] / UZAK > 0.45 ? mavi : murekkep;
        }
        zbuf[i] = z;
        ybuf[i] = ys;
      }
    }
    // Gök çizgisi: en arkadaki silüetin üst kenarı.
    for (i = 0; i < G; i++) {
      if (ybuf[i] > 0 && ybuf[i] < Y) { pikseller[ybuf[i] * G + i] = zbuf[i] / UZAK > 0.45 ? mavi : murekkep; }
    }
    ctx.putImageData(goruntu, 0, 0);
  }

  // ---------------------------------------------------------------- hareket
  var hareketsiz = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : { matches: false };
  var gorunur = true, istek = 0, son = 0;

  function kare(t) {
    istek = 0;
    if (t - son >= KARE_MS) {
      son = t;
      kamY -= 1.1;
      kamX = 180 + Math.sin(kamY * 0.006) * 60;
      ciz();
    }
    planla();
  }
  function planla() {
    if (!istek && gorunur && !document.hidden && !hareketsiz.matches) { istek = window.requestAnimationFrame(kare); }
  }
  function yenidenCiz() { boyutla(); ciz(); }

  yenidenCiz();
  planla();

  if (window.ResizeObserver) { new ResizeObserver(yenidenCiz).observe(tuval); }
  else { window.addEventListener("resize", yenidenCiz); }
  if (window.IntersectionObserver) {
    new IntersectionObserver(function (girdiler) {
      gorunur = girdiler[girdiler.length - 1].isIntersecting;
      planla();
    }).observe(tuval);
  }
  document.addEventListener("visibilitychange", planla);
  if (hareketsiz.addEventListener) { hareketsiz.addEventListener("change", function () { ciz(); planla(); }); }
  // Tema değişince (düğme ya da sistem tercihi) renkleri yeniden oku.
  new MutationObserver(ciz).observe(kok, { attributes: true, attributeFilter: ["data-theme"] });
  if (window.matchMedia) {
    var koyu = window.matchMedia("(prefers-color-scheme: dark)");
    if (koyu.addEventListener) { koyu.addEventListener("change", ciz); }
  }
})();
