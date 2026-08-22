/* Facebook-ის დაკავშირება — popup + postMessage.
 *
 * ⚠️⚠️ ეს ფაილი განზრახ React-ის გარეთაა (იხ. REACT_MIGRATION.md, ნაწილი 3.1).
 * ეს არის ზუსტად ის ნაკადი, რომელიც App Review-ს ვიდეოშია — თუ გატყდა, უარყოფაა.
 *
 * ორი წესი, რომელიც არ უნდა დაირღვეს:
 *  1. `message`-ლისენერი რეგისტრირდება მოდულის ჩატვირთვისთანავე, არა useEffect-ში.
 *     თუ popup React-ის mount-მდე მოასწრებს პასუხს, შეტყობინება დაიკარგებოდა და
 *     პანელი ვერასდროს გაიგებდა, რომ გვერდი დაუკავშირდა (შეცდომის გარეშე!).
 *     ქვემოთ ბუფერია — mount-მდე მოსული შეტყობინება ინახება და subscribe-ზე მიეწოდება.
 *     StrictMode-ის ორმაგი mount-იც უვნებელია (cleanup→resubscribe ბუფერს არ კარგავს).
 *  2. `window.open` სინქრონულად, click-ის დამმუშავებელში, `await`-მდე.
 *     თუ წინ await გაჩნდა, ბრაუზერი popup-ს დაბლოკავს.
 */

const pending = [];
let handler = null;

window.addEventListener("message", (e) => {
  const d = e.data;
  if (!d || typeof d !== "object" || !d.fb) return;
  if (handler) handler(d);
  else pending.push(d); // React ჯერ არ დამონტაჟებულა — ვინახავთ
});

/** React აქედან იღებს შედეგს; mount-მდე დაგროვილი მაშინვე მიეწოდება */
export function subscribeFbResult(fn) {
  handler = fn;
  while (pending.length) fn(pending.shift());
  return () => {
    if (handler === fn) handler = null;
  };
}

/* popup დაბლოკილის fallback — backend გვაბრუნებს `?fb=...`-ით.
 * მოდულის დონეზე ვიჭერთ მაშინვე, რომ URL-ის გასუფთავებამდე არ დაიკარგოს. */
export const fbRedirectResult = (() => {
  const params = new URLSearchParams(window.location.search);
  const fb = params.get("fb");
  if (!fb) return null;
  const out = { fb, page: params.get("page"), reason: params.get("reason") };
  window.history.replaceState({}, "", window.location.pathname);
  return out;
})();

/** შედეგის ერთიანი გამზადება toast-ისთვის (popup და fallback ერთნაირად) */
export function fbResultMessage(d) {
  if (d.fb === "connected") {
    return { msg: "Facebook გვერდი დაკავშირდა: " + (d.page || ""), isErr: false, reload: true };
  }
  if (d.fb === "no_pages") {
    return { msg: "ვერ მოიძებნა Facebook გვერდი ამ ანგარიშზე", isErr: true, reload: false };
  }
  // backend-ის ცნობილი მიზეზები → გასაგები ქართული ტექსტი
  const REASONS = {
    page_taken: "ეს Facebook გვერდი უკვე დაკავშირებულია სხვა მაღაზიაზე. ჯერ იქ გათიშე.",
    shop_not_found: "მაღაზია ვერ მოიძებნა — განაახლე გვერდი და სცადე ხელახლა.",
    save_failed: "გვერდის შენახვა ვერ მოხერხდა — სცადე ცოტა ხანში.",
    invalid_state: "ბმულს ვადა გაუვიდა — დააჭირე „დაკავშირებას“ ხელახლა.",
    missing_code: "Facebook-მა დაკავშირება არ დაასრულა — სცადე ხელახლა.",
  };
  const known = REASONS[d.reason];
  return {
    msg: known || "დაკავშირება ვერ მოხერხდა: " + (d.reason || d.fb),
    isErr: true,
    reload: false,
  };
}

/**
 * popup-ს ხსნის და FB-ის login URL-ზე გადაჰყავს.
 * ⚠️ პირველი ხაზი (window.open) სინქრონულია — არ დაამატო await მის წინ.
 */
export async function startConnect(shopId, api) {
  const popup = window.open("about:blank", "fbconnect", "width=600,height=720");
  let res;
  try {
    res = await api("/facebook/connect/start?shop_id=" + encodeURIComponent(shopId));
  } catch (err) {
    if (popup) popup.close();
    throw err;
  }
  if (popup) popup.location.href = res.login_url;
  else window.location.href = res.login_url; // popup დაიბლოკა → fallback redirect
}
