# Progress

## Current Stage
Stage 14 — LLM provider: Gemini → Claude (default) / OpenAI; სამფენიანი cache-ზე მორგებული prompt; `llm_usage` (მფლობელის მოთხოვნა, 2026-10-28; „Stage A")

ID-ები S14-n; commit: `S14-n: ...`. ბრენჩი — მხოლოდ `agent-system` (**ყოველ commit-მდე** `git branch --show-current`; სხვა პასუხზე — გაჩერდი და ჰკითხე მფლობელს). `main`-ში merge **არ იგეგმება**, სანამ API key-ები არ იქნება.
**აგენტებს აკრძალული აქვთ:** `git push`, `main`-ში merge, deploy, remote Supabase-ზე migration/query, Anthropic / OpenAI / Meta / Gemini API-ს რეალური გამოძახება (ნებისმიერი key-ით), `.env`-ის წაკითხვა/შეცვლა, `.claude/`-ის ნებისმიერი ფაილის შეცვლა. key-ები მხოლოდ env-იდან (`Settings`), კოდში/ტესტებში/ლოგში — არასდროს.
ყველა ტესტი offline: fake Supabase (`tests/conftest.py`), LLM — fake client-ები (S14-4-დან conftest-ის guard რეალურ client-ს ბლოკავს), Graph — monkeypatch.
გადაწყვეტილებები და ვარაუდები — `PROJECT.md` Decision Log, 2026-10-28. შემდეგი ეტაპები (15–18) — `## Upcoming stages`.
Stage 13 — `## Stage 13 — Done`; Stage 12 — `## Stage 12 — Done`; Stage 11 — `## Stage 11 — Done`; Stage 10 — `## Stage 10 — Done`.

<!-- Stage 10 header (ისტორია):

აუდიტი 2026-10-08 (standard-reviewer, ორი ნაწილი: A — isolation/auth/secrets, B — public/webhook/bot/uploads).
ID-ები (A-n / B-n) commit message-ში იწერება: `fix(scope): ... (A-1)`.
შენიშვნა: მიგრაციის ფაილს აგენტი წერს, **გაშვება — მფლობელი, ხელით** (Supabase SQL Editor),
backend-ის deploy-მდე ან მის შემდეგ — task-ში მითითებული რიგით.
-->

## Tasks
> backend-ის ბრძანებები `backend/`-იდან: `.venv/Scripts/python.exe -m pytest -q`, `.venv/Scripts/python.exe -m ruff check app tests`, `.venv/Scripts/python.exe -m compileall -q app`. **საერთო „done when" ყველა backend task-ზე:** სამივე სუფთაა, pytest-ის რაოდენობა report-შია (საწყისი: 274 passed), არცერთი ტესტი ქსელს არ მიმართავს. frontend-ს ეხება მხოლოდ S14-9.
> რიგი: S14-1, S14-2, S14-3, S14-9 ერთმანეთისგან დამოუკიდებელია (S14-1 venv-ში პაკეტებს აყენებს → ეშვება **მარტო**, სხვა backend task-ის pytest-თან პარალელურად არა; S14-9 — frontend, პარალელურად შეიძლება) → S14-4 → S14-5 → S14-6 → S14-7 → S14-8. shared ფაილები — `## Shared files`.
> ტესტის წაშლა დაშვებულია მხოლოდ S14-5-ში (`test_gemini_timeout.py`, Gemini-ს კოდთან ერთად) და მხოლოდ იმ პირობით, რომ მისი გარანტიები ახალი ტესტებით დაფარულია (იხ. S14-4, S14-5).

- [x] **S14-1 — dependencies: `anthropic` + `openai` დამატება (`google-genai` ჯერ რჩება)** ✅ `anthropic>=2.3` (2.3.0), `openai>=3.40` (3.40.0); lock-ში +7: anthropic, docstring-parser, httpcore2, httpx2, jiter, openai, truststore (არსებული pin-ები უცვლელი); pip check ✅, pip-audit 0, jiter cp314 manylinux wheel ✅ (დანარჩენი pure-python); pytest 274. მიგნება: SDK-ები `retry-after`-ს ჭერის გარეშე იცავს → S14-4 შეიცვალა (`max_retries=0` + საკუთარი 1 retry ბიუჯეტით). · owner: task-executor · files: `backend/requirements.txt` (shared), `backend/requirements.lock.txt` (shared) · depends: —
  - `requirements.txt`: `anthropic>=<X>` და `openai>=<Y>` — floor = დაინსტალირებული ვერსიის major.minor; ვერსია უნდა უჭერდეს მხარს: anthropic — `messages.create`-ის top-level `cache_control`-ს და ბლოკის `ttl`-ს; openai — `responses.create`-ის `prompt_cache_key`-ს (SDK-ის კოდში/CHANGELOG-ში შემოწმება, report-ში). `google-genai>=1.0` **რჩება** (Gemini-ს კოდი ჯერ მას იყენებს; S14-7 შლის).
  - lock: `backend/.venv`-ში `.venv/Scripts/python.exe -m pip install "anthropic>=<X>" "openai>=<Y>"`; `pip freeze`-ის diff-ით დამატებული პაკეტები (მოსალოდნელი: `anthropic`, `openai`, `httpx2` და მისი დამოკიდებულებები, `jiter`, `docstring-parser`, `tqdm`… — მხოლოდ ის, რაც რეალურად დაემატა) lock-ში ზუსტი ვერსიით, ანბანურად; **არსებული pin-ები არ იცვლება** (თუ resolver აწევს — report-ში, მიზეზით). Windows-only დამოკიდებულება (მაგ. `colorama` `tqdm`-ისთვის) — უკვე არსებული marker-ით. header-ში ხაზი: `2026-10-28: anthropic/openai added from local venv pip freeze (Python <ver>, Windows); Linux resolution confirmed on next Render deploy`.
  - Python 3.14: ყოველ ახალ compiled პაკეტზე (მაგ. `jiter`) `pip download --only-binary=:all: --platform manylinux2014_x86_64 --python-version 3.14 --no-deps -d <scratchpad> <pkg>==<ver>` → wheel არსებობს (report-ში; ჩამოტვირთული ფაილები მხოლოდ scratchpad-ში).
  - done when: `.venv/Scripts/python.exe -m pip check` სუფთა; `.venv/Scripts/python.exe -m pip_audit -r requirements.lock.txt --no-deps --disable-pip` → 0 ცნობილი მოწყვლადობა (pip-audit საჭიროებისას მხოლოდ venv-ში, არა გლობალურად); `.venv/Scripts/python.exe -m pip show anthropic openai` ვერსიები = lock; `pytest -q` → 274 passed (უცვლელი); ruff/compileall სუფთა.
- [x] **S14-2 — Settings: `LLM_PROVIDER`, key-ები, `llm_ready`; startup warning; `GEMINI_API_KEY` fail-closed სიიდან** ✅ +15 ტესტი (`test_llm_config.py`) → 289 passed; `warn_if_llm_disabled` — `logging.getLogger("app")` (მოდულის logger იქ ჯერ არ არის განსაზღვრული); `extra="ignore"` დადასტურდა ტესტით (`GEMINI_*` env-ში → startup OK). · owner: backend-dev · files: `backend/app/config.py` (shared), `backend/app/main.py`, `backend/tests/conftest.py` (shared), `backend/tests/test_llm_config.py` (ახალი), `backend/tests/test_fail_closed_secrets.py`, `backend/tests/test_config_secrets.py` · depends: —
  - `config.py`: `llm_provider: Literal["claude","openai"] = "claude"` + `field_validator(mode="before")` (`strip().lower()`, ცარიელი → `"claude"`; სხვა მნიშვნელობა → `ValidationError` — startup ჩავარდება ყველა გარემოში); `anthropic_api_key: str = Field("", repr=False)`, `openai_api_key: str = Field("", repr=False)`, `claude_model = "claude-haiku-5-5"`, `openai_model = "gpt-6-luna"`, `llm_timeout_seconds: float = Field(20.0, gt=0, le=20)`. properties: `llm_ready` (არჩეული provider-ის key `.strip()` არაცარიელია), `llm_model`, `llm_key_env_name` (`"ANTHROPIC_API_KEY"` / `"OPENAI_API_KEY"`). `missing_required_secrets()`-იდან `GEMINI_API_KEY` ამოიღე; provider-ის key **არ** დაამატო. `gemini_*` ველები **რჩება** კომენტარით `# removed in S14-5` (`bot.py` ჯერ იყენებს).
  - `main.py`: `warn_if_llm_disabled(s)` — `check_required_settings(settings)`-ის შემდეგ, ყველა გარემოში: `logger.warning("LLM disabled: %s is not set (LLM_PROVIDER=%s) — bot replies with the operator message", s.llm_key_env_name, s.llm_provider)`; მნიშვნელობა არასდროს.
  - `conftest.py`: blank-სიიდან `GEMINI_API_KEY` ამოიღე, დაამატე `OPENAI_API_KEY`; `os.environ["ANTHROPIC_API_KEY"] = "test-anthropic-key-not-real"`, `os.environ["LLM_PROVIDER"] = "claude"` (ტესტების default = კონფიგურირებული ბოტი); `CLAUDE_MODEL`, `OPENAI_MODEL`, `LLM_TIMEOUT_SECONDS` — `os.environ.pop(name, None)` (ცარიელი სტრიქონი default-ს გადაფარავდა / float-ად ვერ გარდაიქმნება).
  - `test_llm_config.py`: default-ები; `" OpenAI "` → `openai`; `""` → `claude`; `"gemini"` → `ValidationError`; timeout `0`, `-1`, `21` → `ValidationError`; `llm_ready` ორივე provider-ზე (მხოლოდ claude key → ready claude-ზე, not ready openai-ზე); `llm_key_env_name`; `repr(settings)`-ში key-ის მნიშვნელობა არ ჩანს; production + ყველა სხვა secret + provider key-ის გარეშე → `missing_required_secrets() == []` და `check_required_settings` არ აგდებს; `warn_if_llm_disabled` (caplog) — WARNING ცვლადის სახელით და key-ის მნიშვნელობის გარეშე, ready-ზე — არაფერი; `monkeypatch.setenv` `GEMINI_API_KEY`/`GEMINI_MODEL`/`GEMINI_TIMEOUT_SECONDS` → `Settings()` იქმნება, production-ში `missing == []` (Render-ზე დარჩენილი ცვლადები startup-ს არ აგდებს).
  - `test_fail_closed_secrets.py`: Gemini აუცილებელი სიიდან/fixture-იდან; `["GEMINI_API_KEY", "FB_APP_SECRET"]` → `["FB_APP_SECRET"]`; ცარიელი provider key სიაში არ ხვდება. დანარჩენი secret-ების fail-closed შემოწმებები უცვლელია. `test_config_secrets.py`: sentinel `GEMINI_API_KEY` → `ANTHROPIC_API_KEY` და `OPENAI_API_KEY` (dotenv-ფაილის ტესტი — `ANTHROPIC_API_KEY`).
  - done when: საერთო backend done-when; `grep -rn "GEMINI" backend/tests/conftest.py backend/tests/test_fail_closed_secrets.py backend/tests/test_config_secrets.py` → 0; `backend/app/config.py`-ში `gemini` მხოლოდ სამ ველზეა `# removed in S14-5` კომენტარით.
- [x] **S14-3 — `services/prompt.py`: სამი ფენა, ისტორიის ნორმალიზაცია, ზომის ჭერი (სუფთა, offline)** ✅ L1 = 4 382 სიმბოლო (12 წესი + 3 few-shot); 21 ტესტი → 310 passed; `MAX_PROMPT_CHARS` 50K → **60K** (Decision Log: უარესი L1+L2+final = 56 147 / 56 299, ორივე ტესტით); პროდუქტები `(str(id), name)`-ით ლაგდება retrieval-მდეც; ცარიელ შეტყობინებაზე `(The customer sent an empty message.)`. ⚠️ S14-4-სთვის: ისტორიის ბოლო user turn + `final` = ორი user ზედიზედ (Claude აერთიანებს; OpenAI-ზე დასაშვებია) — adapter-მა არ უნდა გააგდოს. · owner: backend-dev · files: `backend/app/services/prompt.py` (ახალი), `backend/tests/test_prompt_layers.py` (ახალი), `backend/tests/fixtures/prompt_layer1.txt` (ახალი) · depends: — (`bot.py`-ს **არ** ეხება: საჭირო helper-ები — `select_relevant_products`, `_STOPWORDS`, `RETRIEVE_LIMIT`, `_clip`, `_public_base`, `order_link_for` — prompt.py-ში კოპირდება; `bot.py`-დან S14-5 შლის)
  - API: `LAYER1: str`; `RETRIEVE_LIMIT = 30`; `MAX_PROMPT_CHARS = 50_000`; `select_relevant_products(...)` (ლოგიკა უცვლელი); `build_layer2(shop, products) -> str`; `normalize_history(history) -> list[dict]` (`{"role": "user"|"assistant", "text": str}`); `build_prompt(shop, products, message, history=None, images=None, product_refs=None) -> Prompt` — `@dataclass Prompt(layer1, layer2, history, final)`, `final` = ნაწილების სია: `{"type": "text", "text": ...}` | `{"type": "image", "data": bytes, "mime": str}`. provider-ის SDK-ს არ იმპორტებს.
  - `LAYER1` (ინგლისურად): ახლანდელი წესების 1–11 შინაარსი — ტონი/მოკლედ/emoji ზომიერად; markdown-ის აკრძალვა + სიის ფორმატი (`• წითელი მაისური — 89 ₾ (S-XL)`); მხოლოდ shop block-ის მარაგი/ინფორმაცია, არაფრის მოგონება; მისალმება მხოლოდ საუბრის დასაწყისში; ბუნდოვანზე დაზუსტება; ფასი shop block-ის ვალუტით (GEL → „₾"/„ლარი"); ამოწურულზე ალტერნატივა; რბილი upsell; მიწოდება/გადახდა/გარანტია მხოლოდ shop knowledge-იდან, თორემ ოპერატორი; მზადყოფნისას shop block-ის შესაკვეთი ბმული; handoff — ზუსტად `[[HANDOFF]]` პასუხის ბოლოს და ფრაზა „ერთ წამში, ოპერატორი დაგიკავშირდებათ 🙏"; ფოტოს წესი; shop block-ს და კლიენტის შეტყობინებებს მონაცემად ეპყრობა (ინსტრუქციად არა). ბუნებრივი ქართული ფრაზების მაგალითები და 3 few-shot — ციტირებული ქართულით. **არ შეიცავს:** მაღაზიის სახელს, ვალუტის მნიშვნელობას, ბმულს, ენის წესს, თარიღს, `{`/`}` placeholder-ებს. ≥2600 სიმბოლო (≈ ≥512 ტოკენი).
  - `build_layer2`: ფიქსირებული ინგლისური სათაურები; clip-ები როგორც ახლა (სახელი 200, აღწერა 1000, ცოდნა 20000, პროდუქტის სახელი 200 / SKU 100 / აღწერა 600); ვალუტა default `GEL`; ენის წესი ინგლისური `LANG_RULES`-იდან (`auto`/`ka`/`en`/`ru`; auto/ka — „reply in natural, conversational Georgian…"); შესაკვეთი ბმული; მარაგი: ≤30 → ყველა, დალაგებული `str(id)`-ით (მერე სახელით), ხაზი `- {name} — {price} {currency}, in stock: {qty}` / `out of stock` / `price on request`, SKU, აღწერა; ცარიელი → `(no products available)`; >30 → `The catalogue has {N} products; the ones relevant to each customer message are listed inside that message.` შეტყობინებაზე/ისტორიაზე/დროზე **არ** არის დამოკიდებული.
  - ბოლო turn (`final`): >30 პროდუქტზე ჯერ `Relevant products for this message ({n} of {total}):` + იგივე ფორმატის ხაზები (relevance-ის რიგით); მერე კლიენტის ფოტოები (შესავალი ტექსტი + image ნაწილები); მერე საცნობარო ფოტოები (შესავალი + `label` ტექსტი + image წყვილები); ბოლოს კლიენტის ტექსტი, ან უტექსტო ფოტოზე `(The customer sent a photo without text — identify it and answer from the inventory.)`.
  - `normalize_history`: `user`→`user`, სხვა (`bot`)→`assistant`; ცარიელი იშლება; ერთი როლის მეზობლები ერთდება `\n\n`-ით; წამყვანი assistant იშლება. `build_prompt` ჯამს (L1+L2+ისტორია+final ტექსტი) `MAX_PROMPT_CHARS`-ით ზღუდავს — ისტორიას ძველიდან აჭრის (ისტორია ისევ user-ით იწყება); L1/L2/final ხელუხლებელია.
  - ტესტები: (1) **მფლობელის ტესტი:** ერთი მაღაზია, ორი სხვადასხვა შეტყობინება (და სხვადასხვა ისტორია) → `layer1` და `layer2` ბაიტ-იდენტურია (`.encode("utf-8")` ტოლობა) — 5 პროდუქტზე და 40 პროდუქტზე (retrieval განსხვავდება → `final` განსხვავდება, L2 — არა); (2) `LAYER1` = `fixtures/prompt_layer1.txt` (`\r\n`→`\n` ნორმალიზაციით); არ შეიცავს `{`/`}`; ≥2600 სიმბოლო; შეიცავს `[[HANDOFF]]`; (3) ორი მაღაზია → L1 იგივე, L2 განსხვავებული; (4) პროდუქტების შემთხვევითი შემავალი რიგი → L2 იგივე; (5) L2-ში კლიენტის ტექსტი არ ხვდება; (6) >30: რელევანტური ქვესიმრავლე მხოლოდ `final`-შია; (7) `normalize_history` შემთხვევები; (8) worst-case (`test_text_limits`-ის უზარმაზარი მნიშვნელობები + 20 × 2000-სიმბოლოიანი ისტორია) → ჯამი ≤ `MAX_PROMPT_CHARS`, L2 უცვლელი, ისტორია user-ით იწყება; (9) ფოტოების/საცნობაროების რიგი `final`-ში.
  - done when: საერთო backend done-when; `prompt.py` არ იმპორტებს `google`/`anthropic`/`openai`-ს და ქსელს არ მიმართავს (`grep -n "import" backend/app/services/prompt.py` report-ში).
- [ ] **S14-4 — `services/llm.py`: Claude/OpenAI request, client-ები, usage; migration 0025** · owner: backend-dev · files: `backend/app/services/llm.py` (ახალი), `supabase/migrations/0025_llm_usage.sql` (ახალი), `backend/tests/conftest.py` (shared, S14-2-ის შემდეგ), `backend/tests/test_llm_payload.py` (ახალი), `backend/tests/test_llm_client.py` (ახალი), `backend/tests/test_llm_usage.py` (ახალი) · depends: S14-1, S14-2, S14-3
  - `build_claude_request(prompt, model) -> dict`: `model`, `max_tokens=800`, `thinking={"type": "disabled"}`, `system=[{"type":"text","text":L1,"cache_control":{"type":"ephemeral","ttl":"1h"}}, {"type":"text","text":L2,"cache_control":{"type":"ephemeral","ttl":"5m"}}]`, `messages` (ისტორია → `{"role", "content": text}`; final → content ბლოკები: `{"type":"text"}` / `{"type":"image","source":{"type":"base64","media_type":mime,"data":b64}}`), top-level `cache_control={"type":"ephemeral"}`. **არასდროს:** `temperature`, `top_p`, `top_k`, assistant prefill. თუ SDK-ის ვერსია top-level `cache_control` kwarg-ს არ იღებს — `extra_body` (report-ში).
  - `build_openai_request(prompt, model, shop_id) -> dict`: `model`, `input=[{"role":"developer","content":[{"type":"input_text","text":L1},{"type":"input_text","text":L2}]}, …ისტორია ({"role":"user"|"assistant","content":text}), {"role":"user","content":[{"type":"input_text"…} / {"type":"input_image","image_url":"data:<mime>;base64,<b64>"}]}]`, `max_output_tokens=800`, `prompt_cache_key=f"shop:{shop_id}"`, `store=False`. sampling/reasoning პარამეტრები — არა.
  - სურათები: მხოლოდ `image/jpeg|png|gif|webp`; `MAX_IMAGE_BYTES = 5 * 1024 * 1024`-ზე დიდი → გამოტოვება + WARNING (URL/PSID-ის გარეშე) — კონსერვატიული ვარაუდი (Open Questions).
  - client factory-ები (lazy import ფუნქციის შიგნით): `_anthropic_client(s)` → `anthropic.Anthropic(api_key=s.anthropic_api_key, timeout=s.llm_timeout_seconds, max_retries=0)`; `_openai_client(s)` — ანალოგიურად `openai.OpenAI(...)`. **⚠️ შეცვლილია S14-1-ის მიგნებით** (Decision Log, timeout/retry — Superseded): SDK `retry-after`-ს ჭერის გარეშე იცავს → SDK-ის retry გამორთულია; `generate` თავად აკეთებს მაქს. **1** retry-ს მხოლოდ დროებით შეცდომაზე (`APIConnectionError`/`APITimeoutError`, `RateLimitError`, `InternalServerError` ან `APIStatusError` status ≥500 — ორივე SDK-ის კლასები), `time.sleep(LLM_RETRY_DELAY=1.5)`, მხოლოდ თუ `time.monotonic()`-ით `elapsed + 1.5 + llm_timeout_seconds ≤ LLM_TOTAL_BUDGET_SECONDS = 45`; `retry-after` იგნორდება; სხვა 4xx — retry-ს გარეშე; ბოლო შეცდომა ვრცელდება.
  - OpenAI `input_image`: `"detail": "auto"` (SDK-ში სავალდებულოა).
  - `generate(prompt, shop_id) -> LLMResult` (`@dataclass LLMResult(text, provider, model, usage: Usage)`, `@dataclass Usage(input_tokens, output_tokens, cache_read_tokens, cache_write_tokens)`): `get_settings()`; `not llm_ready` → `RuntimeError(f"LLM key not configured: {s.llm_key_env_name}")` factory-ის გამოძახების გარეშე; Claude — ტექსტი = `type == "text"` ბლოკების `.text`-ების შეერთება (thinking/სხვა ბლოკები იგნორდება), `stop_reason == "refusal"` → `""` + WARNING (shop id); OpenAI — `response.output_text or ""`. SDK-ის შეცდომა ვრცელდება (retry უკვე SDK-მ გააკეთა).
  - usage-ის ნორმალიზაცია (Decision Log 2026-10-28): Claude `input_tokens` / `output_tokens` / `cache_read_input_tokens` / `cache_creation_input_tokens`; OpenAI `input_tokens − input_tokens_details.cached_tokens`, `cached_tokens`, `output_tokens`, write = 0; `None`/არარსებული ატრიბუტი → 0; უარყოფითი არასდროს.
  - `record_usage(shop_id, result)`: `get_service_client().table("llm_usage").insert({shop_id, provider, model, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens}).execute()` — ყველაფერი try-ში; შეცდომა → `logger.warning("llm_usage write failed (shop=%s)", shop_id, exc_info=True)`, არასდროს აგდებს.
  - `conftest.py`: autouse fixture `_block_real_llm_clients` — `monkeypatch.setattr(app.services.llm, "_anthropic_client", <raise RuntimeError("real LLM client blocked in tests")>)` და იგივე `_openai_client`-ზე. ტესტი, რომელსაც ნამდვილი factory სჭირდება (fake SDK კლასით), ორიგინალს მოდულის import-ისას იმახსოვრებს და აბრუნებს.
  - `0025_llm_usage.sql`: header (დანიშნულება; „გაუშვი backend deploy-მდე"; idempotent; მფლობელი უშვებს ხელით); `create table if not exists public.llm_usage (…)` Decision Log-ის სქემით; `create index if not exists llm_usage_shop_created_idx on public.llm_usage (shop_id, created_at)`; `alter table … enable row level security`; პოლისები **არა**; `revoke all on table public.llm_usage from public, anon, authenticated`; `grant select, insert on table public.llm_usage to service_role`; ბოლოს კომენტარად verification query (`relrowsecurity`, პოლისების რაოდენობა 0, `has_table_privilege('anon'|'authenticated', 'public.llm_usage', 'select'|'insert')` = false, `service_role` insert = true).
  - ტესტები: `test_llm_payload.py` — Claude: system 2 ბლოკი, ზუსტი L1/L2, `ttl` 1h მერე 5m, top-level `cache_control`, მოდელი Settings-იდან, `temperature`/`top_p`/`top_k` request-ში არ არის, thinking disabled, `max_tokens == 800`, `messages[0]` და ბოლო — `user`, image ბლოკი base64-ით; OpenAI: პირველი `developer` (L1 მერე L2), ისტორია, ბოლო user, `prompt_cache_key`, `store is False`, `temperature` არ არის, `max_output_tokens == 800`, data URL; არასწორი mime / >5 MB → გამოტოვებულია. `test_llm_client.py` — fake `anthropic.Anthropic`/`openai.OpenAI` კლასები kwargs-ს იჭერს: `api_key` Settings-იდან, `timeout == llm_timeout_seconds`, `max_retries == 0`; retry: დროებითი შეცდომა 1-ჯერ → მე-2 მცდელობა წარმატებულია (sleep monkeypatch-ით, 1.5); დროებითი 2-ჯერ → შეცდომა ვრცელდება, მცდელობა ზუსტად 2; 400 (BadRequest) → 1 მცდელობა; fake monotonic-ით ბიუჯეტი ამოწურულია → retry არ ხდება; not ready → `RuntimeError`, factory არ გამოძახებულა; fake client-ის exception ვრცელდება; refusal → `""`; thinking-ბლოკი + text ბლოკი → მხოლოდ ტექსტი; guard: ფაბრიკის ჩანაცვლების გარეშე `generate` → `RuntimeError("real LLM client blocked…")`. `test_llm_usage.py` — ნორმალიზაცია ორივე provider-ზე (მაგ. OpenAI input 1500 / cached 1024 → input 476, cache_read 1024), `None`-safe; `record_usage` → fake DB-ში `llm_usage` insert `shop_id`-ით და ყველა ველით; DB-ის exception → WARNING, არ აგდებს; 0025-ის ფაილი შეიცავს `enable row level security`-ს და `revoke all`-ს `anon, authenticated`-ზე და `create policy`-ს არ შეიცავს (იაფი static guard).
  - done when: საერთო backend done-when; `grep -rn "Anthropic(\|OpenAI(" backend/app` → მხოლოდ ორი factory; SQL-ის ხელით გადაკითხვა 0001-ის (`shops.id uuid`) და 0024-ის სტილთან (report-ში).
- [ ] **S14-5 — `bot.py` / `chat.py` → `prompt` + `llm`; Gemini-ის კოდი და ველები იშლება** · owner: backend-dev · files: `backend/app/services/bot.py`, `backend/app/api/chat.py`, `backend/app/config.py` (shared, S14-2-ის შემდეგ — მხოლოდ `gemini_*` ველების წაშლა), `backend/tests/test_gemini_timeout.py` (წაშლა), `backend/tests/test_text_limits.py`, `backend/tests/test_bot_images.py` (მხოლოდ docstring), `backend/tests/test_bot_reply.py` (ახალი) · depends: S14-3, S14-4
  - `bot.py`: წაიშლება `_TRANSIENT`, `GEMINI_TOTAL_BUDGET_SECONDS`, `GEMINI_MIN_ATTEMPT_SECONDS`, `_MAX_ATTEMPTS`, `_is_timeout`, `_LANG_RULES`, `SYSTEM_PROMPT_TEMPLATE`, `RETRIEVE_LIMIT`, `_STOPWORDS`, `select_relevant_products`, `_clip`, `_format_inventory`, `_public_base`, `order_link_for`, `build_system_prompt`, `_build_contents`, `google.genai`-ის import-ები, გამოუყენებელი `time`/`re`. რჩება: `HANDOFF_TOKEN`, `parse_reply`, `INLINE_IMAGE_BUDGET`, `PRODUCT_REF_MAX_BYTES`, `PRODUCT_REF_WORKERS`, `_fetch_product_images` (ლოგიკა უცვლელი). `get_bot_reply(shop, products, message, history=None, images=None) -> str`: `not llm_ready` → `RuntimeError`; `relevant = prompt.select_relevant_products(...)`; საცნობარო ფოტოები მხოლოდ კლიენტის ფოტოზე (როგორც ახლა); `p = prompt.build_prompt(...)`; `result = llm.generate(p, shop["id"])`; `llm.record_usage(shop["id"], result)`; `return result.text.strip()`. module docstring და კომენტარები — provider-ნეიტრალური („LLM").
  - `chat.py`: `if not settings.llm_ready` → 503 `f"{settings.llm_key_env_name} არ არის კონფიგურირებული"`; `model=settings.llm_model`; კომენტარები Gemini → LLM. production → 404 და rate limit უცვლელია.
  - `config.py`: `gemini_api_key`, `gemini_model`, `gemini_timeout_seconds` და მათი კომენტარი იშლება.
  - `test_gemini_timeout.py` იშლება; მისი გარანტიები: ერთი მცდელობის timeout client-ს გადაეცემა (S14-4 `test_llm_client.py`), ჯამი შემოსაზღვრულია (`max_retries == 1` + `le=20` — S14-2/S14-4), შეცდომა → webhook-ის „ბოდიში, ამ წუთას ვერ გიპასუხებთ. სცადეთ ცოტა ხანში." + ლოგში shop id, PSID არა — გადადის `test_bot_reply.py`-ში (რეალური `get_bot_reply`, fake client აგდებს timeout-ის მსგავს exception-ს, `webhook._process_events` `test_reply_delivery`-ის `env` fixture-ით).
  - `test_bot_reply.py`: (1) **მფლობელის ტესტი end-to-end:** ორი სხვადასხვა შეტყობინება რეალური `get_bot_reply`-ით, fake Claude client იჭერს kwargs-ს → `system` ორივეზე ბაიტ-იდენტურია (`json.dumps(..., sort_keys=True, ensure_ascii=False).encode()`), პირველი ბლოკი = fixture-ის L1; იგივე OpenAI-ზე (`input[0]` — developer); 5 და 40 პროდუქტზე; (2) `record_usage` გამოძახებულია shop id-ით (fake service DB-ში `llm_usage` insert); DB-ის შეცდომისას პასუხი მაინც ბრუნდება; (3) not ready → `RuntimeError`, factory არ გამოძახებულა; (4) webhook fallback timeout-ზე (ზემოთ); (5) `/test-chat` (`client` fixture, `app.api.chat.get_service_client` patch): key-ის გარეშე → 503 `ANTHROPIC_API_KEY`-ით; fake client-ით → 200, `model == "claude-haiku-5-5"`; production → 404.
  - `test_text_limits.py`: `build_system_prompt` → `prompt.build_prompt`: იგივე უზარმაზარი მონაცემით L1+L2 < 100 000 სიმბოლო და ჯამი ≤ `MAX_PROMPT_CHARS`. `test_bot_images.py`: docstring „no Gemini" → „no LLM" (ტესტები უცვლელი).
  - done when: საერთო backend done-when; `grep -rni "gemini\|genai" backend/app/services/bot.py backend/app/api/chat.py backend/app/config.py backend/tests/test_text_limits.py backend/tests/test_bot_images.py backend/tests/test_bot_reply.py` → 0; `backend/tests/test_gemini_timeout.py` აღარ არსებობს; report-ში — წაშლილი ტესტის თითო გარანტიის შესაბამისი ახალი ტესტის სახელი.
- [ ] **S14-6 — webhook: key-ის გარეშე ოპერატორის პასუხი; ქართული golden ტესტები** · owner: backend-dev · files: `backend/app/api/webhook.py`, `backend/app/services/facebook.py` (მხოლოდ კომენტარები), `backend/tests/test_bot_disabled.py` (ახალი), `backend/tests/test_golden_conversations.py` (ახალი), `backend/tests/test_reply_delivery.py`, `backend/tests/test_over_limit.py`, `backend/tests/test_webhook_ratelimit.py` (ბოლო სამში მხოლოდ „gemini" სტრიქონები/docstring-ები) · depends: S14-5
  - `webhook.py`: over-limit-ის ტექსტი → მოდულის კონსტანტა `OPERATOR_SOON_REPLY` (ტექსტი და ქცევა უცვლელი). over-limit-ის გამოთვლის **შემდეგ**: `bot_disabled = not get_settings().llm_ready`; თუ ასეა → `logger.warning("bot disabled — %s not set (shop=%s)", settings.llm_key_env_name, shop.get("id"))` (PSID-ის გარეშე); `if over_limit or bot_disabled:` → არსებული განშტოება (`OPERATOR_SOON_REPLY` + `_save_turn(..., needs_attention=True)` + `continue`). რიგი უცვლელია: echo/dedup → წუთობრივი ლიმიტი → `track_bot_customer` → abuse cap → თვიური ლიმიტი → **გამორთული ბოტი** → ფოტოების ჩამოტვირთვა → LLM. კომენტარები „Gemini" → „LLM".
  - `services/facebook.py`: ხაზები ~281, ~295 — „Gemini" → „LLM" (კოდი არ იცვლება).
  - `test_bot_disabled.py`: `webhook.get_settings` → settings-ის ასლი `anthropic_api_key=""`-ით: `_process_events` → `sent == [OPERATOR_SOON_REPLY]`; `bot_conversations` upsert `needs_attention=True`; `get_bot_reply` **არ** გამოძახებულა (flag), `download_image` არ გამოძახებულა (ფოტოიან შეტყობინებაზეც); `track_bot_customer` გამოძახებულია (კლიენტი ითვლება); WARNING შეიცავს shop id-ს და `ANTHROPIC_API_KEY`-ს, PSID-ს — არა; `llm_provider="openai"` + ცარიელი `openai_api_key` → იგივე, `OPENAI_API_KEY`-ით; abuse cap გადაჭარბებისას — ჩუმად (როგორც ახლა); key-ით → ჩვეულებრივი გზა.
  - `test_golden_conversations.py` (parametrize: `claude`, `openai`): fake client-ები `llm._anthropic_client` / `_openai_client`-ის ჩანაცვლებით (Claude: `.messages.create(**kw)` → `SimpleNamespace(content=[thinking-ის მსგავსი ბლოკი, text ბლოკი], stop_reason="end_turn", usage=…)`; OpenAI: `.responses.create(**kw)` → `SimpleNamespace(output_text=…, usage=…)`); რეალური `get_bot_reply`; `webhook._process_events` fake service DB-ით (მაღაზია „ტესტ მაღაზია", GEL, `bot_language="auto"`; პროდუქტები „წითელი მაისური" 89 ₾ მარაგი 3, „თეთრი პერანგი" 65 ₾ მარაგი 0, …); `send_text_message`, `decrypt`, `download_image`, `is_own_storage_image_url` — patch. სცენარები: (1) „გამარჯობა" → canned „გამარჯობა! 😊 რით შემიძლია დაგეხმაროთ?" მიწოდებულია უცვლელად; request-ში ბოლო user ტექსტი = „გამარჯობა", ისტორია ცარიელი, L2 შეიცავს პროდუქტის ხაზებს; (2) „წითელი მაისური რა ღირს?" წინა ისტორიით (user + bot) → messages: user, assistant, user; (3) „თეთრი პერანგი გაქვთ?" → L2-ში მისი ხაზი `out of stock`; (4) „ოპერატორთან დამაკავშირეთ" → canned პასუხი `[[HANDOFF]]`-ით მთავრდება → მიწოდებულ ტექსტში ნიშანი არ არის, upsert `needs_attention=True`; (5) ფოტო ტექსტის გარეშე → ბოლო turn-ში image ბლოკი (Claude base64 / OpenAI data URL) + „photo without text" ტექსტი; Storage-ის ფოტოიანი პროდუქტის საცნობარო სურათი. ყოველ სცენარში `llm_usage` insert shop id-ით.
  - done when: საერთო backend done-when (მოსალოდნელი ≈ 320–330 passed); `grep -rni "gemini\|genai" backend/app backend/tests` → 0.
- [ ] **S14-7 — `google-genai`-ის ამოღება; Gemini-ს შედარების სკრიპტი** · owner: task-executor · files: `backend/requirements.txt` (shared, S14-1-ის შემდეგ), `backend/requirements.lock.txt` (shared), `backend/scripts/compare_gemini_models.py` (წაშლა), `backend/scripts/compare_gemini_output.md` (ლოკალური, gitignored — წაშლა), `.gitignore` · depends: S14-1, S14-5, S14-6 (კოდი/ტესტები `google.genai`-ს აღარ იმპორტებს)
  - `requirements.txt`: `google-genai>=1.0` წაიშალოს.
  - venv/lock: uninstall-მდე `pip show google-genai` → `Requires:` სია; `pip uninstall -y google-genai`; ყოველ ყოფილ დამოკიდებულებაზე `pip show <pkg>` → `Required-by:` — ცარიელია → venv-იდან და lock-იდან წაშლა (კანდიდატები: `google-auth`, `pyasn1`, `pyasn1-modules`, `tenacity`, `requests`, `websockets`… — **თითო გადაამოწმე**; მაგ. `websockets` `realtime`/`uvicorn[standard]`-ს სჭირდება). header-ში ხაზი `2026-10-28: google-genai and its exclusive deps removed (Stage 14)`.
  - `.gitignore`: ხაზი `backend/scripts/compare_gemini_output.md` წაიშალოს (Stage 15 თავისას დაამატებს).
  - done when: სუფთა venv scratchpad-ში (`python -m venv <scratchpad>/venv14`) → `pip install --no-deps -r backend/requirements.lock.txt` → `pip install -r backend/requirements-dev.txt` → `pip check` სუფთა (lock სრულია); `pip_audit -r requirements.lock.txt --no-deps --disable-pip` → 0; იმავე venv-ით `pytest -q` გადის (scratchpad-ის venv შეიძლება დარჩეს — `rm -rf` აკრძალულია, scratchpad სესიის დროებითი საქაღალდეა); `grep -rni "genai\|gemini" backend/requirements*.txt backend/app backend/tests backend/scripts .gitignore` → 0.
- [ ] **S14-8 — დოკუმენტაცია: README, CLAUDE.md, `.env.example`, DEPLOYMENT.md** · owner: task-executor · files: `README.md`, `CLAUDE.md`, `.env.example`, `DEPLOYMENT.md` · depends: S14-6, S14-7 (საბოლოო სახელები და ტესტების რაოდენობა)
  - `CLAUDE.md`: Stack — `LLM: Anthropic Claude (anthropic, default) / OpenAI (openai) — LLM_PROVIDER`; test-ის ხაზი — ზუსტი რაოდენობა `pytest -q`-დან + „mock Graph / LLM client-ები"; Conventions — „Gemini-ს გამოძახება რეალური key-ით" → „Anthropic/OpenAI API-ს გამოძახება რეალური key-ით"; ტესტების წესი — „LLM — fake client (`llm._anthropic_client`/`_openai_client`; conftest რეალურს ბლოკავს) ან monkeypatch `get_bot_reply`"; შემდეგი მიგრაცია `0026_...sql`. დანარჩენი ბრძანებები უცვლელი; `.claude/`-ს არ ეხება.
  - `README.md`: §1 დიაგრამა (Gemini → Claude / OpenAI), §3 AI-ის ხაზი, §5.2 (#5 — „LLM multimodal"; ჩარჩო: `services/bot.py` + `prompt.py` + `llm.py`, სამი ფენა მოკლედ), §6 `/test-chat` (503 key-ის გარეშე), §7 — ცხრილები (7) + `llm_usage`, მიგრაციები (25) + `0025` („გაუშვი backend deploy-**მდე**"), §12 — `GEMINI_*` ხაზები → `LLM_PROVIDER`, `ANTHROPIC_API_KEY` 🔒, `CLAUDE_MODEL`, `OPENAI_API_KEY` 🔒, `OPENAI_MODEL`, `LLM_TIMEOUT_SECONDS` (`gt 0, ≤ 20`); fail-closed სიიდან `GEMINI_API_KEY` + შენიშვნა „provider-ის key-ის გარეშე აპი ირთვება, ბოტი ოპერატორის პასუხს აგზავნის, ლოგში WARNING". §15 (ისტორია) არ იცვლება.
  - `.env.example`: Gemini-ს ბლოკი → LLM ბლოკი (`LLM_PROVIDER=claude`, `ANTHROPIC_API_KEY=`, `CLAUDE_MODEL=claude-haiku-5-5`, `OPENAI_API_KEY=`, `OPENAI_MODEL=gpt-6-luna`, `LLM_TIMEOUT_SECONDS=20`; ქართული კომენტარები: სად აიღო key, key-ის გარეშე ბოტი გამორთულია, პანელი მუშაობს).
  - `DEPLOYMENT.md`: საიდუმლოების სკანი (`GEMINI` → `ANTHROPIC\|OPENAI\|sk-ant-`), secrets-ის სიები (38–40, 68), `/test-chat`-ის ხაზი (124), ხარჯების ცხრილი (Gemini → Claude Haiku 5.5: $0.10 / $0.50 per MTok, cache read 0.1×; >100K-ტოკენიანი request — 5×) + მითითება `PROGRESS.md`-ის `## Stage 14 — Deploy plan`-ზე.
  - done when: `grep -rni "gemini\|genai" CLAUDE.md .env.example DEPLOYMENT.md` → 0; README-ში მხოლოდ §15-ის ისტორიულ ხაზ(ებ)ში; README/`.env.example`-ის ცვლადების სახელები ზუსტად ემთხვევა `Settings`-ის ველებს (ჩამონათვალი report-ში); CLAUDE.md-ის ტესტების რაოდენობა = ბოლო `pytest -q`; CLAUDE.md ≤ ~50 ხაზი.
- [x] **S14-9 — `privacy.html` / `terms.html`: subprocessor-ები (Google → Anthropic, OpenAI)** ✅ §4 (Anthropic + OpenAI ორი `<li>`), §9, terms ~87; „ბოლო განახლება" → 28 ოქტომბერი (ორივე); lint 0 error, test 29/29, dist — მხოლოდ ეს 2 გვერდი; `gemini` 0; ბრაუზერში ვიზუალი — unverified (მხოლოდ ტექსტი). · owner: frontend-dev · files: `frontend/privacy.html`, `frontend/terms.html`, `frontend/dist/**` (rebuild) · depends: —
  - `privacy.html` §4: „Google Gemini — AI პასუხების გენერაცია;" → „Anthropic (Claude) — AI პასუხების გენერაცია;" + „OpenAI — AI პასუხების გენერაცია (ალტერნატიული მომწოდებელი);"; §9: „(Supabase, Google, Meta)" → „(Supabase, Anthropic, OpenAI, Meta)". `terms.html` (~ხაზი 87): „(Supabase, Google, Meta — …)" → „(Supabase, Anthropic, OpenAI, Meta — …)". თუ გვერდზე „ბოლო განახლების" თარიღია — 2026-10-28.
  - მხოლოდ ტექსტი: markup, კლასები, Google Fonts-ის ბმულები და სხვა ტექსტები უცვლელია. ფაზა 1ბ (DESIGN.md + Playwright) გამოტოვებულია (Decision Log 2026-10-28).
  - done when: `cd frontend && npm run lint` → 0 error; `npm test` → 29/29; `npm run build` → `dist/` იმავე commit-ში; `git diff --stat -- frontend/dist` — მხოლოდ `privacy.html` და `terms.html`; `grep -i "gemini" frontend/privacy.html frontend/terms.html frontend/dist/privacy.html frontend/dist/terms.html` → 0 (`Google` რჩება მხოლოდ fonts-ის URL-ებში).

## Stage 14 — Deploy plan (Render; NOT to execute — main merge is not planned until keys exist)
> შეასრულებს **მხოლოდ მფლობელი**, როცა `ANTHROPIC_API_KEY` ექნება და Stage 14 დასრულებულია (finish-check). აგენტი remote-ზე არაფერს უშვებს.
> ⚠️ რიგი მნიშვნელოვანია: ძველ (Gemini) ვერსიას production-ში `GEMINI_API_KEY` სჭირდება (fail-closed) → `GEMINI_*` **წაშალე მხოლოდ ახალი ვერსიის წარმატებული deploy-ის შემდეგ**, თორემ rollback/restart ძველ ვერსიას ვეღარ ააწევს. ახალ ვერსიას დარჩენილი `GEMINI_*` არ აწუხებს (`extra="ignore"`).

**Render env — დასამატებელი (deploy-მდე):**
| ცვლადი | მნიშვნელობა | სავალდებულო |
|---|---|---|
| `ANTHROPIC_API_KEY` | 🔒 Anthropic Console → API Keys (რეკომენდაცია: ცალკე production workspace + spend limit) | ✅ (მის გარეშე აპი ადგება, მაგრამ ბოტი მხოლოდ ოპერატორის პასუხს აგზავნის) |
| `LLM_PROVIDER` | `claude` | default-ია; ცხადად დაყენება რეკომენდებულია (არავალიდური მნიშვნელობა → სერვერი არ ადგება) |
| `CLAUDE_MODEL` | — | არა (default `claude-haiku-5-5`); მხოლოდ სხვა მოდელისთვის |
| `LLM_TIMEOUT_SECONDS` | — | არა (default 20; დასაშვები `(0, 20]`, სხვა → სერვერი არ ადგება) |
| `OPENAI_API_KEY`, `OPENAI_MODEL` | — | **არა** Render-ზე, სანამ `LLM_PROVIDER=openai` არ გადაწყდება (Stage 15-ის შედარება ლოკალურად ეშვება) |

**Render env — წასაშლელი (მხოლოდ ახალი ვერსიის live-ის და ნაბიჯი 6-ის შემოწმების შემდეგ):** `GEMINI_API_KEY`, `GEMINI_MODEL` (თუ დაყენებულია), `GEMINI_TIMEOUT_SECONDS` (თუ დაყენებულია). შემდეგ Google AI Studio-ში Gemini key-ის გაუქმება (ძველი „key-ის როტაცია" ამით იხურება).

1. **0025 — PRE-CHECK (SQL Editor):** `select to_regclass('public.llm_usage');` → `null` (ან უკვე არსებობს — მიგრაცია idempotent-ია).
2. **0025-ის გაშვება** — `supabase/migrations/0025_llm_usage.sql`, **backend deploy-მდე** (ახალი backend მასში წერს; ჩავარდნა არაფატალურია, მაგრამ usage დაიკარგება). ძველი backend ცხრილს არ ეხება → წინასწარ გაშვება უსაფრთხოა.
3. **Verification** (ფაილის ბოლოს არსებული query): RLS ჩართული, პოლისები 0, `anon`/`authenticated` — select/insert `false`, `service_role` insert `true`.
4. Render env: დაამატე `ANTHROPIC_API_KEY` (+ `LLM_PROVIDER=claude`). `GEMINI_*`-ს ჯერ **ნუ** წაშლი.
5. `agent-system` → `main` merge + push → Render auto-deploy (build: `pip install -r requirements.lock.txt` — ახალი dependency-ები Linux/Python 3.14.3-ზე პირველად აქ დადასტურდება). ლოგში: სერვერი ადგა, `/health` 200, **`LLM disabled` WARNING არ ჩანს**.
6. შემოწმება (მფლობელი): Messenger-ში 2 შეტყობინება 5 წუთში → ბოტი ქართულად პასუხობს; `select provider, model, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, created_at from public.llm_usage order by created_at desc limit 5;` → რიგები არის; პირველზე `cache_write_tokens > 0`, მეორეზე `cache_read_tokens > 0` (ადასტურებს, რომ ფენა 1 ≥512 ტოკენია და cache მუშაობს); „ოპერატორთან დამაკავშირეთ" → პანელში „ყურადღება სჭირდება"; ფოტოს გაგზავნა → პასუხი.
7. მხოლოდ ამის შემდეგ — `GEMINI_*`-ის წაშლა Render-ზე → restart → ნაბიჯი 6-ის მოკლე გამეორება.
8. **Rollback:** წინა commit-ის redeploy (Render → Manual Deploy) — მუშაობს მხოლოდ მანამ, სანამ `GEMINI_API_KEY` Render-ზეა (ნაბიჯი 7-მდე). `llm_usage` ცხრილი ძველ ვერსიას არ აწუხებს.

## Upcoming stages (plan only, not started)
> დეტალური task-ები თითო stage-ის დაწყებისას დაიწერება. ყველგან: offline ტესტები, key-ები მხოლოდ env-იდან, რეალური API-ს გამოძახება მხოლოდ მფლობელის მიერ.

### Stage 15 — ბრმა შედარება: Claude vs OpenAI (მფლობელის „Stage B")
- **მიზანი:** სკრიპტი, რომელიც 40 ქართულ სატესტო შეკითხვას (მარაგი, ფასი, მიწოდება, ოპერატორი, ფოტო) ორივე provider-ს უგზავნის Stage 14-ის იმავე prompt-ის გზით (`prompt.build_prompt` + `llm.generate`, provider-ის override-ით) ფიქტიურ სადემონსტრაციო მაღაზიაზე; შედეგი — ერთ ფაილში შემთხვევითი რიგით, provider-ის სახელების გარეშე (A/B ნიშნით), ტოკენებითა და ფასით თითო პასუხზე; გასაღები (რომელი პასუხი რომელი provider-ისაა) — ცალკე ფაილში. სკრიპტი **იწერება, არ ეშვება**; README აღწერს გაშვებას key-ების დამატების შემდეგ.
- **მთავარი ფაილები:** `backend/scripts/compare_providers.py`, `backend/scripts/compare_questions.json` (40 შეკითხვა + ფოტო-შეკითხვების სურათების გზები), `backend/scripts/compare_assets/` (მცირე სატესტო სურათები), გამოსავალი `compare_output.md` + `compare_key.json` (gitignored), ოფლაინ ტესტი fake client-ებით (seed-იანი shuffle, გასაღების სისწორე, ფასის გამოთვლა), README-ს სექცია.
- **რისკები:** gpt-6-luna-ს ფასი/პარამეტრები დაუდასტურებელია (ფასის ცხრილი სკრიპტში ცხადად „unverified"); რეალური ხარჯი (~80 გამოძახება, ცენტები); rate limit; ბრმა შეფასება სუბიექტურია — რუბრიკა (სიზუსტე მარაგზე, ბუნებრივი ქართული, მოკლეობა, handoff-ის სისწორე).
- **done when (ესკიზი):** ტესტი fake client-ებით ქმნის ორ ფაილს სწორი ფორმატით და გასაღებით; შეკითხვების რაოდენობა 40 (ტესტით); README-ს ინსტრუქცია; არცერთი რეალური გამოძახება. შედეგით: default provider, thinking/effort, output-ის ჭერი, 5m cache-ის ეკონომიკა — Decision Log.

### Stage 16 — LangGraph გრაფი (მფლობელის „Stage C")
- **მიზანი:** `preprocess` (LLM-ის გარეშე: მისალმება/მადლობა/ოპერატორის მოთხოვნა — ქართული/ინგლისური/რუსული შაბლონებით) → `agent` tools-ით (`search_products`, `search_knowledge`, `order_link`, `request_human` — ბოლო ანაცვლებს `[[HANDOFF]]`-ს) → `postprocess` (markdown-ის გასუფთავება, ისტორია = ბოლო 8 შეტყობინება + ძველის summary).
- **მთავარი ფაილები:** `backend/app/services/graph.py` (ან `bot.py`-ის გაფართოება), `services/tools.py`, `prompt.py` (L1-ში tools-ის წესები; L2-დან სრული მარაგი შეიძლება ამოვიდეს `search_products`-ის სასარგებლოდ — Stage 15-ის ციფრებით), migration `0026` (`bot_conversations.summary`), ტესტები (გრაფის თითო გზა, tool-ების tenant isolation, iteration-ის ჭერი).
- **რისკები:** ისტორიის ჭრა ყოველ turn-ზე (მოცურავე „ბოლო 8") ფენა 3-ის cache-ს ყოველთვის არღვევს → ჭრა ბლოკებად (Decision Log 2026-10-28, ფენები); ახალი dependency `langgraph` (+ `langchain-core`) — Python 3.14 wheel-ები, pip-audit, წონა; LLM-ის გამოძახება nodes-ში **პირდაპირ SDK-ით** (`llm.py`), არა LangChain chat model-ით — თორემ `cache_control`-ის კონტროლი იკარგება; tool definitions prefix-ის ნაწილია (tools → system) → სტატიკური და მაღაზიისგან დამოუკიდებელი; tool-ის არგუმენტები untrusted — `shop_id` მხოლოდ graph state-იდან, არასდროს მოდელიდან; agent loop-ის ჭერი (მაგ. ≤3 tool-იტერაცია) და latency; summary-ის გენერაცია დამატებითი გამოძახებაა (მხოლოდ >8 შეტყობინებაზე); Accepted Risk #20 („ბოტს tools არ აქვს") გადაიხედება.
- **done when (ესკიზი):** golden სცენარები გრაფზე; შაბლონური შეტყობინებები LLM-ის გარეშე (0 usage რიგი); `request_human` → `needs_attention`; ერთ შეტყობინებაზე LLM-ის გამოძახებები ≤ N (ტესტით); `[[HANDOFF]]` კოდიდან ქრება.

### Stage 17 — PDF-ცოდნა: შეკუმშვა + ძებნა (მფლობელის „Stage D")
- **მიზანი:** ატვირთვისას PDF-ის ტექსტი **ერთხელ** იკუმშება მოკლე FAQ-ად (ერთი LLM გამოძახება) → ფენა 2-ში (20000-სიმბოლოიანი clip-ის ნაცვლად); სრული ტექსტი chunk-ებად `search_knowledge`-ისთვის. prompt 100K ტოკენს არასდროს უახლოვდება (ზომის ჭერი ტესტით).
- **მთავარი ფაილები:** `backend/app/api/shops.py` (`upload_knowledge`/`clear_knowledge`), `services/knowledge.py`, migration `0027` (`shops.knowledge_faq`, `knowledge_chunks(shop_id, ord, text)` — RLS, ჩაწერა მხოლოდ backend-ით, როგორც 0022), `prompt.py` (L2), ტესტები.
- **რისკები:** ძებნა vector DB-ის გარეშე (ქართულს Postgres FTS-ის ლექსიკონი არ აქვს → `simple` კონფიგი / ILIKE / trigram); prompt injection PDF-ში (FAQ-ის გენერაციისას და ძებნის შედეგში — მონაცემად); ატვირთვა ნელდება ან background-ში გადადის; FAQ-ის გენერაციის ჩავარდნა → ატვირთვა მაინც ინახება; ხარჯი თითო ატვირთვაზე; free-tier gate უცვლელი; B-14 (PDF-ცოდნა ფაქტობრივად საჯაროა) რჩება.
- **done when (ესკიზი):** fake client-ით FAQ იქმნება და L2-ში ხვდება; chunk-ები იწერება/იშლება; `search_knowledge` tenant-ით შეზღუდულია; worst-case PDF-ზე prompt ≤ ჭერი.

### Stage 18 — ფოტოები: ტექსტური აღწერა (მფლობელის „Stage E")
- **მიზანი:** პროდუქტის ფოტოს ტექსტური აღწერა **ერთხელ**, ატვირთვისას; კლიენტის ფოტოზე — ჯერ აღწერა + ტექსტური შედარება აღწერებთან, სურათები იგზავნება მხოლოდ 2–3 კანდიდატზე (ახლა — 12-მდე საცნობარო ფოტო).
- **მთავარი ფაილები:** `backend/app/api/products.py` (upload-image), `services/vision.py` (ან `llm.py`-ში ფუნქცია), migration (`products.image_description`), `bot.py` (`_fetch_product_images` → კანდიდატები), არსებული ფოტოების backfill სკრიპტი (მფლობელი უშვებს), ტესტები.
- **რისკები:** ორი გამოძახება ერთ შეტყობინებაზე (latency/ხარჯი vs ნაკლები სურათი); არასწორი აღწერა → არასწორი კანდიდატი; ხარჯი თითო ატვირთვაზე; backfill-ის ხარჯი; კლიენტის ფოტოს ზომა (`MAX_IMAGE_BYTES`).
- **done when (ესკიზი):** ატვირთვისას აღწერა ინახება (fake client); კლიენტის ფოტოზე request-ში ≤3 საცნობარო სურათი; golden ფოტო-სცენარები; ტოკენების შემცირება Stage 15-ის მეთოდით გაზომვადია.

## Stage 12 — Deploy plan (მფლობელი; აგენტი remote-ზე არაფერს უშვებს)
> რიგი მნიშვნელოვანია: 0024 backend-ის **შემდეგ** (ძველი backend + 0024 = „პაკეტის მოთხოვნა" 403/500).
> ✅ ნაბიჯები 0–4 და 6 შესრულებულია (მფლობელი, ლაივზე, 2026-10-09): `e8525f0` live, 0024 გაშვებულია. ⏳ ნაბიჯი 5 ნაწილობრივ: დადასტურებულია (ლაივ ლოგებით) პაკეტის მოთხოვნა და ადმინის resolve; ღიაა მეორე მოთხოვნით პირველის გაუქმება, ადმინის downgrade, ბოტის ფოტო-შეკითხვა.
✅ 0. **Deploy-მდე (არჩევითი, SELECT):** `select count(*) from products where image_url is not null and image_url not like '<SUPABASE_URL>/storage/v1/object/public/product-images/%';` — რაც > 0, იმ პროდუქტების ფოტო ბოტს ვიზუალურ შედარებაში აღარ მიიღებს (S12-1). → **შედეგი:** 1 პროდუქტს აქვს ფოტო, Storage-შია (`outside_storage=0`).
✅ 1. **Render env-ის შემოწმება deploy-მდე:** `CLIENT_IP_TRUSTED_HOPS=3` დაყენებულია? (S12-4: გარეშე ახალი ვერსია არ ადგება; Render წინა ვერსიას დატოვებს.) დანარჩენი შვიდი secret უკვე არის. → `CLIENT_IP_TRUSTED_HOPS=3`, fail-closed startup გავიდა.
✅ 2. `agent-system` → `main` merge + push → Render auto-deploy. ლოგში: სერვერი ადგა, `/health` 200. → `e8525f0` live.
✅ 3. 0024-ის PRE-CHECK (დუბლიკატი pending-ები; ინფორმაციული), მერე `supabase/migrations/0024_upgrade_requests_backend_only.sql` SQL Editor-ში. → **შედეგი:** 10 მოთხოვნა, pending 0, დუბლიკატი 0; 0024 გაშვებულია.
✅ 4. 0024-ის verification query → `f, t, f, 0, 1`. → შედეგი `f, t, f, 0, 1` ✔.
⏳ (ნაწილობრივ) 5. ხელით ბრაუზერში: (ა) პანელიდან „პაკეტის მოთხოვნა" → 200, ადმინში pending ჩანს; (ბ) მეორე მოთხოვნა სხვა პაკეტზე → პირველი cancelled; (გ) ადმინი standard→free ორ-ბოტიან ანგარიშზე → ახალი ბოტი ითიშება, ძველი რჩება; (დ) პროდუქტის ფოტო (საკუთარი Storage) ბოტის „რა ღირს ეს?" ფოტო-შეკითხვაზე ისევ მუშაობს. → **დადასტურებულია** (ლაივ ლოგები): `POST …/upgrade-request` 200; `GET /admin/upgrade-requests` 200; `POST …/resolve` 200, შეცდომა არ არის. **ღიაა (ხელით არ შემოწმებულა):** (ბ) მეორე მოთხოვნით პირველის გაუქმება, (გ) ადმინის downgrade, (დ) ბოტის ფოტო-შეკითხვა.
✅ 6. `0023` (S11-7) თუ ჯერ არ გაშვებულა — იგი დამოუკიდებელია, ნებისმიერ დროს. → **შედეგი:** 0023 გაშვებულია (S11-7-ის დროს): PRE-CHECK 0/0, `products_price_finite_check` და `orders_total_finite_check` არსებობს, validated=true.

## Deploy plan
> მფლობელის გადაწყვეტილება (2026-10-08): ყველა task-ის შემდეგ ერთი დაგეგმილი deploy. სტატუსი განახლებულია მფლობელის ინფორმაციით.

### ✅ შესრულებულია (მფლობელი, ლაივ ბაზაზე)
- `supabase/checks/check_0014_0016.sql` → ყველა 32 შემოწმება `ok=true` — 0014–0016 ლაივზე გაშვებული იყო.
- მიგრაციები **0017, 0018, 0019, 0020** გაშვებულია ლაივ ბაზაზე (Supabase migration history-ში ჩაიწერა): PRE-CHECK-ები (0 მწკრივი) და თითოეულის verification query — ყველა შედეგი მოსალოდნელს ემთხვევა.
- **T20 (ერთჯერადი მარაგის გასწორება) არ დასჭირდა:** სატესტო შეკვეთები წაიშალა, `orders` ცხრილი ცარიელია. `supabase/one-off/release_legacy_new_order_stock.sql` რჩება მხოლოდ როგორც სათადარიგო.
  ⚠️ პირობა: თუ deploy-მდე ძველმა backend-მა ახალი შეკვეთა მიიღო (ძველი წესით მარაგი უკვე დაკლებულია), `orders` ცხრილი deploy-ის შემდეგ ისევ შეამოწმე (`select count(*) from public.orders;`); თუ > 0 და ისინი `new`-ია deploy-მდე შექმნილი — გამოიყენე ის სკრიპტი. ცარიელი ცხრილი = არაფერი გასაკეთებელია.
- ⚠️ გაითვალისწინე: მიგრაციები ახლა **ძველ backend-ზე** მუშაობს deploy-მდე. გადამოწმებულია კოდით, რომ ძველი backend თავსებადია (orders UPDATE მხოლოდ `status`, delete მხოლოდ done/cancelled, upgrade_requests იგივე ველები).

### ✅ Backend deploy (მფლობელი, ლაივზე)
- `832997f` live. `CLIENT_IP_TRUSTED_HOPS=3`; `CLIENT_IP_DEBUG=false` (გამორთულია).
- ლაივ XFF ჯაჭვი (მფლობელის ინფორმაციით): `<ყალბი>, <კლიენტი>, <Render-ის Cloudflare>, <Render-ის შიდა>` → კლიენტი მარჯვნიდან მე-3 პოზიციაზეა. `resolved` სწორად აჩვენებს კლიენტის IP-ს და ყალბ XFF-ს ანგარიშში არ აგდებს. (მფლობელმა შეამოწმა; აგენტს ლაივზე არაფერი გაუშვია.)
- შესრულებულია Deploy plan-ის ნაბიჯები: 1 (`CLIENT_IP_DEBUG`), 2 (merge + deploy), 3 (hops-ის შემოწმება), 4 (debug გამორთვა).

### ⏳ დარჩენილი
5. deploy-ის შემდეგ ხელით შემოწმება:
   - ✅ (მფლობელი) login, ფოტოს ატვირთვა, საჯარო შეკვეთა (201), ბოტი, admin.
   - ⏳ **ღია (მფლობელის თქმით ერთადერთი): მარაგის შემოწმება** — საჯარო შეკვეთის შექმნა მარაგს არ ცვლის; პანელში `new → processing` მარაგს აკლებს; `processing → cancelled` აბრუნებს. (სადაც 409 არასაკმარის მარაგზე და `new/processing`-ის წაშლა → 409 — ეს ორი მფლობელს ცალკე არ დაუდასტურებია.)
   - ✅ (მფლობელი, 2026-10-09) დამატებით დადასტურებულია: `new → cancelled` და მოძველებული სტატუსი (409/`STATUS_CHANGED`) — smoke SQL-ის შემოწმებები 4 და 8 ლაივ ბაზაზე; `/status` → `env=production` (შემოწმდა 2026-10-08); GitHub CI მწვანეა; T20-ის სათადარიგო პირობა დახურულია (deploy-მდე `orders` ცარიელი იყო).
   - ⏳ შეუმოწმებელი (მფლობელის გადაწყვეტილებით რჩება): **S11-2** (ორი გვერდის წვდომით connect-ის უარი ბრაუზერში), **S11-3** (Gemini timeout-ის ქცევა ლაივზე); `new/processing`-ის წაშლა → 409 და `ig_taken` ბრაუზერში ცალკე დადასტურებული არ არის.
6. **საგანგებო (2026-10-16):** თუ `gemini-2.5-flash` გაითიშა, Render-ზე `GEMINI_MODEL=gemini-3.5-flash` + restart. ⚠️ 3.5-ზე thinking-ის გამო პასუხები იჭრება `max_output_tokens=800`-ზე (ტესტზე 4/10) — ბოლო გამოსავალია (Backlog T12).
7. **key-ების როტაცია:** ✅ `FB_APP_SECRET` — შეცვლილია; ✅ Supabase — legacy key-ები გამორთულია, 401 დადასტურებულია (T23); ✅ `FB_TOKEN_ENCRYPTION_KEY` — შეცვლილია (Render + ლოკალური `.env`), ერთადერთი Facebook/Instagram-მიბმული მაღაზია ხელახლა დაკავშირდა, ბოტი პასუხობს. ⏳ **ღია: Gemini key-ის როტაცია** — როდის, მფლობელი წყვეტს.
8. ✅ ლოკალურ `.env`-ში `APP_ENV=development` (მფლობელმა დაადასტურა).

### 🔑 Supabase API key-ების გადასვლა (T23) — ზუსტი რიგი
> key-ების მნიშვნელობებს მფლობელი სვამს. **ძველი service_role გაჟონა → ის ძალაში რჩება, სანამ legacy key-ები არ გამოირთვება (ნაბიჯი K7). არ გააჭიანურო.**
> ახალი env სახელები: `SUPABASE_PUBLISHABLE_KEY` (`sb_publishable_…`, ძველი: `SUPABASE_ANON_KEY`), `SUPABASE_SECRET_KEY` (`sb_secret_…`, ძველი: `SUPABASE_SERVICE_ROLE_KEY`). ახალი სახელი უპირატესია; ძველი მუშაობს fallback-ად. ცარიელ-მაგრამ-არსებული ახალი ცვლადი ძველს **ფარავს** → rollback-ისას ახალი ცვლადი **წაშალე**, ცარიელზე ნუ დააყენებ.
> სად ვიღებთ: Supabase Dashboard → Project Settings → API Keys → ახალი tab (Publishable / Secret). Secret key-ს არ ვაჩვენებთ არსად, არ ვაგზავნით.

- **K1. კოდის deploy** ✅ (მფლობელი) (merge `agent-system` → `main` + push). ძველი env ჯერ არ იცვლება — ბოლო ეტაპზე ცვლილება უხილავია (fallback). frontend `config.js`-ში ახლა ველი უკვე `SUPABASE_PUBLISHABLE_KEY`, მნიშვნელობა ჯერ ძველი anon JWT. შემოწმება: საიტი/პანელი/ბოტი ისევ მუშაობს.
- **K2. Render env:** ✅ დაამატე `SUPABASE_SECRET_KEY=sb_secret_…` და `SUPABASE_PUBLISHABLE_KEY=sb_publishable_…` (ძველებს ჯერ ნუ წაშლი) → Render restart.
- **K3. შემოწმება backend-ზე ✅ (მფლობელი: ფოტოს ატვირთვა 200, შეკვეთა 201, ლოგში შეცდომა არ არის) ახალი key-ებით** (ეს არის ერთადერთი ადგილი, სადაც `sb_secret_`-ის რეალური მუშაობა დგინდება — offline ვერ დადასტურდა):
  - პანელში login, მაღაზიების/პროდუქტების სია (publishable + მომხმარებლის JWT, RLS);
  - ფოტოს ატვირთვა/წაშლა (Storage, secret key);
  - საჯარო შეკვეთა `order.html`-იდან (service client);
  - Messenger-ში ბოტი პასუხობს (webhook → service client);
  - admin პანელი იხსნება (service client);
  - Render-ის ლოგში `Invalid API key`/`401`/`permission denied` არ არის.
  თუ რამე ცუდადაა — **rollback:** წაშალე `SUPABASE_SECRET_KEY` და `SUPABASE_PUBLISHABLE_KEY` Render-ზე (ძველი სახელები გააგრძელებს მუშაობას), restart.
- **K4. ლოკალური `.env`:** ✅ (ახალ სახელებზეა) იგივე ორი ცვლადი ახალი სახელებით (ძველი ორი ხაზი წაშალე); ლოკალური backend-ი production Supabase-ს უკავშირდება — მხოლოდ შენ გაუშვი.
- **K5. frontend:** ✅ `public/config.js` და `dist/` განახლებულია `sb_publishable_…`-ით (commit agent-system-ზე; push/deploy და ქვემოთ ჩამოთვლილი ხელით შემოწმებები ჯერ მფლობელს ელის) — `frontend/public/config.js`-ში `SUPABASE_PUBLISHABLE_KEY`-ის მნიშვნელობა შეცვალე `sb_publishable_…`-ით (ეს key საჯაროა, git-ში ჩადება ნორმალურია) → `cd frontend && npm run build` → commit `public/config.js` + `dist/` → push. შემოწმება: login/logout, რეგისტრაცია, პაროლის აღდგენა (`reset.html`), `order.html` (მენიუ იტვირთება), admin.html.
- **K6. Render env-ის გასუფთავება:** ✅ (მფლობელი: ძველი ორი ცვლადი წაშლილია, deploy live, შეკვეთა 201 მხოლოდ ახალ key-ებზე) წაშალე `SUPABASE_SERVICE_ROLE_KEY` და `SUPABASE_ANON_KEY` → restart → K3-ის შემოწმება ხელახლა (დარწმუნდი, რომ ახალი სახელები ნამდვილად მუშაობს და fallback-ზე არ იყავი).
- **K7. legacy key-ების გამორთვა:** ✅ (მფლობელი: გამორთულია) Supabase Dashboard → Project Settings → API Keys → **Legacy API keys** → გამორთვა („Disable JWT-based API keys" / legacy anon & service_role). ეს ააქტიურებს გაჟონილი service_role-ის გაუქმებას. ეფექტი: ძველი anon/service_role JWT-ები აღარ მუშაობს; მომხმარებლების სესიის JWT-ები Auth-ისაა და არ ირღვევა. უკან დასაბრუნებელია Dashboard-იდან (დროებით, თუ რამე გაფუჭდა).
- **K8. შემოწმება K7-ის შემდეგ:** ✅ ძველი anon key-ით REST მოთხოვნა → 401 (მფლობელმა დაადასტურა; გაჟონილი service_role-ის ცალკე curl-ზე ინფორმაცია არ მიმიღია, მაგრამ legacy JWT key-ები სრულად გამორთულია) — იგივე სია, რაც K3 + ახალი მომხმარებლის რეგისტრაცია/login + admin. გაჟონილი service_role-ით სცადე ერთი read (curl `apikey: <ძველი>` → 401 უნდა იყოს) — ამით დაადასტურებ, რომ გაუქმდა.
- **K9. გაჟონვის შემდეგ:** გადახედე Supabase Logs/Auth-ს საეჭვო აქტივობაზე (უცნობი მომხმარებლები, მასობრივი წაკითხვა/წაშლა) იმ პერიოდში, როცა key ძალაში იყო; საჭიროებისას ეს ცალკე task იქნება.

### Stage 11 — Deploy plan
- ✅ **Stage 11 deploy დასრულდა (მფლობელი): `0d7a129` live** (`main` = `agent-system` = `0d7a129`; S11-1…S11-4, ბრენჩის წესი CLAUDE.md-ში). მიგრაცია 0021 ლაივ ბაზაზე უკვე გაშვებული იყო.
- **S11-1 (მიგრაცია `0021_change_order_status.sql`) ✅ ლაივ ბაზაზე გაშვებულია და შემოწმებულია (მფლობელი): 1 ფუნქცია, `security_definer=false`, EXECUTE მხოლოდ `postgres` და `service_role`. დარჩა: backend deploy + ქვემოთ ნაბიჯი 4 (ხელით შემოწმება). (ორიგინალი რიგი/პროცედურა:** რიგი — **ჯერ 0021, მერე backend deploy** (ძველი backend 0021-თან მუშაობს; ახალი backend 0021-ის გარეშე სტატუსის შეცვლა სუფთად 400-ს აბრუნებს, მონაცემები უცვლელია.)
  1. PRE-CHECK: `select proname from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname='public' and proname in ('decrement_stock','apply_stock_delta');` → 2 მწკრივი.
  2. გაუშვი `0021_change_order_status.sql` (იდემპოტენტურია).
  3. Verification: `select p.proname, p.prosecdef as security_definer, coalesce(array_to_string(p.proacl, E'
'),'(PUBLIC-საც აქვს!)') as acl from pg_proc p join pg_namespace ns on ns.oid=p.pronamespace where ns.nspname='public' and p.proname='change_order_status';` → 1 მწკრივი, `security_definer=false`, acl-ში `service_role=X/…` და **არა** `=X/…`, `anon=X/…`, `authenticated=X/…`.
  3b. ✅ **გაშვებულია ლაივზე (მფლობელი): `SMOKE OK — rolled back`, სატესტო მონაცემი 0.** **Smoke-ტესტი (S11-4, გაუშვი deploy-მდე, 0021 უკვე ლაივზეა):** SQL Editor-ში ჩასვი მთელი `supabase/checks/smoke_change_order_status.sql` → RUN. რედაქტორი აჩვენებს „შეცდომას" — ეს ნორმალურია: `SMOKE OK — rolled back` = 12-ვე შემოწმება გავიდა და ბაზაში არაფერი დარჩა (ტრანზაქცია ბათილდება); `SMOKE FAIL: …` = ტექსტი დააკოპირე და deploy გააჩერე; `SMOKE SKIP: no auth.users row` = უნდა არსებობდეს ერთი მომხმარებელი; სხვა შეცდომა (not-null/check/function does not exist) = სქემა/0021 განსხვავდება, ესეც rollback-დება. არჩევითი შემოწმება: `select count(*) from public.shops where name like '\_\_SMOKE\_\_%';` → 0. ⚠️ ფაილი არასდროს გაშვებულა — პირველი გაშვება შენთან.
  4. ✅ (მფლობელი, ლაივზე) პანელში მარაგი: 102 → `processing` 100 → `cancelled` 102; ✅ `new → cancelled` (მარაგი უცვლელი) და მოძველებული სტატუსი → `STATUS_CHANGED` — smoke SQL-ის შემოწმებები 4 და 8.
- **S11-3:** ახალი არჩევითი env `GEMINI_TIMEOUT_SECONDS` (default 20 წმ; ბიუჯეტი ყველა retry-ზე ჯამში 45 წმ). დამატებითი ნაბიჯი არ სჭირდება, ერთ deploy-ში მიჰყვება. შემოწმება: ბოტი ჩვეულებრივად პასუხობს; timeout-ის ქცევა (fallback პასუხი) ლაივზე რეალურად არ გამოცდილა.
- **S11-2:** დამატებითი ნაბიჯი არ სჭირდება (backend + `dist/` ერთ deploy-ში). შემოწმება: ორი გვერდის წვდომით connect → ფანჯარაში შეტყობინება „თავიდან მიაბით…"; ერთი გვერდით → ჩვეულებრივად.

### 🚦 Live-მდე აუცილებელი (მფლობელის სია, 2026-10-09)
> ეს ნაბიჯები ჯერ არ არის შესრულებული/დადასტურებული, თუ სხვაგვარად არ წერია. "Live" = Meta App Live mode + რეალური გამყიდველები.
0. **Meta Graph API `v21.0` მოქმედებს 2027-01-21-მდე** (`FB_GRAPH_VERSION`, `config.py`). ვადამდე განახლდეს ახალ ვერსიაზე — ტესტით (Graph mock-ტესტები + ლაივზე webhook/OAuth/გაგზავნის შემოწმება) და არა ბრმად.
1. **`PAYMENT_IBAN`** (მაგ. `GE00XX0000000000000000`, 22 სიმბოლო; სურვილისამებრ მიმღები) და **`PAYMENT_CONTACT`** (ელფოსტა/ტელეფონი, სადაც გამყიდველი ქვითარს გამოგზავნის) — Render env-ში. მფლობელი დააყენებს Live-მდე; დააყენების გარეშე გამყიდველი პაკეტის მოთხოვნისას placeholder-ს ხედავს (`Dashboard.jsx`). (Backlog #27)
2. **Render plan = Starter და არა Free.** Free instance უმოქმედობისას „იძინებს" (`DEPLOYMENT.md`): პირველ webhook-ზე პასუხი Meta-ს timeout-ს აღემატება და შეტყობინება იკარგება + მეხსიერებაში არსებული ლიმიტები/dedup (`_SEEN_MIDS`, rate-limit) ნულდება. შეამოწმე Dashboard → service → Instance Type = **Starter** (always-on) და რომ **ერთი instance**-ია (Scaling: 1) — Accepted Risks #6, #9 სწორედ ერთ instance-ს ეყრდნობა; >1 instance-ზე ისინი უქმდება.
3. **`CORS_ORIGINS=https://chatassist.ge`** Render-ზე (Accepted Risks #11).
4. **Gemini billing ჩართული** (free tier = 5 მოთხოვნა/წთ; ტრაფიკზე ბოტი 429-ს დააბრუნებს — `PROJECT.md` Constraints) + **Gemini key-ის როტაცია** (ღიაა, იხ. ზემოთ ნაბიჯი 7).
5. **Gemini მოდელი** — `gemini-2.5-flash` 2026-10-16-ს ითიშება: გადაწყვეტილება/საგანგებო ნაბიჯი 6 (Backlog T12).
6. ✅ **Stage 11-ის deploy** (`0d7a129` live). ხელით/ლაივზე დადასტურებული: მარაგი processing/cancelled-ზე (102 → 100 → 102), smoke SQL (`SMOKE OK`, შემოწმებები 4 და 8 ჩათვლით). შეუმოწმებელი (მფლობელის გადაწყვეტილებით): S11-2 ბრაუზერში, S11-3 ლაივზე.
7. ✅ **ნაბიჯი 5-ის ხელით შემოწმებები** — `/status` → `env=production` (2026-10-08), GitHub CI მწვანეა, `orders` ცარიელი იყო deploy-მდე (T20-ის სათადარიგო პირობა დახურულია).
8. **K9:** Supabase Logs/Auth-ის გადახედვა გაჟონვის პერიოდისთვის.
9. **Meta (README §2):** Business Verification ⏳ → App Review ⬜ → Development → Live ⬜. Review-ისთვის: Privacy/Terms/Data Deletion URL-ები და callback არსებობს (Accepted Risks #19).
10. **Supabase Pro (Free გეგმაზე backup-ები საერთოდ არ არის — Dashboard-ში დადასტურდა, მფლობელი).** Live-მდე გადადი Pro-ზე, რომ DB-ს ავტომატური ყოველდღიური backup ჰქონდეს; ახლა შეკვეთების, მარაგისა და გამყიდველების მონაცემის დაკარგვის შემთხვევაში აღდგენა შეუძლებელია. გადასვლის შემდეგ Dashboard → Database → Backups-ში შეამოწმე, რომ backup-ები ჩანს, და ერთხელ გადაამოწმე აღდგენის გზა (Pro-ზე PITR ცალკე add-on-ია, ვადა დამოკიდებულია გეგმაზე — დააზუსტე Dashboard-ში). ხარჯი ბიუჯეტში (~35₾/თვე, `DEPLOYMENT.md`) არ არის გათვალისწინებული — განაახლე `DEPLOYMENT.md`-ის ხარჯების ცხრილი.

### 🚀 S11-5 / S11-6 — Deploy plan (გარე აუდიტი #1–#3) — ✅ დასრულებულია (მფლობელი, ლაივზე)
1. ✅ Render-ის production-ის აუცილებელი ცვლადები: შვიდივე არსებობს (`SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_SECRET_KEY`, `GEMINI_API_KEY`, `FB_APP_SECRET`, `FB_VERIFY_TOKEN`, `FB_TOKEN_ENCRYPTION_KEY`).
2. ✅ Backend deploy: `955cde6` live, fail-closed startup გავიდა (სერვერი ადგება).
3. ✅ PRE-CHECK: free-პაკეტის მაღაზიებს `knowledge` არ აქვთ (გასასუფთავებელი არაფერია).
4. ✅ `0022_revoke_orders_knowledge_update.sql` ლაივ ბაზაზე გაშვებულია; verification 15/15 ემთხვევა მოსალოდნელს.
5. ✅ პანელში (მფლობელი, 0022-ის შემდეგ): knowledge POST/DELETE → 200; შეკვეთის სტატუსის PATCH → 200.
   - ℹ️ „მაღაზიის სახელის შეცვლა" პანელში არ არსებობს, ამიტომ ეს შემოწმება არ ეხება (backend-ში `auth.client`-ით მხოლოდ `bot_language` იწერება — `PATCH /shops/{id}`).
   - ⏳ ბოტის ენის შეცვლა (`bot_language`, ერთადერთი დარჩენილი `auth.client` ჩაწერა `shops`-ზე) 0022-ის შემდეგ ცალკე არ დადასტურებულა.

### Branch `agent-system` → `main`: მზადყოფნა (შემოწმდა 2026-10-08)
- `main` არ წასულა წინ (0 commit-ი `agent-system`-ის გარეშე) → merge fast-forward-ია; `git merge-tree` კონფლიქტს არ აჩვენებს. 27 commit, 42 ფაილი.
- სუფთა venv-ში CI-ის ნაბიჯები (`requirements.lock.txt` + `requirements-dev.txt` → `pip check` → `compileall` → `ruff check app tests` → `pytest -q`, `.env`-ის გარეშე): ყველა გავიდა, 174 passed. ლოკალური Python-ის ვერსია შეიძლება CI-ის 3.14.3-ისგან განსხვავდებოდეს — GitHub-ზე რეალური CI გაშვება: ✅ მწვანეა (მფლობელმა დაადასტურა 2026-10-09).
- Frontend: `npm run build` ახლა `frontend/dist/`-ს არ ცვლის (git status სუფთაა) → dist commit-შია და აქტუალურია.
- `git status` სუფთაა; secrets repo-ში არ ჩაგდებულა (T19: ტესტები `.env`-ს არ კითხულობენ).

## Backlog (needs user decision)
- **T12 (გადადებულია 2026-10-08; → ჩანაცვლებულია Stage 14/15-ით, 2026-10-28) — Gemini მოდელი / AI provider-ის შეფასება.** მომავალი ეტაპი: AI provider-ის შეფასება — gemini-2.5-flash, gemini-3.5-flash (შეზღუდული thinking-ით) და Claude Haiku 4.5; შედარება ხარისხით, სიჩქარით და ფასით (თითო პასუხზე).
  - შედარების სკრიპტი არსებობს: `backend/scripts/compare_gemini_models.py` (პირველი შედეგი — Decision Log 2026-10). multimodal (ფოტოს გაგება) და `[[HANDOFF]]` ჯერ მხოლოდ ტექსტზეა შემოწმებული.
  - ⏰ დედლაინი: gemini-2.5-flash ითიშება 2026-10-16 — საგანგებო ნაბიჯი Deploy plan-შია.
- **T13 (გადატანილია Backlog-ში 2026-10-08) — ORIGIN_SECRET Render-ზე (მფლობელის ქმედება, კოდი არ სჭირდება)** · `backend/app/main.py:124-168`
  - წინაპირობა: Cloudflare ნამდვილად პროქსირებს `chatassist.ge`-ს (ნარინჯისფერი ღრუბელი). ინსტრუქცია — იხ. ჩატის ახსნა; ჩემგან Render-ზე არაფერი კეთდება.
  - Verify (მფლობელი): `curl -i https://<render-url>.onrender.com/status` → 403; `https://chatassist.ge/status` → 200; Messenger-ში ბოტი პასუხობს.
- [x] **T15 — წამკითხველი SQL: 0014–0016 გაშვებულია თუ არა ლაივ ბაზაზე** · `supabase/checks/check_0014_0016.sql`
  - მხოლოდ SELECT (არაფერს ცვლის); აგრეგირებს 0014/0015/0016 ფაილებში არსებულ verification query-ებს ერთ ფაილში,
    თითო შედეგი — ერთი მკაფიო სტრიქონი (migration, ok true/false, რა აკლია). **გაშვება — მფლობელი** (SQL Editor).
  - Verify: ფაილში არც ერთი DDL/DML (grep), query-ები ემთხვევა მიგრაციების ფაილებს.
- [x] **T16 — product-images ბილიკების სტრუქტურა და T5 cleanup-ის გასწორება** · `backend/app/api/products.py`, `backend/app/api/admin.py`
  - კოდიდან დადგინდეს, რა ბილიკებით ინახება ფოტო (`{shop_id}/...` ბრტყელი თუ ქვესაქაღალდეები); თუ ქვესაქაღალდეებია — `admin._remove_shop_images` რეკურსიულად წაშალოს.
  - Verify: ტესტი ქვესაქაღალდიანი fake-ით (თუ ბრტყელია — დადასტურება მოკლედ, ტესტი ბრტყელზე).
  - ✅ შედეგი: ბილიკი ყოველთვის ბრტყელია `{shop_id}/{uuid}.{ext}` (`products.py:179`, ერთადერთი upload) → cleanup-ის გასწორება არ სჭირდება. ისტორიული ხელით ატვირთული nested ობიექტები offline ვერ შემოწმდა.
- [x] **T14 — T2-ის შედეგი: ტექსტების გასწორება (frontend + delete_order)** · `frontend/src/**`, `backend/app/api/orders.py`
  - გამყიდველის პანელი / `order.html` შეიძლება ამბობდეს „მარაგი დაჯავშნილია / გაუქმებისას დაბრუნდება" — გადასამოწმებელია.
  - `delete_order`-ის 409 შეტყობინება და `DELETABLE_STATUSES` კომენტარი `new`-ისთვის ზუსტი აღარ არის (ტესტი d1 ამოწმებს ტექსტს).
  - Verify: grep ძველ ტექსტებზე; `npm run build` + `dist/` იმავე commit-ში; `pytest -q`.
  - მიზეზი: Cloudflare ახლა არ გამოიყენება; ნაცვლად — T17. დაბრუნდება Cloudflare-ის მომავალ ჩართვასთან ერთად.
### Stage 12 აუდიტიდან (nit, 2026-10-09)
- B-12-ის ნარჩენი (S12-1-ის შემდეგ): კლიენტის FB/IG CDN URL-ებზე DNS rebinding TOCTOU და `100.64/10` (CGNAT) `is_private`-ით არ იფარება → `ip.is_global` (`services/facebook.py` `_is_public_http_url`).
- ტესტი: `resolve_attention`-ის service update-ის `.eq("shop_id")` ფილტრის assert (knowledge-ისას დაემატა, აქ — არა).
- `get_current_admin`-ის tier/approve გზებზე ბოტის ხელით ჩართვა (`PATCH /admin/shops` `bot_enabled=true`) ჭერს არ ამოწმებს (ადმინის შეგნებული ქმედებაა).
- `docs`: README 157/175/201 ("19 მიგრაცია", „მარაგი ავტომატურად კლებულობს" → `processing`-ზე) — Stage 11 nit-ებიდან დარჩენილი.
- Finish-check (Stage 12): partial unique index (0024) მაღაზიაზეა, pending კი per-account → ორი პარალელური მოთხოვნა ერთი მფლობელის სხვადასხვა მაღაზიიდან ორ pending-ს დატოვებს; ერთი მაღაზიის პარალელურ მოთხოვნაზე მეორე 23505→500. იშვიათია; ნამდვილი per-account unique `owner_id` სვეტს (ან RPC-ს) მოითხოვს.
- Finish-check (Stage 12), გასწორდა: PROGRESS.md-ის დუბლირებული ბლოკი, `shop_usage` pending per-account, Storage prefix-ის ნორმალიზაცია (host-ის რეგისტრი/პორტი), CLAUDE.md CI-ის აღწერა, ზღვრის კომენტარის სიზუსტე.
### Stage 11 finish-check nits (2026-10-09, standard-reviewer)
- **❓ გადაწყვეტილება — გვერდების არჩევა (S11-2):** გამყიდველი, რომელსაც FB ანგარიშით 2+ გვერდი მართავს (standard/business — 2 ან ულიმიტო მაღაზია), ხელახალ connect-ზე უარს იღებს, მაშინაც კი, როცა არჩევანი ცალსახაა (მაღაზიას უკვე აქვს `facebook_page_id`, ან მეორე გვერდი ამავე მფლობელის სხვა მაღაზიაზეა მიბმული). მიმდინარე ქცევა — შენი გადაწყვეტილება (ა). შემოთავაზება: კანდიდატებიდან ამოვიღოთ ამავე მფლობელის სხვა მაღაზიებზე მიბმული გვერდები; თუ ამ მაღაზიის არსებული `facebook_page_id` სიაშია — ის; თუ ზუსტად 1 კანდიდატი რჩება — გამოვიყენოთ, სხვა შემთხვევაში `multiple_pages`. ⚠️ დაუდასტურებელია Meta-ს ქცევა: ხელახალ login-ზე გვერდის არჩევის დიალოგი ჩანს თუ არა, და გვერდის მონიშვნის მოხსნა სხვა მაღაზიაზე შენახულ token-ს აუქმებს თუ არა (თუ აუქმებს, ერთი FB ანგარიშით ორ მაღაზიას ორი გვერდით ვერ დააკავშირებ).
- 0021: დაბრუნების გზაზე `apply_stock_delta` დაუხარისხებელ items-ს იღებს, `decrement_stock` — დახარისხებულს → ორი შეკვეთის პარალელური საპირისპირო რიგით ცვლილებისას deadlock (40P01) შესაძლებელია (შედეგი: ტრანზაქცია უკან ბრუნდება, 400, მონაცემი არ ფუჭდება). Fix: ორივე გზას იგივე დახარისხებული სია.
- 0018: `authenticated`-ს `UPDATE(status)` ისევ აქვს, backend მას აღარ იყენებს → `revoke update (status) on public.orders from authenticated` (ახლა RPC ერთადერთი ჩამწერია; ზიანი მხოლოდ საკუთარ მარაგზე).
- 0021: `set search_path` არ არის (Supabase advisor: `function_search_path_mutable`; exploit არ არსებობს, ყველა მიმართვა schema-qualified-ია, INVOKER).
- `GEMINI_TIMEOUT_SECONDS` არ ვალიდირდება: 0/უარყოფითი → ყოველი მცდელობა 1 ms-ში ჩავარდება, ბოტი ყოველთვის fallback-ს გასცემს (`Field(gt=0, le=45)`).
- `bot.py`: httpx-ის timeout ფაზაზეა (connect/read/write/pool = 20 წმ), არა მთლიან მოთხოვნაზე → პათოლოგიურ შემთხვევაში ერთი მცდელობა 20 წმ-ს გადააჭარბებს; კომენტარი „ერთი მცდელობის timeout" არაზუსტია. 504 / DEADLINE_EXCEEDED `_TRANSIENT`-ში არ არის (S11-მდეც ასე იყო).
- 0021-ის header-ის კომენტარი ამბობს „500", რეალურად 400 (`orders.py`, test_s7) — დოკუმენტაცია.
- `FB_REDIRECT_URI` production-ის აუცილებელ სიაში არ არის (ცარიელი → OAuth connect გატეხილი, მაგრამ სერვერი ადგება); დაემატოს `missing_required_secrets()`-ს, თუ გინდა.
### Stage 11-ის აუდიტიდან (nit, 2026-10-09)
- **#15** საუბრის ისტორიის race: Messenger-ში ორი სწრაფი შეტყობინება პარალელურად მუშავდება, ორივე ძველ history-ს კითხულობს → ბოტის მეხსიერებიდან ერთი turn იკარგება (`webhook.py` `_save_turn`). კლიენტს ორივე პასუხი მიდის. Fix: append RPC.
- **#17** admin revenue `new` + `processing` + `done`-ს ერთად ითვლის (`admin.py` overview); B-1-ის შემდეგ `new` დაუდასტურებელია → ცალკე „დასრულებული" (done) და „მოლოდინში" მაჩვენებელი.
- **#24** stale `dist/`-ის რისკი: CI-ში `npm ci && npm run build && git diff --exit-code frontend/dist` (იაფია და დავიწყებულ build-ს იჭერს).
- **#27** `PAYMENT_IBAN`/`PAYMENT_CONTACT` default-ად placeholder ტექსტია (`config.py`) → გამყიდველი placeholder-ს ნახავს, თუ Render-ზე არ არის დაყენებული. მფლობელის შესამოწმებელი + production startup warning.
- **#1-ის ნარჩენი** Send API-ს ჩავარდნისას (მაგ. ვადაგასული token) კლიენტი პასუხს ვერ იღებს და ეს მხოლოდ ლოგში ჩანს (`webhook.py`) → საუბარი `needs_attention`-ად მოინიშნოს, რომ გამყიდველმა დაინახოს.
### Finish-check nits (2026-10-08, standard-reviewer)
- 0018-ის header-ის დასაბუთება ზუსტი არ არის: გამყიდველს PostgREST-ით `status`-ის პირდაპირ შეცვლა მაინც შეუძლია (`new → processing` დაკლების გარეშე, მერე API-ით `→ cancelled` = მარაგი +N). ზიანი მხოლოდ საკუთარ მარაგზე (`products.quantity`-საც ისედაც ცვლის, 0015). სრულად დახურვა: UPDATE-ის სრული revoke და status-ის ჩაწერა service-ით ownership-ის შემდეგ.
- `orders.py:410-411`: `_apply_stock_delta(+1)` შეცდომა სტატუსის შეცვლის შემდეგ 500-ს აბრუნებს — try/except + `logger.exception`.
- `facebook.py`: პარალელური connect-ის race-ზე unique violation `page_taken`-ად მიდის `ig_taken`-ის ნაცვლად; `any(...)` `.neq`-ის შემდეგ ზედმეტია.
- `admin.py:396-401`: storage cleanup-ის ციკლი — `break`, თუ `paths` არ შეცვლილა.
- `webhook.py`: `_RATE_PER_SHOP = 30/წთ` ყველა პაკეტისთვის ერთია; 5 spam PSID მაღაზიის ბოტს წუთით აჩერებს.
- README: 157 („19 მიგრაცია" → 20), 175/201 („მარაგი ავტომატურად კლებულობს" → `processing`-ზე).
### Nits (აუდიტიდან)
- ~~**A-9 / B-6**~~ — დაიხურა S11-6-ით (production fail-closed + ცარიელი secret-ის უარი + `"chatassist"` fallback ამოღებულია). ნარჩენი: `encrypt` `subscribe_page`-ის შემდეგაა (`api/facebook.py`).
  production-ში `FB_TOKEN_ENCRYPTION_KEY`/`FB_APP_SECRET` startup-ზე არ მოწმდება; `encrypt` `subscribe_page`-ის შემდეგაა (`api/facebook.py:253`).
- ~~**A-6**~~ — დაიხურა S11-5-ით (migration 0022: `knowledge*`-ზე UPDATE მოხსნილია, ჩაწერა მხოლოდ backend-ით service client-ით).
- **A-7** — `/admin/recovery` ადმინს recovery ბმულს აბრუნებს + `{e}` შეცდომაში (`admin.py:443-453`).
- **A-8** — upgrade request-ის resolve `status='pending'`-ს არ ამოწმებს (`admin.py:416-439`).
- **A-10** — მაღაზიის/პროდუქტის ლიმიტი TOCTOU (პარალელური POST-ით მცირე გადაჭარბება).
- **B-7** — არა-ASCII შეყვანა `hmac.compare_digest`-ს 500-ით აგდებს (`webhook.py:170`, `services/facebook.py:101,148`, `api/facebook.py:110`).
- **B-8a** — webhook batch-ში ერთი entry-ს exception დანარჩენებს კარგავს (`webhook.py:201-243`).
- **B-8b** — `_SEEN_MIDS` threadpool-იდან lock-ის გარეშე იცვლება (`webhook.py:61-77`).
- **B-10** — გვერდის „დაკავება" სხვის უფასო მაღაზიაზე; ნამდვილ მფლობელს მხოლოდ `page_taken` (`api/facebook.py:269-274`).
- **B-11** — popup-ის `message` listener origin/source-ს არ ამოწმებს (`frontend/src/panel/fbConnect.js:19-24`).
- **B-12** — SSRF: DNS rebinding TOCTOU, `is_private` არ ფარავს 100.64/10 → `is_global` + მხოლოდ საკუთარი Storage URL (`services/facebook.py:279-334`).
- **B-13** — კლიენტის ფოტოები `INLINE_IMAGE_BUDGET`-ს არ ემორჩილება (`webhook.py:313-317`).
- **B-14** — prompt extraction-ით PDF-ცოდნა ფაქტობრივად საჯაროა → გამყიდველს UI-ში გაფრთხილება (`bot.py:194-197`).
- ~~Frontend lint (eslint) — არ არის; საჭიროა თუ არა?~~ → Stage 13 (S13-1, S13-4).
- README მოძველებულია: `ADMIN_EMAIL` → `ADMIN_USER_IDS`, „ტესტები არ არსებობს", React 18 → 19, მიგრაციები 14 → 16.

### მფლობელის შესამოწმებელი (კოდით ვერ დადასტურდა)
- Render env: `APP_ENV=production`? (`GET https://chatassist.ge/status` → `env`), `ORIGIN_SECRET` დაყენებულია?
  (თუ არა — `CF-Connecting-IP` ყალბდება და IP-ლიმიტები უქმდება), `CORS_ORIGINS`, `FB_TOKEN_ENCRYPTION_KEY`.
- `product-images` bucket-ის policy-ები `storage.objects`-ზე (მიგრაციებში არ არის): შეუძლია თუ არა `authenticated`-ს პირდაპირ upload/delete?
- live DB-ში 0014 / 0015 / 0016 გაშვებულია? (verification query-ები ფაილებშია)
- Supabase Auth: anonymous sign-ins გამორთულია? email confirmation ჩართულია?
- ⏰ Gemini 2.5 Flash retires **2026-10-16** — რომელ მოდელზე გადასვლა?

### Stage 13 (დაგეგმვისას, 2026-10-27)
- სრული `npm audit` (dev-ის ჩათვლით) — 2 high dev-dependency-ებში: vite 8.2.0–8.2.2 (მხოლოდ dev-server) და source-map-js ≤1.2.1 (AUDIT A-014-ის გაგრძელება; production bundle-ში არ ხვდება; Stage 13-მდეც არსებობდა). CI-ში მხოლოდ `--omit=dev`. Fix: `npm audit fix` / vite-ის განახლება ცალკე, `dist`-ის diff-ის გადახედვით.
- ESLint warning-ები (S13-4-ში განზრახ არ გასწორდა): `AdminPage.jsx:91` `react-hooks/exhaustive-deps` (`load` deps-ში არ არის; დამატება ქცევის ცვლილებაა — `load`-ის `useCallback` ან effect-ში გადატანა, ტესტით); `react-refresh/only-export-components` — `OrdersTab.jsx:6,14`, `ShopData.jsx:6`, `ui.jsx:5` (მხოლოდ dev HMR; fix = კონსტანტების/hook-ის ცალკე ფაილში გატანა).
- `ui.jsx` `ToastProvider`: `setTimeout` არ სუფთავდება და ახალი toast ძველის timer-ს არ აუქმებს → ორი toast-ის სწრაფად ზედიზედ გამოძახებისას მეორე ადრე ქრება (S13-3-ის მიგნება; fix = timer-ის ref + `clearTimeout`, ქცევის ცვლილებაა → ცალკე task).
- Finish-check (Stage 13), nit-ები:
  - `ci.yml:50-51` — `npm audit --omit=dev` lint/test/build-ის წინაა: ახალ advisory-ზე (კოდის ცვლილების გარეშე) job წითლდება და lint/test-ის შედეგი აღარ ჩანს → ნაბიჯი ბოლოში ან ცალკე job; სურვილისამებრ `--audit-level=high`.
  - `vite.config.js` `globals: true` ზედმეტია (ტესტები ცხადად აიმპორტებენ) და Testing Library-ს auto-cleanup-ს რთავს → `cleanup` ორჯერ ეშვება (უვნებელი). ერთ-ერთი ამოიღე.
  - `csv.test.js` — `fmtDate` ვალიდური თარიღის ტესტი სუსტია (`"Invalid Date"`-საც გაატარებს) → შეამოწმოს წელი/დღე.
  - `eslint@9.39.5` registry-ში deprecated-ია (9.x მხარდაჭერა დასრულდა) → ESLint 10-ზე გადასვლა plugin-ების თავსებადობის შემოწმებით (react-hooks 5.x pin რჩება).
- Playwright smoke (`/auto` ფაზა 1ბ) — ამ stage-ში გამოტოვებულია (Decision Log 2026-10-27); საჭიროების შემთხვევაში ცალკე task.

### Stage 14 (დაგეგმვისას, 2026-10-28)
- ისტორიული დოკუმენტები Gemini-ს ახსენებს და **არ** გადაიწერება: `MONETIZATION.md`, `ROADMAP.md`, `AUDIT.md`, `CODE_REVIEW_FINDINGS.md`, `CODE_REVIEW_PROMPT.md`, `REACT_MIGRATION.md`. საჭიროებისას — ცალკე docs task (მაგ. MONETIZATION-ის ხარჯის გათვლა Claude-ის ფასებით Stage 15-ის შემდეგ).
- `llm_usage`: პანელში/ადმინში ჩვენება, per-tenant ხარჯის ჭერი (სტანდარტი §28 — usage/cost limits), retention (ძველი რიგების წაშლა/აგრეგაცია) — Stage 15-ის რეალური მონაცემის შემდეგ.
- ძველი ჩანაწერების სტატუსი Stage 14-ის შემდეგ: Stage 11 nit „`GEMINI_TIMEOUT_SECONDS` არ ვალიდირდება" → იხურება S14-2-ით (`LLM_TIMEOUT_SECONDS` `gt=0, le=20`); nit „httpx-ის timeout ფაზაზეა" — SDK-ებზეც იგივე ნიუანსი რჩება; Deploy plan-ის ნაბიჯი 6 (`GEMINI_MODEL=gemini-3.5-flash`) და „Live-მდე აუცილებელი" 4–5 (Gemini billing/მოდელი) → ჩანაცვლდება Anthropic-ის billing/spend limit-ით Stage 14-ის deploy-ზე; „Gemini key-ის როტაცია" → key-ის გაუქმება Stage 14 — Deploy plan-ის ნაბიჯი 7-ის შემდეგ.
- key-ის გარეშე ოპერატორის პასუხი ყოველ შეტყობინებაზე იგზავნება (over-limit-ის მსგავსად, dedupe-ის გარეშე) — თუ პრობლემა გახდება, dedupe ბოლო bot შეტყობინების მიხედვით.

## Shared files
<!-- წესი: მხოლოდ task-ში აღწერილი ცვლილება; სხვისი ჩანაწერის შეცვლა/წაშლა არა; ერთ საერთო ფაილზე ორი task ერთდროულად არ მუშაობს — რიგი ქვემოთ. -->
- `backend/requirements.txt`, `backend/requirements.lock.txt` — **S14-1** (anthropic/openai დამატება) → **S14-7** (google-genai-ის წაშლა; მხოლოდ S14-5 და S14-6-ის შემდეგ).
- `backend/app/config.py` — **S14-2** (ახალი ველები, `GEMINI_API_KEY` fail-closed სიიდან) → **S14-5** (მხოლოდ `gemini_*` ველების წაშლა).
- `backend/tests/conftest.py` — **S14-2** (env: dummy key, blank/pop სიები) → **S14-4** (autouse guard რეალური LLM client-ების წინააღმდეგ).
- (Stage 13, დასრულებული) `frontend/package.json`, `frontend/package-lock.json` — S13-1 → S13-2.

## Blockers
- **მფლობელი — `ANTHROPIC_API_KEY`:** Stage 14 offline სრულდება key-ის გარეშე, მაგრამ `main`-ში merge/deploy და რეალური შემოწმება (cache, ქართული ხარისხი) მის გარეშე არ იგეგმება. რეკომენდაცია: Anthropic Console-ში ცალკე production workspace + spend limit.
- **მფლობელი — `OPENAI_API_KEY`:** Stage 15-ის ბრმა შედარებისთვის (ლოკალურად; Render-ზე არ სჭირდება, სანამ `LLM_PROVIDER=openai` არ გადაწყდება).
- **მფლობელი — gpt-6-luna-ს ოფიციალური ფასი და პარამეტრები** OpenAI-ის pricing/model გვერდზე (მესამე მხარის: $0.10 in / $0.50 out, cached ≈ $0.01 per MTok; Responses API, `prompt_cache_key`, reasoning-ის პარამეტრები — დაუდასტურებელი; PROJECT.md Open Questions).
- **მფლობელი — migration `0025_llm_usage.sql`** ხელით, SQL Editor-ში, backend deploy-**მდე** (`## Stage 14 — Deploy plan`, ნაბიჯები 1–3).

## Run State
- Stage: Stage 14 — LLM provider: Gemini → Claude / OpenAI, სამფენიანი prompt, llm_usage
- Finish-check this stage: not run
- Fix rounds this stage: 0/2
- Failed attempts: —

## Last Session
- Date: 2026-10-28
- Done: Stage 14-ის დაგეგმვა (არქიტექტორი): PROJECT.md (Current Stage, Decision Log 2026-10-28, API Contract, Open Questions), PROGRESS.md (S14-1…S14-9, Stage 14 — Deploy plan, Upcoming stages 15–18; Stage 13 → `## Stage 13 — Done`). კოდი არ შეცვლილა.
- Verification: — (მხოლოდ დოკუმენტები)
- Known issues / blockers: იხ. `## Blockers` (key-ები, gpt-6-luna-ს ფასი, 0025).
- Next: S14-1, S14-2, S14-3, S14-9 (დამოუკიდებელი) → S14-4 → S14-5 → S14-6 → S14-7 → S14-8.

### წინა სესია
- Date: 2026-10-27
- Done: Stage 13 დასრულდა — S13-1…S13-6 (commit-ები `ebf341e`, `a041fd0`, `783480a`, `2e011a0`, `29070c7`, `1e84ee1`; finish-check `85078d5`, 1 fix round). AUDIT A-016 დაიხურა.
- Verification (საბოლოო, სუფთა `npm ci`-ის შემდეგ): `npm audit --omit=dev` 0; `npm run lint` 0 error / 5 warning (Backlog); `npm test` 29/29 (4 ფაილი); `npm run build` → `dist` byte-identical (`git diff --exit-code -- frontend/dist` = 0); backend: compileall ✅, ruff ✅, pytest 271 passed.
- Unverified: GitHub Actions-ში ახალი ნაბიჯების რეალური გაშვება (push-ის შემდეგ); ბრაუზერში ვიზუალური შემოწმება არ ჩატარებულა (Playwright არ არის) — `dist` იდენტურია, ამიტომ production ცვლილება არ არსებობს.
- Next: მფლობელი — merge/push `main`-ზე და CI-ის მწვანე გაშვების დადასტურება; Backlog-ის Stage 13 nit-ები (+ voltbox-ს იგივე ESLint config ბაგი აქვს).
- წინა სესია (2026-10-09): Stage 12 (S12-1…S12-5) — `e8525f0` live, 0024 გაშვებულია; დარჩა Deploy plan-ის ნაბიჯი 5-ის ნაწილი და „Live-მდე აუცილებელი“ სია.

## Stage 13 — Done
Stage 13 — Frontend-ის ხარისხის შემოწმებები: ESLint 9 + Vitest + CI (მფლობელის მოთხოვნა, 2026-10-27; voltbox-ის ნიმუშით). ID-ები S13-n; commit: `S13-n: ...`.
**ფუნქციონალი და ვიზუალი არ იცვლებოდა.** production კოდს (`frontend/src/**`, ტესტების გარდა) ეხებოდა მხოლოდ S13-4, მხოლოდ ქცევის შემნარჩუნებელი გასწორებით. გადაწყვეტილებები — `PROJECT.md` Decision Log, 2026-10-27. დახურა AUDIT.md-ის **A-016**.
Finish-check: done (code-reviewer: 1 should-fix → S13-6, 3 nit; security-auditor: 0 critical/should-fix, 1 nit); fix rounds 1/2. საბოლოო: `npm audit --omit=dev` 0; lint 0 error / 5 warning; `npm test` 29/29; `dist` byte-identical; backend pytest 271 passed (შემდეგ deps-ის commit-ის შემდეგ — 274, CLAUDE.md).

> ყველა ბრძანება `frontend/`-იდან. საერთო „done when" ყველა task-ზე: `npm run build` გადის და, თუ `src/` არ შეცვლილა, `git diff --exit-code -- dist` სუფთაა; backend-ს არ ვეხებით (`pytest -q` 271 passed რჩება).

- [x] **S13-1 — ESLint 9 setup** ✅ eslint 9.39.5, react-hooks 5.2.0, react 7.37.5, react-refresh 0.5.7, globals 15.15.0. საწყისი lint: 1 error (`BotTab.jsx:1` no-unused-vars `useEffect`), 5 warning (4 react-refresh, 1 exhaustive-deps `AdminPage.jsx:91`); build/dist უცვლელი. · owner: task-executor · files: `frontend/package.json` (shared), `frontend/package-lock.json` (shared), `frontend/eslint.config.js` (ახალი) · depends: —
  - devDependencies: `eslint@^9.39`, `@eslint/js@^9.39`, `globals`, `eslint-plugin-react@^7.37`, `eslint-plugin-react-hooks@^5.2` (**არა 7.x** — Decision Log), `eslint-plugin-react-refresh@^0.5`. script: `"lint": "eslint ."` (`lint:fix` არ ემატება).
  - config — voltbox-ის (`D:/yvelaperi/saitebi/voltbox/frontend/eslint.config.js`) ნიმუშით: ignores `dist/**`, `node_modules/**`; `**/*.{js,jsx}` — browser globals, JSX, `settings.react.version: "19.2"`; წესები: react recommended + react-hooks recommended + `react-refresh/only-export-components: ["warn", { allowConstantExport: true }]`; off: `react/react-in-jsx-scope`, `react/jsx-uses-react`, `react/prop-types`; `no-unused-vars: ["error", { argsIgnorePattern: "^_", varsIgnorePattern: "^_", ignoreRestSiblings: true }]`. `no-console` **არ** ემატება. Node-ის ფაილებზე (`*.config.js`) node globals; `**/*.test.{js,jsx}` + `vitest.setup.js` — node + vitest globals. `public/config.js` / `config.example.js` (`window.APP_CONFIG`) — browser globals საკმარისია.
  - არსებულ კოდს **არ** ასწორებს (ეს S13-4-ია).
  - done when: `npm run lint` ეშვება და config-ის შეცდომის გარეშე ასრულებს (exit 0 ან 1 მხოლოდ `src/`-ის/`public/`-ის მიგნებებით; `eslint.config.js`-ში 0 error); report-ში — error/warning-ების რაოდენობა წესების მიხედვით; `npm run build` → `git diff --exit-code -- dist` სუფთა; `src/` უცვლელი.
- [x] **S13-2 — Vitest setup + `productDiff.test.js` Vitest-ზე** ✅ vitest 5.0.5, jsdom 30.1.3, @testing-library/react 16.3.3, jest-dom 6.9.1, user-event 14.6.8 (peer-კონფლიქტი არ ყოფილა; vite 8.2.2 უცვლელი); `npm test` 7/7; mutation-ით დადასტურდა, რომ ტესტი მართლა ეშვება; dist უცვლელი. · owner: task-executor · files: `frontend/package.json` (shared), `frontend/package-lock.json` (shared), `frontend/vite.config.js`, `frontend/vitest.setup.js` (ახალი), `frontend/src/panel/productDiff.test.js` · depends: S13-1 (იგივე shared ფაილები — თანმიმდევრულად)
  - devDependencies: `vitest@^5`, `jsdom@^30`, `@testing-library/react@^16`, `@testing-library/jest-dom@^6`, `@testing-library/user-event@^14`. scripts: `"test": "vitest run"`, `"test:watch": "vitest"`.
  - `vite.config.js`: `test: { environment: "jsdom", globals: true, setupFiles: ["./vitest.setup.js"] (აბსოლუტური გზით, როგორც `page()`), include: ["src/**/*.test.{js,jsx}"], restoreMocks: true }`. `build`/`base`/8 `.html` input უცვლელი.
  - `vitest.setup.js`: `@testing-library/jest-dom/vitest` + `afterEach(cleanup)`. `window.APP_CONFIG`-ის stub მხოლოდ თუ რომელიმე ტესტს სჭირდება (S13-2-ში — არა).
  - `productDiff.test.js`: `node:test`/`node:assert` → `vitest` (`test`, `expect`); იგივე შემთხვევები, იგივე რაოდენობა (7), იგივე ქართული სახელები; პირველი კომენტარი („გაშვება: node --test …") → `npm test`.
  - done when: `npm test` → 7 passed; `npm run lint` — `vite.config.js`, `vitest.setup.js`, `productDiff.test.js`-ში 0 error; `npm run build` → `git diff --exit-code -- dist` სუფთა (test ბლოკი build-ს არ ცვლის).
- [x] **S13-3 — საბაზისო კომპონენტის/utility ტესტები** ✅ +22 ტესტი (ui 10, csv 8, constants 4) → სულ 29/29; mutation-ით დადასტურდა (თითო ფაილი); production კოდი/dist უცვლელი. · owner: frontend-dev · files: `frontend/src/panel/ui.test.jsx` (ახალი), `frontend/src/lib/csv.test.js` (ახალი), `frontend/src/admin/constants.test.js` (ახალი) · depends: S13-2
  - `ui.jsx` (Testing Library): `BusyButton` — `busy` → `disabled` + `is-loading` კლასი, `children` ჩანს, დამატებითი props (`type`, `onClick`) გადაეცემა, default კლასი `btn btn-primary`; `Skeleton` — default 3 `.skel-item`, `n={5}` → 5; `ToastProvider`/`useToast` — `toast("…")` → `#toast`-ში ტექსტი + `toast-ok`, `toast("…", true)` → `toast-err`, `vi.useFakeTimers()`-ით 3500 ms-ის შემდეგ `hidden`.
  - `csv.js`: `toCSV` — BOM-ით იწყება, `\r\n` გამყოფი, მძიმე/ბრჭყალი/ახალი ხაზი → ციტირება და `""`; formula injection — `=SUM(1)`, `+x`, `@x` → `'`-ით; `-5`, `3.5` უცვლელი; `null`/`undefined` → ცარიელი. `fmtDate` — ცარიელი → `—`.
  - `constants.js`: `tierLabel("standard")` → „სტანდარტი", უცნობი → იგივე მნიშვნელობა.
  - production კოდი (`ui.jsx`, `csv.js`, `constants.js`) **არ იცვლება**; ტესტები offline, ქსელის/Supabase-ის გარეშე.
  - done when: `npm test` → ყველა გადის (7 + ახლები, რაოდენობა report-ში); `npm run lint` ახალ ფაილებში 0 error; `git diff --stat` — მხოლოდ სამი ახალი ფაილი.
- [x] **S13-4 — არსებული კოდის ESLint error-ების გასწორება (მხოლოდ ქცევის შემნარჩუნებელი)** ✅ ერთადერთი error — `BotTab.jsx:1` გამოუყენებელი `useEffect` import ამოღებულია; `eslint-disable` არ დასჭირდა; lint 0 error / 5 warning (Backlog); `dist` byte-identical (tree-shaken). · owner: frontend-dev · files: `frontend/src/**/*.{js,jsx}` (მხოლოდ lint-ის მიერ მონიშნული ხაზები; `*.test.*` გარდა), `frontend/public/config.js` / `frontend/config.example.js` (მხოლოდ თუ მონიშნულია), `frontend/dist/**` (rebuild) · depends: S13-3 (თანმიმდევრულად: S13-2/S13-3 `dist`-ის უცვლელობას ამოწმებენ, S13-4 კი მას ცვლის; `eslint.config.js`/`vite.config.js`/`vitest.setup.js`-ის lint-სისუფთავე — S13-1/S13-2-ის პასუხისმგებლობაა)
  - სწორდება მხოლოდ ის, რაც ქცევას და ვიზუალს არ ცვლის: გამოუყენებელი import/ცვლადი, ცარიელი block, `react/no-unescaped-entities` (`&quot;` და მისთ. — რენდერი იდენტურია), `react/jsx-key` მხოლოდ თუ key სტაბილურია და ახლაც ერთნაირია, და მისთ.
  - **არ** სწორდება: `react-hooks/exhaustive-deps` (warning; deps-ის შეცვლა ქცევაა), `react-refresh` warning-ები (ფაილის დაყოფა რეფაქტორია), ნებისმიერი error, რომლის გასწორება ქცევას ცვლის → იმ ხაზზე `// eslint-disable-next-line <rule> -- <მიზეზი>, Backlog S13` + report-ში სია (ფაილი:ხაზი, წესი, რატომ), რომ Backlog-ში ჩაიწეროს. config-ში წესი არ რბილდება.
  - JSX ტექსტი, className-ები, markup-ის სტრუქტურა და ქართული ტექსტები უცვლელია.
  - done when: `npm run lint` → exit 0 (0 errors); warning-ების რაოდენობა report-ში; `npm run build` გადის და `dist/` იმავე commit-ში; `dist/`-ის diff მხოლოდ JS bundle-ებშია (CSS/HTML უცვლელი — `git diff --stat -- dist`); თითო ცვლილებაზე report-ში მოკლე დასაბუთება „ქცევა უცვლელია".
- [x] **S13-5 — CI + დოკუმენტაცია** ✅ frontend job: `npm ci` → `npm audit --omit=dev` → lint → test → build → dist diff; CLAUDE.md `## Commands` (lint frontend, test frontend, CI); README (root ~421) + `frontend/README.md` (ორკესტრატორმა, docs — გეგმის „~ხაზი 9" ამ ფაილს ეხებოდა); ლოკალურად CI-ის მთელი თანმიმდევრობა exit 0. GitHub-ზე გაშვება — Unverified. · owner: task-executor · files: `.github/workflows/ci.yml`, `CLAUDE.md`, `README.md`, `frontend/README.md` · depends: S13-2, S13-3, S13-4
  - `ci.yml` frontend job, რიგით: `npm ci` → `npm audit --omit=dev` (სახელი „Vulnerability audit (prod deps)") → `npm run lint` → `npm test` → `npm run build` → `git diff --exit-code -- dist`. backend job უცვლელი. node 24 რჩება.
  - `CLAUDE.md` `## Commands`: ხაზი `lint`-ის ქვეშ — frontend: `cd frontend && npm run lint` (ESLint 9; CI-ში); ამოიღე „Frontend-ზე eslint არ არის."; `test`-ის ქვეშ — frontend: `cd frontend && npm test` (Vitest, `vitest run`, jsdom, offline); ამოიღე „frontend ტესტები არ არის"; CI-ის ხაზი — frontend job-ის ახალი ნაბიჯები. `.claude/`-ს არ ეხება.
  - `README.md` frontend-ის ბრძანებების ორ ბლოკში (~ხაზი 9 და ~421): `npm run lint`, `npm test`.
  - done when (S13-5): YAML სწორია (ჩაღრმავება backend job-ის მსგავსი; ხელით გადაკითხვა); CLAUDE.md-ის ბრძანებები ზუსტად ემთხვევა `package.json`-ის scripts-ს; ლოკალურად CI-ის ნაბიჯები ზედიზედ (`npm ci && npm audit --omit=dev && npm run lint && npm test && npm run build && git diff --exit-code -- dist`) გადის. GitHub-ზე რეალური გაშვება — push-ის შემდეგ, მფლობელი (Unverified).
- [x] **S13-6 — should-fix (finish-check, code-reviewer): `js.configs.recommended`-ის წესები გამორთულია** · owner: task-executor · files: `frontend/eslint.config.js`, `frontend/src/**/*.{js,jsx}` (მხოლოდ ახლად მონიშნული ხაზები, ქცევის შენარჩუნებით; ცნობილი: `src/lib/csv.js:19` კომენტარი) · depends: —
  - მიზეზი (გადამოწმდა `eslint --print-config`-ით): `{ ...js.configs.recommended, rules: {...} }` — იმავე object-ში `rules` recommended-ის `rules`-ს მთლიანად ანაცვლებს → `no-undef`, `no-empty`, `no-dupe-keys`, `no-unreachable`… არ მოქმედებს; globals-ის ბლოკები პრაქტიკულად უქმია. შედეგი: დაბეჭდილი ცვლადის სახელი lint/CI-ს მწვანედ გადის და production-ში `ReferenceError`-ს იძლევა. (voltbox-ს იგივე ბაგი აქვს — ამ რეპოს გარეთაა, მფლობელს ეცნობება.)
  - Fix: `rules`-ის პირველ ხაზად `...js.configs.recommended.rules`; `...js.configs.recommended` spread ამოიღე. header-ის კომენტარი სიმართლეს უნდა შეესაბამებოდეს.
  - ახალი error-ები: მხოლოდ ქცევის შემნარჩუნებელი გასწორება (ცნობილი — `csv.js:19` `no-irregular-whitespace`: კომენტარში ნამდვილი BOM სიმბოლო → ტექსტი `U+FEFF`; ხაზი 20-ის string-ს არ ეხები); სხვაგვარად — `eslint-disable-next-line <rule> -- <მიზეზი>, Backlog S13` + report.
  - done when: `eslint --print-config src/panel/ui.jsx`-ში `no-undef` და `no-dupe-keys` = error; კონტროლი: დროებით ფაილში/ხაზზე გამოუცხადებელი იდენტიფიკატორი → `npm run lint` ვარდება `no-undef`-ით (შემდეგ დაბრუნებულია); `npm run lint` exit 0 (0 error); `npm test` 29/29; `npm run build` → `git diff --stat -- frontend/dist` ცარიელი.

## Stage 12 — Done
- [x] **S12-1 — should-fix (Live-მდე): image ჩამოტვირთვას მთლიანი deadline + მხოლოდ საკუთარი Storage URL** (აუდიტი #4, B-12-ის ნაწილი) · `services/facebook.py` (`download_image`, `is_own_storage_image_url`), `services/bot.py` (`_fetch_product_images`)
  - slow-drip `image_url` thread-ს წუთობით იკავებდა → threadpool-ის ამოწურვა. Fix: 15 წმ-იანი `time.monotonic` deadline; ბოტი საცნობარო ფოტოს მხოლოდ `<SUPABASE_URL>/storage/v1/object/public/product-images/` ბილიკიდან იღებს (UI-ში ფოტო მხოლოდ ატვირთვით → გარე URL ლეგიტიმური გზა არ არის; პირდაპირი PostgREST `image_url` გარე URL-ს ბოტი უგულებელყოფს). B-12-ის ნარჩენი (DNS rebinding, 100.64/10) ახლა მხოლოდ კლიენტის FB/IG CDN URL-ებს ეხება → Backlog-ში რჩება.
  - Verify: ტესტები (fake clock-ით slow-drip წყდება; გარე URL არ იწერება; supabase_url ცარიელი → უარი).
- [x] **S12-2 — should-fix: `enforce_bot_limit` სამივე downgrade გზაზე + ტესტები** (აუდიტი #1 + #5) · `services/bot_limits.py`, `api/shops.py`, `api/admin.py`
  - ადმინის tier-ცვლა/approve ზედმეტ ბოტს არ თიშავდა; გამყიდველის downgrade ერთადერთ მომუშავე ბოტს თიშავდა, თუ უფრო ძველი მაღაზიის ბოტი გამორთული იყო. Fix: ერთი helper (რჩება ჩართულებიდან ყველაზე ძველი `limit`); შეცდომა → 500 (აღარ ილექება). knowledge upload/clear ტესტებს `.eq("id")` assert დაემატა.
  - Verify: 9 ახალი ტესტი სამივე გზაზე (mutation-ით დადასტურდა: helper-ის გარეშე admin ტესტები ვარდება).
- [x] **S12-3 — should-fix: `upgrade_requests` — authenticated-ს INSERT მოხსნილია (migration 0024)** (აუდიტი #2 + nit `_cancel_pending_requests`) · `supabase/migrations/0024_*.sql`, `api/shops.py`
  - ბიზნეს-წესი: გამოწერა per-account → pending **per-account**: ახალი მოთხოვნა მფლობელის ყველა მაღაზიის ძველ pending-ს აუქმებს; ჩაწერა service client-ით RLS-ownership-ის შემდეგ; rate limit 10/სთ/IP; `_cancel_pending_requests` შეცდომას აღარ ყლაპავს. 0024: revoke + policy drop + partial unique (მაქს. ერთი pending მაღაზიაზე, დუბლიკატებს cancelled-ზე გადაიყვანს). Decision Log-ში ჩაწერილია.
  - Verify: 5 ახალი ტესტი; SQL verification query მიგრაციაში (**გაშვება — მფლობელი**).
- [x] **S12-4 — `CLIENT_IP_TRUSTED_HOPS` production-ში სავალდებულო** · `config.py`, `core/ratelimit.py`, `.env.example`
  - default (1) ამოღებულია (`None`); production-ში ცარიელი/<1 → startup `RuntimeError`. ⚠️ Render-ზე უკვე `=3` (Stage 10) — deploy-მდე გადაამოწმე, თორემ სერვერი არ ადგება.
  - Verify: ტესტები (პროდაქშენში აკლია → სახელი სიაში; 0 → invalid; dev-ში არ მოითხოვება).
- [x] **S12-5 — docs nits ერთად** · `CLAUDE.md`, `PROJECT.md`, `README.md`, `.env.example`
  - CLAUDE.md: ტესტების რაოდენობა, მიგრაციის შემდეგი ნომერი; PROJECT.md: მიგრაციების დიაპაზონი, Cloudflare → Render, Accepted Risks #18, Open Questions; README: მიგრაციების რაოდენობა + 0024, handoff-ის ცხრილი (`bot_conversations`), `CLIENT_IP_TRUSTED_HOPS`, `ADMIN_USER_IDS`; `.env.example`: `ADMIN_USER_IDS`, `CLIENT_IP_TRUSTED_HOPS`, `CLIENT_IP_DEBUG`, `LOG_LEVEL`, `PAYMENT_*`.
  - Accepted Risks-ში ჩაემატა: kill-switch (#3), `SHOP_ORDERS_PER_HOUR`, Supabase client ყოველ მოთხოვნაზე.

## Stage 11 — Done
- [x] **S11-1 — should-fix: შეკვეთის სტატუსი და მარაგი ერთ ტრანზაქციაში** (აუდიტი #2) · `backend/app/api/orders.py` (`update_order_status`), მიგრაცია `0021`
  - ახლა: სტატუსი `auth.client`-ით ახლდება, მარაგი ცალკე RPC-ით (`_take_stock` წინ, `_apply_stock_delta(+1)` შემდეგ). `processing/done → cancelled`-ზე, თუ სტატუსი შეიცვალა და მარაგის დაბრუნება ჩავარდა → შეკვეთა გაუქმებულია, მარაგი არ დაბრუნდა, პასუხი 500 (კომპენსაცია მხოლოდ აღების მხარეს არსებობს).
  - Fix: ერთი Postgres ფუნქცია (`change_order_status(order_id, expected_old, new)`) — სტატუსის ოპტიმისტური ჩაკეტვა + მარაგის აღება/დაბრუნება ერთ ტრანზაქციაში; იძახება service client-ით მხოლოდ `auth.client`-ით ownership-ის შემოწმების შემდეგ; `REVOKE EXECUTE … FROM public, anon, authenticated`. Python-ის კომპენსაციის ლოგიკა ქრება.
  - Verify: offline ტესტები (RPC-ის შეცდომის კოდები → 409/400), SQL verification query; მიგრაციას მფლობელი უშვებს.
- [x] **S11-2 — should-fix: Facebook OAuth ავტომატურად `pages[0]`-ს იღებს** (აუდიტი #8) · `backend/app/api/facebook.py` (connect callback)
  - რამდენიმე Page-ზე წვდომის მიცემისას შემთხვევითი პირველი მიება მაღაზიას → ბოტი არასწორ გვერდზე პასუხობს.
  - ✅ გადაწყვეტილება (მფლობელი, 2026-10-09): ვარიანტი (ა) — >1 გვერდზე უარი, შეტყობინებით: „თავიდან მიაბით და Facebook-ის ფანჯარაში მონიშნეთ მხოლოდ ის გვერდი, რომელზეც ბოტი გინდათ". backend + ახალი reason frontend-ში (`fbConnect.js`) + `npm run build`.
  - Verify: ტესტი 0/1/2+ გვერდზე.
- [x] **S11-3 — should-fix: Gemini-ს გამოძახებას timeout არ აქვს** (აუდიტი #21) · `backend/app/services/bot.py` (`get_bot_reply`)
  - `genai.Client` `http_options` timeout-ის გარეშეა; ჩამოკიდებული გამოძახება webhook-ის threadpool worker-ს უსასრულოდ იკავებს (4 მცდელობაც დამატებით), კლიენტი პასუხს ვერ იღებს.
  - Fix: `HttpOptions(timeout=…)` (მაგ. 25 წმ) + მთლიანი ბიუჯეტი retry-ებით ≤ ~45 წმ; timeout → არსებული fallback პასუხი.
  - Verify: ტესტი — timeout-ის exception → fallback; retry-ების ბიუჯეტი.
- [x] **S11-4 — should-fix (finish-check): 0021-ის მარაგის წესებს DB-ის დონეზე ტესტი არ აქვს** · `supabase/checks/smoke_change_order_status.sql`
  - მარაგის ბიზნეს-წესები ახლა მხოლოდ plpgsql-შია (0021); offline ტესტები RPC-ს mock-ით ცვლიან და მხოლოდ Python-ის მხარეს ამოწმებენ. წესი (B-1: `new` მარაგს არ ეხება; F-06: cancelled→processing აკლებს; done/processing→cancelled აბრუნებს; წაშლილი პროდუქტი გამოტოვება; INSUFFICIENT_STOCK/STATUS_CHANGED და rollback) რეალურ Postgres-ზე არასდროს გამოცდილა.
  - Fix: checked-in smoke SQL, რომელსაც მფლობელი უშვებს SQL Editor-ში: ერთი `DO` ბლოკი, რომელიც დროებით ქმნის სატესტო მონაცემს (არსებული auth user + ახალი shop/products/orders), ასრულებს გადასვლებს `change_order_status`-ით, ამოწმებს მარაგს/სტატუსს და **ყოველთვის ბოლოს exception-ს აგდებს** (წარმატებაზე ტექსტი `SMOKE OK`, ჩავარდნაზე `SMOKE FAIL: …`) — exception ტრანზაქციას ბათილს ხდის, ამიტომ ბაზაში არაფერი რჩება.
  - Verify: SQL-ის ხელით გადაკითხვა სქემასთან (NOT NULL სვეტები, FK, CHECK-ები 0016/0018/ trigger-ები); რეალური გაშვება — მფლობელი.
- [x] **S11-5 — should-fix (გარე აუდიტი #1 + #2): `authenticated`-ს `orders` და `shops.knowledge*`-ზე UPDATE უფლება · migration `0022`** · `supabase/migrations/0022_*.sql`, `backend/app/api/shops.py`
  - ✅ გადაამოწმდა კოდში: (1) `orders`-ზე `auth.client` UPDATE არსად გამოიყენება (მხოლოდ select/delete; სტატუსს RPC `change_order_status` ცვლის service client-ით) და frontend პირდაპირ Supabase-ს არ იძახებს → `UPDATE(status)` (0018) ზედმეტია; PostgREST-ით პირდაპირი `status`-ის შეცვლა RPC-ს გვერდს უვლის და მარაგს ბერავს. (2) `shops.knowledge/knowledge_filename`: frontend პირდაპირ არ წერს, **მაგრამ backend წერს** — `upload_knowledge` და `clear_knowledge` (`shops.py` ~441, ~454) `auth.client`-ით, ე.ი. მხოლოდ 0015-ის revoke backend-ს გატეხავდა.
  - Fix: (ა) backend: ორივე endpoint ჩაწერას ამჟამად ინახავს service client-ით **მფლობელობის RLS-ით (`auth.client` select) შემოწმების შემდეგ** (`clear_knowledge`-ს ამ შემოწმებას დავუმატებთ); free პაკეტის gate ინარჩუნებს. (ბ) migration `0022`: `revoke update on public.orders from authenticated` + `shops`-ზე `revoke update … from authenticated; grant update (name, description, currency, bot_language) …` (knowledge სვეტები გარეშე; დანარჩენი სვეტები 0015-ის იგივეა). PRE-CHECK/ინფო query: free-პაკეტის მაღაზიები, რომლებსაც უკვე აქვთ `knowledge` (შესაძლოა PostgREST-ით ჩაწერილი).
  - ⚠️ **გაშვების რიგი: ჯერ backend deploy, მერე 0022** (პირიქით knowledge-ის ატვირთვა/წაშლა 4xx-ს დააბრუნებს მიგრაციის გაშვებიდან deploy-მდე). ძველი backend + 0022 = გატეხილი knowledge.
  - Verify: ტესტები (knowledge endpoint-ები ownership-ით 404-ს აბრუნებენ სხვის მაღაზიაზე და ჩაწერა service client-ით; free gate), SQL verification query (`has_table_privilege`/`has_column_privilege`).
- [x] **S11-6 — should-fix (გარე აუდიტი #3): production-ში აუცილებელი secrets fail-closed** · `backend/app/config.py`, `main.py`, `app/api/facebook.py`, `app/services/facebook.py`
  - ✅ გადაამოწმდა: ცარიელი `FB_APP_SECRET` → `verify_signature`, `parse_signed_request`, `sign_state` HMAC-ს **ცარიელ key-ზე** ითვლიან (გაყალბებადია: webhook-ის ხელმოწერა, data-deletion callback, OAuth state); `_deletion_secret()` ცარიელზე `"chatassist"` fallback-ს იყენებს (გამოცნობადი); production startup-ზე secrets არ მოწმდება (`FB_TOKEN_ENCRYPTION_KEY`-ის გარეშე შეცდომა მხოლოდ პირველ connect-ზე — ჩუმი არასრული გაშვება).
  - Fix: (ა) production startup-ზე აუცილებელი სია — `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_SECRET_KEY`, `GEMINI_API_KEY`, `FB_APP_SECRET`, `FB_VERIFY_TOKEN`, `FB_TOKEN_ENCRYPTION_KEY` (+ Fernet-ფორმატის ვალიდაცია): გარეშე `RuntimeError` სახელების სიით (ღირებულებების გარეშე) → სერვერი არ ადგება. dev/test-ზე არ მოქმედებს. (ბ) ფუნქციებში თავდაცვა: `verify_signature`/`parse_signed_request`/`sign_state` ცარიელ secret-ზე უარს ამბობენ (False/None/RuntimeError); `_deletion_secret()` ცარიელზე RuntimeError და არა `"chatassist"`. (გ) ახლა შესაძლებელია ტესტი „ცარიელი secret → 403" (T11-ის შენიშვნა).
  - ⚠️ **deploy-მდე** დარწმუნდი, რომ Render-ზე ყველა ზემოთ ჩამოთვლილი დაყენებულია (ახალი სახელებით Supabase-ისთვის), სხვაგვარად deploy ვერ ადგება (Render წინა ვერსიას დატოვებს). ADMIN_USER_IDS ცარიელი იყოს თუ არა — უკვე fail-closed და არ მოწმდება.
  - Verify: ტესტები production/development ორივე რეჟიმში; backlog A-9/B-6 დაიხურება (A-6 — S11-5).

- [x] **S11-7 — should-fix (მესამე გარე აუდიტი): NaN/Infinity ფასი, არამთელი მარაგი იმპორტში, CI/docs** · `models/product.py`, `models/order.py`, `services/import_products.py`, migration `0023`, `.github/workflows/ci.yml`, `README.md`, `backend/.env.example`
  - API: Infinity ფასი გადიოდა (NaN — არა); იმპორტი იღებდა `nan`/`inf`/`1e999` ფასს, `2.5` მარაგს ჩუმად აკეცავდა 2-მდე, `inf` მარაგი 500-ს (OverflowError) იძლეოდა. DB: `price >= 0` NaN-ს უშვებს → `0023` (`< 'Infinity'`, products + orders.total). Fix: `allow_inf_nan=False`, `math.isfinite`, მწკრივის ნომრით შეცდომა.
  - CI: frontend job (`npm ci` + build + `git diff --exit-code -- dist`), `pip-audit -r requirements.lock.txt`, `permissions: contents: read`. Render build → `requirements.lock.txt`. Docs: `ADMIN_USER_IDS`, ტესტების აღწერა.
  - ⚠️ მფლობელს: `0023` გაუშვი ხელით (PRE-CHECK ფაილის თავშია). Render Build Command უკვე `pip install -r requirements.lock.txt` იყო (Root Directory = backend) — ცვლილება არ დასჭირდა. CI-ის ახალი ნაბიჯები (pip-audit, frontend job) GitHub-ზე ჯერ არ გაშვებულა.

## Stage 10 — Done
- [x] **T1 — Minimal lint setup (backend)** · infra (verify.sh CHECKS: ruff + pytest დამატებულია, hook-ით შემოწმებული)
  - ruff ჯერ არ არის; ტესტები არის (114, offline, CI-ში).
  - `ruff` → `backend/requirements-dev.txt`; მინიმალური კონფიგი (`E`, `F` წესები) `backend/pyproject.toml`-ში ან `ruff.toml`-ში;
    არსებული დარღვევები გასწორდეს ან ცხადად გამოირიცხოს; CI-ში ნაბიჯი `ruff check app tests`.
  - `.claude/hooks/verify.sh` → CHECKS: ruff + pytest (მფლობელის თანხმობით).
  - Verify: `ruff check` სუფთაა, `pytest -q` გადის.
- [x] **T2 — B-1 (critical): ყალბი საჯარო შეკვეთებით მარაგის განულება** · `backend/app/api/orders.py:203-364`
  - ✅ გადაწყვეტილება (მფლობელი, 2026-10-08): ვარიანტი (გ) — მარაგი იკლებს **მხოლოდ `new → processing` გადასვლისას**;
    დამატებით **IP-ზე დღიური ლიმიტი** საჯარო შეკვეთებზე.
  - შედეგები, რაც ამ ცვლილებას თან მოჰყვება (გასათვალისწინებელი):
    - `create_order` აღარ იძახებს `decrement_stock`-ს; `new` შეკვეთის გაუქმებისას მარაგი **არ ბრუნდება** (არაფერი ჩამოვრიცხულა).
    - `new → processing`: ატომური დაკლება; თუ მარაგი არ ჰყოფნის → 409 + გასაგები შეტყობინება გამყიდველს.
    - `processing/done → cancelled` აბრუნებს მარაგს (როგორც ახლა); F-06 reopen-ის ლოგიკა ახალ მდგომარეობებს მოერგოს.
    - `public-menu` / ბოტი აჩვენებს რეალურ მარაგს, `new` შეკვეთები მარაგს აღარ ამცირებს → შეიძლება overselling `new`-ში (მისაღებია, გამყიდველი ადასტურებს).
    - IP-ლიმიტი in-memory-ია (deploy-ზე ნულდება) და **სანდოა მხოლოდ სწორი `CLIENT_IP_TRUSTED_HOPS`-ით (იხ. T17)**.
  - Verify: ტესტები — შეკვეთა მარაგს არ ცვლის; processing-ზე იკლებს; არასაკმარისი მარაგი → 409; cancel processing-იდან აბრუნებს;
    IP-ის დღიური ლიმიტი → 429.
- [x] **T3 — A-4 (hardening, დაბალი): `APP_ENV` default fail-open** · `backend/app/config.py:19`
  - მფლობელმა დაადასტურა: Render-ზე `APP_ENV=production` (`/status` → `env=production`), ე.ი. ლაივ-რისკი ახლა არ არსებობს.
    Fix მაინც ღირს (მომავალი გარემო/აღდგენა): default `production`; dev-ში `.env`-ით `APP_ENV=development`; tests/conftest ცხადად `development`.
  - Verify: ტესტი — env-ის გარეშე `is_production is True`; არსებული ტესტები გადის.
- [x] **T4 — B-2 (should-fix, high): xlsx-ის სვეტებით OOM** · `backend/app/services/import_products.py:62`
  - `iter_rows` `max_col`-ის გარეშე: 4.8KB ფაილი `dimension=A1:XFD…`-ით ≈ 660MB (გაზომილი ლოკალურად) → instance OOM.
  - Fix: `iter_rows(max_col=MAX_COLS)`; `load_workbook`-მდე zip-ის გაშლილი ზომის ჭერი.
  - Verify: ტესტი სინთეზური xlsx-ით (ფართო dimension) — სწრაფად ბრუნდება / ValueError.
- [x] **T5 — A-1 (should-fix): მაღაზიის პირდაპირი DELETE PostgREST-ით → storage კვოტის და კლიენტების მრიცხველის გვერდის ავლა** ·
  `supabase/migrations/0001_init.sql:104-107`, `backend/app/api/admin.py:381-383`
  - Fix: მიგრაცია `0017` — `revoke delete on public.shops from anon, authenticated`; `admin.delete_shop` შლის `product-images/{shop_id}/*`-საც.
  - Verify: ტესტი — admin delete იძახებს storage remove-ს; მიგრაციის verification query.
- [x] **T6 — A-2 (should-fix): `orders`-ზე column privileges / status CHECK არ არის** · `supabase/migrations/0002_orders.sql`
  - გამყიდველს PostgREST-ით შეუძლია `items`/`total` შეცვლა და მერე API-ით გაუქმება → მარაგის გაბერვა; აქტიური შეკვეთის წაშლა (F-07-ის გვერდის ავლა).
  - Fix: მიგრაცია — `revoke update, delete` + `grant update (status)`; `check (status in (...))`; delete policy მხოლოდ `done`/`cancelled`.
  - Verify: SQL verification query მიგრაციაში; API ტესტები გადის.
- [x] **T7 — B-3 (should-fix): webhook-ზე წუთობრივი ლიმიტი არ არის — ერთი კლიენტი ამოწურავს საერთო Gemini კვოტას / threadpool-ს** ·
  `backend/app/api/webhook.py:262-273`
  - Fix: in-memory ლიმიტი `(shop_id, psid)` (~6/წთ) და `shop_id` (~30/წთ); გადაჭარბება — ჩუმად გამოტოვება + log.
  - Verify: ტესტი — N+1-ე შეტყობინება `get_bot_reply`-ს არ იძახებს.
- [x] **T8 — A-3 (should-fix): `upgrade_requests` insert policy სვეტებს არ ზღუდავს** · `supabase/migrations/0005_upgrade_requests.sql:22-27`
  - Fix: მიგრაცია — WITH CHECK `status='pending' and resolved_at is null and requested_tier in (...)` + CHECK constraints.
  - Verify: SQL verification query.
- [x] **T9 — A-5 / B-9 (should-fix, low): `instagram_account_id` არ არის unique → IG DM შეიძლება სხვა tenant-ის მაღაზიას მიება** ·
  `supabase/migrations/0006_instagram.sql:11`, `backend/app/api/facebook.py:251-262`, `backend/app/api/webhook.py:209-213`
  - Fix: connect-ზე იგივე IG id სხვა მაღაზიიდან null-დება; მიგრაცია — partial unique index (`where instagram_account_id is not null`).
    ⚠️ მიგრაციამდე live DB-ში დუბლიკატები შესამოწმებელია (მფლობელი).
  - Verify: ტესტი connect-ზე; SQL verification query.
- [x] **T10 — B-4 (should-fix, low): საჯარო შეკვეთა იღებს `is_active=false` პროდუქტს** · `backend/app/api/orders.py:255-262`
  - Fix: `.eq("is_active", True)` `db_products` select-ში.
  - Verify: ტესტი — არააქტიური პროდუქტი → „ვერ მოიძებნა", მარაგი უცვლელი.
- [x] **T11 — B-5 (should-fix): webhook-ის ხელმოწერას ტესტი არ აქვს** · `backend/tests/`
  - Fix: ტესტები — სწორი ხელმოწერა → 200; არასწორი/არარსებული → 403. (ცარიელი secret → 403 ტესტი — მხოლოდ Backlog-ის A-9/B-6-ის გასწორების შემდეგ.)
  - Verify: `pytest -q`.
- [x] **T17 — should-fix: კლიენტის IP Render-ის სანდო header-იდან (CF-Connecting-IP გაყალბებადია)** · `backend/app/core/ratelimit.py`, `config.py`, `main.py`
  - მფლობელის გადაწყვეტილება (2026-10-08): Cloudflare არ გამოიყენება (chatassist.ge პირდაპირ Render-ზეა). `CF-Connecting-IP` ახლა კლიენტის მიერ ყალბდება → ყველა IP-ლიმიტი (T2, შეკვეთები) შემოსავლელია.
  - Render-ის დოკუმენტაცია ცალსახა არ არის: Render XFF-ს **არ ასუფთავებს, მხოლოდ ამატებს** (კლიენტის მიწოდებული მნიშვნელობა ინახება, Render ბოლოში ამატებს); Render-ის წარმომადგენელი 2021-ში წერს „first IP = real client", მაგრამ ეს მხოლოდ მაშინ სწორია, როცა კლიენტი XFF-ს არ აგზავნის.
    ⇒ სანდოა მხოლოდ XFF-ის **მარჯვენა მხარე** (Render-ის დამატებული ჩანაწერები), არა პირველი. ზუსტი hop-ის რაოდენობა (Render-ის edge + LB) დოკუმენტაციით ვერ დადასტურდა.
  - Fix: `CLIENT_IP_TRUSTED_HOPS` (int) — IP = XFF-ის მარჯვნიდან N-ური ჩანაწერი; კლიენტის `CF-Connecting-IP` სრულად იგნორირდება; დროებითი diagnostic (env-ით ჩასართავი), რომ მფლობელმა Render-ის ლოგში ნახოს რეალური XFF და N დააყენოს.
  - Verify: ტესტი — გაყალბებული `CF-Connecting-IP` და გაყალბებული XFF-ის მარცხენა ჩანაწერები IP-ს ვერ ცვლის; ლიმიტი სწორ bucket-ზე ითვლება.
- [x] **T18 — IG: მეორე მაღაზიის connect-ზე უარი (T9-ის გადაწყვეტილება)** · `backend/app/api/facebook.py`
  - მფლობელის გადაწყვეტილება: თუ IG ანგარიში უკვე სხვა მაღაზიასთანაა — connect უარს იღებს, მკაფიო შეტყობინებით („ანგარიში უკვე სხვა მაღაზიასთანაა, დაგვიკავშირდით"). T9-ის „სხვა მაღაზიიდან null-დება" ამოღდეს; webhook-ის ორაზროვნობის დაცვა და 0020 რჩება.
  - Verify: ტესტი — სხვა მაღაზიის IG id → უარი, არაფერი იცვლება; იგივე მაღაზიის ხელახალი connect გადის.
- [x] **T19 — should-fix: ტესტის ჩავარდნისას `Settings` repr secrets-ს ბეჭდავს** · `backend/tests/conftest.py`, `backend/app/config.py`
  - ტესტები ლოკალურ `.env`-ს კითხულობენ (conftest მხოლოდ `SUPABASE_URL`/`ANON_KEY`-ს ცარიელებს); ჩავარდნისას pytest ბეჭდავს `Settings(...)`-ს რეალური key-ებით (ერთხელ უკვე მოხდა hook-ის გამოტანაში).
  - Fix: conftest ყველა secret-ს (GEMINI_API_KEY, SUPABASE_SERVICE_ROLE_KEY, FB_APP_SECRET, FB_TOKEN_ENCRYPTION_KEY, FB_VERIFY_TOKEN, ...) ცარიელებს/ფიქტიურ მნიშვნელობას უსვამს app-ის import-მდე, და/ან secret ველები `SecretStr`/`repr=False`. Tests ლოკალურ `.env`-ზე არ უნდა იყვნენ დამოკიდებული.
  - Verify: ტესტი — `repr(get_settings())` არ შეიცავს secret-ს; `pytest -q` გადის `.env`-ის გარეშეც (ცარიელი env-ით).
  - ⚠️ მფლობელს: ტრანსკრიპტში უკვე გამოჩნდა Gemini key, FB_APP_SECRET, Supabase service-role და FB_TOKEN_ENCRYPTION_KEY — როტაცია საკუთარ შეფასებაზე.
- [x] **T20 — CRITICAL (finish-check): deploy-მდე შექმნილ `new` შეკვეთებზე მარაგი არასწორად დაითვლება** · `supabase/one-off/release_legacy_new_order_stock.sql`
  - ძველი კოდი მარაგს `create_order`-ისას აკლებდა; ახალი `new`-ს „მარაგი არ ჩამოწერილა"-დ თვლის → `new → processing` მარაგს მეორედ აკლებს (ან 409), `new → cancelled` აღარ აბრუნებს (მარაგი იკარგება). Render-ის deploy-ზე ძველი instance რამდენიმე წუთი კიდევ იღებს შეკვეთებს ძველი წესით.
  - Fix: ერთჯერადი SQL (მფლობელი უშვებს backend deploy-ის დასრულებისთანავე): preview → cutoff (ახალი instance-ის live დრო) → `apply_stock_delta(..., +1)` cutoff-მდე შექმნილ `new` შეკვეთებზე, ერთ ტრანზაქციაში, double-run-ისგან დაცვით. Deploy plan-ში ცალკე ნაბიჯი.
  - Verify: SQL-ის ხელით გადამოწმება RPC-სთან; რეალურ Postgres-ზე ვერ გაიშვება (მფლობელი).
- [x] **T21 — IP-ლიმიტი (ip, shop)-ზე, 20/დღე (მფლობელის გადაწყვეტილება 2026-10-08)** · `backend/app/api/orders.py`, `backend/app/core/ratelimit.py`
  - ახლა `create_order_day` 20/დღე მხოლოდ IP-ზეა და ყველა მაღაზიაზე საერთოა (CGNAT-ის რისკი). გადავიდეს key-ზე `(ip, shop_id)`; ლიმიტი 20/დღე რჩება. წუთობრივი `create_order` (10/წთ, IP) უცვლელია.
  - Verify: ტესტი — ერთი IP + shop A: 21-ე → 429; იგივე IP + shop B ჯერ გადის; სხვა IP + shop A გადის; PROJECT.md Decision Log-ის B-1 ჩანაწერი განახლდეს.
- [x] **T22 — should-fix (ლაივ-შემოწმებიდან): INFO ლოგები production-ში არ ჩანს; `peer` გაყალბებადია (uvicorn proxy headers)** · `backend/app/main.py`, `backend/app/core/ratelimit.py`
  - (ა) მიზეზი: `logging.getLogger("app")`-ზე არც handler, არც level არ არის მორგებული (`basicConfig` არსად არის); uvicorn მხოლოდ საკუთარ `uvicorn*` logger-ებს აყენებს → `app`-ის INFO ჩანაწერები იკარგება, WARNING-ები კი lastResort handler-ით ჩანს. ამიტომ `client-ip debug` (INFO) ლოგში არ გამოჩნდა — და ბოტის/webhook-ის სხვა `logger.info` ჩანაწერებიც production-ში უხილავია.
  - (ბ) uvicorn-ის proxy-headers (ნაგულისხმევად ჩართულია; access log-ში `1.2.3.4:0` ამას აჩვენებს) `request.client.host`-ს XFF-ით ანაცვლებს → `peer` კლიენტის კონტროლშია. `_client_ip` პირველ რიგში XFF-ის მარჯვენა ჩანაწერს იღებს (ეს გაყალბებას უძლებს), მაგრამ fallback (`entries < hops`) `peer`-ზეა → გაყალბებადი. სხვა გამოყენება: `admin.py:154` (მხოლოდ დიაგნოსტიკა).
  - Fix: (1) `LOG_LEVEL` (default INFO) — `app` logger-ი stdout-ზე; **წინასწარ გადაამოწმე ყველა `logger.info`/`debug` — PII (ტექსტი, PSID, ტელეფონი, token) არ იწერებოდეს**; (2) production-ში `_client_ip` fallback = ფიქსირებული საერთო bucket (`"unknown"`) და არა `peer`; dev-ში peer; ტესტი — გაყალბებული peer (XFF-ის გარეშე/ცოტა ჩანაწერით) ლიმიტს ვერ აცდენს; (3) მფლობელს ვთავაზობ (კოდი არა): Render start command-ში `--no-proxy-headers`, რომ `request.client` რეალური socket peer იყოს (access log-ში IP-ები ვეღარ გამოჩნდება).
  - Verify: ტესტები; ლოგის ფორმატი/ლოგში secrets არ ხვდება.
- [x] **T23 — Supabase-ის ახალ API key-ებზე გადასვლა (ძველი legacy service_role გაჟონა)** · `backend/app/config.py`, `core/supabase_client.py`, `core/security.py`, `frontend/src/**`, `frontend/public/config.js`
  - მფლობელის გადაწყვეტილება (2026-10-09): backend → `sb_secret_...` (service_role-ის ნაცვლად), frontend → `sb_publishable_...` (anon-ის ნაცვლად); legacy key-ები ბოლოს ითიშება. key-ების მნიშვნელობებს მფლობელი სვამს, აგენტი არ ხედავს.
  - გადაწყვეტილებები: ახალი სახელები `SUPABASE_PUBLISHABLE_KEY` / `SUPABASE_SECRET_KEY`; ძველი `SUPABASE_ANON_KEY` / `SUPABASE_SERVICE_ROLE_KEY` მუშაობს fallback-ად (pydantic AliasChoices; ახალი სახელი უპირატესია) — უსაფრთხო rollout და rollback env-ის მეშვეობით. supabase-py 2.32.0 key-ის ფორმატს არ ამოწმებს (მხოლოდ ცარიელს). frontend: `supabase-js ^2.112.3`; `config.js`-ში ველი `SUPABASE_PUBLISHABLE_KEY` (მნიშვნელობა ჯერ უცვლელი, მფლობელი ცვლის).
  - Verify: ტესტები (ახალი და ძველი env სახელი, ახალი უპირატესია, secrets repr-ში არ ჩანს); `npm run build` + `dist/` commit-ში; Deploy plan — ზუსტი ნაბიჯები.
  - ⚠️ ვერ გადამოწმდება offline: sb_secret key-ის მუშაობა supabase-py-ს `Authorization: Bearer <key>` header-ით PostgREST/Storage/Auth-ზე — მხოლოდ ლაივზე (შემოწმების სია Deploy plan-შია).

### Stage 10 — აუდიტის გადამოწმების ისტორია (Stage 11-ის წყარო)
### აუდიტის გადამოწმების შედეგი (27 პუნქტი)
- **(ა) უკვე გასწორებულია:** #7 `/test-chat` fail-open → T3 (`APP_ENV` default `production`); #10 XFF-ის ნდობა → T17 + T22 (მარჯვენა hop, `CLIENT_IP_TRUSTED_HOPS=3`, peer აღარ გამოიყენება); #26 `admin_email` → F-08 (კონფიგში აღარ არსებობს; `ADMIN_USER_IDS`, ცარიელი = fail-closed).
- **(ბ) რეალურია:** #2, #8, #21 → S11-1..3 (should-fix). nit-ები → Backlog: #15, #17, #24, #27, #1-ის ნარჩენი. #23 უკვე Backlog-შია.
- **(გ) არ შეესაბამება / ზედმეტია:** #1, #3, #4, #5, #6, #9, #11, #12, #13, #14, #16, #18, #19, #20, #22, #25 → PROJECT.md `Accepted Risks` (მიზეზებით).
