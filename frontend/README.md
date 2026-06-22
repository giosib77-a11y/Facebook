# Frontend — გამყიდველის პანელი (ნაბიჯი 3)

mobile-friendly static SPA (build-ის გარეშე). Auth — Supabase; პროდუქტების CRUD —
FastAPI backend-ის (ნაბიჯი 2) endpoint-ებით.

## ფაილები
- `index.html` — მარკაპი (auth + dashboard)
- `styles.css` — mobile-first სტილი
- `app.js` — ლოგიკა (Supabase Auth + fetch FastAPI-ზე)
- `config.js` — public კონფიგი (SUPABASE_URL, anon key, API_BASE). anon key public-ია.
- `config.example.js` — template

## გაშვება

backend უნდა მუშაობდეს (`uvicorn app.main:app --reload` → http://localhost:8000).
შემდეგ frontend მოემსახურე static სერვერით (file:// არ გამოდგება Auth-ისთვის):

```powershell
cd d:\yvelaperi\saitebi\facebook\frontend
python -m http.server 5500
```
გახსენი http://localhost:5500

## ფუნქციები
- რეგისტრაცია / შესვლა / გასვლა (Supabase Auth)
- მაღაზიის შექმნა და არჩევა (პროდუქტს მაღაზია სჭირდება)
- პროდუქტი: დამატება, სია, რედაქტირება, წაშლა
- RLS-ის გამო თითო გამყიდველი მხოლოდ თავის მონაცემს ხედავს

## შენიშვნა CORS-ზე
backend-ში CORS ღიაა (`*`), ამიტომ localhost-ის ნებისმიერი პორტი მუშაობს.
production-ში შეიზღუდება frontend-ის რეალური დომენით.
