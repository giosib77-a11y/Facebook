"""Stage 16: preprocess templates (greeting / thanks / operator, ka+en+ru) and postprocess `clean_reply`.

Pure module: no LLM, no DB, no network. A template answers only when the WHOLE message is one of the
known phrases (equality after normalization, never substring) - everything else goes to the agent.
"""
import re
from dataclasses import dataclass

LANGS = ("ka", "en", "ru")

# ფრაზები უკვე ნორმალიზებულ ფორმაშია (casefold, პუნქტუაციის გარეშე) - ტესტი ამას ამოწმებს.
_PHRASES: dict[str, dict[str, frozenset[str]]] = {
    "greeting": {
        "ka": frozenset({
            "გამარჯობა", "გამარჯობათ", "სალამი", "მოგესალმებით",
            "gamarjoba", "gamarjobat", "salami",
        }),
        "en": frozenset({
            "hi", "hello", "hey", "hi there", "hello there",
            "good morning", "good afternoon", "good evening",
        }),
        "ru": frozenset({
            "привет", "здравствуйте", "здрасьте",
            "добрый день", "доброе утро", "добрый вечер",
        }),
    },
    "thanks": {
        "ka": frozenset({
            "მადლობა", "დიდი მადლობა", "მადლობთ", "გმადლობთ", "დიდად გმადლობთ",
            "madloba", "didi madloba", "gmadlobt",
        }),
        "en": frozenset({
            "thanks", "thank you", "thanks a lot", "thank you very much", "thx", "ty",
        }),
        "ru": frozenset({
            "спасибо", "спасибо большое", "большое спасибо", "благодарю",
        }),
    },
    "operator": {
        "ka": frozenset({
            "ოპერატორი", "ოპერატორთან", "ოპერატორი მინდა", "ოპერატორთან დამაკავშირეთ",
            "ოპერატორთან დამაკავშირე", "ოპერატორს დამალაპარაკეთ", "ადამიანი მინდა",
            "ცოცხალი ადამიანი", "ცოცხალ ადამიანთან დამაკავშირეთ",
            "operatori", "operatortan",
        }),
        "en": frozenset({
            "operator", "human", "agent", "real person", "talk to a human",
            "talk to a person", "speak to a human", "human please", "operator please",
        }),
        "ru": frozenset({
            "оператор", "оператора", "позовите оператора", "соедините с оператором",
            "живой человек", "человек",
        }),
    },
}

_REPLIES: dict[str, dict[str, str]] = {
    "greeting": {
        "ka": "გამარჯობა! 😊 რით შემიძლია დაგეხმაროთ?",
        "en": "Hello! 😊 How can I help you?",
        "ru": "Здравствуйте! 😊 Чем могу помочь?",
    },
    "thanks": {
        "ka": "არაფრის! 😊 კიდევ რით შემიძლია დაგეხმაროთ?",
        "en": "You're welcome! 😊 Anything else I can help with?",
        "ru": "Пожалуйста! 😊 Чем ещё могу помочь?",
    },
    "operator": {
        "ka": "ერთ წამში, ოპერატორი დაგიკავშირდებათ 🙏",
        "en": "One moment, an operator will contact you shortly 🙏",
        "ru": "Одну минуту, оператор скоро с вами свяжется 🙏",
    },
}

# ფრაზა -> (intent, ენა); ფრაზა ორ intent-ში / ენაში არ მეორდება (ტესტი)
_LOOKUP: dict[str, tuple[str, str]] = {
    phrase: (intent, lang)
    for intent, by_lang in _PHRASES.items()
    for lang, phrases in by_lang.items()
    for phrase in phrases
}


@dataclass(frozen=True)
class TemplateMatch:
    intent: str
    reply: str
    handoff: bool


def normalize_for_match(text: str | None) -> str:
    """casefold; არა-\\w და არა-whitespace სიმბოლო (პუნქტუაცია, emoji) -> space; whitespace იკუმშება."""
    if not text:
        return ""
    folded = re.sub(r"[^\w\s]", " ", text.casefold())
    return " ".join(folded.split())


def match_template(message: str | None, bot_language: str | None) -> TemplateMatch | None:
    """მთლიანი შეტყობინება ზუსტად ერთ-ერთი ფრაზაა -> შაბლონური პასუხი, თორემ None."""
    hit = _LOOKUP.get(normalize_for_match(message))
    if hit is None:
        return None
    intent, phrase_lang = hit
    lang = bot_language if bot_language in LANGS else phrase_lang
    return TemplateMatch(intent=intent, reply=_REPLIES[intent][lang], handoff=intent == "operator")


def handoff_reply(bot_language: str | None) -> str:
    """ოპერატორის ტექსტი მაღაზიის ენაზე (auto / უცნობი -> ka)."""
    return _REPLIES["operator"][bot_language if bot_language in LANGS else "ka"]


# ---------- postprocess ----------

_OLD_MARK = re.compile(r"\[\[[A-Z_]{2,30}\]\]")
_FENCE_LINE = re.compile(r"(?m)^[ \t]*```[\w+-]*[ \t]*(?:\n|$)")
_MD_LINK = re.compile(r"\[([^\]\n]{1,200})\]\((https?://[^\s)]+)\)")
_HEADING = re.compile(r"(?m)^[ \t]{0,3}#{1,6}[ \t]+")
_BOLD = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*")
_UNDERLINE_BOLD = re.compile(r"(?<![\w/=?&])__(?=\S)(.+?)(?<=\S)__(?![\w/])")
_BULLET = re.compile(r"(?m)^[ \t]*[-*][ \t]+")
_MANY_BLANKS = re.compile(r"\n{3,}")

_MAX_PASSES = 10


def _link(m: re.Match) -> str:
    label, url = m.group(1), m.group(2)
    return url if label.strip() == url else f"{label}: {url}"


def _clean_once(text: str) -> str:
    text = _OLD_MARK.sub("", text)
    text = _FENCE_LINE.sub("", text).replace("`", "")
    text = _MD_LINK.sub(_link, text)
    text = _HEADING.sub("", text)
    text = _BOLD.sub(r"\1", text)
    text = _UNDERLINE_BOLD.sub(r"\1", text).replace("**", "")
    text = _BULLET.sub("• ", text)
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    return _MANY_BLANKS.sub("\n\n", text).strip()


def clean_reply(text: str | None) -> str:
    """Messenger-ში markdown ლიტერალურად ჩანს - ვასუფთავებთ. გადის ფიქსირებულ წერტილამდე, რომ იყოს idempotent
    (მაგ. `[[A[[B]]B]]` ერთი გავლის შემდეგ ისევ ნიშანია)."""
    if not text:
        return ""
    for _ in range(_MAX_PASSES):
        cleaned = _clean_once(text)
        if cleaned == text:
            break
        text = cleaned
    return text
