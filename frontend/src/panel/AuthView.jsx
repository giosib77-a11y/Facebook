import { useState } from "react";
import { sb, translateAuthError, resetRedirectUrl } from "./supabase.js";
import { BrandMark, BusyButton, useToast } from "./ui.jsx";

export default function AuthView() {
  const toast = useToast();
  const [mode, setMode] = useState("login"); // login | register | forgot
  const [busy, setBusy] = useState(false);
  const [f, setF] = useState({ email: "", pass: "", regEmail: "", regPass: "", regPass2: "", forgotEmail: "" });
  const upd = (k) => (e) => setF((s) => ({ ...s, [k]: e.target.value }));

  async function onLogin(e) {
    e.preventDefault();
    setBusy(true);
    try {
      const { error } = await sb.auth.signInWithPassword({
        email: f.email.trim(),
        password: f.pass,
      });
      if (error) return toast(translateAuthError(error.message), true);
      toast("მოგესალმებით!");
    } finally {
      setBusy(false);
    }
  }

  async function onRegister(e) {
    e.preventDefault();
    if (f.regPass !== f.regPass2) return toast("პაროლები არ ემთხვევა", true);
    setBusy(true);
    try {
      const { data, error } = await sb.auth.signUp({
        email: f.regEmail.trim(),
        password: f.regPass,
      });
      if (error) return toast(translateAuthError(error.message), true);
      if (data.session) toast("რეგისტრაცია წარმატებულია!");
      else toast("რეგისტრაცია მიღებულია — შეამოწმე ელ-ფოსტა დასადასტურებლად, შემდეგ შედი.");
    } finally {
      setBusy(false);
    }
  }

  async function onForgot(e) {
    e.preventDefault();
    const email = f.forgotEmail.trim();
    if (!email) return;
    const { error } = await sb.auth.resetPasswordForEmail(email, {
      redirectTo: resetRedirectUrl(),
    });
    if (error) return toast(translateAuthError(error.message), true);
    toast("აღდგენის ბმული გაიგზავნა — შეამოწმე ელ-ფოსტა 📧");
    setMode("login");
  }

  return (
    <section className="auth-view">
      <div className="card auth-card">
        <a href="landing.html" className="auth-back">← მთავარ გვერდზე</a>
        <h1 className="auth-title"><BrandMark /> ChatAssist</h1>
        <p className="auth-subtitle">გამყიდველის პანელი</p>

        {mode !== "forgot" && (
          <div className="tabs">
            <button className={"tab" + (mode === "login" ? " active" : "")} onClick={() => setMode("login")}>
              შესვლა
            </button>
            <button className={"tab" + (mode === "register" ? " active" : "")} onClick={() => setMode("register")}>
              რეგისტრაცია
            </button>
          </div>
        )}

        {mode === "login" && (
          <form className="auth-form" onSubmit={onLogin}>
            <label>
              ელ-ფოსტა
              <input type="email" required autoComplete="email" placeholder="you@example.com"
                value={f.email} onChange={upd("email")} />
            </label>
            <label>
              პაროლი
              <input type="password" required autoComplete="current-password" placeholder="••••••••"
                value={f.pass} onChange={upd("pass")} />
            </label>
            <BusyButton busy={busy} type="submit">შესვლა</BusyButton>
            <a href="#" className="auth-link" onClick={(e) => {
              e.preventDefault();
              setF((s) => ({ ...s, forgotEmail: s.email }));
              setMode("forgot");
            }}>პაროლი დაგავიწყდა?</a>
          </form>
        )}

        {mode === "register" && (
          <form className="auth-form" onSubmit={onRegister}>
            <label>
              ელ-ფოსტა
              <input type="email" required autoComplete="email" placeholder="you@example.com"
                value={f.regEmail} onChange={upd("regEmail")} />
            </label>
            <label>
              პაროლი (მინ. 6 სიმბოლო)
              <input type="password" required minLength={6} autoComplete="new-password" placeholder="••••••••"
                value={f.regPass} onChange={upd("regPass")} />
            </label>
            <label>
              გაიმეორე პაროლი
              <input type="password" required minLength={6} autoComplete="new-password" placeholder="••••••••"
                value={f.regPass2} onChange={upd("regPass2")} />
            </label>
            <BusyButton busy={busy} type="submit">რეგისტრაცია</BusyButton>
          </form>
        )}

        {mode === "forgot" && (
          <form className="auth-form" onSubmit={onForgot}>
            <p className="import-hint">ჩაწერე ელ-ფოსტა — გამოგიგზავნით პაროლის აღდგენის ბმულს.</p>
            <label>
              ელ-ფოსტა
              <input type="email" required autoComplete="email" placeholder="you@example.com"
                value={f.forgotEmail} onChange={upd("forgotEmail")} />
            </label>
            <button type="submit" className="btn btn-primary">აღდგენის ბმულის გაგზავნა</button>
            <a href="#" className="auth-link" onClick={(e) => { e.preventDefault(); setMode("login"); }}>
              ← უკან შესვლაზე
            </a>
          </form>
        )}
      </div>
    </section>
  );
}
