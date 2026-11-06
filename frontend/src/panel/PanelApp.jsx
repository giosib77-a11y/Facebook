import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import { api } from "./api.js";
import { isMfaRequired } from "../lib/adminMfa.js";
import { subscribeSession, getSignedIn, getSession, signOut } from "./session.js";
import { subscribeFbResult, fbRedirectResult, fbResultMessage, parsePages, selectPage } from "./fbConnect.js";
import FbPagePicker from "./FbPagePicker.jsx";
import { ShopDataProvider, useShopData } from "./ShopData.jsx";
import { ToastProvider, BrandMark, useToast } from "./ui.jsx";
import AuthView from "./AuthView.jsx";
import Dashboard from "./Dashboard.jsx";

export default function PanelApp() {
  const signedIn = useSyncExternalStore(subscribeSession, getSignedIn);

  return (
    <ToastProvider>
      {signedIn ? (
        <ShopDataProvider>
          <Header />
          <main className="container">
            <FbResultBridge />
            <Dashboard />
          </main>
        </ShopDataProvider>
      ) : (
        <main className="container">
          <AuthView />
        </main>
      )}
      <footer className="panel-footer">
        დახმარება გჭირდება? მოგვწერე{" "}
        <a href="mailto:chatassistbusiness@gmail.com">chatassistbusiness@gmail.com</a>
        <div className="panel-legal">
          <p>Owned and operated by Individual Entrepreneur Jemali Sibashvili</p>
          <p>Address: Georgia, Rustavi city, Pavle Todria II alley, N2, apartment N19</p>
          <p>Phone: <a href="tel:+995557182018">+995 557 18 20 18</a></p>
          <p>Email: <a href="mailto:chatassistbusiness@gmail.com">chatassistbusiness@gmail.com</a></p>
          <p><a href="contact.html">კონტაქტი</a></p>
        </div>
      </footer>
    </ToastProvider>
  );
}

function Header() {
  const session = getSession();
  const [isAdmin, setIsAdmin] = useState(false);

  useEffect(() => {
    api("/admin/check")
      .then(() => setIsAdmin(true))
      .catch((e) => {
        // aal1 ადმინი: MFA-ს 403 — ღილაკი ჩანს (კოდს admin.html-ში შეიყვანს); სხვა — დამალული რჩება
        if (isMfaRequired(e)) setIsAdmin(true);
      });
  }, []);

  return (
    <header className="app-header">
      <div className="brand">
        <BrandMark /> ChatAssist
      </div>
      <div className="header-right">
        <span className="user-email">{session && session.user ? session.user.email : ""}</span>
        {isAdmin && <a href="admin.html" className="btn btn-ghost">🛠 ადმინი</a>}
        <button className="btn btn-ghost" onClick={signOut}>გასვლა</button>
      </div>
    </header>
  );
}

/**
 * Facebook-ის დაკავშირების შედეგი → toast + მაღაზიების განახლება.
 *
 * ⚠️ ლისენერი თვითონ fbConnect.js-შია, მოდულის დონეზე, ბუფერით — ამიტომ mount-ის
 * დაგვიანება უსაფრთხოა: დაგროვილი შეტყობინება subscribe-ზე მაშინვე მოვა.
 */
function FbResultBridge() {
  const toast = useToast();
  const { shopId, loadShops } = useShopData();
  const [choice, setChoice] = useState(null); // { selection, pages } — რამდენიმე გვერდის არჩევა
  const [busyId, setBusyId] = useState(null);

  // ერთი ადგილი popup-ისა და redirect-ის შედეგისთვის
  const handleResult = useCallback(
    (d) => {
      if (d.fb === "choose") {
        const pages = parsePages(d.pages);
        if (pages.length === 0 || !d.selection) {
          toast("დაკავშირება ვერ მოხერხდა. სცადეთ თავიდან.", true);
          return;
        }
        setChoice({ selection: d.selection, pages });
        return;
      }
      const r = fbResultMessage(d);
      toast(r.msg, r.isErr);
      if (r.reload) loadShops(shopId);
    },
    [toast, loadShops, shopId]
  );

  useEffect(() => {
    // popup-დაბლოკილის fallback (?fb=...) — მოდულის ჩატვირთვისას დაფიქსირდა
    if (fbRedirectResult) handleResult(fbRedirectResult);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => subscribeFbResult(handleResult), [handleResult]);

  async function pick(pageId) {
    if (!choice || busyId) return;
    setBusyId(pageId);
    try {
      handleResult(await selectPage(api, choice.selection, pageId));
    } catch (e) {
      toast(e.message, true); // backend-ის ფიქსირებული ქართული ტექსტი (400 / 404 / 503)
    }
    setBusyId(null);
    setChoice(null);
  }

  if (!choice) return null;
  return <FbPagePicker pages={choice.pages} busyId={busyId} onPick={pick} onCancel={() => setChoice(null)} />;
}
