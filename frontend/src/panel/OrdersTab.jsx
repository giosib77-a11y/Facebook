import { useState } from "react";
import { api } from "./api.js";
import { useShopData } from "./ShopData.jsx";
import { Skeleton, useToast } from "./ui.jsx";

export const ORDER_STATUS = {
  new: "ახალი",
  processing: "მუშავდება",
  done: "დასრულებული",
  cancelled: "გაუქმებული",
};

/** ⚠️ URL-კონტრაქტი: order.html იმავე საქაღალდეშია — ბოტი ამ ლინკს მყიდველებს უგზავნის */
export function orderLink(shopId) {
  if (!shopId) return "";
  const dir = location.pathname.replace(/[^/]*$/, "");
  return location.origin + dir + "order.html?shop=" + shopId;
}

export default function OrdersTab() {
  const toast = useToast();
  const { shopId, orders, orderFilter, changeOrderFilter, loadOrders, loadingOrders } = useShopData();
  const link = orderLink(shopId);

  async function copy() {
    if (!link) return;
    try {
      await navigator.clipboard.writeText(link);
      toast("ლინკი დაკოპირდა");
    } catch {
      toast("მონიშნულია — დააკოპირე Ctrl+C-ით");
    }
  }

  async function setStatus(o, status) {
    try {
      await api("/orders/" + o.id, "PATCH", { status });
      toast("სტატუსი განახლდა");
    } catch (err) {
      toast(err.message, true);
      loadOrders();
    }
  }

  async function remove(o) {
    if (!confirm("წავშალო ეს შეკვეთა? მოქმედება შეუქცევადია. (მარაგი არ იცვლება)")) return;
    try {
      await api("/orders/" + o.id, "DELETE");
      toast("შეკვეთა წაიშალა");
      loadOrders();
    } catch (err) {
      toast(err.message, true);
    }
  }

  return (
    <div className="tab-panel">
      <div className="card">
        <h2 style={{ marginTop: 0 }}>🔗 შესაკვეთი ლინკი</h2>
        <p className="import-hint">
          გაუგზავნე კლიენტებს ან დაამაგრე Facebook/Instagram გვერდის ღილაკში. კლიენტი შეავსებს
          და შეკვეთა აქ გამოჩნდება.
        </p>
        <div className="import-row">
          <input type="text" readOnly value={link} />
          <button className="btn btn-ghost" onClick={copy}>კოპირება</button>
          <a href={link || "#"} target="_blank" rel="noreferrer" className="btn btn-ghost">გახსნა</a>
        </div>
      </div>

      <div className="card">
        <div className="list-header">
          <h2>შეკვეთები ({orders.length})</h2>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <select value={orderFilter} onChange={(e) => changeOrderFilter(e.target.value)}>
              <option value="">ყველა</option>
              {Object.entries(ORDER_STATUS).map(([k, v]) => (
                <option value={k} key={k}>{v}</option>
              ))}
            </select>
            <button className="btn btn-ghost" onClick={loadOrders}>↻</button>
          </div>
        </div>

        <div className="product-list">
          {loadingOrders ? (
            <Skeleton n={3} />
          ) : (
            orders.map((o) => (
              <div className={"product-item order-item order-" + o.status} key={o.id}
                style={{ flexDirection: "column", alignItems: "stretch" }}>
                <div className="product-info">
                  <div className="product-name">
                    {o.customer_name} · {Number(o.total).toFixed(2)} ₾
                  </div>
                  <div className="product-meta">
                    {(o.items || []).map((i) => i.name + " ×" + i.quantity).join(", ")}
                  </div>
                  <div className="product-meta">
                    📞 {o.customer_phone || "—"} · 📍 {o.customer_address || "—"}
                  </div>
                  {o.note && <div className="product-meta">📝 {o.note}</div>}
                  <div className="product-meta" style={{ color: "#9ca3af" }}>
                    {new Date(o.created_at).toLocaleString("ka-GE")}
                  </div>
                </div>
                <div className="product-actions"
                  style={{ marginTop: 8, display: "flex", gap: 8, alignItems: "center" }}>
                  <select style={{ flex: 1 }} defaultValue={o.status}
                    onChange={(e) => setStatus(o, e.target.value)}>
                    {Object.entries(ORDER_STATUS).map(([k, v]) => (
                      <option value={k} key={k}>{v}</option>
                    ))}
                  </select>
                  <button className="btn btn-danger btn-sm" onClick={() => remove(o)}>🗑 წაშლა</button>
                </div>
              </div>
            ))
          )}
        </div>
        {!loadingOrders && orders.length === 0 && (
          <p className="empty-state">შეკვეთები ჯერ არ არის.</p>
        )}
      </div>
    </div>
  );
}
