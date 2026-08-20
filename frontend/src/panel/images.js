/* პროდუქტის ფოტო — შემცირება + ატვირთვა. გადმოტანილია app.js-იდან ხაზ-ხაზ.
 *
 * ⚠️ resizeImage-ის ყველა catch განზრახ აბრუნებს ორიგინალ ფაილს:
 * თუ canvas-მა ვერ დაამუშავა, ატვირთვა მაინც გრძელდება (submit არ იჭედება).
 */
import { getToken } from "./supabase.js";

const cfg = window.APP_CONFIG;

/** max 1280px, JPEG — რომ დიდი ფაილიც აიტვირთოს და storage/AI იაფი დარჩეს */
export function resizeImage(file, maxDim, quality) {
  return new Promise((resolve) => {
    try {
      const img = new Image();
      const url = URL.createObjectURL(file);
      img.onload = () => {
        try {
          URL.revokeObjectURL(url);
          let w = img.width;
          let h = img.height;
          if (w > maxDim || h > maxDim) {
            if (w >= h) {
              h = Math.round((h * maxDim) / w);
              w = maxDim;
            } else {
              w = Math.round((w * maxDim) / h);
              h = maxDim;
            }
          }
          const canvas = document.createElement("canvas");
          canvas.width = w;
          canvas.height = h;
          const ctx = canvas.getContext("2d");
          if (!ctx) {
            resolve(file);
            return;
          }
          ctx.drawImage(img, 0, 0, w, h);
          canvas.toBlob((blob) => resolve(blob || file), "image/jpeg", quality);
        } catch {
          resolve(file); // ვერ დამუშავდა → ორიგინალი
        }
      };
      img.onerror = () => {
        URL.revokeObjectURL(url);
        resolve(file);
      };
      img.src = url;
    } catch {
      resolve(file);
    }
  });
}

/** ფოტოს ატვირთვა Storage-ში → აბრუნებს საჯარო URL-ს */
export async function uploadProductImage(shopId, file) {
  const uploadBlob = await resizeImage(file, 1280, 0.85);
  const token = await getToken();
  const fd = new FormData();
  fd.append("shop_id", shopId);
  fd.append("file", uploadBlob, "photo.jpg");

  const r = await fetch(cfg.API_BASE + "/products/upload-image", {
    method: "POST",
    headers: { Authorization: "Bearer " + token, "ngrok-skip-browser-warning": "1" },
    body: fd,
  });
  if (!r.ok) {
    const t = await r.json().catch(() => ({}));
    throw new Error(t.detail || "ფოტოს ატვირთვა ვერ მოხერხდა");
  }
  return (await r.json()).url;
}
