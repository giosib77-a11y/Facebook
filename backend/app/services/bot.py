"""ბოტის ლოგიკა — Gemini-ით ქართული პასუხები მაღაზიის მარაგზე დაყრდნობით.

მთავარი ფუნქცია: get_bot_reply(shop, products, message, history).
system prompt გამოტანილია ცალკე ფუნქციად (build_system_prompt), რომ ადვილად
ჩაანაცვლო შენი საბოლოო ვერსიით და offline-ად დატესტო.
"""
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
    "auto": "პასუხობ იმ ენაზე, რომელზეც კლიენტი წერს (ქართული, English ან русский); თუ ვერ ხვდები — ქართულად.",
    "ka": "პასუხობ ყოველთვის მხოლოდ ქართულად.",
    "en": "Always reply in English only.",
    "ru": "Отвечай всегда только на русском языке.",
}

SYSTEM_PROMPT_TEMPLATE = """შენ ხარ "{shop_name}"-ის გამოცდილი გამყიდველ-კონსულტანტი Facebook Messenger-სა და Instagram Direct-ში. მიზანი — დაეხმარო კლიენტს სწრაფად და თბილად, და გაყიდვა ბუნებრივად დაასრულო.

ქცევის წესები:
1. {language_rule} წერ მოკლედ და ბუნებრივად — როგორც ცოცხალი, თბილი გამყიდველი, არა რობოტი. emoji ზომიერად (1-2 შეტყობინებაზე).
2. ეყრდნობი მხოლოდ ქვემოთ მოცემულ მარაგსა და ინფორმაციას. არასდროს მოიგონო პროდუქტი, ფასი, მახასიათებელი, მარაგი ან პირობა.
3. მიესალმე თბილად, მაგრამ პირდაპირ დაეხმარე — ზედმეტი ლაპარაკის გარეშე.
4. თუ კითხვა ბუნდოვანია, ჯერ **დააზუსტე** (ზომა, ფერი, ბიუჯეტი, ვისთვის), მერე მიეცი კონკრეტული რჩევა.
5. ფასი ყოველთვის მიუთითე ვალუტით ({currency}). თუ პროდუქტი ამოწურულია (მარაგი 0) — თქვი ეს და შესთავაზე მსგავსი მარაგიდან.
6. თუ ეძებს იმას, რაც არ გვაქვს — თავაზიანად უთხარი და **შესთავაზე ალტერნატივა** მარაგიდან.
7. სადაც ბუნებრივია, **რბილად შესთავაზე** თანმხლები/დამატებითი პროდუქტი — ოღონდ არა თავხედურად.
8. მიწოდება, გადახდა, გარანტია, დაბრუნება — უპასუხე **მხოლოდ** ქვემოთ „დამატებითი ინფორმაციის" მიხედვით. თუ იქ არ წერია — თქვი რომ ოპერატორი დააზუსტებს; ნუ მოიგონებ.
9. როცა კლიენტი მზადაა შესაკვეთად (ან კითხულობს როგორ იყიდოს) — მიეცი ეს ბმული: {order_link}
10. თუ ვერ ეხმარები ან კლიენტი ადამიან-ოპერატორს ითხოვს — უპასუხე „ერთ წამში, ოპერატორი დაგიკავშირდებათ 🙏" და პასუხის ბოლოს დაამატე ზუსტად ეს ნიშანი: [[HANDOFF]] (კლიენტი მას ვერ ხედავს — სისტემა წაშლის და გამყიდველს შეატყობინებს). ეს ნიშანი დაამატე მხოლოდ მაშინ, როცა ნამდვილად საჭიროა ადამიანის ჩართვა.

მაგალითი (ტონისთვის):
კლიენტი: რამე კარგი მირჩიე
შენ: სიამოვნებით! 😊 ვისთვის ეძებთ — საჩუქრად თუ საკუთარ თავს? და დაახლოებით რა ბიუჯეტში?

მაღაზია: {shop_name}
აღწერა: {shop_description}

მიმდინარე მარაგი:
{inventory}
{knowledge_section}"""


def _format_inventory(products, currency: str) -> str:
    """მარაგის ტექსტად ჩამოყალიბება prompt-ისთვის."""
    if not products:
        return "(მარაგი ცარიელია — ამ მომენტში პროდუქტი არ არის ხელმისაწვდომი.)"
    lines = []
    for p in products:
        name = p.get("name", "უსახელო")
        price = p.get("price", 0)
        qty = p.get("quantity", 0)
        stock = f"მარაგშია: {qty}" if qty and qty > 0 else "ამოწურულია"
        line = f"- {name} — {price} {currency}, {stock}"
        if p.get("sku"):
            line += f", SKU: {p['sku']}"
        if p.get("description"):
            line += f". {p['description']}"
        lines.append(line)
    return "\n".join(lines)


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


def build_system_prompt(shop, products) -> str:
    """ქმნის system prompt-ს მაღაზიისა და მარაგის მიხედვით (offline, network-ის გარეშე)."""
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
        inventory=_format_inventory(products, currency),
        order_link=order_link_for(shop),
        knowledge_section=knowledge_section,
        language_rule=language_rule,
    )


def _build_contents(message: str, history):
    """საუბრის ისტორია + ახალი შეტყობინება Gemini-ის ფორმატში.

    history: სია ელემენტებით {"role": "user"|"bot", "content": "..."}.
    """
    from google.genai import types

    contents = []
    for turn in history or []:
        role = "user" if turn.get("role") == "user" else "model"
        text = (turn.get("content") or "").strip()
        if text:
            contents.append(types.Content(role=role, parts=[types.Part(text=text)]))
    contents.append(types.Content(role="user", parts=[types.Part(text=message)]))
    return contents


def get_bot_reply(shop, products, message: str, history=None) -> str:
    """აბრუნებს ბოტის ქართულ პასუხს Gemini-ით.

    shop:     dict (name, currency, description, ...)
    products: list[dict] (მხოლოდ აქტიური პროდუქტები უნდა გადმოეცეს)
    message:  კლიენტის შეტყობინება
    history:  წინა საუბარი (არასავალდებულო)
    """
    settings = get_settings()
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY არ არის კონფიგურირებული .env-ში")

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=settings.gemini_api_key)
    config = types.GenerateContentConfig(
        system_instruction=build_system_prompt(shop, products),
        temperature=0.3,
        max_output_tokens=800,
    )
    contents = _build_contents(message, history)

    # დროებითი 503/429-ებზე ხელახლა ვცდით მცირე დაყოვნებით
    last_err = None
    for attempt in range(4):
        try:
            response = client.models.generate_content(
                model=settings.gemini_model, contents=contents, config=config
            )
            return (response.text or "").strip()
        except Exception as e:
            last_err = e
            if attempt < 3 and any(k in str(e) for k in _TRANSIENT):
                time.sleep(1.5 * (attempt + 1))
                continue
            raise
    raise last_err
