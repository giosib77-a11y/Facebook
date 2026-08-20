/* სესიის მდგომარეობა — განზრახ React-ის გარეთ (იგივე მიზეზი, რაც fbConnect.js-ში).
 *
 * ⚠️ ორი დახვეწილობა, რომელიც app.js-იდან ზუსტად უნდა შენარჩუნდეს:
 *
 * 1. „მყისიერი gate": თუ localStorage-ში token დევს, პანელს მაშინვე ვაჩვენებთ,
 *    getSession()-ს არ ველოდებით. ის ასინქრონულია და ზოგჯერ 2-3 წამს აყოვნებს —
 *    ამის გარეშე login-ის ფორმა „ციმციმებს" და მერე ქრება.
 *
 * 2. გამოსვლა მხოლოდ მაშინ, როცა token ნამდვილად აღარ არის:
 *    onAuthStateChange refresh-ის დროს ხანდახან ცარიელ session-ს ისვრის.
 *    თუ ამაზე login-ზე გადავრთეთ, მომხმარებელი შემთხვევით „გამოვარდება".
 *    ამიტომ ცარიელ session-ზე ჯერ storage-ს ვამოწმებთ.
 */
import { sb, readStoredToken } from "./supabase.js";

let session = null;
let signedIn = !!readStoredToken(); // მყისიერი gate (იხ. #1)
const listeners = new Set();

function emit() {
  listeners.forEach((fn) => fn());
}

function apply(s) {
  if (s) {
    session = s;
    signedIn = true;
  } else {
    if (readStoredToken()) return; // იხ. #2 — ჯერ არ გამოვიყვანოთ
    session = null;
    signedIn = false;
  }
  emit();
}

sb.auth.onAuthStateChange((_event, s) => apply(s));
sb.auth.getSession().then(({ data }) => apply(data.session)).catch(() => {});

export function subscribeSession(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export const getSignedIn = () => signedIn;
export const getSession = () => session;

/** გამოსვლა — scope:"local" ქსელის გარეშე, მყისიერი; მერე გვერდი თავიდან იტვირთება */
export async function signOut() {
  try {
    await sb.auth.signOut({ scope: "local" });
  } catch {
    /* ლოკალური სესია მაინც ქრება */
  }
  window.location.reload();
}
