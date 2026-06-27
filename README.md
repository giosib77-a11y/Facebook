# ქართული მაღაზიების AI ბოტი — Facebook Messenger SaaS

Multi-tenant SaaS პლატფორმა: ქართველი გამყიდველი რეგისტრირდება, ტვირთავს მარაგს და
აკავშირებს Facebook გვერდს. მესენჯერში მისულ კლიენტს AI ბოტი ქართულად პასუხობს
შესაბამისი მაღაზიის მარაგზე დაყრდნობით.

## სტეკი

- **Backend:** FastAPI (Python)
- **DB / Auth:** Supabase (Postgres + Row Level Security)
- **Frontend:** (TBD — გამყიდველის dashboard)
- **მესენჯერი:** Facebook Messenger Platform (Webhooks)

## სტრუქტურა

```
.
├── backend/                FastAPI აპლიკაცია
│   └── app/
│       ├── main.py         entrypoint + health endpoint
│       ├── config.py       პარამეტრები (.env-დან)
│       ├── api/            როუტერები
│       ├── core/           ბაზის/Supabase კლიენტი, საერთო ლოგიკა
│       ├── models/         Pydantic მოდელები
│       └── services/       ბიზნეს ლოგიკა (ბოტი, FB, მარაგი)
├── frontend/               გამყიდველის dashboard (TBD)
├── supabase/
│   └── migrations/         SQL მიგრაციები (ცხრილები + RLS)
├── .env.example
└── .gitignore
```

## ეტაპები (roadmap)

- [x] **ნაბიჯი 1** — Supabase ცხრილები (`shops`, `products`) + RLS პოლისიები
- [x] **ნაბიჯი 2** — FastAPI: Supabase auth-ის შემოწმება + shops/products CRUD endpoints
- [x] **ნაბიჯი 3** — გამყიდველის frontend პანელი (Auth + პროდუქტების მართვა, mobile-friendly)
- [x] **ნაბიჯი 4** — ბოტის ფუნქცია `get_bot_reply` (Gemini, ქართულად, მხოლოდ მარაგით) + `POST /test-chat`
- [x] **ნაბიჯი 5** — Facebook Messenger ინტეგრაცია (webhook, Send API, გვერდის OAuth დაკავშირება)
- [x] **ნაბიჯი 6** — Excel/CSV bulk import (`POST /products/import` + ღილაკი პანელში)
- [x] **ნაბიჯი 7** — შეკვეთები: საჯარო შესაკვეთი ფორმა + `orders` ცხ რილი + პანელში „შეკვეთები"
- [x] **ნაბიჯი 8** — ბოტი ავტომატურად აძლევს კლიენტს მაღაზიის შესაკვეთ ლინკს
- [x] **ნაბიჯი 9** — PDF-ცოდნა: გამყიდველი ტვირთავს PDF-ს, ბოტი იყენებს პასუხ ებში

## ლოკალური გაშვება (backend)

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item ..\.env.example ..\.env   # შემდეგ შეავსე მნიშვნელობები
uvicorn app.main:app --reload
```

გახსენი http://localhost:8000/health და http://localhost:8000/docs

## API endpoints (ნაბიჯი 2)

ყველა მოითხოვს `Authorization: Bearer <supabase_access_token>` (გარდა `/health`).
DB-ოპერაციები სრულდება მომხმარებლის JWT-ით → RLS უზრუნველყოფს იზოლაციას.

| Method | Path | აღწერა |
|---|---|---|
| POST | `/shops` | მაღაზიის შექმნა (owner = მიმდინარე user) |
| GET | `/shops/me` | მიმდინარე user-ის მაღაზიები |
| POST | `/shops/{id}/knowledge` | PDF ატვირთვა → ტექსტი ბოტის ცოდნად (auth) |
| DELETE | `/shops/{id}/knowledge` | ცოდნის წაშლა |
| POST | `/products` | პროდუქტის დამატება (`shop_id` უნდა ეკუთვნოდეს user-ს) |
| GET | `/products` | პროდუქტების სია (არასავ. `?shop_id=` ფილტრი) |
| PUT | `/products/{id}` | პროდუქტის ნაწილობრივი განახლება |
| DELETE | `/products/{id}` | პროდუქტის წაშლა |
| POST | `/products/import` | Excel/CSV bulk import (multipart: `shop_id` + `file`) |

### Excel/CSV import ფორმატი (ნაბიჯი 6)

პირველი მწკრივი — სათაურები. სვეტები (ქართ. ან ინგ., რეგისტრი არ აქვს მნიშვნელობა):

| სვეტი | სავალდებულო | მაგალითი |
|---|---|---|
| სახელი / name | ✅ კი | პური |
| ფასი / price | არა (default 0) | 2.50 |
| მარაგი / quantity | არა (default 0) | 100 |
| დეტალები / description | არა | თეთრი პური |
| sku | არა | BR-001 |

ნიმუშები: [sample-products.xlsx](frontend/sample-products.xlsx), [sample-products.csv](frontend/sample-products.csv).
ვალიდაცია „all-or-nothing": თუ ფაილში თუნდაც ერთი შეცდომაა, არცერთი არ ემატება და
ბრუნდება ყველა შეცდომა მწკრივის ნომრით. მაქს. 5MB, 5000 მწკრივი.

### ბოტი (ნაბიჯი 4)

| Method | Path | აღწერა |
|---|---|---|
| POST | `/test-chat` | ⚠️ DEV: ბოტის ტესტი Messenger-ის გარეშე (`shop_id`, `message`, `history`) |

`get_bot_reply(shop, products, message, history)` ([app/services/bot.py](backend/app/services/bot.py))
იძახებს Gemini-ს, პასუხობს ქართულად მხოლოდ მაღაზიის **აქტიური** მარაგით.
საჭიროა `GEMINI_API_KEY` .env-ში (https://aistudio.google.com/apikey).

### Facebook Messenger (ნაბიჯი 5)

| Method | Path | აღწერა |
|---|---|---|
| GET | `/webhook` | Meta webhook ვერიფიკაცია (challenge) |
| POST | `/webhook` | შემოსული შეტყობინებები (X-Hub-Signature-256 შემოწმებით) |
| GET | `/facebook/connect/start` | OAuth-ის დაწყება (auth, აბრუნებს login_url) |
| GET | `/facebook/connect/callback` | OAuth callback — page token-ის შენახვა + webhook subscribe |
| POST | `/facebook/disconnect` | გვერდის გათიშვა |

page token ინახება **დაშიფრულად** (Fernet, `FB_TOKEN_ENCRYPTION_KEY`). webhook ამოწმებs
ხელმოწერას app secret-ით. იხ. ქვემოთ „Meta App setup + ngrok".

### შეკვეთები (ნაბიჯი 7)

| Method | Path | აღწერა |
|---|---|---|
| GET | `/public-menu?shop_id=` | საჯარო: მაღაზია + აქტიური პროდუქტები (ფორმისთვის) |
| POST | `/orders` | საჯარო: კლიენტი ქმნის შეკვეთას |
| GET | `/orders` | გამყიდველი — მისი შეკვეთები (auth, RLS) |
| PATCH | `/orders/{id}` | სტატ უსის შეცვლა (new/processing/done/cancelled) |

ბოტი ავტომატურად აძლევს კლიენტს მაღაზიის შესაკვეთ ლინკს, როცა ის შეკვეთას ჰკითხ ავს
(ლინკი თითო მაღაზიისთვის `shop_id`-დან იგება — იხ. `order_link_for` bot.py-ში; base URL:
`PUBLIC_BASE_URL` ან `FB_REDIRECT_URI`-ის დომენი).

შესაკვეთი ფორმა: [frontend/order.html](frontend/order.html) — გაიხ სნება ლინკით
`order.html?shop=<shop_id>`. SQL: [supabase/migrations/0002_orders.sql](supabase/migrations/0002_orders.sql).
შეკვეთის ჩაწერა service_role-ით ხდება (კლიენტი ავტორიზებული არ არის); გამყიდველი
შეკვეთებს RLS-ით ხედავს. ფორმის ლინკი Facebook გვერდის „Shop Now" ღილაკში მაგრდება.

ინტერაქტიული დოკუმენტაცია: http://localhost:8000/docs

## ნაბიჯი 1 — Supabase setup

იხ. [supabase/migrations/0001_init.sql](supabase/migrations/0001_init.sql) და
README-ის ბოლოს მოცემული ინსტრუქცია dashboard-ში გასაშვებად.

## ნაბიჯი 5 — Meta App setup + ngrok ტესტი

Facebook-ს სჭირდება **https** საჯარო მისამართი. ლოკალურად ამას ngrok აძლევს.

### 1. ngrok
```powershell
# დააყენე https://ngrok.com/download , დარეგისტრირდი, აიღე authtoken
ngrok config add-authtoken <შენი-token>
ngrok http 8000
```
დაიმახსოვრე გაცემული https მისამართი, მაგ: `https://ab12cd.ngrok-free.app`

### 2. Meta App შექმნა
1. https://developers.facebook.com/apps → **Create App** → ტიპი: **Business**
2. App-ში დაამატე პროდუქტი **Messenger** (Add Product → Messenger → Set up)
3. **App Settings → Basic**: დააკოპირე **App ID** და **App Secret**

### 3. .env შევსება
```
FB_APP_ID=<App ID>
FB_APP_SECRET=<App Secret>
FB_VERIFY_TOKEN=ჩემი_საიდუმლო_ვერიფიკაცია_123   # ნებისმიერი, ოღონდ დაიმახსოვრე
FB_REDIRECT_URI=https://ab12cd.ngrok-free.app/facebook/connect/callback
FB_TOKEN_ENCRYPTION_KEY=<უკვე დაგენერირებულია>
```
შეცვლის შემდეგ **გადატვირთე backend** (.env reload-ს ხელით საჭიროებს).

### 4. Webhook კონფიგურაცია Meta-ში
Messenger → **Configure webhooks**:
- **Callback URL:** `https://ab12cd.ngrok-free.app/webhook`
- **Verify Token:** იგივე რაც `FB_VERIFY_TOKEN`
- დააჭირე **Verify and Save** (backend უნდა მუშაობდეს — GET /webhook დაადასტურებს)
- **Subscribe** ველებზე: **messages**, **messaging_postbacks**

### 5. OAuth redirect
App → **Facebook Login → Settings** (თუ არ არის, დაამატე „Facebook Login" პროდუქტი):
- **Valid OAuth Redirect URIs:** `https://ab12cd.ngrok-free.app/facebook/connect/callback`

### 6. საჭირო permissions (App Review-მდე — Dev Mode)
Dev mode-ში მუშაობს მხოლოდ App-ის როლებში დამატებულ ანგარიშებზე:
- `pages_show_list`, `pages_messaging`, `pages_manage_metadata`
- App Roles → დაამატე შენი Facebook ანგარიში (Admin/Tester)
- (Production-ისთვის ამ permission-ებზე App Review დაგჭირდება)

### 7. ტესტი შენს გვერდზე
1. backend + frontend + ngrok — სამივე გაშვებული
2. Chrome → http://localhost:5500 → შედი → აირჩიე მაღაზია → **„Facebook გვერდის დაკავშირება"**
3. Facebook-ის ფანჯარა → აირჩიე შენი გვერდი → დაეთანხმე → დაბრუნდები პანელში „დაკავშირდა"-ით
4. გახსენი შენი Facebook **გვერდი** Messenger-ში (სხვა ანგარიშიდან ან Test User-ით) და მისწერე — ბოტი ქართულად, მაღაზიის მარაგით უპასუხებს

> ⚠️ ngrok-ის უფასო მისამართი ყოველ გადატვირთვაზე იცვლება — მაშინ განაახლე `FB_REDIRECT_URI`,
> Meta-ს webhook callback და OAuth redirect URIs.
