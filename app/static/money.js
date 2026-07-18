/**
 * Format input nominal: 6600000 → 6,600,000
 * parse_money di server sudah menerima koma/titik.
 */
(function () {
  function digitsOnly(s) {
    return String(s || "").replace(/[^\d]/g, "");
  }

  function formatGrouped(digits) {
    if (!digits) return "";
    // hilangkan leading zero berlebih, tapi izinkan "0"
    digits = digits.replace(/^0+(?=\d)/, "");
    return digits.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  }

  function formatEl(el) {
    if (!el || el.dataset.moneySkip === "1") return;
    var raw = digitsOnly(el.value);
    var caretEnd = el.selectionStart === el.value.length;
    el.value = formatGrouped(raw);
    if (caretEnd && typeof el.setSelectionRange === "function") {
      try {
        var n = el.value.length;
        el.setSelectionRange(n, n);
      } catch (e) {}
    }
  }

  function isMoneyField(el) {
    if (!el || el.tagName !== "INPUT") return false;
    if (el.classList.contains("js-money")) return true;
    if (el.classList.contains("js-cost")) return true;
    var name = (el.getAttribute("name") || "").toLowerCase();
    if (/price|amount|capital|cost_amount|charger/.test(name)) {
      // jangan format IMEI / battery / percent
      if (/imei|battery|percent|qty|share|phone|hp/.test(name)) return false;
      if (el.getAttribute("inputmode") === "numeric" || el.type === "text" || !el.type) {
        // skip pure qty fields
        if (name === "qty" || name.indexOf("qty") === 0) return false;
        return true;
      }
    }
    return false;
  }

  function bind(el) {
    if (!el || el.dataset.moneyBound === "1") return;
    if (!isMoneyField(el)) return;
    el.dataset.moneyBound = "1";
    el.classList.add("js-money");
    el.setAttribute("inputmode", "numeric");
    el.setAttribute("autocomplete", "off");
    if (!el.placeholder || /^\d+$/.test(el.placeholder)) {
      var ph = digitsOnly(el.placeholder || "");
      if (ph) el.placeholder = formatGrouped(ph);
      else if (!el.placeholder) el.placeholder = "6,600,000";
    }
    // format nilai awal
    if (el.value) formatEl(el);

    el.addEventListener("input", function () {
      formatEl(el);
    });
    el.addEventListener("blur", function () {
      formatEl(el);
    });
    el.addEventListener("paste", function () {
      setTimeout(function () {
        formatEl(el);
      }, 0);
    });
  }

  function scan(root) {
    (root || document).querySelectorAll("input").forEach(bind);
  }

  document.addEventListener("DOMContentLoaded", function () {
    scan(document);
    // baris biaya / dinamis
    document.addEventListener(
      "focusin",
      function (e) {
        if (e.target && e.target.tagName === "INPUT") bind(e.target);
      },
      true
    );
  });

  // expose
  window.LeksMoney = {
    format: formatGrouped,
    digits: digitsOnly,
    bind: bind,
    scan: scan,
  };
})();
