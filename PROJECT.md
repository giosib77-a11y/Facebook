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
**Stage 11 — Live-მზადყოფნა** (იხ. `PROGRESS.md`; Stage 10 — Audit fixes დასრულებულია).

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
Supabase Postgres, ყველა ცხრილზე RLS; სქემა — `supabase/migrations/0001..0024`
(სია: [README.md](README.md) §7).
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
- **Render** — hosting, TLS; კლიენტის IP `X-Forwarded-For`-ის მარჯვენა hop-იდან (T17). Cloudflare ამჟამად არ გამოიყენება (origin-lock კოდში ოფციაა, `ORIGIN_SECRET` ცარიელია).

## Stack & Architecture
- Complexity tier: მცირე SaaS, ერთი backend instance (modular monolith)
- Frontend: React 19 + Vite **MPA** (8 გვერდი); `frontend/dist/` git-შია
- Backend: FastAPI (Python 3.14), sync handlers + FastAPI BackgroundTasks
- Database: Supabase Postgres + RLS + RPC-ები (EXECUTE მხოლოდ service_role-ს; `track_bot_customer` — DEFINER, stock RPC-ები — INVOKER)
- Storage: Supabase Storage
- Auth: Supabase Auth; backend ამოწმებს JWT-ს `auth.get_user()`-ით და DB-ს მომხმარებლის
  JWT-ით მიმართავს
- Hosting / deployment: Render (Starter), auto-deploy `main`-ზე push-ისას; Cloudflare არ გამოიყენება (Render-ის საკუთარი edge; კლიენტის IP — `X-Forwarded-For`-ის მარჯვენა hop, იხ. Decision Log 2026-10).
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

### 2026-10 — შეკვეთის სტატუსი + მარაგი ერთ DB ტრანზაქციაში (S11-1)
- Context: `update_order_status` სტატუსსა და მარაგს ცალ-ცალკე ცვლიდა; სტატუსის შეცვლის შემდეგ მარაგის დაბრუნების ჩავარდნა (`processing/done → cancelled`) მარაგს კარგავდა და 500-ს აბრუნებდა.
- Decision: RPC `public.change_order_status(order, shop, expected_old, new)` (migration 0021, SECURITY INVOKER, EXECUTE მხოლოდ service_role) — `FOR UPDATE` + სტატუსის შემოწმება + `decrement_stock`/`apply_stock_delta(+1)` + UPDATE ერთ ტრანზაქციაში. backend ჯერ ownership-ს `auth.client`-ით (RLS) ამოწმებს, RPC-ს service client-ით იძახებს RLS-ით დადასტურებული `shop_id`-თ. მარაგის წესი უცვლელია (იკლებს მხოლოდ new/cancelled → processing/done). შეცდომები: `INSUFFICIENT_STOCK|…`, `PRODUCT_NOT_FOUND`, `STATUS_CHANGED`, `ORDER_NOT_FOUND`.
- Run order: ჯერ 0021, მერე backend deploy (ძველი backend 0021-თან მუშაობს; ახალი 0021-ის გარეშე სტატუსის შეცვლაზე 500, მონაცემები უცვლელი).
- Alternatives considered: backend-ში კომპენსაცია/retry. Why rejected: შუალედური მდგომარეობა და ჩავარდნა მაინც რჩება; DB ტრანზაქცია მარტივია.

### 2026-10 — orders/knowledge UPDATE grants removed; writes only via backend (S11-5)
- Context: `authenticated`-ს რჩებოდა `orders` UPDATE(status) (0018), რაც RPC `change_order_status`-ს გვერდს უვლიდა (მარაგი), და `shops` UPDATE(knowledge, knowledge_filename) (0015), რაც free-gate-ს უვლიდა გვერდს.
- Decision: migration 0022 ორივეს აუქმებს; `upload_knowledge`/`clear_knowledge` ამიერიდან წერენ service client-ით `.eq("id", shop_id)`-ით, მფლობელობის `auth.client` (RLS) select-ით შემოწმების შემდეგ.
- Run order: ჯერ backend deploy, მერე 0022 (პირიქით knowledge upload/clear ჩავარდება).

### 2026-10 — Gemini timeout + retry ბიუჯეტი (S11-3)
- Context: `genai.Client` timeout-ის გარეშე იყო; ჩამოკიდებული მოთხოვნა webhook worker-ს იკავებდა და კლიენტი პასუხს ვერ იღებდა.
- Decision: ერთი მცდელობის timeout `GEMINI_TIMEOUT_SECONDS` (default 20; `HttpOptions.timeout` მილიწამებშია, ვამრავლებთ 1000-ზე), ყველა retry-ს ჯამი `GEMINI_TOTAL_BUDGET_SECONDS`=45 (monotonic deadline; მცდელობის timeout = min(timeout, დარჩენილი)). 503/429-ზე retry თუ დარჩენილი >= sleep + 5 წმ; timeout-ის შემდეგ retry მხოლოდ თუ დარჩენილი >= sleep + სრული timeout-ფანჯარა. ბოლო შეცდომა იგდება → webhook-ის „ბოდიში…" fallback.
- Alternatives considered: asyncio/thread-level მკაცრი ჭერი. Why rejected: SDK-ის timeout საკმარისია; დამატებითი სირთულე არ სჭირდება.

### 2026-10 — production fail-closed on missing secrets (S11-6)
- Context: ცარიელი `FB_APP_SECRET`-ით webhook-ის/signed_request-ის/OAuth state-ის HMAC ცარიელი გასაღებით ითვლებოდა (გაყალბებადი), data-deletion კოდი კი ჩაშენებულ `"chatassist"` გასაღებზე ეცემოდა; `FB_TOKEN_ENCRYPTION_KEY` გამოტოვება პირველ connect-ზე ვლინდებოდა.
- Decision: (1) `Settings.missing_required_secrets()` + `check_required_settings()` (`main.py`): `APP_ENV=production`-ზე ცარიელი/არავალიდური `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_SECRET_KEY`, `GEMINI_API_KEY`, `FB_APP_SECRET`, `FB_VERIFY_TOKEN`, `FB_TOKEN_ENCRYPTION_KEY` (Fernet-ის ფორმატიც) → `RuntimeError` სახელებით (მნიშვნელობების გარეშე), აპი არ ირთვება. (2) ყველა env-ში: `verify_signature` → False, `parse_signed_request` → None, `verify_state` → None, `sign_state`/`_deletion_secret` → RuntimeError (`"chatassist"` fallback წაშლილია); `/facebook/connect/start` და `/facebook/data-deletion` → 503, `verify_deletion_code` → None. Dev/ტესტები უცვლელია.
- Alternatives considered: მხოლოდ startup შემოწმება. Why rejected: dev/staging-ში ან `get_settings` ჩანაცვლებისას ფუნქცია მაინც ცარიელი გასაღებით მუშაობდა; ორივე დონე იაფია.

### 2026-10-09 — საიდუმლოების როტაცია გაჟონვის შემდეგ
- Done (მფლობელი, ლაივზე): Supabase → ახალი `sb_publishable_`/`sb_secret_` key-ები, legacy JWT key-ები გამორთულია (ძველი anon-ით REST → 401); `FB_APP_SECRET` შეცვლილია; `FB_TOKEN_ENCRYPTION_KEY` შეცვლილია — ძველით დაშიფრული page token-ები გამოუსადეგარი გახდა და Facebook/Instagram-მიბმული ერთადერთი მაღაზია ხელახლა დაუკავშირდა (ბოტი პასუხობს).
- Open: Gemini key-ის როტაცია (მფლობელი წყვეტს როდის).
- Note: `FB_TOKEN_ENCRYPTION_KEY`-ის შეცვლა ყველა ამ key-ით დაშიფრულ token-ს აუქმებს — მომავალში მაღაზიების რაოდენობის გაზრდისას ეს ხელახალი connect-ებს მოითხოვდა.

### 2026-10 — ბოტის ლიმიტი ერთ helper-ში; upgrade request მხოლოდ backend-ით, pending per-account (S12-2, S12-3)
- Decision: `services/bot_limits.enforce_bot_limit` — ჭერი = მფლობელის უმაღლესი პაკეტი; რჩება **ჩართული** ბოტებიდან ყველაზე ძველი `limit`. იძახება seller downgrade-free-ზე, ადმინის tier-ცვლაზე და upgrade-request approve-ზე (შემდეგ `_restore_bots`). შეცდომა → 500 (tier უკვე შეცვლილია, გამეორება იდემპოტენტურია). `upgrade_requests`-ზე `authenticated`-ს INSERT მოხსნილია (0024), ჩაწერა service client-ით RLS-ownership-ის შემდეგ + rate limit 10/სთ/IP. pending **per-account**: ახალი მოთხოვნა მფლობელის ყველა მაღაზიის ძველ pending-ს აუქმებს (გამოწერა per-account-ია; DB-ში მაღაზიაზე ერთი pending — partial unique).
- Reason: webhook მხოლოდ `bot_enabled`-ს ამოწმებს, ამიტომ `subscription_tier`-ის შეცვლა ჭერს ვერ იცავდა; პირდაპირი PostgREST INSERT ბაზას/ადმინის სიას უსაზღვროდ ავსებდა.

### 2026-10 — სურათის ჩამოტვირთვა: მთლიანი deadline + მხოლოდ საკუთარი Storage (S12-1, B-12)
- Decision: `download_image` 15 წმ-იანი მთლიანი ზღვარი (`time.monotonic`); ბოტი საცნობარო ფოტოს მხოლოდ `<SUPABASE_URL>/storage/v1/object/public/product-images/` ბილიკიდან იღებს (UI-დან ფოტო მხოლოდ ატვირთვით მოდის; პირდაპირი PostgREST `image_url` გარე URL-ს ბოტი უგულებელყოფს). კლიენტის FB/IG CDN ფოტოები უცვლელია.
- Reason: httpx timeout ფაზაზეა → slow-drip სერვერი thread-ს წუთობით იკავებდა (threadpool-ის ამოწურვა); გარე URL ამავდროულად SSRF-ის ზედაპირი იყო.

### 2026-10 — `CLIENT_IP_TRUSTED_HOPS` production-ში სავალდებულოა (S12-4)
- Decision: default აღარ არის (`None`); production-ში ცარიელი/<1 → startup `RuntimeError` (როგორც სხვა secrets). dev/test-ში 1.
- Reason: დაკარგული env ჩუმად ყველა მყიდველს ერთ IP-bucket-ში აგდებდა.

## Accepted Risks
<!-- მიღებული რისკები: რა, რატომ მისაღებია, გადახედვის პირობა. ივსება მფლობელის გადაწყვეტილებით. -->
> 2026-10-09 — გარე აუდიტის (27 პუნქტი) პუნქტები, რომლებიც ახლანდელ კოდში არ დადასტურდა ან ამ მასშტაბისთვის ზედმეტია (მფლობელის მითითებით).

- **#1 webhook dedup — „message-ის დაკარგვა retry-ზე"** — ამ ფორმით არ შეესაბამება: webhook 200-ს **დამუშავებამდე** აბრუნებს (`receive_webhook` → BackgroundTasks), ამიტომ Meta Gemini-ს ჩავარდნაზე retry-ს არ აკეთებს; Gemini-ს შეცდომაზე კლიენტს fallback პასუხი მიდის. რეალური ნარჩენი — crash (#6) და Send API-ს ჩავარდნა (Backlog). გადახედვა: queue-ზე გადასვლისას.
- **#3, #4 product/shop ლიმიტის race (COUNT → INSERT)** — პარალელური POST-ით გამყიდველი საკუთარ ლიმიტს 1–2-ით გადააჭარბებს; უსაფრთხოებას/სხვა tenant-ს არ ეხება (Backlog A-10). გადახედვა: თუ ბილინგი ავტომატური გახდება.
- **#5 `POST /orders` idempotency** — ღილაკი გაგზავნისას ითიშება (`OrderPage.jsx`), ერთ ტელეფონზე მაქს. 3 ღია შეკვეთა, B-1-ის შემდეგ `new` მარაგს არ ეხება; დუბლიკატს გამყიდველი ხედავს და აუქმებს. გადახედვა: ონლაინ გადახდის დამატებისას (მაშინ სავალდებულოა).
- **#6 BackgroundTasks durable queue-ის გარეშე** — crash/OOM-ზე მიმდინარე შეტყობინება იკარგება (კლიენტი პასუხს ვერ იღებს). ერთი instance, დაბალი მოცულობა; Decision Log 2026-08; ROADMAP 🏗 Redis/queue. გადახედვა: >1 instance ან ხშირი restart-ები.
- **#9 rate limiter process-memory-ში** — Decision Log 2026-08: ერთი Render instance; restart-ზე ნულდება. გადახედვა: >1 instance.
- **#11 CORS `*` production-ში მხოლოდ warning** — ავთენტიკაცია Bearer token-ითაა (არა cookie-თი; `*`-ზე `allow_credentials` გამორთულია), ამიტომ wildcard სხვა საიტს მომხმარებლის სახელით მოქმედების საშუალებას არ აძლევს; fail-closed env-ის გამორჩენისას production-ს ჩამოაგდებდა. მფლობელის ქმედება: Render-ზე `CORS_ORIGINS=https://chatassist.ge`.
- **#12 `/public-menu` ზუსტ მარაგს აბრუნებს** — პროდუქტის ფუნქციაა (`OrderPage` აჩვენებს „მარაგში: N" და ზღუდავს რაოდენობას); ბოტიც მარაგს ამბობს. გადახედვა: თუ გამყიდველები მოითხოვენ „არის/ცოტაა" რეჟიმს.
- **#13 ფული float-ით** — ფასები 2 ათწილადიანია, რაოდენობა მთელი, ჯამი `round(…, 2)`; float-ის შეცდომა ~1e-13-ია და ნახევარ თეთრს ვერ აღწევს, ამიტომ თეთრამდე შედეგი სწორია; DB-ში `numeric`. გადახედვა: ფასდაკლება/პროცენტები/გადასახადი ან ონლაინ გადახდა → Decimal.
- **#14 bulk import სრულ ტრანზაქციაში არ არის** — import upsert-ია (SKU/სახელით), ამიტომ ნაწილობრივი შედეგის შემდეგ იგივე ფაილის ხელახალი ატვირთვა მდგომარეობას ასწორებს; შეცდომიანი ფაილი საერთოდ არ იწერება.
- **#16 admin endpoints ყველაფერს მეხსიერებაში კითხულობს** — ათეულობით მაღაზია (Realistic Scale); ROADMAP: admin pagination. გადახედვა: ათასობით შეკვეთა.
- **#18 subscription ლიმიტები მხოლოდ application layer-ში** — გამყიდველს ლიმიტიან ცხრილებზე DB-ში პირდაპირი ჩაწერა არ შეუძლია (0015: products INSERT, shops-ის tier/bot სვეტები ჩამორთმეულია; 0017–0019), ამიტომ backend ერთადერთი ჩამწერია (`knowledge` — 0022, `upgrade_requests` — 0024).
- **#19 PII retention/deletion policy** — არსებობს: privacy.html §6 (ანგარიში — აქტიურობის განმავლობაში, მოთხოვნისას 30 დღეში; საუბრები — ბოლო N შეტყობინება; შეკვეთები — სანამ გამყიდველი/მაღაზია არ წაშლის) და კოდი ემთხვევა (shop-ზე `on delete cascade` ყველა ცხრილზე, admin delete + Storage cleanup, Meta Data Deletion callback + `delete-data.html`). Meta App Review-ს callback ან ინსტრუქციის URL სჭირდება — ორივე არის. გადახედვა: ავტომატური ვადიანი წაშლის საჭიროება ან კანონის ცვლილება.
- **#20 Gemini prompt-ში user/seller content** — კლიენტის ტექსტი ცალკე `user` turn-შია და არა system instruction-ში; system-ში მხოლოდ გამყიდველის საკუთარი მონაცემია (მხოლოდ საკუთარ ბოტს აზიანებს); ბოტს ქმედებები (tools) არ აქვს — მხოლოდ ტექსტი. PDF-ცოდნის ამოღება — Backlog B-14.
- **#22 Gemini output structured schema-ს გარეშე** — პასუხი Messenger-ის თავისუფალი ტექსტია; ერთადერთი სტრუქტურა `[[HANDOFF]]` ნიშანია და `parse_reply` მას ამოწმებს; ცარიელ პასუხზე fallback + handoff (FA-12).
- **#25 CSP header** — ROADMAP-შია (out of scope); frontend React-ია (escape-ით), user HTML არ რენდერდება. გადახედვა: მესამე მხარის script-ების დამატებისას.

> 2026-10-09 — მესამე აუდიტი (Stage 12), მფლობელის გადაწყვეტილებით.
- **admin kill-switch-ს გამყიდველი FB-ის ხელახალი connect-ით აუქმებს** (`api/facebook.py` — `bot_enabled = bot_allowed` მხოლოდ პაკეტის ლიმიტს ამოწმებს; `_restore_bots`-იც იგივეს აკეთებს). ახლა ათეულობით გამყიდველია, ბოროტმოსარგებლეს ადმინი მაღაზიის წაშლითაც აჩერებს. გადახედვა: **პირველ რეალურ abuse-ზე** (მაშინ სვეტი `admin_blocked` + შემოწმება connect/webhook/restore-ში).
- **`SHOP_ORDERS_PER_HOUR=30` მაღაზიაზე საერთოა** (`orders.py`): ორი IP-დან (10/წთ, 20/დღე თითოზე) ~3 წუთში 30 ყალბი შეკვეთა მაღაზიის ფორმას საათით ბლოკავს. შეგნებული trade-off: მაღაზიის შეკვეთების spam-დან დაცვა (F-03B) უფრო მნიშვნელოვანია, ვიდრე ერთი საათის დაბლოკვა; გამყიდველი არსებულ შეკვეთებს ხედავს. გადახედვა: პირველ საჩივარზე.
- **`get_current_auth` ყოველ მოთხოვნაზე ახალ Supabase client-ს ქმნის** (დახურვის გარეშე): ამ მასშტაბზე (ერთი instance, ათეულობით გამყიდველი) პრობლემა არ ჩანს. გადახედვა: Render-ის მეხსიერების გრაფიკის ზრდა ან მოთხოვნების რაოდენობის ზრდა.

## Open Questions
- README §6/§12 მოძველებულია (React 18 → 19). ADMIN_EMAIL, „ტესტები არ არის“ და მიგრაციების სია გასწორდა S12-5-ში — დარჩენილი განახლდეს?
- Gemini 2.5 Flash retires 2026-10-16 — გადაწყვეტილება გადადებულია (Backlog T12, Decision Log 2026-10); საგანგებო გეგმა Deploy plan-შია.
