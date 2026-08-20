# 🚀 სერვერზე ატვირთვის (Deploy) Checklist

> ეს ფაილი შენახ ულია მომავლისთვის. როცა ჰოსტინგზე ატვირთვას გადავწყვეტთ,
> გავივლით ბიჯ-ბიჯ. ✅ = გაკეთებულია, ☐ = გასაკეთებელი.

---

## 🏗️ ყოველ deploy-ზე — ჯერ BUILD (2026-08-20-იდან)

frontend **React-ზეა (Vite)**. push-ამდე build აუცილებელია — თორემ ლაივზე ძველი
ვერსია წავა.

```bash
cd frontend
npm install      # პირველად, ან package.json-ის ცვლილებისას
npm run build    # → frontend/dist/
```

⚠️ **Render-ს Node.js არ აქვს** (Python-სერვისია) — `npm run build` სერვერზე
**ვერ გაეშვება**. ამიტომ `dist/` **git-ში ინახება** და ლოკალურად იგება.

push-ამდე შემოწმება:
- [ ] `frontend/dist/`-ში **8 `.html`** + `config.js`, `favicon.svg`, 2 sample-ფაილი
- [ ] საიდუმლოების სკანი (ცარიელი უნდა იყოს):
      `grep -rin "service_role\|FB_APP_SECRET\|GEMINI\|FERNET" frontend/dist/`
      (`config.js`-ის კომენტარი ცრუ დამთხვევაა — მასში მხოლოდ anon key-ია)
- [ ] `dist/` დაკომიტებულია

**უსაფრთხოების ბადე:** თუ `dist/` არ არსებობს, `main.py` ავტომატურად ძველ
`frontend/`-ს ასერვირებს. თუ `dist/` არსებობს მაგრამ გატეხილია — fallback **არ**
ჩაირთვება; მაშინ `git revert` ან `dist/`-ის წაშლა + push.

> სრული მიგრაციის სპეციფიკაცია: **`REACT_MIGRATION.md`**

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
- [ ] `frontend/public/config.js` → `API_BASE` (თუ backend სხ ვა დომენზეა)

### 3. CORS — შემოვფარგლოთ
- [x] **კოდი მზადაა** — CORS ახლა `.env`-ის `CORS_ORIGINS`-იდან იკითხება
      (`backend/app/main.py` + `config.py`). dev-ში `*`, production-ში კონკრეტული დომენი.
- [ ] deploy-ზე: `.env`-ში `CORS_ORIGINS=https://shendomen.ge` (მხ ოლოდ env-ცვლადის დაყენება)

### 4. Supabase Auth — email დადასტურება ისევ ჩავრთოთ
- [ ] "Confirm email" ისევ ჩართე (ტესტისთვის გამორთული იყო)
- [ ] SMTP დავაყენოთ (Resend / SendGrid / Mailgun) — ჩაშენებული email
      საათში ~3-4 წერილს უშვებს, რეალურ მომხ მარებლებს არ ეყოფა
      (ეს პაროლის აღდგენასაც ეხ ება)

### 5. `public/config.js` — მხ ოლოდ საჯარო გასაღებები
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
- [x] **8.2 Privacy Policy + Terms + Data Deletion** — გვერდები მზადაა, რეალურ დომენზე ხელმისაწვდომია
      - Privacy Policy URL: `<base>/panel/privacy.html`
      - Terms URL: `<base>/panel/terms.html`
      - Data Deletion **Instructions** URL: `<base>/panel/delete-data.html`
      - Data Deletion **Callback** URL: `<base>/facebook/data-deletion`
        (Meta POST-ავს `signed_request`-ს → ვშლით კლიენტის საუბრებს PSID-ით → ვაბრუნებთ
        `{url, confirmation_code}`. კოდი: `services/facebook.parse_signed_request` +
        `api/facebook.data_deletion_callback`.)
      - [ ] Meta App → Settings → Basic-ში ეს URL-ები ჩაწერე (`<base>` = `https://shop-bot-7q7r.onrender.com`,
            მოგვიანებით custom დომენი). Meta-ს „Data Deletion Instructions URL" ველში
            ჩააგდე Instructions URL **ან** Callback URL — ორივე გვაქვს.
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
- `frontend/public/config.js` → `API_BASE`
- Facebook App დაფა (გარე) → Redirect + Webhook URL
- Supabase დაფა (გარე) → Redirect URLs + email confirm + SMTP

---

## 🌐 custom დომენზე გადასვლისას — რა შევცვალო (URL swap)

> როცა .ge დომენს დაარეგისტრირებ და Render-ში Custom Domain-ად დაამატებ,
> onrender-URL 3 ადგილას უნდა შეიცვალოს დომენით. იგივე ცვლილებაა, რაც
> ngrok → Render-ზე გადასვლისას. კოდი არ იცვლება, onrender-URL მაინც მუშაობს.

**1. Render → Environment (env ცვლადები):**
- `PUBLIC_BASE_URL`  → `https://<დომენი>`
- `CORS_ORIGINS`     → `https://<დომენი>`
- `FB_REDIRECT_URI`  → `https://<დომენი>/facebook/connect/callback`
- `FRONTEND_URL`     → `https://<დომენი>`

**2. Meta App (jemo):**
- Webhooks → Callback URL → `https://<დომენი>/webhook`
- Facebook Login for Business → Valid OAuth Redirect URIs → `https://<დომენი>/facebook/connect/callback`

**3. Supabase → Authentication → URL Configuration:**
- Site URL + Redirect URLs → `https://<დომენი>/panel/reset.html` (და დომენი)

> ⚠️ Meta-ს webhook-ის შეცვლის შემდეგ ისევ „Verify and save" (handshake).
