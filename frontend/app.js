/* გამყიდველის პანელი — Supabase Auth + FastAPI products CRUD */
(function () {
  "use strict";

  // --- ხილული შეცდომების ჩვენება (დიაგნოსტიკა) ---
  function showBanner(msg) {
    let b = document.getElementById("fatal-banner");
    if (!b) {
      b = document.createElement("div");
      b.id = "fatal-banner";
      b.style.cssText =
        "position:fixed;top:0;left:0;right:0;background:#dc2626;color:#fff;" +
        "padding:12px 16px;z-index:9999;font:14px sans-serif;white-space:pre-wrap;";
      (document.body || document.documentElement).appendChild(b);
    }
    b.textContent = "⚠️ შეცდომა: " + msg;
  }
  // გლობალური შეცდომები — მხოლოდ console-ში (მომხმარებელს ტექნიკურ შეცდომას არ ვაჩვენებთ)
  window.addEventListener("error", function (e) {
    console.error("JS error:", e.message, "@", e.filename + ":" + e.lineno);
  });
  window.addEventListener("unhandledrejection", function (e) {
    var r = e.reason;
    console.error("Unhandled promise:", r && r.message ? r.message : r);
  });


  // --- დამოკიდებულებების შემოწმება ---
  if (!window.supabase || !window.supabase.createClient) {
    showBanner("Supabase ბიბლიოთეკა ვერ ჩაიტვირთა (CDN დაბლოკილია? ინტერნეტი?).");
    return;
  }
  if (!window.APP_CONFIG) {
    showBanner("config.js ვერ ჩაიტვირთა.");
    return;
  }

  const cfg = window.APP_CONFIG;
  // detectSessionInUrl:false — Facebook redirect-ის #_=_ რომ არ დაარღვიოს სესია.
  // ჩვენ Supabase-ის OAuth-ს არ ვიყენებთ, მხოლოდ email/პაროლს.
  const sb = supabase.createClient(cfg.SUPABASE_URL, cfg.SUPABASE_ANON_KEY, {
    auth: {
      persistSession: true,
      autoRefreshToken: true,
      detectSessionInUrl: false,
      // implicit — პაროლის აღდგენის ბმული hash-ით (მრავალ მოწყობილობაზე მუშაობს)
      flowType: "implicit",
      // no-op lock — navigator LockManager-ის ჩაკეტვის თავიდან ასაცილებლად
      // (getSession() რომ არ „გაიჭედოს" მრავალი tab-ის/popup-ის დროს)
      lock: async (_name, _timeout, fn) => await fn(),
    },
  });

  // --- state ---
  let shops = [];
  let currentShopId = null;

  // --- DOM ---
  const $ = (id) => document.getElementById(id);
  // უსაფრთხო listener — თუ ელემენტი არ არსებობს (მაგ. ძველი cached HTML), არ ჩაიშლება
  const on = (id, ev, fn) => {
    const el = $(id);
    if (el) el.addEventListener(ev, fn);
  };
  const authView = $("auth-view");
  const appView = $("app-view");
  const header = $("header");

  // dashboard ჩანართები (პროდუქტები / შეკვეთები / ბოტი)
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      const tab = btn.dataset.tab;
      document.querySelectorAll(".tab-panel").forEach((p) => {
        p.classList.toggle("hidden", p.dataset.panel !== tab);
      });
    });
  });

  // ---------- helpers ----------
  function toast(msg, isError) {
    const t = $("toast");
    t.textContent = msg;
    t.className = "toast " + (isError ? "toast-err" : "toast-ok");
    setTimeout(() => t.classList.add("hidden"), 3500);
  }

  // ღილაკზე spinner + დაბლოკვა async მოქმედების დროს
  function btnBusy(btn, busy) {
    if (!btn) return;
    btn.classList.toggle("is-loading", busy);
    btn.disabled = busy;
  }

  // list-ში skeleton placeholder-ები ჩატვირთვისას
  function showSkeleton(list, n) {
    if (!list) return;
    let h = "";
    for (let i = 0; i < (n || 3); i++) {
      h += '<div class="skel-item"><div class="skel skel-line lg"></div>' +
           '<div class="skel skel-line sm"></div></div>';
    }
    list.innerHTML = h;
  }

  // token-ს პირდაპირ storage-დან ვკითხულობთ — sb.auth.getSession() ზოგ ჯერ იჭედება
  function readStoredToken() {
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k && k.indexOf("sb-") === 0 && k.indexOf("auth-token") >= 0) {
        try {
          const s = JSON.parse(localStorage.getItem(k));
          return s.access_token || (s.currentSession && s.currentSession.access_token) || null;
        } catch (e) {}
      }
    }
    return null;
  }

  async function getToken() {
    const t = readStoredToken();
    if (t) return t;
    // fallback (იშვიათად)
    try {
      const { data } = await sb.auth.getSession();
      return data.session ? data.session.access_token : null;
    } catch (e) {
      return null;
    }
  }

  // token-ის ავტო-განახლება (ვადაგასვლისას) — 8წმ timeout-ით დაცული, რომ არ გაიჭედოს
  let _refreshPromise = null;
  function refreshToken() {
    if (!_refreshPromise) {
      _refreshPromise = (async () => {
        try {
          const timeout = new Promise((res) => setTimeout(() => res(null), 8000));
          const doRefresh = sb.auth
            .refreshSession()
            .then((r) => (r && r.data && r.data.session ? r.data.session.access_token : null))
            .catch(() => null);
          return await Promise.race([doRefresh, timeout]);
        } finally {
          _refreshPromise = null;
        }
      })();
    }
    return _refreshPromise;
  }

  // FastAPI backend-ის გამოძახება Bearer token-ით (401-ზე ავტო-განახლება + ერთხელ retry)
  async function api(path, method, body, _retried) {
    const token = await getToken();
    if (!token) throw new Error("სესია არ არის — გთხოვ თავიდან შედი");
    const opts = {
      method: method || "GET",
      headers: { Authorization: "Bearer " + token, "ngrok-skip-browser-warning": "1" },
    };
    if (body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    const res = await fetch(cfg.API_BASE + path, opts);

    // ვადაგასული token → ერთხელ ვცდით განახლებას და თავიდან
    if (res.status === 401 && !_retried) {
      const fresh = await refreshToken();
      if (fresh) return api(path, method, body, true);
      throw new Error("სესია ამოიწურა — გთხოვ თავიდან შედი");
    }

    if (res.status === 204) return null;
    const data = await res.json().catch(() => null);
    if (!res.ok) {
      const detail = data && data.detail ? data.detail : "შეცდომა (HTTP " + res.status + ")";
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    return data;
  }

  // ---------- auth UI ----------
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
      const isLogin = tab.dataset.tab === "login";
      $("login-form").classList.toggle("hidden", !isLogin);
      $("register-form").classList.toggle("hidden", isLogin);
    });
  });

  $("login-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = e.target.querySelector("button[type=submit]");
    btnBusy(btn, true);
    try {
      const { error } = await sb.auth.signInWithPassword({
        email: $("login-email").value.trim(),
        password: $("login-password").value,
      });
      if (error) return toast(translateAuthError(error.message), true);
      toast("მოგესალმებით!");
    } finally {
      btnBusy(btn, false);
    }
  });

  $("register-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    if ($("reg-password").value !== $("reg-password2").value) {
      return toast("პაროლები არ ემთხვევა", true);
    }
    const btn = e.target.querySelector("button[type=submit]");
    btnBusy(btn, true);
    try {
      const { data, error } = await sb.auth.signUp({
        email: $("reg-email").value.trim(),
        password: $("reg-password").value,
      });
      if (error) return toast(translateAuthError(error.message), true);
      if (data.session) {
        toast("რეგისტრაცია წარმატებულია!");
      } else {
        toast("რეგისტრაცია მიღებულია — შეამოწმე ელ-ფოსტა დასადასტურებლად, შემდეგ შედი.");
      }
    } finally {
      btnBusy(btn, false);
    }
  });

  on("logout-btn", "click", async () => {
    // scope:"local" — ქსელის გარეშე, მყისიერი; მერე გვერდს ვტვირთავთ თავიდან
    try { await sb.auth.signOut({ scope: "local" }); } catch (e) {}
    window.location.reload();
  });

  // ---------- პაროლის აღდგენა ----------
  on("forgot-link", "click", (e) => {
    e.preventDefault();
    $("login-form").classList.add("hidden");
    $("register-form").classList.add("hidden");
    $("forgot-form").classList.remove("hidden");
    $("forgot-email").value = $("login-email").value;
  });
  on("forgot-back", "click", (e) => {
    e.preventDefault();
    $("forgot-form").classList.add("hidden");
    $("login-form").classList.remove("hidden");
  });
  on("forgot-form", "submit", async (e) => {
    e.preventDefault();
    const email = $("forgot-email").value.trim();
    if (!email) return;
    const dir = location.pathname.replace(/[^/]*$/, ""); // reset.html იმავე საქაღალდეშია
    const redirectTo = location.origin + dir + "reset.html";
    const { error } = await sb.auth.resetPasswordForEmail(email, { redirectTo });
    if (error) return toast(translateAuthError(error.message), true);
    toast("აღდგენის ბმული გაიგზავნა — შეამოწმე ელ-ფოსტა 📧");
    $("forgot-form").classList.add("hidden");
    $("login-form").classList.remove("hidden");
  });

  function translateAuthError(msg) {
    if (/invalid login/i.test(msg)) return "არასწორი ელ-ფოსტა ან პაროლი";
    if (/already registered|already exists/i.test(msg)) return "ეს ელ-ფოსტა უკვე რეგისტრირებულია";
    if (/email not confirmed/i.test(msg)) return "ელ-ფოსტა ჯერ არ დადასტურებულა";
    if (/password should be/i.test(msg)) return "პაროლი ძალიან მოკლეა (მინ. 6 სიმბოლო)";
    return msg;
  }

  // ---------- shops ----------
  $("new-shop-btn").addEventListener("click", () => {
    $("shop-form").classList.remove("hidden");
    $("shop-name").focus();
  });
  $("shop-cancel").addEventListener("click", () => {
    $("shop-form").classList.add("hidden");
    $("shop-name").value = "";
  });

  $("shop-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      const shop = await api("/shops", "POST", { name: $("shop-name").value.trim() });
      $("shop-name").value = "";
      $("shop-form").classList.add("hidden");
      toast("მაღაზია შეიქმნა");
      await loadShops(shop.id);
    } catch (err) {
      toast(err.message, true);
    }
  });

  async function loadShops(selectId) {
    shops = await api("/shops/me");
    const sel = $("shop-select");
    sel.innerHTML = "";
    if (!shops.length) {
      currentShopId = null;
      sel.innerHTML = '<option value="">— მაღაზია არ გაქვს, შექმენი —</option>';
      $("shop-form").classList.remove("hidden");
    } else {
      shops.forEach((s) => {
        const o = document.createElement("option");
        o.value = s.id;
        o.textContent = s.name;
        sel.appendChild(o);
      });
      currentShopId = selectId && shops.some((s) => s.id === selectId) ? selectId : shops[0].id;
      sel.value = currentShopId;
    }
    updateProductFormState();
    updateFbSection();
    updateOrderLink();
    updateKnowledgeStatus();
    updateUsage();
    await Promise.all([loadProducts(), loadOrders(), loadAttention()]);
  }

  $("shop-select").addEventListener("change", async (e) => {
    currentShopId = e.target.value || null;
    updateFbSection();
    updateOrderLink();
    updateKnowledgeStatus();
    updateUsage();
    await Promise.all([loadProducts(), loadOrders(), loadAttention()]);
  });

  // ---------- გამოწერა / გამოყენება (usage) ----------
  const TIER_NAMES = { free: "უფასო", basic: "საბაზისო", standard: "სტანდარტი", business: "ბიზნესი" };
  const PAID_TIERS = ["basic", "standard", "business"];

  async function updateUsage() {
    const box = $("usage-box");
    if (!box) return;
    if (!currentShopId) { box.classList.add("hidden"); return; }
    try {
      const u = await api("/shops/" + currentShopId + "/usage");
      const climit = u.customer_limit;
      const cpct = climit ? Math.min(100, Math.round((u.monthly_customers / climit) * 100)) : 0;
      const near = cpct >= 90;
      const plimit = u.product_limit == null ? "∞" : u.product_limit;

      const prices = u.prices || {};
      let upgrade;
      if (u.pending_request) {
        const pt = u.pending_request;
        const shop = shops.find((s) => s.id === currentShopId);
        const ref = shop ? shop.name : "";
        upgrade = '<div class="usage-upgrade pending">' +
          "⏳ მოთხოვნილია: <b>" + escapeHtml(TIER_NAMES[pt] || pt) + " · " + (prices[pt] || "") + "₾/თვე</b>" +
          '<div class="pay-info">' +
            "💳 გადარიცხე ანგარიშზე: <b>" + escapeHtml(u.payment_iban || "") + "</b><br>" +
            "📝 დანიშნულებაში მიუთითე: <b>" + escapeHtml(ref) + "</b><br>" +
            "📩 ქვითარი გამოგზავნე: <b>" + escapeHtml(u.payment_contact || "") + "</b><br>" +
            "გადახდის შემდეგ ადმინი დაგიდასტურებთ და პაკეტი გააქტიურდება." +
          "</div></div>";
      } else {
        const btns = PAID_TIERS.filter((t) => t !== u.tier).map((t) =>
          '<button type="button" class="btn btn-ghost btn-sm" data-req-tier="' + t + '">' +
            TIER_NAMES[t] + " · " + (prices[t] || "") + "₾</button>"
        ).join("");
        upgrade = '<div class="usage-upgrade"><span>პაკეტის განახლება:</span> ' + btns + "</div>";
      }

      box.innerHTML =
        '<div class="usage-head">' +
          '<span class="usage-tier">📦 პაკეტი: <b>' + escapeHtml(u.tier_label) + "</b></span>" +
          '<span class="usage-nums">კლიენტი ამ თვეს: <b>' + u.monthly_customers + "</b> / " + climit + "</span>" +
        "</div>" +
        '<div class="usage-bar"><span style="width:' + cpct + '%"' + (near ? ' class="near"' : "") + "></span></div>" +
        '<div class="usage-foot">პროდუქტი: ' + u.products + " / " + plimit +
          (near ? ' · <b style="color:#d97706">ლიმიტს უახლოვდები — განაახლე პაკეტი</b>' : "") + "</div>" +
        upgrade;
      box.classList.remove("hidden");
    } catch (e) {
      box.classList.add("hidden");
    }
  }

  // პაკეტის მოთხოვნა (event delegation usage-box-ზე)
  document.addEventListener("click", async (e) => {
    const t = e.target.closest && e.target.closest("[data-req-tier]");
    if (!t || !currentShopId) return;
    const tier = t.dataset.reqTier;
    if (!confirm("გავაგზავნო „" + (TIER_NAMES[tier] || tier) + "“ პაკეტის მოთხოვნა? ადმინი დაგიდასტურებთ გადახდის შემდეგ.")) return;
    try {
      await api("/shops/" + currentShopId + "/upgrade-request", "POST", { tier });
      toast("მოთხოვნა გაიგზავნა");
      updateUsage();
    } catch (err) {
      toast(err.message, true);
    }
  });

  // ---------- შესაკვეთი ლინკი + შეკვეთები ----------
  function updateOrderLink() {
    const input = $("order-link");
    if (!input) return;
    if (!currentShopId) {
      input.value = "";
      return;
    }
    // order.html იმავე საქაღალდეშია, სადაც index.html
    const dir = location.pathname.replace(/[^/]*$/, "");
    const link = location.origin + dir + "order.html?shop=" + currentShopId;
    input.value = link;
    const open = $("open-link");
    if (open) open.href = link;
  }

  on("copy-link-btn", "click", async () => {
    const v = $("order-link").value;
    if (!v) return;
    try {
      await navigator.clipboard.writeText(v);
      toast("ლინკი დაკოპირდა");
    } catch (e) {
      $("order-link").select();
      toast("მონიშნულია — დააკოპირე Ctrl+C-ით");
    }
  });

  on("orders-refresh-btn", "click", loadOrders);
  on("order-filter", "change", loadOrders);
  on("attention-refresh-btn", "click", loadAttention);

  const ORDER_STATUS_LABELS = {
    new: "ახალი",
    processing: "მუშავდება",
    done: "დასრულებული",
    cancelled: "გაუქმებული",
  };

  async function loadOrders() {
    const list = $("order-list");
    if (!list) return;
    if (!currentShopId) {
      list.innerHTML = "";
      $("order-count").textContent = "0";
      return;
    }
    const filter = ($("order-filter") || {}).value || "";
    let path = "/orders";
    if (filter) path += "?status=" + encodeURIComponent(filter);
    showSkeleton(list, 3);
    $("orders-empty").classList.add("hidden");
    let orders;
    try {
      orders = await api(path);
    } catch (err) {
      list.innerHTML = "";
      toast("შეკვეთები ვერ ჩაიტვირთა: " + err.message, true);
      return;
    }
    $("order-count").textContent = orders.length;
    list.innerHTML = "";
    $("orders-empty").classList.toggle("hidden", orders.length > 0);
    orders.forEach((o) => list.appendChild(orderRow(o)));
  }

  function orderRow(o) {
    const row = document.createElement("div");
    row.className = "product-item order-item order-" + o.status;
    row.style.flexDirection = "column";
    row.style.alignItems = "stretch";

    const itemsText = (o.items || [])
      .map((i) => escapeHtml(i.name) + " ×" + i.quantity)
      .join(", ");
    const when = new Date(o.created_at).toLocaleString("ka-GE");

    const info = document.createElement("div");
    info.className = "product-info";
    info.innerHTML =
      '<div class="product-name">' + escapeHtml(o.customer_name) +
      " · " + Number(o.total).toFixed(2) + " ₾</div>" +
      '<div class="product-meta">' + itemsText + "</div>" +
      '<div class="product-meta">📞 ' + escapeHtml(o.customer_phone || "—") +
      " · 📍 " + escapeHtml(o.customer_address || "—") + "</div>" +
      (o.note ? '<div class="product-meta">📝 ' + escapeHtml(o.note) + "</div>" : "") +
      '<div class="product-meta" style="color:#9ca3af">' + escapeHtml(when) + "</div>";

    const actions = document.createElement("div");
    actions.className = "product-actions";
    actions.style.marginTop = "8px";
    actions.style.display = "flex";
    actions.style.gap = "8px";
    actions.style.alignItems = "center";
    const sel = document.createElement("select");
    sel.style.flex = "1";
    ["new", "processing", "done", "cancelled"].forEach((st) => {
      const opt = document.createElement("option");
      opt.value = st;
      opt.textContent = ORDER_STATUS_LABELS[st];
      if (o.status === st) opt.selected = true;
      sel.appendChild(opt);
    });
    sel.addEventListener("change", async () => {
      try {
        await api("/orders/" + o.id, "PATCH", { status: sel.value });
        toast("სტატ უსი განახლდა");
      } catch (err) {
        toast(err.message, true);
        loadOrders();
      }
    });
    actions.appendChild(sel);

    const delBtn = document.createElement("button");
    delBtn.type = "button";
    delBtn.className = "btn btn-danger btn-sm";
    delBtn.textContent = "🗑 წაშლა";
    delBtn.addEventListener("click", async () => {
      if (!confirm("წავშალო ეს შეკვეთა? მოქმედება შეუქცევადია. (მარაგი არ იცვლება)")) return;
      delBtn.disabled = true;
      try {
        await api("/orders/" + o.id, "DELETE");
        row.remove();
        toast("შეკვეთა წაიშალა");
        loadOrders();
      } catch (err) {
        toast(err.message, true);
        delBtn.disabled = false;
      }
    });
    actions.appendChild(delBtn);

    row.appendChild(info);
    row.appendChild(actions);
    return row;
  }

  // ---------- ოპერატორზე გადართვა (handoff — „ყურადღება სჭირდება") ----------
  async function loadAttention() {
    const card = $("attention-card");
    const list = $("attention-list");
    if (!card || !list) return;
    if (!currentShopId) {
      card.classList.add("hidden");
      return;
    }
    let data;
    try {
      data = await api("/shops/" + currentShopId + "/attention");
    } catch (err) {
      card.classList.add("hidden");
      return;
    }
    const items = (data && data.items) || [];
    $("attention-count").textContent = items.length;
    list.innerHTML = "";
    if (!items.length) {
      card.classList.add("hidden");
      return;
    }
    card.classList.remove("hidden");
    items.forEach((it) => list.appendChild(attentionRow(it)));
  }

  function attentionRow(it) {
    const row = document.createElement("div");
    row.className = "product-item";
    const when = it.at ? new Date(it.at).toLocaleString("ka-GE") : "";
    const info = document.createElement("div");
    info.className = "product-info";
    info.innerHTML =
      '<div class="product-name">💬 ' +
      (it.last_message ? escapeHtml(it.last_message) : "ბოტმა ვერ უპასუხა") +
      "</div>" +
      '<div class="product-meta" style="color:#9ca3af">' + escapeHtml(when) + "</div>";
    const actions = document.createElement("div");
    actions.className = "product-actions";
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn btn-primary btn-sm";
    btn.textContent = "✓ მოგვარდა";
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      try {
        await api(
          "/shops/" + currentShopId + "/attention/" + encodeURIComponent(it.psid) + "/resolve",
          "POST"
        );
        row.remove();
        toast("მონიშნულია მოგვარებულად");
        loadAttention();
      } catch (err) {
        toast(err.message, true);
        btn.disabled = false;
      }
    });
    actions.appendChild(btn);
    row.appendChild(info);
    row.appendChild(actions);
    return row;
  }

  // ---------- Facebook გვერდის დაკავშირება ----------
  function currentShop() {
    return shops.find((s) => s.id === currentShopId) || null;
  }

  function updateFbSection() {
    const section = $("fb-section");
    if (!section) return; // ძველი HTML — FB სექცია არ არსებობს
    const shop = currentShop();
    if (!shop) {
      section.classList.add("hidden");
      return;
    }
    section.classList.remove("hidden");
    const langSel = $("bot-language");
    if (langSel) langSel.value = shop.bot_language || "auto";
    const connected = !!shop.facebook_page_id;
    if (connected) {
      const ig = shop.instagram_account_id
        ? ' <span class="fb-connected">+ 📸 Instagram</span>'
        : ' <span class="fb-disconnected">(Instagram არ არის მიბმული ამ გვერდზე)</span>';
      $("fb-status").innerHTML =
        '<span class="fb-connected">✅ დაკავშირებულია Facebook გვერდთან</span>' + ig +
        " (ბოტი " + (shop.bot_enabled ? "ჩართულია" : "გამორთულია") + ")";
      $("fb-connect-btn").classList.add("hidden");
      $("fb-disconnect-btn").classList.remove("hidden");
    } else {
      $("fb-status").innerHTML =
        '<span class="fb-disconnected">გვერდი ჯერ არ არის დაკავშირებული — ბოტი არ მუშაობს Messenger-ში.</span>';
      $("fb-connect-btn").classList.remove("hidden");
      $("fb-disconnect-btn").classList.add("hidden");
    }
  }

  on("bot-language", "change", async (e) => {
    if (!currentShopId) return;
    try {
      await api("/shops/" + currentShopId, "PATCH", { bot_language: e.target.value });
      const s = shops.find((x) => x.id === currentShopId);
      if (s) s.bot_language = e.target.value;
      toast("ბოტის ენა შეიცვალა");
    } catch (err) {
      toast(err.message, true);
    }
  });

  on("fb-connect-btn", "click", async () => {
    if (!currentShopId) return toast("ჯერ აირჩიე მაღაზია", true);
    // popup სინქრონულად ვხსნით (browser blocker-ის ასარიდებლად), მერე ვაყენებთ URL-ს.
    // მთავარი პანელი ადგილზე რჩება → სესია ხელ უხლებელია.
    const popup = window.open("about:blank", "fbconnect", "width=600,height=720");
    let res;
    try {
      res = await api("/facebook/connect/start?shop_id=" + encodeURIComponent(currentShopId));
    } catch (err) {
      if (popup) popup.close();
      return toast(err.message, true);
    }
    if (popup) popup.location.href = res.login_url;
    else window.location.href = res.login_url; // popup დაიბლოკა → fallback redirect
  });

  // popup-დან (callback) მოსული შედეგი
  window.addEventListener("message", function (e) {
    const d = e.data;
    if (!d || typeof d !== "object" || !d.fb) return;
    if (d.fb === "connected") {
      toast("Facebook გვერდი დაკავშირდა: " + (d.page || ""));
      loadShops(currentShopId);
    } else if (d.fb === "no_pages") {
      toast("ვერ მოიძებნა Facebook გვერდი ამ ანგარიშზე", true);
    } else {
      toast("დაკავშირება ვერ მოხერხდა: " + (d.reason || d.fb), true);
    }
  });

  on("fb-disconnect-btn", "click", async () => {
    if (!currentShopId || !confirm("გავთიშო Facebook გვერდი?")) return;
    try {
      await api("/facebook/disconnect?shop_id=" + encodeURIComponent(currentShopId), "POST");
      toast("გვერდი გაითიშა");
      await loadShops(currentShopId);
    } catch (err) {
      toast(err.message, true);
    }
  });

  // callback-იდან დაბრუნების შეტყობინება (?fb=...)
  function handleFbRedirect() {
    const params = new URLSearchParams(window.location.search);
    const fb = params.get("fb");
    if (!fb) return;
    if (fb === "connected") toast("Facebook გვერდი დაკავშირდა: " + (params.get("page") || ""));
    else if (fb === "no_pages") toast("ვერ მოიძებნა Facebook გვერდი ამ ანგარიშზე", true);
    else toast("Facebook დაკავშირება ვერ მოხერხდა: " + (params.get("reason") || fb), true);
    // URL-ის გასუფთავება
    window.history.replaceState({}, "", window.location.pathname);
  }

  // ---------- ბოტის ცოდნა (PDF) ----------
  function updateKnowledgeStatus() {
    const box = $("knowledge-status");
    if (!box) return;
    const shop = currentShop();
    const clearBtn = $("knowledge-clear-btn");
    if (shop && shop.knowledge_filename) {
      box.innerHTML = '<span class="fb-connected">📄 ატვირთულია: ' + escapeHtml(shop.knowledge_filename) + "</span>";
      if (clearBtn) clearBtn.classList.remove("hidden");
    } else {
      box.innerHTML = '<span class="fb-disconnected">დოკუმენტი ჯერ არ არის ატვირთული.</span>';
      if (clearBtn) clearBtn.classList.add("hidden");
    }
  }

  on("knowledge-upload-btn", "click", async () => {
    if (!currentShopId) return toast("ჯერ აირჩიე მაღაზია", true);
    const fileInput = $("knowledge-file");
    const resultBox = $("knowledge-result");
    const file = fileInput.files && fileInput.files[0];
    if (!file) return toast("ჯერ აირჩიე PDF ფაილი", true);

    resultBox.className = "import-result";
    resultBox.textContent = "მუშავდება...";
    const token = await getToken();
    if (!token) { resultBox.textContent = "სესია არ არის — თავიდან შედი"; return; }
    const fd = new FormData();
    fd.append("file", file);
    try {
      const res = await fetch(cfg.API_BASE + "/shops/" + currentShopId + "/knowledge", {
        method: "POST",
        headers: { Authorization: "Bearer " + token, "ngrok-skip-browser-warning": "1" },
        body: fd,
      });
      const data = await res.json().catch(() => null);
      if (res.ok) {
        resultBox.className = "import-result import-ok";
        resultBox.textContent = "✅ PDF ჩაიტვირთა — ბოტი ახლა ამ ინფოს გამოიყენებს";
        fileInput.value = "";
        await loadShops(currentShopId);
      } else {
        const msg = data && data.detail ? (typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail)) : "შეცდომა (HTTP " + res.status + ")";
        resultBox.className = "import-result import-err";
        resultBox.textContent = "⚠️ " + msg;
      }
    } catch (err) {
      resultBox.className = "import-result import-err";
      resultBox.textContent = "⚠️ ატვირთვა ვერ მოხერხდა: " + err.message;
    }
  });

  on("knowledge-clear-btn", "click", async () => {
    if (!currentShopId || !confirm("წავშალო ატვირთული PDF-ცოდნა?")) return;
    try {
      await api("/shops/" + currentShopId + "/knowledge", "DELETE");
      toast("ცოდნა წაიშალა");
      await loadShops(currentShopId);
    } catch (err) {
      toast(err.message, true);
    }
  });

  function updateProductFormState() {
    const disabled = !currentShopId;
    $("product-form").querySelectorAll("input, textarea, button").forEach((el) => {
      el.disabled = disabled;
    });
  }

  // ---------- products ----------
  const productForm = $("product-form");

  function resetProductForm() {
    productForm.reset();
    $("product-id").value = "";
    $("p-active").checked = true;
    $("product-form-title").textContent = "ახალი პროდუქტი";
    $("product-submit").textContent = "დამატება";
    $("product-cancel").classList.add("hidden");
    updateProductFormState();
  }

  $("product-cancel").addEventListener("click", resetProductForm);

  productForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!currentShopId) return toast("ჯერ შექმენი ან აირჩიე მაღაზია", true);
    const id = $("product-id").value;
    const payload = {
      name: $("p-name").value.trim(),
      price: parseFloat($("p-price").value) || 0,
      quantity: parseInt($("p-quantity").value, 10) || 0,
      sku: $("p-sku").value.trim() || null,
      description: $("p-description").value.trim() || null,
      is_active: $("p-active").checked,
    };
    try {
      if (id) {
        await api("/products/" + id, "PUT", payload);
        toast("პროდუქტი განახლდა");
      } else {
        payload.shop_id = currentShopId;
        await api("/products", "POST", payload);
        toast("პროდუქტი დაემატა");
      }
      resetProductForm();
      await loadProducts();
    } catch (err) {
      toast(err.message, true);
    }
  });

  $("refresh-btn").addEventListener("click", loadProducts);

  // ---------- Excel/CSV import (ორ ბიჯად: ნახვა → სვეტების მორგება → ატვირთვა) ----------
  const IMPORT_FIELDS = [
    { key: "name", label: "სახელი", required: true },
    { key: "price", label: "ფასი" },
    { key: "quantity", label: "მარაგი" },
    { key: "description", label: "აღწერა" },
    { key: "sku", label: "SKU / კოდი" },
  ];

  on("import-btn", "click", previewImport);

  // ბიჯი 1 — ფაილის სვეტების ნახვა
  async function previewImport() {
    if (!currentShopId) return toast("ჯერ აირჩიე მაღაზია", true);
    const fileInput = $("import-file");
    const resultBox = $("import-result");
    const mapBox = $("import-mapping");
    const file = fileInput.files && fileInput.files[0];
    if (!file) return toast("ჯერ აირჩიე ფაილი (.xlsx ან .csv)", true);

    resultBox.className = "import-result";
    resultBox.textContent = "";
    mapBox.classList.add("hidden");
    mapBox.innerHTML = "";

    const token = await getToken();
    if (!token) { resultBox.textContent = "სესია არ არის — თავიდან შედი"; return; }

    const fd = new FormData();
    fd.append("shop_id", currentShopId);
    fd.append("file", file);
    try {
      const res = await fetch(cfg.API_BASE + "/products/import/preview", {
        method: "POST",
        headers: { Authorization: "Bearer " + token, "ngrok-skip-browser-warning": "1" },
        body: fd,
      });
      const data = await res.json().catch(() => null);
      if (!res.ok) {
        const msg = data && data.detail ? (typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail)) : "შეცდომა (HTTP " + res.status + ")";
        resultBox.className = "import-result import-err";
        resultBox.textContent = "⚠️ " + msg;
        return;
      }
      renderImportMapping(data);
    } catch (err) {
      resultBox.className = "import-result import-err";
      resultBox.textContent = "⚠️ ფაილი ვერ წაიკითხა: " + err.message;
    }
  }

  // ბიჯი 2 — სვეტების მორგების UI + preview ცხრილი
  function renderImportMapping(data) {
    const mapBox = $("import-mapping");
    const headers = data.headers || [];
    const detected = data.detected || {};
    const preview = data.preview || [];

    let html = '<div class="mapping-title">მიუთითე რომელი სვეტია რომელი (' + data.total_rows + " მწკრივი):</div>";
    html += '<div class="mapping-grid">';
    IMPORT_FIELDS.forEach((f) => {
      const sel = detected[f.key];
      html += '<label class="mapping-row"><span>' + f.label + (f.required ? " *" : "") + "</span>";
      html += '<select data-field="' + f.key + '">';
      html += '<option value="">— არცერთი —</option>';
      headers.forEach((h, i) => {
        const isSel = sel === i ? " selected" : "";
        html += '<option value="' + i + '"' + isSel + ">" + escapeHtml(h || ("სვეტი " + (i + 1))) + "</option>";
      });
      html += "</select></label>";
    });
    html += "</div>";

    // დამატებითი სვეტები — აღწერაში ჩასაწერად (ფერი, ზომა, მასალა...)
    if (headers.length) {
      html += '<div class="mapping-extra"><div class="mapping-extra-title">დამატებითი ინფორმაცია აღწერაში (არჩევითი — მაგ. ფერი, ზომა):</div>';
      headers.forEach((h, i) => {
        html += '<label class="extra-chk"><input type="checkbox" data-extra="' + i + '"> ' + escapeHtml(h || ("სვეტი " + (i + 1))) + "</label>";
      });
      html += "</div>";
    }

    if (headers.length) {
      html += '<div class="mapping-preview"><table><thead><tr>';
      headers.forEach((h) => (html += "<th>" + escapeHtml(h || "—") + "</th>"));
      html += "</tr></thead><tbody>";
      preview.forEach((row) => {
        html += "<tr>";
        headers.forEach((_, i) => (html += "<td>" + escapeHtml(row[i] || "") + "</td>"));
        html += "</tr>";
      });
      html += "</tbody></table></div>";
    }

    html += '<div class="import-row"><button id="import-confirm" class="btn btn-primary">✓ დაადასტურე და ატვირთე</button>';
    html += '<button id="import-cancel" class="btn btn-ghost">გაუქმება</button></div>';

    mapBox.innerHTML = html;
    mapBox.classList.remove("hidden");
    $("import-confirm").addEventListener("click", confirmImport);
    $("import-cancel").addEventListener("click", () => {
      mapBox.classList.add("hidden");
      mapBox.innerHTML = "";
    });
  }

  // ბიჯი 3 — არჩეული mapping-ით ატვირთვა
  async function confirmImport() {
    const fileInput = $("import-file");
    const resultBox = $("import-result");
    const mapBox = $("import-mapping");
    const file = fileInput.files && fileInput.files[0];
    if (!file) return toast("ფაილი დაიკარგა — აირჩიე თავიდან", true);

    const mapping = {};
    mapBox.querySelectorAll("select[data-field]").forEach((s) => {
      if (s.value !== "") mapping[s.dataset.field] = parseInt(s.value, 10);
    });
    if (mapping.name === undefined) {
      return toast("აუცილებელია მიუთითო „სახელის“ სვეტი", true);
    }
    // დამატებითი სვეტები აღწერისთვის (გამოვრიცხოთ ის, რაც უკვე ველად შეირჩა)
    const usedCols = Object.values(mapping);
    const extra = [];
    mapBox.querySelectorAll("input[data-extra]:checked").forEach((c) => {
      const idx = parseInt(c.dataset.extra, 10);
      if (!usedCols.includes(idx)) extra.push(idx);
    });
    if (extra.length) mapping.extra = extra;

    const confirmBtn = $("import-confirm");
    if (confirmBtn) confirmBtn.disabled = true;
    resultBox.className = "import-result";
    resultBox.textContent = "მუშავდება...";

    const token = await getToken();
    if (!token) { resultBox.textContent = "სესია არ არის — თავიდან შედი"; return; }

    const fd = new FormData();
    fd.append("shop_id", currentShopId);
    fd.append("file", file);
    fd.append("mapping", JSON.stringify(mapping));
    try {
      const res = await fetch(cfg.API_BASE + "/products/import", {
        method: "POST",
        headers: { Authorization: "Bearer " + token, "ngrok-skip-browser-warning": "1" },
        body: fd,
      });
      const data = await res.json().catch(() => null);
      if (res.ok) {
        resultBox.className = "import-result import-ok";
        resultBox.textContent = "✅ " + (data.message || "დაემატა " + data.imported + " პროდუქტი");
        fileInput.value = "";
        mapBox.classList.add("hidden");
        mapBox.innerHTML = "";
        await loadProducts();
      } else if (res.status === 422 && data && data.detail && data.detail.errors) {
        let h = '<div class="import-err-title">⚠️ ' + escapeHtml(data.detail.message) + "</div><ul>";
        data.detail.errors.forEach((e) => { h += "<li>მწკრივი " + e.row + ": " + escapeHtml(e.message) + "</li>"; });
        h += "</ul>";
        resultBox.className = "import-result import-err";
        resultBox.innerHTML = h;
        if (confirmBtn) confirmBtn.disabled = false;
      } else {
        const msg = data && data.detail ? (typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail)) : "შეცდომა (HTTP " + res.status + ")";
        resultBox.className = "import-result import-err";
        resultBox.textContent = "⚠️ " + msg;
        if (confirmBtn) confirmBtn.disabled = false;
      }
    } catch (err) {
      resultBox.className = "import-result import-err";
      resultBox.textContent = "⚠️ ატვირთვა ვერ მოხერხდა: " + err.message;
      if (confirmBtn) confirmBtn.disabled = false;
    }
  }

  let allProducts = []; // ჩატვირთული პროდუქტები (ძებნისთვის)

  async function loadProducts() {
    const list = $("product-list");
    if (!currentShopId) {
      allProducts = [];
      list.innerHTML = "";
      $("product-count").textContent = "0";
      $("empty-state").classList.add("hidden");
      return;
    }
    showSkeleton(list, 4);
    $("empty-state").classList.add("hidden");
    allProducts = await api("/products?shop_id=" + encodeURIComponent(currentShopId));
    $("product-count").textContent = allProducts.length;
    renderProductList();
  }

  function renderProductList() {
    const list = $("product-list");
    const q = (($("product-search") || {}).value || "").trim().toLowerCase();
    const shown = q
      ? allProducts.filter(
          (p) =>
            (p.name || "").toLowerCase().includes(q) ||
            (p.sku || "").toLowerCase().includes(q)
        )
      : allProducts;
    list.innerHTML = "";
    shown.forEach((p) => list.appendChild(productRow(p)));
    const empty = $("empty-state");
    if (!allProducts.length) {
      empty.textContent = "პროდუქტები ჯერ არ გაქვს — დაამატე პირველი ზემოთ.";
      empty.classList.remove("hidden");
    } else if (!shown.length) {
      empty.textContent = "„" + q + "“ — ვერაფერი მოიძებნა.";
      empty.classList.remove("hidden");
    } else {
      empty.classList.add("hidden");
    }
  }

  on("product-search", "input", renderProductList);

  function productRow(p) {
    const row = document.createElement("div");
    row.className = "product-item";

    const info = document.createElement("div");
    info.className = "product-info";
    const badge = p.is_active
      ? '<span class="badge badge-on">აქტიური</span>'
      : '<span class="badge badge-off">გამორთული</span>';
    info.innerHTML =
      '<div class="product-name">' + escapeHtml(p.name) + " " + badge + "</div>" +
      '<div class="product-meta">' + Number(p.price).toFixed(2) + " ₾ · მარაგი: " + p.quantity +
      (p.sku ? " · SKU: " + escapeHtml(p.sku) : "") + "</div>";

    const actions = document.createElement("div");
    actions.className = "product-actions";
    const editBtn = document.createElement("button");
    editBtn.className = "btn btn-ghost btn-sm";
    editBtn.textContent = "რედაქტ.";
    editBtn.onclick = () => startEdit(p);
    const delBtn = document.createElement("button");
    delBtn.className = "btn btn-danger btn-sm";
    delBtn.textContent = "წაშლა";
    delBtn.onclick = () => removeProduct(p);
    actions.appendChild(editBtn);
    actions.appendChild(delBtn);

    row.appendChild(info);
    row.appendChild(actions);
    return row;
  }

  function startEdit(p) {
    $("product-id").value = p.id;
    $("p-name").value = p.name;
    $("p-price").value = p.price;
    $("p-quantity").value = p.quantity;
    $("p-sku").value = p.sku || "";
    $("p-description").value = p.description || "";
    $("p-active").checked = p.is_active;
    $("product-form-title").textContent = "პროდუქტის რედაქტირება";
    $("product-submit").textContent = "შენახვა";
    $("product-cancel").classList.remove("hidden");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  async function removeProduct(p) {
    if (!confirm('წავშალო "' + p.name + '"?')) return;
    try {
      await api("/products/" + p.id, "DELETE");
      toast("პროდუქტი წაიშალა");
      await loadProducts();
    } catch (err) {
      toast(err.message, true);
    }
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
    );
  }

  // ---------- session routing ----------
  // ადმინია თუ არა — თუ კი, ვაჩენთ „ადმინი" ღილაკს header-ში
  async function checkAdmin() {
    try {
      await api("/admin/check");
      const l = $("admin-link");
      if (l) l.classList.remove("hidden");
    } catch (e) {
      /* არა ადმინი — ღილაკი დამალული რჩება */
    }
  }

  async function render(session) {
    if (session) {
      authView.classList.add("hidden");
      appView.classList.remove("hidden");
      header.classList.remove("hidden");
      $("user-email").textContent = session.user.email || "";
      resetProductForm();
      try {
        await loadShops();
      } catch (err) {
        showBanner("მონაცემების ჩატვირთვა ვერ მოხერხდა: " + err.message);
      }
      handleFbRedirect();
      checkAdmin();
    } else {
      // session არ არის — მაგრამ თუ storage-ში token ჯერ დევს, login-ზე არ გადავრთოთ
      // (onAuthStateChange refresh-ზე ხან ცარიელ session-ს ისვრის; getSession მალე მოვა).
      // login მხოლოდ მაშინ, თუ token საერთოდ აღარ არის (ნამდვილად გამოსული).
      if (readStoredToken()) return;
      appView.classList.add("hidden");
      header.classList.add("hidden");
      authView.classList.remove("hidden");
    }
  }

  // მყისიერი UI — storage-ში token თუ არის, პანელი მაშინვე ვაჩვენოთ
  // (getSession() ასინქრონულია და ზოგ ჯერ 2-3 წამს ანელებს → login „ციმციმის" გარეშე)
  if (readStoredToken()) {
    authView.classList.add("hidden");
    appView.classList.remove("hidden");
    header.classList.remove("hidden");
  }

  sb.auth.onAuthStateChange((_event, session) => render(session));
  sb.auth.getSession().then(({ data }) => render(data.session));
})();
