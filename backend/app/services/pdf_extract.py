"""PDF-დან ტექსტის ამოღება (pypdf). მხ ოლოდ ტექსტური PDF — დასკანერებული/ფოტო არა."""
import io

from pypdf import PdfReader

MAX_CHARS = 20000  # ბოტის prompt-ის დასაცავად ვზღუდავთ


def extract_pdf_text(content: bytes) -> str:
    """აბრუნებს PDF-ის ტექსტს (გასუფთავებულს, MAX_CHARS-მდე)."""
    try:
        reader = PdfReader(io.BytesIO(content))
    except Exception:
        raise ValueError("PDF ფაილის წაკითხვა ვერ მოხერხდა — დარწმუნდი, რომ სწორი PDF-ია.")

    parts = []
    for page in reader.pages:
        try:
            txt = page.extract_text() or ""
        except Exception:
            txt = ""
        if txt.strip():
            parts.append(txt.strip())

    text = "\n\n".join(parts).strip()
    if not text:
        raise ValueError(
            "PDF-დან ტექსტი ვერ ამოვიღე — სავარაუდოდ დასკანერებული/ფოტო-PDF-ია (ტექსტი არ შეიცავს)."
        )
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS] + "\n…(შემოკლებულია)"
    return text
