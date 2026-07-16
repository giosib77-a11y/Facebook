/* ადმინ პანელი — SaaS მფლობელისთვის. მხოლოდ ADMIN_EMAIL-ს უშვებს backend. */
(function () {
  "use strict";
  var cfg = window.APP_CONFIG;
  var API = cfg.API_BASE;

  var sb = supabase.createClient(cfg.SUPABASE_URL, cfg.SUPABASE_ANON_KEY, {
    auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: false },
  });

  var shops = [], sellers = [], orders = [], requests = [], growth = [];
  var STATUS = { new: "ახალი", processing: "მუშავდება", done: "დასრულებული", cancelled: "გაუქმებული" };
  var TIERS = [["free", "უფასო"], ["basic", "საბაზისო"], ["standard", "სტანდარტი"], ["business", "ბიზნესი"]];
  var TIER_CUST = { free: 30, basic: 200, standard: 800, business: 3000 };

  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function toast(msg, isErr) {
    var t = $("toast");
    t.textContent = msg;
    t.className = "toast " + (isErr ? "toast-err" : "toast-ok");
    setTimeout(function () { t.classList.add("hidden"); }, 3500);
  }
  function fmtDate(s) { try { return s ? new Date(s).toLocaleDateString("ka-GE") : "—"; } catch (e) { return "—"; } }

  function readStoredToken() {
    for (var i = 0; i < localStorage.length; i++) {
      var k = localStorage.key(i);
      if (k && k.indexOf("sb-") === 0 && k.indexOf("auth-token") >= 0) {
        try {
          var s = JSON.parse(localStorage.getItem(k));
          return s.access_token || (s.currentSession && s.currentSession.access_token) || null;
        } catch (e) {}
      }
    }
    return null;
  }

  async function req(method, path, body) {
    var token = readStoredToken();
    if (!token) { location.href = "index.html"; throw new Error("no session"); }
    var opts = { method: method, headers: { Authorization: "Bearer " + token, "ngrok-skip-browser-warning": "1" } };
    if (body !== undefined) { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
    var res = await fetch(API + path, opts);
    if (res.status === 401) { location.href = "index.html"; throw new Error("401"); }
    if (res.status === 403) { throw { forbidden: true }; }
    if (res.status === 204) return null;
    var data = await res.json().catch(function () { return null; });
    if (!res.ok) throw new Error((data && data.detail) || "HTTP " + res.status);
    return data;
  }
  var api = function (p) { return req("GET", p); };

  /* ---------- საერთო ---------- */
  function statCard(val, lbl) {
    return '<div class="stat"><div class="val">' + val + '</div><div class="lbl">' + lbl + "</div></div>";
  }
  function renderStats(o) {
    $("stats").innerHTML =
      '<div class="stat mrr"><div class="val">' + (o.mrr || 0) + ' ₾</div><div class="lbl">MRR · თვიური შემოსავალი</div></div>' +
      statCard(o.total_shops, "მაღაზია") +
      statCard(o.total_sellers, "გამყიდველი") +
      statCard(o.connected_shops, "Facebook-დაკავშ.") +
      statCard(o.total_products, "პროდუქტი") +
      statCard(o.total_orders, "შეკვეთა (სულ)") +
      statCard(o.orders_30d, "შეკვეთა (30 დღე)") +
      statCard(o.revenue + " ₾", "ბრუნვა (გაუქმ. გარეშე)") +
      statCard(o.total_shops ? (o.total_orders / o.total_shops).toFixed(1) : 0, "საშ. შეკვეთა/მაღაზია");
  }

  /* ---------- მაღაზიები ---------- */
  function renderShops() {
    var q = ($("shop-search").value || "").trim().toLowerCase();
    var list = shops.filter(function (s) {
      return !q || (s.name || "").toLowerCase().indexOf(q) >= 0 || (s.owner_email || "").toLowerCase().indexOf(q) >= 0;
    });
    $("shop-count").textContent = list.length;
    $("shops-empty").classList.toggle("hidden", list.length > 0);
    $("shops-body").innerHTML = list.map(function (s) {
      var botPill = s.bot_enabled ? '<span class="pill pill-on">ჩართ.</span>' : '<span class="pill pill-off">გამორთ.</span>';
      var fbPill = s.fb_connected ? '<span class="pill pill-on">კი</span>' : '<span class="pill pill-off">არა</span>';
      var toggleLbl = s.bot_enabled ? "გამორთვა" : "ჩართვა";
      var tierSel = '<select class="tier-sel" data-tier="' + s.id + '">' +
        TIERS.map(function (t) {
          return '<option value="' + t[0] + '"' + (s.tier === t[0] ? " selected" : "") + ">" + t[1] + "</option>";
        }).join("") + "</select>";
      var over = s.customer_limit && s.monthly_customers > s.customer_limit;
      var usage = '<span' + (over ? ' style="color:var(--danger);font-weight:600"' : "") + ">" +
        s.monthly_customers + " / " + s.customer_limit + "</span>";
      return "<tr>" +
        "<td><b>" + esc(s.name) + "</b></td>" +
        "<td>" + esc(s.owner_email || "—") + "</td>" +
        "<td>" + tierSel + "</td>" +
        "<td>" + usage + "</td>" +
        "<td>" + s.products + "</td><td>" + s.orders + "</td>" +
        "<td>" + fbPill + "</td><td>" + botPill + "</td>" +
        "<td>" + fmtDate(s.created_at) + "</td>" +
        '<td><div class="row-actions">' +
          '<button class="icon-btn" data-detail="' + s.id + '">👁</button>' +
          '<button class="icon-btn" data-toggle="' + s.id + '">' + toggleLbl + "</button>" +
          '<button class="icon-btn danger" data-del="' + s.id + '">🗑</button>' +
        "</div></td>" +
      "</tr>";
    }).join("");
  }

  /* ---------- გამყიდვლები ---------- */
  function renderSellers() {
    var q = ($("seller-search").value || "").trim().toLowerCase();
    var list = sellers.filter(function (u) { return !q || (u.email || "").toLowerCase().indexOf(q) >= 0; });
    $("seller-count").textContent = list.length;
    $("sellers-empty").classList.toggle("hidden", list.length > 0);
    $("sellers-body").innerHTML = list.map(function (u) {
      var conf = u.confirmed ? '<span class="pill pill-on">კი</span>' : '<span class="pill pill-off">არა</span>';
      return "<tr>" +
        "<td><b>" + esc(u.email || "—") + "</b></td>" +
        "<td>" + conf + "</td><td>" + u.shops + "</td>" +
        "<td>" + fmtDate(u.last_sign_in) + "</td><td>" + fmtDate(u.created_at) + "</td>" +
        '<td><button class="icon-btn" data-recovery="' + esc(u.email || "") + '">🔑 პაროლი</button></td>' +
      "</tr>";
    }).join("");
  }

  /* ---------- შეკვეთები ---------- */
  function renderOrders() {
    var q = ($("order-search").value || "").trim().toLowerCase();
    var list = orders.filter(function (o) {
      if (!q) return true;
      var hay = (o.shop_name || "") + " " + (o.customer_name || "") + " " + (STATUS[o.status] || o.status || "");
      return hay.toLowerCase().indexOf(q) >= 0;
    });
    $("order-count").textContent = list.length;
    $("orders-empty").classList.toggle("hidden", list.length > 0);
    $("orders-body").innerHTML = list.map(function (o) {
      return "<tr>" +
        "<td>" + esc(o.shop_name || "—") + "</td>" +
        "<td>" + esc(o.customer_name || "—") + "</td>" +
        "<td>" + Number(o.total || 0).toFixed(2) + " ₾</td>" +
        "<td>" + esc(STATUS[o.status] || o.status) + "</td>" +
        "<td>" + fmtDate(o.created_at) + "</td>" +
      "</tr>";
    }).join("");
  }

  /* ---------- ზრდის გრაფიკი ---------- */
  function renderGrowth() {
    var max = 1;
    growth.forEach(function (g) { max = Math.max(max, g.orders, g.shops); });
    $("growth-chart").innerHTML = growth.map(function (g) {
      var oh = Math.round((g.orders / max) * 100);
      var sh = Math.round((g.shops / max) * 100);
      return '<div class="chart-col"><div class="chart-bars">' +
        '<span class="bar orders" style="height:' + oh + '%" title="შეკვეთა: ' + g.orders + '"></span>' +
        '<span class="bar shops" style="height:' + sh + '%" title="მაღაზია: ' + g.shops + '"></span>' +
        '</div><div class="chart-lbl">' + esc(g.ym.slice(5)) + "</div></div>";
    }).join("");
  }

  /* ---------- CSV ექსპორტი ---------- */
  function toCSV(headers, rows) {
    function cell(v) {
      v = v == null ? "" : String(v);
      return /[",\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v;
    }
    var lines = [headers.map(cell).join(",")];
    rows.forEach(function (r) { lines.push(r.map(cell).join(",")); });
    return "﻿" + lines.join("\r\n"); // BOM — Excel-ში ქართული სწორად
  }
  function downloadCSV(name, content) {
    var blob = new Blob([content], { type: "text/csv;charset=utf-8" });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = name;
    a.click();
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 1000);
  }

  /* ---------- პაკეტის მოთხოვნები ---------- */
  function tierLabel(t) { var f = TIERS.filter(function (x) { return x[0] === t; })[0]; return f ? f[1] : t; }
  function renderRequests() {
    $("req-count").textContent = requests.length;
    $("requests-card").classList.toggle("hidden", requests.length === 0);
    $("requests-list").innerHTML = requests.map(function (r) {
      return '<div class="req-row"><div><b>' + esc(r.shop_name || "—") + "</b> " +
        '<span class="muted">(' + esc(r.owner_email || "") + ')</span><br>' +
        '<span class="muted">' + esc(tierLabel(r.current_tier)) + " → </span><b>" + esc(r.tier_label) + "</b></div>" +
        '<div class="row-actions">' +
          '<button class="btn btn-primary btn-sm" data-approve="' + r.id + '">დადასტურება</button>' +
          '<button class="icon-btn danger" data-reject="' + r.id + '">უარი</button>' +
        "</div></div>";
    }).join("");
  }

  /* ---------- Modal (მაღაზიის დეტალები) ---------- */
  function closeModal() { $("modal-root").innerHTML = ""; }
  async function openShopDetail(id) {
    try {
      var d = await api("/admin/shops/" + id);
      var s = d.shop;
      var prods = (d.products || []).map(function (p) {
        return "<tr><td>" + esc(p.name) + "</td><td>" + Number(p.price).toFixed(2) + " ₾</td><td>" + p.quantity +
          "</td><td>" + (p.is_active ? "აქტიური" : "გამორთ.") + "</td></tr>";
      }).join("") || '<tr><td colspan="4" class="empty-state">პროდუქტი არ არის</td></tr>';
      var ords = (d.orders || []).map(function (o) {
        return "<tr><td>" + esc(o.customer_name) + "</td><td>" + Number(o.total).toFixed(2) + " ₾</td><td>" +
          esc(STATUS[o.status] || o.status) + "</td><td>" + fmtDate(o.created_at) + "</td></tr>";
      }).join("") || '<tr><td colspan="4" class="empty-state">შეკვეთა არ არის</td></tr>';
      $("modal-root").innerHTML =
        '<div class="modal-overlay" id="ov"><div class="modal">' +
          '<div class="modal-head"><h2>' + esc(s.name) + '</h2><button class="btn btn-ghost" id="mclose">დახურვა</button></div>' +
          '<p class="import-hint">ვალუტა: ' + esc(s.currency || "GEL") + " · ბოტი: " + (s.bot_enabled ? "ჩართ." : "გამორთ.") +
            " · Facebook: " + (s.facebook_page_id ? "დაკავშ." : "არა") + "</p>" +
          "<h3>პროდუქტები</h3><div class='admin-table-wrap'><table class='admin'><thead><tr><th>სახელი</th><th>ფასი</th><th>მარაგი</th><th>სტატ.</th></tr></thead><tbody>" + prods + "</tbody></table></div>" +
          "<h3>ბოლო შეკვეთები</h3><div class='admin-table-wrap'><table class='admin'><thead><tr><th>კლიენტი</th><th>ჯამი</th><th>სტატ.</th><th>თარიღი</th></tr></thead><tbody>" + ords + "</tbody></table></div>" +
        "</div></div>";
      $("mclose").addEventListener("click", closeModal);
      $("ov").addEventListener("click", function (e) { if (e.target.id === "ov") closeModal(); });
    } catch (e) { toast("დეტალები ვერ ჩაიტვირთა", true); }
  }

  /* ---------- Actions ---------- */
  async function toggleBot(id) {
    var s = shops.find(function (x) { return x.id === id; });
    if (!s) return;
    try {
      await req("PATCH", "/admin/shops/" + id, { bot_enabled: !s.bot_enabled });
      s.bot_enabled = !s.bot_enabled;
      renderShops();
      toast("ბოტი " + (s.bot_enabled ? "ჩაირთო" : "გამოირთო"));
    } catch (e) { toast("ვერ შეიცვალა", true); }
  }
  async function delShop(id) {
    var s = shops.find(function (x) { return x.id === id; });
    if (!s) return;
    if (!confirm('წავშალო მაღაზია „' + s.name + '“ ყველა პროდუქტითა და შეკვეთით? შეუქცევადია.')) return;
    try {
      await req("DELETE", "/admin/shops/" + id);
      shops = shops.filter(function (x) { return x.id !== id; });
      renderShops();
      toast("მაღაზია წაიშალა");
    } catch (e) { toast("წაშლა ვერ მოხერხდა", true); }
  }
  async function recovery(email) {
    if (!email) return;
    try {
      var r = await req("POST", "/admin/recovery", { email: email });
      if (r && r.action_link) {
        prompt("პაროლის აღდგენის ბმული (გაუგზავნე გამყიდველს):", r.action_link);
      } else { toast("ბმული დაგენერირდა", false); }
    } catch (e) { toast("ვერ მოხერხდა", true); }
  }

  /* ---------- tabs ---------- */
  document.querySelectorAll(".tab-btn").forEach(function (btn) {
    btn.addEventListener("click", function () {
      document.querySelectorAll(".tab-btn").forEach(function (b) { b.classList.remove("active"); });
      btn.classList.add("active");
      var name = btn.dataset.tab;
      document.querySelectorAll(".tab-panel").forEach(function (p) {
        p.classList.toggle("hidden", p.dataset.panel !== name);
      });
    });
  });

  /* ---------- event delegation ---------- */
  $("shops-body").addEventListener("click", function (e) {
    var t = e.target;
    if (t.dataset.detail) openShopDetail(t.dataset.detail);
    else if (t.dataset.toggle) toggleBot(t.dataset.toggle);
    else if (t.dataset.del) delShop(t.dataset.del);
  });
  $("shops-body").addEventListener("change", async function (e) {
    var sel = e.target;
    if (!sel.dataset.tier) return;
    var id = sel.dataset.tier, tier = sel.value;
    try {
      await req("PATCH", "/admin/shops/" + id, { subscription_tier: tier });
      var s = shops.find(function (x) { return x.id === id; });
      if (s) { s.tier = tier; s.customer_limit = TIER_CUST[tier] || s.customer_limit; }
      renderShops();
      toast("პაკეტი შეიცვალა: " + tier);
    } catch (e2) { toast("ვერ შეიცვალა", true); }
  });
  $("sellers-body").addEventListener("click", function (e) {
    if (e.target.dataset.recovery !== undefined) recovery(e.target.dataset.recovery);
  });
  $("shop-search").addEventListener("input", renderShops);
  $("seller-search").addEventListener("input", renderSellers);
  $("order-search").addEventListener("input", renderOrders);

  $("csv-shops").addEventListener("click", function () {
    downloadCSV("shops.csv", toCSV(
      ["მაღაზია", "მფლობელი", "პაკეტი", "კლიენტი_თვე", "ლიმიტი", "პროდუქტი", "შეკვეთა", "Facebook", "ბოტი", "შექმნა"],
      shops.map(function (s) {
        return [s.name, s.owner_email, s.tier_label, s.monthly_customers, s.customer_limit,
          s.products, s.orders, s.fb_connected ? "კი" : "არა", s.bot_enabled ? "ჩართ" : "გამორთ", fmtDate(s.created_at)];
      })));
  });
  $("csv-sellers").addEventListener("click", function () {
    downloadCSV("sellers.csv", toCSV(
      ["Email", "დადასტურ", "მაღაზია", "ბოლო_შესვლა", "რეგისტრ"],
      sellers.map(function (u) {
        return [u.email, u.confirmed ? "კი" : "არა", u.shops, fmtDate(u.last_sign_in), fmtDate(u.created_at)];
      })));
  });
  $("csv-orders").addEventListener("click", function () {
    downloadCSV("orders.csv", toCSV(
      ["მაღაზია", "კლიენტი", "ჯამი", "სტატუსი", "თარიღი"],
      orders.map(function (o) {
        return [o.shop_name, o.customer_name, Number(o.total || 0).toFixed(2), STATUS[o.status] || o.status, fmtDate(o.created_at)];
      })));
  });
  $("requests-list").addEventListener("click", async function (e) {
    var t = e.target;
    var id = t.dataset.approve || t.dataset.reject;
    if (!id) return;
    var approve = !!t.dataset.approve;
    if (!approve && !confirm("უარვყო ეს მოთხოვნა?")) return;
    t.disabled = true;
    try {
      await req("POST", "/admin/upgrade-requests/" + id + "/resolve", { approve: approve });
      toast(approve ? "დადასტურდა — პაკეტი შეიცვალა" : "უარყოფილია");
      load();
    } catch (e2) { toast("ვერ მოხერხდა", true); t.disabled = false; }
  });

  /* ---------- load ---------- */
  async function load() {
    try {
      var r = await Promise.all([
        api("/admin/overview"), api("/admin/shops"), api("/admin/sellers"),
        api("/admin/orders"), api("/admin/upgrade-requests"), api("/admin/growth"),
      ]);
      renderStats(r[0]);
      shops = r[1] || []; sellers = r[2] || []; orders = r[3] || []; requests = r[4] || []; growth = r[5] || [];
      renderShops(); renderSellers(); renderOrders(); renderRequests(); renderGrowth();
      $("loading").classList.add("hidden");
      $("admin-content").classList.remove("hidden");
      sb.auth.getUser(readStoredToken()).then(function (u) {
        if (u && u.data && u.data.user) $("user-email").textContent = u.data.user.email || "";
      }).catch(function () {});
    } catch (e) {
      $("loading").classList.add("hidden");
      if (e && e.forbidden) $("not-admin").classList.remove("hidden");
      else toast("ჩატვირთვა ვერ მოხერხდა", true);
    }
  }

  $("refresh-btn").addEventListener("click", function () {
    $("refresh-btn").disabled = true;
    load().finally(function () { $("refresh-btn").disabled = false; });
  });
  $("logout-btn").addEventListener("click", async function () {
    try { await sb.auth.signOut({ scope: "local" }); } catch (e) {}
    location.href = "index.html";
  });

  load();
})();
