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


def _client_ip(request: Request) -> str:
    """რეალური IP — proxy-ს სანდო header-იდან (CLIENT_IP_HEADER), თორემ socket peer.

    X-Forwarded-For-ის პირველი ელემენტი კლიენტის კონტროლშია, ამიტომ არ იკითხება.
    The header is trustworthy only when the origin lock (ORIGIN_SECRET) is active.
    """
    settings = get_settings()
    header = (settings.client_ip_header or "").strip()
    if header:
        value = (request.headers.get(header) or "").split(",")[0].strip()
        if value:
            return value
        if settings.is_production and not _warned_missing_header[0]:
            _warned_missing_header[0] = True
            logger.warning(
                "rate limit: header %r missing — falling back to peer address; "
                "all clients may share one limit bucket", header,
            )
    return request.client.host if request.client else "unknown"


def _sweep(now: float, window: float) -> None:
    """ძველი ჩანაწერების პერიოდული გაწმენდა — ~5 წუთში ერთხელ."""
    if now - _last_sweep[0] < 300:
        return
    _last_sweep[0] = now
    for bucket in list(_HITS.keys()):
        ips = _HITS[bucket]
        for ip in list(ips.keys()):
            dq = ips[ip]
            while dq and now - dq[0] > window:
                dq.popleft()
            if not dq:
                del ips[ip]
        if not ips:
            del _HITS[bucket]


def rate_limit(bucket: str, limit: int, window: int = 60):
    """FastAPI dependency-ს აბრუნებს: `limit` მოთხოვნა `window` წამში, თითო IP-ზე.

    ლიმიტის გადაცილებაზე → HTTP 429.
    """
    def _dep(request: Request) -> None:
        now = time.monotonic()
        _sweep(now, window)
        dq = _HITS[bucket][_client_ip(request)]
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

    return _dep
