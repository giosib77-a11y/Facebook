import { useEffect, useState, useSyncExternalStore } from "react";
import { api } from "./api.js";
import { subscribeSession, getSignedIn, getSession, signOut } from "./session.js";
import { subscribeFbResult, fbRedirectResult, fbResultMessage } from "./fbConnect.js";
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
            <Dashboard />
          </main>
          <FbResultBridge />
        </ShopDataProvider>
      ) : (
        <main className="container">
          <AuthView />
        </main>
      )}
      <footer className="panel-footer">
        დახმარება გჭირდება? მოგვწერე{" "}
        <a href="mailto:chatassistbusiness@gmail.com">chatassistbusiness@gmail.com</a>
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
      .catch(() => {}); // არა ადმინი — ღილაკი დამალული რჩება
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

  useEffect(() => {
    // popup-დაბლოკილის fallback (?fb=...) — მოდულის ჩატვირთვისას დაფიქსირდა
    if (fbRedirectResult) {
      const r = fbResultMessage(fbRedirectResult);
      toast(r.msg, r.isErr);
      if (r.reload) loadShops(shopId);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    return subscribeFbResult((d) => {
      const r = fbResultMessage(d);
      toast(r.msg, r.isErr);
      if (r.reload) loadShops(shopId);
    });
  }, [toast, loadShops, shopId]);

  return null;
}
