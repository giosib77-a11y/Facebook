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
- [ ] backend CORS `*`-იდან → **მხ ოლოდ ჩვენი დომენი**
      (`backend/app/main.py`, CORSMiddleware `allow_origins`)

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
- [ ] ღია endpoint-ებს (`/orders`, login, register) დავამატოთ rate limit
      (`slowapi` FastAPI-სთვის, ან Cloudflare level-ზე)

### 7. მარაგის race condition
- [ ] `create_order`-ში მარაგის კლება ატომური გავხ ადოთ
      (Postgres RPC: `update ... set quantity = quantity - N where quantity >= N`)
      — დაბალ ტრაფიკზე არა სასწრაფო, მაგრამ ჩანიშნული

### 8. Facebook App → Live mode + App Review
- [ ] App Review: `pages_messaging` + `pages_manage_metadata`
- [ ] Privacy Policy URL + App Icon
- [ ] Development → **Live mode**

### 9. Debug/logs
- [ ] პროდაქშენში debug/სიტყ ვიერი error-ები გამორთე (stack trace არ ჩანდეს)
- [ ] მინიმალური logging (Sentry უფასო tier — error tracking)

---

## 🟢 სასურველი (მოგვიანებით)

- [ ] JWT ლოკალური ვერიფიკაცია (ყოველ request-ზე Supabase-ს არ დაეკითხ ოს — სისწრაფე)
- [ ] Pagination (პროდუქტები/შეკვეთები ბევრი რომ გახ დეს)
- [ ] DB backups (Supabase-ში ჩართვა/შემოწმება)
- [ ] Security headers (CSP, HSTS)
- [ ] Uptime მონიტორინგი (ბოტი რომ დაწვეს, გავიგოთ)

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
