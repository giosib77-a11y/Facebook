# ChatAssist

> ეს ფაილი პროექტის **მოთხოვნებს, წესებს და გადაწყვეტილებებს** აჯამებს. დეტალები არ
> მეორდება — მითითებულია არსებულ დოკუმენტებზე. მიმდინარე task-ები: `PROGRESS.md`.

## Overview
Multi-tenant SaaS ქართული მაღაზიებისთვის: გამყიდველი რეგისტრირდება, ტვირთავს მარაგს და
აკავშირებს Facebook გვერდს; Messenger/Instagram-ში მისულ კლიენტს AI ბოტი (Gemini)
პასუხობს **მხოლოდ ამ მაღაზიის რეალურ მარაგზე** დაყრდნობით, ფოტოს ცნობს, აძლევს შესაკვეთ
ლინკს და საჭიროებისას ოპერატორზე გადართავს.
სრული აღწერა: [README.md](README.md) §1, §5.

## Users
- **გამყიდველი (seller)** — Supabase Auth ანგარიში; ფლობს 1+ მაღაზიას (პაკეტის ლიმიტით).
- **კლიენტი (customer)** — ავტორიზაციის გარეშე: Messenger/Instagram-ის PSID, ან საჯარო
  შესაკვეთი ფორმა `order.html?shop=<id>`.
- **ადმინი (პლატფორმის მფლობელი)** — `ADMIN_USER_IDS`-ში ჩაწერილი Supabase user UUID.

## Current Stage
**Live production** — chatassist.ge (Render). Meta Business Verification ⏳, App Review ⬜,
Development → Live ⬜ ([README.md](README.md) §2). ამჟამინდელი სამუშაო ეტაპი:
**Stage 10 — Audit fixes** (იხ. `PROGRESS.md`).

## Scope
### In scope (current stage)
- აუდიტის მიგნებების გასწორება (security / tenant isolation / abuse / data integrity)
- მინიმალური lint/test setup-ის შენარჩუნება და გაფართოება
### Out of scope (for now)
- ახალი ფიჩერები — [ROADMAP.md](ROADMAP.md) (Instagram Live, web widget, ინტეგრაციები,
  ავტომატური billing, Redis/queue, CSP, admin pagination)

## Core Flows
1. რეგისტრაცია → მაღაზია → პროდუქტები (ხელით / Excel / CSV) → PDF-ცოდნა.
2. Facebook OAuth connect → page token (დაშიფრული) → webhook subscribe.
3. Meta webhook (`POST /webhook`, ხელმოწერით) → page_id → მაღაზია → ლიმიტები →
   Gemini → Send API პასუხი (background task).
4. საჯარო შეკვეთა (`POST /orders`) → სერვერი ითვლის ჯამს → შეკვეთა `new` სტატუსით; მარაგი **არ იკლებს** ((IP, shop)-ზე დღიური ლიმიტი).
5. გამყიდველი მართავს შეკვეთებს: `new → processing` ატომურად აკლებს მარაგს (არასაკმარისზე 409); `processing/done → cancelled` აბრუნებს; `new`-ის გაუქმება მარაგს არ ეხება.
6. პაკეტის მოთხოვნა (`upgrade_requests`) → ადმინი ხელით ადასტურებს.
7. Meta Data Deletion callback + ხელმოწერილი დადასტურების კოდი.

## Business Rules
- პაკეტები/ლიმიტები/ფასები: `backend/app/core/tiers.py` (წყარო) · ბიზნეს-ლოგიკა:
  [MONETIZATION.md](MONETIZATION.md). მთავარი მეტრიკა — **უნიკალური კლიენტი თვეში**.
- გამოწერა **per-account**-ია (მფლობელის უმაღლესი პაკეტი), არა per-shop.
- ლიმიტები მოწმდება **სერვერზე**; downgrade-ზე მონაცემი არ იშლება — ზედმეტ მაღაზიებზე
  ბოტი ითიშება.
- ერთი კლიენტი — მაქს. 100 შეტყობინება დღეში (`DAILY_ABUSE_CAP`).
- შეკვეთის ჯამს ითვლის სერვერი; კლიენტის ფასს არ ენდობა. მარაგი მინუსში არ ჩადის.
- ბოტი არ იგონებს პროდუქტს/ფასს — მხოლოდ მაღაზიის აქტიური მარაგი.
- Excel/CSV/PDF ატვირთვა — მხოლოდ ფასიან პაკეტებზე.

## Data
Supabase Postgres, ყველა ცხრილზე RLS; სქემა — `supabase/migrations/0001..0020`
(სია: [README.md](README.md) §7, მოძველებულია 0014-ზე).
- `shops` (owner_id → auth.users) 1—N `products`, `orders`, `bot_customers`,
  `bot_conversations`, `upgrade_requests`
- `orders.items` — JSON პოზიციები; ფული — numeric
- Storage: product images bucket (საჯარო, per-shop folder)

## Integrations
- **Meta Graph API** (`v21.0`) — OAuth, Send API, webhook, Instagram Messaging.
  Setup: [README.md](README.md) §10, [INSTAGRAM_SETUP.md](INSTAGRAM_SETUP.md),
  [APP_REVIEW_TEXTS.md](APP_REVIEW_TEXTS.md)
- **Google Gemini** (`gemini-2.5-flash`) — ბოტის პასუხი, multimodal.
- **Supabase** — DB, Auth, Storage.
- **Cloudflare** — DNS/proxy, `CF-Connecting-IP`, origin-lock header.

## Stack & Architecture
- Complexity tier: მცირე SaaS, ერთი backend instance (modular monolith)
- Frontend: React 19 + Vite **MPA** (8 გვერდი); `frontend/dist/` git-შია
- Backend: FastAPI (Python 3.14), sync handlers + FastAPI BackgroundTasks
- Database: Supabase Postgres + RLS + RPC-ები (EXECUTE მხოლოდ service_role-ს; `track_bot_customer` — DEFINER, stock RPC-ები — INVOKER)
- Storage: Supabase Storage
- Auth: Supabase Auth; backend ამოწმებს JWT-ს `auth.get_user()`-ით და DB-ს მომხმარებლის
  JWT-ით მიმართავს
- Hosting / deployment: Render (Starter), auto-deploy `main`-ზე push-ისას, Cloudflare წინ.
  Checklist: [DEPLOYMENT.md](DEPLOYMENT.md)

## Realistic Scale
ათეულობით მაღაზია პირველ წელს; კლიენტები — ასობით/ათასობით თვეში (პაკეტის ჭერებით).
ერთი Render instance საკმარისია; in-memory rate-limit/dedup ამ მასშტაბზე მისაღებია.

## Security & Privacy
- Tenant isolation: RLS (`shops.owner_id = auth.uid()`) + column privileges (0015);
  service_role მხოლოდ backend-ში (webhook, საჯარო შეკვეთა, storage, admin).
- Page token — Fernet-ით დაშიფრული (`FB_TOKEN_ENCRYPTION_KEY`).
- Webhook — `X-Hub-Signature-256`; Graph — `appsecret_proof`.
- პერსონალური მონაცემი: კლიენტის სახელი/ტელეფონი/მისამართი (შეკვეთები), საუბრები.
  Privacy/Terms/Data Deletion/ექსპორტი არსებობს.
- დაცვების სრული სია: [README.md](README.md) §8. წინა რევიუები:
  [CODE_REVIEW_FINDINGS.md](CODE_REVIEW_FINDINGS.md), [SECURITY_FIX_PROMPT.md](SECURITY_FIX_PROMPT.md),
  commit-ები `F-xx` / `FA-xx` / `N-xx`.

## Constraints
- პროექტი **ლაივზეა**: `main`-ზე push = production deploy. push/merge მხოლოდ მფლობელის
  თანხმობით; სამუშაო ბრენჩი `agent-system`.
- აგენტს **არ** აქვს უფლება: remote Supabase-ზე migration/ბრძანება, Meta API-ს გამოძახება,
  Gemini რეალური key-ით, deploy, `.env`-ის წაკითხვა/შეცვლა.
- ტესტები მხოლოდ ლოკალურად და იზოლირებულად (fake Supabase, mock Graph/Gemini).
- მიგრაციებს მფლობელი უშვებს ხელით (Supabase SQL Editor).
- Render-ზე Node არ არის → frontend build ლოკალურად, `dist/` commit-ში.
- Gemini — free tier (5 req/min); billing გაშვებამდე ჩასართავია.
- Meta-ს ანგარიშის რისკი — ალტერნატიული არხები ROADMAP-შია.
- ბიუჯეტი ~35₾/თვე ([DEPLOYMENT.md](DEPLOYMENT.md)). ენა/რეგიონი — საქართველო, UI ქართულად.

## Decision Log
> კოდიდან და git-ის ისტორიიდან აღდგენილი გადაწყვეტილებები (თარიღი ≈ შესაბამისი commit).

### 2026-06 — Supabase (Postgres + RLS + Auth + Storage) როგორც ერთი backend-სერვისი
- Decision: DB, auth და storage — Supabase; იზოლაცია RLS-ით.
- Reason: multi-tenant იზოლაცია DB-ის დონეზე, auth/storage-ის მზა გადაწყვეტა, მცირე ხარჯი.
- Alternatives considered: საკუთარი Postgres + auth.
- Why rejected: მეტი ინფრასტრუქტურა ერთი დეველოპერისთვის.

### 2026-06 — Backend მომხმარებლის JWT-ით მიმართავს DB-ს; service_role მხოლოდ გამონაკლისებზე
- Decision: `CurrentAuth.client` = anon key + მომხმარებლის token (RLS მოქმედებს);
  `get_service_client()` — მხოლოდ webhook/ბოტი, საჯარო შეკვეთა, storage, admin, upgrade.
- Reason: tenant isolation არ უნდა იყოს დამოკიდებული ყოველ query-ში ხელით ჩაწერილ ფილტრზე.
- Alternatives considered: ყველგან service_role + `owner_id` ფილტრი კოდში.
- Why rejected: ერთი გამორჩენილი ფილტრი = სხვისი მონაცემის გაჟონვა.

### 2026-06 — Gemini (`gemini-2.5-flash`) ბოტის მოდელად, `GEMINI_MODEL`-ით შეცვლადი
- Decision: Google Gemini, multimodal, temperature 0.3, max 800 output tokens.
- Reason: ფასი, ქართული ენის ხარისხი, ფოტოს მხარდაჭერა.
- Alternatives considered: სხვა LLM providers.
- Why rejected: ფასი/ხარისხის თანაფარდობა; იხ. memory „Costs & pricing" (2.5 Flash retires 2026-10-16).

### 2026-07 — ლიმიტი = უნიკალური კლიენტი თვეში (არა შეტყობინება); per-account გამოწერა
- Decision: `bot_customers` მრიცხველი + `track_bot_customer()` RPC; მფლობელის უმაღლესი პაკეტი.
- Reason: გამყიდველისთვის გასაგები და პროგნოზირებადი; abuse — ცალკე დღიური ჭერი.
- Alternatives considered: per-message ბილინგი; per-shop პაკეტი.
- Why rejected: ნდობის პრობლემა („50 მომწერი / 5 მყიდველი") — [MONETIZATION.md](MONETIZATION.md).

### 2026-07 — გადახდა ხელით (`upgrade_requests` → ადმინის დადასტურება)
- Decision: ავტომატური billing არ არის.
- Reason: მცირე მასშტაბი; payment provider-ის ინტეგრაცია ნაადრევია.
- Alternatives considered: payment gateway.
- Why rejected: YAGNI ამ ეტაპზე.

### 2026-07 — მარაგის ატომური ცვლილება Postgres RPC-ით (row-lock); სტატუსი — ოპტიმისტური ჩაკეტვა
- Decision: `decrement_stock()` / `apply_stock_delta()` RPC-ები (INVOKER, იძახებს მხოლოდ service_role); სტატუსის
  ცვლილება 409-ით კონფლიქტზე.
- Reason: პარალელური შეკვეთები მარაგს მინუსში არ უნდა ჩააგდებდეს.
- Alternatives considered: read-modify-write backend-ში.
- Why rejected: race condition.

### 2026-08 — Frontend React + Vite MPA; `dist/` commit-ში
- Decision: 8 ცალკე HTML entry; build ლოკალურად, შედეგი git-ში.
- Reason: Render-ის Python სერვისზე Node არ არის; FastAPI ასერვირებს static-ს.
- Alternatives considered: SPA; ცალკე static hosting; CI build.
- Why rejected: მეტი ინფრასტრუქტურა; spec — [REACT_MIGRATION.md](REACT_MIGRATION.md).

### 2026-08 — Page token-ის შიფვრა Fernet-ით
- Decision: `core/crypto.py`, key — `FB_TOKEN_ENCRYPTION_KEY`.
- Reason: DB-ის გაჟონვისას token-ები პირდაპირ გამოუსადეგარია.
- Alternatives considered: Supabase Vault.
- Why rejected: მარტივი, provider-დამოუკიდებელი.

### 2026-08 — RPC-ების EXECUTE მხოლოდ service_role-ს (მიგრაცია 0014)
- Decision: anon/authenticated-ს EXECUTE მოხსნილი.
- Reason: P0 — anon-ს შეეძლო მრიცხველის გაბერვა ([SECURITY_FIX_PROMPT.md](SECURITY_FIX_PROMPT.md)).

### 2026-08 — Rate limit და webhook-ის dedup მეხსიერებაში (ერთი instance)
- Decision: in-process sliding window + `OrderedDict` mid-cache.
- Reason: ერთი Render instance; Redis ზედმეტია ამ მასშტაბზე.
- Alternatives considered: Redis, Cloudflare rate limiting, queue.
- Why rejected: ხარჯი/სირთულე; გამშვები პირობები — [ROADMAP.md](ROADMAP.md) 🏗.

### 2026-09 — Cloudflare წინ: IP `CF-Connecting-IP`-დან, origin lock საიდუმლო header-ით (F-03A, FA-03)
- Decision: `X-Forwarded-For` არ იკითხება; production-ში header-ის გარეშე → 403.
- Reason: XFF ყალბდება; Render-ის origin-ის პირდაპირი მიმართვა rate-limit-ს უვლის გვერდს.
- Status: IP-ის ნაწილი superseded → იხ. 2026-10 (T17); origin lock კოდში რჩება (T13, Backlog).

### 2026-10 — კლიენტის IP `X-Forwarded-For`-ის მარჯვენა ჰოპებიდან (Render), CF header იგნორირდება (T17)
- Decision: IP = XFF-ის მარჯვნიდან `CLIENT_IP_TRUSTED_HOPS`-ური ჩანაწერი (default 1); ნაკლები ჩანაწერი → socket peer. `CF-Connecting-IP` სრულად იგნორირდება; `CLIENT_IP_HEADER` წაიშალა. დროებითი `CLIENT_IP_DEBUG` სწორი N-ის დასადგენად.
- Reason: Cloudflare არ გამოიყენება; Render არ ასუფთავებს კლიენტის XFF-ს, მხოლოდ მარჯვნივ ამატებს → მარცხენა ჩანაწერები გაყალბებადია, მარჯვენა სანდოა. ჰოპების ზუსტი რაოდენობა დოკუმენტირებული არ არის → ემპირიულად.

### 2026-09 — ადმინი იდენტიფიცირდება user UUID-ით (`ADMIN_USER_IDS`), არა email-ით (F-08)
- Decision: ცარიელი სია = ადმინი არავინაა (fail closed).
- Reason: email სტაბილური იდენტობა არ არის.

### 2026-09 — CI: GitHub Actions — pip check, compileall, pytest (fake Supabase, offline)
- Decision: `.github/workflows/ci.yml`, lock-ფაილიდან ინსტალაცია.
- Reason: რეგრესიების დაჭერა ლაივ პროექტზე.

### 2026-10 — მარაგი იკლებს მხოლოდ `new → processing`-ზე + (IP, shop)-ზე დღიური ლიმიტი (B-1, T21)
- Decision: საჯარო შეკვეთა მარაგს არ ეხება; დაკლება გამყიდველის დადასტურებისას; `PUBLIC_ORDERS_PER_IP_SHOP_PER_DAY = 20` (key `ip|shop_id`, შემოწმება handler-შია, DB-მდე).
- Reason: ყალბი საჯარო შეკვეთებით მარაგის განულება.
- Alternatives considered: დროებითი reservation/TTL; CAPTCHA.
- Why rejected: სირთულე; `new`-ში overselling მისაღებია, გამყიდველი ადასტურებს.

### 2026-10 — Gemini 2.5 Flash vs 3.5 Flash: პირველი შედარება (10 ქართული შეკითხვა, temperature 0.3, max 800)
- Result (`backend/scripts/compare_gemini_models.py`): ორივე მოდელმა სწორად გაიგო ფასი, მარაგი, მიწოდება, ბმული, რუსული/ინგლისური და `[[HANDOFF]]`.
  2.5-flash: საშ. 2.2 წმ, thinking 1517 ტოკენი სულ, 0 ჩამოჭრილი. 3.5-flash (default thinking): საშ. 4.2 წმ, thinking 6517 ტოკენი (≈4×), **4/10 პასუხი ჩამოიჭრა** `MAX_TOKENS`-ზე (thinking ბიუჯეტს ჭამს), პასუხები უფრო მრავლისმთქმელი, მაგრამ off-topic-ზე შარფის დაუსწრებელი შეთავაზება.
- Decision: მოდელი ჯერ არ იცვლება; 3.5-flash `thinking_config`-ის შეზღუდვის გარეშე ბოტისთვის უვარგისია. შეფასება გადადებულია (PROGRESS.md Backlog T12): 2.5-flash, 3.5-flash შეზღუდული thinking-ით და Claude Haiku 4.5 — ხარისხი, სიჩქარე, ფასი თითო პასუხზე.
- Caveat: ერთი გაშვება, ერთგზისი შეკითხვები ისტორიისა და ფოტოს გარეშე; ბოტის რეალურ სცენარებზე არ განზოგადდეს.
- Emergency: 2.5-flash-ის გათიშვისას (2026-10-16) `GEMINI_MODEL=gemini-3.5-flash` Render-ზე, ჩამოჭრის რისკით — იხ. Deploy plan.

### 2026-10 — uvicorn proxy-headers რჩება ჩართული; `request.client.host` არ გამოიყენება IP-ლიმიტის key-ად (T22)
- Context: ლაივ-ტესტით (X-Forwarded-For: 1.2.3.4) დადასტურდა — uvicorn proxy-headers `request.client.host`-ს კლიენტის XFF-ით ანაცვლებს (access log: `1.2.3.4:0`), ანუ `peer` გაყალბებადია. გარდა ამისა, `app` logger-ზე handler/level არ იყო → INFO ჩანაწერები production-ში იკარგებოდა.
- Decision: (1) `_client_ip` production-ში XFF-ის ნაკლებობისას აბრუნებს ფიქსირებულ საერთო key-ს `unknown` და არა `peer`-ს; (2) `app` logger stdout-ზე `LOG_LEVEL`-ით (default INFO); (3) `--no-proxy-headers` **ჯერ არ ვრთავთ**.
- Reason: კოდში `request.url.scheme`/`X-Forwarded-Proto` პირდაპირ არსად გამოიყენება (HSTS და cookie `secure` — `is_production`-ით, OAuth redirect — settings-იდან, `RedirectResponse` ფარდობითია), მაგრამ Starlette-ის `StaticFiles`/FastAPI-ის trailing-slash redirect აბსოლუტურ `Location`-ს scope-ის scheme-ით აგებს (TestClient-ით დადასტურდა: `http://chatassist.ge/panel/`). `--no-proxy-headers`-ით Render-ის უკან აპი `http`-ს დაინახავდა → redirect-ები `http://`-ზე წავიდოდა (ზედმეტი hop, fetch-ის შემთხვევაში mixed-content რისკი). ლაივზე ეს არ გამოცდილა.
- Live result (2026-10-08, მფლობელი): `CLIENT_IP_TRUSTED_HOPS=3`; Render-ზე XFF ჯაჭვი = `<ყალბი>, <კლიენტი>, <Render-ის Cloudflare>, <Render-ის შიდა>` — კლიენტი მარჯვნიდან მე-3 ჩანაწერია; გაყალბებული ჩანაწერები მარცხნივ რჩება და resolved IP-ზე გავლენას არ ახდენს.
- Alternatives considered: `--no-proxy-headers`; `--forwarded-allow-ips` კონკრეტული CIDR-ით (მხოლოდ XFF ჯაჭვის რეალური ფორმის გაგების შემდეგ).
- Why rejected: პირველი — redirect-ის რისკი, მეორე — ჯერ გაუგებარი ჯაჭვი; მიმდინარე გადაწყვეტა ამას გარეშე ხურავს გაყალბებას.

### 2026-10-09 — საიდუმლოების როტაცია გაჟონვის შემდეგ
- Done (მფლობელი, ლაივზე): Supabase → ახალი `sb_publishable_`/`sb_secret_` key-ები, legacy JWT key-ები გამორთულია (ძველი anon-ით REST → 401); `FB_APP_SECRET` შეცვლილია; `FB_TOKEN_ENCRYPTION_KEY` შეცვლილია — ძველით დაშიფრული page token-ები გამოუსადეგარი გახდა და Facebook/Instagram-მიბმული ერთადერთი მაღაზია ხელახლა დაუკავშირდა (ბოტი პასუხობს).
- Open: Gemini key-ის როტაცია (მფლობელი წყვეტს როდის).
- Note: `FB_TOKEN_ENCRYPTION_KEY`-ის შეცვლა ყველა ამ key-ით დაშიფრულ token-ს აუქმებს — მომავალში მაღაზიების რაოდენობის გაზრდისას ეს ხელახალი connect-ებს მოითხოვდა.

## Accepted Risks
<!-- მიღებული რისკები: რა, რატომ მისაღებია, გადახედვის პირობა. ივსება მფლობელის გადაწყვეტილებით. -->

## Open Questions
- README §2/§6/§12/§14 მოძველებულია (ADMIN_EMAIL → ADMIN_USER_IDS, „ტესტები არ არსებობს",
  React 18 → 19, მიგრაციები 14 → 16) — განახლდეს?
- Gemini 2.5 Flash retires 2026-10-16 — გადაწყვეტილება გადადებულია (Backlog T12, Decision Log 2026-10); საგანგებო გეგმა Deploy plan-შია.
