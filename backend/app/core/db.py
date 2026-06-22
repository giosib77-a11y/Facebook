"""PostgREST მოთხოვნების შესრულების helper — შეცდომების HTTP-ში გადათარგმნა."""
from fastapi import HTTPException, status
from postgrest.exceptions import APIError


def run(query):
    """ასრულებს supabase query-ს და APIError-ს HTTP შეცდომად აქცევს.

    მთავარი შემთხვევები:
      - 42501 insufficient_privilege  -> RLS-მა აკრძალა (403)
      - 23514 check_violation         -> ვალიდაციის დარღვევა, მაგ. price < 0 (400)
      - 23503 foreign_key_violation   -> არასწორი shop_id (400)
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
        if code in ("23514", "23503", "23505"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)
