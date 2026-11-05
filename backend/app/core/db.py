"""PostgREST მოთხოვნების შესრულების helper — შეცდომების HTTP-ში გადათარგმნა."""
import logging

from fastapi import HTTPException, status
from postgrest.exceptions import APIError

from app.config import get_settings

logger = logging.getLogger("app")

# = Supabase API-ის „Max rows" default (1000). Dashboard-ში შემცირებისას fetch_all პირველ „მოკლე"
# გვერდზე ადრე გაჩერდება და ჩუმი ჭრა დაბრუნდება — Stage 22 Deploy plan-ის შემოწმება.
PAGE_SIZE = 1000


class TooManyRows(Exception):
    """strict `fetch_all`-ში მწკრივების რაოდენობა `max_rows`-ს აჭარბებს."""

    def __init__(self, label: str, max_rows: int):
        super().__init__(f"{label}: more than {max_rows} rows")
        self.label = label
        self.max_rows = max_rows


def run(query):
    """ასრულებს supabase query-ს და APIError-ს HTTP შეცდომად აქცევს.

    მთავარი შემთხვევები:
      - 42501 insufficient_privilege  -> RLS-მა აკრძალა (403)
      - 23514 check_violation         -> ვალიდაციის დარღვევა, მაგ. price < 0 (400)
      - 23503 foreign_key_violation   -> არასწორი shop_id (400)

    production-ში ბაზის ნედლი ტექსტი კლიენტს არ უბრუნდება (schema არ ჟონავს) —
    მხოლოდ ლოგში იწერება.
    """
    try:
        return query.execute()
    except APIError as e:
        code = getattr(e, "code", None)
        message = getattr(e, "message", None) or str(e)
        if code == "42501":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="წვდომა აკრძალულია: ეს რესურსი თქვენი არ არის (RLS)",
            )
        # ვალიდაციის დარღვევები — უსაფრთხოა შეტყობინების ჩვენება (price<0, დუბლიკატი და ა.შ.)
        if code in ("23514", "23503", "23505"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)
        # სხვა ყველაფერი: production-ში ზოგადი ტექსტი, dev-ში დეტალი
        logger.warning("DB APIError code=%s: %s", code, message)
        if get_settings().is_production:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="მოთხოვნის დამუშავება ვერ მოხერხდა"
            )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)


def fetch_all(
    make_query,
    *,
    max_rows: int,
    label: str,
    strict: bool = False,
    execute=None,
    page_size: int = PAGE_SIZE,
) -> list[dict]:
    """სრული სია Supabase-ის 1000-მწკრივიანი ჭერის გვერდის (`range`) გავლით (A-041).

    `make_query()` ყოველ გვერდზე **ახალ** builder-ს აბრუნებს: postgrest-py-ის `range()`
    `offset`/`limit`-ს builder-ს ამატებს, ამიტომ ერთი builder-ის ხელახლა გამოყენება query-ს აფუჭებს.
    გამომძახებლის `order` **unique სვეტით** უნდა მთავრდებოდეს (მაგ. `.order("id")`), თორემ
    გვერდები ერთმანეთს გადაფარავს ან მწკრივს გამოტოვებს.

    `max_rows`-ზე მეტი: `strict` → `TooManyRows`; სხვაგვარად WARNING (მხოლოდ label და რიცხვი)
    და პირველი `max_rows` მწკრივი. `execute=run` — API-ის გამომძახებლები HTTP შეცდომებს ინარჩუნებენ.
    """
    if max_rows < 1 or page_size < 1:
        raise ValueError("max_rows and page_size must be >= 1")
    run_query = execute or (lambda q: q.execute())
    out: list[dict] = []
    offset = 0
    while True:
        # ერთი მწკრივით მეტს ვითხოვთ ჭერზე, რომ გადაჭარბება გამოჩნდეს (და არა ზუსტად max_rows)
        end = min(offset + page_size, max_rows + 1) - 1
        res = run_query(make_query().range(offset, end))
        page = res.data or []
        out.extend(page)
        if len(page) < end - offset + 1 or len(out) > max_rows:
            break
        offset += len(page)
    if len(out) > max_rows:
        if strict:
            raise TooManyRows(label, max_rows)
        logger.warning("fetch_all %s: more than %d rows - result truncated", label, max_rows)
        out = out[:max_rows]
    return out
