# ChatAssist

> ეს ფაილი პროექტის **მოთხოვნებს, წესებს და გადაწყვეტილებებს** აჯამებს. დეტალები არ
> მეორდება — მითითებულია არსებულ დოკუმენტებზე. მიმდინარე task-ები: `PROGRESS.md`.

## Overview
Multi-tenant SaaS ქართული მაღაზიებისთვის: გამყიდველი რეგისტრირდება, ტვირთავს მარაგს და
აკავშირებს Facebook გვერდს; Messenger/Instagram-ში მისულ კლიენტს AI ბოტი პასუხობს
(production-ში ჯერ Gemini; **planned replacement (Stage 14):** Claude Haiku 5.5 default / OpenAI, `LLM_PROVIDER`-ით) **მხოლოდ ამ მაღაზიის რეალურ მარაგზე** დაყრდნობით, ფოტოს ცნობს, აძლევს შესაკვეთ
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
**Stage 15 — ბრმა შედარება: Claude vs OpenAI (სკრიპტი იწერება, არ ეშვება)**
(იხ. `PROGRESS.md`; Stage 10–14 დასრულებულია, Stage 14 — offline, deploy key-ებს ელოდება). Stage 16–18 (LangGraph, PDF-ცოდნა, ფოტოები) — `PROGRESS.md` `## Upcoming stages`.
სამუშაო მხოლოდ `agent-system`-ზე; `main`-ში merge არ იგეგმება, სანამ API key-ები არ იქნება.

## Scope
### In scope (current stage — Stage 15)
- `llm.generate`-ში provider-ის override (`provider=`), default ქცევა უცვლელი
- `backend/scripts/compare_providers.py`: 40 ქართული შეკითხვა ფიქტიურ მაღაზიაზე × 2 provider, იგივე `prompt` + `llm` გზით; `compare_output.md` (A/B, provider-ის სახელების გარეშე, ტოკენები/ფასი თითო პასუხზე) + `compare_key.json` (გასაღები) — ორივე gitignored
- სატესტო მონაცემი (`compare_questions.json`, `compare_assets/`), offline ტესტები fake client-ებით, README-ს ინსტრუქცია
- სკრიპტს **არავინ უშვებს, გარდა მფლობელისა** key-ების დამატების შემდეგ; შედეგის Decision Log (default provider, thinking/effort, output-ის ჭერი, 5m cache) — მფლობელი, გაშვების შემდეგ
### Out of scope (for now)
- Stage 15-ში: production-ის ქცევის ცვლილება (prompt, webhook, default provider), Stage 14-ის Backlog nit-ები, LangGraph/tools, PDF-ის შეკუმშვა, ფოტოს აღწერა (Stage 16–18)
- ახალი ფიჩერები — [ROADMAP.md](ROADMAP.md) (Instagram Live, web widget, ინტეგრაციები,
  ავტომატური billing, Redis/queue, CSP, admin pagination)

## Core Flows
1. რეგისტრაცია → მაღაზია → პროდუქტები (ხელით / Excel / CSV) → PDF-ცოდნა.
2. Facebook OAuth connect → page token (დაშიფრული) → webhook subscribe.
3. Meta webhook (`POST /webhook`, ხელმოწერით) → page_id → მაღაზია → ლიმიტები →
   LLM (ახლა Gemini; Stage 14-დან Claude/OpenAI; key-ის გარეშე — ოპერატორის პასუხი) → Send API პასუხი (background task).
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
(სია: [README.md](README.md) §7). Stage 14: `0025_llm_usage.sql` (დაგეგმილი; `llm_usage` — მხოლოდ service_role).
- `shops` (owner_id → auth.users) 1—N `products`, `orders`, `bot_customers`,
  `bot_conversations`, `upgrade_requests`
- `orders.items` — JSON პოზიციები; ფული — numeric
- Storage: product images bucket (საჯარო, per-shop folder)

## Integrations
- **Meta Graph API** (`v21.0`) — OAuth, Send API, webhook, Instagram Messaging.
  Setup: [README.md](README.md) §10, [INSTAGRAM_SETUP.md](INSTAGRAM_SETUP.md),
  [APP_REVIEW_TEXTS.md](APP_REVIEW_TEXTS.md)
- **Google Gemini** (`gemini-2.5-flash`) — ბოტის პასუხი, multimodal. **Planned replacement (Stage 14):**
  **Anthropic Claude** (`claude-haiku-5-5`, SDK `anthropic`, default) ან **OpenAI** (`gpt-6-luna`, SDK `openai`) —
  `LLM_PROVIDER=claude|openai`; Gemini სრულად იშლება (Decision Log 2026-10-28).
- **Supabase** — DB, Auth, Storage.
- **Render** — hosting, TLS; კლიენტის IP `X-Forwarded-For`-ის მარჯვენა hop-იდან (T17). Cloudflare ამჟამად არ გამოიყენება (origin-lock კოდში ოფციაა, `ORIGIN_SECRET` ცარიელია).

## Stack & Architecture
- Complexity tier: მცირე SaaS, ერთი backend instance (modular monolith)
- Frontend: React 19 + Vite **MPA** (8 გვერდი); `frontend/dist/` git-შია
- Backend: FastAPI (Python 3.14), sync handlers + FastAPI BackgroundTasks
- LLM: Gemini (`google-genai`) → planned replacement (Stage 14): `anthropic` / `openai` SDK, `services/prompt.py` +
  `services/llm.py`; LangGraph — მხოლოდ Stage 16-ში
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
  Gemini / Anthropic / OpenAI რეალური key-ით, deploy, `.env`-ის წაკითხვა/შეცვლა.
- ტესტები მხოლოდ ლოკალურად და იზოლირებულად (fake Supabase, mock Graph / LLM client-ები).
- მიგრაციებს მფლობელი უშვებს ხელით (Supabase SQL Editor).
- Render-ზე Node არ არის → frontend build ლოკალურად, `dist/` commit-ში.
- Gemini — free tier (5 req/min) — Stage 14-ის deploy-მდე. Stage 14-ის შემდეგ: Anthropic-ის billing/spend limit
  (Claude Haiku 5.5: $0.10 / $0.50 per MTok ≤100K-ტოკენიან request-ზე, >100K — $0.50 / $2.50 → prompt 100K-ს არასდროს უახლოვდება).
- Meta-ს ანგარიშის რისკი — ალტერნატიული არხები ROADMAP-შია.
- ბიუჯეტი ~35₾/თვე ([DEPLOYMENT.md](DEPLOYMENT.md)). ენა/რეგიონი — საქართველო, UI ქართულად.

## API Contract
სრული სია (47 endpoint): [README.md](README.md) §6 — ეს ერთადერთი წყაროა; აქ მხოლოდ საერთო წესები და Stage 14-ის ცვლილებები.
- **შეცდომის საერთო ფორმატი:** FastAPI-ის `{"detail": "<ქართული ტექსტი>"}` (422-ზე — FastAPI-ის ვალიდაციის `detail` სია);
  production-ში მოულოდნელი შეცდომა → 500 `{"detail": "სერვერის შიდა შეცდომა"}`; 413 → `{"detail": "მოთხოვნა ძალიან დიდია"}`.
- **`POST /webhook`** (Meta) — უცვლელი: ხელმოწერა → 200 `{"status": "ok" | "ignored"}` დამუშავებამდე; 403 არასწორ ხელმოწერაზე;
  400 არავალიდურ JSON-ზე. Stage 14: key-ის გარეშე კლიენტი იღებს ოპერატორის პასუხს და საუბარი `needs_attention`-ად ინიშნება.
- **`POST /test-chat`** (dev only; production → 404) — request `{shop_id: uuid, message: str (min 1), history: [{role: "user"|"bot", content: str}]}`;
  response 200 `{reply: str, products_in_context: int, model: str}`. Stage 14: `model` = არჩეული provider-ის მოდელი
  (`CLAUDE_MODEL` / `OPENAI_MODEL`); არჩეული provider-ის key არ არის → **503** `{"detail": "<ENV_NAME> არ არის კონფიგურირებული"}`;
  provider-ის შეცდომა → 502; მაღაზია ვერ მოიძებნა → 404; rate limit (15/წთ) → 429.

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
- Status: **superseded → 2026-10-28** (Stage 14: Claude / OpenAI).

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
- Status: **superseded → 2026-10-28** (SDK-ის `timeout` + `max_retries=1`; იგივე გარანტიები ახალი ტესტებით).

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
- Decision: `download_image` 15 წმ-იანი ზღვარი body-ს კითხვასა და redirect-ებზე (`time.monotonic`; connect/header ფაზას httpx-ის timeout ზღუდავს); ბოტი საცნობარო ფოტოს მხოლოდ `<SUPABASE_URL>/storage/v1/object/public/product-images/` ბილიკიდან იღებს (UI-დან ფოტო მხოლოდ ატვირთვით მოდის; პირდაპირი PostgREST `image_url` გარე URL-ს ბოტი უგულებელყოფს). კლიენტის FB/IG CDN ფოტოები უცვლელია.
- Reason: httpx timeout ფაზაზეა → slow-drip სერვერი thread-ს წუთობით იკავებდა (threadpool-ის ამოწურვა); გარე URL ამავდროულად SSRF-ის ზედაპირი იყო.

### 2026-10 — `CLIENT_IP_TRUSTED_HOPS` production-ში სავალდებულოა (S12-4)
- Decision: default აღარ არის (`None`); production-ში ცარიელი/<1 → startup `RuntimeError` (როგორც სხვა secrets). dev/test-ში 1.
- Reason: დაკარგული env ჩუმად ყველა მყიდველს ერთ IP-bucket-ში აგდებდა.

### 2026-10-27 — Frontend: ESLint 9 + Vitest, voltbox-ის ნიმუშით (Stage 13)
- Decision: ESLint 9 flat config (`frontend/eslint.config.js`): `@eslint/js` recommended + `eslint-plugin-react` recommended + `eslint-plugin-react-hooks` **5.x** recommended + `eslint-plugin-react-refresh` (`only-export-components` → warn); `react/react-in-jsx-scope`, `react/jsx-uses-react`, `react/prop-types` → off; `no-unused-vars` `_`-ით და `ignoreRestSiblings`. voltbox-ის `no-console: error` **არ** გადმოგვაქვს (აქ `console.error` ზოგან განზრახაა). Vitest — `vite.config.js`-ის `test` ბლოკში (jsdom, `vitest.setup.js`: jest-dom + cleanup), `include: src/**/*.test.{js,jsx}`; `npm test` = `vitest run`. ვერსიები — voltbox-ის ხაზის თანადროული (eslint 9.39.x, vitest 5.x, jsdom 30.x, @testing-library/react 16.x).
- Reason: მფლობელის მოთხოვნა (voltbox-ის მსგავსად) + AUDIT A-016 (frontend ტესტი CI-ში არ ეშვებოდა). react-hooks 7.x React Compiler-ის წესებს (`set-state-in-effect`, `refs`, `purity`…) ამატებს — არსებულ კოდზე მათი გასწორება ქცევას ცვლის, რაც ამ stage-ში აკრძალულია; 5.x მხოლოდ `rules-of-hooks` (error) + `exhaustive-deps` (warn)-ია. ცალკე `vitest.config.js`-ის ნაცვლად `test` ბლოკი — ერთი კონფიგი, build-ის გამოსავალს არ ცვლის.
- ვარაუდი (/auto): ESLint-ის **error**, რომლის გასწორებაც ქცევას შეცვლის, არ სწორდება — ის ხაზი იღებს `// eslint-disable-next-line <rule> -- <მიზეზი>, Backlog S13` კომენტარს და Backlog-ში ცალკე ჩანაწერს. წესის სიმკაცრე config-ში არ მცირდება (ახალ კოდზე სრულად მოქმედებს). `exhaustive-deps`-ის warning-ები არ სწორდება (deps-ის დამატება ქცევის ცვლილებაა) → Backlog.
- ვარაუდი (/auto): `/auto`-ს ფაზა 1ბ (DESIGN.md + Playwright setup) ამ stage-ში გამოტოვებულია — stage UI-ს/ვიზუალს არ ცვლის, მხოლოდ tooling-ია; ვიზუალის უცვლელობა მოწმდება `npm run build`-ით და `dist/`-ის diff-ის გადახედვით (ESLint-ის გასწორებისას). შეიცვლება: მფლობელს Playwright-ის smoke ტესტი სურს → ცალკე task მომდევნო stage-ში.
- CI: frontend job — `npm ci` → `npm audit --omit=dev` → `npm run lint` → `npm test` → build → `dist` diff. სრული `npm audit` (dev-ის ჩათვლით) CI-ში არ არის (A-014: dev-dependency-ების high-ები production bundle-ში არ ხვდება).

### 2026-10-28 — Gemini სრულად იცვლება: Claude (default) / OpenAI, პირდაპირი SDK-ებით; ეტაპები 14–18
- Decision: Gemini-ს კოდი, `google-genai` და `GEMINI_*` ცვლადები სრულად იშლება (Stage 14). provider — `LLM_PROVIDER=claude|openai` (default `claude`); SDK-ები `anthropic` (`client.messages.create`) და `openai` — **არა** Claude Agent SDK. მოდელები env-ით: `CLAUDE_MODEL=claude-haiku-5-5`, `OPENAI_MODEL=gpt-6-luna`. ეტაპები (მფლობელის A–E): **14** — provider + სამფენიანი prompt + `llm_usage`; **15** — ბრმა შედარების სკრიპტი (იწერება, არ ეშვება); **16** — LangGraph გრაფი (preprocess → agent+tools → postprocess); **17** — PDF-ცოდნის შეკუმშვა + ძებნა; **18** — ფოტოს ტექსტური აღწერა. LangGraph Stage 14-ში **არ** შემოდის.
- Reason: მფლობელის მოთხოვნა (ტოკენების მინიმიზაცია, LangGraph). ბოტს რეალური კლიენტები ჯერ არ ჰყავს → თანდათანობითი მიგრაცია / feature flag / Gemini-ს მესამე provider-ად დატოვება არ სჭირდება. `gemini-2.5-flash`-ის გათიშვის თარიღი (2026-10-16) უკვე გავიდა.
- Alternatives considered: Gemini მესამე provider-ად; LangChain-ის chat model wrapper-ები; Claude Agent SDK.
- Why rejected: მკვდარი კოდი და ტესტები; wrapper-ები `cache_control`-ის ბლოკების და ბაიტ-იდენტური prefix-ის ზუსტ კონტროლს ართულებს; Agent SDK agent loop-ია (ფაილები/shell), ჩატ-ბოტისთვის ზედმეტი.
- როგორ შეიცვლება: ახალი provider = ერთი ფუნქცია `services/llm.py`-ში + `Literal`-ის გაფართოება. Stage 15-ის შედეგით default provider შეიძლება შეიცვალოს (მხოლოდ env).

### 2026-10-28 — Prompt სამ ფენად, cache-ის წერტილებით (Stage 14)
- Context: `build_system_prompt` ერთ ქართულ system prompt-ში აერთიანებდა წესებს, მაღაზიას და მარაგს, ხოლო >30 პროდუქტზე მარაგი ყოველ შეტყობინებაზე სხვანაირად იფილტრებოდა (`select_relevant_products`, `RETRIEVE_LIMIT=30`) → prefix ყოველთვის იცვლებოდა და cache შეუძლებელი იყო. webhook-ის `products` query `.order()`-ის გარეშეა → რიგი არადეტერმინისტულია.
- Decision:
  - **ფენა 1** (`prompt.LAYER1`, კონსტანტა, ინგლისურად, ყველა მაღაზიისთვის ერთი): ბოტის წესები (ახლანდელი 1–11-ის შინაარსი), ქართული ფრაზების მაგალითები და few-shot — ციტირებული ქართული ტექსტით (მაღაზიისგან დამოუკიდებელია). **არ** შეიცავს: მაღაზიის სახელს, ვალუტის მნიშვნელობას, შესაკვეთ ბმულს, ენის წესს, თარიღს — წესები მიუთითებს „ქვემოთ მოცემულ shop block-ზე". ≥512 ტოკენი (Claude-ის მინიმუმი; უფრო მოკლე ჩუმად არ იქეშება) — offline შემოწმება სიმბოლოებით (≥2600). Claude: `cache_control {"type":"ephemeral","ttl":"1h"}`.
  - **ფენა 2** (`prompt.build_layer2(shop, products)`, დეტერმინისტული): სახელი, აღწერა, ვალუტა, ენის წესი (`bot_language`), შესაკვეთი ბმული, ცოდნა (PDF-ის ტექსტი, 20000 სიმბოლომდე — Stage 17-მდე), და **სრული მარაგი** `id`-ით დალაგებული, როცა პროდუქტი ≤ `RETRIEVE_LIMIT`; მეტზე — მხოლოდ შენიშვნა („relevant products are listed inside each customer message"). არ არის დამოკიდებული შეტყობინებაზე/ისტორიაზე/დროზე. Claude: `ttl 5m`. იცვლება მხოლოდ მაღაზიის მონაცემის/მარაგის ცვლილებისას (cache miss მისაღებია).
  - **ფენა 3** (messages): ნორმალიზებული ისტორია + ბოლო user turn: (>30 პროდუქტზე) ამ შეტყობინების რელევანტური პროდუქტები → კლიენტის ფოტოები → საცნობარო ფოტოები → კლიენტის ტექსტი. Claude: top-level `cache_control={"type":"ephemeral"}` (automatic caching ბოლო ბლოკზე, 5m; 1h → 5m → automatic რიგი დასაშვებია; 3 breakpoint 4-დან).
  - Claude request: `system=[{L1, 1h}, {L2, 5m}]`, `messages=[ისტორია…, ბოლო user]`. **OpenAI:** იგივე რიგი — L1 და L2 ერთ წამყვან `developer` შეტყობინებაში (ორი `input_text` ნაწილი), მერე ისტორია, მერე ბოლო turn; `prompt_cache_key="shop:<shop_id>"`. OpenAI cache-ავს მხოლოდ ≥1024-ტოკენიან prefix-ს — L1+L2 ჩვეულებრივ აღემატება; პატარა მაღაზიაზე შეიძლება არ დაიქეშოს (მისაღებია).
  - ისტორიის ნორმალიზაცია: `user/bot` → `user/assistant`; ცარიელი ტექსტი იშლება; ერთი როლის თანმიმდევრული turn-ები ერთდება `\n\n`-ით; წამყვანი assistant turn-ები იშლება; ბოლო ყოველთვის user. DB-ში ისტორიის ფორმატი **არ იცვლება** (კლიენტის ნედლი ტექსტი, პროდუქტების ჩანართის გარეშე) → წინა turn-ები ბაიტ-იდენტურია და tail cache მუშაობს.
  - L2/L3-ის დამხმარე წარწერები (მარაგის ხაზის ფორმატი: „in stock: N" / „out of stock" / „price on request", სათაურები) ინგლისურად; მაღაზიის მონაცემი — როგორც არის. ენის წესები (`auto/ka/en/ru`) ინგლისურად, ცხადი ინსტრუქციით („reply in natural conversational Georgian…").
- Reason: Claude-ის cache = ზუსტი prefix (რიგი tools → system → messages; ნებისმიერი ბაიტის ცვლილება ყველაფერს მის შემდეგ აუქმებს; cache workspace-ზეა). ფენა 1 ყველა მაღაზიისთვის საერთოა (ერთი 1h ჩანაწერი), ფენა 2 — მაღაზიის, ფენა 3 — საუბრის. მფლობელის მოთხოვნა: საერთო წესები ინგლისურად.
- Trade-off: დაბალ ტრაფიკზე 5m-იანი write (1.25×) შეიძლება წაკითხვის დანაზოგს აღემატებოდეს (შეტყობინებებს შორის >5 წთ) — Stage 15-ში `llm_usage`-ის რეალური მონაცემით გადაიხედება. ინგლისური წესები ქართული პასუხის ხარისხზე — Stage 15-ის შედარება.
- **შესწორება (finish-check SF-1, ორკესტრატორი, 2026-10-28):** ფენა 3-ზე Claude-ის top-level automatic caching **იცვლება explicit breakpoint-ით ისტორიის ბოლო შეტყობინებაზე** (S14-10). მიზეზი: automatic breakpoint ბოლო user turn-ის ბოლოს იწერება, ის კი შეიცავს ამ შეტყობინების რელევანტურ პროდუქტებს (>30) და ფოტოებს, რომლებიც ისტორიაში არ ინახება → შემდეგ turn-ზე prefix იშლება და write (1.25×) არასდროს იკითხება (Anthropic-ის docs ამას „pure surcharge"-ს უწოდებს). explicit breakpoint ისტორიაზე იგივე მიზანს (საუბრის cache) ასრულებს: turn N+1 კითხულობს turn N-ის ჩანაწერს (lookback), ცვალებადი ბოლო turn არასდროს იწერება. მფლობელის ფორმულირებიდან („ავტომატური caching") გადახვევაა — **გადასახედი**; დაბრუნება: top-level `cache_control` + ბოლო turn-ის შენახვა ისტორიაში იმავე ფორმით (მეტი token ისტორიაში). ზემოთ „წინა turn-ები ბაიტ-იდენტურია და tail cache მუშაობს" — მართალი იყო მხოლოდ ≤30 პროდუქტის ტექსტურ turn-ებზე.
- Trade-off (ორკესტრატორი): ისტორია მოცურავე ფანჯარაა (`bot_memory_messages=20`, `webhook.py` `[-N:]`) → როცა საუბარი ფანჯარას ავსებს, ყოველ turn-ზე უძველესი შეტყობინება ამოვარდება, ფენა 3-ის prefix იცვლება და automatic cache მხოლოდ write-ს (1.25×) იხდის, read-ის გარეშე. მოკლე საუბრებზე (≤10 გაცვლა — Messenger-ის ტიპური შემთხვევა) cache მუშაობს; Stage 14-ში ეს მისაღებია და `llm_usage`-ით გაიზომება. Stage 16-ში („ბოლო 8 + შეჯამება") ფანჯარა **ბლოკებად** უნდა იჭრებოდეს (მაგ. 16-ზე → ბოლო 8 + განახლებული summary), რომ prefix ჭრებს შორის სტაბილური დარჩეს.
- Alternatives considered: ერთი system prompt cache-ის გარეშე (ახლანდელი); სრული მარაგი ყოველთვის L2-ში (დიდ მარაგზე prompt იბერება); retrieval L2-ში (cache ყოველ შეტყობინებაზე ირღვევა).
- როგორ შეიცვლება: Stage 16-ში tools ემატება — tool definitions prefix-ის ნაწილია (tools → system), ამიტომ ისინი სტატიკური და მაღაზიისგან დამოუკიდებელი უნდა იყოს (deploy-ზე ერთჯერადი cache miss).

### 2026-10-28 — prompt-ის ზომის ჭერი `MAX_PROMPT_CHARS = 50_000` (არქიტექტორის დამატება, Stage 14)
- Context: Claude Haiku 5.5-ის ფასი ხუთჯერ იზრდება, თუ request >100K ტოკენია (მთლიანი request). ახლანდელი clip-ებით ყველაზე უარესი შემთხვევა: L1 ~4K + აღწერა 1K + ცოდნა 20K + 30 პროდუქტი × ~0.96K ≈ 54K სიმბოლო + ისტორია (20 შეტყობინება × ≤~2K) ≈ 40K → ~95K სიმბოლო; ქართულზე ტოკენი/სიმბოლო თანაფარდობა დაუდასტურებელია (პესიმისტურად ~1) + 15-მდე სურათი (~1.6K ტოკენი თითო, ≈24K).
- Decision: `prompt.build_prompt` ჯამურ ტექსტს (L1+L2+ისტორია+ბოლო turn) ზღუდავს 50 000 სიმბოლოთი — ზედმეტისას ისტორიას ძველიდან აჭრის (L1/L2/ბოლო turn ხელუხლებელია, ისტორია user-ით იწყება). პესიმისტური ჯამი ≈ 50K + 24K ≈ 74K < 100K. ტესტი worst-case მონაცემით.
- როგორ შეიცვლება: Stage 15-ის რეალური `input_tokens`-ით ზღვარი დაზუსტდება; Stage 16 (8 შეტყობინება + summary), 17 (FAQ) და 18 (2–3 საცნობარო ფოტო) ზომას ამცირებს.
- **შესწორება (S14-3, ორკესტრატორი): `MAX_PROMPT_CHARS = 60_000`.** S14-3-მა დაითვალა: L1 = 4 382 სიმბოლო, უარესი L2 (≤30 პროდუქტი, ცოდნა 20K) = 49 730 → L1+L2 ≈ 54K > 50K, ანუ 50K-იანი ჭერი ამ შემთხვევაში ვერ სრულდებოდა (L1/L2/final ხელუხლებელია), >30 პროდუქტზე (30 რელევანტური `final`-ში) ≈ 56K. 60K-ზე ინვარიანტი `ჯამი ≤ MAX` ორივე უარეს შემთხვევაში მოქმედებს (ტესტით). პესიმისტური ჯამი ≈ 60K + ~24K (სურათები) ≈ 84K < 100K. Alternatives: ცოდნის clip 20K → 15K (Stage 17 მას მაინც ცვლის — ახლა შეცვლა გამყიდველის ცოდნას ჩამოჭრიდა); ჭერის ცხადი დარღვევა დოკუმენტაციით. Reason: უმარტივესი ცვლილება, ქცევა არ იცვლება.

### 2026-10-28 — მოდულები: `services/prompt.py` + `services/llm.py`; ორი provider = ორი ფუნქცია
- Decision: `prompt.py` — ფენები, ისტორიის ნორმალიზაცია, retrieval (`select_relevant_products`, `RETRIEVE_LIMIT`, `order_link_for` გადმოდის `bot.py`-დან), provider-ნეიტრალური `Prompt` dataclass (`layer1`, `layer2`, `history`, `final` ნაწილები: text / image bytes+mime); სუფთა, offline. `llm.py` — `build_claude_request` / `build_openai_request` (სუფთა), client factory-ები `_anthropic_client` / `_openai_client`, `generate(prompt, shop_id) -> LLMResult(text, provider, model, usage)`, usage-ის ნორმალიზაცია, `record_usage`. `bot.py` — `get_bot_reply` (**აბრუნებს `str`-ს, როგორც ახლა**), `parse_reply`/`HANDOFF_TOKEN`, საცნობარო ფოტოების ჩამოტვირთვა. abstract base class / registry / factory კლასი არ არის.
- Reason: სტანდარტი §27 (BaseProvider/Factory — მხოლოდ რეალური საჭიროებისას); `get_bot_reply`-ის სიგნატურის შენარჩუნება webhook-ს და `/test-chat`-ს და მათ ტესტებს ნაკლებად ცვლის.
- Deviation from brief: usage-ს წერს `get_bot_reply` (`llm.record_usage`, service client), არა webhook — ის მაინც webhook-ის background task-ში ეშვება. შედეგი: `/test-chat` (dev) usage-საც წერს — მისაღებია.

### 2026-10-28 — request-ის პარამეტრები: thinking გამორთული, sampling-ის გარეშე, 800 output; OpenAI — Responses API, `store=False`
- Claude: `thinking={"type":"disabled"}` (დაშვებულია effort ≤ high-ზე; default `medium`, effort-ს არ ვაგზავნით), `max_tokens=800`; `temperature`/`top_p`/`top_k` **არასდროს** (non-default → 400); prefill არა (messages user-ით იწყება და მთავრდება); პასუხის ტექსტი — მხოლოდ `type == "text"` ბლოკები; `stop_reason == "refusal"` → ცარიელი ტექსტი → არსებული FA-12 fallback + handoff (Haiku-ზე server-side fallback არ არის).
- OpenAI: `client.responses.create(model, input=[…], max_output_tokens=800, prompt_cache_key=…, store=False)`; sampling/reasoning პარამეტრები არ იგზავნება (gpt-6-luna-ს მხარდაჭერა დაუდასტურებელია — Open Questions). `store=False` — საუბარი OpenAI-ზე response ობიექტად არ ინახება (privacy). ტექსტი — `response.output_text`.
- Risk: OpenAI-ზე reasoning-ტოკენები output-ის ლიმიტში ითვლება → ცარიელი/მოჭრილი პასუხი შესაძლებელია (როგორც Gemini 3.5-ზე) → FA-12 fallback. პირველი რეალური გამოძახება — Stage 15-ის სკრიპტით.
- Alternatives considered: Chat Completions API. Why rejected: Responses — OpenAI-ის მიმდინარე API; თუ gpt-6-luna მას არ უჭერს მხარს, Stage 15-ში ერთი ფუნქცია იცვლება.
- როგორ შეიცვლება: thinking/effort და output-ის ჭერი — Stage 15-ის შედეგით.

### 2026-10-28 — timeout/retry: SDK-ის `timeout` + `max_retries=1`; custom retry loop იშლება
- Decision: ორივე client — `timeout=LLM_TIMEOUT_SECONDS` (default 20, `gt=0, le=20`), `max_retries=1`, `api_key=` ცხადად Settings-იდან (SDK სხვა credential წყაროს რომ არ მოძებნოს). worst case ≈ 20 (1-ლი მცდელობა) + backoff (SDK-ის პირველი retry ~0.5–1 წმ) + 20 (2-ე) ≈ **41 წმ**. SDK retry-ს აკეთებს 408/409/429/5xx/კავშირის შეცდომაზე; ბოლო შეცდომა ვრცელდება → webhook-ის „ბოდიში…" fallback (უცვლელი).
- `tests/test_gemini_timeout.py` იშლება Gemini-ს კოდთან ერთად — ეს არ არის „ტესტის წაშლა გასავლელად": იგივე გარანტიებს ფარავს ახალი ტესტები (client-ს გადაეცემა timeout/max_retries/api_key; `le=20` ვალიდაცია ჯამს ზღუდავს; შეცდომა → webhook fallback).
- Caveat: SDK შესაძლოა `retry-after` header-ს ითვალისწინებდეს (429-ზე დაყოვნება 41 წმ-ს გადააჭარბებს) — S14-4 ამოწმებს დაინსტალირებული SDK-ის კოდში, Open Questions. httpx-ის timeout ფაზაზეა (Backlog-ის ძველი nit რჩება).
- **Superseded (S14-1-ის მიგნება, ორკესტრატორი):** დადასტურდა SDK-ის კოდით — `anthropic 2.3.0` `retry-after`/`retry-after-ms`-ს **ზედა ზღვრის გარეშე** იცავს (`_base_client.py:881-930`; ჭერი მხოლოდ header-ის გარეშე backoff-ზეა, 8 წმ), `openai 3.40.0` — ≤120 წმ-მდე (`MAX_RETRY_AFTER_DELAY`). ე.ი. `max_retries=1` 429-ზე webhook-ის worker-ს წუთობით დაიჭერდა. **ახალი Decision:** ორივე client — `max_retries=0`; `llm.generate` თავად აკეთებს **მაქსიმუმ ერთ** retry-ს მხოლოდ დროებით შეცდომაზე (`APIConnectionError` — მათ შორის `APITimeoutError`, `RateLimitError`, `InternalServerError`/status ≥500, Anthropic-ის 529 overloaded), ფიქსირებული 1.5 წმ დაყოვნებით, `retry-after`-ს **არ** იცავს და retry-ს იწყებს მხოლოდ თუ `elapsed + 1.5 + LLM_TIMEOUT_SECONDS ≤ LLM_TOTAL_BUDGET_SECONDS (45)` (monotonic). worst case ≈ 20 + 1.5 + 20 = 41.5 წმ, ჭერი 45 წმ — გარანტირებულად, header-ისგან დამოუკიდებლად. 4xx (გარდა 429) — retry-ს გარეშე. Alternatives: SDK `max_retries=1` (ჭერი არ არის); retry საერთოდ არა (გადატვირთვის 529-ზე ზედმეტი fallback-ები). როგორ შეიცვლება: Stage 15-ის რეალური 429/529 სიხშირით.
- **SDK-ები `httpx2`/`httpcore2`-ზეა** (არა პროექტის `httpx`-ზე): ტესტებში SDK-ის HTTP ფენის mock — `httpx2.MockTransport`, ან (უმარტივესი, Stage 14-ის გეგმა) client factory-ის ჩანაცვლება fake client-ით. OpenAI `input_image`-ს `detail` სავალდებულოა → `"auto"`.

### 2026-10-28 — Settings/startup: key-ის გარეშე აპი ირთვება, ბოტი გამორთულია
- Decision: `llm_provider: Literal["claude","openai"] = "claude"` (before-validator: `strip().lower()`, ცარიელი → `claude`); **არავალიდური მნიშვნელობა → `ValidationError` startup-ზე ყველა გარემოში** (კონფიგურაციის შეცდომაა; Render წინა ვერსიას დატოვებს). `anthropic_api_key` / `openai_api_key` (`repr=False`), `claude_model`, `openai_model`, `llm_timeout_seconds`. properties: `llm_ready` (არჩეული provider-ის key არაცარიელია), `llm_model`, `llm_key_env_name`.
- `GEMINI_API_KEY` ამოდის `missing_required_secrets()`-იდან; provider-ის key **არ** ემატება. startup: `warn_if_llm_disabled(settings)` (`main.py`) — WARNING მხოლოდ ცვლადის სახელით, ყველა გარემოში. დანარჩენი secrets-ის fail-closed უცვლელია.
- `Settings.model_config` უკვე `extra="ignore"`-ია → Render-ზე დარჩენილი `GEMINI_*` startup-ს არ აგდებს (ტესტით).
- Alternatives considered: provider-ის key fail-closed სიაში. Why rejected: მფლობელის მოთხოვნა — key-ის გარეშე პანელი უნდა მუშაობდეს.

### 2026-10-28 — ბოტი key-ის გარეშე: over-limit-ის გზა (ოპერატორის პასუხი + `needs_attention`)
- Decision: webhook-ში, over-limit-ის შემოწმების **შემდეგ** (წუთობრივი ლიმიტი, `track_bot_customer`, `DAILY_ABUSE_CAP`, თვიური ლიმიტი — უცვლელი; კლიენტი ითვლება): `not settings.llm_ready` → იგივე განშტოება, რაც over-limit: არსებული ტექსტი „მადლობა შეტყობინებისთვის! 🙏 ჩვენი ოპერატორი მალე დაგიკავშირდებათ." (კონსტანტად გამოიტანება, ქცევა უცვლელი), `_save_turn(..., needs_attention=True)`; LLM და ფოტოების ჩამოტვირთვა არ ხდება; WARNING (shop id + ცვლადის სახელი, PSID-ის გარეშე). `/test-chat` → 503.
- spam: over-limit-ის მსგავსად ყოველ შეტყობინებაზე იგზავნება — ზღუდავს 6/წთ/PSID და `DAILY_ABUSE_CAP`; dedupe არ ემატება (გზა მხოლოდ კონფიგურაციის შეცდომისას მოქმედებს).
- Alternatives considered: პასუხის გარეშე (კლიენტი ჩუმად იკარგება — FA-12-ის საწინააღმდეგო); dedupe ბოლო bot შეტყობინებით (მეტი კოდი იშვიათი შემთხვევისთვის).

### 2026-10-28 — usage ცხრილი `public.llm_usage` (migration 0025)
- Schema: `id uuid pk default gen_random_uuid()` (როგორც სხვა ცხრილებში), `shop_id uuid not null references public.shops(id) on delete cascade`, `provider text not null check (provider in ('claude','openai'))`, `model text not null`, `input_tokens` / `output_tokens` / `cache_read_tokens` / `cache_write_tokens integer not null default 0 check (>= 0)`, `created_at timestamptz not null default now()`; index `(shop_id, created_at)`. RLS ჩართული, **პოლისების გარეშე**; `revoke all … from public, anon, authenticated`; `grant select, insert … to service_role`. idempotent (`if not exists`).
- სემანტიკა: `input_tokens` = **cache-ის გარეშე** შესული (Claude: `usage.input_tokens`; OpenAI: `input_tokens − cached_tokens`); `cache_read_tokens` (Claude: `cache_read_input_tokens`; OpenAI: `input_tokens_details.cached_tokens`); `cache_write_tokens` (Claude: `cache_creation_input_tokens` = 5m+1h ჯამი; OpenAI: ~~0~~ → **`input_tokens_details.cache_write_tokens`**, S14-12; OpenAI-ის uncached = `input − cached − cache_write` — ვარაუდი openai SDK 3.40-ის Usage API docstring-ით („including cached and cache-write tokens"), Responses-ის რეალურ პასუხზე Stage 15-ში დასადასტურებელი); `output_tokens` (OpenAI-ზე reasoning-ის ჩათვლით); `None` → 0. ფასის შეფასებაში cache write 1.25×-ით ითვლება (1h write მხოლოდ L1-ზეა, საათში ≤1-ჯერ — უმნიშვნელო).
- ჩაწერა: `llm.record_usage` service client-ით ყოველი წარმატებული გამოძახების შემდეგ (refusal/ცარიელი პასუხიც, თუ API-მ usage დააბრუნა); შეცდომა → `logger.warning`, პასუხი არ ფუჭდება; LLM არ გამოძახებულა → რიგი არ იწერება. PII არ ინახება.
- Run order: **0025 backend deploy-მდე** (ახალი backend მასში წერს; ჩავარდნა მაინც არაფატალურია). მფლობელი უშვებს ხელით.
- როგორ შეიცვლება: პანელში ჩვენება / per-tenant ხარჯის ჭერი / retention — Backlog (Stage 15-ის მონაცემის შემდეგ).

### 2026-10-28 — dependencies ორ ნაბიჯად; lock — local venv-ის `pip freeze`-ით
- Decision: S14-1 ამატებს `anthropic`, `openai` (`google-genai` რჩება → ტესტები მწვანეა), S14-7 შლის `google-genai`-ს და მხოლოდ მის transitive-ებს (Gemini-ს კოდის წაშლის შემდეგ). lock-ის ძველი წყარო (Render-ის build log) ახლა არ არის → `backend/.venv`-ში ინსტალაცია + `pip freeze` diff, ხელით შერწყმა (არსებული pin-ები არ იცვლება, თუ resolver არ მოითხოვს — report-ში), header-ში ჩანაწერი. სისრულე მოწმდება სუფთა venv-ით (`--no-deps` + `pip check`); Linux/3.14.3 resolution — Render-ის deploy-ზე. `anthropic` 1.x `httpx2`-ზეა (ახალი dependency).
- Reason: ერთ task-ში წაშლა+დამატება შუალედურ მდგომარეობაში ტესტებს/კოდს გატეხავდა (Gemini-ს კოდი ჯერ `google-genai`-ს ეყრდნობა). brief-ისგან გადახვევა: shared ფაილი ორ task-შია, თანმიმდევრულად.

### 2026-10-28 — ტესტები: dummy key + რეალური client-ების guard (Stage 14)
- Decision: `tests/conftest.py` — `ANTHROPIC_API_KEY="test-anthropic-key-not-real"`, `OPENAI_API_KEY=""`, `LLM_PROVIDER="claude"` (ტესტების default = კონფიგურირებული ბოტი → webhook-ის არსებული ტესტები უცვლელად მუშაობს); `CLAUDE_MODEL`/`OPENAI_MODEL`/`LLM_TIMEOUT_SECONDS` env-იდან **იშლება** (`os.environ.pop`), არა ცარიელდება (ცარიელი სტრიქონი default-ს გადაფარავდა / float-ად ვერ გარდაიქმნება). autouse fixture `llm._anthropic_client`/`_openai_client`-ს ანაცვლებს `RuntimeError`-ით — fake-ის გარეშე ტესტი ქსელს ვერ მიაღწევს. key-ის გარეშე ქცევა — ცხადი `Settings(...)`/`model_copy`-ით.
- Golden: ფენა 1-ის ტექსტი — `tests/fixtures/prompt_layer1.txt` (შედარება `\r\n`→`\n` ნორმალიზაციით — Windows checkout); 5 ქართული სცენარი (მისალმება, ფასი/მარაგი, ამოწურული, ოპერატორი → `[[HANDOFF]]`, ფოტო) ორივე provider-ზე canned პასუხებით; მფლობელის ტესტი (L1 და L2 ბაიტ-იდენტურია ორ სხვადასხვა შეტყობინებაზე) — `prompt`-ის დონეზეც და მთელ `get_bot_reply`-ზეც (request-ის `system`).
- ტესტების მოსალოდნელი რაოდენობა Stage 14-ის შემდეგ: ≈ 274 − 8 + ~60 ≈ 320–330.

### 2026-10-28 — დოკუმენტაცია, privacy, ფაზა 1ბ
- Decision: README / CLAUDE.md / `.env.example` / DEPLOYMENT.md განახლდება Stage 14-ში; `frontend/privacy.html` (§4 subprocessor-ები, §9 გადაცემა) და `frontend/terms.html` (subprocessor-ების სია) — Google → Anthropic, OpenAI; `npm run build`, `dist/` იმავე commit-ში. ისტორიული დოკუმენტები (MONETIZATION, ROADMAP, AUDIT, CODE_REVIEW_*, REACT_MIGRATION) არ გადაიწერება — Backlog. `backend/scripts/compare_gemini_models.py` და `compare_gemini_output.md` იშლება (Stage 15 ახალ სკრიპტს წერს).
- ვარაუდი (/auto): ფაზა 1ბ (DESIGN.md + Playwright) ამ stage-ში გამოტოვებულია — UI/ვიზუალი არ იცვლება, მხოლოდ ტექსტი ორ legal გვერდზე; შემოწმება — `dist` diff მხოლოდ ამ ორ ფაილში. შეიცვლება: თუ მფლობელს Playwright smoke სურს — ცალკე task.
- ვარაუდი: privacy-ში OpenAI ჩამოთვლილია „ალტერნატიულ მომწოდებლად" (კოდში ჩართვადია env-ით); იურიდიული ფორმულირება — მფლობელის შესამოწმებელი (Open Questions).

### 2026-10-28 — Stage 15: ბრმა შედარების სკრიპტი იწერება, აგენტი არ უშვებს; `scripts` — package
- Decision: `backend/scripts/compare_providers.py` + ცარიელი `backend/scripts/__init__.py`; გაშვება `backend/`-იდან `python -m scripts.compare_providers` (ასე `app` იმპორტდება `sys.path`-ის ხელით შეცვლის გარეშე; pytest-ის `pythonpath = .` იგივე package-ს ხედავს → ტესტი `from scripts import compare_providers`). 40 შეკითხვა × 2 provider = 80 გამოძახება, თანმიმდევრულად. **აგენტი სკრიპტს shell-იდან არასდროს უშვებს** — არც dummy key-ით, არც `--dry-run`-ით, არც `--help`-ით; ტესტები `main(argv)`-ს და ფუნქციებს აიმპორტებენ fake client-ებით. რეალური გაშვება — მხოლოდ მფლობელი, key-ების შემდეგ (README §9).
- Reason: მფლობელის მოთხოვნა (key-ები ჯერ არ არის; რეალური API აკრძალულია). `--dry-run` ქსელს არ მიმართავს, მაგრამ shell-იდან `Settings` ლოკალურ `.env`-ს კითხულობს (production საიდუმლოებით) — ტესტში conftest `.env`-ს თიშავს, ამიტომ dry-run უსაფრთხოდ მხოლოდ pytest-იდან მოწმდება.
- Alternatives considered: `sys.path.insert` სკრიპტის თავში (ჰაკი + ruff E402); ტესტში `importlib`-ით ფაილის გზით ჩატვირთვა (იმპორტის ორი განსხვავებული გზა).
- როგორ შეიცვლება: CI `ruff`/`compileall` ახლა მხოლოდ `app tests`-ს ამოწმებს — `scripts` მოწმდება task-ის done-when-ში ლოკალურად; თუ სკრიპტები გამრავლდება → CI-ში დამატება (Backlog).

### 2026-10-28 — provider-ის override: `llm.generate(prompt, shop_id, provider=None)` (S15-1)
- Decision: `generate`-ს ემატება keyword `provider: str | None = None` და მოდულის კონსტანტა `PROVIDERS = ("claude", "openai")`. `None` → ქცევა ზუსტად ისეთი, როგორც ახლა. სხვა მნიშვნელობა: `provider not in PROVIDERS` → `ValueError` (factory-ის გამოძახებამდე; case-sensitive); წინააღმდეგ შემთხვევაში `s = get_settings().model_copy(update={"llm_provider": provider})` — `llm_ready`, `llm_key_env_name`, `llm_model`, factory და retry ამ ასლიდან გამოდის (not ready → `RuntimeError` მოთხოვნილი provider-ის env სახელით). cache-ში არსებული `Settings` არ იცვლება.
- Reason: ერთ გაშვებაში ორივე provider, ზუსტად production-ის request/retry/usage-ის ნორმალიზაციით. `model_copy` ვალიდაციას არ უშვებს → უცნობი სახელი ცხადად უნდა შემოწმდეს, თორემ `generate`-ის `else` განშტოება ჩუმად OpenAI-ს აირჩევდა.
- Alternatives considered: სკრიპტი `llm.get_settings`-ს monkeypatch-ით ცვლის (global state, production კოდში patch); `settings=` პარამეტრი (უფრო ფართო API — გამომძახებელი ნებისმიერ პარამეტრს შეცვლის); `_call_claude`/`_call_openai`-ის პირდაპირი გამოძახება (private, retry-ის გარეშე → გაზომვა production-ს აღარ ემთხვევა).
- როგორ შეიცვლება: Stage 16-ის გრაფს იგივე kwarg შეუძლია (მაგ. summary სხვა provider-ით). default გზა უცვლელია — არსებული ტესტები ფარავს.

### 2026-10-28 — სკრიპტი = `get_bot_reply`-ის გზა ქსელის/DB-ის გარეშე; `llm_usage` არ იწერება (Stage 15)
- Decision: თითო შეკითხვაზე სკრიპტი იმეორებს `bot.get_bot_reply`-ს: ფოტოზე `prompt.select_relevant_products` (`prompt._sort_key`-ით დალაგებულ მარაგზე) → იმ პროდუქტების საცნობარო ფოტოები, რომლებსაც `image` აქვთ (≤12, label `bot._fetch_product_images`-ის ფორმატით) → `prompt.build_prompt` → `llm.generate(..., provider=…)` → `bot.parse_reply` (`[[HANDOFF]]`). ფოტოები — ლოკალური ფაილები `compare_assets/`-იდან (Storage/Graph არა). `llm.record_usage` / `get_service_client` **არ** გამოიძახება; ტოკენები `LLMResult.usage`-დან ფაილებში იწერება. Supabase-ის env საჭირო არ არის: `get_settings()` fail-closed-ს არ ამოწმებს (ეს `main.check_required_settings`-ია), `get_service_client` client-ს მხოლოდ გამოძახებისას ქმნის.
- Reason: ლოკალური `.env` production Supabase-ს უკავშირდება — ფიქტიური მაღაზიის `llm_usage` რიგი FK-ზე ჩავარდებოდა ან production-ის მონაცემს შეურევდა. `get_bot_reply`-ის პირდაპირ გამოძახებას `record_usage` და Storage-დან ჩამოტვირთვა ახლავს.
- Alternatives considered: `get_bot_reply(..., record=False)` + ფოტოს წყაროს პარამეტრი (production კოდის ცვლილება მხოლოდ სკრიპტისთვის).
- Trade-off: latency მოიცავს SDK client-ის შექმნას და TLS-ს ყოველ გამოძახებაზე — ზუსტად როგორც production-ში (Backlog „Stage 14" nit (c)), ამიტომ გაზომვა სწორია და nit ამ stage-ში არ სწორდება. Backlog-ის სხვა nit-ებიც შედარებას სისტემურად არ ამახინჯებს (ფოტოები მცირე PNG-ია, 5 MB/mime-ის გზა არ ეხება) → არცერთი არ შედის Stage 15-ში.

### 2026-10-28 — სადემონსტრაციო მაღაზია და 40 შეკითხვა: ერთი JSON, ≤30 პროდუქტი, სინთეტიკური PNG (Stage 15)
- Decision: `backend/scripts/compare_questions.json` = `shop` (ფიქტიური, `id` `00000000-0000-4000-8000-000000000015`, GEL, `bot_language` `auto`, ცოდნა: მიწოდება/გადახდა/დაბრუნება) + `products` (24 — ტანსაცმელი/ფეხსაცმელი/აქსესუარი; ≥3 ამოწურული, 1 ფასის გარეშე, 4 ფოტოიანი `image`-ით) + `questions` (40). კატეგორიები (ზუსტი რაოდენობა, ტესტით): `stock_price` 6, `out_of_stock` 3, `price_on_request` 1, `knowledge` 5, `knowledge_missing` 2, `ambiguous` 3, `multi_turn` 4, `order` 2, `handoff` 3, `off_topic` 2, `language` 2 (en, ru), `injection` 3, `photo` 4. შეკითხვა: `id` (`Q01`…`Q40`), `category`, `message`, არასავალდებულო `history` (webhook-ის ფორმატი `{"role": "user"|"bot", "content"}`), `image` (ფაილის სახელი `compare_assets/`-ში), `expect` (`handoff`: true/false/null = ნებისმიერი, `note` — შემფასებლისთვის, არასავალდებულო `must_mention`).
- ვარაუდი (/auto): ერთი მაღაზია ≤30 პროდუქტით — სრული მარაგი L2-შია (პატარა ქართული მაღაზიის ტიპური შემთხვევა; L2 ყველა 80 გამოძახებაზე ერთია → cache-ის ეკონომიკაც რეალისტურად იზომება). >30-ის retrieval-ის გზა (keyword-ზე, provider-ისგან დამოუკიდებელი) შედარებაში არ შედის — Backlog.
- ვარაუდი (/auto): ფოტოები სინთეტიკურია — 8 PNG (4 პროდუქტის + 4 კლიენტის), 256×256, თეთრ ფონზე ფერადი სილუეტი (მაისური/შარვალი/ქურთუკი/ფეხსაცმელი/ქუდი), stdlib `zlib`+`struct`-ით; გენერატორი სესიის scratchpad-შია, repo-ში არა (Pillow არ ემატება). ფოტო-შეკითხვები ამოწმებს pipeline-ს და უხეშ ვიზუალურ შესაბამისობას, არა რეალური ფოტოს ამოცნობას (Stage 18).
- Alternatives considered: ფოტოს runtime-ში გენერაცია JSON-ის ფერებიდან (binary ფაილის გარეშე, მაგრამ ორი მექანიზმი და ფაილის გზა აღარ ემთხვევა production-ის bytes+mime-ს); Pillow (ახალი dependency ერთჯერადი ამოცანისთვის); ცალკე `compare_shop.json` (მეტი ფაილი, სარგებლის გარეშე); მეორე მაღაზია >30 პროდუქტით (80 → 160 გამოძახება).
- როგორ შეიცვლება: მფლობელს რეალური ფოტოები ან >30-იანი მაღაზია სურს → ცალკე task (შეკითხვების ფორმატი იგივე რჩება).

### 2026-10-28 — ბრმა გამოსავლის ფორმატი: A/B per შეკითხვა, usage ჩაკეცილი, provider-ის ჯამები მხოლოდ გასაღებში (Stage 15)
- Decision: შეკითხვების რიგი ფიქსირებულია (`Q01`…`Q40`, კატეგორიებით); A/B — თითო შეკითხვაზე `random.Random(seed)`-ით (`--seed`, default 15), დანიშვნა ყველა ჩატვირთულ შეკითხვაზე ითვლება (`--limit`-ისგან დამოუკიდებლად). `compare_output.md`: header (თარიღი, seed, რუბრიკა, „ფასები ნაწილობრივ UNVERIFIED"), თითო შეკითხვაზე — ისტორია, ფოტოს სახელი, ტექსტი, `expect`, პასუხი A და B (`[[HANDOFF]]` მოცილებული + `handoff: yes|no`, ტექსტი fenced ბლოკში უცვლელად), ტოკენები (input / cache read / cache write / output), latency, ფასი — `<details>` ბლოკში, რუბრიკის ცხრილი (0–2); ბოლოს მხოლოდ **საერთო** ჯამი (გამოძახებები, შეცდომები, ჯამური ფასი). provider-ის/მოდელის სახელი output-ში არსად არ არის (ტესტით). `compare_key.json`: seed, created_at, მოდელები, ფასების ცხრილი, mapping, შეცდომები (`class` + `status`), per-provider ჯამები. გამოძახების შეცდომა → `[error: <ExceptionClass>]` (შეტყობინება არა — შეიძლება provider-ს ან key-ის ფრაგმენტს შეიცავდეს), ცარიელი პასუხი → `[empty answer]`; გაშვება გრძელდება.
- Reason: მფლობელს ტოკენები და ფასი თითო პასუხზე იმავე ფაილში სურს, მაგრამ tokenizer-ები განსხვავდება → input-ის ტოკენები provider-ის „ანაბეჭდია"; `<details>` მათ rendered markdown-ში მალავს, README კი ჯერ ტექსტის შეფასებას ითხოვს. „A-ს ჯამი" უაზროა (A ორივე provider-ს აერთიანებს), provider-ის ჯამი კი ბრმას არღვევს → გასაღებში.
- Alternatives considered: usage მხოლოდ გასაღებში (მფლობელის ფორმულირებიდან გადახვევა); შეკითხვების რიგის shuffle-იც (კატეგორიით დაჯგუფება შეფასებას ამარტივებს, ბრმას არ ეხება); შეცდომის სრული ტექსტი (key-ის ფრაგმენტის რისკი).
- როგორ შეიცვლება: თუ usage შეფასებაზე მოქმედებს — `--hide-usage` (Backlog).

### 2026-10-28 — ფასების ცხრილი სკრიპტში; gpt-6-luna — UNVERIFIED (Stage 15)
- Decision: `PRICES` (USD / 1M ტოკენი), თითო provider-ზე `model`, `input`, `output`, `cache_read`, `cache_write`, `unverified`, `source`: claude (`claude-haiku-5-5`) — 0.10 / 0.50 / 0.01 (0.1×) / 0.125 (1.25×, 5m), წყარო DEPLOYMENT.md + ეს Decision Log; openai (`gpt-6-luna`) — 0.10 / 0.50 / 0.01 / 0.10, **`unverified: True`** (კომენტარი `UNVERIFIED`, output-ის header, გასაღები). ფასი = Σ(ტოკენი × ფასი) / 1e6 (`Usage.input_tokens` უკვე uncached-ია). გამარტივებები (კომენტარში): L1-ის 1h write (2×) ითვლება 1.25×-ით (საათში ≤1-ჯერ); >100K-ტოკენიანი request-ის 5× არ მოდელირდება (prompt ≤ `MAX_PROMPT_CHARS`); სურათის ტოკენები provider-ის `input_tokens`-შია. `CLAUDE_MODEL`/`OPENAI_MODEL` ცხრილის მოდელისგან განსხვავდება → stderr WARNING + გასაღებში `prices_match_models`.
- ვარაუდი (/auto): OpenAI-ის cache write — input-ის ფასით (დანამატის გარეშე); დაუდასტურებელია (Open Questions).
- Reason: ფასი გამოსავალში მხოლოდ შეფასებაა; რეალური ხარჯი — provider-ის კონსოლში (README).

### 2026-10-28 — გაშვების უსაფრთხოება: ორივე key სავალდებულო, `--dry-run`, `--limit`, `--delay` (Stage 15)
- Decision: key-ები მხოლოდ `Settings`-იდან (env / ლოკალური `.env`); რომელიმე ცარიელია → stderr-ში მხოლოდ ცვლადის სახელ(ებ)ი, exit 2, ფაილი არ იქმნება, client არ იქმნება. ერთი provider-ის რეჟიმი **არ არის** (ბრმა A/B ორივეს ითხოვს). `--dry-run` — 40 prompt-ის აგება და ზომების ბეჭდვა key-ის, client-ის და ფაილის გარეშე. `--limit N` — პირველი N შეკითხვა (smoke: 3 → 6 გამოძახება). `--delay` (default 1.0 წმ) გამოძახებებს შორის, თანმიმდევრულად; timeout/retry — `llm.generate`-ის (1 retry, 45 წმ ბიუჯეტი). მონაცემის/ფოტოს შეცდომა → exit 2 პირველ გამოძახებამდე. ფაილები იწერება ბოლოს (`--out-dir`, default `backend/scripts/`, ორივე სახელი `.gitignore`-შია); Ctrl+C → არაფერი იწერება. console-ის პროგრესში provider-ის სახელი არ ჩანს.
- Reason: ხარჯის კონტროლი (smoke), rate limit-ის თავიდან აცილება, ბრმის დაცვა, საიდუმლოების არგამჟღავნება.
- Alternatives considered: `--provider claude|openai` (ბრმა აღარ არის; ერთი provider-ის გამართვა `--limit`-ით და ერთი key-ით მაინც შეუძლებელია — მისაღებია); პარალელური გამოძახებები (429-ის რისკი, latency-ს გაზომვა მახინჯდება); ნაწილობრივი ფაილის ჩაწერა ყოველი შეკითხვის შემდეგ (მეტი კოდი; 80 გამოძახება რამდენიმე წუთია).
- როგორ შეიცვლება: შედეგის შემდეგ მფლობელი Decision Log-ში წერს: default provider, thinking/effort, output-ის ჭერი (800), 5m cache-ის ეკონომიკა (გასაღების ჯამები: cache read vs write), OpenAI-ის `input_tokens`-ის სემანტიკა, gpt-6-luna-ს რეალური ფასი.

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
- ~~Gemini 2.5 Flash retires 2026-10-16~~ → გადაწყვეტილება: Stage 14 (Decision Log 2026-10-28). **ღიაა:** production (`main`) ჯერ Gemini-ზეა და თარიღი გავიდა — ახლა ლაივზე რომელი მოდელი მუშაობს (`GEMINI_MODEL`) და პასუხობს თუ არა ბოტი? (მფლობელი; Stage 14-ის merge key-ებამდე არ იგეგმება.)
- **gpt-6-luna** (Stage 14/15): ოფიციალური ფასი (მესამე მხარის წყაროები: $0.10 in / $0.50 out, cached ≈ $0.01 per MTok, ~1.05M context, 128K output) OpenAI-ის pricing გვერდზე **დაუდასტურებელია**; ასევე: Responses API-ის მხარდაჭერა, `prompt_cache_key`, reasoning-ის პარამეტრები და reasoning-ტოკენები `max_output_tokens`-ში. პირველი რეალური გამოძახება — Stage 15-ის სკრიპტით (მფლობელი). Stage 15-ის ფასების ცხრილში OpenAI-ის cache write = input-ის ფასი — ვარაუდი, დასადასტურებელი.
- ქართულზე ტოკენი/სიმბოლო თანაფარდობა (Claude/OpenAI) უცნობია → `MAX_PROMPT_CHARS=50_000` პესიმისტურია; L1 ≥512 ტოკენი რეალურად დადასტურდება მხოლოდ პირველ გამოძახებაზე (`cache_creation_input_tokens > 0`, შემდეგ `cache_read_input_tokens > 0`).
- Claude-ის ერთი სურათის ზომის ლიმიტი — ვარაუდი 5 MB (`llm.MAX_IMAGE_BYTES`; კლიენტის ფოტო `download_image`-ით 8 MB-მდეა) — დოკუმენტაციით დასაზუსტებელი.
- `anthropic` / `openai` SDK `retry-after` header-ს ითვალისწინებს თუ არა `max_retries=1`-ზე (worst case > 41 წმ) — S14-4 ამოწმებს SDK-ის კოდში.
- `anthropic` (`httpx2`) და `openai`-ს compiled დამოკიდებულებებს (მაგ. `jiter`) Python 3.14 manylinux wheel აქვს? — S14-1 ამოწმებს, საბოლოოდ Render-ის deploy.
- Anthropic-ის workspace: cache workspace-ზეა — production-ისთვის ცალკე workspace + spend limit? data retention (privacy.html-ის ფორმულირება Anthropic/OpenAI-ზე) — მფლობელი.
- 5m cache write-ის ეკონომიკა დაბალ ტრაფიკზე (1.25× write vs 0.1× read) — Stage 15-ის სკრიპტის გასაღების ჯამებით (ერთ გაშვებაში cache „თბილია" — დაბალი ტრაფიკის შემთხვევას production-ის `llm_usage` აჩვენებს).
- ვარაუდი (Stage 15): სატესტო ფოტოები სინთეტიკურია, მაღაზია ერთია ≤30 პროდუქტით — მფლობელს რეალური ფოტოები / დიდი კატალოგის შედარება სურს? (Decision Log 2026-10-28, Stage 15).
