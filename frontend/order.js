/* საჯარო შესაკვეთი ფორმა — კლიენტი ავსებს, ავტორიზაცია არ სჭირდება */
(function () {
  "use strict";
  var cfg = window.APP_CONFIG;
  var API = cfg.API_BASE;
  var H = { "ngrok-skip-browser-warning": "1" };

  var shopId = new URLSearchParams(location.search).get("shop");
  var products = [];
  var currency = "GEL";

  function $(id) { return document.getElementById(id); }

  function toast(msg, isErr) {
    var t = $("toast");
    t.textContent = msg;
    t.className = "toast " + (isErr ? "toast-err" : "toast-ok");
    setTimeout(function () { t.classList.add("hidden"); }, 3500);
  }

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function recalcTotal() {
    var total = 0;
    products.forEach(function (p) {
      var qty = parseInt(($("qty-" + p.id) || {}).value, 10) || 0;
      total += (Number(p.price) || 0) * qty;
    });
    $("total").textContent = total.toFixed(2);
  }

  function renderProducts() {
    var list = $("product-list");
    list.innerHTML = "";
    if (!products.length) {
      $("empty-products").classList.remove("hidden");
      return;
    }
    products.forEach(function (p) {
      var row = document.createElement("div");
      row.className = "product-item";
      row.dataset.search = (p.name + " " + (p.description || "")).toLowerCase();
      row.innerHTML =
        '<div class="product-info"><div class="product-name">' + esc(p.name) + "</div>" +
        '<div class="product-meta">' + Number(p.price).toFixed(2) + " " + currency +
        (p.description ? " · " + esc(p.description) : "") + "</div></div>";
      var qtyWrap = document.createElement("div");
      qtyWrap.className = "product-actions";
      qtyWrap.innerHTML =
        '<input type="number" min="0" value="0" id="qty-' + p.id + '" ' +
        'style="width:80px" aria-label="რაოდენობა" />';
      row.appendChild(qtyWrap);
      list.appendChild(row);
      qtyWrap.querySelector("input").addEventListener("input", recalcTotal);
    });
  }

  // ძებნა — ვმალავთ/ვაჩვენებთ მწკრივებს (რაოდენობა არ იკარგება)
  var searchEl = $("product-search");
  if (searchEl) {
    searchEl.addEventListener("input", function () {
      var q = this.value.trim().toLowerCase();
      var rows = document.querySelectorAll("#product-list .product-item");
      var visible = 0;
      rows.forEach(function (row) {
        var match = !q || (row.dataset.search || "").indexOf(q) >= 0;
        row.style.display = match ? "" : "none";
        if (match) visible++;
      });
      var noMatch = $("no-match");
      if (noMatch) noMatch.classList.toggle("hidden", !(rows.length && visible === 0));
    });
  }

  async function loadMenu() {
    if (!shopId) {
      $("shop-name").textContent = "არასწორი ლინკი (მაღაზია არ არის მითითებული)";
      return;
    }
    try {
      var res = await fetch(API + "/public-menu?shop_id=" + encodeURIComponent(shopId), { headers: H });
      if (!res.ok) throw new Error("მაღაზია ვერ მოიძებნა");
      var data = await res.json();
      currency = (data.shop && data.shop.currency) || "GEL";
      $("shop-name").textContent = "🛍️ " + (data.shop ? data.shop.name : "მაღაზია");
      document.title = "შეკვეთა — " + (data.shop ? data.shop.name : "");
      products = data.products || [];
      renderProducts();
      recalcTotal();
    } catch (e) {
      $("shop-name").textContent = "ვერ ჩაიტვირთა";
      toast(e.message, true);
    }
  }

  $("order-form").addEventListener("submit", async function (e) {
    e.preventDefault();
    var items = [];
    products.forEach(function (p) {
      var qty = parseInt($("qty-" + p.id).value, 10) || 0;
      if (qty > 0) {
        items.push({ product_id: p.id, name: p.name, price: Number(p.price) || 0, quantity: qty });
      }
    });
    if (!items.length) return toast("აირჩიე მინიმუმ ერთი პროდუქტი (რაოდენობა > 0)", true);

    var payload = {
      shop_id: shopId,
      customer_name: $("c-name").value.trim(),
      customer_phone: $("c-phone").value.trim(),
      customer_address: $("c-address").value.trim(),
      note: $("c-note").value.trim() || null,
      items: items,
    };
    var btn = $("submit-btn");
    btn.disabled = true;
    btn.textContent = "იგზავნება...";
    try {
      var res = await fetch(API + "/orders", {
        method: "POST",
        headers: { "Content-Type": "application/json", "ngrok-skip-browser-warning": "1" },
        body: JSON.stringify(payload),
      });
      var data = await res.json().catch(function () { return null; });
      if (!res.ok) {
        var d = data && data.detail ? data.detail : "შეცდომა (HTTP " + res.status + ")";
        throw new Error(typeof d === "string" ? d : JSON.stringify(d));
      }
      $("order-form").classList.add("hidden");
      $("success").classList.remove("hidden");
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (err) {
      toast(err.message, true);
      btn.disabled = false;
      btn.textContent = "შეკვეთის გაგზავნა";
    }
  });

  loadMenu();
})();
