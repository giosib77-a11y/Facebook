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
- **status:** open

### A-012 — `/docs`, `/redoc`, `/openapi.json` production-ში ღიაა
- **severity:** nit
- **file:** `backend/app/main.py:40-44`
- **სცენარი:** ნებისმიერი სტუმარი ხსნის `https://chatassist.ge/docs`-ს.
- **შედეგი:** სრული API სქემა (ადმინის route-ების ჩათვლით) ჩანს. exploit არ არის — ყველა route სერვერზე მოწმდება.
- **გამოსწორება:** production-ში `FastAPI(docs_url=None, redoc_url=None, openapi_url=None)`.
- **owner:** backend-dev
- **status:** open

### A-013 — Storage-ის ნედლი შეცდომა კლიენტს უბრუნდება
- **severity:** nit
- **file:** `backend/app/api/products.py:184-185`
- **სცენარი:** Storage upload ვარდება.
- **შედეგი:** პასუხში `ატვირთვა ვერ მოხერხდა: {e}` — storage3-ის შიდა დეტალი (statusCode/error/message). საიდუმლო არ ჟონავს.
- **გამოსწორება:** ფიქსირებული ტექსტი + `logger.warning(..., exc_info=True)`.
- **owner:** backend-dev
- **status:** open

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
- **status:** open

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
