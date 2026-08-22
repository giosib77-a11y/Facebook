// ფრონტენდის კონფიგი — ეს მნიშვნელობები PUBLIC-ია (anon key განკუთვნილია
// ბრაუზერისთვის; უსაფრთხოებას RLS უზრუნველყოფს). git-ში ჩადება უსაფრთხოა.
// service_role key აქ არასდროს ჩასვა!
window.APP_CONFIG = {
  SUPABASE_URL: "https://xtvuqanwqocxgwetpzze.supabase.co",
  SUPABASE_ANON_KEY:
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inh0dnVxYW53cW9jeGd3ZXRwenplIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODIwOTU3NTUsImV4cCI6MjA5NzY3MTc1NX0.9QxS7SLWnEp7XH3wAou7FCFfAfe7GtieX6wjln39Vp8",
  // FastAPI backend-ის მისამართი.
  // თუ პანელი backend-იდან იხსნება (localhost:8000/panel ან ngrok), API იმავე origin-ზეა.
  // თუ ცალკე static სერვერიდან (localhost:5500), API ლოკალურ 8000-ზეა.
  // dev: static-სერვერი (5500) ან Vite dev (5173) → backend ცალკე 8000-ზე.
  // prod: პანელი backend-იდანვე იდება → იგივე origin. ⚠️ prod-ის ქცევა არ შეცვალო.
  API_BASE: ["5500", "5173"].includes(location.port)
    ? "http://localhost:8000"
    : location.origin,
};
