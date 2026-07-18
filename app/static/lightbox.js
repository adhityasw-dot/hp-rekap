/**
 * Lightbox foto — buka di overlay (tanpa tab baru).
 * Prev/next, tutup: X, klik luar, Escape, swipe.
 */
(function () {
  var overlay = null;
  var imgEl = null;
  var capEl = null;
  var counterEl = null;
  var items = [];
  var index = 0;
  var touchX = null;

  function ensureDom() {
    if (overlay) return;
    overlay = document.createElement("div");
    overlay.id = "lightbox";
    overlay.className = "lightbox";
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");
    overlay.hidden = true;
    overlay.innerHTML =
      '<button type="button" class="lightbox-close" aria-label="Tutup">&times;</button>' +
      '<button type="button" class="lightbox-nav lightbox-prev" aria-label="Sebelumnya">&#10094;</button>' +
      '<button type="button" class="lightbox-nav lightbox-next" aria-label="Berikutnya">&#10095;</button>' +
      '<div class="lightbox-stage">' +
      '  <img class="lightbox-img" alt="" />' +
      '  <div class="lightbox-meta">' +
      '    <span class="lightbox-cap"></span>' +
      '    <span class="lightbox-counter"></span>' +
      "  </div>" +
      "</div>";
    document.body.appendChild(overlay);
    imgEl = overlay.querySelector(".lightbox-img");
    capEl = overlay.querySelector(".lightbox-cap");
    counterEl = overlay.querySelector(".lightbox-counter");

    overlay.querySelector(".lightbox-close").addEventListener("click", close);
    overlay.querySelector(".lightbox-prev").addEventListener("click", function (e) {
      e.stopPropagation();
      show(index - 1);
    });
    overlay.querySelector(".lightbox-next").addEventListener("click", function (e) {
      e.stopPropagation();
      show(index + 1);
    });
    overlay.addEventListener("click", function (e) {
      if (e.target === overlay || e.target.classList.contains("lightbox-stage")) close();
    });
    imgEl.addEventListener("click", function (e) {
      e.stopPropagation();
    });

    overlay.addEventListener(
      "touchstart",
      function (e) {
        if (e.changedTouches && e.changedTouches[0]) touchX = e.changedTouches[0].clientX;
      },
      { passive: true }
    );
    overlay.addEventListener(
      "touchend",
      function (e) {
        if (touchX == null || !e.changedTouches || !e.changedTouches[0]) return;
        var dx = e.changedTouches[0].clientX - touchX;
        touchX = null;
        if (Math.abs(dx) < 50) return;
        if (dx < 0) show(index + 1);
        else show(index - 1);
      },
      { passive: true }
    );
  }

  function collectFrom(anchor) {
    var gallery = anchor.closest(".photo-gallery");
    var list = [];
    var nodes = gallery
      ? gallery.querySelectorAll("a.photo-thumb, a.lightbox-trigger")
      : [anchor];
    nodes.forEach(function (a) {
      var full = a.getAttribute("data-full") || a.getAttribute("href") || "";
      if (!full || full === "#") return;
      var cap = "";
      var capNode = a.querySelector(".photo-cap");
      if (capNode) cap = capNode.textContent.trim();
      else cap = a.getAttribute("data-caption") || a.getAttribute("title") || "";
      list.push({ url: full, caption: cap });
    });
    return list;
  }

  function show(i) {
    if (!items.length) return;
    index = (i + items.length) % items.length;
    var it = items[index];
    imgEl.src = it.url;
    imgEl.alt = it.caption || "Foto";
    capEl.textContent = it.caption || "";
    counterEl.textContent = items.length > 1 ? index + 1 + " / " + items.length : "";
    var prev = overlay.querySelector(".lightbox-prev");
    var next = overlay.querySelector(".lightbox-next");
    var multi = items.length > 1;
    prev.hidden = !multi;
    next.hidden = !multi;
  }

  function open(anchor) {
    ensureDom();
    items = collectFrom(anchor);
    if (!items.length) return;
    var full = anchor.getAttribute("data-full") || anchor.getAttribute("href") || "";
    index = 0;
    for (var i = 0; i < items.length; i++) {
      if (items[i].url === full) {
        index = i;
        break;
      }
    }
    show(index);
    overlay.hidden = false;
    document.body.classList.add("lightbox-open");
    requestAnimationFrame(function () {
      overlay.classList.add("is-open");
    });
  }

  function close() {
    if (!overlay) return;
    overlay.classList.remove("is-open");
    document.body.classList.remove("lightbox-open");
    setTimeout(function () {
      if (overlay) {
        overlay.hidden = true;
        if (imgEl) imgEl.removeAttribute("src");
      }
    }, 200);
  }

  document.addEventListener("click", function (e) {
    var a = e.target.closest && e.target.closest("a.photo-thumb, a.lightbox-trigger");
    if (!a) return;
    var full = a.getAttribute("data-full") || a.getAttribute("href");
    if (!full || full.indexOf("http") === 0 && full.indexOf(location.host) === -1 && full.indexOf("/media/") === -1) {
      // external non-media: biarkan default
      if (full && full.indexOf("/media/") === -1 && !a.classList.contains("photo-thumb")) return;
    }
    if (!full) return;
    // hanya foto internal / data-full
    if (a.classList.contains("photo-thumb") || a.classList.contains("lightbox-trigger")) {
      e.preventDefault();
      open(a);
    }
  });

  document.addEventListener("keydown", function (e) {
    if (!overlay || overlay.hidden) return;
    if (e.key === "Escape") close();
    if (e.key === "ArrowLeft") show(index - 1);
    if (e.key === "ArrowRight") show(index + 1);
  });

  window.LeksLightbox = { open: open, close: close };
})();
