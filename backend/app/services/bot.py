"""საცნობარო ფოტოები გრაფისთვის (`services/graph.py`).

პასუხის აგება — `graph.run_turn`; prompt — services/prompt.py, LLM-ის გამოძახება, retry და
usage — services/llm.py. აქ რჩება მხოლოდ რელევანტური პროდუქტების ფოტოების ჩამოტვირთვა
(`_fetch_product_images`) და მათი წარწერა (`product_ref_label`).
"""
from app.config import get_settings  # noqa: F401  (tests/test_golden_conversations.py still patches bot.get_settings)

# ფოტოიანი შეტყობინების მეხსიერების ჭერი (512 MB instance-ზე რამდენიმე
# პარალელური ფოტო-შეტყობინება სერვისს არ უნდა აგდებდეს).
INLINE_IMAGE_BUDGET = 15 * 1024 * 1024  # კლიენტის + საცნობარო ფოტოები ერთ LLM მოთხოვნაში
PRODUCT_REF_MAX_BYTES = 3 * 1024 * 1024  # თითო საცნობარო ფოტოზე
PRODUCT_REF_WORKERS = 4
MAX_REF_IMAGES = 12  # საცნობარო ფოტოების ჭერი ერთ LLM მოთხოვნაში


def product_ref_label(p) -> str:
    """საცნობარო ფოტოს წარწერა LLM-ისთვის: `• {name} — {price}` (+ ` (SKU: …)`)."""
    label = f"• {p.get('name', '?')} — {p.get('price', 0)}"
    if p.get("sku"):
        label += f" (SKU: {p['sku']})"
    return label


def _fetch_product_images(products, customer_images=None, max_images: int = MAX_REF_IMAGES):
    """რელევანტური პროდუქტების ფოტოებს ჩამოტვირთავს ვიზუალური შედარებისთვის.

    აბრუნებს [(label, (bytes, mime)), ...] — მხოლოდ იმ პროდუქტების, რომლებსაც
    ფოტო აქვთ (image_url). max_images — ჭერი (ხარჯი/სისწრაფე; ბევრი სურათი
    LLM-ს ძვირი/ნელი უჯდება). ჩამოტვირთვა პარალელურია და მოკლე timeout-ით,
    რომ ბოტის პასუხი არ შეყოვნდეს (webhook სინქრონულია).

    მეხსიერება: კლიენტის ფოტოები (customer_images) ყოველთვის იგზავნება და
    INLINE_IMAGE_BUDGET-იდან ჯერ ისინი აკლდება; საცნობარო ფოტოები მხოლოდ
    დარჩენილს ავსებს (თითო ≤ PRODUCT_REF_MAX_BYTES).
    """
    from concurrent.futures import ThreadPoolExecutor

    from app.services.facebook import download_image, is_own_storage_image_url

    remaining = INLINE_IMAGE_BUDGET - sum(len(data) for data, _ in customer_images or [])
    if remaining <= 0:
        return []

    # კანდიდატები — მხოლოდ ფოტოიანი, max_images-მდე
    candidates = []
    for p in products or []:
        # მხოლოდ საკუთარი Storage-ის ფოტო (B-12): გარე URL-ზე სერვერი არ გადის
        if is_own_storage_image_url((p.get("image_url") or "").strip()):
            candidates.append(p)
        if len(candidates) >= max_images:
            break
    if not candidates:
        return []

    def _one(p):
        try:
            return p, download_image(p["image_url"], max_bytes=PRODUCT_REF_MAX_BYTES, timeout=8)
        except Exception:
            return p, None

    refs = []
    with ThreadPoolExecutor(max_workers=min(PRODUCT_REF_WORKERS, len(candidates))) as ex:
        for p, got in ex.map(_one, candidates):
            if not got:
                continue
            # ბიუჯეტს გადააჭარბებს — ვტოვებთ, შემდეგი (უფრო პატარა) შეიძლება ჩაეტიოს
            if len(got[0]) > remaining:
                continue
            remaining -= len(got[0])
            refs.append((product_ref_label(p), got))
    return refs
