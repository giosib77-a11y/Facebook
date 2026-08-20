import { useEffect, useMemo, useState } from "react";

const cfg = window.APP_CONFIG;
const API = cfg.API_BASE;
// ngrok-ის ინტერსტიციალის ასაცილებლად (ძველი კოდიდან — უვნებელია ngrok-ის გარეშეც)
const H = { "ngrok-skip-browser-warning": "1" };

/** ?shop=ID — ⚠️ URL-კონტრაქტი: ბოტი ამ ლინკს რეალურ მყიდველებს უგზავნის. არ შეცვალო. */
const shopId = new URLSearchParams(location.search).get("shop");

function BagIcon() {
  return (
    <svg width="28" height="28" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M5 8h14l-1.1 11.2A2.5 2.5 0 0 1 15.4 21.5H8.6A2.5 2.5 0 0 1 6.1 19.2L5 8z" fill="#fff" />
      <path d="M9 8V6.5a3 3 0 0 1 6 0V8" fill="none" stroke="#fff" strokeWidth="1.7" strokeLinecap="round" />
    </svg>
  );
}

function StockLabel({ stock }) {
  if (stock <= 0) return <span className="stock stock-out">არ არის მარაგში</span>;
  if (stock <= 3) return <span className="stock stock-low">დარჩა {stock} ცალი</span>;
  return <span className="stock">მარაგში: {stock} ცალი</span>;
}

export default function OrderPage() {
  const [shopName, setShopName] = useState("იტვირთება...");
  const [currency, setCurrency] = useState("GEL");
  const [products, setProducts] = useState([]);
  const [loaded, setLoaded] = useState(false);
  // რაოდენობები ცალკე state-ში — ძებნით გაფილტვრისას არ იკარგება
  const [qty, setQty] = useState({});
  const [query, setQuery] = useState("");
  const [form, setForm] = useState({ name: "", phone: "", address: "", note: "" });
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [toast, setToast] = useState(null);

  function showToast(msg, isErr) {
    setToast({ msg, isErr });
    setTimeout(() => setToast(null), 3500);
  }

  useEffect(() => {
    if (!shopId) {
      setShopName("არასწორი ლინკი (მაღაზია არ არის მითითებული)");
      return;
    }
    (async () => {
      try {
        const res = await fetch(
          API + "/public-menu?shop_id=" + encodeURIComponent(shopId),
          { headers: H }
        );
        if (!res.ok) throw new Error("მაღაზია ვერ მოიძებნა");
        const data = await res.json();
        setCurrency((data.shop && data.shop.currency) || "GEL");
        setShopName(data.shop ? data.shop.name : "მაღაზია");
        document.title = "შეკვეთა — " + (data.shop ? data.shop.name : "");
        setProducts(data.products || []);
        setLoaded(true);
      } catch (e) {
        setShopName("ვერ ჩაიტვირთა");
        showToast(e.message, true);
      }
    })();
  }, []);

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return products;
    return products.filter((p) =>
      (p.name + " " + (p.description || "")).toLowerCase().includes(q)
    );
  }, [products, query]);

  const total = products.reduce(
    (sum, p) => sum + (Number(p.price) || 0) * (parseInt(qty[p.id], 10) || 0),
    0
  );

  function setQtyClamped(p, raw) {
    if (raw === "") {
      setQty((s) => ({ ...s, [p.id]: "" }));
      return;
    }
    const stock = Number(p.quantity) || 0;
    let v = parseInt(raw, 10);
    if (isNaN(v)) v = 0;
    if (v > stock) {
      v = stock;
      showToast(p.name + " — მარაგშია მხოლოდ " + stock + " ცალი", true);
    } else if (v < 0) {
      v = 0;
    }
    setQty((s) => ({ ...s, [p.id]: String(v) }));
  }

  async function onSubmit(e) {
    e.preventDefault();
    const items = products
      .map((p) => ({ p, n: parseInt(qty[p.id], 10) || 0 }))
      .filter((x) => x.n > 0)
      .map((x) => ({
        product_id: x.p.id,
        name: x.p.name,
        price: Number(x.p.price) || 0,
        quantity: x.n,
      }));
    if (!items.length) {
      showToast("აირჩიე მინიმუმ ერთი პროდუქტი (რაოდენობა > 0)", true);
      return;
    }
    setBusy(true);
    try {
      const res = await fetch(API + "/orders", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...H },
        body: JSON.stringify({
          shop_id: shopId,
          customer_name: form.name.trim(),
          customer_phone: form.phone.trim(),
          customer_address: form.address.trim(),
          note: form.note.trim() || null,
          items,
        }),
      });
      const data = await res.json().catch(() => null);
      if (!res.ok) {
        const d = data && data.detail ? data.detail : "შეცდომა (HTTP " + res.status + ")";
        throw new Error(typeof d === "string" ? d : JSON.stringify(d));
      }
      setDone(true);
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (err) {
      showToast(err.message, true);
      setBusy(false);
    }
  }

  const upd = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  return (
    <>
      <div
        id="toast"
        className={"toast " + (toast ? (toast.isErr ? "toast-err" : "toast-ok") : "hidden")}
      >
        {toast ? toast.msg : ""}
      </div>

      <main className="order-wrap">
        <header className="order-head">
          <div className="badge">
            <BagIcon />
          </div>
          <h1 id="shop-name">{shopName}</h1>
          <p className="sub">აირჩიე პროდუქტები, მიუთითე რაოდენობა და შეავსე მონაცემები.</p>
        </header>

        {!done && (
          <form id="order-form" onSubmit={onSubmit}>
            <div className="card">
              <h2>🛒 პროდუქტები</h2>
              <input
                type="search"
                placeholder="🔍 ძებნა — პროდუქტის სახელი"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
              <div className="product-list" style={{ marginTop: 12 }}>
                {visible.map((p) => {
                  const stock = Number(p.quantity) || 0;
                  const out = stock <= 0;
                  return (
                    <div key={p.id} className={"product-item" + (out ? " out" : "")}>
                      <div className="product-info">
                        <div className="product-name">{p.name}</div>
                        <div className="product-meta">
                          {Number(p.price).toFixed(2)} {currency}
                          {p.description ? " · " + p.description : ""}
                        </div>
                        <div className="product-meta">
                          <StockLabel stock={stock} />
                        </div>
                      </div>
                      <div className="product-actions">
                        <input
                          type="number"
                          min="0"
                          max={stock}
                          placeholder="0"
                          inputMode="numeric"
                          style={{ width: 80 }}
                          disabled={out}
                          aria-label="რაოდენობა"
                          value={qty[p.id] ?? ""}
                          onFocus={(e) => e.target.select()}
                          onChange={(e) => setQtyClamped(p, e.target.value)}
                        />
                      </div>
                    </div>
                  );
                })}
              </div>
              {loaded && products.length === 0 && (
                <p className="empty-state">ამ მაღაზიას ამჟამად პროდუქტი არ აქვს.</p>
              )}
              {products.length > 0 && visible.length === 0 && (
                <p className="empty-state">ვერაფერი მოიძებნა.</p>
              )}
            </div>

            <div className="card">
              <h2>📝 შენი მონაცემები</h2>
              <label>
                სახელი *
                <input
                  type="text"
                  required
                  placeholder="სახელი გვარი"
                  autoComplete="name"
                  value={form.name}
                  onChange={upd("name")}
                />
              </label>
              <label>
                ტელეფონი *
                <input
                  type="tel"
                  required
                  placeholder="5XX XX XX XX"
                  autoComplete="tel"
                  value={form.phone}
                  onChange={upd("phone")}
                />
              </label>
              <label>
                მისამართი *
                <input
                  type="text"
                  required
                  placeholder="ქალაქი, ქუჩა, ბინა"
                  autoComplete="street-address"
                  value={form.address}
                  onChange={upd("address")}
                />
              </label>
              <label>
                კომენტარი (არასავალდებულო)
                <textarea
                  rows="2"
                  placeholder="დამატებითი ინფორმაცია"
                  value={form.note}
                  onChange={upd("note")}
                />
              </label>
            </div>

            <div className="summary">
              <div className="summary-row">
                <span className="lbl">ჯამი</span>
                <span className="val">
                  <span id="total">{total.toFixed(2)}</span> <small>₾</small>
                </span>
              </div>
              <button type="submit" className="btn btn-primary" disabled={busy}>
                {busy ? "იგზავნება..." : "შეკვეთის გაგზავნა"}
              </button>
            </div>
          </form>
        )}

        {done && (
          <div className="card">
            <div className="ok-badge">✅</div>
            <h2>შეკვეთა მიღებულია!</h2>
            <p>მადლობა! გამყიდველი მალე დაგიკავშირდებათ.</p>
          </div>
        )}
      </main>
    </>
  );
}
