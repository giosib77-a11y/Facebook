# Project: ChatAssist (Facebook Messenger AI bot, multi-tenant SaaS)

`PROJECT.md` — მოთხოვნები და გადაწყვეტილებები. `PROGRESS.md` — მიმდინარე სტატუსი.

## Stack
- Backend: FastAPI (Python 3.14), `backend/app` — venv `backend/.venv`
- DB / Auth / Storage: Supabase (Postgres + RLS), მიგრაციები `supabase/migrations/`
- Frontend: React 19 + Vite MPA, `frontend/` — build-ის შედეგი `frontend/dist/` **git-შია**
- LLM: Google Gemini (`google-genai`)
- Hosting: Render (auto-deploy `main`-ზე push-ისას) + Cloudflare

## Commands
ყველა ბრძანება repo root-იდან (Git Bash). PowerShell-ში იგივე: `start-backend.ps1`, `start-frontend.ps1`.
- dev backend: `cd backend && PYTHONUTF8=1 .venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload`
  (⚠️ ლოკალური `.env` production Supabase-ს უკავშირდება — აგენტმა backend არ გაუშვას მფლობელის თანხმობის გარეშე)
- dev frontend: `cd frontend && npm run dev` → http://localhost:5173/panel/
- lint (backend): `cd backend && .venv/Scripts/python.exe -m ruff check app tests` (E,F; E501 ignored; CI-ში). Frontend-ზე eslint არ არის.
- typecheck: **არ არის** (Python type hints უმოწმებელია; frontend JS-ია)
- compile check (CI-ში): `cd backend && .venv/Scripts/python.exe -m compileall -q app`
- test: `cd backend && .venv/Scripts/python.exe -m pytest -q`
  (114 ტესტი, offline — fake Supabase + mock Graph/Gemini; frontend ტესტები არ არის)
- build frontend: `cd frontend && npm run build` → `frontend/dist/` (commit-ში უნდა წავიდეს ცვლილებასთან ერთად)
- migrations: **ხელით**, მფლობელი უშვებს Supabase SQL Editor-ში თანმიმდევრობით. აგენტი remote-ზე არაფერს უშვებს.
- CI: `.github/workflows/ci.yml` — `pip check`, `compileall`, `pytest` (push/PR `main`-ზე)

## Conventions
- **აკრძალულია** (მფლობელის თანხმობის გარეშე): `git push`, `main`-ში merge, deploy, remote Supabase-ზე
  migration/query, Meta/Facebook Graph API-ს გამოძახება, Gemini-ს გამოძახება რეალური key-ით, `.env`-ის წაკითხვა/შეცვლა.
- ტესტები offline: ახალი ტესტი იყენებს `tests/conftest.py`-ის `client` / `user_db` / `service_db` fixture-ებს;
  Graph — `httpx.MockTransport` ან monkeypatch; Gemini — monkeypatch `get_bot_reply`. გარე სერვისი სჭირდება → ჯერ კითხვა.
- Tenant isolation: seller-ის endpoint-ები DB-ს `auth.client`-ით (მომხმარებლის JWT, RLS) მიმართავენ.
  `get_service_client()` მხოლოდ იქ, სადაც სესია არ არის (webhook, საჯარო შეკვეთა, storage, admin) —
  და მაშინ ownership ჯერ `auth.client`-ით მოწმდება ან ფილტრი კოდშია ცხადად.
- ახალი SECURITY DEFINER ფუნქცია → იმავე მიგრაციაში `REVOKE EXECUTE ... FROM public, anon, authenticated`.
- ახალი მიგრაცია — შემდეგი ნომრით (`0017_...sql`), idempotent სადაც შესაძლებელია; README §7-ის სიაც განახლდეს.
- Frontend-ის ცვლილება → `npm run build` და `dist/` იმავე commit-ში. 8 `.html` სახელი არ იცვლება (URL-კონტრაქტი).
- commit-ის სტილი: `fix(scope): ... (ID)` — აუდიტის მიგნების ID ფრჩხილებში.
- კოდის comments ბევრგან ქართულადაა — შეინარჩუნე ფაილის არსებული სტილი.
