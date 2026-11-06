"""A-045 (N-09): გვერდის არჩევის (page selection) token.

როცა Facebook-ის მომხმარებელს ≥2 გვერდი აქვს, callback არ აკავშირებს არცერთს, არამედ აბრუნებს
token-ს; მომხმარებელი არჩევს გვერდს და `POST /facebook/connect/select` token-ს უკან აგზავნის.

- რატომ Fernet: AES-128-CBC + HMAC-SHA256 — token ერთდროულად დაშიფრულია (user token URL-ში/ლოგში
  არ ჩანს) და ავთენტიფიცირებული (ვერავინ გააყალბებს), timestamp ჩაშენებულია, `cryptography` უკვე
  dependency-ა.
- რატომ ცალკე HKDF label (`chatassist:fb-page-selection:v1`): domain separation — page token-ების
  `FB_TOKEN_ENCRYPTION_KEY`-ის და OAuth state-ის გასაღებებით შექმნილი ტექსტი ამ token-ად ვერ
  გაივლის და პირიქით.
- რატომ user token და არა page token-ები: ზომა (token URL-ში მოგზაურობს; 25 page token ძალიან
  დიდია) და არჩევისას გვერდები Graph-იდან თავიდან მოწმდება — token მხოლოდ "ვის სახელით" იცავს.
- stateless: სერვერზე არაფერი ინახება, ამიტომ 10 წუთის განმავლობაში იმავე მომხმარებლის მიერ
  განმეორება შესაძლებელია (იგივე მაღაზიის ხელახალი დაკავშირება) — უვნებელია.

ლოგირება განზრახ არ არის: token და მისი შიგთავსი არასდროს უნდა მოხვდეს ლოგში.
"""
import base64
import json
import time

from cryptography.fernet import Fernet, InvalidToken

from app.core.crypto import KEY_FB_PAGE_SELECTION, derive_key

TTL_SECONDS = 600
MAX_PAGES = 25  # Graph-ის /me/accounts default გვერდი
MAX_TOKEN_CHARS = 4096
_FUTURE_SKEW_SECONDS = 60


class SelectionError(Exception):
    """kind: "invalid" (გაყალბებული / დაზიანებული / სხვისი) ან "expired" (ვადაგასული)."""

    def __init__(self, kind: str):
        super().__init__(kind)
        self.kind = kind


def _fernet() -> Fernet:
    # ცარიელი FB_APP_SECRET → RuntimeError (fail closed)
    return Fernet(base64.urlsafe_b64encode(derive_key(KEY_FB_PAGE_SELECTION)))


def make(user_id: str, shop_id: str, user_token: str, page_ids: list[str]) -> str:
    if not 1 <= len(page_ids) <= MAX_PAGES:
        raise ValueError(f"page_ids must contain 1..{MAX_PAGES} items")
    payload = {"v": 1, "uid": user_id, "shop": shop_id, "ut": user_token, "pages": list(page_ids)}
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return _fernet().encrypt(raw).decode()


def _nonempty_str(value: object) -> bool:
    return isinstance(value, str) and bool(value)


def read(token: str, user_id: str, *, now: float | None = None) -> dict:
    """token-ის გახსნა და შემოწმება; შეცდომისას `SelectionError`."""
    if not isinstance(token, str) or not token or len(token) > MAX_TOKEN_CHARS:
        raise SelectionError("invalid")
    f = _fernet()
    try:
        ts = f.extract_timestamp(token)  # ხელმოწერას ამოწმებს
    except (InvalidToken, ValueError, TypeError):
        raise SelectionError("invalid") from None
    now = time.time() if now is None else now
    if now - ts > TTL_SECONDS:
        raise SelectionError("expired")
    if ts - now > _FUTURE_SKEW_SECONDS:
        raise SelectionError("invalid")
    try:
        data = json.loads(f.decrypt(token))
    except (InvalidToken, ValueError, TypeError):
        raise SelectionError("invalid") from None
    if (
        not isinstance(data, dict)
        or data.get("v") != 1
        or not _nonempty_str(data.get("uid"))
        or not _nonempty_str(data.get("shop"))
        or not _nonempty_str(data.get("ut"))
    ):
        raise SelectionError("invalid")
    pages = data.get("pages")
    if (
        not isinstance(pages, list)
        or not 1 <= len(pages) <= MAX_PAGES
        or not all(isinstance(p, str) for p in pages)
    ):
        raise SelectionError("invalid")
    # სხვისი token — იგივე kind, რომ არჩევანის არსებობა არ გამჟღავნდეს
    if data["uid"] != user_id:
        raise SelectionError("invalid")
    return data
