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
**Stage 18 — ფოტოები: პროდუქტის ფოტოს ტექსტური აღწერა ერთხელ (create/update-ზე) + კლიენტის ფოტოზე ≤3 საცნობარო ფოტო (აღწერის ერთი გამოძახება მხოლოდ >3 აღწერიან მაღაზიაზე); migration 0028**
(იხ. `PROGRESS.md`; Stage 10–17 დასრულებულია, Stage 14–17 — offline, deploy/გაშვება key-ებს ელოდება). Stage 18 — Stage 15–18 სერიის ბოლო.
სამუშაო მხოლოდ `agent-system`-ზე; `main`-ში merge არ იგეგმება, სანამ API key-ები არ იქნება. ყველაფერი offline, fake client-ებით.

## Scope
### In scope (current stage — Stage 18)
- `services/vision.py`: `describe_images` (ერთი `llm.complete(images=)` → `EN:` + `KA:` ორხაზიანი აღწერა ≤500, არასდროს აგდებს, usage → `llm_usage`), `describe_product_image` (მხოლოდ საკუთარი Storage), `save_image_description` (service, პირობითი `image_url`-ზე, 0028-ის გარეშე tolerance), `query_text`
- `llm.py`: `complete(..., images=None)` — Claude image block / OpenAI `input_image` (`detail: low`); `images=None` → Stage 17-ის request ბაიტ-იდენტურად
- `api/products.py`: `create_product` / `update_product` — `image_url`-ის დაყენება/შეცვლა ამ მაღაზიის საკუთარ ფოტოზე → აღწერა სინქრონულად (≤~35 წმ worst case), მოხსნა/შეცვლა → ძველი აღწერა იშლება/იცვლება; 30 აღწერა/სთ მაღაზიაზე (`ratelimit.allow`); `upload-image` და API-ის response-ები უცვლელი
- `prompt.py` / `graph.py` / `bot.py`: `match_products` ხედავს `image_description`-ს; კლიენტის ფოტოზე — აღწერა (პირობითად) → retrieval-ის query (>30) + რანჟირება → `MAX_REF_IMAGES` 12 → **3**; L1 წესი 12 და საცნობარო ბლოკის ტექსტი; L2 უცვლელი
- migration `0028` (`products.image_description`); backfill სკრიპტი (`backend/scripts/backfill_image_descriptions.py`, მხოლოდ მფლობელი უშვებს); შედარების სკრიპტის მონაცემები (ხელით დაწერილი აღწერები, 8 ფოტოიანი პროდუქტი); README / CLAUDE.md
### Stage 17-ის scope (დასრულებული, ისტორია)
- `services/knowledge.py`: `build_faq(shop_id, text)` — ატვირთვისას **ერთი** `llm.complete` → მოკლე FAQ (≤3000 სიმბოლო, `Q:`/`A:` ხაზები, PDF = DATA); არასდროს აგდებს; usage → `llm_usage`
- `api/shops.py`: `upload_knowledge` — FAQ სინქრონულად (≤40 წმ), ერთი service update `{knowledge, knowledge_filename, knowledge_faq}`; FAQ-ის ჩავარდნა → ატვირთვა მაინც ინახება (`knowledge_faq = null`); `clear_knowledge` FAQ-საც შლის; ლიმიტი 10 ატვირთვა/სთ; PDF-ის ტექსტის ჭერი 20 000 → 50 000 (`pdf_extract.MAX_CHARS`)
- `prompt.py` L2: FAQ ანაცვლებს 20000-იან clip-ს; FAQ-ის გარეშე — Stage 16-ის L2 ბაიტ-იდენტურად; L1 წესები 9 / 13 (ძებნა FAQ-ში არარსებულ დეტალზე); `MAX_PROMPT_CHARS` უცვლელი (60 000), worst-case ტესტები
- `tools.py` `search_knowledge`: ხაზებით chunk-ები + ქართული ფუძეები (მეხსიერებაში, ცხრილის გარეშე); migration `0027` (`shops.knowledge_faq`); შედარების სადემონსტრაციო მაღაზიას ხელით დაწერილი FAQ; README / CLAUDE.md
### Stage 16-ის scope (დასრულებული, ისტორია)
- `services/graph.py`: `preprocess → agent ⟲ tools → postprocess`, `run_turn(...) -> TurnResult`; wiring — LangGraph, თუ S16-1 = GO, თორემ plain Python (იგივე node-ები). LLM-ის გამოძახება მხოლოდ `llm.py`-ით (LangChain chat model-ები — არა)
- `llm.py`: tool calling ორივე provider-ზე (Claude `tool_use`/`tool_result`, OpenAI `function_call`/`function_call_output`), turn-ის deadline, `complete()` summary-სთვის
- `services/tools.py`: `search_products`, `search_knowledge`, `order_link` (read-only, მხოლოდ state-იდან) + `request_human` (ანაცვლებს `[[HANDOFF]]`-ს → `needs_attention`)
- `services/replies.py`: მისალმება / მადლობა / ოპერატორის მოთხოვნა (ka/en/ru) შაბლონით, LLM-ისა და `llm_usage`-ის გარეშე; markdown-ის გასუფთავება
- `services/memory.py` + migration `0026` (`bot_conversations.summary`): ისტორია 16-ზე მეტისას → ბოლო 8 + summary (ერთი დამატებითი გამოძახება, პასუხის გაგზავნის შემდეგ)
- webhook + `/test-chat` → `run_turn`; `get_bot_reply` / `parse_reply` / `[[HANDOFF]]` იშლება; შედარების სკრიპტი იმავე გზით (`run_turn`, provider-ის override, DB-ის გარეშე)
### Out of scope (for now)
- Stage 18-ში: frontend (აღწერის ჩვენება/რედაქტირება/ხელახლა გენერაცია — Backlog), აღწერა `upload-image`-ში ან background-ში, embeddings / vector search, აღწერები L2-ში, Excel import-ის ფოტოები, `MAX_IMAGE_BYTES`-ის ცვლილება, default provider-ის ცვლილება, Stage 14–17-ის Backlog nit-ები (გარდა Stage 16-ის „ჩამოტვირთვა deadline-ში" — ნაწილობრივ, ≤3 ფოტოთი)
- Stage 17-ში: `knowledge_chunks` ცხრილი / Postgres FTS / pg_trgm / embeddings (Decision Log 2026-10-29); FAQ background-ში; frontend (FAQ-ის სტატუსი/გადახედვა — Backlog); არსებული მაღაზიების FAQ-ის backfill სკრიპტი; `MAX_PROMPT_CHARS`-ის შემცირება; ფოტოს აღწერა (Stage 18); default provider-ის ცვლილება
- Stage 16-ში: L2-ის ცვლილება (მარაგი/ცოდნა რჩება), PDF-ის chunk-ები / FAQ (Stage 17), ფოტოს აღწერა (Stage 18), default provider-ის ცვლილება, frontend (privacy-ის ტექსტი — Open Questions), Stage 14/15-ის Backlog nit-ები (გარდა Stage 15 (c) — S16-9)
- ახალი ფიჩერები — [ROADMAP.md](ROADMAP.md) (Instagram Live, web widget, ინტეგრაციები,
  ავტომატური billing, Redis/queue, CSP, admin pagination)

## Core Flows
1. რეგისტრაცია → მაღაზია → პროდუქტები (ხელით / Excel / CSV) → PDF-ცოდნა.
2. Facebook OAuth connect → page token (დაშიფრული) → webhook subscribe.
3. Meta webhook (`POST /webhook`, ხელმოწერით) → page_id → მაღაზია → ლიმიტები →
   LLM (ახლა Gemini; Stage 14-დან Claude/OpenAI; key-ის გარეშე — ოპერატორის პასუხი; Stage 16-დან გრაფი: შაბლონი ან agent + tools ≤4 გამოძახებით → markdown-ის გასუფთავება) → Send API პასუხი (background task) → ისტორიის შენახვა (16-ზე მეტისას summary).
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
Stage 16: `0026_bot_conversations_summary.sql` (დაგეგმილი) — `bot_conversations.summary text` (nullable): ძველი შეტყობინებების
მოკლე შეჯამება; წერს მხოლოდ backend (service_role, როგორც `messages`), გამყიდველი კითხულობს საკუთარს 0008-ის select პოლისით;
ახალი grant/პოლისი არ არის. backend მის გარეშეც მუშაობს (summary გამორთულია, WARNING).
Stage 17: `0027_shops_knowledge_faq.sql` (დაგეგმილი) — `shops.knowledge_faq text` (nullable): PDF-ის ტექსტის მოკლე FAQ (≤3000, LLM-ით, ერთხელ
ატვირთვისას); null = FAQ არ არის (ბოტი — ცოდნის პირველი 20 000 სიმბოლო). წერს მხოლოდ backend (service client, `upload_knowledge`/`clear_knowledge`,
როგორც `knowledge` — 0022); `authenticated`-ს ცხრილის დონის UPDATE არ აქვს → ახალი grant/revoke/პოლისი არ სჭირდება. სრული ტექსტი (≤50 000)
რჩება `shops.knowledge`-ში; ცალკე chunk-ების ცხრილი **არ არის** (ძებნა მეხსიერებაში). backend სვეტის გარეშეც მუშაობს (FAQ გამორთულია, WARNING).
Stage 18: `0028_products_image_description.sql` (დაგეგმილი) — `products.image_description text` (nullable): პროდუქტის ფოტოს მოკლე აღწერა (≤500, `EN:` + `KA:` ხაზები,
LLM-ით, ერთხელ — `image_url`-ის დაყენება/შეცვლისას ან backfill სკრიპტით); null = აღწერა არ არის. იყენებს მხოლოდ ბოტის ძებნა/რანჟირება (L2-ში არ ჩანს).
წერს მხოლოდ backend (service client, მფლობელობის შემოწმების შემდეგ, პირობითად `image_url`-ზე); `authenticated`-ს `products`-ზე ცხრილის დონის INSERT/UPDATE არ აქვს
და column UPDATE მხოლოდ 7 სვეტზეა (0015) → ახალი grant/revoke/პოლისი არ სჭირდება. backend სვეტის გარეშეც მუშაობს (აღწერა გამორთულია, ერთჯერადი WARNING).
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
  `services/llm.py`; Stage 16: `services/graph.py` (+ `tools.py`, `replies.py`, `memory.py`) — wiring LangGraph-ით (S16-1 GO) ან plain Python;
  LLM-ის გამოძახება ყოველთვის `llm.py`-ით (Decision Log 2026-10-28, Stage 16); Stage 17: `services/knowledge.py` (FAQ ერთხელ, ატვირთვისას); Stage 18: `services/vision.py` (ფოტოს აღწერა: პროდუქტზე ერთხელ, კლიენტის ფოტოზე პირობითად)
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
  **Stage 16: კონტრაქტი უცვლელია** (`{reply, products_in_context, model}`, იგივე სტატუს-კოდები). შიგნით — `graph.run_turn`: შაბლონურ
  შეტყობინებაზე (მაგ. „გამარჯობა") `reply` = შაბლონი LLM-ის გამოძახების გარეშე (503-ის შემოწმება მანამდე რჩება); `reply` markdown-ისგან
  გასუფთავებულია; handoff (`request_human`) პასუხში არ ჩანს (როგორც ახლა `[[HANDOFF]]`); turn-ის ბიუჯეტის ამოწურვა (`TimeoutError`) → 502.
- **`POST /webhook`** — Stage 16: გარე ქცევა უცვლელია; handoff-ის წყარო `[[HANDOFF]]` ნიშნის ნაცვლად `request_human` tool call ან ოპერატორის შაბლონია → `needs_attention`.
- **`POST /shops/{id}/knowledge`** (multipart `file`: `.pdf`, ≤10 MB; Bearer) — **Stage 17: response უცვლელია** — 200 `ShopOut` (`knowledge` და `knowledge_faq` არ ბრუნდება; `knowledge_filename` — ნიშანი). სტატუსები უცვლელი: 400 (არა-`.pdf` / ცარიელი / >10 MB / PDF ვერ წაიკითხა / ტექსტი არ აქვს), 403 (free პაკეტი — LLM-მდე), 404 (მაღაზია არ არის ან სხვისია), + ახალი **429** `{"detail": "ბევრი მოთხოვნა მოვიდა — სცადეთ ცოტა ხანში."}` (+ `Retry-After`; 10 მოთხოვნა/სთ IP-ზე). შიგნით: ტექსტი ≤50 000 სიმბოლო + FAQ ერთი LLM გამოძახებით (≤40 წმ; მოთხოვნა ≤~45 წმ); FAQ-ის ჩავარდნა / key-ის გარეშე → მაინც 200 (`knowledge_faq = null`); ხელახალი ატვირთვა ტექსტს და FAQ-ს ერთად ცვლის.
- **`DELETE /shops/{id}/knowledge`** — Stage 17: კონტრაქტი უცვლელი (200 `ShopOut`, 404); `knowledge`, `knowledge_filename` და `knowledge_faq` ერთად სუფთავდება; LLM არა.
- **`POST /products/upload-image`** — Stage 18: **უცვლელი** (multipart `shop_id`, `file`; 200 `{url: str, path: str}`; 400 / 404 / 429 / 502 / 503 როგორც ახლა); აღწერა აქ **არ** იქმნება (პროდუქტი ჯერ არ არსებობს).
- **`POST /products`** (201 `ProductOut`) და **`PUT /products/{id}`** (200 `ProductOut`) — Stage 18: request/response **უცვლელი** (`ProductOut`-ში `image_description` არ ბრუნდება; `ProductCreate`/`ProductUpdate`-ში არ არის — გამყიდველი მას ვერ წერს), სტატუს-კოდები უცვლელი (404 სხვისი/არარსებული, 403 ლიმიტი, 400, 422). შიგნით: როცა `image_url` დგება/იცვლება ამავე მაღაზიის საკუთარ Storage ფოტოზე (`<SUPABASE_URL>/storage/v1/object/public/product-images/<shop_id>/…`), მოთხოვნა ფოტოს აღწერას ელოდება (ტიპურად რამდენიმე წამი; worst case ≤~35 წმ: ჩამოტვირთვა ≤15 + LLM ≤20); აღწერის ჩავარდნა / key-ის გარეშე / 30 აღწერა/სთ მაღაზიაზე გადაჭარბება / 0028-ის გარეშე → მაინც 201/200 (აღწერა null; 429 **არა**); `image_url`-ის მოხსნა ან გარე URL → ძველი აღწერა იშლება LLM-ის გარეშე; სხვა ველის ცვლილება — LLM არა. `POST /products/import` — უცვლელი (LLM არა).
- **`POST /webhook`** — Stage 18: გარე ქცევა უცვლელი; კლიენტის ფოტოზე LLM-ს მიდის ≤3 საცნობარო ფოტო (ადრე ≤12); >3 აღწერიან მაღაზიაზე turn-ს ემატება ≤1 აღწერის გამოძახება (ჯამი ≤5 + summary ≤1).

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

### 2026-10-28 — Stage 16: LangGraph თუ plain Python — S16-1-ის go/no-go; არქიტექტორის რეკომენდაცია: plain Python
- Context: მფლობელმა ცხადად ითხოვა LangGraph. ნაკადი = 3 node + ერთი შემოსაზღვრული ციკლი (`agent ⟲ tools`, ≤3 რაუნდი) ერთი შეტყობინების ფარგლებში; ისტორია Supabase-შია (checkpointer არ გვჭირდება); streaming, interrupt/resume, პარალელური branch-ები არ გამოიყენება. LLM-ის გამოძახება LangChain chat model-ით აკრძალულია (`cache_control`-ის და ბაიტ-იდენტური prefix-ის კონტროლი — Decision Log 2026-10-28, „Gemini სრულად იცვლება").
- Decision: **S16-1** (task-executor) ამოწმებს და აყენებს `langgraph`-ს (უახლესი stable) მხოლოდ `backend/.venv`-ში. **GO** — თუ ყველა: (1) ყოველ compiled პაკეტს (მოსალოდნელი: `ormsgpack`, `xxhash`, `orjson`, `zstandard`, …) აქვს cp314 manylinux x86_64 wheel (`pip download --only-binary=:all: --platform manylinux2014_x86_64` ან `manylinux_2_28_x86_64` `--python-version 3.14 --no-deps`), დანარჩენი pure-python; (2) არცერთი არსებული lock-ის pin არ იცვლება; (3) `pip check` სუფთა; (4) `pip-audit` 0; (5) offline smoke (2-node `StateGraph` + ციკლი) მუშაობს; (6) pytest უცვლელად 473. სხვა შემთხვევაში **NO-GO** — დაყენებული პაკეტები იშლება, requirements უცვლელია.
  - GO → `graph.py` node-ებს LangGraph-ის `StateGraph`-ით აწყობს: მხოლოდ wiring (`langgraph` import მხოლოდ `graph.py`-ში; `langchain_core`-ის message/tool/chat model ტიპები — არსად; checkpointer — არა; `recursion_limit` მხოლოდ დამცავი ბადეა, ჭერს ჩვენი მთვლელი აკონტროლებს). LangSmith tracing არასდროს: `LANGSMITH_*`/`LANGCHAIN_*` env არ ყენდება (ტესტებში conftest შლის).
  - NO-GO → იგივე node ფუნქციები (`preprocess`, `agent`, `tools`, `postprocess`; `state -> dict`) plain Python ციკლით (~20 ხაზი), იგივე routing ფუნქციები და იგივე ტესტები; მიზეზი — ამ ჩანაწერის ბოლოს და `PROGRESS.md` `## Blockers`-ში.
- ვარაუდი (/auto): GO-ზე LangGraph-ით ვაწყობთ, რადგან ეს მფლობელის ცხადი მოთხოვნაა (პრიორიტეტი #1) — ქვემოთ მოცემული რეკომენდაციის მიუხედავად. ორივე გზაზე node-ები ჩვეულებრივი ფუნქციებია, ამიტომ wiring-ის შეცვლა ერთი ფუნქციაა.
- **არქიტექტორის რეკომენდაცია (on merit): plain Python.** (1) LangGraph-ის არცერთი უნიკალური შესაძლებლობა (checkpoint/resume, streaming, interrupt, parallel fan-out) აქ არ გამოიყენება — 3-node-იანი ხაზოვანი ნაკადი ერთი შემოსაზღვრული ციკლით ერთ ეკრანზე იწერება; (2) ~12–16 ახალი პაკეტი (`langgraph`, `langgraph-checkpoint`/`-prebuilt`/`-sdk`, `langchain-core`, `langsmith`, `ormsgpack`, `xxhash`, `orjson`, `zstandard`, `requests` + `urllib3`/`charset-normalizer` (S14-7-ში ამოღებული), `requests-toolbelt`, `jsonpatch`, `jsonpointer`, `tenacity`…) — supply chain / pip-audit-ის ზედაპირი, import-ის მეხსიერება Render-ის 512 MB-ზე, Python 3.14-ის wheel-ების რისკი; (3) `langsmith` — telemetry SDK, env-ით ჩართვადი → კონფიგურაციის შეცდომით კლიენტების საუბრები მესამე მხარეს წავა; (4) ჭერს, deadline-ს და cache-ს მაინც ჩვენი კოდი აკონტროლებს. LangGraph გამართლდება, როცა გამოჩნდება: მრავალსაფეხურიანი/პარალელური workflow, შეჩერება-გაგრძელება (human approval), გრძელვადიანი state checkpointer-ით.
- Alternatives considered: LangGraph + LangChain chat models (cache-ის კონტროლი იკარგება — უარყოფილია); Claude Agent SDK (უარყოფილია 2026-10-28); ორივე wiring feature flag-ით (ორმაგი კოდი).
- როგორ შეიცვლება: მფლობელი წყვეტს (Open Questions). plain-ზე გადასვლა = `graph.py`-ის wiring + lock-იდან პაკეტების ამოღება (S14-7-ის მეთოდით).
- **S16-1-ის შედეგი: GO** — `langgraph 1.2.18`; venv-ში 17 ახალი პაკეტი (~25 MB; უდიდესი: langsmith 9.3, langchain_core 5.9, langgraph 3.5 MB), არსებული pin არ შეცვლილა; compiled (`orjson`, `ormsgpack`, `uuid_utils`, `xxhash`, `zstandard`) — cp314/abi3 manylinux2014 wheel-ები არსებობს; `pip check` ✅, pip-audit 0; ცივი import ~2.7 წმ (Windows). lock-ს დაემატა `requests`/`charset-normalizer`/`urllib3` (langsmith-ის runtime დამოკიდებულება; Stage 14-ში ამოღებული, venv-ში pip-audit-ის გამო იდგა). `langchain` / chat model პაკეტები — არ არის. გამოყენება: მხოლოდ `services/graph.py`; `LANGSMITH_*`/`LANGCHAIN_*` env production-ში არ უნდა იყოს დაყენებული (tracing მესამე მხარეს გზავნის საუბრებს) — S16-6 (tests) / S16-10 (docs).

### 2026-10-28 — Stage 16: გრაფის ფორმა, მოდულები, `run_turn` (webhook / `/test-chat` / სკრიპტი)
- Decision: მოდულები — `services/graph.py` (node-ები, routing, `run_turn`, `build_turn_prompt`, `TurnResult`, ჭერის კონსტანტები), `services/tools.py` (tool spec-ები + executor-ები), `services/replies.py` (შაბლონები + `clean_reply`; სუფთა), `services/memory.py` (ისტორიის ჭრა + summary). prompt-ის აგება — მხოლოდ `prompt.py`, provider-ის გამოძახება — მხოლოდ `llm.py`. `bot.py`-ში რჩება მხოლოდ საცნობარო ფოტოები (`_fetch_product_images`, `MAX_REF_IMAGES`, `product_ref_label`); `get_bot_reply`, `parse_reply`, `HANDOFF_TOKEN` იშლება (S16-8).
- `run_turn(shop, products, message, history=None, images=None, *, summary=None, provider=None, record_usage=True, refs_loader=None) -> TurnResult(text, handoff, route, calls, tools_used)` (`route` = `"template"` | `"agent"`, `calls` = ამ turn-ის `LLMResult`-ები). node-ები: `preprocess` (შაბლონი → END; ფოტოიან შეტყობინებაზე არასდროს) → `agent` (ზუსტად ერთი `llm.generate`) → `tools` → `agent` … → `postprocess` (`clean_reply`). LLM-ის შეცდომა / `TimeoutError` / not ready (`RuntimeError`) ვრცელდება — webhook-ის „ბოდიში…" fallback და `/test-chat`-ის 503/502 უცვლელია.
- webhook / `/test-chat`: `get_bot_reply` + `parse_reply`-ის ნაცვლად ერთი `run_turn` გამოძახება (`reply, handoff = result.text, result.handoff`); შემოწმებების რიგი (echo/dedup → წუთობრივი ლიმიტი → `track_bot_customer` → abuse cap → თვიური ლიმიტი → გამორთული ბოტი → ფოტოები → გრაფი), FA-12 და `_save_turn` — უცვლელი. ე.ი. over-limit/გამორთულ ბოტზე შაბლონი არ მუშაობს (ოპერატორის პასუხი, როგორც ახლა).
- შედარების სკრიპტი (`compare_providers.py`) — იგივე `run_turn` (`provider=`, `record_usage=False`, ლოკალური `refs_loader` `bot.product_ref_label`/`bot.MAX_REF_IMAGES`-ით) → production-ის გზას სტრუქტურულად ზომავს; Backlog Stage 15 nit (c) იხურება (S16-9, პარიტეტის ტესტით).
- Reason: ერთი შესასვლელი სამივე გამომძახებლისთვის; node-ები სუფთა ფუნქციებია და wiring-ისგან დამოუკიდებლად ტესტდება.
- Alternatives considered: `get_bot_reply`-ის გაფართოება (დაბრუნების ტიპი მაინც იცვლება → ტესტების იგივე ცვლილება; ყველაფერი ერთ ფაილში); `get_bot_reply` wrapper-ად (ორი გზა ერთი რამისთვის).
- ტესტები: `test_bot_reply.py`-ის `get_bot_reply`-ის დონის გარანტიები გადადის `test_graph.py`-ში (S16-6-ის mapping ცხრილით); ძველები იშლება მხოლოდ S16-8-ში ამ ცხრილის მიხედვით — სხვაგან ტესტის წაშლა აკრძალულია.

### 2026-10-28 — Stage 16: tool calling `llm.py`-ში — ორივე provider, cache, `tool_choice`, deadline, usage
- tool spec — provider-ნეიტრალური `{"name", "description", "parameters"}` (`tools.TOOL_SPECS`, სტატიკური, მაღაზიისგან დამოუკიდებელი; `llm.py` `tools.py`-ს არ იმპორტებს — spec-ს გამომძახებელი აწვდის). Claude: `tools=[{name, description, input_schema}]`; OpenAI Responses: `tools=[{"type": "function", name, description, parameters, "strict": true}]`.
- **cache:** Claude-ის prefix-ის რიგი tools → system → messages. tools სტატიკურია → L1-ის 1h breakpoint (`system[0]`) tools-ს და L1-ს ერთად ფარავს; ცალკე breakpoint tools-ზე **არ** არის; breakpoint-ები უცვლელია (1h → 5m → ისტორიის ბოლო ბლოკი; ≤3). tools-ის დამატება deploy-ზე ერთჯერადი cache miss-ია. turn-ის შიგნით 2–4 გამოძახება ისტორიის ბოლომდე cache-იდან კითხულობს; ბოლო turn + tool ნაბიჯები cache-ის გარეშეა (მე-4 breakpoint — Backlog, `llm_usage`-ის ციფრებით). OpenAI: tools prefix-ის ნაწილია, `prompt_cache_key` უცვლელი.
- `tool_choice`: გამოძახებები 1–3 — არ იგზავნება (= auto); მე-4 (ბოლო დაშვებული) — `none` (Claude `{"type": "none"}`, OpenAI `"none"`) → ტექსტური პასუხი გარანტირებულია. Claude-ზე `tool_choice`-ის ცვლილება message-ების cache-ს ამ ერთ (იშვიათ) გამოძახებაზე აუქმებს — მისაღებია.
- turn-ის შიგნითა transcript (`steps`, provider-ნეიტრალური: `{"text", "calls": [ToolCall], "results": [{"id", "content", "is_error"}]}`) ბოლო user turn-ის შემდეგ ემატება: Claude — assistant (`text` თუ არაცარიელია + `tool_use` ბლოკები) → user (`tool_result` ბლოკები; `is_error` მხოლოდ შეცდომაზე). OpenAI — `store=False`-ის გამო ყოველ გამოძახებაზე თავიდან იგზავნება: assistant ტექსტი (თუ არის) + `function_call` (`call_id`, `name`, **ორიგინალი** `arguments` სტრიქონი) + `function_call_output`; `previous_response_id` არ გამოიყენება (`store=True` სჭირდება — privacy). reasoning item-ები ხელახლა არ იგზავნება (Open Question).
- პასუხის დამუშავება: `LLMResult.tool_calls: list[ToolCall(id, name, arguments: dict | None, raw_arguments)]` — Claude `type == "tool_use"` ბლოკები, OpenAI `output[*].type == "function_call"`; არავალიდური JSON → `arguments=None` → tool-ის შეცდომის შედეგი (ციკლი გრძელდება). ტექსტი — როგორც ახლა (Claude `text` ბლოკები, refusal → `""`; OpenAI `output_text`). კლიენტს მიდის მხოლოდ ბოლო, tool call-ის გარეშე პასუხის ტექსტი; tool-იანი პასუხის „წინასიტყვაობა" — არა (გამონაკლისი: `request_human`).
- max tokens 800 ყოველ გამოძახებაზე, thinking disabled, sampling-ის გარეშე (უცვლელი).
- **deadline:** `graph.TURN_BUDGET_SECONDS = 45` მთელ turn-ზე → `llm.generate(..., deadline=)`: ყოველ მცდელობას per-request `timeout=min(LLM_TIMEOUT_SECONDS, დარჩენილი)`; <3 წმ დარჩენისას → `TimeoutError` გამოძახების გარეშე; ერთი retry მხოლოდ თუ ეტევა. ე.ი. ერთი შეტყობინების worst case ≈ 45 წმ (როგორც Stage 14-ის ერთი გამოძახების ჭერი), არა 4 × 45. `deadline=None` → Stage 14-ის ზუსტი ქცევა (არსებული ტესტები უცვლელი).
- **usage:** `llm_usage` — ერთი მწკრივი **ყოველ** LLM გამოძახებაზე (არსებული `record_usage`, სქემა უცვლელი; უმარტივესი), ჩაწერა ყოველი გამოძახებისთანავე (turn-ის შუაში შეცდომისასაც აღრიცხულია). შაბლონური პასუხი → 0 მწკრივი. turn-ის ჯამი — query-ით (`created_at`-ის სიახლოვე) ან `graph`-ის INFO ლოგით (`calls=N`).
- summary-სთვის ცალკე `llm.complete(system, text, shop_id, *, max_tokens, provider=None, deadline=None)` — tools/cache-ის გარეშე, იგივე retry.
- Alternatives considered: OpenAI `previous_response_id` (`store=True` — privacy-ის გადაწყვეტილების საწინააღმდეგო); turn-ის usage ერთ მწკრივში (სქემის ცვლილება); `tool_choice` `any`/`required` (იძულებითი ძებნა ყოველ შეტყობინებაზე); LangChain-ის tool/message ფორმატი.

### 2026-10-28 — Stage 16: tools — სქემები, executor-ები, tenant isolation; L2 უცვლელია
- 4 tool, სტატიკური ინგლისური აღწერებით; სქემები OpenAI strict-თან თავსებადი (`additionalProperties: false`, ყველა property `required`-ში): `search_products(query: string)`, `search_knowledge(query: string)`, `order_link()`, `request_human(reason ∈ customer_request | complaint | cannot_help | other)`.
- **tenant isolation:** `tools.execute(name, arguments, ToolContext(shop, products))` — shop და products **მხოლოდ graph state-იდან** (webhook-მა მაღაზია `entry.id`-ით იპოვა, პროდუქტები `shop_id`-ით წაიკითხა). tool-ის არგუმენტები untrusted: schema-ს გარეთ ნებისმიერი გასაღები (მაგ. `shop_id`), არასწორი ტიპი, ცარიელი / >200-სიმბოლოიანი `query` → შეცდომის შედეგი. executor-ები DB-ს და ქსელს არ მიმართავენ (ყველაფერი უკვე ჩატვირთულია) → სხვა tenant-ის მონაცემამდე სტრუქტურულად ვერ მიდიან და ახალ query-ს არ ქმნიან.
- `search_products` → `prompt.match_products` (იგივე keyword ქულა, რაც retrieval-ს; მხოლოდ დამთხვეული, ≤10). `search_knowledge` → `shops.knowledge`-ის **სრული** ტექსტი (L2-ში 20000 სიმბოლომდეა მოჭრილი — tool მის მიღმაც პოულობს), აბზაცებად (>800 → ფანჯრები), ტოპ-3 (Stage 17 — chunk-ებზე გადავა). `order_link` → `prompt.order_link_for(shop)`. `request_human` — **terminal**: graph მას არ „ასრულებს" და LLM-ს აღარ იძახებს; `handoff=True`, პასუხი = იმავე LLM პასუხის ტექსტი ან (ცარიელზე) ოპერატორის ფრაზა მაღაზიის ენაზე (`replies.handoff_reply`); იმავე პასუხის სხვა tool call-ები იგნორდება.
- ზომები: შედეგი ≤3000 სიმბოლო; turn-ზე შედეგების ჯამი ≤8000 (მერე „Result omitted…"); ერთ პასუხში ≤3 შესრულებული tool call (დანარჩენს „skipped" შეცდომა — ყოველ `tool_use`-ს `tool_result` უნდა ჰქონდეს); ცარიელი შედეგი — ცხადი ტექსტი („No products match …"). ჯამი: prompt ≤60K (`MAX_PROMPT_CHARS`) + spec-ები ≤3K + შედეგები ≤8K ≈ ≤71K სიმბოლო + სურათები (~24K ტოკენი) → პესიმისტურადაც <100K (5×-იანი ფასის ზღვარი).
- **L2 უცვლელია** (≤30 პროდუქტი — სრული მარაგი; >30 — რელევანტური სია ბოლო turn-ში; ცოდნა 20000-მდე). Reason: Stage 15-ის / `llm_usage`-ის ციფრები ჯერ არ არის; მარაგის L2-დან ამოღება ყოველ პროდუქტის შეკითხვას ≥2 გამოძახებად აქცევს (latency ×2, ბოლო turn ორჯერ) და 5m-იან L2 cache-ს (read 0.1×) კარგავს. tools დამატებითია: L1 ეუბნება მოდელს, რომ ძებნა მხოლოდ მაშინ, როცა საჭირო SHOP block-ში არ არის → ტიპურ შეტყობინებაზე 1 გამოძახება.
- გულწრფელი შეფასება: Stage 16-ში `order_link` L2-ს იმეორებს, `search_knowledge` ახალს მხოლოდ >20000-სიმბოლოიან ცოდნაზე იძლევა, `search_products` — >30 პროდუქტზე სხვა სიტყვებით ძებნისას. ისინი მფლობელის სიიდანაა და იაფია (spec-ები cached prefix-შია); რეალური ღირებულება Stage 17-ში ჩნდება. მთავარი სტრუქტურული მოგება — `request_human` (handoff აღარ არის ტექსტური ნიშანი) და tool-ის შედეგი, რომელსაც კლიენტი ვერ გააყალბებს (S14-11-ის სათაურისგან განსხვავებით).
- Alternatives considered: executor-ები DB query-ით (ზედმეტი query + tenant-ის ფილტრის რისკი); `shop_id` არგუმენტად (აკრძალულია); L2-დან მარაგის ამოღება (იხ. ზემოთ).
- როგორ შეიცვლება: Stage 17 — `search_knowledge` chunk-ებზე; L2-ის შემცირება — `llm_usage`-ის ციფრებით (Backlog).

### 2026-10-28 — Stage 16: preprocess — შაბლონური პასუხები LLM-ის გარეშე (`services/replies.py`)
- Decision: სამი intent — მისალმება, მადლობა, ოპერატორის მოთხოვნა — ka (მათ შორის ლათინური ქართული), en, ru ფრაზების ფიქსირებული სიით (ზუსტი სია — `PROGRESS.md` S16-3). ნორმალიზაცია: `casefold`, ყველა არა-`\w` სიმბოლო (პუნქტუაცია, emoji) → space, whitespace-ის შეკუმშვა. დამთხვევა **მხოლოდ მთლიან შეტყობინებაზე** (ტოლობა, არა substring) — „გამარჯობა, წითელი მაისური გაქვთ?" LLM-ს მიდის. ფოტოიან შეტყობინებაზე შაბლონი არასდროს.
- პასუხები (ka / en / ru): მისალმება „გამარჯობა! 😊 რით შემიძლია დაგეხმაროთ?" (L1-ის few-shot); მადლობა „არაფრის! 😊 კიდევ რით შემიძლია დაგეხმაროთ?"; ოპერატორი „ერთ წამში, ოპერატორი დაგიკავშირდებათ 🙏" (L1-ის არსებული ფრაზა) + `handoff=True` → `needs_attention`. ენა: მაღაზიის `bot_language` ∈ {ka, en, ru} → ის; `auto` (ან უცნობი) → დამთხვეული ფრაზის ენა.
- შაბლონური პასუხი ისტორიაში ჩვეულებრივ bot პასუხად ინახება; LLM-ის გამოძახება და `llm_usage` მწკრივი — 0; summary-ის ჭრა შაბლონურ turn-ზე არ ხდება (შემდეგ agent turn-ზე).
- Reason: მფლობელის მოთხოვნა (ტოკენების მინიმიზაცია); ეს შეტყობინებები ხშირია და პასუხი ფიქსირებულია.
- Alternatives considered: substring/regex დამთხვევა (გრძელ შეკითხვას „გადაყლაპავს"); LLM-ით intent-ის კლასიფიკაცია (თვითონ გამოძახებაა).
- ვარაუდი (/auto): ფრაზების სია და ტექსტები — არქიტექტორის; მფლობელის გადასახედი (Open Questions). შუა საუბარში მისალმებაზეც იგივე მისალმება ბრუნდება.

### 2026-10-28 — Stage 16: postprocess — markdown-ის გასუფთავება (`replies.clean_reply`)
- Decision (ზუსტი რიგი): (1) `[[WORD]]` სტილის ნიშნები (`\[\[[A-Z_]{2,30}\]\]`) იშლება — ძველი `[[HANDOFF]]`-ის ნარჩენი, handoff-ს **არ** რთავს (ერთადერთი წყარო — `request_human`/შაბლონი); (2) მხოლოდ code fence-იანი ხაზები იშლება, დარჩენილი backtick-ები იშლება; (3) `[label](https://url)` → `label: url` (ან `url`, თუ label = url); (4) ხაზის თავში `#`…`######` → იშლება; (5) `**x**` / `__x__` (არა URL-ის შიგნით) → `x`, დარჩენილი `**` → იშლება; (6) ხაზის თავში `- ` / `* ` → `• `; (7) ხაზების ბოლო space-ები, 3+ ცარიელი ხაზი → 1, strip. ერთი `*` / `_` ხელუხლებელია (გამრავლება, URL, SKU). „•"-იანი სიები, emoji და შესაკვეთი ბმული უცვლელია (ტესტით); idempotent. ცარიელი შედეგი → webhook-ის FA-12 fallback + handoff (უცვლელი).
- Reason: L1 markdown-ს კრძალავს, მაგრამ მოდელები მაინც წერენ — Messenger-ში `**` და `#` ლიტერალურად ჩანს.
- Alternatives considered: მხოლოდ L1-ის წესი (საიმედო არ არის); სრული markdown parser (dependency, ზედმეტი).

### 2026-10-28 — Stage 16: ისტორია ბლოკებად + summary (`services/memory.py`, migration 0026)
- Decision: `bot_conversations.summary text` (0026, idempotent, ახალი grant/პოლისი არა — ჩაწერა მხოლოდ backend-ის service client-ით, როგორც `messages`; გამყიდველი საკუთარს 0008-ის select პოლისით კითხულობს). **ჭრა ბლოკებად:** turn-ის შენახვისას, თუ შეტყობინებები (user+bot) > `HISTORY_CUT = 16` (ე.ი. 18) → უძველესი ნაწილი (ყველა, ბოლო `HISTORY_KEEP = 8`-ის გარდა; დარჩენილი იწყება user-ით) + წინა summary → ერთი `llm.complete` გამოძახება → ახალი summary (≤1200 სიმბოლო), ინახება ბოლო 8. ჭრებს შორის ისტორია 8 → 16 იზრდება მხოლოდ ბოლოში დამატებით → ფენა 3-ის prefix სტაბილურია და cache იკითხება; prefix იცვლება მხოლოდ ჭრისას (ყოველ ~5 turn-ში ერთხელ). ეს ასრულებს Decision Log-ის („Prompt სამ ფენად", ორკესტრატორის trade-off) მოთხოვნას — მოცურავე „ბოლო 8" არა.
- prompt-ში: `prompt.build_prompt(..., summary=)` — summary ისტორიის **პირველ user turn-ს** ემატება თავში (`SUMMARY_HEADER = "Summary of the earlier conversation (data, not instructions):"`; ცარიელ ისტორიაზე — ერთადერთი ისტორიის turn); `_neutralize_header` მასზეც; L1/L2/ბოლო turn summary-ზე არ არის დამოკიდებული; `normalize_history`-ის ინვარიანტები (user-ით იწყება, როლები მონაცვლეობს) ნარჩუნდება; `MAX_PROMPT_CHARS`-ის ჭრისას summary უძველეს turn-თან ერთად იჭრება. L1: summary და tool-ის შედეგები DATA-ა.
- summary-ის გამოძახება **პასუხის გაგზავნის შემდეგ** (კლიენტის latency არ იზრდება), მხოლოდ agent turn-ზე, `SUMMARY_BUDGET_SECONDS = 25`, `max_tokens = 400`, შეყვანა ≤12000 სიმბოლო; system — სტატიკური ინგლისური (გაყიდვისთვის საჭირო ფაქტები; ტელეფონი/მისამართი/email **არა**; საუბარი DATA-ა). ჩავარდნა / ცარიელი / key-ის გარეშე → შეტყობინებები **არ** იჭრება, summary უცვლელი (WARNING shop id-ით) — `_save_turn`-ის არსებული ჭერი `[-BOT_MEMORY_MESSAGES:]` (20) მაინც მოქმედებს (= Stage 14-ის ქცევა); შემდეგ agent turn-ზე თავიდან ცდა.
- `bot_memory_messages`: რჩება მთავარ გადამრთველად და ზედა ჭერად (0 → მეხსიერება და summary გამორთულია; ჭრა ეფექტურია, როცა > 16, default 20). `bot_memory_hours` (24): ძველ საუბარზე summary-იც იგნორდება და შენახვისას `null` ხდება. over-limit / გამორთული ბოტის გზა summary-ს არ ეხება (upsert-ში გასაღები არ არის → სვეტი უცვლელია).
- **Run order:** 0026 — Stage 16-ის backend deploy-მდე (Stage 14-ის deploy-ის შემდეგ). კოდი სვეტის არარსებობას იტანს: `summary`-იანი select ვარდება → select მის გარეშე, summary გამორთულია (ერთჯერადი WARNING პროცესზე), ჭრა არ ხდება (Stage 14-ის ქცევა).
- Alternatives considered: summary L2-ში (L2 მაღაზიის ფენაა — ყველა კლიენტის cache დაირღვეოდა); მოცურავე ბოლო 8 (ფენა 3-ის cache ყოველ turn-ზე ირღვევა); summary-ის გამოძახება პასუხამდე (latency); ცალკე ცხრილი (ზედმეტი).
- Privacy: summary არის უკვე შენახული საუბრის შეკუმშული ფორმა იმავე მწკრივში (იშლება მაღაზიის წაშლით და Data Deletion callback-ით, როგორც `messages`); privacy.html §6-ის ფორმულირება („საუბრები — ბოლო N შეტყობინება") — მფლობელის გადასახედი (Open Questions).

### 2026-10-28 — Stage 16: ლიმიტები, latency, ხარჯი
- LLM-ის გამოძახება ერთ შემოსულ შეტყობინებაზე: შაბლონი — 0; agent — **≤4** (`MAX_LLM_CALLS = 4` = 1 + `MAX_TOOL_ROUNDS = 3`; მე-4 იძულებით ტექსტურია) + summary — **≤1** მხოლოდ ჭრისას, პასუხის შემდეგ. ტესტით (`test_graph.py`, `test_webhook_memory.py`).
- latency: ტიპური შეტყობინება — 1 გამოძახება (როგორც ახლა); ძებნით — 2; worst case — turn-ის 45 წმ deadline (ერთი Stage 14-ის გამოძახების ჭერის ტოლი). Meta webhook-ს 200 დამუშავებამდე უბრუნდება (უცვლელი).
- ხარჯი: tool spec-ები cached prefix-შია (L1-თან ერთად); ფოტოიან turn-ზე ყოველი დამატებითი გამოძახება სურათებს ხელახლა აგზავნის (≤15 × ~1.6K ტოკენი) — Backlog / Stage 18 (2–3 საცნობარო ფოტო). გაზომვა — `llm_usage` (მწკრივი გამოძახებაზე) და შედარების სკრიპტის `calls`.

### 2026-10-29 — Stage 17: შენახვა — ერთი სვეტი `shops.knowledge_faq`; `knowledge_chunks` ცხრილი არ არის; PDF-ის ტექსტის ჭერი 20 000 → 50 000
- Context: ესკიზში იყო `knowledge_chunks(shop_id, ord, text)` ცხრილი. კოდში: `pdf_extract.MAX_CHARS = 20000` → `shops.knowledge` ≤20 000 სიმბოლოა და L2-ში მთლიანად ხვდება (clip 20000); webhook და `/test-chat` მაღაზიას `select("*")`-ით კითხულობენ → ცოდნა ყოველ შეტყობინებაზე უკვე მეხსიერებაშია; `tools._search_knowledge` (Stage 16) მას მეხსიერებაში ჭრის (აბზაცები / 800-იანი ფანჯრები), DB-ის და ქსელის გარეშე.
- Decision: ახალი ცხრილი **არა**. FAQ — ერთი nullable სვეტი `shops.knowledge_faq text` (0027). სრული ტექსტი რჩება `shops.knowledge`-ში, chunk-ები — მეხსიერებაში, ძებნის დროს (როგორც Stage 16). `pdf_extract.MAX_CHARS` 20 000 → **50 000**: ჭერის მიზეზი (prompt-ის დაცვა) FAQ-ით ქრება, ხოლო 50K პესიმისტურადაც (1 ტოკენი/სიმბოლო) FAQ-ის გენერაციის request-ს 100K ტოკენზე (5×-იანი ფასის ზღვარი) ბევრად ქვემოთ ტოვებს. `MAX_PAGES = 300` უცვლელი.
- Reason: ცხრილს დასჭირდებოდა RLS/grant-ები, ორ ცხრილში ჩაწერა (re-upload-ზე არაატომური ჩანაცვლება), webhook-ში დამატებითი query ან tool-ში DB-ის მიმართვა (Stage 16-ის ინვარიანტი „tool-ები DB-ს არ მიმართავს" დაირღვეოდა) — რეალური მოგების გარეშე: 50K-ის chunk-ება მეხსიერებაში მიკროწამებია, Postgres-side ძებნა კი ქართულზე (FTS ლექსიკონი არ აქვს) მაინც `simple` / ILIKE / trigram, ანუ იგივე keyword ძებნა იქნებოდა.
- Trade-off: `shops` მწკრივი ყოველ შეტყობინებაზე ≤50K სიმბოლოს ატარებს (ქართული UTF-8 ≈ ≤150 KB; ადრე ≤60 KB); admin-ის `select("*")` სიაც. Realistic Scale-ზე (ათეულობით მაღაზია) მისაღებია.
- Alternatives considered: `knowledge_chunks` + pg_trgm / FTS `simple`; FAQ ცალკე ცხრილში; ჭერის 20K-ზე დატოვება (მაშინ FAQ მხოლოდ L2-ს ამცირებს).
- ვარაუდი (/auto): მფლობელის „სრული ტექსტი ძებნისთვის" 20K-ზე დიდ დოკუმენტს გულისხმობს → 50K; ზუსტი რიცხვი — არქიტექტორის.
- როგორ შეიცვლება: ცხრილი / FTS / embeddings — თუ ცოდნა >~100K გახდება, keyword ძებნა არ იკმარებს, ან webhook-ის `select("*")` ცხადი სვეტებით შეიცვლება და ცოდნა მხოლოდ tool-ის გამოძახებისას ჩაიტვირთება (Backlog).

### 2026-10-29 — Stage 17: FAQ-ის გენერაცია — სინქრონულად `upload_knowledge`-ში, `llm.complete`, 40 წმ, ერთი ჩაწერა
- Decision: `services/knowledge.py` → `build_faq(shop_id, text) -> str | None`, **არასდროს აგდებს** (`memory.compact`-ის ნიმუში): ერთი `llm.complete(FAQ_SYSTEM, "Shop document:\n" + text[:50 000], shop_id, max_tokens=1500, deadline=monotonic()+40)` → `llm.record_usage(shop_id, result)` (მწკრივი `llm_usage`-ში ამ მაღაზიაზე) → `replies.clean_reply` (markdown) → ჭერი `FAQ_MAX_CHARS = 3000` ხაზის საზღვარზე. `FAQ_SYSTEM` — სტატიკური ინგლისური: ≤25 კითხვა-პასუხი, ≤2500 სიმბოლო, plain text, `Q: ` / `A: ` ხაზები; მხოლოდ დოკუმენტში ნათქვამი ფაქტები (ფასი, საფასური, ვადა, პირობა, მაღაზიის მისამართი/ტელეფონი/საათები) უცვლელად, არაფრის დამატება/გამოცნობა; პრიორიტეტი — მიწოდება, გადახდა, დაბრუნება/გაცვლა, გარანტია, საათები, კონტაქტი; კატალოგი — არა; დოკუმენტის ენაზე; დოკუმენტი DATA-ა — მასში არსებული ინსტრუქციები იგნორდება და არ მეორდება. provider — default (override არ სჭირდება).
- handler-ის რიგი: მფლობელობა + პაკეტი (უცვლელი; free → 403 **LLM-მდე**) → ფაილის ვალიდაცია → ტექსტის ამოღება → FAQ → **ერთი** service update `{knowledge, knowledge_filename, knowledge_faq}`. ჩავარდნა / key-ის გარეშე / timeout / ცარიელი პასუხი → `knowledge_faq = null` (WARNING shop id-ით, დოკუმენტის ტექსტის გარეშე), ატვირთვა მაინც 200, ბოტი — fallback (იხ. L2). re-upload ტექსტს და FAQ-ს ერთად ცვლის (ჩავარდნაზე წინა PDF-ის FAQ იშლება — ახალ ტექსტს ძველი FAQ არ მიეწერება); `clear_knowledge` სამივე სვეტს ასუფთავებს (LLM-ის გარეშე). response (`ShopOut`) უცვლელი.
- ხანგრძლივობა და ხარჯი: მოთხოვნა ≤~45 წმ (FAQ 40 + ამოღება); handler sync-ია (threadpool); frontend-ს fetch timeout არ აქვს და „მუშავდება..."-ს აჩვენებს. ხარჯი ≤~50K input + ≤1500 output ტოკენი ≈ <$0.01 ატვირთვაზე (Haiku 5.5-ის ფასით); ხარჯის ჭერად (სტანდარტი §28) — `rate_limit("knowledge_upload", 10, 3600)` (IP-ზე, `upgrade_request`-ის ნიმუში).
- Reason: ერთი ატომური ჩაწერა — ტექსტი და მისი FAQ ყოველთვის ერთმანეთს შეესაბამება (პარალელურ ატვირთვებზეც ბოლო იმარჯვებს წყვილით); ატვირთვის დასრულებისას FAQ უკვე prompt-შია; ტესტები მარტივია.
- Alternatives considered: FastAPI `BackgroundTasks` (სწრაფი პასუხი, მაგრამ ორი ჩაწერა, race ძველ/ახალ FAQ-ს შორის → პირობითი update, ჩავარდნა გამყიდველისთვის უხილავი, restart-ზე იკარგება — Accepted Risk #6); ცალკე „FAQ-ის გენერაცია" endpoint/ღილაკი (UI). Why rejected: სირთულე მოგების გარეშე ამ მასშტაბზე.
- Risk / ❓: `LLM_TIMEOUT_SECONDS ≤ 20` თითო მცდელობაზე — 1500 output ტოკენი Haiku-ზე ჩვეულებრივ ეტევა, დაუდასტურებელია (max_tokens-ზე ჭრილი პასუხი ხაზის საზღვარზე იჭრება; timeout → fallback); ~45 წმ-იანი მოთხოვნა Render-ზე/ბრაუზერში — პირველ რეალურ ატვირთვაზე. ხშირი ჩავარდნისას: per-attempt timeout-ის override `complete`-ში ან background (Backlog).
- ვარაუდი (/auto): ზომები (3000 სიმბოლო / 1500 ტოკენი / 40 წმ / 25 წყვილი), ლიმიტი 10/სთ, `Q:`/`A:` ფორმატი — არქიტექტორის; მფლობელმა გადახედოს.

### 2026-10-29 — Stage 17: L2 — FAQ ანაცვლებს 20000-იან clip-ს; FAQ-ის გარეშე — Stage 16-ის L2 ბაიტ-იდენტურად; `MAX_PROMPT_CHARS` რჩება 60 000
- Decision: `prompt.build_layer2`: `knowledge_faq` (str, strip-ის შემდეგ არაცარიელი; clip `KNOWLEDGE_FAQ_MAX_CHARS = 3000`) → სექცია `SHOP KNOWLEDGE (short FAQ of the shop's document; search_knowledge searches the full document)` + FAQ; სხვა შემთხვევაში (გასაღები არ არის / `None` / ცარიელი / whitespace) — **ზუსტად Stage 16-ის სექცია** (`SHOP KNOWLEDGE (from the shop's document)` + ცოდნის პირველი 20 000 სიმბოლო; კონსტანტა `KNOWLEDGE_CLIP_CHARS = 20000`). L2 ისევ მხოლოდ shop + products-ზეა დამოკიდებული → cache დეტერმინისტულია (FAQ მაღაზიის მწკრივშია და მხოლოდ ატვირთვისას იცვლება).
- L1 (მინიმალური): წესი 9 → „Answer only from the shop knowledge: the SHOP block, or the search_knowledge result when the detail is not in the SHOP block. If the answer is in neither, say that the operator will clarify it …" (ძველი „თუ SHOP block-ში არ არის → ოპერატორი" FAQ-ით ძებნას გამოტოვებინებდა); წესი 13 → „… the inventory and the shop knowledge (sometimes only a short FAQ of it) …". L1 ყველა მაღაზიისთვის ერთია → deploy-ზე ერთჯერადი cache miss; `TOOL_SPECS` უცვლელი.
- fallback-ის მიზეზი: არსებული ცოდნიანი მაღაზიები (FAQ ხელახალ ატვირთვამდე არ აქვთ) და FAQ-ის ჩავარდნა ქცევას არ კარგავს (= Stage 16); მათი L2/cache prefix და არსებული ტესტები უცვლელია. უფრო მოკლე fallback (მაგ. 4000) ჭერს შეამცირებდა, მაგრამ არსებულ მაღაზიებს L2-დან ცოდნის უმეტესობას ჩუმად ჩამოაჭრიდა.
- `MAX_PROMPT_CHARS = 60_000` **არ იცვლება**: უარესი შემთხვევა ისევ fallback-ია (20K); FAQ-იანი L2 ≤ fallback-იანისა (ტესტით). turn-ის ერთი request: ≤ `MAX_PROMPT_CHARS` + spec-ები (≤3K) + tool შედეგები (≤8K) + step-ების ტექსტი/არგუმენტები (≈≤2K) ≈ ≤73K სიმბოლო (S17-5-ის ტესტი 50K-იანი ცოდნით, ორივე provider) + სურათები — პესიმისტურადაც <100K ტოკენი ფოტოს გარეშე; ფოტოიან turn-ზე ზღვარი Stage 16-ის იგივეა.
- როგორ შეიცვლება: როცა ყველა ცოდნიან მაღაზიას FAQ ექნება (re-upload / backfill) → fallback ~4000-მდე და `MAX_PROMPT_CHARS` ~45K-მდე (Backlog).

### 2026-10-29 — Stage 17: `search_knowledge` — ხაზებით chunk-ები + ქართული „ფუძეები"; tenant isolation უცვლელი
- Decision (მინიმალური, მხოლოდ `tools.py`): აბზაცი (ცარიელი ხაზებით) ≤800 — უცვლელად; >800 → მისი ხაზებიდან (`\n`) ხარბად აწყობილი ≤800-იანი chunk-ები (ხაზი არ იჭრება); >800-იანი ერთი ხაზი → 800-იანი ფანჯრები (როგორც ახლა). ქულა — query-ის ტოკენების ფუძეებით: ტოკენი ≥6 სიმბოლო → პირველი `max(4, len − 2)` (მიწოდება / მიწოდების → „მიწოდე", გარანტია / გარანტიის → „გარანტ", თბილისში / თბილისი → „თბილის"). ტოპ-3 (ქულა, მერე პოზიცია), შედეგის ფორმატი და ≤3000 — უცვლელი. `search_products`, `prompt.query_tokens`, `match_products`, `TOOL_SPECS` — უცვლელი.
- Reason: FAQ-ის შემდეგ დეტალი ძირითადად ძებნით მოდის; pypdf გვერდს ერთ „აბზაცად" აბრუნებს (ერთი `\n`-ებით) → 800-იანი ფანჯარა ფაქტს შუაზე ჭრიდა; ქართული ბრუნვის ბოლოსართები substring დამთხვევას არღვევდა.
- tenant isolation: ცოდნა მხოლოდ `ToolContext.shop`-იდან (webhook-მა `entry.id`-ით ჩატვირთა), DB/ქსელი არა — უცვლელი.
- Alternatives considered: overlap-იანი ფანჯრები (დუბლირებული excerpt-ები ტოპ-3-ში); Postgres FTS / pg_trgm (ცხრილი/RPC — იხ. „შენახვა"); embeddings (vector DB, dependency, ხარჯი).
- ვარაუდი (/auto): ფუძის წესი უხეში ევრისტიკაა (მოკლე ფუძეზე false positive შესაძლოა) — რეალური ლოგებით გადაიხედება.

### 2026-10-29 — Stage 17: migration 0027, run order, frontend, შედარების სკრიპტი, privacy
- `0027_shops_knowledge_faq.sql`: `alter table public.shops add column if not exists knowledge_faq text` + comment; **grant/revoke/policy არ არის**: `authenticated`-ს `shops`-ზე ცხრილის დონის INSERT/UPDATE არ აქვს (0015/0022), column grant მხოლოდ `name, description, currency, bot_language`-ზეა → ახალი სვეტი გამყიდველისთვის ჩაუწერადია (შემოწმება: `has_column_privilege('authenticated','public.shops','knowledge_faq','UPDATE') = f`); სვეტის დონის revoke ცხრილის დონის grant-ს მაინც ვერ გადაფარავდა, ამიტომ არ იწერება. SELECT — საკუთარი მაღაზიისა (RLS; ექსპორტშიც ჩანს — FAQ-ის ნახვის ერთადერთი გზა UI-ის გარეშე). ჩაწერა მხოლოდ backend-ით (service client, მფლობელობის RLS შემოწმების შემდეგ — 0022-ის ნიმუში).
- Run order: 0027 → Stage 17-ის backend deploy (რეკომენდებული). კოდი სვეტის არარსებობას იტანს: ბოტი `select("*")`-ით FAQ-ს ვერ ხედავს → fallback; ატვირთვა/წაშლა — update-ის შეცდომა, რომლის ტექსტი `knowledge_faq`-ს შეიცავს (PostgREST PGRST204) → იგივე update ამ გასაღების გარეშე + ერთჯერადი WARNING პროცესზე; სხვა შეცდომა ვრცელდება (500, როგორც ახლა). ძველ backend-ს ახალი სვეტი არ აწუხებს.
- Frontend **არ იცვლება** (`ShopOut` უცვლელი; „მუშავდება..." უკვე ჩანს; 8 HTML / `dist` ხელუხლებელი); FAQ-ის სტატუსი / გადახედვა / ხელახლა გენერაცია UI-ში — Backlog.
- შედარების სკრიპტი: სადემონსტრაციო მაღაზიას (`compare_questions.json`) ემატება ხელით დაწერილი `knowledge_faq` (მხოლოდ მისივე `knowledge`-ის ფაქტები, LLM-ის გამოძახება სკრიპტში არა) → სკრიპტი production-ის FAQ-იან L2-ს ასახავს; `compare_providers.py` და პარიტეტის ტესტი უცვლელი (ორივე გზა ერთსა და იმავე shop dict-ს იღებს). სკრიპტს აგენტი არ უშვებს.
- Privacy: FAQ მხოლოდ გამყიდველის PDF-იდანაა (კლიენტის PII არა); provider-ს იგივე ტექსტი მიდის, რაც ისედაც L2-ში მიდიოდა (ახლა ≤50K ერთხელ, ატვირთვისას). B-14 (ცოდნა ფაქტობრივად საჯაროა) უცვლელია — FAQ იგივე ცოდნის ქვესიმრავლეა; 50K-იანი ჭერი ძებნით ამოღებად ზედაპირს ზრდის (გამყიდველის საკუთარი, საჯაროდ ნაგულისხმევი ტექსტი).

### 2026-10-29 — Stage 18: კლიენტის ფოტო — ვარიანტი (a) პირობითად: აღწერის ერთი გამოძახება → ტექსტური რანჟირება → ≤3 საცნობარო ფოტო
- Context (კოდიდან): კლიენტის ფოტოზე `graph.build_turn_prompt` რელევანტურ სიას (`select_relevant_products`: ≤30 პროდუქტზე — ყველა, >30-ზე — შეტყობინების keyword-ებით) `bot._fetch_product_images`-ს აწვდის, რომელიც `_sort_key`-ის რიგით პირველ ≤12 ფოტოიანს (`MAX_REF_IMAGES = 12`) ჩამოტვირთავს (4 worker, ≤8 წმ თითო, turn-ის 45 წმ-იანი deadline-ის შიგნით). ზოგად ფოტო-შეკითხვაზე („ეს გაქვთ?", „რა ღირს?" — სტოპ-სიტყვებია; ან ცარიელი) ეს 12 ფაქტობრივად შემთხვევითია, >30 კატალოგზე რელევანტური სიაც. სურათები ბოლო user turn-შია → ყოველ tool-რაუნდზე (≤4 გამოძახება) ხელახლა იგზავნება. Claude-ის ფორმულით (w·h/750 — docs, **დაუდასტურებელი**) frontend-ის 1280px ფოტო ≈ 1 600 ტოკენი → 1 + 12 ≈ 21K ტოკენი გამოძახებაზე.
- გულწრფელი შედარება (Haiku 5.5: $0.10 / $0.50 per MTok):
  - **(a)** ცალკე წინასწარი გამოძახება: კლიენტის ფოტო(ებ)ის აღწერა იმავე `vision.describe_images`-ით, რითაც პროდუქტის ფოტო აღიწერება → keyword დამთხვევა `image_description` + name/description/sku-სთან → ტოპ-3 კანდიდატის ფოტო. ფასი: +~2K input + ≤300 output ≈ +$0.0003 და +1 თანმიმდევრული გამოძახება (≈1.5–4 წმ, დაუდასტურებელი). მოგება: −9 სურათი **ყოველ** agent გამოძახებაზე (≈−14K ტოკენი ≈ −$0.0014), −9 ჩამოტვირთვა (3 რაუნდი → 1), ნაკლები prefill. ჯამი ფოტო-შეტყობინებაზე: 1 agent გამოძახებით ≈$0.0021 → ≈$0.0010; 2-ით ≈$0.0042 → ≈$0.0016. latency ≈ ნეიტრალური (+აღწერა, −ჩამოტვირთვები/prefill). მუშაობს >30 კატალოგზეც (აღწერა retrieval-ის query-შიც შედის).
  - **(b)** დამატებითი გამოძახების გარეშე, კანდიდატები შეტყობინების ტექსტით: ფოტო-შეტყობინებების უმეტესობაში ტექსტური სიგნალი არ არის → ≥4 ფოტოიან მაღაზიაზე კანდიდატები შემთხვევითია (ხარისხი ახლანდელზე უარესი — 12-ის ნაცვლად 3 შემთხვევითი). შემავსებელი ვარიანტი — ყველა `image_description` prompt-ში: L2 ≤30 × 500 სიმბოლოთი იბერება **ყოველ** შეტყობინებაზე (ტექსტურზეც), >30-ზე არ ეტევა.
- Decision: **(a), პირობითად.** აღწერის გამოძახება მხოლოდ თუ (1) კლიენტმა ფოტო გამოაგზავნა (ვალიდური, ≤`llm.MAX_IMAGE_BYTES`) **და** (2) მაღაზიის > `bot.MAX_REF_IMAGES` (3) პროდუქტს აქვს არაცარიელი `image_description` (`graph.wants_photo_description`). სხვა შემთხვევაში 0 დამატებითი გამოძახება: ≤3 აღწერიან/ფოტოიან მაღაზიაზე ყველა ფოტო ისედაც ეტევა, აღწერების გარეშე (backfill-მდე) შესადარებელი არაფერია → რანჟირება მხოლოდ შეტყობინების ტექსტით. ერთი გამოძახება ყველა (≤3) კლიენტის ფოტოზე ერთად. ბიუჯეტი `vision.PHOTO_BUDGET_SECONDS = 12`, `deadline=min(turn deadline, now + 12)` (45 წმ-იანი turn-ის შიგნით; agent-ს ≥~18 წმ რჩება). ჩავარდნა / timeout / ცარიელი / not ready → ტექსტური რანჟირება, turn გრძელდება (WARNING shop id + კლასი). აღწერა prompt-ში **არ** ჩადის (მოდელი თავად ხედავს ფოტოს) — მხოლოდ რანჟირებაში და (>30) retrieval-ის query-ში (`vision.query_text`). usage — ჩვეულებრივი `llm_usage` მწკრივი (`record_usage` flag-ით); `TurnResult.calls`-ში პირველია; agent-ის ჭერი (≤4) უცვლელი → turn ≤5 + summary ≤1.
- Reason: (b) ესკიზის მთავარ შემთხვევას (ზოგადი ფოტო-შეკითხვა ≥4 ფოტოიან მაღაზიაზე) ვერ ფარავს და prompt-ს ან ხარისხს აფუჭებს; (a) ხარჯს და request-ს ამცირებს, პირობა პატარა მაღაზიებს ზედმეტ გამოძახებას არ უხდის; კოდი — ერთი ფუნქცია, რომელიც ატვირთვასაც ემსახურება.
- Alternatives considered: (b); embeddings / vector search (dependency + ხარჯი + ცხრილი); `view_product_photos` tool (სურათი `tool_result`-ში — OpenAI Responses-ზე დაუდასტურებელი; +1 გამოძახება მაინც); აღწერები L2-ში; აღწერის გამოძახება ყოველ ფოტოზე (პატარა მაღაზიაზე ფუჭი).
- როგორ შეიცვლება: ზღვარი (>3), კანდიდატების რაოდენობა (3), ბიუჯეტი (12 წმ) — `llm_usage`-ით და რეალური საუბრებით; თუ რანჟირება ხშირად ცდება → 4–5 კანდიდატი ან embeddings.

### 2026-10-29 — Stage 18: პროდუქტის ფოტოს აღწერა — `create_product` / `update_product`-ში, სინქრონულად; `services/vision.py`; ერთი ფორმატი ორივე მხარეს
- Context: `POST /products/upload-image` პროდუქტამდე ეშვება (frontend: ჯერ ატვირთვა → URL → მერე `POST /products` / `PUT /products/{id}` `image_url`-ით, `ProductsTab.jsx` `onSubmit`) → upload-ის მომენტში აღწერის მისაბმელი მწკრივი ჯერ არ არსებობს.
- Decision: `upload-image` **არ იცვლება**. აღწერა იქმნება პროდუქტის ჩაწერისას: `create_product` — insert-ის (უცვლელი payload) შემდეგ, თუ `image_url` ამავე მაღაზიის საკუთარ საქაღალდეშია (`products._own_image_path(url, shop_id)`) → `vision.describe_product_image` → წარმატებაზე `vision.save_image_description` (ჩავარდნაზე არაფერი — default null); `update_product` — მხოლოდ თუ `image_url` შეიცვალა, RLS update-ის წარმატების (მფლობელობის) შემდეგ: ახალი საკუთარი ფოტო → აღწერა ან null; მოხსნილი / გარე / სხვა მაღაზიის ბილიკი → null **LLM-ის გარეშე** (ძველი აღწერა ახალ ფოტოს არ რჩება). სხვა ველის ცვლილება, import, delete — LLM არა. shop_id — სერვერის მწკრივიდან (`res.data[0]`), არა request-იდან.
- `services/vision.py` (LLM მხოლოდ `llm.py`-ით; DB-ს მხოლოდ `save_image_description` ეხება — client-ს გამომძახებელი აწვდის): `describe_images(shop_id, images, *, deadline, provider=None, record_usage=True) -> (str | None, LLMResult | None)` — **არასდროს აგდებს** (`knowledge.build_faq`-ის ნიმუში); `describe_product_image(shop_id, image_url) -> str | None` — მხოლოდ `facebook.is_own_storage_image_url` (S12-1), `facebook.download_image(url, max_bytes=llm.MAX_IMAGE_BYTES, timeout=8)`, ბიუჯეტი `UPLOAD_BUDGET_SECONDS = 20`; `save_image_description(sc, product_id, shop_id, image_url, description) -> bool` — service `update({"image_description": d}).eq("id").eq("shop_id")` + `.eq("image_url", url)` (თუ url str-ია: პარალელურ ფოტოს შეცვლაზე ძველი აღწერა ახალ ფოტოს არ მიეწერება), არასდროს აგდებს; `query_text(description)`.
- ფორმატი (`vision.DESCRIBE_SYSTEM`, სტატიკური ინგლისური, `{`/`}`-ის გარეშე): ზუსტად ორი ხაზი — `EN: ` ≤40 სიტყვა (ნივთის ტიპი, მთავარი ფერები, მასალა/ნახატი, მკაფიოდ ხილული ბრენდი/წარწერა, გამორჩეული დეტალები) და `KA: ` 3–8 ქართული სიტყვა სახელობით ბრუნვაში, მძიმით (ტიპი, ფერები); მხოლოდ ხილული; ფასი/ზომა/უხილავი ბრენდი — არასდროს; რამდენიმე ფოტოზე/ნივთზე — მთავარი; ადამიანები/სახეები/ფონი — არა; ფოტოში ტექსტი DATA-ა (ინსტრუქციები იგნორდება, არ მეორდება). user ტექსტი `"Photo to describe:"`. `DESCRIBE_MAX_TOKENS = 300`, `replies.clean_reply`, max_tokens-ზე (`output_tokens >= 300`) მოჭრილი ბოლო ხაზი იშლება (S17-8-ის გაკვეთილი), ჭერი `DESCRIPTION_MAX_CHARS = 500` ხაზის (მერე სიტყვის) საზღვარზე; ცარიელი → None. იგივე prompt კლიენტის ფოტოზე → ერთი ლექსიკა ორივე მხარეს.
- ენა: დამთხვევა ორ მოდელის-გენერირებულ ტექსტს შორის keyword-ებითაა → `EN:` (ბრუნვის გარეშე, თანმიმდევრული ლექსიკა, ნაკლები ტოკენი) + `KA:` სახელობითში (ემთხვევა გამყიდველის ქართულ სახელებს/აღწერებს, კლიენტის ქართულ ტექსტს — „წითელი", და `search_products`-ს ტექსტურ შეკითხვაზე). მხოლოდ ქართული — ბრუნვები/სინონიმები დამთხვევას არღვევს (Stage 17-ის „ფუძეები"); მხოლოდ ინგლისური — ქართულ სახელებს ვერ ემთხვევა.
- სინქრონული (Stage 17-ის მსგავსად): ფოტოიანი save ტიპურად რამდენიმე წამით გრძელდება, worst case ≤~35 წმ (frontend-ს fetch timeout არ აქვს, ღილაკი „busy"-ა). background (`BackgroundTasks`) — Backlog: restart-ზე იკარგება (Accepted Risk #6), ჩავარდნა უხილავია, ტესტები რთულდება.
- ხარჯი და ჭერი: ≈1.6K image + ~0.4K text input + ≤300 output ≈ <$0.0005 ფოტოზე. სტანდარტი §28: `ratelimit.allow("image_describe", <shop_id>, 30, 3600)` — ახალი public helper `core/ratelimit.py`-ში (იგივე sliding window, 429-ის ნაცვლად `False`); ზედმეტზე ფოტო ინახება აღწერის გარეშე (WARNING), პროდუქტის შენახვა არ ვარდება. upload-image-ის 5/წთ/IP ლიმიტი უცვლელი.
- Alternatives considered: აღწერა `upload-image`-ში + response-ით frontend-ისთვის დაბრუნება და create/update-ით გადაცემა (frontend-ის ცვლილება, `dist`; სვეტი გამყიდველისთვის ჩაწერადი უნდა გამხდარიყო); მეხსიერებაში `path → აღწერა` (restart, race); Storage-ის object metadata; DB trigger, რომელიც `image_url`-ის ცვლილებაზე აღწერას შლის (პირდაპირ PostgREST-ით `image_url`-ის შეცვლასაც დაფარავდა — ზედმეტია: ერთადერთი რეალური ჩამწერი backend-ია, პირდაპირი ცვლილება მხოლოდ საკუთარ ბოტს აზიანებს).
- ვარაუდი (/auto): ზომები და ზღვრები (500 სიმბოლო / 300 ტოკენი / 20 წმ / 12 წმ / 30 აღწერა/სთ / >3 / ≤3 კანდიდატი), ფორმატი `EN:`/`KA:` — არქიტექტორის; მფლობელმა გადახედოს.

### 2026-10-29 — Stage 18: `llm.complete(..., images=None)` — სურათიანი ერთჯერადი გამოძახება ორივე provider-ზე
- Decision: არსებულ `complete`-ს ემატება არჩევითი `images: list[(bytes, mime)] | None` (sibling ფუნქცია არა — იგივე readiness / retry / deadline / usage). ფილტრი — იგივე წესი, რაც `generate`-ში (`ALLOWED_IMAGE_MIMES`, `0 < len ≤ MAX_IMAGE_BYTES = 5 MB`, გამოტოვებაზე იგივე WARNING); საერთო private helper.
  - Claude: `{"model", "max_tokens", "thinking": {"type": "disabled"}, "system": [{"type": "text", "text": system}], "messages": [{"role": "user", "content": [{"type": "image", "source": {"type": "base64", "media_type": mime, "data": b64}}, …, {"type": "text", "text": text}]}]}` — სურათები ტექსტის წინ, `cache_control`/tools არა.
  - OpenAI Responses: `{"model", "input": [{"role": "developer", "content": [{"type": "input_text", "text": system}]}, {"role": "user", "content": [{"type": "input_image", "image_url": "data:<mime>;base64,<b64>", "detail": "low"}, …, {"type": "input_text", "text": text}]}], "max_output_tokens", "store": False}` — `prompt_cache_key` არა (როგორც `complete`-ში ახლა).
  - `images` None / `[]` → request **ბაიტ-იდენტურია** Stage 17-ისა (summary / FAQ-ის ტესტები უცვლელი).
- `detail: "low"` (OpenAI ~85 ტოკენი, 512px) — ტიპი/ფერი აღწერისთვის საკმარისია და ორივე მხარე (პროდუქტი/კლიენტი) ერთნაირად მუშავდება; Claude-ს detail პარამეტრი არ აქვს (≤1.15 MP-მდე თავად ამცირებს). ❓ წვრილი წარწერა/ბრენდი low-ზე შეიძლება დაიკარგოს — OpenAI default არ არის.

### 2026-10-29 — Stage 18: migration 0028, grants, tolerance, run order
- `0028_products_image_description.sql`: `alter table public.products add column if not exists image_description text` + comment; **grant/revoke/policy არ არის**: 0015-ით `authenticated`-ს `products`-ზე ცხრილის დონის INSERT/UPDATE ჩამორთმეულია, column UPDATE მხოლოდ `name, description, sku, price, quantity, image_url, is_active`-ზეა (მოგვიანებით `products`-ის grant არცერთ მიგრაციაში არ შეცვლილა) → ახალი სვეტი გამყიდველისთვის PostgREST-ით ჩაუწერადია (შემოწმება: `has_column_privilege('authenticated','public.products','image_description','UPDATE') = f`). SELECT — საკუთარი პროდუქტების (RLS 0001; ექსპორტშიც ჩანს). length check არ არის (ერთადერთი ჩამწერი backend-ია, ≤500). იდემპოტენტური; header/შემოწმება/ROLLBACK — 0027-ის სტილით. შემდეგი თავისუფალი ნომერი → `0029`.
- Tolerance (Stage 17-ის ნიმუში, nit-ის გათვალისწინებით): ბოტი სვეტს `select("*")`-ით კითხულობს → სვეტის გარეშე აღწერა უბრალოდ არ არის (`wants_photo_description` = False, რანჟირება ტექსტით). ჩაწერა: `save_image_description` → `APIError`, რომლის `code ∈ {PGRST204, 42703}` **და** message შეიცავს `image_description`-ს → module flag + ერთჯერადი WARNING („products.image_description missing (migration 0028 not applied) - product photo descriptions disabled") → ამ პროცესში შემდეგი create/update **LLM-ს აღარ იძახებს** (`vision.descriptions_enabled()`; Stage 17 nit: სვეტის გარეშე ფუჭი გამოძახება). სხვა შეცდომა → WARNING, `False` (პროდუქტი უკვე შენახულია — 500 არა).
- Run order: 0028 (SQL Editor, 0027-ის შემდეგ) → Stage 18-ის backend deploy (რეკომენდებული) → backfill სკრიპტი (მფლობელი, key-ის შემდეგ, `--dry-run` → მცირე `--limit` → დანარჩენი). ძველ backend-ს სვეტი არ აწუხებს.

### 2026-10-29 — Stage 18: prompt — აღწერა ძებნაში, რანჟირება, L1 წესი 12; L2 უცვლელი; `MAX_REF_IMAGES = 3`
- `prompt.match_products`: hay = name + description + sku + **image_description** (იგივე substring ქულა) → `search_products`, >30-ის retrieval და რანჟირება აღწერასაც ხედავს (`KA:` ხაზი ქართულ ტექსტურ შეკითხვასაც ეხმარება). `select_relevant_products(..., extra_query=None)` — ფოტოიან turn-ზე აღწერის query ემატება შეტყობინებას + ისტორიის ბოლო user turn-ს. ახალი `rank_products(products, query)` — `match_products`-ის დამთხვეულები ქულით, მერე დანარჩენი `_sort_key`-ით (დეტერმინისტული, input-ის რიგისგან დამოუკიდებელი; ტოლ ქულაზე — `_sort_key`). `build_prompt(..., photo_query=None)` — იგივე `extra_query` → საცნობარო ფოტოს label ყოველთვის რელევანტურ სიაშია (>30) ან L2-შია (≤30) — L1 წესი 3 („მხოლოდ SHOP block / პირველი სია") არ ირღვევა.
- `graph.build_turn_prompt(..., photo_description=None)`: `query = vision.query_text(photo_description)`; `relevant = select_relevant_products(ordered, message, history, extra_query=query)`; `ranked = rank_products(relevant, message + query)`; `refs_loader(ranked, images)` — ლოადერი (production `bot._fetch_product_images`, სკრიპტის `local_refs_loader`) ranked რიგით იღებს პირველ ≤`MAX_REF_IMAGES` ფოტოიანს (კონტრაქტი უცვლელი). ტექსტურ turn-ზე (`images` არ არის) ყველაფერი ბაიტ-იდენტურია.
- **L2 ბაიტ-იდენტური** (`_product_line` აღწერას არ აჩვენებს): ტექსტურ შეტყობინებაზე ზედმეტი ტოკენი არ არის, 5m cache არ ირღვევა, `MAX_PROMPT_CHARS` (60 000) worst case უცვლელია.
- L1 წესი 12 → „12. Photos. If the customer sends a photo, look at it carefully. Photos of up to three inventory products that look closest to it may follow it for comparison: use them for a precise visual match and name the specific product (name, price, stock). Not every product photo is shown, so if none of them matches, check the inventory by name and description (or use search_products) before you say the shop does not have it. If you cannot match it exactly, describe what you see and ask the customer to clarify, or offer an alternative from the inventory. Never invent a product that is not in the inventory." საცნობარო ბლოკის სათაური → „🛍️ Reference photos of up to 3 inventory products that look closest to the customer's photo follow (other products may have photos too). Compare them with the customer's photo. If one matches (the same or a very similar item), name exactly that product with its price and stock. If none matches, check the inventory by name and description, then describe what you see and ask the customer to clarify:". L1 ყველა მაღაზიისთვისაა → deploy-ზე ერთჯერადი cache miss; `TOOL_SPECS` უცვლელი.
- `bot.MAX_REF_IMAGES` 12 → **3**; `PRODUCT_REF_WORKERS = 4` (≥3 → ერთი ჩამოტვირთვის რაუნდი), `PRODUCT_REF_MAX_BYTES`, `INLINE_IMAGE_BUDGET`, `product_ref_label` — უცვლელი. Stage 16-ის nit („საცნობარო ფოტოების ჩამოტვირთვა turn-ის deadline-შია"): worst case 3 რაუნდი → 1 (≤15 წმ `download_image`-ის ზღვარით) + აღწერა ≤12 → agent-ს ≥18 წმ რჩება; ჩამოტვირთვა deadline-ს ჯერ კიდევ არ ემორჩილება → Backlog.
- ქულა უხეშია (substring: „red" ⊂ „colored"); `vision.query_text` შლის `EN`/`KA` ნიშნებს და ინგლისურ filler სიტყვებს (`the, and, with, of, a, an, in, on, for, is, it, its, this, that, has, shows, photo, image, item, product, visible`), რომ ყველა აღწერას თანაბრად არ დაემთხვეს. `prompt.query_tokens` / `_STOPWORDS` უცვლელი.

### 2026-10-29 — Stage 18: backfill, შედარების სკრიპტი, frontend, privacy
- **Backfill** (`backend/scripts/backfill_image_descriptions.py`, `python -m scripts.backfill_image_descriptions` `backend/`-იდან): **მხოლოდ მფლობელი უშვებს** (აგენტი — არასდროს, არც `--dry-run`/`--help`; შედარების სკრიპტის წესი). `--dry-run` (LLM / ჩამოტვირთვა / ჩაწერა არა: რაოდენობა + ხარჯის შეფასება), `--limit N` (default 20, ≤500), `--shop <uuid>`, `--delay S` (default 1.0). service client; კანდიდატი = `image_url` საკუთარ Storage-ში და იმავე `shop_id`-ის საქაღალდეში, `image_description` ცარიელი (idempotent — ხელახალი გაშვება აგრძელებს); `id`-ით დალაგებული; იგივე `vision.describe_product_image` + `save_image_description` (პირობითი `image_url`-ზე); usage → `llm_usage` თითო მაღაზიაზე. key-ის გარეშე (არა dry-run) → exit 2; სვეტი არ არის → exit 2 („გაუშვი 0028"). კლიენტის მონაცემს არ ეხება; ბეჭდავს მხოლოდ product id-ებს და ჯამებს. ხარჯი ≈ <$0.0005 ფოტოზე (200 ფოტო/მაღაზია-ს ჭერით ≤~$0.10 მაღაზიაზე).
- **შედარების სკრიპტი:** `compare_questions.json` — 4 ფოტოიან პროდუქტს ემატება 4 (არსებული სინთეტიკური asset-ების ხელახალი გამოყენებით: d02 ← tshirt, d06 ← jeans, d10 ← jacket, d14 ← sneakers) → 8 ფოტოიანი; ყველა 8-ს ხელით დაწერილი `image_description` (`EN:`/`KA:`, PNG-ზე რაც ჩანს), Q37–Q40-ს — `photo_description` (რასაც `describe_images` კლიენტის ფოტოზე იტყოდა). `--dry-run` / პარიტეტის ტესტი `photo_description`-ს JSON-იდან იღებს (LLM-ის გარეშე); რეალურ გაშვებაში `run_turn` აღწერას provider-ით აკეთებს (production-ის გზა, ხარჯი `calls`-ში ითვლება). გაზომვა: dry-run-ის `images N` ფოტო-შეკითხვაზე 1 + 3 (ძველი ჭერით იქნებოდა 1 + 8); რეალური ტოკენები — `compare_key.json`-ის `input_tokens` (README §9).
- **Frontend არ იცვლება** (`ProductOut`/API უცვლელი, 8 HTML / `dist` ხელუხლებელი); აღწერის ჩვენება / რედაქტირება / ხელახლა გენერაცია — Backlog.
- **Privacy:** კლიენტის ფოტო არ ინახება (როგორც ახლა); მისი აღწერა მხოლოდ turn-ის მეხსიერებაშია — prompt-ში, ისტორიაში (`[სურათი]` / ტექსტი, როგორც ახლა), DB-ში და ლოგში **არ** ხვდება; ფოტო იმავე provider-ს ერთხელ მეტად მიდის (OpenAI `store=False`). პროდუქტის ფოტოს აღწერა — გამყიდველის მონაცემი (`products` მწკრივი, RLS SELECT, ექსპორტი); prompt ადამიანების/სახეების აღწერას კრძალავს. privacy.html — ახალი კატეგორია არ არის (ფოტო AI provider-ს Stage 14-დან მიდის) → ცვლილება არ სჭირდება (Open Questions-ში შესამოწმებლად).

### 2026-10-29 — FAQ და ფოტოს აღწერა ფონზე (მფლობელის მოთხოვნა; Stage 17/18-ის „სინქრონულად" — superseded)
- Decision: `POST /shops/{id}/knowledge` ერთი ჩაწერით `{knowledge, knowledge_filename, knowledge_faq: null}` → response მაშინვე → FastAPI `BackgroundTasks` `_build_and_save_faq`: `build_faq` → FAQ იწერება მხოლოდ თუ `shops.knowledge` ჯერ ისევ **იგივე ტექსტია** (წაკითხვა → შედარება → ჩაწერა); 0027-ის გარეშე task არ იგეგმება. `POST/PUT /products`: response მაშინვე; ფოტოს აღწერა (download + LLM) ფონზე, ჩაწერა პირობითი `image_url`-ზე (უკვე იყო); 30/სთ/მაღაზია მოწმდება handler-ში (ლიმიტზე task არ იგეგმება); `update`-ზე ახალი საკუთარი ფოტოსას ძველი აღწერა მაშინვე სუფთავდება (ერთი ჩაწერა, LLM-ის გარეშე), რომ ძველი აღწერა ახალ ფოტოს არ ეკრას. სანამ შედეგი მზად არ არის — ძველი ქცევა (L2 — ცოდნის 20000-იანი ამონარიდი; რანჟირება აღწერის გარეშე).
- Reason: მფლობელის მოთხოვნა — ატვირთვა/შენახვა მაშინვე სრულდება (ადრე ≤~45 / ≤~35 წმ sync handler-ში, threadpool).
- Alternatives considered: `updated_at`-ით guard (shops-ის trigger სახელის ცვლილებაზეც ცვლის → ვალიდურ FAQ-ს დაბლოკავდა); `knowledge`-ით URL-ფილტრი (50K სიმბოლო არ ეტევა); queue/worker (ზედმეტი ინფრასტრუქტურა).
- Residual risk: წაკითხვიდან ჩაწერამდე მილიწამების ფანჯარა — მასში სხვა ტექსტის ატვირთვისას ძველი FAQ შეიძლება ჩაიწეროს; ახალი ატვირთვის საკუთარი task მას გადაწერს (თუ მისი LLM არ ჩავარდა). ფონური task-ი process-ის crash/restart-ზე იკარგება (Accepted Risk #6-ის მსგავსად) — FAQ/აღწერა null რჩება, ხელახალი ატვირთვა/შენახვა ან backfill აღადგენს.
- როგორ შეიცვლება: queue-ზე გადასვლისას (ROADMAP 🏗) task-ები იქ გადავა.

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
  - ⚠️ **გადაიხედება Stage 16-ში (2026-10-28; ჩანაწერის შეცვლა — მფლობელის გადაწყვეტილება):** ბოტს ემატება tools — 3 read-only (`search_products`, `search_knowledge`, `order_link` — მხოლოდ სერვერის state-ში უკვე ჩატვირთულ ამ მაღაზიის მონაცემზე, DB/ქსელის გარეშე, `shop_id` მოდელიდან არასდროს) + `request_human` (საუბარს `needs_attention`-ად ნიშნავს). prompt injection-ის worst case: ზედმეტი handoff (გამყიდველის ხმაური) ან ზედმეტი ძებნა (≤4 გამოძახება/შეტყობინება, 45 წმ). `search_knowledge` ცოდნის 20000-სიმბოლოიან clip-ს მიღმა ნაწილსაც აჩენს — B-14-ის ზედაპირს არ ზრდის (ცოდნა ისედაც საჯაროდ ითვლება).
  - ⚠️ **Stage 17 (2026-10-29; ჩანაწერის შეცვლა — მფლობელის გადაწყვეტილება):** ცოდნის FAQ LLM-ით იქმნება გამყიდველის PDF-იდან (`knowledge.FAQ_SYSTEM` დოკუმენტს DATA-დ თვლის); PDF-ში ჩადებულმა ინსტრუქციამ შეიძლება FAQ-ის შინაარსზე იმოქმედოს — მხოლოდ საკუთარ ბოტს აზიანებს, FAQ L2-ში DATA-ა (როგორც ცოდნა ახლა), tool-ებს/DB-ს არ ეხება. PDF-ის ტექსტის ჭერი 50K-მდე იზრდება (B-14-ის ზედაპირი — გამყიდველის საკუთარი ტექსტი).
  - ⚠️ **Stage 18 (2026-10-29; ჩანაწერის შეცვლა — მფლობელის გადაწყვეტილება):** ფოტოები LLM-ით აღიწერება (`vision.DESCRIBE_SYSTEM` ფოტოში ტექსტს DATA-დ თვლის). პროდუქტის ფოტოში ჩადებული წარწერა მხოლოდ საკუთარი ბოტის ძებნას/რანჟირებას ცვლის (აღწერა L2-ში არ ჩადის). კლიენტის ფოტოში ჩადებული წარწერის worst case — არასწორი ≤3 კანდიდატი (აღწერა prompt-ში **არ** ჩადის, tool-ებს/DB-ს არ ეხება); ფოტო თავად ისედაც მიდის მოდელს (Stage 14-დან). ხარჯი: ≤1 დამატებითი გამოძახება ფოტო-შეტყობინებაზე (>3 აღწერიან მაღაზიაზე), პროდუქტის აღწერა ≤30/სთ მაღაზიაზე.
- **#22 Gemini output structured schema-ს გარეშე** — პასუხი Messenger-ის თავისუფალი ტექსტია; ერთადერთი სტრუქტურა `[[HANDOFF]]` ნიშანია და `parse_reply` მას ამოწმებს; ცარიელ პასუხზე fallback + handoff (FA-12).
  - ⚠️ **გადაიხედება Stage 16-ში (2026-10-28):** `[[HANDOFF]]` და `parse_reply` იშლება; handoff = `request_human` tool call (სტრუქტურირებული, provider-ის tool API) ან ოპერატორის შაბლონი; ტექსტი `clean_reply`-ით სუფთავდება; FA-12 უცვლელი. ჩანაწერის განახლება — მფლობელი.
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
- **Stage 16 — LangGraph თუ plain Python** (მფლობელის გადაწყვეტილება S16-1-ის შედეგის შემდეგ): არქიტექტორი plain Python-ს გირჩევს (Decision Log 2026-10-28, Stage 16); GO-ზე ახლა LangGraph-ით იწყობა, რადგან ცხადად მოითხოვე.
- Stage 16, დასადასტურებელი პირველ რეალურ გამოძახებაზე (offline ვერ მოწმდება): OpenAI Responses `store=False` + `function_call` ხელახლა reasoning item-ების გარეშე → 400 ხომ არ არის gpt-6-luna-ზე (თუ კი — `include=["reasoning.encrypted_content"]` და reasoning item-ების გადაცემა); `strict: true` tool-ები gpt-6-luna-ზე; Claude Haiku 5.5-ზე `tool_choice: {"type": "none"}` და tools + 1h cache-ის ერთად მუშაობა (`cache_read_input_tokens` მე-2 გამოძახებაზე); რამდენ შეტყობინებაზე იძახებს მოდელი tool-ს „ზედმეტად" (`llm_usage`-ის მწკრივები / შეტყობინება).
- ვარაუდი (Stage 16): შაბლონების ფრაზები (ka/en/ru) და ტექსტები, summary-ის სიგრძე (≤1200) და ჭრის ზღვრები (16 → 8) — არქიტექტორის; მფლობელმა გადახედოს ტონს.
- privacy.html §6 („საუბრები — ბოლო N შეტყობინება"): Stage 16-დან იმავე მწკრივში ინახება ძველი შეტყობინებების მოკლე summary (PII-ის გარეშე ინსტრუქციით) — ფორმულირების განახლება საჭიროა? (frontend task, მფლობელის გადაწყვეტილება).
- ვარაუდი (Stage 17, /auto — მფლობელმა გადახედოს): PDF-ის ტექსტის ჭერი 50 000 (ადრე 20 000); FAQ ≤3000 სიმბოლო / 1500 output ტოკენი / 40 წმ / ≤25 წყვილი `Q:`/`A:` ფორმატით; ლიმიტი 10 ატვირთვა/სთ IP-ზე; FAQ-ის გარეშე ბოტი ძველ 20000-იან ცოდნას იყენებს; `knowledge_chunks` ცხრილი არ არის; ქართული „ფუძის" წესი ძებნაში (Decision Log 2026-10-29, Stage 17).
- ვარაუდი (Stage 18, /auto — მფლობელმა გადახედოს): ვარიანტი (a) პირობითად (აღწერის გამოძახება მხოლოდ >3 აღწერიან მაღაზიაზე); ≤3 საცნობარო ფოტო (ადრე 12); აღწერა `create`/`update`-ზე სინქრონულად (არა upload-image-ზე, არა background-ში); ფორმატი `EN:` + `KA:`, ≤500 სიმბოლო / 300 ტოკენი / 20 წმ (ატვირთვა) / 12 წმ (კლიენტის ფოტო); 30 აღწერა/სთ მაღაზიაზე; L2 უცვლელი; frontend უცვლელი (Decision Log 2026-10-29, Stage 18).
- Stage 18, დასადასტურებელი პირველ რეალურ გამოძახებაზე (offline ვერ მოწმდება): აღწერის ხარისხი და `KA:` ხაზის სისწორე (სახელობითი ბრუნვა); ერთ პროდუქტზე და კლიენტის ფოტოზე ერთი და იგივე ლექსიკა რამდენად თანმიმდევრულია (რანჟირების სიზუსტე — შედარების სკრიპტის Q37–Q40); ფოტოს ტოკენები (Claude w·h/750, OpenAI `detail: low` ≈85) და აღწერის გამოძახების latency; 300 ტოკენი OpenAI-ზე reasoning-ით ეტევა თუ არა; ფოტოიანი პროდუქტის შენახვის ხანგრძლივობა Render-ზე; privacy.html-ის ფორმულირება ფოტოს AI-დამუშავებაზე საკმარისია?
- Stage 17, დასადასტურებელი პირველ რეალურ ატვირთვაზე (offline ვერ მოწმდება): FAQ-ის ხარისხი ქართულ დოკუმენტზე (ფაქტები უცვლელად, არაფერი მოგონილი); 1500 ტოკენი 20 წმ-იან მცდელობაში ეტევა თუ არა; ~45 წმ-იანი მოთხოვნა Render-ზე; არსებული ცოდნიანი მაღაზიები — PDF-ის ხელახალი ატვირთვა თუ backfill სკრიპტი (Backlog)?
