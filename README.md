# ChatAssist — AI ბოტი ქართული მაღაზიებისთვის

**Multi-tenant SaaS პლატფორმა.** ქართველი გამყიდველი რეგისტრირდება, ტვირთავს მარაგს და
აკავშირებს Facebook გვერდს. Messenger-ში მისულ კლიენტს AI ბოტი **ქართულად** პასუხობს
სწორედ იმ მაღაზიის მარაგზე დაყრდნობით, ფოტოს ცნობს, შეკვეთის ლინკს აძლევს და
საჭიროებისას ცოცხალ ოპერატორზე გადაერთვება.

🌐 **ლაივზე:** [chatassist.ge](https://chatassist.ge) · **ჰოსტინგი:** Render (Starter)
· **ბოლო deploy:** `c1696ee`

---

## შიგთავსი

1. [როგორ მუშაობს](#1-როგორ-მუშაობს)
2. [მიმდინარე მდგომარეობა](#2-მიმდინარე-მდგომარეობა)
3. [სტეკი](#3-სტეკი)
4. [პროექტის სტრუქტურა](#4-პროექტის-სტრუქტურა)
5. [ფუნქციონალი](#5-ფუნქციონალი)
6. [API — 47 endpoint](#6-api--47-endpoint)
7. [მონაცემთა ბაზა](#7-მონაცემთა-ბაზა)
8. [უსაფრთხოება](#8-უსაფრთხოება)
9. [ლოკალური გაშვება](#9-ლოკალური-გაშვება)
10. [Meta App setup](#10-meta-app-setup)
11. [Production deploy](#11-production-deploy)
12. [გარემოს ცვლადები](#12-გარემოს-ცვლადები)
13. [დოკუმენტაცია](#13-დოკუმენტაცია)
14. [ცნობილი ხარვეზები](#14-ცნობილი-ხარვეზები)
15. [ეტაპების ისტორია](#15-ეტაპების-ისტორია)

---

## 1. როგორ მუშაობს

```
გამყიდველი                          კლიენტი
    │                                   │
    ├─ რეგისტრაცია (Supabase Auth)      │
    ├─ მაღაზია + პროდუქტები             │
    │  (ხელით / Excel / CSV)            │
    ├─ PDF-ცოდნა (FAQ, მიწოდება)        │
    └─ Facebook გვერდის დაკავშირება     │
              (OAuth)                   │
                 │                      │
                 ▼                      ▼
         ┌───────────────────────────────────┐
         │   Messenger / Instagram Direct    │
         └───────────────┬───────────────────┘
                         │ webhook (ხელმოწერით)
                         ▼
              ┌─────────────────────┐
              │  FastAPI  /webhook  │
              │  ├ page_id → მაღაზია │
              │  ├ ლიმიტის შემოწმება │
              │  ├ მარაგი + ცოდნა    │
              │  └ საუბრის მეხსიერება│
              └──────────┬──────────┘
                         ▼
                   ┌──────────┐
                   │  Gemini  │  ← ქართული / English / Русский
                   └────┬─────┘
                        ▼
                 პასუხი Send API-ით
                        │
                        └─→ საჭიროებისას: შესაკვეთი ლინკი
                                          ან ოპერატორზე გადართვა
```

**მთავარი იდეა:** ბოტი **მხოლოდ მაღაზიის რეალურ მარაგზე** პასუხობს — არაფერს იგონებს.
თუ პროდუქტი არ არის, ასე ამბობს.

---

## 2. მიმდინარე მდგომარეობა

**კოდი დასრულებულია და ლაივზეა.** დარჩენილი გზა Meta-ს ნებართვებზე გადის.

| ეტაპი | სტატუსი |
|---|---|
| პლატფორმა, ბოტი, პანელი, მონეტიზაცია | ✅ ლაივზე მუშაობს |
| კოდ-რევიუ (8 გავლა, 22 მიგნება, 16 გასწორება) | ✅ დასრულდა |
| ი/მ რეგისტრაცია | ✅ დასრულდა |
| დომენის ვერიფიკაცია (`chatassist.ge`) | ✅ Verified |
| **Meta Business Verification** | ⏳ **განხილვაშია** |
| Meta App Review (5 ნებართვა) | ⬜ ვერიფიკაციის შემდეგ |
| Development → Live | ⬜ App Review-ს შემდეგ |

⚠️ **Dev-რეჟიმის შეზღუდვა:** სანამ აპი `Live` არ არის, ბოტი მუშაობს **მხოლოდ**
App Roles-ში დამატებულ ანგარიშებზე (Admin/Tester). Instagram dev-რეჟიმში
საერთოდ არ იღებს webhook-ს.

ცოცხალი სტატუს-დაფა (გაკეთებული / გასაშვები / დაგეგმილი) ცალკე ინახება — იხ.
[ROADMAP.md](ROADMAP.md).

---

## 3. სტეკი

| ფენა | ტექნოლოგია |
|---|---|
| **Backend** | FastAPI (Python 3.11+), uvicorn |
| **DB / Auth / Storage** | Supabase — Postgres + Row Level Security + Auth + Storage |
| **Frontend** | React 18 + Vite (**MPA**, არა SPA) — 8 გვერდი |
| **AI** | Google Gemini (`gemini-2.5-flash`, `GEMINI_MODEL`-ით იცვლება) |
| **არხები** | Facebook Messenger Platform · Instagram Messaging (Graph `v21.0`) |
| **ჰოსტინგი** | Render (Starter $7/თვე — cold-start გამორთულია) |
| **დომენი** | `chatassist.ge` (DNS + SSL) |

⚠️ **Render-ზე Node არ არის** — ამიტომ `frontend/dist/` **ჩადის git-ში**.
build-ს ლოკალურად აკეთებ (`npm run build`) და commit-ავ.

---

## 4. პროექტის სტრუქტურა

```
.
├── backend/
│   └── app/
│       ├── main.py              entrypoint · CORS · security headers · static mount
│       ├── config.py            პარამეტრები (.env → pydantic-settings)
│       ├── api/                 9 როუტერი
│       │   ├── health.py        /health · /status
│       │   ├── shops.py         მაღაზიები, ცოდნა, გამოწერა, ანალიტიკა, handoff
│       │   ├── products.py      CRUD · Excel/CSV იმპორტი · ფოტოს ატვირთვა
│       │   ├── orders.py        საჯარო შეკვეთა + გამყიდვლის მართვა
│       │   ├── chat.py          /test-chat (მხოლოდ dev)
│       │   ├── webhook.py       Meta webhook — ბოტის მთავარი შესასვლელი
│       │   ├── facebook.py      OAuth connect/disconnect · data deletion
│       │   └── admin.py         მფლობელის პანელი (მხოლოდ ADMIN_EMAIL)
│       ├── core/
│       │   ├── security.py      Supabase JWT → CurrentAuth (RLS-იანი კლიენტი)
│       │   ├── supabase_client.py  anon (publishable key) / service (secret key) კლიენტები
│       │   ├── db.py            Postgres შეცდომების → HTTP კოდები
│       │   ├── crypto.py        Fernet — page token-ის შიფვრა
│       │   ├── ratelimit.py     in-memory per-IP sliding window
│       │   └── tiers.py         პაკეტები, ლიმიტები, ფასები
│       ├── models/              Pydantic სქემები (shop, product, order, chat)
│       └── services/
│           ├── bot.py           get_bot_reply · prompt · პროდუქტ-ძებნა · ლინკი
│           ├── facebook.py      Graph API · Send API · SSRF-დაცული download_image
│           ├── import_products.py  Excel/CSV პარსერი (all-or-nothing)
│           └── pdf_extract.py   PDF → ტექსტი (ბოტის ცოდნა)
│
├── frontend/                    React + Vite (MPA)
│   ├── *.html                   8 entry: landing, index, admin, order, reset,
│   │                            privacy, terms, delete-data
│   ├── src/
│   │   ├── panel/               გამყიდვლის პანელი (Dashboard, Products, Orders, Bot)
│   │   ├── admin/               ადმინ-პანელი
│   │   ├── order/               საჯარო შესაკვეთი ფორმა
│   │   ├── reset/               პაროლის აღდგენა
│   │   └── lib/                 api.js · csv.js (საერთო)
│   ├── public/                  config.js · favicon · sample-products.{csv,xlsx}
│   └── dist/                    ⚠️ build-ის შედეგი — ჩადის git-ში
│
├── supabase/migrations/         19 SQL მიგრაცია (ცხრილები, RLS, RPC, grants)
│
├── .env.example                 გარემოს ცვლადების შაბლონი
└── *.md                         დოკუმენტაცია — იხ. §13
```

---

## 5. ფუნქციონალი

### 5.1 გამყიდვლის პანელი

`/panel/index.html` — ოთხი ჩანართი:

| ჩანართი | რა შეუძლია |
|---|---|
| **მთავარი** | სტატისტიკა, პაკეტის მდგომარეობა, კლიენტების მრიცხველი, Facebook გვერდის დაკავშირება/გათიშვა |
| **პროდუქტები** | დამატება/რედაქტირება/წაშლა · Excel/CSV იმპორტი (preview-თი) · ფოტოს ატვირთვა (ბრაუზერში resize) · აქტიური/არააქტიური |
| **შეკვეთები** | სტატუსები (new → processing → done / cancelled) · მარაგი ავტომატურად კლებულობს და ბრუნდება · CSV ექსპორტი |
| **ბოტი** | ენის არჩევა · PDF-ცოდნის ატვირთვა · ანალიტიკა (top-terms, უპასუხო კითხვები) · „ყურადღება სჭირდება" სია |

მრავალი მაღაზია ერთ ანგარიშზე — პაკეტის ლიმიტის ფარგლებში.

### 5.2 ბოტი

| # | ფუნქცია | აღწერა |
|---|---|---|
| **#1** | საუბრის მეხსიერება | ბოლო 20 შეტყობინება, 24 საათი (`BOT_MEMORY_*`) |
| **#2** | გაძლიერებული prompt | პერსონა, დაზუსტება, upsell, handoff-ის წესები |
| **#3** | ჭკვიანი პროდუქტ-ძებნა | ≤30 პროდუქტი → ყველა; >30 → keyword-match, top-30 (სიზუსტე + იაფი prompt) |
| **#4** | ოპერატორზე გადართვა | ბოტი პასუხს `[[HANDOFF]]` ნიშანს ამატებს → საუბარი პანელში ინიშნება |
| **#5** | სურათის გაგება | კლიენტი ფოტოს აგზავნის → Gemini multimodal → მარაგს ადარებს |
| — | ვიზუალური ამოცნობა | პროდუქტების ფოტოებს ადარებს და კონკრეტულს ცნობს |
| **#7** | ანალიტიკა | საუბრების რაოდ., top-terms, ბოლო შეკითხვები |
| — | მრავალენოვნება | ქართული / English / Русский — ავტო ან ხელით |
| — | შესაკვეთი ლინკი | `order.html?shop=<id>` — ბოტი თვითონ აძლევს |

**ჩარჩო:** `get_bot_reply(shop, products, message, history, images)` —
[backend/app/services/bot.py](backend/app/services/bot.py)

### 5.3 შეკვეთები

- საჯარო ფორმა — ავტორიზაცია **არ სჭირდება** (`order.html?shop=<id>`)
- ჯამს **სერვერი ითვლის** — კლიენტის გამოგზავნილ ფასს არ ენდობა
- მარაგი იკლებს **ატომურად** (Postgres RPC + row-lock) — ორი პარალელური შეკვეთა
  მარაგს მინუსში ვერ ჩააგდებს
- გაუქმებისას მარაგი ბრუნდება; სტატუსის ცვლილება **ოპტიმისტური ჩაკეტვით** (409 კონფლიქტზე)

### 5.4 მონეტიზაცია

**მთავარი ლიმიტი — უნიკალური კლიენტი თვეში**, არა შეტყობინება.

| | 🆓 უფასო | 🥉 საბაზისო | 🥈 სტანდარტი | 🥇 ბიზნესი |
|---|---|---|---|---|
| **ფასი / თვე** | 0 ₾ | 29 ₾ | 69 ₾ | 149 ₾ |
| კლიენტი / თვე | 30 | 200 | 800 | 3 000 |
| პროდუქტი | 20 | 150 | 1 000 | ულიმიტო |
| მაღაზია / გვერდი | 1 | 1 | 2 | ულიმიტო |
| Excel/CSV + PDF | ❌ | ✅ | ✅ | ✅ |

- ლიმიტები **სერვერზე** მოწმდება (4 ადგილას), არა მხოლოდ UI-ში
- გამოწერა **per-account**-ია, არა per-shop
- **abuse-ჭერი:** ერთი კლიენტი დღეში მაქს. 100 შეტყობინება (loop-ის დაცვა)
- უფასოზე დაბრუნებისას **მონაცემი არ იშლება** — ზედმეტ მაღაზიებზე ბოტი უბრალოდ
  ითიშება და upgrade-ზე ავტომატურად ბრუნდება

გადახდა ჯერ **ხელით** — გამყიდველი აგზავნის მოთხოვნას, ადმინი ადასტურებს
(`upgrade_requests`). დეტალები: [MONETIZATION.md](MONETIZATION.md).

### 5.5 ადმინ-პანელი

`/panel/admin.html` — ხელმისაწვდომია **მხოლოდ** `ADMIN_EMAIL`-ისთვის.

მაღაზიები · გამყიდვლები · შეკვეთები · MRR · ზრდის გრაფიკი · პაკეტის მოთხოვნების
დამუშავება · CSV ექსპორტი · ბოტის kill-switch · აღდგენის ინსტრუმენტი.

### 5.6 არხები

| არხი | მდგომარეობა |
|---|---|
| **Facebook Messenger** | ✅ სრულად მუშაობს (dev-რეჟიმში testers-ზე) |
| **Instagram Direct** | ✅ კოდი მზადაა · ⏳ Live-რეჟიმს ელოდება |

ორივე იმავე `get_bot_reply`-ს იყენებს — ბოტის ლოგიკა 100% reuse-დება.
webhook `object` ველით არჩევს (`page` / `instagram`).

---

## 6. API — 47 endpoint

ავტორიზაცია: `Authorization: Bearer <supabase_access_token>`.
DB-ოპერაციები სრულდება **მომხმარებლის JWT-ით** → RLS უზრუნველყოფს იზოლაციას.
სრული ინტერაქტიული დოკუმენტაცია: `/docs`

### სისტემა
| Method | Path | აღწერა | Auth |
|---|---|---|---|
| GET | `/health` | ჯანმრთელობის შემოწმება | — |
| GET | `/status` | სახელი, ვერსია, გარემო | — |
| GET | `/` | → `/panel/landing.html` | — |

### მაღაზიები
| Method | Path | აღწერა |
|---|---|---|
| POST | `/shops` | მაღაზიის შექმნა |
| GET | `/shops/me` | ჩემი მაღაზიები |
| PATCH | `/shops/{id}` | განახლება (სახელი, ენა, ბოტის ჩართვა…) |
| POST | `/shops/{id}/knowledge` | PDF ატვირთვა → ბოტის ცოდნა |
| DELETE | `/shops/{id}/knowledge` | ცოდნის წაშლა |
| GET | `/shops/{id}/usage` | პაკეტი + კლიენტების მრიცხველი |
| GET | `/shops/{id}/analytics` | ბოტის ანალიტიკა (top-terms, შეკითხვები) |
| GET | `/shops/{id}/attention` | „ყურადღება სჭირდება" საუბრები |
| POST | `/shops/{id}/attention/{psid}/resolve` | საუბრის დახურვა |
| POST | `/shops/{id}/upgrade-request` | პაკეტის მოთხოვნა |
| POST | `/shops/{id}/downgrade-free` | უფასოზე დაბრუნება |
| GET | `/shops/{id}/export` | მონაცემთა ექსპორტი (portability) |

### პროდუქტები
| Method | Path | აღწერა |
|---|---|---|
| POST · GET | `/products` | დამატება · სია (`?shop_id=`) |
| PUT · DELETE | `/products/{id}` | განახლება · წაშლა |
| POST | `/products/import/preview` | იმპორტის წინასწარი ნახვა |
| POST | `/products/import` | Excel/CSV bulk import |
| POST | `/products/upload-image` | ფოტოს ატვირთვა (Supabase Storage) |

### შეკვეთები
| Method | Path | აღწერა | Auth |
|---|---|---|---|
| GET | `/public-menu?shop_id=` | მაღაზია + აქტიური პროდუქტები | საჯარო |
| POST | `/orders` | კლიენტი ქმნის შეკვეთას | საჯარო (rate-limited) |
| GET | `/orders` | გამყიდვლის შეკვეთები (`?shop_id=`) | ✅ |
| PATCH · DELETE | `/orders/{id}` | სტატუსი · წაშლა | ✅ |

### Facebook / Instagram
| Method | Path | აღწერა |
|---|---|---|
| GET | `/webhook` | Meta-ს ვერიფიკაცია (challenge) |
| POST | `/webhook` | შემოსული შეტყობინებები (X-Hub-Signature-256) |
| GET | `/facebook/connect/start` | OAuth-ის დაწყება |
| GET | `/facebook/connect/callback` | token-ის შენახვა + webhook subscribe |
| POST | `/facebook/disconnect` | გვერდის გათიშვა |
| POST | `/facebook/data-deletion` | Meta-ს Data Deletion callback |
| GET | `/facebook/data-deletion/status` | კოდის შემოწმება (ხელმოწერილი) |

### ადმინი (მხოლოდ `ADMIN_EMAIL`)
| Method | Path | აღწერა |
|---|---|---|
| GET | `/admin/check` | ადმინია თუ არა |
| GET | `/admin/overview` | MRR, ჯამები |
| GET | `/admin/growth` | ზრდის გრაფიკი |
| GET | `/admin/sellers` · `/admin/shops` · `/admin/orders` | სიები |
| GET · PATCH · DELETE | `/admin/shops/{id}` | დეტალები · პაკეტი/ბოტი · წაშლა |
| GET | `/admin/upgrade-requests` | მოთხოვნების სია |
| POST | `/admin/upgrade-requests/{id}/resolve` | დადასტურება/უარი |
| POST | `/admin/recovery` | აღდგენის ინსტრუმენტი |

### Dev
| Method | Path | აღწერა |
|---|---|---|
| POST | `/test-chat` | ⚠️ ბოტის ტესტი Messenger-ის გარეშე — **production-ში გამორთულია** |

---

## 7. მონაცემთა ბაზა

### ცხრილები (6) — ყველას აქვს RLS

| ცხრილი | რა ინახება |
|---|---|
| `shops` | მაღაზია, მფლობელი, პაკეტი, FB/IG ID-ები, დაშიფრული token, ცოდნა, ენა |
| `products` | სახელი, ფასი, მარაგი, აღწერა, SKU, ფოტო, აქტიურობა |
| `orders` | კლიენტის შეკვეთა, პოზიციები (JSON), ჯამი, სტატუსი |
| `upgrade_requests` | პაკეტის მოთხოვნები (manual billing) |
| `bot_customers` | უნიკალური კლიენტი თვეში (ლიმიტის მრიცხველი) + handoff-ის ნიშანი |
| `bot_conversations` | საუბრის მეხსიერება (ბოლო შეტყობინებები) |

**იზოლაცია:** ყველა პოლისი `shops.owner_id = auth.uid()`-ზე დგას (`USING` + `WITH CHECK`).
ერთი გამყიდველი მეორისას **ვერ ხედავს და ვერ ცვლის**.

### მიგრაციები (21)

| # | რა |
|---|---|
| `0001` | `shops` + `products` + RLS |
| `0002` | `orders` + RLS |
| `0003` | PDF-ცოდნის ველები |
| `0004` | მონეტიზაცია — პაკეტი + `bot_customers` + `track_bot_customer()` |
| `0005` | `upgrade_requests` |
| `0006` | Instagram — IG account id |
| `0007` | ბოტის ენა |
| `0008` | საუბრის მეხსიერება (`bot_conversations`) |
| `0009` | `decrement_stock()` — ატომური დაკლება |
| `0010` | handoff — „ყურადღება სჭირდება" |
| `0011` | გამყიდვლის FB user-id (Data Deletion-ისთვის) |
| `0012` | პროდუქტის ფოტო (`image_url`) |
| `0013` | `apply_stock_delta()` — გაუქმება/დაბრუნება |
| `0014` | 🔒 **RPC-ების EXECUTE ნებართვები** (უსაფრთხოება — P0) |
| `0015` | 🔒 სვეტის დონის ნებართვები `shops` / `products`-ზე |
| `0016` | 🔒 ტექსტური სვეტების სიგრძის CHECK ლიმიტები |
| `0017` | 🔒 `shops`-ის DELETE მოხსნილია `anon`/`authenticated`-დან (წაშლა მხოლოდ admin endpoint-ით) |
| `0018` | 🔒 `orders`: UPDATE მხოლოდ `status` სვეტზე, status CHECK, DELETE პოლისი მხოლოდ `done`/`cancelled` |
| `0019` | 🔒 `upgrade_requests`: INSERT პოლისი მოითხოვს `pending` + tier-ის სიას; status/tier CHECK |
| `0020` | 🔒 `shops.instagram_account_id` — partial UNIQUE ინდექსი (IG შეტყობინება სხვა tenant-ს ვეღარ მიეწერება) |
| `0021` | `change_order_status()` — შეკვეთის სტატუსი + მარაგი ერთ ტრანზაქციაში (გაუშვი backend-ის deploy-მდე) |

**გაშვება:** Supabase → SQL Editor → ჩასვი ფაილის შიგთავსი → RUN. თანმიმდევრობით.

**ერთჯერადი სკრიპტები** (`supabase/one-off/`, არა მიგრაციები — ხელით, ერთხელ, header-ის ინსტრუქციით):
`release_legacy_new_order_stock.sql` — deploy-მდე შექმნილი `new` შეკვეთების მარაგის დაბრუნება.

---

## 8. უსაფრთხოება

| დაცვა | როგორ |
|---|---|
| **მოიჯარეთა იზოლაცია** | RLS ყველა ცხრილზე; backend მომხმარებლის JWT-ით მიმართავს ბაზას |
| **Page token** | ინახება **დაშიფრულად** (Fernet, `FB_TOKEN_ENCRYPTION_KEY`) |
| **webhook-ის ავთენტურობა** | `X-Hub-Signature-256` მოწმდება app secret-ით |
| **RPC-ების ნებართვები** | `SECURITY DEFINER` ფუნქციები **მხოლოდ** `service_role`-ს — `anon`/`authenticated` მოხსნილია (მიგრაცია 0014) |
| **SSRF** | სურათის ჩამოტვირთვისას: სქემის allowlist, private/loopback/link-local IP-ების ბლოკი, redirect-ების ხელით გავლა, ბაიტების ჭერი |
| **რბოლები** | მარაგი — Postgres row-lock; შეკვეთის სტატუსი — ოპტიმისტური ჩაკეტვა (409) |
| **დედუპლიკაცია** | Meta-ს განმეორებული `mid` ბოტს ორჯერ არ ამუშავებს |
| **Rate limiting** | per-IP sliding window საჯარო endpoint-ებზე |
| **Abuse cap** | ერთი კლიენტი დღეში 100 შეტყობინება |
| **File bombs** | Excel/CSV — 5 MB / 5 000 მწკრივი; PDF — 300 გვერდი; zip-ratio ჭერი |
| **CSV injection** | `=`, `+`, `-`, `@` ექსპორტში ნეიტრალდება |
| **Security headers** | `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`, HSTS (production) |
| **შეცდომების გაჟონვა** | production-ში stack trace არ ბრუნდება |
| **Dev endpoint** | `/test-chat` production-ში გამორთულია |
| **Data Deletion** | Meta-ს callback + ხელმოწერილი (HMAC) დადასტურების კოდი |

**კოდ-რევიუ:** 2026-08-21…23, 8 გავლა, ~6 400 ხაზი, 22 მიგნება → 16 გასწორებული.
სრული ანგარიში: [CODE_REVIEW_FINDINGS.md](CODE_REVIEW_FINDINGS.md).
P0-ის დეტალები: [SECURITY_FIX_PROMPT.md](SECURITY_FIX_PROMPT.md).

⚠️ **CSP ჯერ არ არის** — გადადებულია რედიზაინთან ერთად (იხ. §14).

---

## 9. ლოკალური გაშვება

### Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item ..\.env.example ..\.env    # შემდეგ შეავსე
uvicorn app.main:app --reload
```

გახსენი <http://localhost:8000/health> და <http://localhost:8000/docs>

### Frontend

```bash
cd frontend
npm install
npm run dev      # http://localhost:5173/panel/
npm run build    # → dist/  (ეს ჩადის git-ში!)
```

`frontend/public/config.js` — გადააკოპირე `config.example.js`-დან და შეავსე
(`SUPABASE_URL`, anon key, `API_BASE`).

> ⚠️ **ხაფანგი:** `uvicorn --reload` ხანდახან ობოლ პროცესს ტოვებს, რომელიც პორტს
> იკავებს და ძველ კოდს ასერვირებს. თუ ცვლილება არ ჩანს —
> `Get-Process python | Stop-Process -Force` და თავიდან გაუშვი.

---

## 10. Meta App setup

Facebook-ს **https** საჯარო მისამართი სჭირდება. ლოკალურად — ngrok.

### 1. ngrok (სტატიკური დომენით)
```powershell
ngrok config add-authtoken <token>
ngrok http 8000 --domain=<შენი-სტატიკური>.ngrok-free.dev
```
> 💡 **სტატიკური დომენი აიღე** (ngrok-ის უფასო გეგმაშიც არის) — თორემ ყოველ
> გადატვირთვაზე მისამართი იცვლება და Meta-ს კონფიგი ხელახლა უნდა შეცვალო.

### 2. Meta App
1. <https://developers.facebook.com/apps> → **Create App** → **Business**
2. Add Product → **Messenger** → Set up
3. **App Settings → Basic** → App ID + App Secret

### 3. `.env`
```
FB_APP_ID=<App ID>
FB_APP_SECRET=<App Secret>
FB_VERIFY_TOKEN=ნებისმიერი_საიდუმლო_სტრიქონი
FB_REDIRECT_URI=https://<ngrok>/facebook/connect/callback
FB_TOKEN_ENCRYPTION_KEY=<Fernet key>
PUBLIC_BASE_URL=https://<ngrok>
```
შეცვლის შემდეგ **backend გადატვირთე**.

### 4. Webhook
Messenger → **Configure webhooks**:
- Callback URL: `https://<ngrok>/webhook`
- Verify Token: იგივე, რაც `FB_VERIFY_TOKEN`
- **Verify and Save** (backend უნდა მუშაობდეს)
- Subscribe: **messages**, **messaging_postbacks**

### 5. OAuth redirect
Facebook Login → Settings → **Valid OAuth Redirect URIs:**
`https://<ngrok>/facebook/connect/callback`

> ⚠️ **გამოყენების შემდეგ ngrok-ის URI მოხსენი.** უფასო დომენი გათავისუფლებისას
> სხვამ შეიძლება დაიკავოს და **შენი OAuth-კოდები მიიღოს.**

### 6. ნებართვები (App Review-მდე)
Dev-რეჟიმში მუშაობს **მხოლოდ** App Roles-ში დამატებულ ანგარიშებზე:

`pages_show_list` · `pages_messaging` · `pages_manage_metadata` ·
`business_management` · `pages_read_engagement`

Instagram-ისთვის დამატებით: `instagram_basic` · `instagram_manage_messages`
(პირველი submit-ისას **გამოტოვე** — dev-რეჟიმში ვერ დემონსტრირდება).

App Review-ს ტექსტები: [APP_REVIEW_TEXTS.md](APP_REVIEW_TEXTS.md)

---

## 11. Production deploy

**Render:** auto-deploy `main`-ზე push-ისას.

```
Build:  pip install -r backend/requirements.txt
Start:  uvicorn app.main:app --host 0.0.0.0 --port $PORT --app-dir backend
```

**აუცილებელი production-პარამეტრები:**

```
APP_ENV=production
CORS_ORIGINS=https://chatassist.ge
PUBLIC_BASE_URL=https://chatassist.ge
FB_REDIRECT_URI=https://chatassist.ge/facebook/connect/callback
```

⚠️ **`main`-ზე push = ცოცხალ საიტზე deploy.** `frontend/dist/` წინასწარ ააგე და commit-ე.

სრული ინსტრუქცია, ხარჯები და checklist: [DEPLOYMENT.md](DEPLOYMENT.md)

---

## 12. გარემოს ცვლადები

| ცვლადი | სავალდებულო | ნაგულისხმევი | აღწერა |
|---|---|---|---|
| `SUPABASE_URL` | ✅ | — | პროექტის URL |
| `SUPABASE_PUBLISHABLE_KEY` | ✅ | — | საჯარო გასაღები (`sb_publishable_...`). ძველი სახელი `SUPABASE_ANON_KEY` fallback-ად მუშაობს |
| `SUPABASE_SECRET_KEY` | ✅ | — | 🔒 სერვერის გასაღები (`sb_secret_...`) — **არასდროს frontend-ში**. ძველი სახელი `SUPABASE_SERVICE_ROLE_KEY` fallback-ად მუშაობს; ორივე რომ იყოს, ახალი იგებს |
| `APP_ENV` | | `production` | `production` (default, fail-closed) → HSTS, დამალული შეცდომები, `/test-chat` off. ლოკალურად `.env`-ში `APP_ENV=development` |
| `APP_HOST` · `APP_PORT` | | `0.0.0.0` · `8000` | |
| `CORS_ORIGINS` | | `*` | production-ში კონკრეტული დომენი |
| `CLIENT_IP_TRUSTED_HOPS` | | `1` | კლიენტის IP = `X-Forwarded-For`-ის მარჯვნიდან N-ური ჩანაწერი (Render-ზე სწორი N დაადგინე `CLIENT_IP_DEBUG`-ით). `CF-Connecting-IP` იგნორირდება |
| `CLIENT_IP_DEBUG` | | `false` | დროებით `true` → ერთი INFO ხაზი ლოგში: სრული XFF (≤1000 სიმბ.), entries, peer (არასანდო), hops, resolved IP (10 წმ-ში ერთხელ); შემდეგ გამორთე. production-ში XFF-ის ნაკლებობისას resolved = `unknown` (საერთო key, `peer` არ გამოიყენება — გაყალბებადია) |
| `LOG_LEVEL` | | `INFO` | `app` logger-ის დონე (stdout-ზე): `DEBUG` / `INFO` / `WARNING` / `ERROR`; არავალიდური → `INFO` |
| `GEMINI_API_KEY` | ✅ | — | <https://aistudio.google.com/apikey> |
| `GEMINI_MODEL` | | `gemini-2.5-flash` | მოდელის შეცვლა კოდის გარეშე |
| `GEMINI_TIMEOUT_SECONDS` | | `20` | ერთი Gemini მცდელობის timeout (წმ); retry-ების ჯამი ≤45 წმ, მერე webhook fallback პასუხი |
| `BOT_MEMORY_MESSAGES` | | `20` | 0 = მეხსიერება გამორთული |
| `BOT_MEMORY_HOURS` | | `24` | |
| `FB_APP_ID` · `FB_APP_SECRET` | ✅ | — | 🔒 Meta App |
| `FB_VERIFY_TOKEN` | ✅ | — | webhook-ის ვერიფიკაცია |
| `FB_GRAPH_VERSION` | | `v21.0` | |
| `FB_REDIRECT_URI` | ✅ | — | OAuth callback |
| `FB_LOGIN_CONFIG_ID` | | — | Facebook Login for Business (business-owned გვერდები) |
| `FB_TOKEN_ENCRYPTION_KEY` | ✅ | — | 🔒 Fernet key |
| `PUBLIC_BASE_URL` | | `FB_REDIRECT_URI`-დან | შესაკვეთი ლინკების ბაზა |
| `FRONTEND_URL` | | `localhost:5500` | |
| `ADMIN_EMAIL` | | `giosib77@gmail.com` | ვინ ხედავს `/admin`-ს |
| `PAYMENT_IBAN` · `PAYMENT_CONTACT` | | placeholder | გადახდის რეკვიზიტები |

🔒 = საიდუმლო. **`.env` არასდროს ჩააქოს git-ში.**

Fernet key-ის დაგენერირება:
```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

---

## 13. დოკუმენტაცია

| ფაილი | რაზეა |
|---|---|
| [ROADMAP.md](ROADMAP.md) | სამომავლო ფიჩერები + განზრახ გადადებული ინფრასტრუქტურა (გამშვები პირობებით) |
| [MONETIZATION.md](MONETIZATION.md) | ფასები, ლიმიტები, unit economics |
| [DEPLOYMENT.md](DEPLOYMENT.md) | production deploy, ხარჯები, checklist |
| [REACT_MIGRATION.md](REACT_MIGRATION.md) | frontend-ის React-ზე გადაყვანის სპეციფიკაცია + **URL-კონტრაქტი** |
| [CODE_REVIEW_PROMPT.md](CODE_REVIEW_PROMPT.md) | რევიუს დავალება (v4) — 8 გავლა |
| [CODE_REVIEW_FINDINGS.md](CODE_REVIEW_FINDINGS.md) | რევიუს შედეგები — 22 მიგნება |
| [SECURITY_FIX_PROMPT.md](SECURITY_FIX_PROMPT.md) | P0-ის სრული ანალიზი და გასწორება |
| [APP_REVIEW_TEXTS.md](APP_REVIEW_TEXTS.md) | Meta App Review-ს მზა ინგლისური ტექსტები |
| [INSTAGRAM_SETUP.md](INSTAGRAM_SETUP.md) | Instagram-ის Meta-მხრივი კონფიგი |
| [frontend/README.md](frontend/README.md) | frontend-ის სტრუქტურა და წესები |

---

## 14. ცნობილი ხარვეზები

გულწრფელი სია — რაც **არ** არის გაკეთებული:

| # | რა | რატომ |
|---|---|---|
| 1 | **ავტომატური ტესტები არ არსებობს** | ყველა შემოწმება ხელით კეთდება. ეს ბლოკავს ავტორიზაციის კოდის გადაწერას — ჯერ ტესტები, მერე რეფაქტორინგი |
| 2 | **React-ის კოდი ხაზ-ხაზ არ წაკითხულა** | რევიუზე შემოწმდა სტრუქტურა, `useEffect`-ები და ძველთან დიფი; `AdminPage.jsx` (539 ხაზი) და `ProductsTab.jsx` (365) ცალკე გავლას იმსახურებს |
| 3 | **CSP header არ არის** | თეთრი სიის პრინციპი — ერთი გამორჩენა ცარიელ გვერდს იძლევა. რედიზაინისას ისედაც გადაიწერება |
| 4 | **Rate limit მეხსიერებაშია** | deploy-ზე ნულდება; მრავალ-instance-ზე Redis/Cloudflare დასჭირდება |
| 5 | **webhook-ის დედუპლიკაცია მეხსიერებაშია** | რესტარტზე იწმინდება; სრული გადაწყვეტა რიგს (Redis) სჭირდება |
| 6 | **ადმინ-პანელი ყველაფერს მეხსიერებაში იღებს** | 5 მაღაზია — მილიწამები, 500 — 10წმ+. მხოლოდ მფლობელი იყენებს, ამიტომ არ არის სასწრაფო |
| 7 | **ვიზუალი და ლოგო არ ემთხვევა** | საიტზე ძველი ჩანთის SVG, Meta-ს აპ-იკონა კი CA-მონოგრამი |
| 8 | **გადახდა ხელითაა** | ავტომატური billing ჯერ არ არის — მოთხოვნა → ადმინის დადასტურება |

თითოეულს გამშვები პირობა აქვს — იხ. [ROADMAP.md](ROADMAP.md) → 🏗 ინფრასტრუქტურა.

---

## 15. ეტაპების ისტორია

### ბირთვი
- [x] **1** — Supabase ცხრილები (`shops`, `products`) + RLS
- [x] **2** — FastAPI: auth + shops/products CRUD
- [x] **3** — გამყიდვლის პანელი (mobile-friendly)
- [x] **4** — ბოტი `get_bot_reply` (Gemini, ქართული, მხოლოდ მარაგით) + `/test-chat`
- [x] **5** — Facebook Messenger (webhook, Send API, OAuth)
- [x] **6** — Excel/CSV bulk import
- [x] **7** — შეკვეთები: საჯარო ფორმა + `orders` + პანელი
- [x] **8** — ბოტი თვითონ აძლევს შესაკვეთ ლინკს
- [x] **9** — PDF-ცოდნა

### გაფართოება
- [x] **10** — მონეტიზაცია: პაკეტები, ლიმიტები, კლიენტების თვლა
- [x] **11** — ადმინ-პანელი: MRR, ზრდა, CSV, kill-switch
- [x] **12** — Instagram-ის კოდი (webhook `object=="instagram"`)
- [x] **13** — მრავალენოვნება (ქართული / English / Русский)
- [x] **14** — საუბრის მეხსიერება + გაძლიერებული prompt
- [x] **15** — ჭკვიანი პროდუქტ-ძებნა (დიდ ასორტიმენტზე)
- [x] **16** — ოპერატორზე გადართვა (handoff)
- [x] **17** — სურათის გაგება + პროდუქტის ფოტოები + ვიზუალური ამოცნობა
- [x] **18** — ბოტის ანალიტიკა

### გაშვება
- [x] **19** — Compliance: Privacy, Terms + DPA, Cookies, Data Deletion, ექსპორტი
- [x] **20** — რებრენდი → **ChatAssist** + ზურმუხტისფერი დიზაინ-სისტემა
- [x] **21** — Production: Render + `chatassist.ge` (DNS + SSL)
- [x] **22** — ტარიფების enforcement + per-account გამოწერა
- [x] **23** — frontend React-ზე (Vite MPA, 8 გვერდი)
- [x] **24** — კოდ-რევიუ: 22 მიგნება → 16 გასწორება
- [x] **25** — 🔒 P0: RPC-ების EXECUTE ნებართვები (მიგრაცია 0014)
- [x] **26** — Render Starter ($7) — cold-start მოხსნილია
- [ ] **27** — Meta Business Verification ⏳
- [ ] **28** — Meta App Review (5 ნებართვა)
- [ ] **29** — Development → Live 🚀

---

<sub>ChatAssist · მრავალ-მაღაზიიანი AI ბოტი SaaS · README განახლდა 2026-09-06</sub>
