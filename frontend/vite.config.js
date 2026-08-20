import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";

/** გვერდის აბსოლუტური გზა (root-ისგან დამოუკიდებლად სწორი) */
const page = (p) => fileURLToPath(new URL(p, import.meta.url));

// ⚠️ MPA (multi-page) — არა SPA routing.
// build-ის გამოსავალი უნდა იყოს ზუსტად იგივე 8 .html ფაილი, იგივე სახელებით,
// რადგან ეს URL-ები რეგისტრირებულია Meta-ს დაფაზე, Supabase-ზე და უკვე
// გაგზავნილია რეალურ მყიდველებთან (იხ. REACT_MIGRATION.md, ნაწილი 1).
export default defineConfig({
  base: "/panel/",
  plugins: [react()],
  server: { port: 5173 },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    rollupOptions: {
      input: {
        landing: page("./landing.html"),
        index: page("./index.html"),
        admin: page("./admin.html"),
        order: page("./order.html"),
        reset: page("./reset.html"),
        privacy: page("./privacy.html"),
        terms: page("./terms.html"),
        "delete-data": page("./delete-data.html"),
      },
    },
  },
});
