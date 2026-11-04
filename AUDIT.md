# Audit — ChatAssist

- **თარიღი:** 2026-10-18
- **Commit:** `9b4163a` (ბრენჩი `agent-system`)
- **სფერო:** მთელი პროექტი (backend `backend/app`, მიგრაციები `supabase/migrations/0001–0024`, frontend `frontend/src`)
- **რეჟიმი:** trusted (code-reviewer + security-auditor + tester; ყველა critical/should-fix ხელახლა გადამოწმდა კოდში)
- **Baseline:**
  - `pip check` ✅ · `compileall` ✅ · `ruff check app tests` ✅
  - `pytest -q` ✅ **263 passed**, 0 failed, 0 skipped, 2 warning (third-party deprecation: starlette testclient/httpx, google-genai)
  - `npm run build` ✅, `frontend/dist` აქტუალურია (`git status` სუფთა build-ის შემდეგ)
  - `npm audit --omit=dev` ✅ 0 vulnerabilities (dev-ში 1 high — იხ. A-014)
  - `pip-audit` — ლოკალურად **არ გაეშვა** (venv-ში არ არის დაყენებული; CI-ში ეშვება)
  - typecheck, frontend lint და frontend ტესტები პროექტში არ არის
- **რაოდენობა:** critical 2 (ორივე fixed) · should-fix 0 · nit 14 (12 აუდიტიდან + 2 /fix-ის გადამოწმებიდან)

Accepted Risks-ში (`PROJECT.md`) და Backlog-ში (`PROGRESS.md`) უკვე ჩაწერილი პუნქტები აქ აღარ მეორდება.

---

## Critical

### A-001 — Excel/CSV-ის ხელახალი ატვირთვა არსებულ პროდუქტებს ფასს, მარაგს და SKU-ს უნულებს
- **severity:** critical (ფული/მარაგი არასწორად)
- **file:** `backend/app/api/products.py:321-332`, `backend/app/services/import_products.py:191,206,226`
- **სცენარი:** UI ფასისა და მარაგის სვეტზე „— არცერთი —“-ს სთავაზობს (`frontend/src/panel/ProductsTab.jsx:302`, `importApi.js:8-14` — სავალდებულო მხოლოდ სახელია) და ამბობს, რომ ხელახალი ატვირთვა არსებულ პროდუქტებს განაახლებს (`ProductsTab.jsx:282`). გამყიდველი მარაგის გასაახლებლად ტვირთავს ფაილს მხოლოდ „სახელი, მარაგი“ სვეტებით. parser-ი მიუთითებელ ან ცარიელ სვეტზე აბრუნებს `price=0.0`, `quantity=0`, `sku=None`; update ყოველთვის წერს `name, price, quantity, sku`-ს (დაცულია მხოლოდ `description`).
- **შედეგი:** ყველა დამთხვეული პროდუქტის ფასი ხდება 0 და SKU იშლება. საჯარო შეკვეთის ჯამს სერვერი DB-იდან ითვლის, ამიტომ შეკვეთა 0 ₾-ზე იქმნება, ბოტი კი „ფასი დასაზუსტებელია“-ს ამბობს. სარკისებური შემთხვევა: ფაილი „სახელი, ფასი“ სვეტებით მარაგს ანულებს, პროდუქტი „არ არის მარაგში“ ხდება. ერთი ცარიელი უჯრა მითითებულ სვეტში ამ პროდუქტზე იგივე ეფექტს იძლევა. გაფრთხილება არ ჩანს.
- **გამოსწორება:** parser-მა მიუთითებელ/ცარიელ ველზე დააბრუნოს `None` (ან მითითებული ველების სია); update-ში ჩაიწეროს მხოლოდ მითითებული და არაცარიელი ველები (როგორც `description`-ზეა); ახალი პროდუქტის insert-ზე default 0 რჩება. ტესტები: ნაწილობრივი mapping (სახელი+მარაგი; სახელი+ფასი) და ცარიელი უჯრა არსებულ price/quantity/sku-ს ინარჩუნებს; import-ის update გზას ამჟამად ტესტი საერთოდ არ აქვს.
- **owner:** backend-dev
- **status:** fixed (verified) — commit `6a80cb9`. `backend/tests/test_import_update.py` (8 ტესტი): ძველ კოდზე 6 failed / 2 passed (insert default-ები და ცხადი მნიშვნელობები ძველზეც სწორი იყო), ახალზე 8/8; სრული `pytest -q` 271 passed. ქცევის შენიშვნა: ცარიელი უჯრით ფასის/SKU-ს გასუფთავება import-ით აღარ ხდება (როგორც `description`-ზე) — ეს ხელით რედაქტირებით კეთდება. code-reviewer-ის ხელახალი შემოწმება: fixed.

### A-002 — პროდუქტის რედაქტირება მოძველებულ მარაგს წერს და `processing`-ის დაკლებას აუქმებს (lost update)
- **severity:** critical (მარაგი არასწორად → overselling)
- **file:** `frontend/src/panel/ProductsTab.jsx:36-41,70-80`, `frontend/src/panel/OrdersTab.jsx:44`, `frontend/src/panel/ShopData.jsx:24-34`
- **სცენარი:** პანელი ჩაიტვირთა, პროდუქტ P-ის მარაგი 5-ია. „შეკვეთები“ ტაბში შეკვეთა (P×2) გადადის `new → processing`-ზე და RPC მარაგს 3-მდე აკლებს. `setStatus` მხოლოდ `loadOrders()`-ს იძახებს; პროდუქტები context-შია და მხოლოდ მაღაზიის შეცვლისას ან ხელით „↻“-ზე იტვირთება, ტაბის შეცვლა მათ არ ანახლებს. გამყიდველი P-ს მხოლოდ ფასს უცვლის: `startEdit` ფორმას ძველი snapshot-იდან ავსებს, PUT კი ყველა ველს აგზავნის, მათ შორის `quantity: 5`-ს.
- **შედეგი:** DB-ში მარაგი ისევ 5 ხდება. შეკვეთის შემდგომი გაუქმება +2-ს ამატებს, სულ 7 გამოდის. 2 ცალი ზედმეტად გაიყიდება და შეცდომა არსად ჩანს.
- **გამოსწორება:** (ა) PUT-ში გაიგზავნოს მხოლოდ შეცვლილი ველები (diff `startEdit`-ის snapshot-თან). backend უკვე `exclude_unset`-ს იყენებს (`products.py:368`), ამიტომ backend-ის ცვლილება არ სჭირდება. (ბ) `setStatus`-ის წარმატებაზე გამოიძახოს `loadProducts()`-იც. `npm run build` და `dist/` იმავე commit-ში.
- **owner:** frontend-dev
- **status:** fixed (reviewed) — commit `69290f0`. diff-ის ლოგიკა `frontend/src/panel/productDiff.js`-შია და ტესტით მოწმდება (`node --test frontend/src/panel/productDiff.test.js` → 7/7; „სრული payload“ ვერსიაზე 0/7). ის, რომ `ProductsTab` PUT-ში `diff`-ს აგზავნის და `OrdersTab` `loadProducts()`-ს იძახებს, დადასტურებულია მხოლოდ კოდის კითხვით (frontend-ზე UI ტესტები არ არის, ბრაუზერში არ შემოწმებულა). ხელით შესამოწმებლად: DevTools → Network, მხოლოდ ფასის შეცვლისას PUT body = `{"price": …}`. code-reviewer-ის ხელახალი შემოწმება: fixed.

---

## Should-fix

არ არის.

---

## Nit

### A-003 — მნიშვნელოვან ბიზნეს-წესებს ტესტი არ აქვს
- **severity:** nit
- **file:** `backend/tests/*`; კოდი: `backend/app/api/webhook.py:324-325`, `backend/app/api/admin.py:107`, `backend/app/api/orders.py:56-66`
- **სცენარი:** (1) `DAILY_ABUSE_CAP`: ყველა ტესტში `day_count: 1`-ია, ამიტომ წესის წაშლის შემდეგაც ყველა ტესტი გაივლის. (2) `_restore_bots` (upgrade approve → ბოტი ირთვება, Core Flow 6): `test_bot_limit.py` მხოლოდ downgrade-ს ამოწმებს. (3) `/public-menu`-ს `is_active` ფილტრი ტესტით არ მოწმდება.
- **შედეგი:** რეგრესია ამ წესებში CI-ს გაივლის.
- **გამოსწორება:** თითო offline ტესტი (`service_db` / `admin_db` fixture-ებით): `day_count=101` → პასუხი არ იგზავნება; approve upgrade → ზედმეტი ბოტები ჭერამდე ირთვება; `is_active=false` → მენიუში არ ჩანს. import-ის ტესტი A-001-ის ნაწილია.
- **owner:** backend-dev
- **status:** open

### A-004 — OAuth-ის fallback redirect (popup დაბლოკილია) landing-ზე მიდის და შედეგი იკარგება
- **severity:** nit
- **file:** `backend/app/api/facebook.py:54`, `backend/app/main.py:245-248`, `backend/app/config.py`
- **სცენარი:** fallback = `{FRONTEND_URL}/?fb=...`. `DEPLOYMENT.md`-ის მიხედვით `FRONTEND_URL` დომენის root-ია, `/` კი `/panel/landing.html`-ზე გადაამისამართებს query-ს გარეშე.
- **შედეგი:** popup-ის დაბლოკვისას გამყიდველი landing-ზე ხვდება და connect-ის შედეგს (ან შეცდომას) ვერ ხედავს. `FRONTEND_URL` (default `http://localhost:5500`) და `FB_APP_ID` production-ის სავალდებულო სიაში არ არის.
- **გამოსწორება:** fallback → `{_public_base()}/panel/?…`; `FRONTEND_URL`/`FB_APP_ID` → `missing_required_secrets()` (ან production warning).
- **owner:** backend-dev
- **status:** open

### A-005 — პროდუქტის შექმნის/წაშლის შემდეგ ლიმიტის მრიცხველი („N / ლიმიტი“) არ ახლდება
- **severity:** nit
- **file:** `frontend/src/panel/ProductsTab.jsx:87,100`
- **სცენარი:** `onSubmit`/`remove` იძახებს მხოლოდ `loadProducts()`-ს, `loadUsage()`-ს არა.
- **შედეგი:** usage-ის ბლოკი მოძველებულ რაოდენობას აჩვენებს, სანამ გვერდი არ განახლდება.
- **გამოსწორება:** შექმნა/წაშლა/import-ის შემდეგ `loadUsage()`.
- **owner:** frontend-dev
- **status:** open

### A-006 — ვალუტის ჩვენება: ჯამი ყოველთვის „₾“, Dashboard ამრგვალებს
- **severity:** nit
- **file:** `frontend/src/order/OrderPage.jsx:208,304`, `frontend/src/panel/Dashboard.jsx:334`
- **სცენარი:** შეკვეთის ფორმაში პოზიციები მაღაზიის `currency`-ით ჩანს, ჯამი კი ყოველთვის „₾“-ით. Dashboard-ზე `toFixed(0)` 89.50-ს „90 ₾“-ად აჩვენებს.
- **შედეგი:** არა-₾ მაღაზიაში ჯამის ვალუტა არასწორად ჩანს; ბოლო შეკვეთების თანხა დამრგვალებულია.
- **გამოსწორება:** ჯამთან `{currency}`; Dashboard-ზე `toFixed(2)`.
- **owner:** frontend-dev
- **status:** open

### A-007 — ლიმიტს გადაცილებულ კლიენტს ერთი და იგივე auto-reply ყოველ შეტყობინებაზე მიდის
- **severity:** nit
- **file:** `backend/app/api/webhook.py:346-351`
- **სცენარი:** over-limit კლიენტი წერს რამდენჯერმე.
- **შედეგი:** „ოპერატორი მალე დაგიკავშირდებათ“ მეორდება (დღეში 100-მდე); ყოველ ჯერზე Send API-ს გამოძახება.
- **გამოსწორება:** გაგზავნა მხოლოდ მაშინ, როცა საუბარი ჯერ `needs_attention` არ არის.
- **owner:** backend-dev
- **status:** open

### A-008 — ადმინის ხელით tier-ის ცვლა მფლობელის pending upgrade-მოთხოვნას არ აუქმებს
- **severity:** nit
- **file:** `backend/app/api/admin.py:379-383`
- **სცენარი:** მფლობელს pending მოთხოვნა აქვს (მაგ. standard). ადმინი ხელით ცვლის tier-ს business-ზე, მერე ძველ მოთხოვნას ადასტურებს.
- **შედეგი:** tier გადაიწერება standard-ზე (დაწევა). A-8-ისგან განსხვავებულია: მოთხოვნა ლეგიტიმურად pending-ია.
- **გამოსწორება:** ხელით tier-ის ცვლისას მფლობელის pending მოთხოვნები → `cancelled` (არსებული `_cancel_pending_requests`-ის მსგავსად).
- **owner:** backend-dev
- **status:** open

### A-009 — import ერთნაირი სახელის რამდენიმე არსებული პროდუქტიდან ჩუმად პირველს ანახლებს
- **severity:** nit
- **file:** `backend/app/api/products.py:296-298`
- **სცენარი:** მაღაზიაში 2 პროდუქტია ერთი სახელით და SKU-ს გარეშე; ფაილში იგივე სახელი წერია.
- **შედეგი:** განახლდება მხოლოდ პირველი (`setdefault`); მეორე უცვლელი რჩება და გაფრთხილება არ ჩანს.
- **გამოსწორება:** ორაზროვან სახელზე მწკრივის შეცდომა („რამდენიმე პროდუქტი ამ სახელით — მიუთითე SKU“).
- **owner:** backend-dev
- **status:** open

### A-010 — `POST /orders`-ის დღიური bucket მაღაზიის შემოწმებამდე იქმნება (მეხსიერების ზრდა)
- **severity:** nit
- **file:** `backend/app/api/orders.py:82-89`, `backend/app/core/ratelimit.py:131-135`
- **სცენარი:** თავდამსხმელი ყოველ მოთხოვნას შემთხვევითი `shop_id` UUID-ით აგზავნის. `check_rate_limit` ახალ `ip|shop_id` key-ს მაღაზიის არსებობის შემოწმებამდე ქმნის, 24-საათიანი window-ით.
- **შედეგი:** ერთი IP-დან (10/წთ) დღეში ~14 400 key; ათეულობით IP-დან Starter-ის მეხსიერება შეიძლება ამოიწუროს (OOM → restart → in-memory ლიმიტების განულება). მონაცემი არ იკარგება.
- **გამოსწორება:** დღიური `check_rate_limit` გადავიდეს `shop` select-ის შემდეგ (უცნობი UUID → 404 bucket-ის გარეშე; ეს გზა უკვე 10/წთ/IP-ითაა შეზღუდული).
- **owner:** backend-dev
- **status:** open

### A-011 — `is_production` allowlist-ია: `APP_ENV`-ის უცნობი მნიშვნელობა production-ის დაცვებს თიშავს
- **severity:** nit
- **file:** `backend/app/config.py:94-95`
- **სცენარი:** Render-ზე `APP_ENV=live`/`prd`/`staging` (typo ან ახალი გარემო).
- **შედეგი:** ითიშება fail-closed startup, OAuth nonce-ის შემოწმება და XFF-ზე დაფუძნებული IP; იხსნება `/test-chat` (Gemini ავთენტიფიკაციის გარეშე); კლიენტს DB-ის შეცდომის დეტალი უბრუნდება. ლაივზე `env=production` დადასტურებულია, ამიტომ ეს მხოლოდ კონფიგურაციის შეცდომის რისკია.
- **გამოსწორება:** შებრუნებული ლოგიკა: არა-production მხოლოდ ცხადი `development|dev|test`; ან უცნობი მნიშვნელობა → startup `RuntimeError`.
- **owner:** backend-dev
- **status:** superseded by A-019 (2026-11-03)

### A-012 — `/docs`, `/redoc`, `/openapi.json` production-ში ღიაა
- **severity:** nit
- **file:** `backend/app/main.py:40-44`
- **სცენარი:** ნებისმიერი სტუმარი ხსნის `https://chatassist.ge/docs`-ს.
- **შედეგი:** სრული API სქემა (ადმინის route-ების ჩათვლით) ჩანს. exploit არ არის — ყველა route სერვერზე მოწმდება.
- **გამოსწორება:** production-ში `FastAPI(docs_url=None, redoc_url=None, openapi_url=None)`.
- **owner:** backend-dev
- **status:** fixed via A-022 (`203754f`)

### A-013 — Storage-ის ნედლი შეცდომა კლიენტს უბრუნდება
- **severity:** nit
- **file:** `backend/app/api/products.py:184-185`
- **სცენარი:** Storage upload ვარდება.
- **შედეგი:** პასუხში `ატვირთვა ვერ მოხერხდა: {e}` — storage3-ის შიდა დეტალი (statusCode/error/message). საიდუმლო არ ჟონავს.
- **გამოსწორება:** ფიქსირებული ტექსტი + `logger.warning(..., exc_info=True)`.
- **owner:** backend-dev
- **status:** fixed via A-023 (`023dd43`)

### A-014 — dev dependency `source-map-js` (high, GHSA-68fv-2mgg-jv7q)
- **severity:** nit
- **file:** `frontend/package-lock.json`
- **სცენარი:** `npm audit` (dev-ის ჩათვლით) → 1 high, event-loop DoS build-ის ინსტრუმენტში.
- **შედეგი:** runtime-ზე გავლენა არ აქვს (`npm audit --omit=dev` → 0).
- **გამოსწორება:** lock-ის განახლება შემდეგ dependency bump-თან ერთად.
- **owner:** frontend-dev
- **status:** open

### A-015 — რედაქტირების ფორმა მარაგს ფორმის გახსნის მომენტით აჩვენებს (A-002-ის ნარჩენი)
- **severity:** nit
- **file:** `frontend/src/panel/ProductsTab.jsx:39-45`
- **სცენარი:** გამყიდველი რედაქტირებას ხსნის (მარაგი 5); ამასობაში შეკვეთის დადასტურება მარაგს 3-მდე აკლებს. გამყიდველს 10-ის დამატება უნდა და წერს 15-ს.
- **შედეგი:** ჩაიწერება აბსოლუტური 15, ანუ დაკლებული 2 იკარგება. ეს ცხადი ხელით ჩანაწერია, ჩუმი overwrite აღარ არის (A-002 დაიხურა). პანელს polling არ აქვს.
- **გამოსწორება:** `startEdit`-ში პროდუქტის თავიდან წამოღება (`GET`), ან მინიშნება ველთან („მარაგი შეიძლება შეიცვალა — განაახლე“).
- **owner:** frontend-dev
- **status:** open

### A-016 — frontend-ის ტესტი CI-ში არ ეშვება
- **severity:** nit
- **file:** `frontend/package.json`, `.github/workflows/ci.yml`
- **სცენარი:** `productDiff.test.js` მხოლოდ ხელით ეშვება (`node --test`); `test` script და CI-ის ნაბიჯი არ არის.
- **შედეგი:** A-002-ის diff ლოგიკის რეგრესია CI-ს გაივლის.
- **გამოსწორება:** `"test": "node --test src/panel/"` და CI-ის frontend job-ში `npm test`.
- **owner:** frontend-dev
- **status:** fixed (Stage 13, 2026-10-27: Vitest `npm test` + CI-ის frontend job — S13-2, S13-5)

---

## გარე code review — 2026-11-03 (commit `ba295b1`, ბრენჩი `agent-system`)

მფლობელის მიერ გადმოცემული გარე review; ხუთივე მიგნება კოდში დადასტურდა. A-019 ანაცვლებს A-011-ს.

### A-017 — Meta Data Deletion: წაშლის შეცდომები იყლაპება, status ყოველთვის „completed"
- **severity:** should-fix (privacy: Meta-ს/მომხმარებელს წაშლა დადასტურებულად ეუწყება, თუმცა შეიძლება არ მომხდარა)
- **file:** `backend/app/api/facebook.py:351-375` (`except Exception: pass` სამ ადგილას), `:385-395` (`status: "completed"` ხელმოწერის შემოწმების შემდეგ ყოველთვის)
- **სცენარი:** Supabase დროებით მიუწვდომელია ან `delete` ვარდება → callback მაინც 200-ს და დადასტურების კოდს აბრუნებს; `delete-data.html` „✅ დადასტურდა"-ს აჩვენებს, მონაცემი კი ბაზაში რჩება და ამის კვალი არსად არის.
- **გამოსწორება:** მოთხოვნა ინახება ცხრილში `data_deletion_requests` (`pending` → `completed` / `failed`, migration 0029); შეცდომა ილოგება და სტატუსად იწერება; status endpoint ცხრილიდან კითხულობს.
- **owner:** backend-dev (+ `delete-data.html` სტატუსის ტექსტი)
- **status:** fixed (`6bfc16b`; ტესტი `test_data_deletion.py`; migration 0029 — მფლობელი)

### A-018 — საუბრების შენახვის ვადა არ სრულდება: `bot_conversations` არასდროს იშლება
- **severity:** should-fix (PII — კლიენტის შეტყობინებები — უვადოდ ინახება; privacy.html §6 ვადაზე საუბრობს)
- **file:** `backend/app/api/webhook.py:169` (ვადა მხოლოდ კითხვისას მოწმდება), `frontend/privacy.html:92-98`
- **სცენარი:** კლიენტი ერთხელ წერს და აღარ ბრუნდება → მისი შეტყობინებები + summary ბაზაში რჩება, სანამ მაღაზია არ წაიშლება. `BOT_MEMORY_HOURS` (24) მხოლოდ იმას განსაზღვრავს, ბოტი გამოიყენებს თუ არა ისტორიას.
- **გამოსწორება:** Supabase `pg_cron` (Render-ის უფასო გეგმაზე cron არ არის) საათში ერთხელ შლის ვადაგასულ ჩანაწერებს (migration 0030); privacy.html §6 განახლდება.
- **owner:** backend-dev (+ frontend-dev: privacy.html)
- **status:** fixed (`9ed57c4`; ტესტი `test_conversation_retention.py` — სტატიკური, რეალურ Postgres-ზე არ შემოწმებულა; migration 0030 — მფლობელი). ღია handoff (`needs_attention`) რჩება მოგვარებამდე, მაქს. 30 დღე.

### A-019 — `APP_ENV`-ის უცნობი მნიშვნელობა production-ის დაცვებს თიშავს (A-011-ის ჩანაცვლება)
- **severity:** should-fix (fail-open კონფიგურაცია: typo → `/test-chat` ღიაა, fail-closed startup და nonce-ის შემოწმება ითიშება)
- **file:** `backend/app/config.py:121-123`
- **სცენარი:** `APP_ENV=prd` / `live` / `staging` → `is_production=False` → აპი ჩუმად dev რეჟიმში ირთვება.
- **გამოსწორება:** non-production მხოლოდ ცხადი `development | dev | test`; `production | prod` → production; ნებისმიერი სხვა მნიშვნელობა → startup-ზე ValidationError (აპი არ ირთვება).
- **owner:** backend-dev
- **status:** fixed (`07b57da`; ტესტი `test_config_env.py`)

### A-020 — `POST /orders` idempotency არ აქვს: განმეორებული მოთხოვნა მეორე შეკვეთას ქმნის
- **severity:** should-fix (ჩვეულებრივ გამოყენებაში: მობილური ქსელის timeout → ხელახლა გაგზავნა → დუბლიკატი შეკვეთა)
- **file:** `backend/app/api/orders.py:201-222`, `frontend/src/order/OrderPage.jsx:141-166`
- **სცენარი:** სერვერმა შეკვეთა ჩაწერა, პასუხი გზაში დაიკარგა (ან proxy-ს 502/504) → ღილაკი ისევ აქტიურდება → მყიდველი ხელახლა აგზავნის → ორი `new` შეკვეთა. Accepted Risk #5 („ღილაკი ითიშება") ამ შემთხვევას არ ფარავს.
- **გამოსწორება:** frontend ფორმაზე ერთ `idempotency_key`-ს (UUID) ქმნის; backend `(shop_id, idempotency_key)`-ზე unique index-ით (migration 0031) არსებულ შეკვეთას აბრუნებს, ახალს არ ქმნის.
- **owner:** backend-dev + frontend-dev
- **status:** fixed (`49fdb40`; ტესტები `test_order_idempotency.py`, `OrderPage.test.jsx`; migration 0031 — მფლობელი)

### A-021 — webhook ყოველ event-ზე `products.select("*")`-ს ტვირთავს
- **severity:** nit (მონაცემთა მინიმიზაცია / ზედმეტი ტრაფიკი; ფუნქციური შეცდომა არ არის)
- **file:** `backend/app/api/webhook.py:351-358`
- **სცენარი:** ყოველ შემოსულ შეტყობინებაზე იტვირთება მაღაზიის ყველა აქტიური პროდუქტის ყველა სვეტი (`shop_id`, `is_active`, `created_at`, `updated_at` …), რომელსაც ბოტი არ იყენებს; ახალი სვეტი ავტომატურად მოხვდება ბოტის მეხსიერებაში.
- **გამოსწორება:** მხოლოდ ბოტის სვეტები (`id, name, price, quantity, sku, description, image_url, image_description`); `image_description`-ის გარეშე (0028 არ არის) — fallback.
- **owner:** backend-dev
- **status:** fixed (`31111a9`; ტესტი `test_webhook_product_columns.py`). `/test-chat` (`api/chat.py:44-52`) ჯერ ისევ `select("*")`-ს იყენებს — Backlog.

### შემოწმება (2026-11-03, ბოლო commit-ის შემდეგ)
pytest **1825 passed** (1783 → +42) · ruff ✅ · compileall ✅ · frontend lint 0 error / 5 warning (იგივე) · `npm test` 31/31 (29 → +2) · `npm run build` → `dist` commit-შია. pip-audit / `npm audit` ამ სესიაში არ გაეშვა (dependency არ შეცვლილა). **დაუდასტურებელი:** მიგრაციები 0029–0031 რეალურ Postgres-ზე (ტესტები SQL-ს მხოლოდ სტატიკურად ამოწმებს), pg_cron-ის რეალური გაშვება, Meta-ს რეალური callback.

### Proposed Accepted Risks (მფლობელის გადაწყვეტილება; კოდი არ იცვლება)
საერთო მიზეზი: production ერთ Render instance-ზეა, `WEB_CONCURRENCY=1` (ერთი process) — ყველა in-memory state ერთ ადგილასაა და ერთმანეთს არ ეწინააღმდეგება. გადახედვის პირობა ყველასთვის: >1 instance/worker ან ხშირი restart-ები.
- **webhook-ის მდგრადი queue არ არის** (`BackgroundTasks`) — უკვე Accepted Risk #6; crash/deploy-ზე მიმდინარე შეტყობინება იკარგება.
- **`_SEEN_MIDS` (webhook dedup) process-memory-შია** (`webhook.py:30`) — restart-ზე ნულდება; Meta-ს retry restart-ის შემდეგ ერთ შეტყობინებაზე მეორე პასუხს გამოიწვევს (იშვიათი, უვნებელი). Decision Log 2026-08.
- **rate limiter-ის state საერთო არ არის** (`core/ratelimit.py`, `webhook._RATE_HITS`) — უკვე Accepted Risk #9; რამდენიმე worker-ზე ლიმიტი N-ჯერ გაიზრდება.
- **`track_bot_customer` fail-open** (`webhook.py:386-410`): RPC-ის შეცდომაზე ბოტი პასუხობს ლიმიტის შემოწმების გარეშე. შეგნებული: DB-ის ხარვეზისას კლიენტს პასუხი არ დაეკარგოს; ზედა ზღვარი — webhook-ის წუთობრივი ლიმიტი (6/psid, 30/shop). გადახედვა: ავტომატური ბილინგი ან ხშირი RPC-შეცდომები ლოგში.
- **`POST /orders`-ის დღიური bucket მაღაზიის შემოწმებამდე იქმნება** — A-010 (nit, Backlog-ში); ერთი instance-ის მეხსიერებაზე გავლენა მცირეა (10/წთ/IP ლიმიტით).

---

## გარე აუდიტი (PDF) — 2026-11-03, ეტაპი 1 (commit `3c7cd9a`, ბრენჩი `main`)

წყარო: `docs/external-audit-2026-11-03.pdf` (`.gitignore`-ით git-ში არ არის). ID ფრჩხილებში — PDF-ის N-ნომერი. ეტაპი 1 = სწრაფი და დაბალი რისკის მიგნებები (მფლობელის სია). დანარჩენი (N-01…N-05, N-06-ის MFA/audit log/recovery, N-07…N-10, N-12, N-18) — ეტაპი 2/3, აქ არ შედის. ყველა მიგნება ჩაწერამდე ახლანდელ კოდში გადამოწმდა (2026-11-03, `a498a1f`). გეგმა და task-ები — `PROGRESS.md` Stage 19.

### A-022 (N-13) — `/docs`, `/redoc`, `/openapi.json` production-ში ღიაა (ანაცვლებს A-012-ს)
- **severity:** nit (ინფორმაციის გამჟღავნება; ყველა route სერვერზე მოწმდება)
- **file:** `backend/app/main.py:66-70` (`FastAPI(...)` docs პარამეტრების გარეშე)
- **გამოსწორება:** production-ში `docs_url=None, redoc_url=None, openapi_url=None`; dev-ში უცვლელი.
- **owner:** backend-dev · **task:** S19-1
- **status:** fixed (`203754f`; ტესტი `test_docs_production.py`). A-012 დაიხურა.

### A-023 (N-14) — Storage-ის ნედლი შეცდომა კლიენტს უბრუნდება (ანაცვლებს A-013-ს)
- **severity:** nit
- **file:** `backend/app/api/products.py:239` (`f"ატვირთვა ვერ მოხერხდა: {e}"`)
- **გამოსწორება:** ფიქსირებული ტექსტი; დეტალი — `logger.warning(..., exc_info=True)` shop id-ით.
- **owner:** backend-dev · **task:** S19-3
- **status:** fixed (`023dd43`; ტესტი `test_upload_error.py`). A-013 დაიხურა. nit (Backlog): `/admin/recovery` (`admin.py`) ჯერ `{e}`-ს აბრუნებს.

### A-024 (N-06, ნაწილი) — `resolve_upgrade_request` არ ამოწმებს `status == 'pending'`
- **severity:** should-fix (ფული: უკვე უარყოფილი / გაუქმებული / დადასტურებული მოთხოვნის ხელახალი approve პაკეტს ცვლის)
- **file:** `backend/app/api/admin.py:444-470`
- **სცენარი:** ადმინი ძველ (rejected/cancelled) მოთხოვნას ადასტურებს → მფლობელის ყველა მაღაზია `requested_tier`-ზე გადადის; დადასტურებულის ხელახალი approve ხელით შეცვლილ tier-ს გადაწერს.
- **გამოსწორება:** `status != 'pending'` → 409, არაფერი იცვლება; სტატუსის საბოლოო update `.eq("status", "pending")` ფილტრით. MFA / audit log / recovery-ის ბმული — ეტაპი 2/3.
- **owner:** backend-dev · **task:** S19-4
- **status:** fixed (`500f1be`; ტესტი `test_upgrade_resolve.py`; `test_bot_limit.py`-ის fixture-ს `status: pending` დაემატა)

### A-025 (N-11) — Facebook-ის popup-ის `message` listener `e.origin`-ს და `e.source`-ს არ ამოწმებს
- **severity:** nit (ნებისმიერ ფანჯარას შეუძლია ყალბი toast / პანელის reload; მონაცემი არ იცვლება)
- **file:** `frontend/src/panel/fbConnect.js:19-24`
- **გამოსწორება:** მიიღება მხოლოდ `e.origin === new URL(APP_CONFIG.API_BASE).origin` (callback-ის HTML backend-იდან მოდის) **და** `e.source === popup` (`startConnect`-ში გახსნილი ფანჯარა); დანარჩენი — ჩუმად იგნორდება. ბუფერი და fallback redirect უცვლელი.
- **owner:** frontend-dev · **task:** S19-10
- **status:** fixed (`ee15bd9`; ტესტი `fbConnect.test.js`; რეალურ ბრაუზერში — unverified)

### A-026 (N-15) — `_SEEN_MIDS` და `ratelimit._sweep` / `_hit` / `allow` lock-ის გარეშეა
- **severity:** nit (sync handler-ები threadpool-ში ერთდროულად მუშაობს: dict-ის იტერაცია ცვლილებისას → `RuntimeError` → 500; dedup-ის race → ორმაგი პასუხი)
- **file:** `backend/app/api/webhook.py:30,67-83`, `backend/app/core/ratelimit.py:78-130`
- **გამოსწორება:** `threading.Lock` (როგორც `_RATE_HITS`/`_RATE_LOCK`-ში): `_already_handled` მთლიანად lock-ში; ratelimit-ში `_sweep` + deque-ის შემოწმება/დამატება ერთ lock-ში (`HTTPException` lock-ის გარეთ ისვრის).
- **owner:** backend-dev · **task:** S19-5
- **status:** fixed (`93392f7`; ტესტი `test_inmemory_locks.py` — სტრუქტურული ტესტები ძველზე ვარდება; race GIL-ის გამო საიმედოდ ვერ რეპროდუცირდება)

### A-027 (N-16) — disconnect webhook-ის გამოწერას (`subscribed_apps`) არ აუქმებს
- **severity:** should-fix (privacy: გათიშვის შემდეგ Meta ამ გვერდის შეტყობინებებს ისევ გვიგზავნის)
- **file:** `backend/app/api/facebook.py:425-444`, `backend/app/services/facebook.py:244-250`
- **გამოსწორება:** DB-ის გასუფთავებამდე `DELETE /{page_id}/subscribed_apps` page token-ით (best-effort: Graph-ის / გაშიფვრის შეცდომა ილოგება, disconnect მაინც სრულდება).
- **owner:** backend-dev · **task:** S19-7
- **status:** fixed (`013c3e4`; ტესტი `test_disconnect_unsubscribe.py`; რეალური Graph DELETE — unverified)

### A-028 (N-17) — `download_image`: არა-სურათი `image/jpeg`-ად ინიშნება; DNS-ის შემოწმება და კავშირი ცალ-ცალკე resolve-დება
- **severity:** nit (defense-in-depth: DNS rebinding-ით SSRF-ის ფანჯარა; HTML/JSON LLM-ს სურათად მიეწოდება)
- **file:** `backend/app/services/facebook.py:289-323,353-408`
- **გამოსწორება:** `content-type` არ იწყება `image/`-ით ან არ არის → `None`; კავშირი იმ IP-ზე, რომელიც შემოწმდა (URL-ში IP, `Host` header + TLS `sni_hostname` = ორიგინალი host; `trust_env=False`), ყოველ redirect-ზე თავიდან.
- **owner:** backend-dev · **task:** S19-8
- **status:** fixed (`7aa9c2d`; ტესტი `test_image_download.py`; რეალური FB CDN / TLS SNI IP-ზე — unverified)

### A-029 (N-19) — მაღაზიების ლიმიტის შემოწმება და INSERT ცალ-ცალკეა (race)
- **severity:** should-fix (`PROJECT.md`-ის პაკეტის წესი ირღვევა: ორი პარალელური `POST /shops` ლიმიტზე მეტ მაღაზიას ქმნის)
- **file:** `backend/app/api/shops.py:76-104`
- **გამოსწორება:** RPC `create_shop_limited` (migration `0032`, SECURITY DEFINER, `pg_advisory_xact_lock` მფლობელზე → count → insert ერთ ტრანზაქციაში; EXECUTE მხოლოდ `service_role`); 0032-ის გარეშე — ძველი გზა + ერთჯერადი WARNING.
- **owner:** backend-dev · **task:** S19-9
- **status:** fixed (`97e4f75`; ტესტები `test_create_shop_limit.py`, `test_migration_0032.py`; migration 0032 — მფლობელი; რეალურ Postgres-ზე — unverified)

### A-030 (N-20) — Data Deletion `bot_customers`-ში psid-ს ტოვებს
- **severity:** should-fix (privacy: წაშლა დადასტურებულად ეუწყება, კლიენტის იდენტიფიკატორი კი რჩება)
- **file:** `backend/app/api/facebook.py:384-401` (`_erase_fb_user_data`)
- **გამოსწორება:** `bot_customers.delete().eq("psid", user_id)` (იგივე user_id, რაც `bot_conversations`-ზე); შეცდომა ზემოთ ადის (A-017).
- **owner:** backend-dev · **task:** S19-6
- **status:** fixed (`b2fbf32`; ტესტი `test_data_deletion.py`) → **superseded by A-039 (2026-11-04):** Meta-ს დოკუმენტაციით callback-ის `user_id` app-scoped ID-ია (ASID, გამყიდველი), `bot_customers.psid` / `bot_conversations.psid` — page-scoped (PSID); psid-ით წაშლა არაფერს შლიდა. S20-5-ში psid-ით ნაბიჯები იხსნება და `bot_customers` / საუბრები გამყიდველის მაღაზიის `shop_id`-ით იშლება.

### A-031 (N-21) — `dist`-ის არარსებობისას `/panel` მთელ `frontend/` წყაროს ასერვირებს
- **severity:** nit (მხოლოდ build-ის გარეშე: `package.json`, `src/**`, `node_modules/**`, `vite.config.js` საჯაროდ ჩანს; `dist` git-შია და CI ამოწმებს)
- **file:** `backend/app/main.py:309-323`
- **გამოსწორება:** fallback სრულად იხსნება (მფლობელის გადაწყვეტილება, 2026-11-03): `/panel` მხოლოდ `frontend/dist`-იდან; `dist/index.html`-ის გარეშე `/panel` არ mount-დება + WARNING.
- **owner:** backend-dev · **task:** S19-2
- **status:** fixed (`dba6f30`; ტესტი `test_frontend_fallback.py`)

### A-032 (N-22) — supabase-js-ის no-op `lock`: refresh token-ის race ტაბებს შორის
- **severity:** nit (შესაძლო შემთხვევითი logout ორ ტაბში; რეალურ ბრაუზერში დაუდასტურებელი)
- **file:** `frontend/src/panel/supabase.js:19-22`
- **გამოსწორება:** `lock` პარამეტრი იშლება (ნაგულისხმევი navigator lock). popup-ის ცალკე გადაწყვეტა: popup (`about:blank` → Facebook → backend-ის callback HTML) supabase-js-ს საერთოდ არ ტვირთავს, ამიტომ lock მას ვერ ჩაკეტავს; `readStoredToken` და `refreshToken`-ის 8 წმ timeout რჩება.
- **owner:** frontend-dev · **task:** S19-11
- **status:** fixed (`6f6d644`; ტესტი `supabase.test.js`; ორი tab / popup რეალურ ბრაუზერში — unverified)

### A-033 (N-23) — `requirements.lock.txt`-ს hash-ები არ აქვს; GitHub Actions tag-ზეა მიბმული
- **severity:** nit (supply chain)
- **file:** `backend/requirements.lock.txt`, `.github/workflows/ci.yml:19-20,42-43`
- **გამოსწორება:** `pip-compile --generate-hashes` Linux-ზე (Docker `python:3.14.3-slim`), არსებული ვერსიები უცვლელი; CI-ში lock ცალკე `--require-hashes`-ით; `actions/*` → commit SHA (`# vX` კომენტარით).
- **owner:** task-executor · **task:** S19-12
- **status:** fixed (`f1779c8`; Render-ის hash-mode build — unverified რეალურ deploy-მდე)

### A-034 — README-ის აცდენა
- **severity:** nit
- **file:** `README.md:109,111,179` (+ §7 მიგრაციების სია)
- **სცენარი:** README: Python 3.11+, React 18, 28 მიგრაცია; რეალურად Python 3.14 (CI 3.14.3), React 19, 31 (S19-9-ის შემდეგ 32).
- **owner:** task-executor · **task:** S19-13
- **status:** fixed (S19-13)

---

## გარე აუდიტი (PDF) — 2026-11-03, ეტაპი 2 (ბრენჩი `agent-system`)

წყარო: `docs/external-audit-2026-11-03.pdf` (git-ში არ არის), ეტაპი 2 „ფული და ნდობა" (N-01, N-02, N-03, N-07) + Stage 19-ის finish-check-ის „შესამოწმებელი" (Data Deletion, Meta-ს დოკუმენტაციით დადასტურებული). ყველა მიგნება კოდში გადამოწმდა (2026-11-04, `ae00bf9`). სიმძიმე ჩვენი სკალით: critical = ფული/მონაცემი/ნდობა იკარგება ახლა. გეგმა და task-ები — `PROGRESS.md` Stage 20; გადაწყვეტილებები — `PROJECT.md` Decision Log 2026-11-04 („Stage 20").

### A-035 (N-01) — handoff ბოტს არ აჩერებს; გამყიდველის ხელით პასუხი ბოტისთვის უხილავია
- **severity:** critical (ნდობა: handoff-ის შემდეგ ბოტი ყოველ ახალ შეტყობინებას პასუხობს, სანამ გამყიდველიც წერს — გამყიდველის დაპირებას (ფასდაკლება, მიწოდების ვადა) არ იცნობს და შეიძლება ეწინააღმდეგებოდეს)
- **file:** `backend/app/api/webhook.py:383-384` (`is_echo` → `continue`), `:466-470` (`run_turn` `needs_attention`-ის შემოწმების გარეშე), `:216-218` (`needs_attention` მხოლოდ იწერება), `backend/app/services/facebook.py:244-250` (`subscribed_fields` `message_echoes`-ის გარეშე — echo საერთოდ არ მოდის)
- **სცენარი:** კლიენტი ითხოვს ოპერატორს → `needs_attention` → გამყიდველი Messenger-ში წერს „10% ფასდაკლება" → კლიენტის შემდეგ შეტყობინებას ბოტი პასუხობს ძველი ფასით.
- **გამოსწორება:** `bot_conversations.bot_paused_until` (0033); handoff-ზე და გამყიდველის echo-ზე (`app_id` ≠ `FB_APP_ID`) პაუზა 12 სთ ან „მოგვარებულია"/„ბოტის ჩართვა"-მდე; echo-ს ტექსტი ისტორიაში (`role: "operator"`); `message_echoes` გამოწერაში; პანელში „ბოტი შეჩერებულია" + „ბოტის ჩართვა".
- **owner:** backend-dev, frontend-dev · **task:** S20-3, S20-4, S20-13
- **status:** ღია — S20-3 / S20-4 / S20-13

### A-036 (N-02) — ფასიანი პაკეტი არასდროს იწურება
- **severity:** critical (ფული: ერთი თვის გადახდით პაკეტი სამუდამოდ რჩება; `paid_until` არსად არ არის)
- **file:** `backend/app/api/admin.py:457-469` (`resolve_upgrade_request` tier-ს `shops.subscription_tier`-ში უვადოდ წერს), `:379-383` (ადმინის tier-ის ცვლა), `backend/app/api/shops.py:265-321` (downgrade — ერთადერთი გზა უკან)
- **გამოსწორება:** `subscriptions (owner_id, tier, paid_until)` (0034) + დღიური pg_cron (ვადაგასული → `free` + ბოტების ჭერი); არსებულ ფასიანებს `now() + 30 days`; `shops.subscription_tier` — სარკე; პანელში გაფრთხილება 3 დღით ადრე; ადმინში „ვადა" + გაგრძელება.
- **owner:** backend-dev, frontend-dev · **task:** S20-6, S20-7, S20-14, S20-15
- **status:** ღია — S20-6 / S20-7 / S20-14 / S20-15

### A-037 (N-03) — LLM-ის ხარჯს ჭერი არ აქვს
- **severity:** critical (ფული: `llm_usage` მხოლოდ იწერება; უფასო მაღაზია: 30 კლიენტი × 100 შეტყობინება/დღე ≈ 90 000/თვე, თითოზე ≤4 LLM გამოძახება + ფოტო + summary; Stage 14+ deploy-ის ბლოკერი)
- **file:** `backend/app/services/llm.py:474-489` (`record_usage` — მხოლოდ ჩაწერა), `backend/app/api/webhook.py:466-470` (`run_turn` ბიუჯეტის შემოწმების გარეშე), `backend/app/core/tiers.py:37` (`DAILY_ABUSE_CAP = 100` ყველა პაკეტზე), `backend/app/services/graph.py:29` (`MAX_LLM_CALLS = 4`)
- **გამოსწორება:** თვიური ტოკენ-ბიუჯეტი პაკეტზე (per-account, env) `run_turn`-მდე, RPC `llm_tokens_used` (0035); ამოწურვა / დღიური გლობალური ჭერი / `LLM_KILL_SWITCH` → ოპერატორის გზა; უფასოზე კლიენტის დღიური ჭერი 30; ≥80% → WARNING + ადმინ პანელი; provider-ის dashboard-ის spend limit — მფლობელი.
- **owner:** backend-dev, frontend-dev · **task:** S20-2, S20-8, S20-9, S20-15
- **status:** ღია — S20-2 / S20-8 / S20-9 / S20-15

### A-038 (N-07) — გამყიდველი და ადმინი პრობლემას ვერ იგებენ
- **severity:** should-fix (ახალი შეკვეთა და handoff მხოლოდ პანელში ჩანს; „BOT DOWN" — მხოლოდ Render-ის ლოგში; ადრე ხუთივე მაღაზია შეუმჩნევლად გაითიშა)
- **file:** `backend/app/api/webhook.py:358-369` (გაშიფვრის ჩავარდნა — `logger.error`), `:487-493` (გაგზავნის ჩავარდნა — `logger.exception`), `:216-218` (handoff — მხოლოდ flag), `backend/app/api/orders.py:215-246` (შეკვეთა — მხოლოდ DB)
- **გამოსწორება:** `services/notify.py` — email გამყიდველს (SMTP, stdlib `smtplib`) ახალ შეკვეთაზე და handoff-ზე; Telegram ადმინს „BOT DOWN"-ზე (გაშიფვრა, ვადაგასული token, გაგზავნა); key-ის გარეშე გამორთულია; in-memory throttle; `shops.bot_status` (0036) + პანელში ჯანმრთელობა და „შეტყობინებები გამორთულია" ნიშანი. Sentry/uptime — Backlog.
- **owner:** backend-dev, frontend-dev · **task:** S20-2, S20-10, S20-11, S20-12, S20-14
- **status:** ღია — S20-2 / S20-10 / S20-11 / S20-12 / S20-14

### A-039 — Data Deletion: callback psid-ით შლის (სხვა ID-სივრცე); გამყიდველის ASID და webhook-ის გამოწერა რჩება; კლიენტს მცდარი გზა ეუწყება
- **severity:** should-fix (privacy / Meta Platform Terms §3.d.i.1, §4.b: „completed"-ის შემდეგ `shops.facebook_user_id` (ASID) რჩება, გვერდი Meta-ზე გამოწერილი რჩება; `bot_conversations`/`bot_customers`-ის psid-ით წაშლა არაფერს შლის; `delete-data.html` კლიენტს „Apps and Websites"-ით ავტომატურ წაშლას ჰპირდება, რაც Messenger-ის კლიენტზე არ მუშაობს)
- **file:** `backend/app/api/facebook.py:384-403` (`_erase_fb_user_data`: ნაბიჯები 2–3 psid-ით; ნაბიჯი 1 — `facebook_user_id` არ სუფთავდება, `unsubscribe_page` არ იძახება, `bot_customers` shop-ით არ იშლება), `frontend/delete-data.html:43-60`, `frontend/privacy.html:120-124`
- **დადასტურება:** Meta-ს Data Deletion Callback-ის დოკუმენტაცია („app-scoped ID identifying the user"; ტრიგერი — აპის მოხსნა Apps and Websites-ში, Facebook Login-ის შემდეგ) და Messenger-ის PSID/ASID-ის განმარტება — ციტატები `PROJECT.md` Decision Log 2026-11-04.
- **გამოსწორება:** გამყიდველის ყოველ მაღაზიაზე: `unsubscribe_page` (best-effort), საუბრები + `bot_customers` `shop_id`-ით, page/IG/token/`facebook_user_id` = null, `bot_enabled = false`; psid-ის ნაბიჯები იხსნება; კლიენტისთვის — `DELETE /shops/{id}/customers/{psid}` (გამყიდველი, RLS) + privacy/delete-data/README-ის ტექსტი.
- **owner:** backend-dev, frontend-dev, task-executor · **task:** S20-5, S20-13, S20-16, S20-17
- **status:** ღია — S20-5 / S20-13 / S20-16 / S20-17

---

## /fix — 2026-10-18 (A-001, A-002)

- ბრენჩი: `agent-system` (მფლობელის არჩევანი; `fix/` ბრენჩი არ შექმნილა). commit-ები: `69290f0` (A-002), `6a80cb9` (A-001).
- მიზნობრივი გადამოწმება (code-reviewer, მხოლოდ შეცვლილი ფაილები): ორივე — fixed; ახალი critical/should-fix არ არის; ახალი nit-ები: A-015, A-016.
- საბოლოო შემოწმება vs baseline: pip check ✅, compileall ✅, ruff ✅, pytest **271 passed** (263 → +8), 0 failed, warnings იგივე 2; `node --test` productDiff 7/7 (ახალი); `npm run build` ✅, `dist` აქტუალური; `npm audit --omit=dev` 0. pip-audit — არ გაეშვა (იგივე მიზეზით).

---

## შესამოწმებელი (დაუდასტურებელი)

- **კლიენტების ჭერი per-shop-ია, გამოწერა კი per-account** (`webhook.py:324-327`, `shops.py:142-148`): standard პაკეტზე 2 მაღაზია = 2×ლიმიტი კლიენტი. `PROJECT.md` ამბობს „გამოწერა per-account“, `MONETIZATION.md`-ის ცხრილი ორაზროვანია. **მფლობელის გადაწყვეტილება.**
- **PDF-ცოდნა downgrade-ზე რჩება** (`shops.py` downgrade, `bot.py:207` ცოდნას tier-ის მიუხედავად იყენებს): წესი მხოლოდ „ატვირთვას“ ზღუდავს, თუმცა S11-5-ის PRE-CHECK („free-ს knowledge არ აქვს“) მიანიშნებს, რომ ჩანაფიქრი სხვა იყო. **მფლობელის გადაწყვეტილება.**
- **`track_bot_customer` (0004) თვესა და დღეს DB-ის `now()`-ით (UTC) ითვლის** — დღიური/თვიური მრიცხველი თბილისის დროით 04:00-ზე ნულდება. მისაღებია თუ არა — მფლობელი.
- **`FRONTEND_URL` Render-ზე** — რეალური მნიშვნელობა ვერ შემოწმდა (`.env`/Render env აგენტისთვის დახურულია); A-004-ის სიმძიმე ამაზეა დამოკიდებული.
- **IPv6** — თუ `chatassist.ge`-ს AAAA ჩანაწერი აქვს, IP-ლიმიტის key სრული IPv6 მისამართია და ერთ /64 ბლოკს პრაქტიკულად შეუზღუდავი key-ები აქვს (ყველა per-IP ლიმიტი + A-010 ერთი ჰოსტიდან). შემოწმება: `dig AAAA chatassist.ge`; თუ არის — key /64-მდე.
- **pip-audit** ლოკალურად არ გაეშვა; Python dependency-ების CVE სტატუსის ერთადერთი წყარო CI-ის `pip-audit` ნაბიჯია.

## Reviewer-ის მიგნებები, რომლებიც არ დადასტურდა ან შეიცვალა — და რატომ

- **„ტესტების ხარვეზები“ (code-reviewer: should-fix) → nit (A-003).** ფაქტი დადასტურდა (grep), მაგრამ ტესტის არარსებობა თავისთავად არც `PROJECT.md`-ის წესს არღვევს და არც ჩვეულებრივ გამოყენებაში იწვევს შეცდომას. import-ის ტესტი A-001-ის გამოსწორებაშია.
- **security-auditor-ის ხაზები `config.py:390-392` და `ratelimit.py:290-294` არასწორი იყო** (ფაილები 141 და 135 ხაზიანია); მიგნებები გადამოწმდა და ზუსტი ხაზებით ჩაიწერა (A-011, A-010).
- **Backlog-ის მოძველებული პუნქტები** (security-auditor, დადასტურდა): „0018: `authenticated`-ს `UPDATE(status)` ისევ აქვს“ უკვე დახურულია `0022_revoke_orders_knowledge_update.sql:46-47`-ით; A-9-ის ნარჩენი „production-ში secrets startup-ზე არ მოწმდება“ დახურულია `missing_required_secrets()`/`check_required_settings()`-ით (S11-6). `PROGRESS.md`-ის Backlog-იდან ამოსაღებია (ეს ფაილი აუდიტში არ შეცვლილა).
- security-auditor-მა critical/should-fix ვერ იპოვა; authN/authZ (40+ route), IDOR, RLS/grant-ების საბოლოო მდგომარეობა, webhook/OAuth/signed_request, ატვირთვები, XSS, logging და secrets git-ის ისტორიაში შემოწმდა და რიგზეა.
