# Frontend — გამყიდველის პანელი (React + Vite)

**2026-08-20-იდან React-ზეა.** სრული სპეციფიკაცია: `../REACT_MIGRATION.md`

## გაშვება

```bash
npm install
npm run dev      # http://localhost:5173/panel/  (dev-სერვერი)
npm run build    # → dist/  (ეს ჩადის git-ში, იხ. ქვემოთ)
```

backend ცალკე უნდა გაუშვა: `../start-backend.ps1` (პორტი 8000).

## სტრუქტურა

```
*.html              8 გვერდი — Vite-ის entry-ები (MPA, არა SPA)
public/             უცვლელად კოპირდება dist/-ში
  config.js         public კონფიგი (SUPABASE_URL, anon key, API_BASE)
  favicon.svg, sample-products.{csv,xlsx}
styles.css · landing.css · order.css
src/
  lib/              api.js · csv.js         (ადმინის საერთო)
  panel/            პანელი — index.html
    supabase.js api.js session.js fbConnect.js images.js importApi.js
    PanelApp.jsx AuthView.jsx Dashboard.jsx ProductsTab.jsx
    OrdersTab.jsx BotTab.jsx ShopData.jsx ui.jsx
  admin/            ადმინ-პანელი — admin.html
  order/            საჯარო შესაკვეთი ფორმა — order.html
  reset/            პაროლის აღდგენა — reset.html
```

`landing.html`, `privacy.html`, `terms.html`, `delete-data.html` **განზრახ სტატიკურია**
— JavaScript მათ არ სჭირდებათ (იხ. REACT_MIGRATION.md, ფაზა 4).

## ⚠️ სამი წესი

1. **MPA, არა SPA routing.** 8 `.html` ფაილი ზუსტად იმავე სახელით უნდა დარჩეს —
   ეს URL-ები რეგისტრირებულია Meta-ზე/Supabase-ზე და ბოტმა უკვე დაუგზავნა
   მყიდველებს (`/panel/order.html?shop=ID`).

2. **დროზე-დამოკიდებული ლოგიკა React-ის გარეთაა** — `fbConnect.js` (popup +
   postMessage + ბუფერი), `session.js`, `supabase.js`-ის no-op `lock`.
   `useEffect`-ში გადატანა **ჩუმად ტეხს** Facebook-ის დაკავშირებას.

3. **`dist/` git-ში ინახება** — Render-ს Node.js არ აქვს, build ლოკალურად კეთდება.
   push-ამდე: `npm run build`.

## ძველი vanilla ფაილები — წაშლილია

`app.js`, `admin.js`, `order.js`, `reset.js`, `index.html.vanilla-backup`, `serve.py`
**წაიშალა 2026-08-21-ს.** React ლაივზე დადასტურდა (12/12 smoke) და კოდ-რევიუმ
ძველი↔ახალი დიფიც გაიარა — ეტალონი აღარ არის საჭირო.

საჭიროების შემთხვევაში ისინი git-ის ისტორიაშია: `git show 84560d6:frontend/app.js`.

ლოკალური frontend-ის გასაშვებად `serve.py`-ის ნაცვლად: `npm run dev` (Vite, პორტი 5173).
