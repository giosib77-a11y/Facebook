import { useState } from "react";
import { api } from "./api.js";
import { useShopData } from "./ShopData.jsx";
import { useToast } from "./ui.jsx";
import ProductsTab from "./ProductsTab.jsx";
import OrdersTab from "./OrdersTab.jsx";
import BotTab from "./BotTab.jsx";

const TIER_NAMES = { free: "უფასო", basic: "საბაზისო", standard: "სტანდარტი", business: "ბიზნესი" };
const PAID_TIERS = ["basic", "standard", "business"];

const TABS = [
  ["overview", "📊 მთავარი"],
  ["products", "🛒 პროდუქტები"],
  ["orders", "📋 შეკვეთები"],
  ["bot", "🤖 ბოტი · არხები"],
];

export default function Dashboard() {
  const [tab, setTab] = useState("overview");
  const { usage, orders, products, attention } = useShopData();

  return (
    <section>
      <div className="dash">
        <aside className="dash-side">
          <nav className="tabs-nav">
            {TABS.map(([k, label]) => (
              <button key={k} className={"tab-btn" + (tab === k ? " active" : "")} onClick={() => setTab(k)}>
                {label}
              </button>
            ))}
          </nav>
          <div className="dash-side-foot">
            💬 დახმარება:<br />
            <a href="mailto:chatassistbusiness@gmail.com">chatassistbusiness@gmail.com</a>
          </div>
        </aside>

        <div className="dash-main">
          <div className="stat-cards">
            <StatCard icon="👥" val={usage ? usage.monthly_customers : "—"} label="კლიენტი ამ თვეს" />
            <StatCard icon="🛒" val={orders.length} label="შეკვეთა" />
            <StatCard icon="🔔" val={attention.length} label="ყურადღება სჭირდება" alert={attention.length > 0} />
            <StatCard icon="📦" val={products.length} label="პროდუქტი" />
          </div>

          <ShopBar />
          <AttentionCard />

          {tab === "overview" && <Overview goto={setTab} />}
          {tab === "products" && <ProductsTab />}
          {tab === "orders" && <OrdersTab />}
          {tab === "bot" && <BotTab />}
        </div>
      </div>
    </section>
  );
}

function StatCard({ icon, val, label, alert }) {
  return (
    <div className={"stat-card" + (alert ? " alert" : "")}>
      <div className="si">{icon}</div>
      <div className="sv">{val}</div>
      <div className="sl">{label}</div>
    </div>
  );
}

/* ---------- მაღაზიის არჩევა / შექმნა + პაკეტი ---------- */
function ShopBar() {
  const toast = useToast();
  const { shops, shopId, selectShop, loadShops } = useShopData();
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("");

  async function create(e) {
    e.preventDefault();
    try {
      const shop = await api("/shops", "POST", { name: name.trim() });
      setName("");
      setShowForm(false);
      toast("მაღაზია შეიქმნა");
      await loadShops(shop.id);
    } catch (err) {
      toast(err.message, true);
    }
  }

  const noShops = shops.length === 0;

  return (
    <div className="card">
      <div className="shop-bar">
        <label className="shop-select-wrap">
          მაღაზია
          <select value={shopId || ""} onChange={(e) => selectShop(e.target.value)}>
            {noShops && <option value="">— მაღაზია არ გაქვს, შექმენი —</option>}
            {shops.map((s) => (
              <option value={s.id} key={s.id}>{s.name}</option>
            ))}
          </select>
        </label>
        <button className="btn btn-ghost" onClick={() => setShowForm(true)}>+ ახალი მაღაზია</button>
      </div>

      <UsageBox />

      {(showForm || noShops) && (
        <form className="inline-form" onSubmit={create}>
          <input type="text" placeholder="მაღაზიის სახელი" required autoFocus
            value={name} onChange={(e) => setName(e.target.value)} />
          <button type="submit" className="btn btn-primary">შექმნა</button>
          {!noShops && (
            <button type="button" className="btn btn-ghost" onClick={() => { setShowForm(false); setName(""); }}>
              გაუქმება
            </button>
          )}
        </form>
      )}
    </div>
  );
}

/* ---------- გამოწერა / ლიმიტები ---------- */
function UsageBox() {
  const toast = useToast();
  const { shopId, currentShop, usage, loadUsage } = useShopData();
  if (!shopId || !usage) return null;

  const climit = usage.customer_limit;
  const cpct = climit ? Math.min(100, Math.round((usage.monthly_customers / climit) * 100)) : 0;
  const near = cpct >= 90;
  const plimit = usage.product_limit == null ? "∞" : usage.product_limit;
  const prices = usage.prices || {};

  async function request(tier) {
    if (!confirm("გავაგზავნო „" + (TIER_NAMES[tier] || tier) + "“ პაკეტის მოთხოვნა? ადმინი დაგიდასტურებთ გადახდის შემდეგ.")) return;
    try {
      await api("/shops/" + shopId + "/upgrade-request", "POST", { tier });
      toast("მოთხოვნა გაიგზავნა");
      loadUsage();
    } catch (err) {
      toast(err.message, true);
    }
  }

  async function downgrade() {
    if (!confirm(
      "უფასო პაკეტზე დაბრუნდები — გამოწერა ერთიანია, ამიტომ ეს ეხება ყველა შენს მაღაზიას. " +
      "ფასიანი პაკეტის უპირატესობები გაუქმდება (მეტი კლიენტი და პროდუქტი, " +
      "Excel/PDF ატვირთვა, პრიორიტეტული მხარდაჭერა).\n\nგავაგრძელო?"
    )) return;
    try {
      await api("/shops/" + shopId + "/downgrade-free", "POST");
      toast("უფასო პაკეტზე დაბრუნდი");
      loadUsage();
    } catch (err) {
      toast(err.message, true);
    }
  }

  return (
    <div className="usage-box">
      <div className="usage-head">
        <span className="usage-tier">📦 პაკეტი: <b>{usage.tier_label}</b></span>
        <span className="usage-nums">კლიენტი ამ თვეს: <b>{usage.monthly_customers}</b> / {climit}</span>
      </div>
      <div className="usage-bar">
        <span style={{ width: cpct + "%" }} className={near ? "near" : undefined} />
      </div>
      <div className="usage-foot">
        პროდუქტი: {usage.products} / {plimit}
        {near && <> · <b style={{ color: "#d97706" }}>ლიმიტს უახლოვდები — განაახლე პაკეტი</b></>}
      </div>

      {usage.pending_request ? (
        <div className="usage-upgrade pending">
          ⏳ მოთხოვნილია:{" "}
          <b>{TIER_NAMES[usage.pending_request] || usage.pending_request} · {prices[usage.pending_request] || ""}₾/თვე</b>
          <div className="pay-info">
            💳 გადარიცხე ანგარიშზე: <b>{usage.payment_iban || ""}</b><br />
            📝 დანიშნულებაში მიუთითე: <b>{currentShop ? currentShop.name : ""}</b><br />
            📩 ქვითარი გამოგზავნე: <b>{usage.payment_contact || ""}</b><br />
            გადახდის შემდეგ ადმინი დაგიდასტურებთ და პაკეტი გააქტიურდება.
          </div>
        </div>
      ) : (
        <div className="usage-upgrade">
          <span>პაკეტის განახლება:</span>{" "}
          {PAID_TIERS.filter((t) => t !== usage.tier).map((t) => (
            <button key={t} type="button" className="btn btn-ghost btn-sm" onClick={() => request(t)}>
              {TIER_NAMES[t]} · {prices[t] || ""}₾
            </button>
          ))}
        </div>
      )}

      {usage.tier !== "free" && (
        <div className="usage-downgrade-row">
          <button type="button" className="usage-downgrade" onClick={downgrade}>
            ↩ უფასო პაკეტზე დაბრუნება
          </button>
        </div>
      )}
    </div>
  );
}

/* ---------- ყურადღება სჭირდება (handoff) ---------- */
function AttentionCard() {
  const toast = useToast();
  const { shopId, attention, loadAttention } = useShopData();
  if (!attention.length) return null;

  async function resolve(it) {
    try {
      await api("/shops/" + shopId + "/attention/" + encodeURIComponent(it.psid) + "/resolve", "POST");
      toast("მონიშნულია მოგვარებულად");
      loadAttention();
    } catch (err) {
      toast(err.message, true);
    }
  }

  return (
    <div className="card attention-card">
      <div className="list-header">
        <h2 style={{ margin: 0 }}>🔔 ყურადღება სჭირდება ({attention.length})</h2>
        <button className="btn btn-ghost" onClick={loadAttention}>↻</button>
      </div>
      <p className="import-hint">
        ამ საუბრებში ბოტმა ვერ უპასუხა ან კლიენტმა ოპერატორი ითხოვა — შედი Messenger/Instagram-ში
        და უპასუხე. მოგვარების შემდეგ დააჭირე „მოგვარდა“.
      </p>
      <div className="product-list">
        {attention.map((it) => (
          <div className="product-item" key={it.psid}>
            <div className="product-info">
              <div className="product-name">💬 {it.last_message || "ბოტმა ვერ უპასუხა"}</div>
              <div className="product-meta" style={{ color: "#9ca3af" }}>
                {it.at ? new Date(it.at).toLocaleString("ka-GE") : ""}
              </div>
            </div>
            <div className="product-actions">
              <button className="btn btn-primary btn-sm" onClick={() => resolve(it)}>✓ მოგვარდა</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ---------- Overview ---------- */
function Overview({ goto }) {
  const { currentShop, orders } = useShopData();
  const fb = !!(currentShop && currentShop.facebook_page_id);
  const ig = !!(currentShop && currentShop.instagram_account_id);
  const botOn = fb && currentShop.bot_enabled !== false;
  const top = orders.slice(0, 3);

  return (
    <div className="tab-panel">
      <div className="two-col">
        <div className="card">
          <div className="list-header">
            <h2 style={{ margin: 0 }}>🤖 ბოტი &amp; არხები</h2>
            <button type="button" className="tab-btn-link" onClick={() => goto("bot")}>მართვა →</button>
          </div>
          {!currentShop ? (
            <p className="ov-empty">აირჩიე ან შექმენი მაღაზია.</p>
          ) : (
            <>
              <div className="ov-conn">
                <div className={"ov-ch" + (fb ? " on" : "")}>
                  📘<b>Facebook</b>
                  <span className={"s " + (fb ? "yes" : "no")}>{fb ? "✓ დაკავშირებული" : "არ არის"}</span>
                </div>
                <div className={"ov-ch" + (ig ? " on" : "")}>
                  📸<b>Instagram</b>
                  <span className={"s " + (ig ? "yes" : "no")}>{ig ? "✓ დაკავშირებული" : "არ არის"}</span>
                </div>
              </div>
              <div className="ov-bot">
                <span className={"led " + (botOn ? "on" : "off")} />
                <div>
                  <b>{botOn ? "ბოტი აქტიურია" : "ბოტი ჯერ არ მუშაობს"}</b>
                  <br />
                  <span>
                    {fb
                      ? "პასუხობს კლიენტებს ქართულად, 24/7"
                      : "დააკავშირე Facebook გვერდი „ბოტი · არხები“ ტაბში"}
                  </span>
                </div>
              </div>
            </>
          )}
        </div>

        <div className="card">
          <div className="list-header">
            <h2 style={{ margin: 0 }}>🧾 ბოლო შეკვეთები</h2>
            <button type="button" className="tab-btn-link" onClick={() => goto("orders")}>ყველა →</button>
          </div>
          <div className="overview-orders">
            {top.length === 0 ? (
              <p className="ov-empty">შეკვეთები ჯერ არ არის.</p>
            ) : (
              top.map((o) => (
                <div className="ov-ord" key={o.id}>
                  <span className="oi">🧾</span>
                  <div className="oinfo">
                    <b>{o.customer_name}</b>
                    <div className="m">
                      {(o.items || []).map((i) => i.name + " ×" + i.quantity).join(", ") || "—"}
                    </div>
                  </div>
                  <span className="pr">{Number(o.total).toFixed(0)} ₾</span>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
