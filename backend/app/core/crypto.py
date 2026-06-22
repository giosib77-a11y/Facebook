"""page token-ის დაშიფვრა/გაშიფვრა (Fernet).

FB_TOKEN_ENCRYPTION_KEY .env-ში — Fernet key. დასაგენერირებლად:
  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""
from cryptography.fernet import Fernet

from app.config import get_settings


def _fernet() -> Fernet:
    key = get_settings().fb_token_encryption_key
    if not key:
        raise RuntimeError("FB_TOKEN_ENCRYPTION_KEY არ არის კონფიგურირებული .env-ში")
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    return _fernet().decrypt(ciphertext.encode()).decode()
