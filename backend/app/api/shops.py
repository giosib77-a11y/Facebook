"""Shops endpoints — გამყიდველის მაღაზიები."""
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.core.db import run
from app.core.security import CurrentAuth, get_current_auth
from app.models.shop import ShopCreate, ShopOut
from app.services.pdf_extract import extract_pdf_text

router = APIRouter(prefix="/shops", tags=["shops"])

MAX_PDF_BYTES = 10 * 1024 * 1024  # 10MB


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


@router.post("/{shop_id}/knowledge", response_model=ShopOut)
async def upload_knowledge(
    shop_id: uuid.UUID,
    file: UploadFile = File(...),
    auth: CurrentAuth = Depends(get_current_auth),
):
    """ტვირთავ PDF-ს → ტექსტი ამოდის და ინახ ება მაღაზიის ცოდნად (ბოტი იყენებს)."""
    name = (file.filename or "").lower()
    if not name.endswith(".pdf"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "მხ ოლოდ .pdf ფაილია მხ არდაჭერილი")
    content = await file.read()
    if not content:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "ფაილი ცარიელია")
    if len(content) > MAX_PDF_BYTES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "ფაილი ძალიან დიდია (მაქს. 10MB)")

    try:
        text = extract_pdf_text(content)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))

    res = run(
        auth.client.table("shops")
        .update({"knowledge": text, "knowledge_filename": file.filename})
        .eq("id", str(shop_id))
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "მაღაზია ვერ მოიძებნა ან არ არის თქვენი")
    return res.data[0]


@router.delete("/{shop_id}/knowledge", response_model=ShopOut)
def clear_knowledge(shop_id: uuid.UUID, auth: CurrentAuth = Depends(get_current_auth)):
    """შლის მაღაზიის ცოდნას (PDF-ინფოს)."""
    res = run(
        auth.client.table("shops")
        .update({"knowledge": None, "knowledge_filename": None})
        .eq("id", str(shop_id))
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "მაღაზია ვერ მოიძებნა ან არ არის თქვენი")
    return res.data[0]
