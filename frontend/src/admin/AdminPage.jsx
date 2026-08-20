import { useEffect, useMemo, useState } from "react";
import { createClient } from "@supabase/supabase-js";
import { api, req, readStoredToken } from "../lib/api.js";
import { toCSV, downloadCSV, fmtDate } from "../lib/csv.js";
import { STATUS, TIERS, tierLabel } from "./constants.js";
import ShopDetailModal from "./ShopDetailModal.jsx";

const cfg = window.APP_CONFIG;
// detectSessionInUrl:false — იგივე კონფიგი, რაც პანელს აქვს (Facebook-ის #_=_ გამო)
const sb = createClient(cfg.SUPABASE_URL, cfg.SUPABASE_ANON_KEY, {
  auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: false },
});

function Pill({ on, yes = "კი", no = "არა" }) {
  return <span className={on ? "pill pill-on" : "pill pill-off"}>{on ? yes : no}</span>;
}

function Stat({ val, lbl, mrr }) {
  return (
    <div className={mrr ? "stat mrr" : "stat"}>
      <div className="val">{val}</div>
      <div className="lbl">{lbl}</div>
    </div>
  );
}

export default function AdminPage() {
  const [loading, setLoading] = useState(true);
  const [forbidden, setForbidden] = useState(false);
  const [overview, setOverview] = useState(null);
  const [shops, setShops] = useState([]);
  const [sellers, setSellers] = useState([]);
  const [orders, setOrders] = useState([]);
  const [requests, setRequests] = useState([]);
  const [growth, setGrowth] = useState([]);
  const [userEmail, setUserEmail] = useState("");

  const [tab, setTab] = useState("shops");
  const [shopQ, setShopQ] = useState("");
  const [sellerQ, setSellerQ] = useState("");
  const [orderQ, setOrderQ] = useState("");

  const [detail, setDetail] = useState(null);
  const [refreshing, setRefreshing] = useState(false);
  const [toast, setToast] = useState(null);

  function showToast(msg, isErr) {
    setToast({ msg, isErr });
    setTimeout(() => setToast(null), 3500);
  }

  async function load() {
    // allSettled — ერთი endpoint-ის ჩავარდნა მთელ პანელს აღარ შლის
    const r = await Promise.allSettled([
      api("/admin/overview"),
      api("/admin/shops"),
      api("/admin/sellers"),
      api("/admin/orders"),
      api("/admin/upgrade-requests"),
      api("/admin/growth"),
    ]);
    setLoading(false);

    const ov = r[0];
    if (ov.status === "rejected") {
      if (ov.reason && ov.reason.forbidden) {
        setForbidden(true);
        return;
      }
      showToast("ზოგი მონაცემი ვერ ჩაიტვირთა", true);
    }

    const val = (i, d) => (r[i].status === "fulfilled" && r[i].value != null ? r[i].value : d);
    if (ov.status === "fulfilled") setOverview(ov.value);
    setShops(val(1, []));
    setSellers(val(2, []));
    setOrders(val(3, []));
    setRequests(val(4, []));
    setGrowth(val(5, []));

    sb.auth
      .getUser(readStoredToken())
      .then((u) => {
        if (u && u.data && u.data.user) setUserEmail(u.data.user.email || "");
      })
      .catch(() => {});
  }

  useEffect(() => {
    load();
  }, []);

  /* ---------- ფილტრები ---------- */
  const shopList = useMemo(() => {
    const q = shopQ.trim().toLowerCase();
    if (!q) return shops;
    return shops.filter(
      (s) =>
        (s.name || "").toLowerCase().includes(q) ||
        (s.owner_email || "").toLowerCase().includes(q)
    );
  }, [shops, shopQ]);

  const sellerList = useMemo(() => {
    const q = sellerQ.trim().toLowerCase();
    if (!q) return sellers;
    return sellers.filter((u) => (u.email || "").toLowerCase().includes(q));
  }, [sellers, sellerQ]);

  const orderList = useMemo(() => {
    const q = orderQ.trim().toLowerCase();
    if (!q) return orders;
    return orders.filter((o) =>
      ((o.shop_name || "") + " " + (o.customer_name || "") + " " + (STATUS[o.status] || o.status || ""))
        .toLowerCase()
        .includes(q)
    );
  }, [orders, orderQ]);

  /* ---------- მოქმედებები ---------- */
  async function toggleBot(s) {
    try {
      await req("PATCH", "/admin/shops/" + s.id, { bot_enabled: !s.bot_enabled });
      setShops((list) =>
        list.map((x) => (x.id === s.id ? { ...x, bot_enabled: !x.bot_enabled } : x))
      );
      showToast("ბოტი " + (!s.bot_enabled ? "ჩაირთო" : "გამოირთო"));
    } catch {
      showToast("ვერ შეიცვალა", true);
    }
  }

  async function delShop(s) {
    if (!confirm("წავშალო მაღაზია " + s.name + " ყველა პროდუქტითა და შეკვეთით? შეუქცევადია.")) return;
    try {
      await req("DELETE", "/admin/shops/" + s.id);
      setShops((list) => list.filter((x) => x.id !== s.id));
      showToast("მაღაზია წაიშალა");
    } catch {
      showToast("წაშლა ვერ მოხერხდა", true);
    }
  }

  async function changeTier(id, tier) {
    try {
      await req("PATCH", "/admin/shops/" + id, { subscription_tier: tier });
      showToast("პაკეტი შეიცვალა: " + tier);
      load(); // per-account — მფლობელის ყველა მაღაზია განახლდა
    } catch {
      showToast("ვერ შეიცვალა", true);
    }
  }

  async function recovery(email) {
    if (!email) return;
    try {
      const r = await req("POST", "/admin/recovery", { email });
      if (r && r.action_link) prompt("პაროლის აღდგენის ბმული (გაუგზავნე გამყიდველს):", r.action_link);
      else showToast("ბმული დაგენერირდა", false);
    } catch {
      showToast("ვერ მოხერხდა", true);
    }
  }

  async function openDetail(id) {
    try {
      setDetail(await api("/admin/shops/" + id));
    } catch {
      showToast("დეტალები ვერ ჩაიტვირთა", true);
    }
  }

  async function resolveRequest(id, approve) {
    if (!approve && !confirm("უარვყო ეს მოთხოვნა?")) return;
    try {
      await req("POST", "/admin/upgrade-requests/" + id + "/resolve", { approve });
      showToast(approve ? "დადასტურდა — პაკეტი შეიცვალა" : "უარყოფილია");
      load();
    } catch {
      showToast("ვერ მოხერხდა", true);
    }
  }

  async function logout() {
    try {
      await sb.auth.signOut({ scope: "local" });
    } catch {
      /* ლოკალური სესია მაინც ქრება */
    }
    location.href = "index.html";
  }

  /* ---------- CSV ---------- */
  const csvShops = () =>
    downloadCSV(
      "shops.csv",
      toCSV(
        ["მაღაზია", "მფლობელი", "პაკეტი", "კლიენტი_თვე", "ლიმიტი", "პროდუქტი", "შეკვეთა", "Facebook", "ბოტი", "შექმნა"],
        shops.map((s) => [
          s.name, s.owner_email, s.tier_label, s.monthly_customers, s.customer_limit,
          s.products, s.orders, s.fb_connected ? "კი" : "არა", s.bot_enabled ? "ჩართ" : "გამორთ",
          fmtDate(s.created_at),
        ])
      )
    );

  const csvSellers = () =>
    downloadCSV(
      "sellers.csv",
      toCSV(
        ["Email", "დადასტურ", "მაღაზია", "ბოლო_შესვლა", "რეგისტრ"],
        sellers.map((u) => [
          u.email, u.confirmed ? "კი" : "არა", u.shops, fmtDate(u.last_sign_in), fmtDate(u.created_at),
        ])
      )
    );

  const csvOrders = () =>
    downloadCSV(
      "orders.csv",
      toCSV(
        ["მაღაზია", "კლიენტი", "ჯამი", "სტატუსი", "თარიღი"],
        orders.map((o) => [
          o.shop_name, o.customer_name, Number(o.total || 0).toFixed(2),
          STATUS[o.status] || o.status, fmtDate(o.created_at),
        ])
      )
    );

  const chartMax = growth.reduce((m, g) => Math.max(m, g.orders, g.shops), 1);

  return (
    <>
      <div
        id="toast"
        className={"toast " + (toast ? (toast.isErr ? "toast-err" : "toast-ok") : "hidden")}
      >
        {toast ? toast.msg : ""}
      </div>

      <header className="app-header">
        <div className="brand">
          <span className="brand-mark">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path d="M5 8h14l-1.1 11.2A2.5 2.5 0 0 1 15.4 21.5H8.6A2.5 2.5 0 0 1 6.1 19.2L5 8z" fill="#fff" />
              <path d="M9 8V6.5a3 3 0 0 1 6 0V8" fill="none" stroke="#fff" strokeWidth="1.7" strokeLinecap="round" />
            </svg>
          </span>
          ადმინ პანელი
        </div>
        <div className="header-right">
          <span className="user-email">{userEmail}</span>
          <a href="index.html" className="btn btn-ghost">← პანელი</a>
          <button className="btn btn-ghost" onClick={logout}>გასვლა</button>
        </div>
      </header>

      <main className="container">
        {loading && (
          <div className="card">
            <p className="import-hint" style={{ margin: 0 }}>იტვირთება...</p>
          </div>
        )}

        {forbidden && (
          <div className="card" style={{ textAlign: "center" }}>
            <h2 style={{ color: "var(--danger)" }}>წვდომა აკრძალულია</h2>
            <p className="import-hint">
              ეს გვერდი მხოლოდ ადმინისთვისაა. <a href="index.html">დაბრუნება პანელზე</a>
            </p>
          </div>
        )}

        {!loading && !forbidden && (
          <>
            {requests.length > 0 && (
              <div className="card" style={{ borderColor: "var(--primary)" }}>
                <h2 style={{ marginTop: 0 }}>🔔 პაკეტის მოთხოვნები ({requests.length})</h2>
                <div>
                  {requests.map((r) => (
                    <div className="req-row" key={r.id}>
                      <div>
                        <b>{r.shop_name || "—"}</b>{" "}
                        <span className="muted">({r.owner_email || ""})</span>
                        <br />
                        <span className="muted">{tierLabel(r.current_tier)} → </span>
                        <b>{r.tier_label}</b>
                      </div>
                      <div className="row-actions">
                        <button className="btn btn-primary btn-sm" onClick={() => resolveRequest(r.id, true)}>
                          დადასტურება
                        </button>
                        <button className="icon-btn danger" onClick={() => resolveRequest(r.id, false)}>
                          უარი
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div className="card">
              <div className="list-header">
                <h2 style={{ margin: 0 }}>📊 საერთო მაჩვენებლები</h2>
                <button
                  className="btn btn-ghost"
                  disabled={refreshing}
                  onClick={async () => {
                    setRefreshing(true);
                    await load();
                    setRefreshing(false);
                  }}
                >
                  ↻ განახლება
                </button>
              </div>
              <div className="stat-grid">
                {overview && (
                  <>
                    <Stat mrr val={(overview.mrr || 0) + " ₾"} lbl="MRR · თვიური შემოსავალი" />
                    <Stat val={overview.total_shops} lbl="მაღაზია" />
                    <Stat val={overview.total_sellers} lbl="გამყიდველი" />
                    <Stat val={overview.connected_shops} lbl="Facebook-დაკავშ." />
                    <Stat val={overview.total_products} lbl="პროდუქტი" />
                    <Stat val={overview.total_orders} lbl="შეკვეთა (სულ)" />
                    <Stat val={overview.orders_30d} lbl="შეკვეთა (30 დღე)" />
                    <Stat val={overview.revenue + " ₾"} lbl="ბრუნვა (გაუქმ. გარეშე)" />
                    <Stat
                      val={overview.total_shops ? (overview.total_orders / overview.total_shops).toFixed(1) : 0}
                      lbl="საშ. შეკვეთა/მაღაზია"
                    />
                  </>
                )}
              </div>
            </div>

            <div className="card">
              <h2 style={{ marginTop: 0 }}>📈 ზრდა (ბოლო 6 თვე)</h2>
              <div className="chart">
                {growth.map((g) => (
                  <div className="chart-col" key={g.ym}>
                    <div className="chart-bars">
                      <span
                        className="bar orders"
                        style={{ height: Math.round((g.orders / chartMax) * 100) + "%" }}
                        title={"შეკვეთა: " + g.orders}
                      />
                      <span
                        className="bar shops"
                        style={{ height: Math.round((g.shops / chartMax) * 100) + "%" }}
                        title={"მაღაზია: " + g.shops}
                      />
                    </div>
                    <div className="chart-lbl">{g.ym.slice(5)}</div>
                  </div>
                ))}
              </div>
              <div className="chart-legend">
                <span><i style={{ background: "var(--primary)" }} />შეკვეთები</span>
                <span><i style={{ background: "#14b8a6" }} />ახალი მაღაზიები</span>
              </div>
            </div>

            <div className="tabs-nav">
              {[["shops", "🏪 მაღაზიები"], ["sellers", "👤 გამყიდვლები"], ["orders", "📋 შეკვეთები"]].map(
                ([k, label]) => (
                  <button
                    key={k}
                    className={"tab-btn" + (tab === k ? " active" : "")}
                    onClick={() => setTab(k)}
                  >
                    {label}
                  </button>
                )
              )}
            </div>

            {tab === "shops" && (
              <div className="tab-panel">
                <div className="card">
                  <div className="list-header">
                    <h2 style={{ margin: 0 }}>მაღაზიები ({shopList.length})</h2>
                    <button className="btn btn-ghost btn-sm" onClick={csvShops}>📤 CSV</button>
                  </div>
                  <input
                    type="search"
                    placeholder="🔍 ძებნა — მაღაზია ან მფლობელი"
                    style={{ marginBottom: 12 }}
                    value={shopQ}
                    onChange={(e) => setShopQ(e.target.value)}
                  />
                  <div className="admin-table-wrap">
                    <table className="admin">
                      <thead>
                        <tr>
                          <th>მაღაზია</th><th>მფლობელი</th><th>პაკეტი</th><th>კლიენტი/თვე</th>
                          <th>პროდ.</th><th>შეკვ.</th><th>Facebook</th><th>ბოტი</th><th>შექმნა</th><th>მოქმედება</th>
                        </tr>
                      </thead>
                      <tbody>
                        {shopList.map((s) => {
                          const over = s.customer_limit && s.monthly_customers > s.customer_limit;
                          return (
                            <tr key={s.id}>
                              <td><b>{s.name}</b></td>
                              <td>{s.owner_email || "—"}</td>
                              <td>
                                <select
                                  className="tier-sel"
                                  value={s.tier}
                                  onChange={(e) => changeTier(s.id, e.target.value)}
                                >
                                  {TIERS.map((t) => (
                                    <option key={t[0]} value={t[0]}>{t[1]}</option>
                                  ))}
                                </select>
                              </td>
                              <td>
                                <span style={over ? { color: "var(--danger)", fontWeight: 600 } : undefined}>
                                  {s.monthly_customers} / {s.customer_limit}
                                </span>
                              </td>
                              <td>{s.products}</td>
                              <td>{s.orders}</td>
                              <td><Pill on={s.fb_connected} /></td>
                              <td><Pill on={s.bot_enabled} yes="ჩართ." no="გამორთ." /></td>
                              <td>{fmtDate(s.created_at)}</td>
                              <td>
                                <div className="row-actions">
                                  <button className="icon-btn" onClick={() => openDetail(s.id)}>👁</button>
                                  <button className="icon-btn" onClick={() => toggleBot(s)}>
                                    {s.bot_enabled ? "გამორთვა" : "ჩართვა"}
                                  </button>
                                  <button className="icon-btn danger" onClick={() => delShop(s)}>🗑</button>
                                </div>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                  {shopList.length === 0 && <p className="empty-state">მაღაზიები ჯერ არ არის.</p>}
                </div>
              </div>
            )}

            {tab === "sellers" && (
              <div className="tab-panel">
                <div className="card">
                  <div className="list-header">
                    <h2 style={{ margin: 0 }}>გამყიდვლები ({sellerList.length})</h2>
                    <button className="btn btn-ghost btn-sm" onClick={csvSellers}>📤 CSV</button>
                  </div>
                  <input
                    type="search"
                    placeholder="🔍 ძებნა — email"
                    style={{ marginBottom: 12 }}
                    value={sellerQ}
                    onChange={(e) => setSellerQ(e.target.value)}
                  />
                  <div className="admin-table-wrap">
                    <table className="admin">
                      <thead>
                        <tr>
                          <th>Email</th><th>დადასტ.</th><th>მაღაზია</th>
                          <th>ბოლო შესვლა</th><th>რეგისტრ.</th><th>მოქმედება</th>
                        </tr>
                      </thead>
                      <tbody>
                        {sellerList.map((u) => (
                          <tr key={u.email}>
                            <td><b>{u.email || "—"}</b></td>
                            <td><Pill on={u.confirmed} /></td>
                            <td>{u.shops}</td>
                            <td>{fmtDate(u.last_sign_in)}</td>
                            <td>{fmtDate(u.created_at)}</td>
                            <td>
                              <button className="icon-btn" onClick={() => recovery(u.email)}>
                                🔑 პაროლი
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  {sellerList.length === 0 && <p className="empty-state">გამყიდვლები ჯერ არ არის.</p>}
                </div>
              </div>
            )}

            {tab === "orders" && (
              <div className="tab-panel">
                <div className="card">
                  <div className="list-header">
                    <h2 style={{ margin: 0 }}>ბოლო შეკვეთები ({orderList.length})</h2>
                    <button className="btn btn-ghost btn-sm" onClick={csvOrders}>📤 CSV</button>
                  </div>
                  <input
                    type="search"
                    placeholder="🔍 ძებნა — მაღაზია, კლიენტი ან სტატუსი"
                    style={{ marginBottom: 12 }}
                    value={orderQ}
                    onChange={(e) => setOrderQ(e.target.value)}
                  />
                  <div className="admin-table-wrap">
                    <table className="admin">
                      <thead>
                        <tr>
                          <th>მაღაზია</th><th>კლიენტი</th><th>ჯამი</th><th>სტატუსი</th><th>თარიღი</th>
                        </tr>
                      </thead>
                      <tbody>
                        {orderList.map((o) => (
                          <tr key={o.id}>
                            <td>{o.shop_name || "—"}</td>
                            <td>{o.customer_name || "—"}</td>
                            <td>{Number(o.total || 0).toFixed(2)} ₾</td>
                            <td>{STATUS[o.status] || o.status}</td>
                            <td>{fmtDate(o.created_at)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  {orderList.length === 0 && <p className="empty-state">შეკვეთები ჯერ არ არის.</p>}
                </div>
              </div>
            )}
          </>
        )}
      </main>

      <ShopDetailModal data={detail} onClose={() => setDetail(null)} />
    </>
  );
}
