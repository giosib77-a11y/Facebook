# 🚀 სერვერზე ატვირთვის (Deploy) Checklist

> ეს ფაილი შენახ ულია მომავლისთვის. როცა ჰოსტინგზე ატვირთვას გადავწყვეტთ,
> გავივლით ბიჯ-ბიჯ. ✅ = გაკეთებულია, ☐ = გასაკეთებელი.

---

## 🔴 კრიტიკული (ამის გარეშე არ ვტვირთავთ)

### 1. საიდუმლო გასაღებები — `.env` არასდროს სერვერზე ფაილად
- [ ] `SUPABASE_SERVICE_ROLE`, `GEMINI_API_KEY`, `FB_APP_SECRET`, `FERNET_KEY`
      გადავიტანოთ hosting-ის **Environment Variables**-ში (არა ფაილად რეპოში)
- [ ] დავრწმუნდეთ რომ `.env` **არასდროს** აიტვირთა Git-ზე (`git log` შემოწმება)
- [ ] თუ ერთხ ელ მაინც აიტვირთა — **ყველა გასაღები შევცვალოთ** (rotate)
- [ ] `FERNET_KEY` — იგივე გასაღები დავტოვოთ (ის შიფრავს page token-ებს;
      შეცვლა = ყველა გვერდი თავიდან უნდა დაუკავშირდეს)

### 2. HTTPS + ფიქსირებული დომენი (ngrok წავა)
- [ ] ფიქსირებული დომენი + ავტო-SSL (hosting უზრუნველყოფს)
- [ ] `PUBLIC_BASE_URL` → ახ ალი დომენი
- [ ] `FB_REDIRECT_URI` → ახ ალი დომენი
- [ ] Facebook App → OAuth Redirect + Webhook Callback URL → ახ ალი დომენი
- [ ] Supabase → Redirect URLs → ახ ალი დომენი (`/panel/reset.html`)
- [ ] `frontend/config.js` → `API_BASE` (თუ backend სხ ვა დომენზეა)

### 3. CORS — შემოვფარგლოთ
- [x] **კოდი მზადაა** — CORS ახლა `.env`-ის `CORS_ORIGINS`-იდან იკითხება
      (`backend/app/main.py` + `config.py`). dev-ში `*`, production-ში კონკრეტული დომენი.
- [ ] deploy-ზე: `.env`-ში `CORS_ORIGINS=https://shendomen.ge` (მხ ოლოდ env-ცვლადის დაყენება)

### 4. Supabase Auth — email დადასტურება ისევ ჩავრთოთ
- [ ] "Confirm email" ისევ ჩართე (ტესტისთვის გამორთული იყო)
- [ ] SMTP დავაყენოთ (Resend / SendGrid / Mailgun) — ჩაშენებული email
      საათში ~3-4 წერილს უშვებს, რეალურ მომხ მარებლებს არ ეყოფა
      (ეს პაროლის აღდგენასაც ეხ ება)

### 5. `config.js` — მხ ოლოდ საჯარო გასაღებები
- [ ] გადავამოწმოთ: მხ ოლოდ `anon key` + `URL`
      (`service_role` / `FB_APP_SECRET` / `GEMINI_KEY` — არასდროს frontend-ში)

---

## 🟡 მნიშვნელოვანი

### 6. Rate limiting
- [x] **კოდი მზადაა** — საჯარო endpoint-ებზე per-IP rate limit ჩაშენდა
      (`backend/app/core/ratelimit.py`, დამოკიდებულების გარეშე, in-memory):
      `POST /orders` (10/წთ), `GET /public-menu` (60/წთ), `POST /test-chat` (15/წთ).
      reverse-proxy-ს (`X-Forwarded-For`) ითვალისწინებს.
- [ ] მრავალ-instance-ზე გადასვლისას → Redis/Cloudflare level (ერთ instance-ზე ეს საკმარისია)

### 7. მარაგის race condition
- [ ] `create_order`-ში მარაგის კლება ატომური გავხ ადოთ
      (Postgres RPC: `update ... set quantity = quantity - N where quantity >= N`)
      — დაბალ ტრაფიკზე არა სასწრაფო, მაგრამ ჩანიშნული

### 8. Facebook App → Live mode + App Review

> ახლა App **Development mode**-შია → ბოტთან მხოლოდ ტესტერები/ადმინები ურთიერთობენ.
> რომ ნებისმიერმა მომხმარებელმა შეძლოს წერა და გამყიდვლებმა გვერდები დააკავშირონ,
> საჭიროა Live mode + App Review. **წინაპირობა: ჯერ deploy (პუნქტი 2) — რეალური HTTPS
> დომენი; ngrok App Review-სთვის არ გამოდგება.**

თანმიმდევრობა:
- [ ] **8.1 ფიქსირებული HTTPS დომენი** — deploy დასრულებული (იხ. პუნქტი 2)
- [ ] **8.2 Privacy Policy + Terms + Data Deletion** — რეალურ დომენზე ხელმისაწვდომი
      - Privacy Policy URL (გვაქვს `privacy.html`)
      - Terms URL (გვაქვს `terms.html`)
      - Data Deletion ინსტრუქცია ან callback URL (Meta ითხოვს) — დასამატებელი
- [ ] **8.3 Business Verification** — ბიზნესის დადასტურება Meta-ში (დოკუმენტები/რეკვიზიტები);
      საჭიროა `pages_messaging`-ის Advanced Access-ისთვის
- [ ] **8.4 App-ის სავალდებულო ველები**
      - App Icon (1024×1024), App სახელი, კატეგორია
      - Privacy Policy URL + Data Deletion URL შევსებული App Settings-ში
- [ ] **8.5 App Review — ნებართვები** (თითოზე screencast ვიდეო საჭიროა)
      - `pages_messaging` (მესიჯების მიღება/გაგზავნა)
      - `pages_manage_metadata` (webhook subscription)
      - (სურვილისამებრ) `pages_show_list`, `pages_read_engagement`
- [ ] **8.6 Development → Live mode** გადართვა (App Dashboard-ის თავში)

> შენიშვნა: Standard Access = მხოლოდ app-ის role-ის მქონე ხალხი (ტესტერები).
> Advanced Access = ფართო საზოგადოება — სწორედ ეს სჭირდება App Review + Business Verification.

### 9. Debug/logs
- [x] **კოდი მზადაა** — `APP_ENV=production`-ზე:
      - გლობალური exception handler → კლიენტს ზოგადი „სერვერის შიდა შეცდომა" (stack trace არ ჟონავს)
      - `db.py` → ბაზის ნედლი ტექსტი აღარ უბრუნდება კლიენტს (მხოლოდ ლოგში)
      - dev endpoint `/test-chat` → 404 (დაუცველად Gemini-ს აღარ იძახებს)
- [ ] deploy-ზე: `.env`-ში `APP_ENV=production` დაყენება
- [ ] (სასურველი) Sentry უფასო tier — error tracking

---

## 🟢 სასურველი (მოგვიანებით)

- [ ] JWT ლოკალური ვერიფიკაცია (ყოველ request-ზე Supabase-ს არ დაეკითხ ოს — სისწრაფე)
- [ ] Pagination (პროდუქტები/შეკვეთები ბევრი რომ გახ დეს)
- [ ] DB backups (Supabase-ში ჩართვა/შემოწმება)
- [x] Security headers — ჩაშენდა (`X-Content-Type-Options`, `X-Frame-Options`,
      `Referrer-Policy`, `Permissions-Policy`; `HSTS` მხოლოდ production-ში). CSP — მოგვიანებით.
- [ ] Uptime მონიტორინგი (ბოტი რომ დაწვეს, გავიგოთ)

---

## 💰 ხარჯები — რა დაჯდება ატვირთვა (მიახლოებით, $1 ≈ 2.7₾)

| ვარიანტი | ღირებულება | შენიშვნა |
|---|---|---|
| **1. 🆓 უფასო** | **0₾/თვე** | Render/Koyeb free subdomain + HTTPS (Facebook-ს ვარგა). მინუსი: სერვერი უმოქმედობისას „იძინებს", პირველი პასუხი ნელია |
| **2. 💼 მინიმალური რეალური** | **~25–35₾/თვე** | Render Starter **$7** (≈19₾) ან Railway **$5** (≈14₾) + .ge დომენი **~60₾/წ** (≈5₾/თვე) + Gemini (დაბალ ტრაფიკზე თითქმის უფასო) |
| **3. 📈 ზრდის ეტაპზე** | **~50–80₾/თვე** | ცალკე DB / მეტი RAM, Sentry, მეტი Gemini — მხოლოდ მაშინ, როცა ბევრი კლიენტი იქნება |

**დაშლილი (ვარიანტი 2):**
- სერვერი (backend): ~14–19₾/თვე · .ge დომენი: ~5₾/თვე (60₾/წელი, წინასწარ იხდება)
- Gemini API: ~0–მცირე (გამოყენებაზეა) · Supabase: უფასო tier (ჯერ სრულად ჰყოფნის)

**რეკომენდაცია:** Render — მარტივი მართვა, env-ცვლადები, ავტო-HTTPS.

---

## 📦 რეკომენდებული ჰოსტინგი (ამ სტეკისთვის)

| ნაწილი | სად | შენიშ ვნა |
|---|---|---|
| **Backend** (FastAPI) | Railway ან Render | env vars-ით; ngrok-ს ცვლის |
| **Frontend** | იმავე backend-ის `/panel` (უკვე ასეა) ან Netlify/Vercel | |
| **DB + Auth** | Supabase (უკვე cloud) | იცვლება მხ ოლოდ Redirect URLs |

---

## 📝 შესაცვლელი ფაილები (ცნობისთვის)

- `.env` → hosting env vars
- `backend/app/main.py` → CORS `allow_origins`
- `frontend/config.js` → `API_BASE`
- Facebook App დაფა (გარე) → Redirect + Webhook URL
- Supabase დაფა (გარე) → Redirect URLs + email confirm + SMTP
