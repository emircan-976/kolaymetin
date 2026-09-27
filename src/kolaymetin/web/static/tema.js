/* Tema ve yazı boyutu tercihini sayfa çizilmeden önce uygular.
   Tercihler yalnızca bu tarayıcıda saklanır (localStorage); erişilemezse varsayılan kullanılır. */
(function () {
  "use strict";
  var root = document.documentElement;
  function oku(anahtar) {
    try { return window.localStorage.getItem(anahtar); } catch (e) { return null; }
  }
  var tema = oku("kolaymetin.tema");
  if (tema === "dark" || tema === "light") { root.setAttribute("data-theme", tema); }
  var olcek = parseFloat(oku("kolaymetin.olcek") || "");
  if (olcek >= 1 && olcek <= 2) { root.style.setProperty("--olcek", String(olcek)); }
})();
