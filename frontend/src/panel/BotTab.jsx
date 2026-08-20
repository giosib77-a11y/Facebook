import { useEffect, useRef, useState } from "react";
import { api } from "./api.js";
import { getToken } from "./supabase.js";
import { startConnect } from "./fbConnect.js";
import { useShopData } from "./ShopData.jsx";
import { useToast } from "./ui.jsx";

const cfg = window.APP_CONFIG;

export default function BotTab() {
  const { currentShop } = useShopData();
  return (
    <div className="tab-panel">
      <FacebookCard />
      <LanguageCard />
      <KnowledgeCard key={currentShop ? currentShop.id : "none"} />
      <ExportCard />
      <AnalyticsCard />
    </div>
  );
}

/* ---------- Facebook / Instagram ---------- */
function FacebookCard() {
  const toast = useToast();
  const { shopId, currentShop, loadShops } = useShopData();
  const connected = !!(currentShop && currentShop.facebook_page_id);
  const ig = !!(currentShop && currentShop.instagram_account_id);

  async function connect() {
    if (!shopId) return toast("ჯერ აირჩიე მაღაზია", true);
    // ⚠️ startConnect-ის პირველი ხაზი window.open-ია და სინქრონულად უნდა შესრულდეს.
    // აქ await არ დგას მის წინ — popup არ დაიბლოკება.
    startConnect(shopId, api).catch((err) => toast(err.message, true));
  }

  async function disconnect() {
    if (!shopId || !confirm("გავთიშო Facebook გვერდი?")) return;
    try {
      await api("/facebook/disconnect?shop_id=" + encodeURIComponent(shopId), "POST");
      toast("გვერდი გაითიშა");
      await loadShops(shopId);
    } catch (err) {
      toast(err.message, true);
    }
  }

  return (
    <div className="card">
      <h2 style={{ marginTop: 0 }}>🔵 Facebook &amp; 📸 Instagram</h2>
      <p className="import-hint">
        დააკავშირე შენი Facebook გვერდი — ბოტი Messenger-ში კლიენტებს უპასუხებს მაღაზიის მარაგით.
        თუ გვერდზე Instagram Business ანგარიშია მიბმული, ბოტი Instagram Direct-შიც იმუშავებს
        (ერთი დაკავშირებით).
      </p>
      {currentShop && (
        <div className="fb-section">
          <div className="fb-status">
            {connected ? (
              <>
                <span className="fb-connected">✅ დაკავშირებულია Facebook გვერდთან</span>
                {ig ? (
                  <span className="fb-connected"> + 📸 Instagram</span>
                ) : (
                  <span className="fb-disconnected"> (Instagram არ არის მიბმული ამ გვერდზე)</span>
                )}
                {" "}(ბოტი {currentShop.bot_enabled ? "ჩართულია" : "გამორთულია"})
              </>
            ) : (
              <span className="fb-disconnected">
                გვერდი ჯერ არ არის დაკავშირებული — ბოტი არ მუშაობს Messenger-ში.
              </span>
            )}
          </div>
          <div className="fb-actions">
            {!connected && (
              <button className="btn btn-primary" onClick={connect}>
                🔵 Facebook გვერდის დაკავშირება
              </button>
            )}
            {connected && (
              <button className="btn btn-danger" onClick={disconnect}>გათიშვა</button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/* ---------- ბოტის ენა ---------- */
function LanguageCard() {
  const toast = useToast();
  const { shopId, currentShop, loadShops } = useShopData();
  const value = (currentShop && currentShop.bot_language) || "auto";

  async function change(e) {
    if (!shopId) return;
    const bot_language = e.target.value;
    try {
      await api("/shops/" + shopId, "PATCH", { bot_language });
      toast("ბოტის ენა შეიცვალა");
      await loadShops(shopId);
    } catch (err) {
      toast(err.message, true);
    }
  }

  return (
    <div className="card">
      <h2 style={{ marginTop: 0 }}>🌍 ბოტის ენა</h2>
      <p className="import-hint">რომელ ენაზე უპასუხოს ბოტმა კლიენტებს Messenger/Instagram-ში.</p>
      <label>
        ენა
        <select value={value} onChange={change}>
          <option value="auto">ავტომატური — კლიენტის ენა (ქართული/English/Русский)</option>
          <option value="ka">მხოლოდ ქართული</option>
          <option value="en">Only English</option>
          <option value="ru">Только русский</option>
        </select>
      </label>
    </div>
  );
}

/* ---------- ბოტის ცოდნა (PDF) ---------- */
function KnowledgeCard() {
  const toast = useToast();
  const { shopId, currentShop, loadShops, usage } = useShopData();
  const [result, setResult] = useState(null);
  const fileRef = useRef(null);
  const allowed = !usage || usage.bulk_import !== false;
  const fname = currentShop && currentShop.knowledge_filename;

  async function upload() {
    if (!shopId) return toast("ჯერ აირჩიე მაღაზია", true);
    const file = fileRef.current && fileRef.current.files && fileRef.current.files[0];
    if (!file) return toast("ჯერ აირჩიე PDF ფაილი", true);
    setResult({ text: "მუშავდება..." });
    const token = await getToken();
    if (!token) return setResult({ err: "სესია არ არის — თავიდან შედი" });
    const fd = new FormData();
    fd.append("file", file);
    try {
      const res = await fetch(cfg.API_BASE + "/shops/" + shopId + "/knowledge", {
        method: "POST",
        headers: { Authorization: "Bearer " + token, "ngrok-skip-browser-warning": "1" },
        body: fd,
      });
      const data = await res.json().catch(() => null);
      if (res.ok) {
        setResult({ ok: "✅ PDF ჩაიტვირთა — ბოტი ახლა ამ ინფოს გამოიყენებს" });
        if (fileRef.current) fileRef.current.value = "";
        await loadShops(shopId);
      } else {
        const d = data && data.detail;
        setResult({ err: "⚠️ " + (typeof d === "string" ? d : d ? JSON.stringify(d) : "შეცდომა (HTTP " + res.status + ")") });
      }
    } catch (err) {
      setResult({ err: "⚠️ ატვირთვა ვერ მოხერხდა: " + err.message });
    }
  }

  async function clear() {
    if (!shopId || !confirm("წავშალო ატვირთული PDF-ცოდნა?")) return;
    try {
      await api("/shops/" + shopId + "/knowledge", "DELETE");
      toast("ცოდნა წაიშალა");
      await loadShops(shopId);
    } catch (err) {
      toast(err.message, true);
    }
  }

  return (
    <div className={"card" + (allowed ? "" : " locked")}>
      <h2>📚 ბოტის ცოდნა (PDF)</h2>
      {!allowed && (
        <div className="tier-lock">
          🔒 ეს ფუნქცია ფასიან პაკეტშია ხელმისაწვდომი — განაახლე პაკეტი ზემოთ.
        </div>
      )}
      <p className="import-hint">
        ატვირთე PDF (მიწოდების პირობები, გარანტია, ხშირი კითხვები...) — ბოტი ამ ინფორმაციას
        გამოიყენებს კლიენტებთან პასუხისას. მხოლოდ ტექსტური PDF (არა დასკანერებული/ფოტო).
      </p>
      <div className="import-hint">
        {fname ? (
          <span className="fb-connected">📄 ატვირთულია: {fname}</span>
        ) : (
          <span className="fb-disconnected">დოკუმენტი ჯერ არ არის ატვირთული.</span>
        )}
      </div>
      <div className="import-row">
        <input type="file" accept=".pdf,application/pdf" ref={fileRef} disabled={!allowed} />
        <button className="btn btn-primary" disabled={!allowed} onClick={upload}>ატვირთვა</button>
        {fname && <button className="btn btn-danger" onClick={clear}>წაშლა</button>}
      </div>
      {result && (
        <div className={"import-result" + (result.ok ? " import-ok" : result.err ? " import-err" : "")}>
          {result.ok || result.err || result.text}
        </div>
      )}
    </div>
  );
}

/* ---------- მონაცემების ექსპორტი ---------- */
function ExportCard() {
  const toast = useToast();
  const { shopId } = useShopData();
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);

  async function run() {
    if (!shopId) return toast("ჯერ აირჩიე მაღაზია", true);
    setBusy(true);
    setResult({ text: "მუშავდება..." });
    const token = await getToken();
    if (!token) {
      setBusy(false);
      return setResult({ err: "სესია არ არის — თავიდან შედი" });
    }
    try {
      const res = await fetch(cfg.API_BASE + "/shops/" + shopId + "/export", {
        headers: { Authorization: "Bearer " + token, "ngrok-skip-browser-warning": "1" },
      });
      if (!res.ok) {
        const data = await res.json().catch(() => null);
        return setResult({ err: "⚠️ " + ((data && data.detail) || "შეცდომა (HTTP " + res.status + ")") });
      }
      const blob = await res.blob();
      let fname = "chatassist-export.json";
      const cd = res.headers.get("Content-Disposition");
      const m = cd && cd.match(/filename="([^"]+)"/);
      if (m) fname = m[1];
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = fname;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      setResult({ ok: "✅ ჩამოიტვირთა: " + fname });
    } catch (err) {
      setResult({ err: "⚠️ ჩამოტვირთვა ვერ მოხერხდა: " + err.message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card">
      <h2>📥 ჩემი მონაცემები</h2>
      <p className="import-hint">
        ჩამოტვირთე შენი მაღაზია, პროდუქტები და შეკვეთები ერთ ფაილად (JSON) —
        სარეზერვო ასლისთვის ან სხვა სერვისზე გადასატანად.
      </p>
      <button className={"btn btn-ghost" + (busy ? " is-loading" : "")} disabled={busy} onClick={run}>
        📥 ჩამოტვირთვა (JSON)
      </button>
      {result && (
        <div className={"import-result" + (result.ok ? " import-ok" : result.err ? " import-err" : "")}>
          {result.ok || result.err || result.text}
        </div>
      )}
    </div>
  );
}

/* ---------- ბოტის ანალიტიკა ---------- */
function AnalyticsCard() {
  const { analytics } = useShopData();
  let body;
  if (analytics === "loading" || analytics == null) body = "იტვირთება...";
  else if (analytics === "error")
    body = <span className="fb-disconnected">ანალიტიკა ვერ ჩაიტვირთა.</span>;
  else if (!analytics.total_conversations)
    body = (
      <span className="fb-disconnected">
        ჯერ საუბრები არ არის — კლიენტები ბოტთან რომ დაიწყებენ წერას, აქ გამოჩნდება.
      </span>
    );
  else
    body = (
      <>
        <div className="analytics-nums">
          🗨️ საუბრები: <b>{analytics.total_conversations}</b> · 🔔 ყურადღება სჭირდება:{" "}
          <b>{analytics.needs_attention || 0}</b>
        </div>
        {(analytics.top_terms || []).length > 0 && (
          <>
            <div className="analytics-lbl">ხშირად კითხულობენ:</div>
            <div className="term-chips">
              {analytics.top_terms.map((t, i) => (
                <span className="term-chip" key={i}>{t.term} <b>{t.count}</b></span>
              ))}
            </div>
          </>
        )}
        {(analytics.recent_questions || []).length > 0 && (
          <>
            <div className="analytics-lbl">ბოლო შეკითხვები:</div>
            {analytics.recent_questions.slice(0, 15).map((q, i) => (
              <div className="q-item" key={i}>💬 {q}</div>
            ))}
          </>
        )}
      </>
    );

  return (
    <div className="card">
      <h2>📊 ბოტის ანალიტიკა</h2>
      <p className="import-hint">რას კითხულობენ კლიენტები ბოტთან და რომელ საუბარს სჭირდება შენი ჩართვა.</p>
      <div className="analytics-body">{body}</div>
    </div>
  );
}
