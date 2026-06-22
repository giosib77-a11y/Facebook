"""ბოტის ლოგიკა — Gemini-ით ქართული პასუხები მაღაზიის მარაგზე დაყრდნობით.

მთავარი ფუნქცია: get_bot_reply(shop, products, message, history).
system prompt გამოტანილია ცალკე ფუნქციად (build_system_prompt), რომ ადვილად
ჩაანაცვლო შენი საბოლოო ვერსიით და offline-ად დატესტო.
"""
import time

from app.config import get_settings

# დროებითი (გადასატანი) შეცდომების ნიშნები — ასეთებზე ხელახლა ვცდით
_TRANSIENT = ("503", "UNAVAILABLE", "500", "429", "RESOURCE_EXHAUSTED", "high demand", "overloaded")

# ---------------------------------------------------------------------------
# System prompt — ქართული. ჩაანაცვლე საჭიროებისამებრ.
# ---------------------------------------------------------------------------
SYSTEM_PROMPT_TEMPLATE = """შენ ხარ "{shop_name}"-ის გაყიდვების ასისტენტი — ემსახურები ქართულ მაღაზიას Facebook Messenger-ში.

მთავარი წესები:
1. პასუხობ ყოველთვის და მხოლოდ ქართულად, თბილად, თავაზიანად და მოკლედ.
2. იყენებ მხოლოდ ქვემოთ მოცემულ მარაგს. არ მოიგონო პროდუქტი, ფასი, მახასიათებელი ან ხელმისაწვდომობა.
3. თუ კლიენტი ეძებს პროდუქტს, რომელიც მარაგში არ არის — თავაზიანად უთხარი რომ ამჟამად არ გვაქვს და, თუ შესაძლებელია, შესთავაზე მსგავსი მარაგიდან.
4. ფასი ყოველთვის მიუთითე ვალუტით ({currency}). თუ რაოდენობა 0-ია — თქვი რომ პროდუქტი ამჟამად ამოწურულია.
5. არ მისცე ინფორმაცია მიწოდებაზე, გადახდის მეთოდებზე, აქციებზე ან მისამართზე, თუ ეს მონაცემებში პირდაპირ არ წერია. ასეთ შემთხვევაში სთხოვე კლიენტს დაელოდოს ოპერატორს.
6. წაახალისე შესყიდვა, მაგრამ ნუ იქნები აგრესიული. თუ კითხვა ბუნდოვანია — დააზუსტე.

მაღაზიის აღწერა: {shop_description}

მიმდინარე მარაგი:
{inventory}
"""


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


def build_system_prompt(shop, products) -> str:
    """ქმნის system prompt-ს მაღაზიისა და მარაგის მიხედვით (offline, network-ის გარეშე)."""
    currency = shop.get("currency") or "GEL"
    return SYSTEM_PROMPT_TEMPLATE.format(
        shop_name=shop.get("name") or "მაღაზია",
        currency=currency,
        shop_description=shop.get("description") or "—",
        inventory=_format_inventory(products, currency),
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
