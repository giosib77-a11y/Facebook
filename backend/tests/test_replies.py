"""Stage 16 (S16-3): preprocess templates and `clean_reply` (pure module, offline)."""
import json
import random
from pathlib import Path

import pytest

from app.services import replies
from app.services.replies import (
    TemplateMatch,
    clean_reply,
    handoff_reply,
    match_template,
    normalize_for_match,
)

DATA_FILE = Path(__file__).resolve().parents[1] / "scripts" / "compare_questions.json"
ORDER_URL = "https://chatassist.ge/panel/order.html?shop=3f2b8c1e-5d4a-4e6b-9c7d-0a1b2c3d4e5f"

GREETING = {
    "ka": ["გამარჯობა", "გამარჯობათ", "სალამი", "მოგესალმებით", "gamarjoba", "gamarjobat", "salami"],
    "en": ["hi", "hello", "hey", "hi there", "hello there", "good morning", "good afternoon", "good evening"],
    "ru": ["привет", "здравствуйте", "здрасьте", "добрый день", "доброе утро", "добрый вечер"],
}
THANKS = {
    "ka": ["მადლობა", "დიდი მადლობა", "მადლობთ", "გმადლობთ", "დიდად გმადლობთ", "madloba", "didi madloba", "gmadlobt"],
    "en": ["thanks", "thank you", "thanks a lot", "thank you very much", "thx", "ty"],
    "ru": ["спасибо", "спасибо большое", "большое спасибо", "благодарю"],
}
OPERATOR = {
    "ka": [
        "ოპერატორი", "ოპერატორთან", "ოპერატორი მინდა", "ოპერატორთან დამაკავშირეთ", "ოპერატორთან დამაკავშირე",
        "ოპერატორს დამალაპარაკეთ", "ადამიანი მინდა", "ცოცხალი ადამიანი", "ცოცხალ ადამიანთან დამაკავშირეთ",
        "operatori", "operatortan",
    ],
    "en": [
        "operator", "human", "agent", "real person", "talk to a human", "talk to a person",
        "speak to a human", "human please", "operator please",
    ],
    "ru": ["оператор", "оператора", "позовите оператора", "соедините с оператором", "живой человек", "человек"],
}
TABLE = {"greeting": GREETING, "thanks": THANKS, "operator": OPERATOR}

REPLIES = {
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

ALL_PHRASES = [
    (intent, lang, phrase)
    for intent, by_lang in TABLE.items()
    for lang, phrases in by_lang.items()
    for phrase in phrases
]


# ---------- normalize_for_match ----------

@pytest.mark.parametrize(
    "raw, expected",
    [
        ("გამარჯობა!!! 😊", "გამარჯობა"),
        ("Hello.", "hello"),
        ("СПАСИБО!", "спасибо"),
        ("  ოპერატორი?  ", "ოპერატორი"),
        ("Good\t\nMorning,,,  ", "good morning"),
        ("hi-there", "hi there"),
        ("😊🙏", ""),
        ("", ""),
        ("   ", ""),
        (None, ""),
    ],
)
def test_normalize_for_match(raw, expected):
    assert normalize_for_match(raw) == expected


# ---------- phrase tables ----------

def test_phrase_tables_match_spec_and_are_normalized():
    for intent, by_lang in TABLE.items():
        for lang, phrases in by_lang.items():
            stored = replies._PHRASES[intent][lang]
            assert stored == frozenset(phrases), (intent, lang)
            for phrase in stored:
                assert normalize_for_match(phrase) == phrase, phrase


def test_no_phrase_is_shared_between_intents_or_languages():
    total = sum(len(p) for by_lang in replies._PHRASES.values() for p in by_lang.values())
    assert len(replies._LOOKUP) == total == len(ALL_PHRASES)


# ---------- match_template ----------

@pytest.mark.parametrize("intent, lang, phrase", ALL_PHRASES)
def test_every_phrase_matches_exact_and_noisy_variants(intent, lang, phrase):
    for variant in (phrase, phrase.upper(), phrase.title(), f"{phrase}!!! 😊", f"  {phrase}?  ", f"{phrase}."):
        m = match_template(variant, "auto")
        assert m is not None, variant
        assert m.intent == intent
        assert m.reply == REPLIES[intent][lang]
        assert m.handoff is (intent == "operator")


@pytest.mark.parametrize(
    "message",
    [
        "გამარჯობა, წითელი მაისური გაქვთ?",
        "thanks, how much is it?",
        "ოპერატორი რომ მყავდეს, რას მეტყოდა?",
        "human size shoes?",
        "hello i want to order",
        "спасибо, а сколько стоит?",
        "გამარჯობა გამარჯობა",
        "hi hi",
        "good night",
        "madloba rom gtxovt",
    ],
)
def test_longer_messages_do_not_match(message):
    assert match_template(message, "auto") is None
    assert match_template(message, "ka") is None


@pytest.mark.parametrize("message", ["", "   ", "😊", "!!!", None])
def test_empty_message_does_not_match(message):
    assert match_template(message, "auto") is None
    assert match_template(message, "ka") is None


def test_no_compare_question_matches_a_template():
    questions = json.loads(DATA_FILE.read_text(encoding="utf-8"))["questions"]
    assert len(questions) == 40
    for q in questions:
        assert match_template(q["message"], "auto") is None, q["id"]


@pytest.mark.parametrize("bot_language", ["auto", None, "xx", "", "KA"])
@pytest.mark.parametrize("intent, lang, phrase", ALL_PHRASES)
def test_auto_or_unknown_language_follows_phrase_language(bot_language, intent, lang, phrase):
    assert match_template(phrase, bot_language).reply == REPLIES[intent][lang]


@pytest.mark.parametrize("shop_lang", ["ka", "en", "ru"])
@pytest.mark.parametrize("intent, lang, phrase", ALL_PHRASES)
def test_fixed_shop_language_wins_over_phrase_language(shop_lang, intent, lang, phrase):
    assert match_template(phrase, shop_lang).reply == REPLIES[intent][shop_lang]


def test_english_phrase_in_fixed_language_shops():
    assert match_template("Hello", "ka").reply == REPLIES["greeting"]["ka"]
    assert match_template("Hello", "en").reply == REPLIES["greeting"]["en"]
    assert match_template("Hello", "ru").reply == REPLIES["greeting"]["ru"]


def test_exact_reply_texts():
    assert match_template("გამარჯობა", "auto") == TemplateMatch(
        "greeting", "გამარჯობა! 😊 რით შემიძლია დაგეხმაროთ?", False
    )
    assert match_template("thanks", "auto") == TemplateMatch(
        "thanks", "You're welcome! 😊 Anything else I can help with?", False
    )
    assert match_template("оператор", "auto") == TemplateMatch(
        "operator", "Одну минуту, оператор скоро с вами свяжется 🙏", True
    )


def test_only_operator_sets_handoff():
    for intent, lang, phrase in ALL_PHRASES:
        assert match_template(phrase, "auto").handoff is (intent == "operator"), phrase


def test_operator_template_reuses_l1_georgian_phrase():
    # L1-ის (prompt.py) არსებული ფრაზა - ბოტი ორივე გზით ერთსა და იმავეს ამბობს
    assert REPLIES["operator"]["ka"] == "ერთ წამში, ოპერატორი დაგიკავშირდებათ 🙏"
    assert handoff_reply("ka") == "ერთ წამში, ოპერატორი დაგიკავშირდებათ 🙏"


def test_template_match_is_frozen():
    m = match_template("hi", "auto")
    with pytest.raises(AttributeError):
        m.reply = "x"


# ---------- handoff_reply ----------

@pytest.mark.parametrize(
    "bot_language, expected",
    [
        ("ka", REPLIES["operator"]["ka"]),
        ("en", REPLIES["operator"]["en"]),
        ("ru", REPLIES["operator"]["ru"]),
        ("auto", REPLIES["operator"]["ka"]),
        (None, REPLIES["operator"]["ka"]),
        ("de", REPLIES["operator"]["ka"]),
    ],
)
def test_handoff_reply(bot_language, expected):
    assert handoff_reply(bot_language) == expected


# ---------- clean_reply ----------

@pytest.mark.parametrize(
    "raw, expected",
    [
        # bold
        ("**წითელი მაისური** — 89 ₾", "წითელი მაისური — 89 ₾"),
        ("a **b** c **d**", "a b c d"),
        ("__bold__ text", "bold text"),
        ("**unclosed bold", "unclosed bold"),
        ("** spaced **", "spaced"),
        ("****", ""),
        # heading
        ("# Title\ntext", "Title\ntext"),
        ("### Sub title", "Sub title"),
        ("   ## indented", "indented"),
        ("not # a heading", "not # a heading"),
        ("#hashtag", "#hashtag"),
        # backticks / fences
        ("`code` here", "code here"),
        ("```\nline1\nline2\n```", "line1\nline2"),
        ("before\n```python\nx = 1\n```\nafter", "before\nx = 1\nafter"),
        ("```json", ""),
        # links
        ("[ბმული](https://example.com/a?b=1)", "ბმული: https://example.com/a?b=1"),
        ("[https://example.com](https://example.com)", "https://example.com"),
        ("see [shop](http://x.ge) now", "see shop: http://x.ge now"),
        ("[no url]( not-a-link )", "[no url]( not-a-link )"),
        # lists
        ("- ერთი\n- ორი", "• ერთი\n• ორი"),
        ("* ერთი\n* ორი", "• ერთი\n• ორი"),
        ("  - indented", "• indented"),
        ("-5 degrees", "-5 degrees"),
        ("**Title**\n- a\n- b", "Title\n• a\n• b"),
        # whitespace
        ("a   \nb\t\n\n\n\n\nc", "a\nb\n\nc"),
        ("  \n hi \n  ", "hi"),
        ("a\r\nb\r\n", "a\nb"),
    ],
)
def test_clean_reply_exact(raw, expected):
    assert clean_reply(raw) == expected


def test_clean_reply_order_link_is_untouched():
    plain = f"შეგიძლიათ შეუკვეთოთ აქ: {ORDER_URL}"
    assert clean_reply(plain) == plain
    assert clean_reply(f"{plain} 🙏") == f"{plain} 🙏"
    assert clean_reply(f"[{ORDER_URL}]({ORDER_URL})") == ORDER_URL
    assert clean_reply(f"[შეკვეთა]({ORDER_URL})") == f"შეკვეთა: {ORDER_URL}"
    assert clean_reply(f"**შეკვეთა:** {ORDER_URL}") == f"შეკვეთა: {ORDER_URL}"
    assert clean_reply(f"- {ORDER_URL}") == f"• {ORDER_URL}"


def test_clean_reply_keeps_bullet_product_lines():
    line = "• წითელი მაისური — 89 ₾ (S-XL)"
    assert clean_reply(line) == line
    assert clean_reply(f"{line}\n• შავი ჯინსი — 120 ₾") == f"{line}\n• შავი ჯინსი — 120 ₾"


@pytest.mark.parametrize(
    "text",
    [
        "https://example.com/a__b__c",
        "https://example.com/path/__init__/x",
        "https://example.com/?q=__x__",
        "SKU_12__34 ხელმისაწვდომია",
        "2*3=6",
        "a * b",
        "snake_case_name",
        "5 ცალი, 2*2",
    ],
)
def test_clean_reply_leaves_single_stars_underscores_and_urls(text):
    assert clean_reply(text) == text


def test_clean_reply_removes_old_marks_only_in_double_bracket_caps():
    assert clean_reply("ერთ წამში [[HANDOFF]]") == "ერთ წამში"
    assert clean_reply("[[HANDOFF]]") == ""
    assert clean_reply("a [[OTHER_MARK]] b") == "a  b"
    assert clean_reply("[[x]]") == "[[x]]"
    assert clean_reply("[[A]]") == "[[A]]"  # ერთი ასო - ნიშანი არაა
    assert clean_reply("[[lower]]") == "[[lower]]"
    assert clean_reply("[HANDOFF]") == "[HANDOFF]"


def test_clean_reply_keeps_emoji_and_plain_text():
    text = "გამარჯობა! 😊 რით შემიძლია დაგეხმაროთ? 🙏"
    assert clean_reply(text) == text


@pytest.mark.parametrize("value", ["", "   ", "\n\n", None])
def test_clean_reply_empty_and_none(value):
    assert clean_reply(value) == ""


def test_clean_reply_only_markup_becomes_empty():
    assert clean_reply("[[HANDOFF]]\n") == ""
    assert clean_reply("```\n```") == ""


def test_clean_reply_idempotent_on_known_cases():
    samples = [
        "**bold** `c` # h",
        "# T\n- a\n* b\n\n\n\nc [l](https://u.ge) [[HANDOFF]]",
        "[[A[[B]]B]]",
        f"[x]({ORDER_URL})",
        "***a***",
        "- - x",
        "* * *",
        "```\n**x**\n```",
        "• 89 ₾ — 2*3=6",
    ]
    for s in samples:
        once = clean_reply(s)
        assert clean_reply(once) == once, s


def test_clean_reply_idempotent_on_random_markup_soup():
    rng = random.Random(1234)
    atoms = [
        "*", "**", "_", "__", "`", "```", "\n", "\n\n", " ", "- ", "* ", "# ", "## ", "[", "]", "(", ")",
        "[[", "]]", "HANDOFF", "AB", "x", "ab", "https://u.ge/a", "](https://u.ge)", "[a](", "•", "😊",
    ]
    for _ in range(3000):
        s = "".join(rng.choice(atoms) for _ in range(rng.randint(0, 14)))
        once = clean_reply(s)
        assert clean_reply(once) == once, repr(s)
