import { useEffect, useRef, useState } from "react";

// secret / QR / კოდი — არასდროს იწერება console-ში ან storage-ში.
const LOAD_ERR = "ორფაქტორიანი შესვლის ჩატვირთვა ვერ მოხერხდა — განაახლე გვერდი.";
const VERIFY_ERR = "კოდი არასწორია ან ვადა გაუვიდა — სცადე ხელახლა.";

function useMounted() {
  const ref = useRef(true);
  useEffect(() => {
    ref.current = true;
    return () => { ref.current = false; };
  }, []);
  return ref;
}

export default function MfaGate({ mfa, onVerified }) {
  const mounted = useMounted();
  // setup: null = იტვირთება, "error", {mode, factorId, qr, secret}
  const [setup, setSetup] = useState(null);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const { data, error } = await mfa.listFactors();
        if (error) throw error;
        const verified = (data?.totp || []).find((f) => f.status === "verified");
        if (verified) {
          if (!cancelled) setSetup({ mode: "challenge", factorId: verified.id });
          return;
        }
        const stale = (data?.all || []).filter((f) => f.factor_type === "totp" && f.status === "unverified");
        for (const f of stale) {
          try { await mfa.unenroll({ factorId: f.id }); } catch { /* best-effort */ }
        }
        const { data: en, error: enErr } = await mfa.enroll({ factorType: "totp" });
        if (enErr) throw enErr;
        if (!cancelled) setSetup({ mode: "enroll", factorId: en.id, qr: en.totp.qr_code, secret: en.totp.secret });
      } catch {
        if (!cancelled) setSetup("error");
      }
    })();
    return () => { cancelled = true; };
  }, [mfa]);

  if (setup === "error") return <div className="import-err" role="alert">{LOAD_ERR}</div>;
  if (!setup) return <div className="empty-state" role="status">იტვირთება…</div>;

  async function submit(e) {
    e.preventDefault();
    if (code.length !== 6 || busy) return;
    setBusy(true);
    setErr("");
    try {
      const ch = await mfa.challenge({ factorId: setup.factorId });
      if (ch.error) throw ch.error;
      const v = await mfa.verify({ factorId: setup.factorId, challengeId: ch.data.id, code });
      if (v.error) throw v.error;
      if (!mounted.current) return;
      setCode("");
      setSetup(null);
      onVerified();
    } catch {
      if (!mounted.current) return;
      setCode("");
      setErr(VERIFY_ERR);
      setBusy(false);
    }
  }

  const enroll = setup.mode === "enroll";
  return (
    <form className="card" onSubmit={submit}>
      <h2>{enroll ? "🔐 ჩართე ორფაქტორიანი შესვლა (MFA)" : "🔐 შეიყვანე ავთენტიფიკატორის კოდი"}</h2>
      {enroll && (
        <>
          <p className="import-hint">
            დაასკანერე QR კოდი ავთენტიფიკატორის აპით (Google Authenticator, 1Password, Authy …) და შეიყვანე 6-ნიშნა კოდი. გასაღები შეინახე პაროლების მენეჯერში — ტელეფონის დაკარგვისას დაგჭირდება.
          </p>
          <img alt="QR კოდი" src={setup.qr} width="180" height="180" />
          <p className="import-hint">ან ჩაწერე გასაღები ხელით: <code>{setup.secret}</code></p>
        </>
      )}
      <label>
        6-ნიშნა კოდი
        <input
          type="text"
          inputMode="numeric"
          autoComplete="one-time-code"
          maxLength={6}
          value={code}
          onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
          autoFocus
        />
      </label>
      {err && <div className="import-err" role="alert">{err}</div>}
      <button type="submit" className={"btn btn-primary" + (busy ? " is-loading" : "")} disabled={code.length !== 6 || busy}>
        დადასტურება
      </button>
    </form>
  );
}

export function MfaStatus({ mfa }) {
  // null = იტვირთება/შეცდომა (არაფერი), "on", "off", "enrolling"
  const [state, setState] = useState(null);

  useEffect(() => {
    let cancelled = false;
    mfa.listFactors().then(({ data, error }) => {
      if (cancelled || error) return;
      setState((data?.totp || []).some((f) => f.status === "verified") ? "on" : "off");
    }).catch(() => {});
    return () => { cancelled = true; };
  }, [mfa]);

  if (!state) return null;
  if (state === "enrolling") return <MfaGate mfa={mfa} onVerified={() => setState("on")} />;
  return (
    <div className="card">
      {state === "on" ? (
        <span>🔐 ორფაქტორიანი შესვლა ჩართულია ✓</span>
      ) : (
        <>
          <span>🔐 ორფაქტორიანი შესვლა ჯერ არ არის ჩართული</span>{" "}
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setState("enrolling")}>ჩართვა</button>
        </>
      )}
    </div>
  );
}
