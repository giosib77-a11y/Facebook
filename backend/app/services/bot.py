"""ბოტის ლოგიკა — LLM-ით (Claude / OpenAI) პასუხები მაღაზიის მარაგზე დაყრდნობით.

მთავარი ფუნქცია: get_bot_reply(shop, products, message, history, images).
prompt-ის აგება — services/prompt.py (სუფთა, offline), LLM-ის გამოძახება, retry და
usage — services/llm.py. აქ რჩება მხოლოდ მათი შეკვრა, საცნობარო ფოტოების ჩამოტვირთვა
და პასუხის დამუშავება.
"""
from app.config import get_settings
from app.services import llm, prompt

# ოპერატორზე გადართვის ნიშანი — ბოტი პასუხის ბოლოს ამატებს, სისტემა წაშლის
# კლიენტამდე გაგზავნამდე და საუბარს „ყურადღება სჭირდება"-დ ნიშნავს.
HANDOFF_TOKEN = "[[HANDOFF]]"

# ფოტოიანი შეტყობინების მეხსიერების ჭერი (512 MB instance-ზე რამდენიმე
# პარალელური ფოტო-შეტყობინება სერვისს არ უნდა აგდებდეს).
INLINE_IMAGE_BUDGET = 15 * 1024 * 1024  # კლიენტის + საცნობარო ფოტოები ერთ LLM მოთხოვნაში
PRODUCT_REF_MAX_BYTES = 3 * 1024 * 1024  # თითო საცნობარო ფოტოზე
PRODUCT_REF_WORKERS = 4


def parse_reply(raw: str) -> tuple[str, bool]:
    """ბოტის raw პასუხიდან [[HANDOFF]] ნიშანს აცლის.

    აბრუნებს: (გასუფთავებული_ტექსტი, handoff_საჭიროა?)
    """
    text = raw or ""
    handoff = HANDOFF_TOKEN in text
    clean = text.replace(HANDOFF_TOKEN, "").strip()
    return clean, handoff


def _fetch_product_images(products, customer_images=None, max_images: int = 12):
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
            label = f"• {p.get('name', '?')} — {p.get('price', 0)}"
            if p.get("sku"):
                label += f" (SKU: {p['sku']})"
            refs.append((label, got))
    return refs


def get_bot_reply(shop, products, message: str, history=None, images=None) -> str:
    """აბრუნებს ბოტის პასუხს LLM-ით.

    shop:     dict (id, name, currency, description, ...)
    products: list[dict] (მხოლოდ აქტიური პროდუქტები უნდა გადმოეცეს)
    message:  კლიენტის შეტყობინება
    history:  წინა საუბარი (არასავალდებულო)
    images:   სია (bytes, mime_type) — კლიენტის ფოტოები (multimodal, არასავალდებულო)

    LLM-ის შეცდომა (timeout, 5xx, ...) გადადის გამომძახებელს — webhook-ის fallback პასუხი
    იქ ამუშავდება.
    """
    settings = get_settings()
    if not settings.llm_ready:
        raise RuntimeError(f"{settings.llm_key_env_name} არ არის კონფიგურირებული")

    # ვიზუალური ამოცნობა — თუ კლიენტმა ფოტო გამოგზავნა, რელევანტური პროდუქტების
    # ფოტოებსაც ვურთავთ, რომ LLM-მა ვიზუალურად შეადაროს და კონკრეტული ამოიცნოს.
    # კანდიდატები = ზუსტად ის ქვესიმრავლე, რასაც build_prompt ირჩევს, ამიტომ იგივე
    # დალაგება (prompt._sort_key) — DB-ის რიგითობა გარანტირებული არ არის.
    product_refs = None
    if images:
        ordered = sorted(products or [], key=prompt._sort_key)
        relevant = prompt.select_relevant_products(ordered, message, history)
        product_refs = _fetch_product_images(relevant, images)

    p = prompt.build_prompt(shop, products, message, history, images, product_refs)
    result = llm.generate(p, shop["id"])
    llm.record_usage(shop["id"], result)
    return result.text.strip()
