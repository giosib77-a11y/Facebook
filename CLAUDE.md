# Project: ChatAssist (Facebook Messenger AI bot, multi-tenant SaaS)

`PROJECT.md` — მოთხოვნები და გადაწყვეტილებები. `PROGRESS.md` — მიმდინარე სტატუსი.

## Stack
- Backend: FastAPI (Python 3.14), `backend/app` — venv `backend/.venv`
- DB / Auth / Storage: Supabase (Postgres + RLS), მიგრაციები `supabase/migrations/`
- Frontend: React 19 + Vite MPA, `frontend/` — build-ის შედეგი `frontend/dist/` **git-შია**
- LLM: Anthropic Claude (`anthropic`, default) / OpenAI (`openai`) — `LLM_PROVIDER`
- ბოტი: `services/graph.py` (LangGraph) + `tools.py` / `replies.py` / `memory.py`; LLM მხოლოდ `llm.py`-ით (LangChain chat model-ები — არა)
- Hosting: Render (auto-deploy `main`-ზე push-ისას) + Cloudflare

## Commands
ყველა ბრძანება repo root-იდან (Git Bash). PowerShell-ში იგივე: `start-backend.ps1`, `start-frontend.ps1`.
- dev backend: `cd backend && PYTHONUTF8=1 .venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload`
  (⚠️ ლოკალური `.env` production Supabase-ს უკავშირდება — აგენტმა backend არ გაუშვას მფლობელის თანხმობის გარეშე)
- dev frontend: `cd frontend && npm run dev` → http://localhost:5173/panel/
- lint: `cd backend && .venv/Scripts/python.exe -m ruff check app tests`
  (E,F; E501 ignored; CI-ში).
- lint frontend: `cd frontend && npm run lint`
  (ESLint 9 flat config, react + react-hooks 5.x + react-refresh; CI-ში; warning-ები exit-ს არ აფუჭებს)
- typecheck: `cd backend && .venv/Scripts/python.exe -m compileall -q app`
  (ნამდვილი type checker (mypy/pyright) არ არის — ეს მხოლოდ syntax/compile check-ია, CI-ში იგივე; frontend JS-ია)
- test: `cd backend && .venv/Scripts/python.exe -m pytest -q`
  (ერთჯერადი გაშვება, watch-ის გარეშე; 1440 ტესტი, offline — fake Supabase + mock Graph / LLM client-ები)
- test frontend: `cd frontend && npm test`
  (Vitest `vitest run`, ერთჯერადი; jsdom + Testing Library, offline; ტესტები `src/**/*.test.{js,jsx}` ფაილის გვერდით)
- build frontend: `cd frontend && npm run build` → `frontend/dist/` (commit-ში უნდა წავიდეს ცვლილებასთან ერთად)
- migrations: **ხელით**, მფლობელი უშვებს Supabase SQL Editor-ში თანმიმდევრობით. აგენტი remote-ზე არაფერს უშვებს.
- CI: `.github/workflows/ci.yml` — `pip check`, `pip-audit`, `compileall`, `ruff`, `pytest` + frontend job (`npm ci`, `npm audit --omit=dev`, lint, test, build, `git diff --exit-code -- dist`) (push/PR `main`-ზე)

## Conventions
- **აკრძალულია** (მფლობელის თანხმობის გარეშე): `git push`, `main`-ში merge, deploy, remote Supabase-ზე
  migration/query, Meta/Facebook Graph API-ს გამოძახება, Anthropic/OpenAI API-ს გამოძახება რეალური key-ით, `.env`-ის წაკითხვა/შეცვლა.
- **ბრენჩი:** სამუშაო ბრენჩი მხოლოდ `agent-system`-ია. **ყოველ commit-მდე** გაუშვი `git branch --show-current`; თუ პასუხი `agent-system` არ არის (მაგ. `main` — მფლობელმა merge/push-ის შემდეგ ბრენჩი შეცვალა) — **გაჩერდი და მკითხე**, არ დააკომიტო. სესიის დასაწყისშიც შეამოწმე.
- ტესტები offline: ახალი ტესტი იყენებს `tests/conftest.py`-ის `client` / `user_db` / `service_db` fixture-ებს;
  Graph — `httpx.MockTransport` ან monkeypatch; LLM — fake client (`llm._anthropic_client`/`_openai_client`; conftest რეალურს ბლოკავს) ან monkeypatch `run_turn`. გარე სერვისი სჭირდება → ჯერ კითხვა.
- Tenant isolation: seller-ის endpoint-ები DB-ს `auth.client`-ით (მომხმარებლის JWT, RLS) მიმართავენ.
  `get_service_client()` მხოლოდ იქ, სადაც სესია არ არის (webhook, საჯარო შეკვეთა, storage, admin) —
  და მაშინ ownership ჯერ `auth.client`-ით მოწმდება ან ფილტრი კოდშია ცხადად.
- ახალი SECURITY DEFINER ფუნქცია → იმავე მიგრაციაში `REVOKE EXECUTE ... FROM public, anon, authenticated`.
- ახალი მიგრაცია — შემდეგი თავისუფალი ნომრით (ახლა `0027_...sql`), idempotent სადაც შესაძლებელია; README §7-ის სიაც განახლდეს.
- Frontend-ის ცვლილება → `npm run build` და `dist/` იმავე commit-ში. 8 `.html` სახელი არ იცვლება (URL-კონტრაქტი).
- `backend/scripts/compare_providers.py` (Stage 15) — აგენტი **არასდროს** უშვებს (არც `--dry-run`): რეალური API + ხარჯი; მხოლოდ მფლობელი (README §9); ტესტები — fake client-ებით.
- commit-ის სტილი: `fix(scope): ... (ID)` — აუდიტის მიგნების ID ფრჩხილებში.
- კოდის comments ბევრგან ქართულადაა — შეინარჩუნე ფაილის არსებული სტილი.
