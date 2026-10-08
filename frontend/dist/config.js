// ფრონტენდის კონფიგი — ეს მნიშვნელობები PUBLIC-ია (publishable key განკუთვნილია
// ბრაუზერისთვის; უსაფრთხოებას RLS უზრუნველყოფს). git-ში ჩადება უსაფრთხოა.
// secret key (sb_secret_... / service_role) აქ არასდროს ჩასვა!
window.APP_CONFIG = {
  SUPABASE_URL: "https://xtvuqanwqocxgwetpzze.supabase.co",
  SUPABASE_PUBLISHABLE_KEY:
    "sb_publishable_SCqdd9pDsLkG371fqzr8kQ_DtvOyLnv",
  // FastAPI backend-ის მისამართი.
  // თუ პანელი backend-იდან იხსნება (localhost:8000/panel ან ngrok), API იმავე origin-ზეა.
  // თუ ცალკე static სერვერიდან (localhost:5500), API ლოკალურ 8000-ზეა.
  // dev: static-სერვერი (5500) ან Vite dev (5173) → backend ცალკე 8000-ზე.
  // prod: პანელი backend-იდანვე იდება → იგივე origin. ⚠️ prod-ის ქცევა არ შეცვალო.
  API_BASE: ["5500", "5173"].includes(location.port)
    ? "http://localhost:8000"
    : location.origin,
};
