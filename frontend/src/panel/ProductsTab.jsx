import { useMemo, useRef, useState } from "react";
import { api } from "./api.js";
import { uploadProductImage } from "./images.js";
import { IMPORT_FIELDS, previewImport, confirmImport, buildMapping } from "./importApi.js";
import { useShopData } from "./ShopData.jsx";
import { Skeleton, useToast } from "./ui.jsx";

const EMPTY = {
  id: "", name: "", price: "0", quantity: "0", sku: "", description: "",
  is_active: true, image_url: "",
};

export default function ProductsTab() {
  const toast = useToast();
  const { shopId, products, loadProducts, loadingProducts, usage } = useShopData();

  const [form, setForm] = useState(EMPTY);
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(""); // ლოკალური objectURL ან არსებული URL
  const [busy, setBusy] = useState(false);
  const [q, setQ] = useState("");
  const fileRef = useRef(null);
  const upd = (k) => (e) =>
    setForm((s) => ({ ...s, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value }));

  const editing = !!form.id;
  const bulkAllowed = !usage || usage.bulk_import !== false;

  function reset() {
    setForm(EMPTY);
    setFile(null);
    setPreview("");
    if (fileRef.current) fileRef.current.value = "";
  }

  function startEdit(p) {
    setForm({
      id: p.id, name: p.name, price: String(p.price), quantity: String(p.quantity),
      sku: p.sku || "", description: p.description || "", is_active: p.is_active,
      image_url: p.image_url || "",
    });
    setFile(null);
    setPreview(p.image_url || "");
    if (fileRef.current) fileRef.current.value = "";
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function pickFile(e) {
    const f = e.target.files && e.target.files[0];
    if (!f) return;
    setFile(f);
    setPreview(URL.createObjectURL(f));
  }

  function clearImage() {
    setFile(null);
    setPreview("");
    setForm((s) => ({ ...s, image_url: "" }));
    if (fileRef.current) fileRef.current.value = "";
  }

  async function onSubmit(e) {
    e.preventDefault();
    if (!shopId) return toast("ჯერ შექმენი ან აირჩიე მაღაზია", true);
    setBusy(true);
    try {
      let imageUrl = form.image_url || null;
      if (file) imageUrl = await uploadProductImage(shopId, file);

      const payload = {
        name: form.name.trim(),
        price: parseFloat(form.price) || 0,
        quantity: parseInt(form.quantity, 10) || 0,
        sku: form.sku.trim() || null,
        description: form.description.trim() || null,
        is_active: form.is_active,
        image_url: imageUrl,
      };
      if (form.id) {
        await api("/products/" + form.id, "PUT", payload);
        toast("პროდუქტი განახლდა");
      } else {
        await api("/products", "POST", { ...payload, shop_id: shopId });
        toast("პროდუქტი დაემატა");
      }
      reset();
      await loadProducts();
    } catch (err) {
      toast(err.message, true);
    } finally {
      setBusy(false);
    }
  }

  async function remove(p) {
    if (!confirm('წავშალო "' + p.name + '"?')) return;
    try {
      await api("/products/" + p.id, "DELETE");
      toast("პროდუქტი წაიშალა");
      await loadProducts();
    } catch (err) {
      toast(err.message, true);
    }
  }

  const shown = useMemo(() => {
    const s = q.trim().toLowerCase();
    if (!s) return products;
    return products.filter(
      (p) => (p.name || "").toLowerCase().includes(s) || (p.sku || "").toLowerCase().includes(s)
    );
  }, [products, q]);

  return (
    <div className="tab-panel">
      {/* ---------- ფორმა ---------- */}
      <div className="card">
        <h2>{editing ? "პროდუქტის რედაქტირება" : "ახალი პროდუქტი"}</h2>
        <form className="product-form" onSubmit={onSubmit}>
          <label>
            დასახელება *
            <input type="text" required placeholder="მაგ. პური" value={form.name} onChange={upd("name")} />
          </label>
          <div className="row-2">
            <label>
              ფასი (₾)
              <input type="number" min="0" step="0.01" value={form.price} onChange={upd("price")} />
            </label>
            <label>
              რაოდენობა
              <input type="number" min="0" step="1" value={form.quantity} onChange={upd("quantity")} />
            </label>
          </div>
          <label>
            SKU (არასავალდებულო)
            <input type="text" placeholder="მაგ. BR-001" value={form.sku} onChange={upd("sku")} />
          </label>
          <label>
            აღწერა (არასავალდებულო)
            <textarea rows="2" placeholder="მოკლე აღწერა" value={form.description} onChange={upd("description")} />
          </label>
          <label>
            ფოტო (არასავალდებულო)
            <input type="file" accept="image/*" ref={fileRef} onChange={pickFile} />
          </label>
          {preview && (
            <div className="img-preview">
              <img src={preview} alt="პროდუქტის ფოტო" />
              <button type="button" className="img-remove" title="ფოტოს მოცილება" onClick={clearImage}>✕</button>
            </div>
          )}
          <label className="checkbox-label">
            <input type="checkbox" checked={form.is_active} onChange={upd("is_active")} /> აქტიური (ჩანს ბოტში)
          </label>
          <div className="form-actions">
            <button type="submit" className="btn btn-primary" disabled={busy}>
              {busy ? "ინახება..." : editing ? "შენახვა" : "დამატება"}
            </button>
            {editing && (
              <button type="button" className="btn btn-ghost" onClick={reset}>გაუქმება</button>
            )}
          </div>
        </form>
      </div>

      {/* ---------- სია ---------- */}
      <div className="card">
        <div className="list-header">
          <h2>პროდუქტები ({products.length})</h2>
          <button className="btn btn-ghost" onClick={loadProducts}>↻ განახლება</button>
        </div>
        <input type="search" placeholder="🔍 ძებნა — სახელი ან SKU" style={{ marginBottom: 12 }}
          value={q} onChange={(e) => setQ(e.target.value)} />
        <div className="product-list">
          {loadingProducts ? (
            <Skeleton n={4} />
          ) : (
            shown.map((p) => (
              <div className="product-item" key={p.id}>
                {p.image_url && <img className="product-thumb" src={p.image_url} alt="" loading="lazy" />}
                <div className="product-info">
                  <div className="product-name">
                    {p.name}{" "}
                    <span className={p.is_active ? "badge badge-on" : "badge badge-off"}>
                      {p.is_active ? "აქტიური" : "გამორთული"}
                    </span>
                  </div>
                  <div className="product-meta">
                    {Number(p.price).toFixed(2)} ₾ · მარაგი: {p.quantity}
                    {p.sku ? " · SKU: " + p.sku : ""}
                  </div>
                </div>
                <div className="product-actions">
                  <button className="btn btn-ghost btn-sm" onClick={() => startEdit(p)}>რედაქტ.</button>
                  <button className="btn btn-danger btn-sm" onClick={() => remove(p)}>წაშლა</button>
                </div>
              </div>
            ))
          )}
        </div>
        {!loadingProducts && products.length === 0 && (
          <p className="empty-state">პროდუქტები ჯერ არ გაქვს — დაამატე პირველი ზემოთ.</p>
        )}
        {!loadingProducts && products.length > 0 && shown.length === 0 && (
          <p className="empty-state">„{q}“ — ვერაფერი მოიძებნა.</p>
        )}
      </div>

      <ImportCard allowed={bulkAllowed} />
    </div>
  );
}

/* ================= Excel/CSV იმპორტი ================= */
function ImportCard({ allowed }) {
  const toast = useToast();
  const { shopId, loadProducts } = useShopData();
  const [file, setFile] = useState(null);
  const [data, setData] = useState(null); // {headers, detected, preview, total_rows}
  const [cols, setCols] = useState({});
  const [extra, setExtra] = useState([]);
  const [result, setResult] = useState(null); // {ok, text} | {errors}
  const [busy, setBusy] = useState(false);
  const fileRef = useRef(null);

  async function onPreview() {
    if (!shopId) return toast("ჯერ აირჩიე მაღაზია", true);
    if (!file) return toast("ჯერ აირჩიე ფაილი (.xlsx ან .csv)", true);
    setResult(null);
    setData(null);
    try {
      const d = await previewImport(shopId, file);
      setData(d);
      const init = {};
      IMPORT_FIELDS.forEach((f) => {
        const v = (d.detected || {})[f.key];
        init[f.key] = v == null ? "" : String(v);
      });
      setCols(init);
      setExtra([]);
    } catch (e) {
      setResult({ err: "⚠️ " + e.message });
    }
  }

  async function onConfirm() {
    const mapping = buildMapping(cols, extra);
    if (mapping.name === undefined) return toast("აუცილებელია მიუთითო „სახელის“ სვეტი", true);
    setBusy(true);
    setResult({ text: "მუშავდება..." });
    try {
      const r = await confirmImport(shopId, file, mapping);
      if (r.ok) {
        setResult({ ok: "✅ " + r.message });
        setData(null);
        setFile(null);
        if (fileRef.current) fileRef.current.value = "";
        await loadProducts();
      } else {
        setResult({ errTitle: r.message, rows: r.rowErrors });
      }
    } catch (e) {
      setResult({ err: "⚠️ " + e.message });
    } finally {
      setBusy(false);
    }
  }

  const headers = (data && data.headers) || [];

  return (
    <div className={"card" + (allowed ? "" : " locked")}>
      <h2>📄 ბევრი პროდუქტის ატვირთვა (Excel/CSV)</h2>
      {!allowed && (
        <div className="tier-lock">
          🔒 ეს ფუნქცია ფასიან პაკეტშია ხელმისაწვდომი — განაახლე პაკეტი ზემოთ.
        </div>
      )}
      <p className="import-hint">
        ატვირთე შენი ფაილი <b>ისე, როგორც არის</b> — შემდეგ თვითონ მიუთითებ რომელი სვეტია
        სახელი, ფასი, მარაგი. სვეტების გადარქმევა საჭირო არ არის.
        <br />🔄 <b>ხელახლა ატვირთვა</b> არსებულ პროდუქტებს განაახლებს (SKU-ით ან სახელით),
        ახალს დაამატებს — დუბლიკატს არ ქმნის.{" "}
        <a href="sample-products.xlsx" download>Excel ნიმუში</a> ·{" "}
        <a href="sample-products.csv" download>CSV ნიმუში</a>
      </p>

      <div className="import-row">
        <input type="file" accept=".csv,.xlsx" ref={fileRef} disabled={!allowed}
          onChange={(e) => setFile(e.target.files && e.target.files[0])} />
        <button className="btn btn-primary" disabled={!allowed} onClick={onPreview}>სვეტების ნახვა →</button>
      </div>

      {data && (
        <div className="import-mapping">
          <div className="mapping-title">მიუთითე რომელი სვეტია რომელი ({data.total_rows} მწკრივი):</div>
          <div className="mapping-grid">
            {IMPORT_FIELDS.map((f) => (
              <label className="mapping-row" key={f.key}>
                <span>{f.label}{f.required ? " *" : ""}</span>
                <select value={cols[f.key] ?? ""} onChange={(e) => setCols((s) => ({ ...s, [f.key]: e.target.value }))}>
                  <option value="">— არცერთი —</option>
                  {headers.map((h, i) => (
                    <option value={i} key={i}>{h || "სვეტი " + (i + 1)}</option>
                  ))}
                </select>
              </label>
            ))}
          </div>

          {headers.length > 0 && (
            <div className="mapping-extra">
              <div className="mapping-extra-title">
                დამატებითი ინფორმაცია აღწერაში (არჩევითი — მაგ. ფერი, ზომა):
              </div>
              {headers.map((h, i) => (
                <label className="extra-chk" key={i}>
                  <input type="checkbox" checked={extra.includes(i)}
                    onChange={(e) => setExtra((s) => (e.target.checked ? [...s, i] : s.filter((x) => x !== i)))} />{" "}
                  {h || "სვეტი " + (i + 1)}
                </label>
              ))}
            </div>
          )}

          {headers.length > 0 && (
            <div className="mapping-preview">
              <table>
                <thead>
                  <tr>{headers.map((h, i) => <th key={i}>{h || "—"}</th>)}</tr>
                </thead>
                <tbody>
                  {(data.preview || []).map((row, ri) => (
                    <tr key={ri}>{headers.map((_, i) => <td key={i}>{row[i] || ""}</td>)}</tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <div className="import-row">
            <button className="btn btn-primary" disabled={busy} onClick={onConfirm}>✓ დაადასტურე და ატვირთე</button>
            <button className="btn btn-ghost" onClick={() => setData(null)}>გაუქმება</button>
          </div>
        </div>
      )}

      {result && (
        <div className={"import-result" + (result.ok ? " import-ok" : result.err || result.errTitle ? " import-err" : "")}>
          {result.ok || result.err || result.text}
          {result.errTitle && (
            <>
              <div className="import-err-title">⚠️ {result.errTitle}</div>
              <ul>
                {(result.rows || []).map((e, i) => (
                  <li key={i}>მწკრივი {e.row}: {e.message}</li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}
    </div>
  );
}
