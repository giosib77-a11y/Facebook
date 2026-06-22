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
  window.addEventListener("error", function (e) {
    showBanner((e.message || "JS error") + "  @ " + (e.filename || "") + ":" + (e.lineno || ""));
  });
  window.addEventListener("unhandledrejection", function (e) {
    var r = e.reason;
    showBanner("Promise: " + (r && r.message ? r.message : String(r)));
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

  // ---------- helpers ----------
  function toast(msg, isError) {
    const t = $("toast");
    t.textContent = msg;
    t.className = "toast " + (isError ? "toast-err" : "toast-ok");
    setTimeout(() => t.classList.add("hidden"), 3500);
  }

  // token-ს პირდაპირ storage-დან ვკითხ ულობთ — sb.auth.getSession() ზოგ ჯერ იჭედება
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

  // FastAPI backend-ის გამოძახება Bearer token-ით
  async function api(path, method, body) {
    const token = await getToken();
    if (!token) throw new Error("სესია არ არის — გთხოვ თავიდან შედი");
    const opts = { method: method || "GET", headers: { Authorization: "Bearer " + token } };
    if (body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    const res = await fetch(cfg.API_BASE + path, opts);
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
    const { error } = await sb.auth.signInWithPassword({
      email: $("login-email").value.trim(),
      password: $("login-password").value,
    });
    if (error) return toast(translateAuthError(error.message), true);
    toast("მოგესალმებით!");
  });

  $("register-form").addEventListener("submit", async (e) => {
    e.preventDefault();
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
  });

  on("logout-btn", "click", async () => {
    // scope:"local" — ქსელის გარეშე, მყისიერი; მერე გვერდს ვტვირთავთ თავიდან
    try { await sb.auth.signOut({ scope: "local" }); } catch (e) {}
    window.location.reload();
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
    await loadProducts();
  }

  $("shop-select").addEventListener("change", async (e) => {
    currentShopId = e.target.value || null;
    updateFbSection();
    await loadProducts();
  });

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
    const connected = !!shop.facebook_page_id;
    if (connected) {
      $("fb-status").innerHTML =
        '<span class="fb-connected">✅ დაკავშირებულია Facebook გვერდთან</span> ' +
        "(ბოტი " + (shop.bot_enabled ? "ჩართულია" : "გამორთულია") + ")";
      $("fb-connect-btn").classList.add("hidden");
      $("fb-disconnect-btn").classList.remove("hidden");
    } else {
      $("fb-status").innerHTML =
        '<span class="fb-disconnected">გვერდი ჯერ არ არის დაკავშირებული — ბოტი არ მუშაობს Messenger-ში.</span>';
      $("fb-connect-btn").classList.remove("hidden");
      $("fb-disconnect-btn").classList.add("hidden");
    }
  }

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

  // ---------- Excel/CSV import ----------
  on("import-btn", "click", async () => {
    if (!currentShopId) return toast("ჯერ აირჩიე მაღაზია", true);
    const fileInput = $("import-file");
    const resultBox = $("import-result");
    const file = fileInput.files && fileInput.files[0];
    if (!file) return toast("ჯერ აირჩიე ფაილი (.xlsx ან .csv)", true);

    resultBox.className = "import-result";
    resultBox.textContent = "მუშავდება...";

    const token = await getToken();
    if (!token) {
      resultBox.textContent = "სესია არ არის — თავიდან შედი";
      return;
    }
    const fd = new FormData();
    fd.append("shop_id", currentShopId);
    fd.append("file", file);

    try {
      const res = await fetch(cfg.API_BASE + "/products/import", {
        method: "POST",
        headers: { Authorization: "Bearer " + token }, // Content-Type-ს browser თვითონ აყენებს
        body: fd,
      });
      const data = await res.json().catch(() => null);
      if (res.ok) {
        resultBox.className = "import-result import-ok";
        resultBox.textContent = "✅ " + (data.message || "დაემატა " + data.imported + " პროდუქტი");
        fileInput.value = "";
        await loadProducts();
      } else if (res.status === 422 && data && data.detail && data.detail.errors) {
        // მწკრივების შეცდომები
        let html = '<div class="import-err-title">⚠️ ' + escapeHtml(data.detail.message) + "</div><ul>";
        data.detail.errors.forEach((e) => {
          html += "<li>მწკრივი " + e.row + ": " + escapeHtml(e.message) + "</li>";
        });
        html += "</ul>";
        resultBox.className = "import-result import-err";
        resultBox.innerHTML = html;
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

  async function loadProducts() {
    const list = $("product-list");
    if (!currentShopId) {
      list.innerHTML = "";
      $("product-count").textContent = "0";
      $("empty-state").classList.add("hidden");
      return;
    }
    const products = await api("/products?shop_id=" + encodeURIComponent(currentShopId));
    $("product-count").textContent = products.length;
    list.innerHTML = "";
    $("empty-state").classList.toggle("hidden", products.length > 0);
    products.forEach((p) => list.appendChild(productRow(p)));
  }

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
    } else {
      appView.classList.add("hidden");
      header.classList.add("hidden");
      authView.classList.remove("hidden");
    }
  }

  sb.auth.onAuthStateChange((_event, session) => render(session));
  sb.auth.getSession().then(({ data }) => render(data.session));
})();
