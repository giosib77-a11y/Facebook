"""ბოტის ლოგიკა — Gemini-ით ქართული პასუხები მაღაზიის მარაგზე დაყრდნობით.

მთავარი ფუნქცია: get_bot_reply(shop, products, message, history).
system prompt გამოტანილია ცალკე ფუნქციად (build_system_prompt), რომ ადვილად
ჩაანაცვლო შენი საბოლოო ვერსიით და offline-ად დატესტო.
"""
import re
import time

from app.config import get_settings

# დროებითი (გადასატანი) შეცდომების ნიშნები — ასეთებზე ხელახლა ვცდით
_TRANSIENT = ("503", "UNAVAILABLE", "500", "429", "RESOURCE_EXHAUSTED", "high demand", "overloaded")

# ოპერატორზე გადართვის ნიშანი — ბოტი პასუხის ბოლოს ამატებს, სისტემა წაშლის
# კლიენტამდე გაგზავნამდე და საუბარს „ყურადღება სჭირდება"-დ ნიშნავს.
HANDOFF_TOKEN = "[[HANDOFF]]"


def parse_reply(raw: str) -> tuple[str, bool]:
    """ბოტის raw პასუხიდან [[HANDOFF]] ნიშანს აცლის.

    აბრუნებს: (გასუფთავებული_ტექსტი, handoff_საჭიროა?)
    """
    text = raw or ""
    handoff = HANDOFF_TOKEN in text
    clean = text.replace(HANDOFF_TOKEN, "").strip()
    return clean, handoff

# ---------------------------------------------------------------------------
# System prompt — ქართული. ჩაანაცვლე საჭიროებისამებრ.
# ---------------------------------------------------------------------------
# ბოტის ენა — მაღაზიის bot_language პარამეტრის მიხედვით
_LANG_RULES = {
    "auto": "პასუხობ იმ ენაზე, რომელზეც კლიენტი წერს (ქართული, English ან русский); თუ ვერ ხვდები — ქართულად. ქართულად წერისას გამოიყენე ბუნებრივი, სასაუბრო ქართული (არა ინგლისურიდან სიტყვასიტყვით თარგმნილი).",
    "ka": "პასუხობ ყოველთვის მხოლოდ ბუნებრივი, სასაუბრო ქართულით.",
    "en": "Always reply in English only.",
    "ru": "Отвечай всегда только на русском языке.",
}

SYSTEM_PROMPT_TEMPLATE = """შენ ხარ "{shop_name}"-ის გამოცდილი გამყიდველ-კონსულტანტი Facebook Messenger-სა და Instagram Direct-ში. მიზანი — დაეხმარო კლიენტს სწრაფად და თბილად, და გაყიდვა ბუნებრივად დაასრულო.

ქცევის წესები:
1. {language_rule} წერ მოკლედ და ბუნებრივად — როგორც ცოცხალი, თბილი გამყიდველი, არა რობოტი. emoji ზომიერად (1-2 შეტყობინებაზე).
   ⚠️ ქართულად წერისას გამოიყენე ბუნებრივი, სასაუბრო ქართული — არა ინგლისურიდან სიტყვასიტყვით თარგმნილი ფრაზები. სწორად: „რით შემიძლია დაგეხმაროთ?", „კიდევ რით დაგეხმაროთ?", „რას გირჩევდით..." — და არა „როგორ შემიძლია დაგეხმაროთ?". დაწერე ისე, როგორც ცოცხალი ქართველი გამყიდველი დაწერდა.
   📵 არ გამოიყენო markdown — Messenger/Instagram ვარსკვლავებს („*", „**"), „#"-სა და „_"-ს უბრალო ტექსტად აჩვენებს (კლიენტი დაინახავს „**"-ს). წერ სუფთა ტექსტით. თუ პროდუქტებს ჩამოთვლი — თითო ცალკე ხაზზე, ასე: „• წითელი მაისური — 89 ₾ (S-XL)".
2. ეყრდნობი მხოლოდ ქვემოთ მოცემულ მარაგსა და ინფორმაციას. არასდროს მოიგონო პროდუქტი, ფასი, მახასიათებელი, მარაგი ან პირობა.
3. მიესალმე („გამარჯობა") მხოლოდ საუბრის დასაწყისში. თუ საუბარი უკვე მიმდინარეობს (ზემოთ ისტორია არსებობს), აღარ გაიმეორო „გამარჯობა" ყოველ პასუხში — პირდაპირ დაეხმარე, ზედმეტი ლაპარაკის გარეშე.
4. თუ კითხვა ბუნდოვანია, ჯერ **დააზუსტე** (ზომა, ფერი, ბიუჯეტი, ვისთვის), მერე მიეცი კონკრეტული რჩევა.
5. ფასი ყოველთვის მიუთითე ვალუტით ({currency}). თუ ვალუტა GEL-ია, ქართულად უფრო ბუნებრივია „₾" ან „ლარი" (მაგ. „89 ₾"), ვიდრე „GEL". თუ პროდუქტი ამოწურულია (მარაგი 0) — თქვი ეს და შესთავაზე მსგავსი მარაგიდან.
6. თუ ეძებს იმას, რაც არ გვაქვს — თავაზიანად უთხარი და **შესთავაზე ალტერნატივა** მარაგიდან.
7. სადაც ბუნებრივია, **რბილად შესთავაზე** თანმხლები/დამატებითი პროდუქტი — ოღონდ არა თავხედურად.
8. მიწოდება, გადახდა, გარანტია, დაბრუნება — უპასუხე **მხოლოდ** ქვემოთ „დამატებითი ინფორმაციის" მიხედვით. თუ იქ არ წერია — თქვი რომ ოპერატორი დააზუსტებს; ნუ მოიგონებ.
9. როცა კლიენტი მზადაა შესაკვეთად (ან კითხულობს როგორ იყიდოს) — მიეცი ეს ბმული: {order_link}
10. თუ ვერ ეხმარები ან კლიენტი ადამიან-ოპერატორს ითხოვს — უპასუხე „ერთ წამში, ოპერატორი დაგიკავშირდებათ 🙏" და პასუხის ბოლოს დაამატე ზუსტად ეს ნიშანი: [[HANDOFF]] (კლიენტი მას ვერ ხედავს — სისტემა წაშლის და გამყიდველს შეატყობინებს). ეს ნიშანი დაამატე მხოლოდ მაშინ, როცა ნამდვილად საჭიროა ადამიანის ჩართვა.
11. 📷 თუ კლიენტი ფოტოს გამოგზავნის — ყურადღებით დაათვალიერე. თუ შენს პროდუქტებს ფოტოები აქვთ, ისინიც მოგეწოდება შესადარებლად — გამოიყენე ვიზუალურად ზუსტი ამოცნობისთვის და დაასახელე კონკრეტული პროდუქტი (სახელი, ფასი, მარაგი). თუ ზუსტად ვერ ცნობ, აღწერე რას ხედავ და დააზუსტე კლიენტთან, ან შესთავაზე ალტერნატივა მარაგიდან. არასდროს მოიგონო პროდუქტი, რომელიც მარაგში არ არის.

მაგალითები (ტონისა და ბუნებრივი ქართულისთვის):
კლიენტი: გამარჯობა
შენ: გამარჯობა! 😊 რით შემიძლია დაგეხმაროთ?

კლიენტი: რამე კარგი მირჩიე
შენ: სიამოვნებით! 😊 ვისთვის ეძებთ — საჩუქრად თუ საკუთარ თავს? და დაახლოებით რა ბიუჯეტში?

კლიენტი: 100 ლარამდე რა გაქვთ?
შენ: ამ ბიუჯეტში გვაქვს:
• წითელი მაისური Nike — 89 ₾ (S-XL)
• თეთრი პერანგი — 65 ₾
რომელი მოგწონთ? 😊

მაღაზია: {shop_name}
აღწერა: {shop_description}

მიმდინარე მარაგი:
{inventory}
{knowledge_section}"""


# ---------------------------------------------------------------------------
# #3 ჭკვიანი პროდუქტ-ძებნა — დიდ მარაგზე მოდელს მხოლოდ რელევანტურ პროდუქტებს ვუგზავნით
# ---------------------------------------------------------------------------
# ამ ზღვარს ზემოთ ვრთავთ retrieval-ს (ქვემოთ — ყველა პროდუქტი პირდაპირ prompt-ში)
RETRIEVE_LIMIT = 30

# ხშირი სასაუბრო სიტყვები — ესენი პროდუქტს არ განსაზღვრავს, ამიტომ არ ვითვლით
_STOPWORDS = {
    "მინდა", "გინდა", "გაქვთ", "გაქვს", "აქვს", "უნდა", "ეს", "ის", "რა", "რას",
    "რამე", "კარგი", "არის", "და", "თუ", "ხომ", "მე", "შენ", "თქვენ", "რომელი",
    "როგორ", "ფასი", "ღირს", "რამდენი", "გამარჯობა", "მოიცა", "კი", "არა", "ჯერ",
    "ახლა", "ხო", "ან", "ვის", "ვისთვის", "საჩუქრად", "მაჩვენე", "მიჩვენე",
}


def select_relevant_products(products, message, history=None, max_products: int = RETRIEVE_LIMIT):
    """დიდ ასორტიმენტზე — მოდელს მხოლოდ რელევანტურ პროდუქტებს ვუბრუნებთ.

    პატარა მარაგზე (≤ max_products) — ყველა (უცვლელი ქცევა).
    დიდზე — keyword-ს ვადარებთ კლიენტის მიმდინარე + ბოლო შეტყობინებას და
    ვაბრუნებთ ყველაზე რელევანტურ max_products-ს. თუ საკვანძო სიტყვა არ ემთხვევა
    (ზოგადი კითხვა) — პირველ max_products-ს (ბოტი მაინც დააზუსტებს კლიენტთან).
    """
    if not products or len(products) <= max_products:
        return products or []

    parts = [message or ""]
    for turn in reversed(history or []):
        if turn.get("role") == "user":
            parts.append(turn.get("content") or "")
            break
    tokens = {
        t for t in re.split(r"\W+", " ".join(parts).lower())
        if len(t) >= 2 and t not in _STOPWORDS
    }
    if not tokens:
        return products[:max_products]

    scored = []
    for p in products:
        hay = " ".join(str(p.get(k) or "") for k in ("name", "description", "sku")).lower()
        score = sum(1 for t in tokens if t in hay)
        if score:
            scored.append((score, p))
    scored.sort(key=lambda sp: sp[0], reverse=True)
    top = [p for _, p in scored[:max_products]]
    return top if top else products[:max_products]


def _format_inventory(products, currency: str, total: int | None = None) -> str:
    """მარაგის ტექსტად ჩამოყალიბება prompt-ისთვის."""
    if not products:
        return "(მარაგი ცარიელია — ამ მომენტში პროდუქტი არ არის ხელმისაწვდომი.)"
    lines = []
    for p in products:
        name = p.get("name", "უსახელო")
        price = p.get("price", 0)
        qty = p.get("quantity", 0)
        stock = f"მარაგშია: {qty}" if qty and qty > 0 else "ამოწურულია"
        try:
            has_price = float(price) > 0
        except (TypeError, ValueError):
            has_price = False
        price_str = f"{price} {currency}" if has_price else "ფასი დასაზუსტებელია"
        line = f"- {name} — {price_str}, {stock}"
        if p.get("sku"):
            line += f", SKU: {p['sku']}"
        if p.get("description"):
            line += f". {p['description']}"
        lines.append(line)
    body = "\n".join(lines)
    # თუ დიდი მარაგიდან მხოლოდ ნაწილი ჩავრთეთ — ბოტს ვამცნობთ (რომ „ეს არის ყველაფერი" არ თქვას)
    if total is not None and total > len(products):
        body += (
            f"\n\n(ეს {len(products)} პროდუქტი შენს შეკითხვას ყველაზე უკეთ ესადაგება "
            f"სულ {total}-დან. თუ კლიენტი სხვას ეძებს, დააზუსტე რას ეძებს.)"
        )
    return body


def _public_base() -> str:
    """საჯარო base URL — public_base_url, თუ არა — fb_redirect_uri-ის დომენი, თუ არა — frontend_url."""
    s = get_settings()
    if s.public_base_url:
        return s.public_base_url.rstrip("/")
    if s.fb_redirect_uri:
        return s.fb_redirect_uri.split("/facebook/")[0].rstrip("/")
    return s.frontend_url.rstrip("/")


def order_link_for(shop) -> str:
    """თითო მაღაზიის ავტომატური შესაკვეთი ლინკი (shop_id-დან)."""
    return f"{_public_base()}/panel/order.html?shop={shop.get('id')}"


def build_system_prompt(shop, products, total: int | None = None) -> str:
    """ქმნის system prompt-ს მაღაზიისა და მარაგის მიხედვით (offline, network-ის გარეშე).

    total: მარაგის სრული რაოდენობა (თუ products უკვე გაფილტრულია retrieval-ით) —
    ბოტი გაიგებს, რომ ნაჩვენები არ არის სრული მარაგი.
    """
    currency = shop.get("currency") or "GEL"
    knowledge = (shop.get("knowledge") or "").strip()
    knowledge_section = (
        f"\nდამატებითი ინფორმაცია (მაღაზიის დოკუმენტიდან):\n{knowledge}\n" if knowledge else ""
    )
    language_rule = _LANG_RULES.get(shop.get("bot_language") or "auto", _LANG_RULES["auto"])
    return SYSTEM_PROMPT_TEMPLATE.format(
        shop_name=shop.get("name") or "მაღაზია",
        currency=currency,
        shop_description=shop.get("description") or "—",
        inventory=_format_inventory(products, currency, total),
        order_link=order_link_for(shop),
        knowledge_section=knowledge_section,
        language_rule=language_rule,
    )


def _fetch_product_images(products, max_images: int = 12):
    """რელევანტური პროდუქტების ფოტოებს ჩამოტვირთავს ვიზუალური შედარებისთვის.

    აბრუნებს [(label, (bytes, mime)), ...] — მხოლოდ იმ პროდუქტების, რომლებსაც
    ფოტო აქვთ (image_url). max_images — ჭერი (ხარჯი/სისწრაფე; ბევრი სურათი
    Gemini-ს ძვირი/ნელი უჯდება). ჩამოტვირთვა პარალელურია და მოკლე timeout-ით,
    რომ ბოტის პასუხი არ შეყოვნდეს (webhook სინქრონულია).
    """
    from concurrent.futures import ThreadPoolExecutor

    from app.services.facebook import download_image

    # კანდიდატები — მხოლოდ ფოტოიანი, max_images-მდე
    candidates = []
    for p in products or []:
        if (p.get("image_url") or "").strip():
            candidates.append(p)
        if len(candidates) >= max_images:
            break
    if not candidates:
        return []

    def _one(p):
        try:
            return p, download_image(p["image_url"], timeout=8)
        except Exception:
            return p, None

    refs = []
    with ThreadPoolExecutor(max_workers=min(8, len(candidates))) as ex:
        for p, got in ex.map(_one, candidates):
            if not got:
                continue
            label = f"• {p.get('name', '?')} — {p.get('price', 0)}"
            if p.get("sku"):
                label += f" (SKU: {p['sku']})"
            refs.append((label, got))
    return refs


def _build_contents(message: str, history, images=None, product_refs=None):
    """საუბრის ისტორია + ახალი შეტყობინება (და სურათები) Gemini-ის ფორმატში.

    history:      სია ელემენტებით {"role": "user"|"bot", "content": "..."}.
    images:       სია (bytes, mime_type) — კლიენტის გამოგზავნილი ფოტოები.
    product_refs: სია (label, (bytes, mime)) — მარაგის პროდუქტების საცნობარო
                  ფოტოები, კლიენტის ფოტოსთან ვიზუალურად შესადარებლად.
    """
    from google.genai import types

    contents = []
    for turn in history or []:
        role = "user" if turn.get("role") == "user" else "model"
        text = (turn.get("content") or "").strip()
        if text:
            contents.append(types.Content(role=role, parts=[types.Part(text=text)]))

    parts = []
    has_client_img = bool(images)
    if has_client_img:
        parts.append(types.Part(text="📷 კლიენტმა გამოგზავნა ეს ფოტო(ები):"))
        for item in images or []:
            try:
                data, mime = item
                parts.append(types.Part.from_bytes(data=data, mime_type=mime))
            except Exception:
                pass  # გატეხილი სურათი — გამოვტოვოთ

    # პროდუქტების საცნობარო ფოტოები — ვიზუალური ამოცნობისთვის
    if product_refs:
        parts.append(types.Part(text=(
            "🛍️ შენს მარაგში ქვემოთ ჩამოთვლილ პროდუქტებს აქვთ ფოტოები. ყურადღებით შეადარე "
            "კლიენტის ფოტოს. თუ რომელიმე ემთხვევა (იგივე ან ძალიან მსგავსი), ზუსტად ის პროდუქტი "
            "დაასახელე ფასითა და მარაგით. თუ ვერცერთს ვერ ადარებ — აღწერე რას ხედავ და დააზუსტე კლიენტთან:"
        )))
        for label, got in product_refs:
            parts.append(types.Part(text=label))
            try:
                data, mime = got
                parts.append(types.Part.from_bytes(data=data, mime_type=mime))
            except Exception:
                pass

    msg = (message or "").strip()
    if msg:
        parts.append(types.Part(text=msg))
    elif has_client_img:  # მხოლოდ ფოტო, ტექსტის გარეშე
        parts.append(types.Part(text="(კლიენტმა ფოტო გამოგზავნა ტექსტის გარეშე — ამოიცანი და უპასუხე მარაგზე დაყრდნობით.)"))
    if not parts:
        parts.append(types.Part(text=msg))
    contents.append(types.Content(role="user", parts=parts))
    return contents


def get_bot_reply(shop, products, message: str, history=None, images=None) -> str:
    """აბრუნებს ბოტის ქართულ პასუხს Gemini-ით.

    shop:     dict (name, currency, description, ...)
    products: list[dict] (მხოლოდ აქტიური პროდუქტები უნდა გადმოეცეს)
    message:  კლიენტის შეტყობინება
    history:  წინა საუბარი (არასავალდებულო)
    images:   სია (bytes, mime_type) — კლიენტის ფოტოები (multimodal, არასავალდებულო)
    """
    settings = get_settings()
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY არ არის კონფიგურირებული .env-ში")

    from google import genai
    from google.genai import types

    # #3 ჭკვიანი ძებნა — დიდ მარაგზე მოდელს მხოლოდ რელევანტურ პროდუქტებს ვუგზავნით
    total = len(products) if products else 0
    relevant = select_relevant_products(products, message, history)

    # ვიზუალური ამოცნობა — თუ კლიენტმა ფოტო გამოგზავნა, რელევანტური პროდუქტების
    # ფოტოებსაც ვურთავთ, რომ Gemini-მ ვიზუალურად შეადაროს და კონკრეტული ამოიცნოს.
    product_refs = _fetch_product_images(relevant) if images else None

    client = genai.Client(api_key=settings.gemini_api_key)
    config = types.GenerateContentConfig(
        system_instruction=build_system_prompt(shop, relevant, total=total),
        temperature=0.3,
        max_output_tokens=800,
    )
    contents = _build_contents(message, history, images, product_refs=product_refs)

    # დროებითი 503/429-ებზე ხელახლა ვცდით მცირე დაყოვნებით
    for attempt in range(4):
        try:
            response = client.models.generate_content(
                model=settings.gemini_model, contents=contents, config=config
            )
            return (response.text or "").strip()
        except Exception as e:
            if attempt < 3 and any(k in str(e) for k in _TRANSIENT):
                time.sleep(1.5 * (attempt + 1))
                continue
            raise
