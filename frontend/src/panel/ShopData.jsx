import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api } from "./api.js";
import { useToast } from "./ui.jsx";

const Ctx = createContext(null);
export const useShopData = () => useContext(Ctx);

export function ShopDataProvider({ children }) {
  const toast = useToast();
  const [shops, setShops] = useState([]);
  const [shopId, setShopId] = useState(null);
  const [products, setProducts] = useState([]);
  const [orders, setOrders] = useState([]);
  const [orderFilter, setOrderFilter] = useState("");
  const [attention, setAttention] = useState([]);
  const [usage, setUsage] = useState(null);
  const [analytics, setAnalytics] = useState(null);
  const [loadingProducts, setLoadingProducts] = useState(false);
  const [loadingOrders, setLoadingOrders] = useState(false);

  const currentShop = shops.find((s) => s.id === shopId) || null;

  /* ---------- ჩამტვირთველები ---------- */
  const loadProducts = useCallback(async (id) => {
    if (!id) return setProducts([]);
    setLoadingProducts(true);
    try {
      setProducts(await api("/products?shop_id=" + encodeURIComponent(id)));
    } catch (e) {
      toast("პროდუქტები ვერ ჩაიტვირთა: " + e.message, true);
    } finally {
      setLoadingProducts(false);
    }
  }, [toast]);

  const loadOrders = useCallback(async (id, filter) => {
    if (!id) return setOrders([]);
    setLoadingOrders(true);
    try {
      // ⚠️ რევიუ P2-14: shop_id აუცილებლად უნდა გადავცეთ, თორემ backend
      // მფლობელის ყველა მაღაზიის შეკვეთას აბრუნებს (ძველ app.js-შიც ასე იყო).
      const qs = new URLSearchParams({ shop_id: id });
      if (filter) qs.set("status", filter);
      setOrders(await api("/orders?" + qs.toString()));
    } catch (e) {
      toast("შეკვეთები ვერ ჩაიტვირთა: " + e.message, true);
    } finally {
      setLoadingOrders(false);
    }
  }, [toast]);

  const loadAttention = useCallback(async (id) => {
    if (!id) return setAttention([]);
    try {
      const d = await api("/shops/" + id + "/attention");
      setAttention((d && d.items) || []);
    } catch {
      setAttention([]); // ჩავარდნაზე ბარათი უბრალოდ არ ჩანს (ძველი ქცევა)
    }
  }, []);

  const loadUsage = useCallback(async (id) => {
    if (!id) return setUsage(null);
    try {
      setUsage(await api("/shops/" + id + "/usage"));
    } catch {
      setUsage(null);
    }
  }, []);

  const loadAnalytics = useCallback(async (id) => {
    if (!id) return setAnalytics(null);
    setAnalytics("loading");
    try {
      setAnalytics(await api("/shops/" + id + "/analytics"));
    } catch {
      setAnalytics("error");
    }
  }, []);

  /** ყველაფრის განახლება მიმდინარე მაღაზიისთვის */
  const reloadAll = useCallback(
    (id, filter = orderFilter) => {
      loadUsage(id);
      loadAnalytics(id);
      return Promise.all([loadProducts(id), loadOrders(id, filter), loadAttention(id)]);
    },
    [loadProducts, loadOrders, loadAttention, loadUsage, loadAnalytics, orderFilter]
  );

  const loadShops = useCallback(
    async (selectId) => {
      const list = await api("/shops/me");
      setShops(list);
      const next = selectId && list.some((s) => s.id === selectId) ? selectId : (list[0] ? list[0].id : null);
      setShopId(next);
      await reloadAll(next);
      return list;
    },
    [reloadAll]
  );

  // პირველი ჩატვირთვა
  useEffect(() => {
    loadShops().catch((e) => toast("მონაცემების ჩატვირთვა ვერ მოხერხდა: " + e.message, true));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const selectShop = useCallback(
    (id) => {
      setShopId(id || null);
      reloadAll(id || null);
    },
    [reloadAll]
  );

  const changeOrderFilter = useCallback(
    (f) => {
      setOrderFilter(f);
      loadOrders(shopId, f);
    },
    [loadOrders, shopId]
  );

  const value = {
    shops, shopId, currentShop, selectShop, loadShops,
    products, loadProducts: () => loadProducts(shopId), loadingProducts,
    orders, orderFilter, changeOrderFilter, loadOrders: () => loadOrders(shopId, orderFilter), loadingOrders,
    attention, loadAttention: () => loadAttention(shopId),
    usage, loadUsage: () => loadUsage(shopId),
    analytics,
    reloadAll: () => reloadAll(shopId),
  };

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
