"""Shops endpoints — გამყიდველის მაღაზიები."""
from fastapi import APIRouter, Depends, HTTPException, status

from app.core.db import run
from app.core.security import CurrentAuth, get_current_auth
from app.models.shop import ShopCreate, ShopOut

router = APIRouter(prefix="/shops", tags=["shops"])


@router.post("", response_model=ShopOut, status_code=status.HTTP_201_CREATED)
def create_shop(payload: ShopCreate, auth: CurrentAuth = Depends(get_current_auth)):
    """ქმნის მაღაზიას მიმდინარე მომხმარებლის სახელზე.

    owner_id ავტომატურად ისმება auth.uid()-ით; RLS insert პოლისი ამოწმებს, რომ
    owner_id == ავტორიზებული მომხმარებელი.
    """
    data = payload.model_dump(mode="json")
    data["owner_id"] = auth.user_id
    res = run(auth.client.table("shops").insert(data))
    if not res.data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "მაღაზიის შექმნა ვერ მოხერხდა")
    return res.data[0]


@router.get("/me", response_model=list[ShopOut])
def my_shops(auth: CurrentAuth = Depends(get_current_auth)):
    """აბრუნებს მიმდინარე მომხმარებლის მაღაზიებს (RLS ისედაც მხოლოდ მათ აჩვენებს)."""
    res = run(
        auth.client.table("shops")
        .select("*")
        .eq("owner_id", auth.user_id)
        .order("created_at")
    )
    return res.data
