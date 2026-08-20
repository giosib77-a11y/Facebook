import { fmtDate } from "../lib/csv.js";
import { STATUS } from "./constants.js";

export default function ShopDetailModal({ data, onClose }) {
  if (!data) return null;
  const s = data.shop;
  const products = data.products || [];
  const orders = data.orders || [];

  return (
    <div
      className="modal-overlay"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="modal">
        <div className="modal-head">
          <h2>{s.name}</h2>
          <button className="btn btn-ghost" onClick={onClose}>
            დახურვა
          </button>
        </div>
        <p className="import-hint">
          ვალუტა: {s.currency || "GEL"} · ბოტი: {s.bot_enabled ? "ჩართ." : "გამორთ."} · Facebook:{" "}
          {s.facebook_page_id ? "დაკავშ." : "არა"}
        </p>

        <h3>პროდუქტები</h3>
        <div className="admin-table-wrap">
          <table className="admin">
            <thead>
              <tr>
                <th>სახელი</th>
                <th>ფასი</th>
                <th>მარაგი</th>
                <th>სტატ.</th>
              </tr>
            </thead>
            <tbody>
              {products.length === 0 ? (
                <tr>
                  <td colSpan="4" className="empty-state">
                    პროდუქტი არ არის
                  </td>
                </tr>
              ) : (
                products.map((p) => (
                  <tr key={p.id}>
                    <td>{p.name}</td>
                    <td>{Number(p.price).toFixed(2)} ₾</td>
                    <td>{p.quantity}</td>
                    <td>{p.is_active ? "აქტიური" : "გამორთ."}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        <h3>ბოლო შეკვეთები</h3>
        <div className="admin-table-wrap">
          <table className="admin">
            <thead>
              <tr>
                <th>კლიენტი</th>
                <th>ჯამი</th>
                <th>სტატ.</th>
                <th>თარიღი</th>
              </tr>
            </thead>
            <tbody>
              {orders.length === 0 ? (
                <tr>
                  <td colSpan="4" className="empty-state">
                    შეკვეთა არ არის
                  </td>
                </tr>
              ) : (
                orders.map((o) => (
                  <tr key={o.id}>
                    <td>{o.customer_name}</td>
                    <td>{Number(o.total).toFixed(2)} ₾</td>
                    <td>{STATUS[o.status] || o.status}</td>
                    <td>{fmtDate(o.created_at)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
