import { createContext, useCallback, useContext, useState } from "react";

/* ---------- Toast ---------- */
const ToastCtx = createContext(() => {});
export const useToast = () => useContext(ToastCtx);

export function ToastProvider({ children }) {
  const [t, setT] = useState(null);
  const toast = useCallback((msg, isErr) => {
    setT({ msg, isErr });
    setTimeout(() => setT(null), 3500);
  }, []);
  return (
    <ToastCtx.Provider value={toast}>
      <div id="toast" className={"toast " + (t ? (t.isErr ? "toast-err" : "toast-ok") : "hidden")}>
        {t ? t.msg : ""}
      </div>
      {children}
    </ToastCtx.Provider>
  );
}

/* ---------- საერთო ელემენტები ---------- */

export function BrandMark() {
  return (
    <span className="brand-mark">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path d="M5 8h14l-1.1 11.2A2.5 2.5 0 0 1 15.4 21.5H8.6A2.5 2.5 0 0 1 6.1 19.2L5 8z" fill="#fff" />
        <path d="M9 8V6.5a3 3 0 0 1 6 0V8" fill="none" stroke="#fff" strokeWidth="1.7" strokeLinecap="round" />
      </svg>
    </span>
  );
}

/** ჩატვირთვის skeleton — იგივე კლასები, რაც ძველ კოდში */
export function Skeleton({ n = 3 }) {
  return (
    <>
      {Array.from({ length: n }, (_, i) => (
        <div className="skel-item" key={i}>
          <div className="skel skel-line lg" />
          <div className="skel skel-line sm" />
        </div>
      ))}
    </>
  );
}

/** ღილაკი spinner-ით — btnBusy-ს ეკვივალენტი */
export function BusyButton({ busy, className = "btn btn-primary", children, ...rest }) {
  return (
    <button className={className + (busy ? " is-loading" : "")} disabled={busy} {...rest}>
      {children}
    </button>
  );
}
