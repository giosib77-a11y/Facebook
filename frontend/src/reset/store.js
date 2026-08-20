/* პაროლის აღდგენის სესია — განზრახ React-ის გარეთ.
 *
 * ⚠️ კრიტიკული: Supabase კლიენტი და onAuthStateChange რეგისტრირდება მოდულის
 * ჩატვირთვისთანავე, არა useEffect-ში. მიზეზი: detectSessionInUrl:true URL-ის
 * hash-ს ამუშავებს კლიენტის შექმნისთანავე და PASSWORD_RECOVERY event-ს ერთხელ
 * ისვრის — თუ ლისენერი mount-ის შემდეგ დარეგისტრირდა, event იკარგება და
 * მომხმარებელი „ბმული მოწმდება..."-ზე ჩარჩება. StrictMode-ის ორმაგი mount-იც
 * ვერაფერს დააკლებს, რადგან აქ React საერთოდ არ მონაწილეობს.
 */
import { createClient } from "@supabase/supabase-js";

const cfg = window.APP_CONFIG;

// ცალკე კლიენტი — პანელისგან განსხვავებით detectSessionInUrl:true,
// რადგან email-ის ბმულიდან recovery token უნდა წაიკითხოს.
export const sb = createClient(cfg.SUPABASE_URL, cfg.SUPABASE_ANON_KEY, {
  auth: { detectSessionInUrl: true, persistSession: false, flowType: "implicit" },
});

let status = "checking"; // "checking" | "ready" | "error"
let errorMsg = "";
const listeners = new Set();

/** პირველი შედეგი იმარჯვებს (ძველი კოდის `ready` დამცავის ეკვივალენტი) */
function settle(next, msg = "") {
  if (status !== "checking") return;
  status = next;
  errorMsg = msg;
  listeners.forEach((fn) => fn());
}

sb.auth.onAuthStateChange((event, session) => {
  if (event === "PASSWORD_RECOVERY" || session) settle("ready");
});

// fallback — თუ event არ ესროლა, 2.5 წმ-ში getSession-ით ვამოწმებთ
setTimeout(async () => {
  if (status !== "checking") return;
  try {
    const r = await sb.auth.getSession();
    if (r.data && r.data.session) settle("ready");
    else settle("error", "ბმული არასწორია ან ვადაგასულია. სცადე პაროლის აღდგენა თავიდან.");
  } catch {
    settle("error", "ბმული ვერ დამუშავდა. სცადე თავიდან.");
  }
}, 2500);

export function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}
export const getStatus = () => status;
export const getError = () => errorMsg;
