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
6. [API — 51 endpoint](#6-api--51-endpoint)
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
              │    (ბოლო 8 + summary)│
              └──────────┬──────────┘
                         ▼
              ┌─────────────────────────┐
              │ ბოტის გრაფი (LangGraph)  │
              │ შაბლონი (LLM-ის გარეშე)  │
              │  → agent ⇄ tools         │
              │  → გასუფთავება           │
              └──────────┬──────────────┘
                         ▼
                   ┌───────────────────┐
                   │  Claude / OpenAI  │  ← ქართული / English / Русский
                   └────┬─────────────┘
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
| **Backend** | FastAPI (Python 3.14, CI 3.14.3), uvicorn |
| **DB / Auth / Storage** | Supabase — Postgres + Row Level Security + Auth + Storage |
| **Frontend** | React 19 + Vite (**MPA**, არა SPA) — 8 გვერდი |
| **AI** | Anthropic Claude (`claude-haiku-5-5`, default) ან OpenAI (`gpt-6-luna`) — `LLM_PROVIDER`-ით; მოდელები `CLAUDE_MODEL` / `OPENAI_MODEL`-ით იცვლება |
| **ბოტის გრაფი** | LangGraph (`langgraph>=1.2`) — **მხოლოდ wiring** (node-ები და გადასვლები). LLM-ს ყოველთვის `services/llm.py` იძახებს; LangChain-ის chat model-ები არ გამოიყენება |
| **არხები** | Facebook Messenger Platform · Instagram Messaging (Graph `v21.0`) |
| **ჰოსტინგი** | Render (Starter $7/თვე — cold-start გამორთულია) |
| **დომენი** | `chatassist.ge` (DNS + SSL) |

⚠️ **Render-ზე Node არ არის** — ამიტომ `frontend/dist/` **ჩადის git-ში**. `/panel` ისერვება მხოლოდ `frontend/dist`-იდან (fallback არ არის; dist-ის გარეშე 404 — გაუშვი `npm run build`).
build-ს ლოკალურად აკეთებ (`npm run build`) და commit-ავ.

---

## 4. პროექტის სტრუქტურა

```
.
├── backend/
│   ├── scripts/                 ⚠️ მხოლოდ მფლობელი უშვებს (რეალური API + ხარჯი)
│   │   ├── compare_providers.py    Claude vs OpenAI ბრმა შედარება (Stage 15)
│   │   ├── compare_questions.json  ფიქტიური მაღაზია + 40 შეკითხვა
│   │   ├── compare_assets/         სინთეტიკური დემო-ფოტოები
│   │   └── backfill_image_descriptions.py  არსებული პროდუქტის ფოტოების აღწერა (Stage 18)
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
│       │   └── admin.py         მფლობელის პანელი (მხოლოდ ADMIN_USER_IDS)
│       ├── core/
│       │   ├── security.py      Supabase JWT → CurrentAuth (RLS-იანი კლიენტი, `claims`); ES256/RS256 — ლოკალურად (jwt_verify), სხვა — ქსელური get_user; ადმინი ყოველთვის ქსელითაც
│       │   ├── jwt_verify.py    ლოკალური JWT შემოწმება PyJWT + JWKS-ით (Stage 22); ვერ წყდება → None → get_user
│       │   ├── supabase_client.py  anon (publishable key) / service (secret key) კლიენტები
│       │   ├── db.py            Postgres შეცდომების → HTTP კოდები · `fetch_all` — სრული სია 1000-მწკრივიანი ჭერის გვერდებით გავლით (Stage 22)
│       │   ├── crypto.py        Fernet — page token-ის შიფვრა
│       │   ├── ratelimit.py     in-memory per-IP sliding window
│       │   └── tiers.py         პაკეტები, ლიმიტები, ფასები
│       ├── models/              Pydantic სქემები (shop, product, order, chat)
│       └── services/
│           ├── graph.py         ბოტის გრაფი (LangGraph): preprocess → agent ⇄ tools → postprocess · `run_turn`
│           ├── tools.py         4 tool: search_products · search_knowledge · order_link · request_human
│           ├── replies.py       შაბლონური პასუხები (მისალმება/მადლობა/ოპერატორი) + markdown-ის გასუფთავება
│           ├── memory.py        ისტორიის შეკუმშვა: >16 შეტყობინება → ბოლო 8 + summary
│           ├── product_search.py  `search_products` დიდ კატალოგზე (≥ `BOT_DB_SEARCH_MIN_PRODUCTS`) — RPC 0040; RPC-ის გარეშე → მეხსიერების ძებნა (Stage 22)
│           ├── admin_audit.py   ადმინის მოქმედებების audit log (`admin_audit_log`, 0041; append-only, PII-ის გარეშე, best-effort) (Stage 23)
│           ├── fb_selection.py  Facebook-გვერდის არჩევის ერთჯერადი token (Fernet + HKDF, 10 წთ, ბაზაში არაფერი) (Stage 23)
│           ├── bot.py           საცნობარო ფოტოები graph-ისთვის (პროდუქტის სურათები)
│           ├── vision.py        ფოტო → ტექსტური აღწერა (≤500 სიმბოლო, EN+KA; პროდუქტის და კლიენტის ფოტო)
│           ├── prompt.py        სამფენიანი prompt (L1 საერთო წესები · L2 მაღაზია · L3 summary + საუბარი)
│           ├── llm.py           Claude Messages API / OpenAI Responses API · retry · usage → `llm_usage`
│           ├── facebook.py      Graph API · Send API · SSRF-დაცული download_image
│           ├── import_products.py  Excel/CSV პარსერი (all-or-nothing)
│           ├── knowledge.py     ცოდნის FAQ: PDF-ის ტექსტიდან ერთი LLM გამოძახებით (≤3000 სიმბოლო, არასდროს აგდებს შეცდომას)
│           └── pdf_extract.py   PDF → ტექსტი (ბოტის ცოდნა, ≤50 000 სიმბოლო)
│
├── frontend/                    React + Vite (MPA)
│   ├── *.html                   8 entry: landing, index, admin, order, reset,
│   │                            privacy, terms, delete-data
│   ├── src/
│   │   ├── panel/               გამყიდვლის პანელი (Dashboard, Products, Orders, Bot)
│   │   ├── admin/               ადმინ-პანელი
│   │   ├── order/               საჯარო შესაკვეთი ფორმა
│   │   ├── reset/               პაროლის აღდგენა
│   │   │                        (Stage 23: panel/FbPagePicker.jsx — გვერდის არჩევა; admin/MfaGate.jsx — ადმინის MFA)
│   │   └── lib/                 api.js · csv.js · adminMfa.js (საერთო)
│   ├── public/                  config.js · favicon · sample-products.{csv,xlsx}
│   └── dist/                    ⚠️ build-ის შედეგი — ჩადის git-ში
│
├── supabase/migrations/         41 SQL მიგრაცია (ცხრილები, RLS, RPC, grants)
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
| **#1** | საუბრის მეხსიერება | 24 საათი (`BOT_MEMORY_*`); ისტორია 16 შეტყობინებამდე იზრდება, მერე ძველი ნაწილი summary-ად იკუმშება და ბოლო 8 რჩება (იხ. ქვემოთ) |
| **#2** | გაძლიერებული prompt | პერსონა, დაზუსტება, upsell, handoff-ის წესები |
| **#3** | ჭკვიანი პროდუქტ-ძებნა | ≤30 პროდუქტი → ყველა prompt-ში; >30 → keyword-match, top-30; დამატებით agent-ს აქვს `search_products` tool |
| **#4** | ოპერატორზე გადართვა | agent იძახებს `request_human` tool-ს (ძველი `[[HANDOFF]]` ნიშანი აღარ არსებობს) → საუბარი პანელში „ყურადღება სჭირდება"-დ ინიშნება |
| **#5** | სურათის გაგება | კლიენტი ფოტოს აგზავნის → LLM multimodal → მარაგს ადარებს |
| — | ვიზუალური ამოცნობა | პროდუქტების ფოტოებს ადარებს და კონკრეტულს ცნობს (იხ. „ფოტოს ამოცნობა", Stage 18) |
| **#7** | ანალიტიკა | საუბრების რაოდ., top-terms, ბოლო შეკითხვები |
| — | მრავალენოვნება | ქართული / English / Русский — ავტო ან ხელით |
| — | შესაკვეთი ლინკი | `order.html?shop=<id>` — ბოტი თვითონ აძლევს |

**ჩარჩო:** `graph.run_turn(shop, products, message, history, images, summary=...)` —
[backend/app/services/graph.py](backend/app/services/graph.py) +
[tools.py](backend/app/services/tools.py) · [replies.py](backend/app/services/replies.py) ·
[memory.py](backend/app/services/memory.py) · [prompt.py](backend/app/services/prompt.py) ·
[llm.py](backend/app/services/llm.py). webhook და `/test-chat` ორივე ამ ერთ გზას იყენებს
(ძველი `get_bot_reply` / `[[HANDOFF]]` პარსერი წაშლილია).

**ბოტის გრაფი** (ერთი შემოსული შეტყობინება = ერთი turn):
1. **preprocess** — შაბლონური პასუხი LLM-ის გარეშე (მისალმება / მადლობა / ოპერატორის მოთხოვნა). ფოტოიან შეტყობინებაზე არასდროს.
2. **agent ⇄ tools** — LLM-ის გამოძახება ოთხი tool-ით: `search_products` (პროდუქტების ძებნა), `search_knowledge` (PDF-ცოდნაში ძებნა), `order_link` (შესაკვეთი ლინკი), `request_human` (ოპერატორზე გადართვა — ამთავრებს turn-ს). ჭერი: **≤4 LLM გამოძახება** (≤3 tool რაუნდი, რაუნდში ≤3 call) და **45 წმ** მთელ turn-ზე; tool შედეგების ჯამი ≤8000 სიმბოლო. შეცდომა/timeout ვრცელდება და webhook-ის fallback პასუხს აგზავნის.
3. **postprocess** — markdown-ის გასუფთავება (სათაურები, `**bold**`, ბულეტები, ლინკები); ცარიელი პასუხი ცარიელი რჩება.

LangGraph გამოიყენება **მხოლოდ wiring-ად** (node-ები, გადასვლები). ჭერებს, deadline-ს და usage-ს ჩვენი კოდი აკონტროლებს; checkpointer არ არის; LLM-ს ყოველთვის `llm.py` იძახებს.

⚠️ **Production-ში `LANGSMITH_TRACING`, `LANGCHAIN_TRACING_V2` და `LANGSMITH_API_KEY` (ზოგადად `LANGSMITH_*` / `LANGCHAIN_*`) არასდროს დააყენო** — tracing საუბრებს (კლიენტების შეტყობინებებს) მესამე მხარეს გაუგზავნიდა. ტესტებში conftest ამ ცვლადებს შლის.

**მეხსიერება და summary:** ისტორია 16 შეტყობინებამდე მხოლოდ იზრდება (prompt-ის cache-ის პრეფიქსი სტაბილურია). გადაჭარბებისას — **პასუხის გაგზავნის შემდეგ** — `memory.compact` ძველ ნაწილს ერთ მოკლე summary-ად (≤1200 სიმბოლო, პირადი მონაცემების გარეშე) აქცევს და მხოლოდ ბოლო 8 შეტყობინება რჩება. summary ინახება `bot_conversations.summary`-ში (მიგრაცია `0026`) და შემდეგ პასუხებში ისტორიის წინ ემატება prompt-ში. შეკუმშვა ხდება მხოლოდ agent turn-ზე (არა შაბლონზე); ჩავარდნისას შეტყობინებები უცვლელი რჩება, ლოგში WARNING (მხოლოდ shop id) და შემდეგ turn-ზე თავიდან ცდის. `0026`-ის გარეშე backend მუშაობს: summary გამორთულია, ჭრა არ ხდება, ლოგში ერთი WARNING.

**სამი ფენა prompt-ში** (cache-ის გამო სტაბილური ნაწილი წინ დგას):
- **L1** — ინგლისურად დაწერილი საერთო წესები, ყველა მაღაზიისთვის იდენტური (Claude cache 1 სთ)
- **L2** — მაღაზიის სტაბილური ბლოკი: სახელი, აღწერა, ვალუტა, ენის წესი, შეკვეთის ლინკი, ცოდნის FAQ (ან FAQ-ს გარეშე — ცოდნის პირველი 20 000 სიმბოლო), მარაგი (≤30 პროდუქტი სრულად) (cache 5 წთ)
- **L3** — საუბრის ისტორია + კლიენტის ბოლო შეტყობინება (ავტომატური cache)

**PDF-ცოდნა და FAQ (Stage 17):** PDF-ის ატვირთვისას ტექსტი (≤50 000 სიმბოლო) ინახება სრულად და response მაშინვე ბრუნდება; მოკლე FAQ (≤3000 სიმბოლო, `shops.knowledge_faq`, მიგრაცია `0027`) ერთი LLM გამოძახებით **ფონში, response-ის შემდეგ** იქმნება და, როგორც წესი, დაახლოებით ერთ წუთში მზადაა. მანამდე ბოტი ძველებურად მუშაობს. FAQ ინახება მხოლოდ თუ მაღაზიის ცოდნა ჯერ ისევ იგივე ტექსტია (ამასობაში ხელახალი ატვირთვა ან წაშლა ძველ FAQ-ს არ გადააწერს). prompt-ში (L2) FAQ ხვდება; სრულ ტექსტში `search_knowledge` ეძებს (ხაზებად დაყოფილი ნაწყვეტები, ქართული ფუძეებით შედარება). თუ FAQ ვერ შეიქმნა (LLM-ის შეცდომა ან key-ის უქონლობა), ატვირთვა მაინც ინახება, FAQ ცარიელია და prompt-ში ძველებურად ცოდნის პირველი 20 000 სიმბოლო ემატება. ცოდნის წაშლა FAQ-საც შლის. **არსებული მაღაზიები FAQ-ს მხოლოდ PDF-ის ხელახალი ატვირთვის შემდეგ იღებენ.** `0027`-ის გარეშე backend მუშაობს: FAQ გამორთულია, ატვირთვა ინახება, ლოგში ერთი WARNING.

**ფოტოს ამოცნობა (Stage 18):**
- **პროდუქტის ფოტო → ტექსტი.** პროდუქტის შექმნისას/განახლებისას (`POST /products`, `PUT /products/{id}`), თუ ფოტო მაღაზიის საკუთარ Storage საქაღალდეშია, `vision.py` ერთხელ აღწერს მას (≤500 სიმბოლო, ინგლისურად + ქართულად) და აღწერა ინახება `products.image_description`-ში (მიგრაცია `0028`). აღწერა **ფონში, response-ის შემდეგ** იქმნება (save მაშინვე სრულდება) და, როგორც წესი, დაახლოებით ერთ წუთში მზადაა; მანამდე ბოტი ძველებურად მუშაობს (ტექსტური რანჟირება). ჩაწერა მხოლოდ მაშინ ხდება, თუ პროდუქტს ჯერ ისევ იგივე ფოტო აქვს. ლიმიტი — **30 აღწერა/სთ მაღაზიაზე** (მოწმდება save-ისას). ჩავარდნისას ან ლიმიტზე პროდუქტი მაინც ინახება, აღწერა `null` რჩება; ფოტოს მოხსნა ან შეცვლა ძველ აღწერას მაშინვე ასუფთავებს. გარე URL-ებს არ აღწერს.
- **კლიენტის ფოტო.** აღწერის წინა გამოძახება (+1 LLM call, 12 წმ ბიუჯეტი 45-წამიანი turn-ის შიგნით) ხდება **მხოლოდ** თუ მაღაზიას >3 აღწერიანი პროდუქტი აქვს; ნაკლებზე ყველა საცნობარო ფოტო ისედაც ეტევა. კლიენტის ფოტოს აღწერა **არ ინახება და ლოგში არ იწერება**. აღწერით `prompt.rank_products` ალაგებს პროდუქტებს და LLM-ს ეგზავნება **≤3** ყველაზე მსგავსი საცნობარო ფოტო (ადრე 12). აღწერის ჩავარდნისას — ტექსტური რანჟირება, როგორც ადრე.
- `0028`-ის გარეშე backend მუშაობს: აღწერები გამორთულია, ლოგში ერთი WARNING. არსებული ფოტოები აღწერას იღებენ backfill სკრიპტით (§9).

`llm.py` იძახებს არჩეულ provider-ს (Claude Messages API / OpenAI Responses API), SDK-ის retry გამორთულია, აქვს საკუთარი ერთი retry (ჯამი ≤45 წმ) და ყოველი გამოძახების usage-ს (ტოკენები, cache read/write) წერს `llm_usage`-ში.

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
- **abuse-ჭერი:** ერთი კლიენტი დღეში მაქს. 100 შეტყობინება (უფასოზე 30) (loop-ის დაცვა)
- უფასოზე დაბრუნებისას **მონაცემი არ იშლება** — ზედმეტ მაღაზიებზე ბოტი უბრალოდ
  ითიშება და upgrade-ზე ავტომატურად ბრუნდება

გადახდა ჯერ **ხელით** — გამყიდველი აგზავნის მოთხოვნას, ადმინი ადასტურებს
(`upgrade_requests`). დეტალები: [MONETIZATION.md](MONETIZATION.md).

### 5.5 ადმინ-პანელი

`/panel/admin.html` — ხელმისაწვდომია **მხოლოდ** `ADMIN_USER_IDS`-ისთვის.

მაღაზიები · გამყიდვლები · შეკვეთები · MRR · ზრდის გრაფიკი · პაკეტის მოთხოვნების
დამუშავება · CSV ექსპორტი · ბოტის kill-switch · აღდგენის ინსტრუმენტი (ბმული
გამყიდველს ელფოსტით მიდის).

Stage 23-იდან შესასვლელად საჭიროა **ორფაქტორიანი კოდი (TOTP)**; პირველად admin.html-ზე
ჩნდება „ჩართვა" (QR → ავთენტიფიკატორის აპი). ადმინის მოქმედებები იწერება `admin_audit_log`-ში.
rollout-ის თანმიმდევრობა და საგანგებო ბერკეტი — §7 და §8.

### 5.6 არხები

| არხი | მდგომარეობა |
|---|---|
| **Facebook Messenger** | ✅ სრულად მუშაობს (dev-რეჟიმში testers-ზე) |
| **Instagram Direct** | ✅ კოდი მზადაა · ⏳ Live-რეჟიმს ელოდება |

ორივე იმავე `graph.run_turn`-ს იყენებს — ბოტის ლოგიკა 100% reuse-დება.
webhook `object` ველით არჩევს (`page` / `instagram`).

---

## 6. API — 51 endpoint

ავტორიზაცია: `Authorization: Bearer <supabase_access_token>`.
DB-ოპერაციები სრულდება **მომხმარებლის JWT-ით** → RLS უზრუნველყოფს იზოლაციას.
სრული ინტერაქტიული დოკუმენტაცია: `/docs` (OpenAPI; `/docs`, `/redoc`, `/openapi.json` მხოლოდ dev-ში — production-ში გამორთულია)

**Stage 21 — header-ები:** ყველა პასუხს აქვს `Content-Security-Policy` (`default-src 'self'; script-src 'self'; …`, `connect-src` — `'self'` + Supabase), `Cross-Origin-Resource-Policy: same-origin`, `Cache-Control: no-store` (თუ route-ს/static-ს საკუთარი არ აქვს; `/panel/assets/*` — immutable). `CSP_REPORT_ONLY=true` → იგივე policy `Content-Security-Policy-Report-Only` header-ით. `/facebook/connect/callback`-ს საკუთარი nonce-იანი CSP აქვს. ახალი endpoint არ დამატებულა.

**Stage 22 — ფორმები უცვლელია** (ახალი endpoint, query-პარამეტრი და response-ის ველი არ არის; frontend არ შეცვლილა; შეცდომის ფორმატი `{"detail": "..."}`):
- **ჭერები** (Supabase-ის 1000-მწკრივიანი ჭერის ნაცვლად სიები გვერდებად იკითხება, `core/db.fetch_all`): `GET /products` — 10 000; `GET /orders` — უახლესი 10 000; `GET /public-menu` — აქტიური პროდუქტები ≤ 5 000; ბოტის პროდუქტები (webhook) ≤ 5 000. გადაჭარბებისას — პირველი/უახლესი N + სერვერის WARNING (200), ჩუმი ჭრა არა. ადმინის სიები: მაღაზიები ≤ 20 000, სხვა ცხრილები ≤ 200 000 (მხოლოდ 0039-მდე Python-ის fallback-ში), ერთი მაღაზიის პროდუქტები ≤ 10 000. pagination-ის პარამეტრები (`limit`/`offset`) არ დამატებულა.
- **`GET /shops/{id}/export`** — products და orders სრულად, თითო ≤ 50 000; მეტზე **413** `მონაცემი ექსპორტისთვის ძალიან დიდია — მიმართეთ მხარდაჭერას.` (ნაწილობრივი ექსპორტი არასდროს).
- **`POST /products/import`** — არსებულ პროდუქტებთან დამთხვევა (SKU / სახელი) ახლა მთელ კატალოგზე (ადრე პირველ 1000-ზე → დუბლიკატები); მაღაზიაში > 50 000 პროდუქტი → **413** `კატალოგი ძალიან დიდია იმპორტისთვის — მიმართეთ მხარდაჭერას.`
- **`/admin/overview` · `/admin/growth` · `/admin/shops`** — რიცხვები RPC-დან (`0039`); მის გარეშე Python-ის აგრეგაცია გვერდებით (სწორი, ნელი) + ერთი WARNING.
- **JWT:** 401-ის ტექსტები უცვლელია; ES256/RS256 token ლოკალურად მოწმდება, დანარჩენი — ქსელური `get_user`; `/admin/*` ყოველთვის ქსელითაც (იხ. §8).

**Stage 23 — ცვლილებები:**
- **`/admin/*` (ყველა) — MFA:** aal2 token-ის (TOTP) გარეშე → **403** `{"detail": "ადმინ პანელისთვის საჭიროა ორფაქტორიანი შესვლა (MFA)"}` (`ADMIN_REQUIRE_MFA`, იხ. §8/§12). `/admin/check`-ზეც (პანელში „ადმინი" ღილაკი aal1 სესიაზე არ ჩანს; ადმინი კოდს admin.html-ზე შეიყვანს).
- **`POST /admin/recovery`** → `{"ok": true}`. აღდგენის ბმული **გამყიდველის ელფოსტაზე იგზავნება** და ადმინს/response-ში არასდროს ბრუნდება. შეცდომები: 503 — SMTP არ არის მორგებული; 400 — არასწორი მოთხოვნა; 502 — provider-ის შეცდომა.
- **`GET /facebook/connect/callback`** — ≥ 2 გვერდიან ანგარიშზე პანელს `fb=choose` უბრუნდება (გვერდის არჩევა; ერთ გვერდზე ძველი ქცევა).
- **`POST /facebook/connect/select`** (ახალი) — არჩეული გვერდის დაკავშირება; selection token (10 წთ; ბაზაში არაფერი ინახება).

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
| GET | `/shops/me` | ჩემი მაღაზიები (`bot_status` / `bot_status_at` — ბოტის ჯანმრთელობა, 0036) |
| PATCH | `/shops/{id}` | განახლება (სახელი, ენა, ბოტის ჩართვა…) |
| POST | `/shops/{id}/knowledge` | PDF ატვირთვა → ბოტის ცოდნა; response მაშინვე ბრუნდება, FAQ ფონში იქმნება (ერთი LLM გამოძახება, როგორც წესი ~1 წუთში მზადაა; მანამდე ბოტი ძველებურად მუშაობს). ლიმიტი: 10 ატვირთვა/საათში IP-ზე, გადაჭარბებისას **429** |
| DELETE | `/shops/{id}/knowledge` | ცოდნის და FAQ-ის წაშლა |
| GET | `/shops/{id}/usage` | პაკეტი + კლიენტების მრიცხველი; Stage 20: `paid_until`, `expires_soon` (ბოლო 3 დღე), `expired`, `email_notifications` (SMTP მორგებულია თუ არა) |
| GET | `/shops/{id}/analytics` | ბოტის ანალიტიკა (top-terms, შეკითხვები) |
| GET | `/shops/{id}/attention` | „ყურადღება სჭირდება" საუბრები + შეჩერებული (`paused_until`) საუბრები; `attention_count` — მხოლოდ handoff |
| POST | `/shops/{id}/attention/{psid}/resolve` | საუბრის დახურვა (handoff-ის ნიშანიც და პაუზაც იხსნება) |
| POST | `/shops/{id}/attention/{psid}/resume` | „ბოტის ჩართვა" — მხოლოდ პაუზის მოხსნა (503 — 0033 არ არის) |
| DELETE | `/shops/{id}/customers/{psid}` | კლიენტის მონაცემების წაშლა (`bot_conversations` იშლება; `bot_customers.psid` ანონიმიზდება → `del:<uuid>`, მრიცხველი რჩება; შეკვეთები რჩება) |
| POST | `/shops/{id}/upgrade-request` | პაკეტის მოთხოვნა |
| POST | `/shops/{id}/downgrade-free` | უფასოზე დაბრუნება |
| GET | `/shops/{id}/export` | მონაცემთა ექსპორტი (portability) |

### პროდუქტები
| Method | Path | აღწერა |
|---|---|---|
| POST · GET | `/products` | დამატება · სია (`?shop_id=`). ფოტოს აღწერა (Stage 18) ფონში იქმნება response-ის შემდეგ (როგორც წესი ~1 წუთში მზადაა; მანამდე ძველი ქცევა); response და error კოდები უცვლელია |
| PUT · DELETE | `/products/{id}` | განახლება (ფოტოს შეცვლისას იგივე აღწერა) · წაშლა |
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
| POST | `/webhook` | შემოსული შეტყობინებები (X-Hub-Signature-256). გარე კონტრაქტი უცვლელია (200 / 403 / 400 / 413); Stage 21-დან 200 `webhook_inbox`-ში ჩაწერის **შემდეგ** იგზავნება, პასუხს worker აგზავნის (at-least-once, ტიპურად ≤1 წმ) |
| GET | `/facebook/connect/start` | OAuth-ის დაწყება |
| GET | `/facebook/connect/callback` | token-ის შენახვა + webhook subscribe; ≥ 2 გვერდზე → `fb=choose` (Stage 23) |
| POST | `/facebook/connect/select` | არჩეული გვერდის დაკავშირება selection token-ით (Stage 23) |
| POST | `/facebook/disconnect` | გვერდის გათიშვა + Meta-ს webhook subscription-ის მოხსნა (`DELETE /{page_id}/subscribed_apps`, best-effort) |
| POST | `/facebook/data-deletion` | Meta-ს Data Deletion callback |
| GET | `/facebook/data-deletion/status` | კოდის შემოწმება (ხელმოწერილი) |

### ადმინი (მხოლოდ `ADMIN_USER_IDS` + MFA / aal2)
| Method | Path | აღწერა |
|---|---|---|
| GET | `/admin/check` | ადმინია თუ არა |
| GET | `/admin/overview` | MRR, ჯამები; `llm` (Stage 21, USD) — `today_usd`, `month_usd` (`null` — 0038-ის გარეშე / შეცდომაზე), `daily_cap_usd`, `kill_switch`, `alert` (kill-switch ან დღიური ≥ 80% ჭერის) |
| GET | `/admin/growth` | ზრდის გრაფიკი |
| GET | `/admin/sellers` · `/admin/shops` · `/admin/orders` | სიები (`/admin/shops` ჩანაწერს აქვს `owner_id`, `paid_until`) |
| POST | `/admin/subscriptions/{owner_id}/extend` | გამოწერის გაგრძელება `{days}` (1–366) |
| GET · PATCH · DELETE | `/admin/shops/{id}` | დეტალები · პაკეტი/ბოტი · წაშლა |
| GET | `/admin/upgrade-requests` | მოთხოვნების სია |
| POST | `/admin/upgrade-requests/{id}/resolve` | დადასტურება/უარი |
| POST | `/admin/recovery` | აღდგენის ბმული გამყიდველის ელფოსტაზე → `{"ok": true}` (ბმული არ ბრუნდება) |

### Dev
| Method | Path | აღწერა |
|---|---|---|
| POST | `/test-chat` | ⚠️ ბოტის ტესტი Messenger-ის გარეშე — **production-ში გამორთულია** (404). provider-ის key-ის გარეშე → 503 `<VAR> არ არის კონფიგურირებული`; LLM-ის შეცდომა → 502 |

---

## 7. მონაცემთა ბაზა

### ცხრილები (მთავარი 9; + `webhook_inbox` 0037, `admin_audit_log` 0041) — ყველას აქვს RLS

| ცხრილი | რა ინახება |
|---|---|
| `shops` | მაღაზია, მფლობელი, პაკეტი, FB/IG ID-ები, დაშიფრული token, ცოდნა + `knowledge_faq` (0027, nullable), ენა |
| `products` | სახელი, ფასი, მარაგი, აღწერა, SKU, ფოტო, ფოტოს ტექსტური აღწერა `image_description` (0028, nullable), აქტიურობა |
| `orders` | კლიენტის შეკვეთა, პოზიციები (JSON), ჯამი, სტატუსი |
| `upgrade_requests` | პაკეტის მოთხოვნები (manual billing) |
| `bot_customers` | უნიკალური კლიენტი თვეში (ლიმიტის მრიცხველი) |
| `bot_conversations` | საუბრის მეხსიერება (ბოლო შეტყობინებები) + ძველი ნაწილის `summary` (0026, nullable) + handoff-ის ნიშანი (`needs_attention`, 0010) |
| `llm_usage` | LLM-ის გამოძახებების usage: `shop_id`, `provider`, `model`, `input_tokens` (cache-ის გარეშე), `output_tokens`, `cache_read_tokens`, `cache_write_tokens`. RLS ჩართული, პოლისები არ არის — მხოლოდ `service_role` (0025) |
| `data_deletion_requests` | Meta Data Deletion მოთხოვნების სტატუსი: `code`, `status` (`pending` / `completed` / `failed`), `error`; `fb_user_id` მხოლოდ დასრულებამდე. RLS ჩართული, პოლისები არ არის — მხოლოდ `service_role` (0029) |

| `subscriptions` | გამოწერის ვადა მფლობელზე: `owner_id`, `tier`, `paid_until` (0034). `authenticated` მხოლოდ კითხულობს (RLS), წერს backend (`service_role`) და ყოველდღიური pg_cron `expire_subscriptions()` |
| `admin_audit_log` | ადმინის მოქმედებების ჟურნალი (Stage 23, 0041): `actor_id`, `action`, `target`, `details` (jsonb, მხოლოდ allow-list-ის ველები — email / სახელი / ტექსტი არა), `created_at`. Append-only: `service_role`-ს მხოლოდ select + insert, update/delete არა; `anon`/`authenticated` — არაფერი |

**იზოლაცია:** ყველა პოლისი `shops.owner_id = auth.uid()`-ზე დგას (`USING` + `WITH CHECK`).
ერთი გამყიდველი მეორისას **ვერ ხედავს და ვერ ცვლის**.

### მიგრაციები (41)

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
| `0022` | 🔒 `orders`: UPDATE სრულად მოხსნილია `authenticated`-დან; `shops.knowledge*`-ზე UPDATE მოხსნილია (ჩაწერა მხოლოდ backend-ით). გაუშვი backend-ის deploy-ის **შემდეგ** |
| `0023` | `products.price` / `orders.total`: CHECK `< 'Infinity'` — Postgres-ში NaN `>= 0`-ს აკმაყოფილებს, ამიტომ NaN/Infinity ბაზაში ჩაწერა შეიძლებოდა. PRE-CHECK ფაილის თავშია |
| `0024` | 🔒 `upgrade_requests`: INSERT/UPDATE/DELETE მოხსნილია `authenticated`-დან, პოლისი `ur_owner_insert` იშლება; partial UNIQUE — მაქს. ერთი pending მაღაზიაზე. გაუშვი backend-ის deploy-ის **შემდეგ** |
| `0025` | 🔒 `llm_usage` — LLM usage-ის აღრიცხვა (RLS ჩართული, პოლისების გარეშე, მხოლოდ `service_role`). გაუშვი backend deploy-**მდე** |
| `0026` | `bot_conversations.summary` (text, nullable) — ძველი შეტყობინებების შეკუმშული ვერსია (Stage 16). ახალი პოლისი/უფლება არ არის. იდემპოტენტურია. გაუშვი Stage 16-ის backend deploy-**მდე**; backend მის გარეშეც მუშაობს — summary გამორთულია, ლოგში ერთი WARNING |
| `0027` | `shops.knowledge_faq` (text, nullable) — PDF-ცოდნის მოკლე FAQ (Stage 17). `authenticated`-ს ამ სვეტზე UPDATE არ აქვს (ჩაწერა მხოლოდ backend-ით). იდემპოტენტურია. გაუშვი Stage 17-ის backend deploy-**მდე**; backend მის გარეშეც მუშაობს — FAQ გამორთულია, ლოგში ერთი WARNING |
| `0028` | `products.image_description` (text, nullable) — პროდუქტის ფოტოს ტექსტური აღწერა (Stage 18). იდემპოტენტურია. გაუშვი Stage 18-ის backend deploy-**მდე**; backend მის გარეშეც მუშაობს — აღწერები გამორთულია, ლოგში ერთი WARNING |
| `0029` | 🔒 `data_deletion_requests` — Meta Data Deletion-ის რეალური სტატუსი (A-017; RLS, პოლისების გარეშე, მხოლოდ `service_role`). იდემპოტენტურია. გაუშვი backend deploy-**მდე**: მის გარეშე ახალი backend callback-ზე 503-ს აბრუნებს (წაშლა არ იწყება) |
| `0030` | 🔒 `pg_cron` + `purge_expired_bot_conversations(hours)` — საათში ერთხელ შლის 24 სთ-ზე ძველ საუბრებს (ღია handoff — 30 დღემდე რჩება) (A-018). EXECUTE მოხსნილია `public/anon/authenticated`-დან. იდემპოტენტურია; გაშვება ნებისმიერ დროს (backend-ის ცვლილება არ სჭირდება) |
| `0031` | `orders.idempotency_key` (uuid, nullable) + partial UNIQUE `(shop_id, idempotency_key)` — საჯარო ფორმის განმეორებითი გაგზავნა მეორე შეკვეთას არ ქმნის (A-020). იდემპოტენტურია. გაუშვი backend deploy-**მდე** (რეკომენდებული); backend მის გარეშეც მუშაობს — idempotency-ს გარეშე, ლოგში WARNING |
| `0032` | 🔒 `create_shop_limited` RPC — მაღაზიის ლიმიტის შემოწმება + INSERT ატომურად (per-owner advisory lock) (A-029). EXECUTE მხოლოდ `service_role`-ს. გაუშვი backend deploy-**მდე** (რეკომენდებული); მის გარეშე backend ძველი გზით მუშაობს + ერთი WARNING |
| `0033` | `bot_conversations.bot_paused_until` (timestamptz, nullable) — ბოტის პაუზა handoff-ის / გამყიდველის ხელით პასუხის შემდეგ, 12 სთ (Stage 20, A-035). გაუშვი backend deploy-**მდე**; მის გარეშე ძველი ქცევა (ბოტი ისევ პასუხობს) + WARNING, „ბოტის ჩართვა" → 503 |
| `0034` | 🔒 `subscriptions` (`owner_id`, `tier`, `paid_until`) + backfill + `expire_subscriptions()` და pg_cron `expire-subscriptions` (ყოველდღე 00:05 UTC) — ფასიანი პაკეტის ვადა (A-036). EXECUTE მოხსნილია `public/anon/authenticated`-დან. იდემპოტენტურია. გაუშვი backend deploy-**მდე**; მის გარეშე პაკეტები უვადოა + WARNING, ადმინის „გაგრძელება" → 503. **deploy-ის შემდეგ ხელახლა გაუშვი** (backfill `on conflict do nothing` — არსებული ვადები უცვლელი) |
| `0035` | 🔒 `llm_tokens_used(owner, since)` RPC + ინდექსი `llm_usage (created_at)` — LLM ბიუჯეტის შემოწმებისთვის (A-037). EXECUTE მხოლოდ `service_role`-ს. გაუშვი backend deploy-**მდე**; მის გარეშე თვიური/დღიური ბიუჯეტი გამორთულია + WARNING (kill-switch და უფასოს 30/დღე მუშაობს) |
| `0036` | `shops.bot_status` / `bot_status_at` (nullable) — ბოტის ჯანმრთელობა (A-038). `authenticated`-ს ამ სვეტებზე UPDATE არ აქვს. გაუშვი backend deploy-**მდე**; მის გარეშე პანელში ჯანმრთელობა არ ჩანს (Telegram მუშაობს) + WARNING |
| `0037_webhook_inbox` | 🔒 `webhook_inbox` — მდგრადი webhook-ის რიგი + dedup `(page_id, mid)` (Stage 21, A-040); RLS ჩართული, პოლისების გარეშე, მხოლოდ `service_role`; `claim_webhook_events(...)` (`SKIP LOCKED`) და `purge_webhook_inbox()` — EXECUTE მხოლოდ `service_role`; pg_cron `purge-webhook-inbox` (`23 * * * *`, 24 სთ-ზე ძველი მწკრივები). იდემპოტენტურია. გაუშვი backend deploy-**მდე** (რეკომენდებული); მის გარეშე ძველი in-process გზა + WARNING |
| `0038_llm_usage_by_model` | 🔒 `llm_usage_by_model(owner, shop, since)` RPC — ხარჯი მოდელის მიხედვით USD ბიუჯეტისთვის (Stage 21, A-048). EXECUTE მხოლოდ `service_role`. გაუშვი backend deploy-**მდე** (სავალდებულოა); მის გარეშე USD ბიუჯეტი გამორთულია + WARNING (kill-switch და უფასოს 30/დღე მუშაობს), ადმინის `today_usd`/`month_usd` = `null` |
| `0039_admin_stats` | 🔒 3 RPC (`admin_overview_stats()`, `admin_growth(p_months)`, `admin_shop_counts()`, `jsonb`) — ადმინის რიცხვები SQL-ში, 1000-მწკრივიანი ჭერის გარეშე (Stage 22, A-041). SECURITY INVOKER, `search_path = ''`; EXECUTE მხოლოდ `service_role`. იდემპოტენტურია. გაუშვი backend deploy-**მდე** (რეკომენდებული); მის გარეშე ადმინი Python-ის აგრეგაციაზეა (გვერდებით, სწორი, ნელი) + ერთი WARNING `admin_… missing (migration 0039 not applied)`; ფუნქციის გამოჩენისთანავე გადაერთვება, restart-ის გარეშე |
| `0040_products_search_trgm` | 🔒 `pg_trgm` (`extensions` schema) + 2 GIN trigram ინდექსი `products.name` / `description`-ზე + RPC `search_products(p_shop, p_terms, p_query, p_limit)` — ბოტის ძებნა ≥ `BOT_DB_SEARCH_MIN_PRODUCTS` (300) პროდუქტიან მაღაზიაზე ბაზაში (Stage 22, A-041). მოითხოვს `0028`-ს. SECURITY INVOKER; EXECUTE მხოლოდ `service_role`. იდემპოტენტურია. ინდექსის აგებისას `products`-ზე ჩაწერა მოკლედ იბლოკება — გაუშვი მშვიდ დროს. გაუშვი backend deploy-**მდე** (რეკომენდებული); მის გარეშე ძებნა მეხსიერებაშია + ერთი WARNING, RPC-ს backend 10 წთ-ში ერთხელ ხელახლა ცდის — restart არ სჭირდება |
| `0041_admin_audit_log` | 🔒 `admin_audit_log` — ადმინის მოქმედებების append-only ჟურნალი (Stage 23); RLS ჩართული, `service_role`-ს მხოლოდ select + insert (update/delete არა), `anon`/`authenticated` — არაფერი. იდემპოტენტურია. გაუშვი backend deploy-**მდე** (რეკომენდებული); მის გარეშე ადმინი მუშაობს + ერთი WARNING, ჩაწერა მიგრაციის გაშვებისთანავე იწყება, restart-ის გარეშე |

**გაშვება:** Supabase → SQL Editor → ჩასვი ფაილის შიგთავსი → RUN. თანმიმდევრობით (მიგრაციებს **მფლობელი უშვებს ხელით**; აგენტი remote-ზე არაფერს უშვებს). Stage 16-ის run order: `0026` (SQL Editor) → backend deploy. Stage 17-ის run order: `0027` (SQL Editor, `0026`-ის შემდეგ) → backend deploy → არსებული ცოდნიანი მაღაზიების PDF-ის ხელახალი ატვირთვა (FAQ-სთვის). Stage 18-ის run order: `0028` (SQL Editor, `0027`-ის შემდეგ) → backend deploy → backfill (`--dry-run` ჯერ, §9). Stage 19-ის run order: `0032` (SQL Editor) → backend deploy. Stage 20-ის run order (`0029`–`0032` ლაივ ბაზაში უკვე გაშვებულია): `0033` → `0034` → `0035` → `0036` (SQL Editor, თითო ცალკე, თანმიმდევრობით) → Render-ის env-ები (§12) → backend + frontend deploy (თუ `0035` გაეშვა მას შემდეგ, რაც ახალი backend უკვე მუშაობს — Render service-ის restart: ბიუჯეტის „გამორთულია" ფლაგი პროცესზეა) → `0034` ხელახლა (იდემპოტენტურია) → Meta App Dashboard-ში `message_echoes` (§10). Stage 21-ის run order: `0037` (რეკომენდებული) → `0038` (**სავალდებულო**, deploy-მდე) → Render-ის env-ები (§12; ტოკენის ცვლადები წაშალე) → backend + frontend deploy (თუ `0038` deploy-ის შემდეგ გაეშვა — Render restart) → შემოწმება: ლოგში `webhook worker started`, პანელი/ადმინი/`order.html`/`delete-data.html` Console-ში CSP-ის შეცდომის გარეშე (პრობლემაზე `CSP_REPORT_ONLY=true`). Stage 22-ის run order: `0039` → `0040` (SQL Editor, თითო ცალკე; ორივე deploy-მდე **რეკომენდებული**, არა სავალდებულო — მათ გარეშე fallback-ებია და ფუნქციის გამოჩენისას restart-ის გარეშე გადაერთვება) → Render-ზე `JWT_LOCAL_VERIFY` / `BOT_DB_SEARCH_MIN_PRODUCTS` (§12; ნაგულისხმევი საკმარისია) → backend deploy. JWT გასაღების ES256-ზე გადართვა (Supabase) Stage 22-ის კოდისგან დამოუკიდებელია და შეიძლება ადრეც — ზუსტი ნაბიჯები `PROGRESS.md` → `### Stage 22 — Deploy plan`; rollback: `JWT_LOCAL_VERIFY=false` + restart. Stage 23-ის run order (წინაპირობა — Stage 22-ის deploy): Supabase Auth → MFA → TOTP ჩართულია → `0041` (SQL Editor, რეკომენდებული) → SMTP (§12; recovery-ს სჭირდება) → Render-ზე **დროებით** `ADMIN_REQUIRE_MFA=false` → backend + frontend deploy → admin.html-ზე TOTP-ის ჩართვა (**გასაღები შეინახე პაროლების მენეჯერში**) → `ADMIN_REQUIRE_MFA` წაშალე (production-ში default = ჩართული; Render-ი თავად რესტარტავს) → შემოწმება: aal1 token-ით `/admin/overview` → 403, კოდის შემდეგ მუშაობს; სატესტო `PATCH /admin/shops/{id}` → ერთი ჩანაწერი `admin_audit_log`-ში. ზუსტი ნაბიჯები — `PROGRESS.md` → `### Stage 23 — Deploy plan`. შემდეგი თავისუფალი ნომერი — `0042`. ფაილის ბოლოს არის შემოწმების query და ROLLBACK.

**ერთჯერადი სკრიპტები** (`supabase/one-off/`, არა მიგრაციები — ხელით, ერთხელ, header-ის ინსტრუქციით):
`release_legacy_new_order_stock.sql` — deploy-მდე შექმნილი `new` შეკვეთების მარაგის დაბრუნება.

---

## 8. უსაფრთხოება

| დაცვა | როგორ |
|---|---|
| **მოიჯარეთა იზოლაცია** | RLS ყველა ცხრილზე; backend მომხმარებლის JWT-ით მიმართავს ბაზას |
| **JWT ლოკალურად (Stage 22)** | access token-ის `alg` ∈ {ES256, RS256} **და** `kid` JWKS-შია (`<SUPABASE_URL>/auth/v1/.well-known/jwks.json`, cache-ით) → ხელმოწერა, `exp` (±30 წმ), `aud`, `iss`, `sub` ლოკალურად (`core/jwt_verify.py`, PyJWT); ცუდი token → 401 fallback-ის გარეშე; `alg: none` / სხვა ალგორითმი → 401. HS256 / `kid`-ის გარეშე / უცნობი `kid` / JWKS-ის მიუწვდომლობა (შეცდომის შემდეგ 30 წმ ქსელს აღარ ვცდით) → ძველი ქსელური `get_user` (ავტორიტეტული; JWKS-ის გაუმართაობა არასდროს იძლევა 401-ს). **ადმინი (`/admin/*`) — ყოველთვის ქსელითაც** (`get_user`). **revocation-ის ნარჩენი:** გაუქმებული/გამოსული მომხმარებლის token seller endpoint-ებზე მუშაობს token-ის `exp`-მდე (≤ 1 სთ) — მიღებული რისკი (A-046), ადმინზე არა. ბერკეტი: `JWT_LOCAL_VERIFY=false` + restart → ყველა token `get_user`-ით (Stage 21-ის ქცევა). ლოგში token / `sub` / email არასდროს |
| **სიების ჭერები** | Stage 22: Supabase-ის (PostgREST) „Max rows" = **1000** (Dashboard → Settings → API) — კოდი ამ ჭერს გვერდებით (`fetch_all`) უვლის და არ ეყრდნობა მას; ეს პარამეტრი **1000-ზე დარჩეს** (გაზრდა ზედმეტია). ცხადი ჭერები (10 000 / 5 000 / 50 000 / ადმინში 20 000…200 000) — გადაჭარბებისას WARNING ან 413, არასდროს ჩუმი ჭრა (§6) |
| **Page token** | ინახება **დაშიფრულად** (Fernet, `FB_TOKEN_ENCRYPTION_KEY`) |
| **webhook-ის ავთენტურობა** | `X-Hub-Signature-256` მოწმდება app secret-ით |
| **RPC-ების ნებართვები** | `SECURITY DEFINER` ფუნქციები **მხოლოდ** `service_role`-ს — `anon`/`authenticated` მოხსნილია (მიგრაცია 0014) |
| **SSRF** | სურათის ჩამოტვირთვისას: სქემის allowlist, private/loopback/link-local IP-ების ბლოკი, redirect-ების ხელით გავლა, ბაიტების ჭერი |
| **რბოლები** | მარაგი — Postgres row-lock; შეკვეთის სტატუსი — ოპტიმისტური ჩაკეტვა (409) |
| **დედუპლიკაცია** | Meta-ს განმეორებული `mid` ბოტს ორჯერ არ ამუშავებს |
| **Rate limiting** | per-IP sliding window საჯარო endpoint-ებზე |
| **Abuse cap** | ერთი კლიენტი დღეში 100 შეტყობინება (უფასოზე 30) |
| **LLM ხარჯის ჭერი (USD)** | Stage 21: ბიუჯეტი დოლარშია (`llm_usage`-ის ტოკენები × ფასი, მოდელის მიხედვით — `LLM_PRICES`). `LLM_KILL_SWITCH`; გლობალური დღიური `LLM_DAILY_USD_CAP` ($1, ყველა tenant ერთად); მაღაზიის თვიური `LLM_MONTHLY_USD_*` პაკეტის მიხედვით; მაღაზიის დღიური = თვიური ÷ `LLM_DAILY_USD_SHOP_DIVISOR` (10 → free $0.03 / basic $0.25 / standard $0.80 / business $2.50), მიზეზი `shop_daily_cap`. ამოწურვისას ბოტი ოპერატორის პასუხს აგზავნის. საჭიროა `0038` — მის გარეშე ბიუჯეტი გამორთულია + WARNING |
| **webhook-ის რიგი** | Stage 21: `message.mid`-იანი მოვლენა ჯერ `webhook_inbox`-ში (0037) ინახება და მხოლოდ მერე იგზავნება 200; worker იმავე პროცესში (FastAPI lifespan) იღებს `SKIP LOCKED`-ით. **at-least-once**: restart / deploy / რამდენიმე instance მოვლენას ვერ კარგავს; განმეორებული `(page_id, mid)` იგნორდება; ჩაწერის შეცდომაზე — ძველი in-process დამუშავება. `event` (შეტყობინება, PSID) დამუშავებისთანავე `null`, მწკრივები 24 სთ-ში იშლება (pg_cron `purge-webhook-inbox`); ლოგში payload/PSID/ტექსტი არასდროს |
| **CSP** | Stage 21: ყველა პასუხზე `Content-Security-Policy` (`script-src 'self'` — inline/eval არა), + `Cross-Origin-Resource-Policy: same-origin`, `Cache-Control: no-store` (სადაც route-ს საკუთარი არ აქვს). OAuth callback-ის HTML — ერთჯერადი nonce. COOP არ არის (FB OAuth popup). საგანგებოდ: `CSP_REPORT_ONLY=true` + restart |
| **გასაღებების გამოყოფა (HKDF)** | Stage 21: OAuth `state` და Data Deletion კოდი HKDF-SHA256-ით გამოყვანილი გასაღებებით (IKM = `FB_APP_SECRET`). Meta-ს კონტრაქტის HMAC-ები (`appsecret_proof`, `X-Hub-Signature-256`, `signed_request`) უცვლელად app secret-ს იყენებს. Stage 21-მდე გაცემული deletion კოდები ვერიფიცირდება 2027-12-10-მდე; deploy-მდე დაწყებული OAuth connect (≤10 წთ) → `invalid_state`, ხელახლა სცადე |
| **ადმინის MFA (Stage 23)** | `/admin/*` მოითხოვს aal2 token-ს (TOTP, supabase-js; ბექაპ კოდები არ არის — გასაღები (secret) შეინახე პაროლების მენეჯერში). `ADMIN_REQUIRE_MFA`: ცარიელი = production-ში ჩართული, სხვაგან გამორთული; `false` — მხოლოდ დროებით, TOTP-ის ჩართვამდე (**lock-out-safe rollout**: ჯერ `false` + deploy → TOTP-ის ჩართვა admin.html-ზე → ცვლადის წაშლა/`true`). საგანგებოდ (ავთენტიფიკატორი დაიკარგა): `ADMIN_REQUIRE_MFA=false` + restart → Supabase Dashboard-ში factor-ის წაშლა → ხელახლა ჩართვა. production-ში გამორთულზე ლოგში ერთი WARNING |
| **ადმინის audit log (Stage 23)** | `admin_audit_log` (0041): ადმინის ცვლილებები (`shop.update`, `shop.delete`, `upgrade_request.approve/reject`, `subscription.extend`, `seller.recovery`) იწერება append-only (`service_role`-ს update/delete არა). `details` — მხოლოდ allow-list-ის ველები, PII (email, სახელი, ტექსტი) არა. **best-effort**: ჩაწერის შეცდომა ადმინის მოქმედებას არ აჩერებს (მიღებული რისკი); მიგრაციის გარეშე ადმინი მუშაობს + ერთი WARNING, ჩაწერა restart-ის გარეშე იწყება |
| **აღდგენის ბმული** | `POST /admin/recovery`: ბმული მხოლოდ გამყიდველის საფოსტო ყუთში მიდის; ადმინი მას ვერ ხედავს, response-ში და ლოგში არ ბრუნდება |
| **FB გვერდის არჩევა (Stage 23)** | selection token = Fernet + HKDF (`chatassist:fb-page-selection:v1`), 10 წთ; შიგნით დაშიფრულია FB user token; ბაზაში არაფერი ინახება. popup-ის დაბლოკვისას redirect fallback-ზე token request URL-ში ჩნდება — მიღებული რისკი |
| **File bombs** | Excel/CSV — 5 MB / 5 000 მწკრივი; PDF — 300 გვერდი; zip-ratio ჭერი |
| **CSV injection** | `=`, `+`, `-`, `@` ექსპორტში ნეიტრალდება |
| **Security headers** | `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`, HSTS (production); CSP — იხ. ზემოთ (CSP-ის ხაზი) |
| **შეცდომების გაჟონვა** | production-ში stack trace არ ბრუნდება |
| **Dev endpoint** | `/test-chat` production-ში გამორთულია |
| **Data Deletion** | Meta-ს callback ეხება **მხოლოდ გამყიდველს** (app-scoped ID = `shops.facebook_user_id`): მისი მაღაზიების FB მონაცემები იშლება, გვერდი ითიშება, webhook-ის გამოწერა მოიხსნება (best-effort); + ხელმოწერილი (HMAC) დადასტურების კოდი; სტატუსი (`pending` / `completed` / `failed`) `data_deletion_requests`-ში (0029), შეცდომა ილოგება და არ იყლაპება. **Messenger-ის კლიენტის** (page-scoped ID) წაშლა — მაღაზიისთვის მიწერით (გამყიდველი პანელში: საუბარი → 🗑, `DELETE /shops/{id}/customers/{psid}`: საუბარი იშლება, ხოლო კლიენტის ID თვიურ მრიცხველში ანონიმიზდება — `bot_customers.psid` → `del:<uuid>`; რაოდენობა რჩება, რომ ლიმიტი არ განულდეს; გამყიდველის Meta callback კვლავ შლის) ან ელფოსტით `chatassistbusiness@gmail.com`; საუბრები ისედაც 24 სთ-ში იშლება |

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
pip install -r requirements.txt    # Windows-ზე ლოკალურად ყოველთვის ეს (არა requirements.lock.txt)
Copy-Item ..\.env.example ..\.env    # შემდეგ შეავსე
uvicorn app.main:app --reload
```

> ⚠️ **ლოკალური `.env` production Supabase-ს უკავშირდება.** `APP_ENV` ნაგულისხმევად `production`-ია, ამიტომ ლოკალურ `.env`-ში **აუცილებლად** უნდა იყოს ორივე: `APP_ENV=development` **და** `WEBHOOK_INBOX_ENABLED=false`. წინააღმდეგ შემთხვევაში ლოკალური backend გაუშვებს inbox worker-ს და production `webhook_inbox`-ის მოვლენებს დაამუშავებს.

გახსენი <http://localhost:8000/health> და <http://localhost:8000/docs>

### Frontend

```bash
cd frontend
npm install
npm run dev      # http://localhost:5173/panel/
npm run build    # → dist/  (ეს ჩადის git-ში!)
npm run lint     # ESLint
npm test         # Vitest-ის ტესტები
```

ბრაუზერის (e2e) ტესტები — Playwright, მხოლოდ ლოკალურად (CI-ში არა); backend არ სჭირდება, API-ები იმოკება:

```bash
cd frontend
npx playwright install chromium   # ერთხელ
npm run build && npm run test:e2e # preview აშენებულ dist/-ს ემსახურება → ჯერ build
```

`frontend/public/config.js` — გადააკოპირე `config.example.js`-დან და შეავსე
(`SUPABASE_URL`, anon key, `API_BASE`).

> ⚠️ **ხაფანგი:** `uvicorn --reload` ხანდახან ობოლ პროცესს ტოვებს, რომელიც პორტს
> იკავებს და ძველ კოდს ასერვირებს. თუ ცვლილება არ ჩანს —
> `Get-Process python | Stop-Process -Force` და თავიდან გაუშვი.

### Provider-ების ბრმა შედარება (Stage 15)

1. **დანიშნულება.** 40 შეკითხვა × 2 provider (Claude და OpenAI) — იგივე გზით, რასაც ბოტი იყენებს: `graph.run_turn` (შაბლონები, tool-ები, გასუფთავება); ერთი შეკითხვა შეიძლება რამდენიმე LLM გამოძახება იყოს (≤4), usage = ამ turn-ის გამოძახებების ჯამი (`calls`), შაბლონურ პასუხზე 0; მონაცემი ფიქტიური მაღაზიისაა. Supabase-ს და `llm_usage`-ს არ ეხება. სკრიპტს **მხოლოდ მფლობელი** უშვებს (რეალური API-ები და ხარჯი).
2. **წინაპირობა.** `ANTHROPIC_API_KEY` და `OPENAI_API_KEY` ორივე სავალდებულოა — ლოკალურ `.env`-ში ან გარემოს ცვლადებში (სკრიპტი key-ს არ ბეჭდავს). რეკომენდაცია: ორივე კონსოლში დააყენე spend limit.
3. **ბრძანებები** (`backend/` საქაღალდიდან). PowerShell — ჯერ smoke (`--limit 3`, 6 გამოძახება):
   ```powershell
   $env:PYTHONUTF8=1; .\.venv\Scripts\python.exe -m scripts.compare_providers --limit 3
   ```
   დაათვალიერე შედეგი და მერე სრული გაშვება (80 შეკითხვა-გაშვება (თითოს tool-ების გამო შეიძლება რამდენიმე LLM გამოძახება ჰქონდეს), თანმიმდევრულად, ~1 წმ პაუზით; რამდენიმე წუთი):
   ```powershell
   $env:PYTHONUTF8=1; .\.venv\Scripts\python.exe -m scripts.compare_providers
   ```
   Git Bash:
   ```bash
   PYTHONUTF8=1 .venv/Scripts/python.exe -m scripts.compare_providers --limit 3
   PYTHONUTF8=1 .venv/Scripts/python.exe -m scripts.compare_providers
   ```
   არგუმენტები:
   - `--seed N` — A/B ეტიკეტების შემთხვევითობის seed (მთელი რიცხვი, default `15`);
   - `--limit N` — მხოლოდ პირველი N შეკითხვა (N ≥ 1);
   - `--delay S` — პაუზა გამოძახებებს შორის წამებში (≥ 0, default `1.0`);
   - `--out-dir DIR` — სად ჩაიწეროს შედეგი (default — `backend/scripts/`);
   - `--dry-run` — key-ის და API-ს გარეშე, მხოლოდ prompt-ების ზომებს ბეჭდავს და ფაილს არ წერს.
4. **ხარჯი.** ~80 გამოძახება; სკრიპტის ფასების ცხრილით < $0.10. gpt-6-luna-ს ფასი **UNVERIFIED** (მესამე წყაროდანაა) — რეალური ხარჯი ნახე OpenAI კონსოლში.
5. **გამოსავალი.** `backend/scripts/compare_output.md` და `compare_key.json` — ორივე gitignored, **არასდროს** დააკომიტო. ხელახალი გაშვება მათ გადაწერს. `--out-dir` მიუთითე repo-ს გარეთ ან ignored გზაზე.
6. **ბრმა შეფასება.** ჯერ გახსენი მხოლოდ `compare_output.md`. თითო შეკითხვაზე A და B შეაფასე 0–2 ქულით თითო კრიტერიუმზე: facts (ფოტოზე — სწორი პროდუქტი), ქართული/ენა, მოკლეობა + markdown-ის გარეშე, handoff. `usage` ბლოკი არ გახსნა, სანამ ტექსტს არ შეაფასებ (ტოკენების რაოდენობა provider-ს ავლენს). მხოლოდ ამის შემდეგ გახსენი `compare_key.json` და დაითვალე ქულების ჯამი provider-ზე.
7. **შემდეგ `PROJECT.md` Decision Log-ში ჩაწერე:** default provider (`LLM_PROVIDER`); thinking/effort საჭიროა თუ არა; output-ის ჭერი (800); 5-წუთიანი cache-ის ეკონომიკა (key-ის totals: cache read vs write); OpenAI-ის `input_tokens`-ის სემანტიკა; gpt-6-luna-ს რეალური ფასი; 429/timeout-ების რაოდენობა.
8. **შენიშვნა.** ფოტოები სინთეტიკურია — ისინი ამოწმებენ pipeline-ს და უხეშ შესაბამისობას, არა რეალური ფოტოების ხარისხს; მაღაზია ერთია, ≤30 პროდუქტით.
9. **Stage 18.** დემო-მაღაზიას აღწერიანი ფოტო-პროდუქტები აქვს, ამიტომ ფოტო-შეკითხვებზე საცნობარო ფოტო ≤3-ია (`--dry-run`-ში `images 4` = 3 საცნობარო + კლიენტის ფოტო); ტოკენების გაზომვა — `input_tokens`-ით.

### ფოტოების აღწერის backfill (Stage 18)

1. **დანიშნულება.** არსებულ პროდუქტებს, რომელთა ფოტოს ჯერ აღწერა არ აქვს (`image_description` ცარიელია) და ფოტო მაღაზიის საკუთარ Storage საქაღალდეშია, თითოს ერთხელ აღწერს და შედეგს ინახავს. აღწერილ პროდუქტს არასდროს ეხება, ამიტომ განმეორებითი გაშვება მხოლოდ დარჩენილს იღებს (idempotent). ბეჭდავს მხოლოდ პროდუქტის id-ებს და ჯამებს.
2. **ვინ უშვებს.** **მხოლოდ მფლობელი** (რეალური API და ხარჯი; აგენტი არასდროს). სჭირდება მიმდინარე `LLM_PROVIDER`-ის key (ლოკალურ `.env`-ში ან გარემოს ცვლადებში) და გაშვებული `0028`.
3. **რიგი.** `0028` (SQL Editor) → backend deploy → სკრიპტი: ჯერ `--dry-run`, მერე `--limit 5`, მერე დანარჩენი.
4. **ბრძანება** (`backend/` საქაღალდიდან):
   ```bash
   .venv/Scripts/python.exe -m scripts.backfill_image_descriptions [--dry-run] [--limit N] [--shop UUID] [--delay S]
   ```
   - `--dry-run` — API-ს არ იძახებს და არაფერს წერს, მხოლოდ კანდიდატებს და სავარაუდო ხარჯს ითვლის;
   - `--limit N` — მაქს. N პროდუქტი ერთ გაშვებაზე (default `20`, მაქს. `500`);
   - `--shop UUID` — მხოლოდ ერთი მაღაზია;
   - `--delay S` — პაუზა გამოძახებებს შორის წამებში (default `1.0`, მაქს. `60`).
   Exit კოდები: `0` მზადაა (ჩავარდნილი ფოტოები ითვლება, არ აჩერებს), `1` query-ს შეცდომა, `2` არასწორი არგუმენტი / key-ის უქონლობა / `0028` არ არის გაშვებული, `130` შეწყვეტა.
5. **ხარჯი.** ≈ < $0.0005 ფოტოზე (მაგ. 200 ფოტო ≈ < $0.10); `--dry-run` სავარაუდო თანხას გვიჩვენებს. რეალური ხარჯი ნახე provider-ის კონსოლში.

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
- Subscribe: **messages**, **messaging_postbacks**, **message_echoes** (Stage 20 — გამყიდველის ხელით პასუხის ამოსაცნობად; უკვე დაკავშირებულ გვერდებს echo მოუვა მხოლოდ **ხელახალი დაკავშირების** შემდეგ: პანელი → გათიშვა → დაკავშირება). Echo-ს ამოცნობა: ჩვენი პასუხი ამოიცნობა გაგზავნილი `message_id`-ითაც; Instagram-ის echo `app_id`-ის გარეშე პაუზას არ აყენებს (გამყიდველის ხელით პასუხის პაუზა Instagram-ზე გამორთულია, სანამ რეალური payload არ გადამოწმდება); ყოველი echo-ს `app_id` ილოგება INFO-ზე — მფლობელმა ამით გადაამოწმოს Instant Reply / Business Suite-ის ქცევა

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

**Render:** auto-deploy `main`-ზე push-ისას. Dashboard-ის პარამეტრები:

```
Root Directory:    backend
Build:             pip install -r requirements.lock.txt
Start:             uvicorn app.main:app --host 0.0.0.0 --port $PORT
Instances:         1  (rate limit და webhook dedup მეხსიერებაშია — >1 instance-ზე უქმდება)
Health Check Path: /health
Build Filter:      backend/**  frontend/dist/**
```

`requirements.lock.txt` — hash-pinned და Linux-ზე resolved (Render/CI); pip hash-checking რეჟიმს ავტომატურად რთავს. Windows ლოკალურად `requirements.txt` გამოიყენება. თავიდან გენერაცია (repo root-იდან, Git Bash; ვერსიების ასაწევად დაამატე `--upgrade`, მერე თავსართი ხელით დააბრუნე):

```bash
MSYS_NO_PATHCONV=1 docker run --rm -v "$PWD/backend:/w" -w /w python:3.14.3-slim sh -c "pip install -q pip-tools && pip-compile --generate-hashes --allow-unsafe --strip-extras --no-emit-index-url --output-file requirements.lock.txt requirements.txt"
```

CI-ში GitHub Actions commit SHA-ებზეა დაპინული — ვერსიის აწევისას SHA განაახლე.

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
| `APP_ENV` | | `production` | `production` (default, fail-closed) → HSTS, დამალული შეცდომები, `/test-chat` off. ლოკალურად `.env`-ში `APP_ENV=development`. დასაშვები მხოლოდ `production`/`prod` ან `development`/`dev`/`test`; სხვა მნიშვნელობით (მაგ. `prd`, `staging`) აპი **არ ირთვება** (A-019) |
| `APP_HOST` · `APP_PORT` | | `0.0.0.0` · `8000` | |
| `CORS_ORIGINS` | | `*` | production-ში კონკრეტული დომენი |
| `CLIENT_IP_TRUSTED_HOPS` | ✅ | — (Render: `3`) | production-ში სავალდებულოა (≥1), სხვაგვარად სერვერი არ ადგება. კლიენტის IP = `X-Forwarded-For`-ის მარჯვნიდან N-ური ჩანაწერი (Render-ზე სწორი N დაადგინე `CLIENT_IP_DEBUG`-ით). `CF-Connecting-IP` იგნორირდება |
| `CLIENT_IP_DEBUG` | | `false` | დროებით `true` → ერთი INFO ხაზი ლოგში: სრული XFF (≤1000 სიმბ.), entries, peer (არასანდო), hops, resolved IP (10 წმ-ში ერთხელ); შემდეგ გამორთე. production-ში XFF-ის ნაკლებობისას resolved = `unknown` (საერთო key, `peer` არ გამოიყენება — გაყალბებადია) |
| `LOG_LEVEL` | | `INFO` | `app` logger-ის დონე (stdout-ზე): `DEBUG` / `INFO` / `WARNING` / `ERROR`; არავალიდური → `INFO` |
| `LLM_PROVIDER` | | `claude` | `claude` ან `openai`; ცარიელი → `claude`; სხვა მნიშვნელობა → სერვერი არ ადგება |
| `ANTHROPIC_API_KEY` | ✅ ბოტისთვის (`LLM_PROVIDER=claude`) | — | 🔒 Anthropic Console → API Keys. არ არის fail-closed სიაში: გარეშე აპი ირთვება, ბოტი ოპერატორის პასუხს აგზავნის |
| `CLAUDE_MODEL` | | `claude-haiku-5-5` | მოდელის შეცვლა კოდის გარეშე |
| `OPENAI_API_KEY` | ✅ ბოტისთვის (`LLM_PROVIDER=openai`) | — | 🔒 OpenAI Platform → API keys |
| `OPENAI_MODEL` | | `gpt-6-luna` | მოდელის შეცვლა კოდის გარეშე |
| `LLM_TIMEOUT_SECONDS` | | `20` | ერთი LLM მცდელობის timeout (წმ); `gt 0, ≤ 20`, სხვა მნიშვნელობა → სერვერი არ ადგება. retry-ების ჯამი ≤45 წმ, მერე webhook fallback პასუხი |
| `BOT_MEMORY_MESSAGES` | | `20` | 0 = მეხსიერება გამორთული (ისტორიის შეკუმშვა 16-ზე/8-ზე კოდშია, `memory.py`) |
| `BOT_MEMORY_HOURS` | | `24` | ვადაგასულ საუბრებს pg_cron შლის 24 სთ-ზე (0030); სხვა მნიშვნელობაზე startup WARNING — cron-ის ბრძანებაც შეცვალე |
| `FB_APP_ID` · `FB_APP_SECRET` | ✅ | — | 🔒 Meta App |
| `FB_VERIFY_TOKEN` | ✅ | — | webhook-ის ვერიფიკაცია |
| `FB_GRAPH_VERSION` | | `v21.0` | |
| `FB_REDIRECT_URI` | ✅ | — | OAuth callback |
| `FB_LOGIN_CONFIG_ID` | | — | Facebook Login for Business (business-owned გვერდები) |
| `FB_TOKEN_ENCRYPTION_KEY` | ✅ | — | 🔒 Fernet key |
| `PUBLIC_BASE_URL` | | `FB_REDIRECT_URI`-დან | შესაკვეთი ლინკების ბაზა |
| `FRONTEND_URL` | | `localhost:5500` | |
| `ADMIN_USER_IDS` | | — | ვინ ხედავს `/admin`-ს (Supabase user UUID-ები, მძიმით; ცარიელი = ადმინი არავინაა) |
| `ADMIN_REQUIRE_MFA` | | ცარიელი | (Stage 23) `/admin/*`-ზე ორფაქტორიანი შესვლა (aal2). ცარიელი = production-ში ჩართული, dev-ში გამორთული; `true`/`false` ცხადად. `false` — მხოლოდ TOTP-ის ჩართვამდე (ან ავთენტიფიკატორის დაკარგვისას), მერე წაშალე; ცვლილება → restart (§8) |
| `PAYMENT_IBAN` · `PAYMENT_CONTACT` | | placeholder | გადახდის რეკვიზიტები |
| `SMTP_HOST` · `SMTP_USER` · `SMTP_PASSWORD` | | — | 🔒 email შეტყობინებები გამყიდველს (ახალი შეკვეთა, handoff). ნებისმიერი SMTP provider, მაგ. Brevo (`smtp-relay.brevo.com:587`) ან Resend SMTP (`smtp.resend.com:465`, user `resend`). ცარიელი (ან `NOTIFY_EMAIL_FROM` ცარიელი) = email გამორთულია |
| `SMTP_PORT` | | `587` | `465` = SSL, სხვა (587) = STARTTLS |
| `NOTIFY_EMAIL_FROM` | | — | გამგზავნი, მაგ. `ChatAssist <noreply@chatassist.ge>`; დომენი provider-ში ვერიფიცირებული უნდა იყოს (SPF/DKIM) |
| `TELEGRAM_BOT_TOKEN` · `TELEGRAM_CHAT_ID` | | — | 🔒 ადმინის „BOT DOWN" alert-ები (მხოლოდ მიზეზი, shop id, სახელი). ცარიელი = გამორთულია |
| `LLM_KILL_SWITCH` | | `false` | `true` → ყველა LLM გამოძახება გაჩერებულია (ბოტი ოპერატორის პასუხს აგზავნის) |
| `LLM_DAILY_USD_CAP` | | `1.0` | (Stage 21) გლობალური დღიური ჭერი USD-ში, ყველა tenant ერთად (UTC დღე); `0` = გამორთული. ⚠️ ფასიანი მაღაზიების ზრდისას გაზარდე |
| `LLM_DAILY_USD_SHOP_DIVISOR` | | `10` | მაღაზიის დღიური ჭერი = თვიური ÷ ეს რიცხვი (free $0.03 / basic $0.25 / standard $0.80 / business $2.50); `0` = გამორთული |
| `LLM_MONTHLY_USD_FREE` · `_BASIC` · `_STANDARD` · `_BUSINESS` | | `0.30` · `2.50` · `8` · `25` | თითო მაღაზიის თვიური ბიუჯეტი USD-ში პაკეტის მიხედვით; `0` = გამორთული. ბოლო ბადედ provider-ის კონსოლშიც დააყენე spend limit |
| `LLM_PRICES` | | ცარიელი (კოდის default-ები) | ფასები USD / 1M ტოკენი, JSON, მაგ. `{"claude-haiku-5-5":{"input":0.10,"output":0.50,"cache_read":0.01,"cache_write":0.20}}`; მითითებული მოდელი მთლიანად იცვლება, დანარჩენი რჩება |
| `WEBHOOK_INBOX_ENABLED` | | ცარიელი | ცარიელი = production-ში ჩართული, dev-ში გამორთული. **Render-ზე არ დააყენო.** ⚠️ ლოკალურ `.env`-ში **აუცილებლად** `APP_ENV=development` **და** `WEBHOOK_INBOX_ENABLED=false`: ლოკალური `.env` production ბაზას უკავშირდება, `APP_ENV` ნაგულისხმევად `production`-ია და ამ ორის გარეშე ლოკალური backend გაუშვებს worker-ს და production `webhook_inbox`-ს დაამუშავებს |
| `BOT_MAX_CONCURRENCY` | | `8` | ბოტის ერთდროული გაშვებების ლიმიტი (1–32) |
| `WEBHOOK_POLL_SECONDS` | | `10` | worker-ის რიგის შემოწმების ინტერვალი, წმ (1–300) |
| `WEBHOOK_MAX_ATTEMPTS` | | `3` | ერთი მოვლენის მაქს. მცდელობა, მერე `failed` (1–10) |
| `WEBHOOK_CLAIM_STALE_SECONDS` | | `180` | `processing` მოვლენა ამ დროის შემდეგ გაჭედილად ითვლება და თავიდან ირიცხება (60–3600) |
| `CSP_REPORT_ONLY` | | `false` | `true` → CSP მხოლოდ `Content-Security-Policy-Report-Only` რეჟიმში (არაფერს ბლოკავს) — საგანგებო გადამრთველი, კოდის გარეშე |
| `BOT_DB_SEARCH_MIN_PRODUCTS` | | `300` | (Stage 22) ბოტის `search_products`: ამდენ ან მეტ პროდუქტიან მაღაზიაზე ძებნა Postgres-ში (RPC `0040`), ნაკლებზე — მეხსიერებაში. `0` = ყოველთვის მეხსიერებაში |
| `JWT_LOCAL_VERIFY` | | `true` | (Stage 22) ES256/RS256 token-ის ლოკალური შემოწმება JWKS-ით. `false` → ყველა token ქსელური `get_user`-ით (Stage 21-ის ქცევა) — საგანგებო ბერკეტი (მაგ. გასაღების როტაციის შემდეგ 401-ები); restart სჭირდება |

**წაიშალა (Stage 21):** `LLM_DAILY_TOKEN_CAP`, `LLM_DAILY_TOKENS_PER_OWNER`, `LLM_MONTHLY_TOKENS_*` — ბიუჯეტი ახლა USD-შია. Render-ზე წაშალე — იგნორდება, მაგრამ აბნევს.

🔒 = საიდუმლო. **`.env` არასდროს ჩააქოს git-ში.**

**Fail-closed (S11-6):** `APP_ENV=production`-ზე აპი **არ ირთვება** (`RuntimeError: Missing required production settings: ...`, მხოლოდ სახელები), თუ ცარიელია რომელიმე:
`SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_SECRET_KEY`, `FB_APP_SECRET`, `FB_VERIFY_TOKEN`, `FB_TOKEN_ENCRYPTION_KEY` (ვალიდური Fernet key; არავალიდური → `FB_TOKEN_ENCRYPTION_KEY (invalid format)`).
LLM provider-ის key (`ANTHROPIC_API_KEY` / `OPENAI_API_KEY`) ამ სიაში **არ არის**: მის გარეშე აპი ირთვება, ბოტი ოპერატორის პასუხს აგზავნის (საუბარი „ყურადღება სჭირდება"-ში ინიშნება), ლოგში WARNING `LLM disabled: <VAR> is not set`. დარჩენილი `GEMINI_*` ცვლადები იგნორირდება — Render-ზე წაშალე ახალი ვერსიის live-ის შემდეგ (იხ. [DEPLOYMENT.md](DEPLOYMENT.md)).
`development`-ში შემოწმება არ მუშაობს, თუმცა ცარიელი `FB_APP_SECRET`-ით webhook/signed_request/OAuth state/data-deletion კოდი ყოველთვის უარყოფილია.

⚠️ **`LANGSMITH_TRACING` / `LANGCHAIN_TRACING_V2` / `LANGSMITH_API_KEY` არასდროს დააყენო production-ში** (არც ლოკალურად რეალურ საუბრებზე): LangGraph-ის tracing კლიენტების შეტყობინებებს მესამე მხარეს გაგზავნიდა.

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
| 1 | **Frontend ტესტების დაფარვა ნაწილობრივია** | Vitest (116) და Playwright e2e (27, მხოლოდ ლოკალურად) ძირითად ნაკადებს ფარავს; დანარჩენი React-ის კოდი ხელით მოწმდება |
| 2 | **React-ის კოდი ხაზ-ხაზ არ წაკითხულა** | რევიუზე შემოწმდა სტრუქტურა, `useEffect`-ები და ძველთან დიფი; `AdminPage.jsx` (539 ხაზი) და `ProductsTab.jsx` (365) ცალკე გავლას იმსახურებს |
| 3 | **CSP header არ არის** | თეთრი სიის პრინციპი — ერთი გამორჩენა ცარიელ გვერდს იძლევა. რედიზაინისას ისედაც გადაიწერება |
| 4 | **Rate limit მეხსიერებაშია** | deploy-ზე ნულდება; მრავალ-instance-ზე Redis/Cloudflare დასჭირდება |
| 5 | **webhook-ის დედუპლიკაცია მეხსიერებაშია** | რესტარტზე იწმინდება; სრული გადაწყვეტა რიგს (Redis) სჭირდება |
| 6 | **ადმინ-პანელის სიები ერთ მოთხოვნაში იტვირთება** | Stage 22-იდან overview/growth/მაღაზიების რიცხვები SQL-შია (`0039`), სიები გვერდებით და ცხადი ჭერებით (§6); სერვერული pagination (`limit`/`offset`) არ არის. მხოლოდ მფლობელი იყენებს |
| 7 | **ვიზუალი და ლოგო არ ემთხვევა** | საიტზე ძველი ჩანთის SVG, Meta-ს აპ-იკონა კი CA-მონოგრამი |
| 8 | **გადახდა ხელითაა** | ავტომატური billing ჯერ არ არის — მოთხოვნა → ადმინის დადასტურება |
| 9 | **JWT revocation ≤ 1 სთ seller endpoint-ებზე** | Stage 22-იდან ES256/RS256 token ლოკალურად მოწმდება, ამიტომ გაუქმებული/წაშლილი მომხმარებლის token მუშაობს `exp`-მდე (≤ 1 სთ). ადმინზე არა (ყოველთვის `get_user`-ითაც). მიღებული რისკი A-046; საგანგებოდ — `JWT_LOCAL_VERIFY=false` (§8) |
| 10 | **FB გვერდის არჩევა: მხოლოდ პირველი 25 გვერდი** | > 25 გვერდიან ანგარიშზე არჩევანში პირველი 25 ჩანს (Stage 23) |
| 11 | **TOTP-ს ბექაპ კოდები არ აქვს** | Supabase TOTP-ს recovery კოდები არ აქვს; გასაღები შეინახე პაროლების მენეჯერში. დაკარგვისას — `ADMIN_REQUIRE_MFA=false` + restart + factor-ის წაშლა Dashboard-ში (§8) |

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
