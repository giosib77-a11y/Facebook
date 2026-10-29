"""PDF-დან ტექსტის ამოღება (pypdf). მხოლოდ ტექსტური PDF — დასკანერებული/ფოტო არა."""
import io
from itertools import islice

from pypdf import PdfReader

# Stage 17: prompt-ში FAQ ან პირველი 20000 სიმბოლო მიდის (prompt.py); სრული ტექსტი მხოლოდ
# search_knowledge-ით იძებნება და upload-ზე ერთხელ იკუმშება FAQ-დ. 50K FAQ-ის მოთხოვნას
# 100K ტოკენზე ქვემოთ ტოვებს.
MAX_CHARS = 50_000
# ⚠️ რევიუ P2-12: გვერდების ჭერი. ზომა (10MB) საკმარისი დაცვა არ არის —
# სპეციალურად აწყობილი PDF ათასობით გვერდად იშლება და extract_text()-ი
# CPU/მეხსიერებას ამოწურავს. ტექსტი ისედაც MAX_CHARS-ზე იჭრება.
MAX_PAGES = 300


def extract_pdf_text(content: bytes) -> str:
    """აბრუნებს PDF-ის ტექსტს (გასუფთავებულს, MAX_CHARS-მდე)."""
    try:
        reader = PdfReader(io.BytesIO(content))
    except Exception:
        raise ValueError("PDF ფაილის წაკითხვა ვერ მოხერხდა — დარწმუნდი, რომ სწორი PDF-ია.")

    parts = []
    total = 0  # len("\n\n".join(parts)) — to stop once MAX_CHARS is exceeded
    for page in islice(reader.pages, MAX_PAGES):
        try:
            txt = page.extract_text() or ""
        except Exception:
            txt = ""
        if txt.strip():
            parts.append(txt.strip())
            total += len(parts[-1]) + (2 if len(parts) > 1 else 0)
            if total > MAX_CHARS:
                break  # the rest would be cut off anyway

    text = "\n\n".join(parts).strip()
    if not text:
        raise ValueError(
            "PDF-დან ტექსტი ვერ ამოვიღე — სავარაუდოდ დასკანერებული/ფოტო-PDF-ია (ტექსტი არ შეიცავს)."
        )
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS] + "\n…(შემოკლებულია)"
    return text
