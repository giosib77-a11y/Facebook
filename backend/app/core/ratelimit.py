"""მარტივი, დამოკიდებულების გარეშე rate limiter — საჯარო endpoint-ების დასაცავად.

In-memory, per-IP sliding window. ერთი პროცესისთვის (ერთი instance) საკმარისია
გაშვების ეტაპზე. მრავალ-instance-ზე გადასვლისას → Redis/Cloudflare level.

გამოყენება:
    from app.core.ratelimit import rate_limit
    @router.post("/orders", dependencies=[Depends(rate_limit("orders", limit=20, window=60))])
"""
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status

# bucket -> (ip -> deque[timestamps])
_HITS: dict[str, dict[str, deque]] = defaultdict(lambda: defaultdict(deque))
# პერიოდული გაწმენდის მრიცხველი (მეხსიერება არ გაიბეროს)
_last_sweep = [time.monotonic()]


def _client_ip(request: Request) -> str:
    """რეალური IP — reverse proxy-ს (Render/Railway/Cloudflare) გავითვალისწინებთ."""
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
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
