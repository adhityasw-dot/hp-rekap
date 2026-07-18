/**
 * Leks Phone — motion UX (non-blocking)
 * Hover/press feedback only. Reveal pakai CSS agar konten tidak hilang.
 */
(function () {
  if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    return;
  }

  document.addEventListener(
    "pointerdown",
    function (e) {
      var btn = e.target.closest && e.target.closest(".btn");
      if (!btn) return;
      btn.classList.add("btn-press");
      setTimeout(function () {
        btn.classList.remove("btn-press");
      }, 280);
    },
    true
  );

  document.addEventListener("DOMContentLoaded", function () {
    document.body.classList.add("motion-on");
  });
})();
