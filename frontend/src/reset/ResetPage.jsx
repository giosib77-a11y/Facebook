import { useState, useSyncExternalStore } from "react";
import { sb, subscribe, getStatus, getError } from "./store.js";

/* ბრენდის ნიშანი — იგივე SVG, რაც სხვა გვერდებზე (ვიზუალური იდენტურობისთვის) */
function BrandMark() {
  return (
    <span className="brand-mark">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path d="M5 8h14l-1.1 11.2A2.5 2.5 0 0 1 15.4 21.5H8.6A2.5 2.5 0 0 1 6.1 19.2L5 8z" fill="#fff" />
        <path d="M9 8V6.5a3 3 0 0 1 6 0V8" fill="none" stroke="#fff" strokeWidth="1.7" strokeLinecap="round" />
      </svg>
    </span>
  );
}

export default function ResetPage() {
  const status = useSyncExternalStore(subscribe, getStatus);
  const [p1, setP1] = useState("");
  const [p2, setP2] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [toast, setToast] = useState(null);

  function showToast(msg, isErr) {
    setToast({ msg, isErr });
    setTimeout(() => setToast(null), 3500);
  }

  async function onSubmit(e) {
    e.preventDefault();
    if (p1 !== p2) {
      showToast("პაროლები არ ემთხვევა", true);
      return;
    }
    setBusy(true);
    try {
      const r = await sb.auth.updateUser({ password: p1 });
      if (r.error) {
        showToast(r.error.message, true);
        setBusy(false);
        return;
      }
      setDone(true);
    } catch (err) {
      showToast(err.message || "შეცდომა", true);
      setBusy(false);
    }
  }

  return (
    <>
      <div
        id="toast"
        className={"toast " + (toast ? (toast.isErr ? "toast-err" : "toast-ok") : "hidden")}
      >
        {toast ? toast.msg : ""}
      </div>

      <main className="container">
        <div className="auth-view">
          <div className="card auth-card">
            <h1 className="auth-title">
              <BrandMark /> ახალი პაროლი
            </h1>

            {status === "checking" && <div className="import-hint">ბმული მოწმდება...</div>}

            {status === "ready" && !done && (
              <form className="auth-form" onSubmit={onSubmit}>
                <label>
                  ახალი პაროლი (მინ. 6 სიმბოლო)
                  <input
                    type="password"
                    required
                    minLength={6}
                    autoComplete="new-password"
                    placeholder="••••••••"
                    autoFocus
                    value={p1}
                    onChange={(e) => setP1(e.target.value)}
                  />
                </label>
                <label>
                  გაიმეორე პაროლი
                  <input
                    type="password"
                    required
                    minLength={6}
                    autoComplete="new-password"
                    placeholder="••••••••"
                    value={p2}
                    onChange={(e) => setP2(e.target.value)}
                  />
                </label>
                <button type="submit" className="btn btn-primary" disabled={busy}>
                  პაროლის შენახვა
                </button>
              </form>
            )}

            {status === "error" && <div className="import-result import-err">{getError()}</div>}

            {done && (
              <div style={{ textAlign: "center" }}>
                <p style={{ color: "var(--ok)", fontWeight: 600 }}>✅ პაროლი შეიცვალა!</p>
                {/* ფარდობითი ლინკი — /panel/index.html-ზე გადადის (URL-კონტრაქტი) */}
                <a href="index.html" className="btn btn-primary" style={{ display: "inline-block" }}>
                  შესვლა
                </a>
              </div>
            )}
          </div>
        </div>
      </main>
    </>
  );
}
