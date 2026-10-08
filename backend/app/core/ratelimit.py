"""მარტივი, დამოკიდებულების გარეშე rate limiter — საჯარო endpoint-ების დასაცავად.

In-memory, per-IP sliding window. ერთი პროცესისთვის (ერთი instance) საკმარისია
გაშვების ეტაპზე. მრავალ-instance-ზე გადასვლისას → Redis/Cloudflare level.

გამოყენება:
    from app.core.ratelimit import rate_limit
    @router.post("/orders", dependencies=[Depends(rate_limit("orders", limit=20, window=60))])
"""
import logging
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status

from app.config import get_settings

logger = logging.getLogger("app")

# bucket -> (ip -> deque[timestamps])
_HITS: dict[str, dict[str, deque]] = defaultdict(lambda: defaultdict(deque))
# პერიოდული გაწმენდის მრიცხველი (მეხსიერება არ გაიბეროს)
_last_sweep = [time.monotonic()]
# გაფრთხილება „header აკლია" — პროცესზე მაქსიმუმ ერთხელ
_warned_missing_header = [False]
# CLIENT_IP_DEBUG ლოგის throttle (monotonic დრო; -inf = ჯერ არ დაწერილა)
_last_debug_log = [float("-inf")]
# bucket -> window (წმ). sweep-მა ყოველ bucket-ს თავისი window უნდა გამოიყენოს,
# თორემ მოკლე window-ის მქონე endpoint-ი გრძელი (მაგ. დღიური) ლიმიტის ჩანაწერებს წაშლიდა.
_WINDOWS: dict[str, int] = {}


def _client_ip(request: Request) -> str:
    """რეალური IP — X-Forwarded-For-ის მარჯვნიდან N-ური ჩანაწერი (CLIENT_IP_TRUSTED_HOPS).

    Render ამატებს ჩანაწერებს მარჯვნივ და კლიენტის მიწოდებულს არ ასუფთავებს, ამიტომ მარცხენა
    ჩანაწერები გაყალბებადია; მხოლოდ მარჯვენა (proxy-ს დამატებული) სანდოა. CF-Connecting-IP
    და სხვა კლიენტის header-ები არ იკითხება. ჩანაწერები არ ჰყოფნის → socket peer.
    """
    settings = get_settings()
    peer = request.client.host if request.client else "unknown"
    raw = request.headers.get("x-forwarded-for") or ""
    entries = [e.strip() for e in raw.split(",") if e.strip()]
    hops = max(settings.client_ip_trusted_hops, 1)

    if len(entries) >= hops:
        chosen = entries[-hops]
    else:
        chosen = peer
        if settings.is_production and not _warned_missing_header[0]:
            _warned_missing_header[0] = True
            logger.warning(
                "rate limit: X-Forwarded-For has %d entries, CLIENT_IP_TRUSTED_HOPS=%d — "
                "falling back to peer address; all clients may share one limit bucket",
                len(entries), hops,
            )

    if settings.client_ip_debug:
        now = time.monotonic()
        if now - _last_debug_log[0] >= 10:
            _last_debug_log[0] = now
            logger.info(
                "client-ip debug: xff=%r entries=%d peer=%s hops=%d chosen=%s",
                raw[:300], len(entries), peer, hops, chosen,
            )
    return chosen


def _sweep(now: float) -> None:
    """ძველი ჩანაწერების პერიოდული გაწმენდა — ~5 წუთში ერთხელ."""
    if now - _last_sweep[0] < 300:
        return
    _last_sweep[0] = now
    for bucket in list(_HITS.keys()):
        ips = _HITS[bucket]
        window = _WINDOWS.get(bucket, 0)
        for ip in list(ips.keys()):
            dq = ips[ip]
            while dq and now - dq[0] > window:
                dq.popleft()
            if not dq:
                del ips[ip]
        if not ips:
            del _HITS[bucket]


def register_window(bucket: str, window: int) -> None:
    """bucket-ის window-ის რეგისტრაცია — sweep-მა გრძელი (მაგ. დღიური) ჩანაწერები არ წაშალოს."""
    _WINDOWS[bucket] = max(_WINDOWS.get(bucket, 0), window)


def _hit(bucket: str, key: str, limit: int, window: int) -> None:
    """ერთი მოთხოვნის აღრიცხვა; ლიმიტის გადაცილებაზე → HTTP 429 + Retry-After."""
    now = time.monotonic()
    _sweep(now)
    dq = _HITS[bucket][key]
    while dq and now - dq[0] > window:
        dq.popleft()
    if len(dq) >= limit:
        retry = int(window - (now - dq[0])) + 1
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="ბევრი მოთხოვნა მოვიდა — სცადეთ ცოტა ხანში.",
            headers={"Retry-After": str(max(retry, 1))},
        )
    dq.append(now)


def rate_limit(bucket: str, limit: int, window: int = 60):
    """FastAPI dependency-ს აბრუნებს: `limit` მოთხოვნა `window` წამში, თითო IP-ზე.

    ლიმიტის გადაცილებაზე → HTTP 429.
    """
    register_window(bucket, window)

    def _dep(request: Request) -> None:
        _hit(bucket, _client_ip(request), limit, window)

    return _dep


def check_rate_limit(request: Request, bucket: str, key_suffix: str, limit: int, window: int) -> None:
    """იგივე ლიმიტი, ოღონდ key = `ip|key_suffix` — handler-იდან გამოსაძახებლად, როცა
    key-ის ნაწილი (მაგ. shop_id) მხოლოდ request body-შია. `bucket`-ის window უნდა იყოს
    რეგისტრირებული (`register_window`) import-ზე."""
    _hit(bucket, f"{_client_ip(request)}|{key_suffix}", limit, window)
