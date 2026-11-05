"""page token-ის დაშიფვრა/გაშიფვრა (Fernet).

FB_TOKEN_ENCRYPTION_KEY .env-ში — Fernet key. დასაგენერირებლად:
  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.config import get_settings

# A-047: ცალკე გასაღები თითო დანიშნულებაზე (HKDF). raw FB_APP_SECRET რჩება მხოლოდ იქ,
# სადაც Meta-ს ფორმულა მას მოითხოვს (appsecret_proof, X-Hub-Signature-256, signed_request).
KEY_OAUTH_STATE = "oauth-state:v1"
KEY_DELETION_CODE = "deletion-code:v1"


def derive_key(label: str, secret: str | None = None) -> bytes:
    """32-ბაიტიანი გასაღები FB_APP_SECRET-იდან (HKDF-SHA256, info = chatassist:<label>).

    `secret` ცხადად გადაეცემა იქ, სადაც caller-ს თავისი settings აქვს; ცარიელი — fail closed.
    """
    if secret is None:
        secret = get_settings().fb_app_secret
    if not secret:
        raise RuntimeError("FB_APP_SECRET is not configured")
    return HKDF(
        algorithm=hashes.SHA256(), length=32, salt=None, info=b"chatassist:" + label.encode()
    ).derive(secret.encode())


def _fernet() -> Fernet:
    key = get_settings().fb_token_encryption_key
    if not key:
        raise RuntimeError("FB_TOKEN_ENCRYPTION_KEY არ არის კონფიგურირებული .env-ში")
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    return _fernet().decrypt(ciphertext.encode()).decode()
