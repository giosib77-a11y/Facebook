"""core/supabase_client — პროცესის საერთო Supabase კლიენტი თრედებს შორის უსაფრთხოა და timeout აქვს.

ლაივი (2026-11-06): `GET /admin/growth` → 500 `httpx.ReadError: [Errno 11] Resource temporarily
unavailable`, როცა იმავე წამში სხვა ადმინის მოთხოვნებიც მიდიოდა. მიზეზი: `get_service_client()`
(`lru_cache`) ყველა თრედს ერთ supabase-py კლიენტს აძლევს, რომლის httpx `http2=True`-ია — HTTP/2-ზე
ყველა თრედი ერთ TLS socket-ს იზიარებს (httpcore-ში recv და send სხვადასხვა lock-ითაა) → EAGAIN.

ტესტები ქსელს არ მიმართავს — მხოლოდ 127.0.0.1-ზე ამ ტესტის მიერ გაშვებულ სერვერს.
"""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import httpx
import pytest

from app.core import supabase_client

SECRET = "sb_secret_test_key"
PUBLISHABLE = "sb_publishable_test_key"


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"  # keep-alive: ერთ კავშირზე რამდენიმე მოთხოვნა

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        srv = self.server
        with srv.lock:
            srv.seen.append({
                "path": self.path,
                "apikey": self.headers.get("apikey"),
                "authorization": self.headers.get("Authorization"),
                "conn": id(self.connection),
            })
        if self.path.endswith("/rpc/slow"):
            time.sleep(2.0)
        # პატარა პაუზა — რამდენიმე თრედის მოთხოვნა ერთდროულად „ფრენაშია"
        time.sleep(0.005)
        out = json.dumps({"echo": body.get("n")}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *args):  # ტესტის გამოსავალში ხმაური არა
        pass


@pytest.fixture
def local_supabase(monkeypatch):
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.daemon_threads = True
    server.lock = threading.Lock()
    server.seen = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    monkeypatch.setattr(
        supabase_client,
        "get_settings",
        lambda: SimpleNamespace(supabase_url=url, supabase_secret_key=SECRET, supabase_publishable_key=PUBLISHABLE),
    )
    caches = [supabase_client.get_service_client, supabase_client.get_anon_client]
    if hasattr(supabase_client, "get_http_client"):
        caches.append(supabase_client.get_http_client)
    for fn in caches:
        fn.cache_clear()
    yield server
    if hasattr(supabase_client, "get_http_client"):
        supabase_client.get_http_client().close()
    for fn in caches:
        fn.cache_clear()
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def _pool_uses_http2(http_client: httpx.Client) -> bool:
    return http_client._transport._pool._http2  # httpx 0.28 / httpcore 1.0


def test_service_client_uses_one_shared_http1_client_with_timeout(local_supabase):
    """ძველ კოდზე ვარდება: supabase-py-ს საკუთარი httpx — `http2=True`, read timeout 120 წმ, ყოველ
    ქვე-კლიენტს (postgrest / storage / auth) — ცალკე."""
    sc = supabase_client.get_service_client()
    shared = supabase_client.get_http_client()

    assert sc.postgrest.session is shared
    assert sc.storage.session is shared
    assert sc.auth._http_client is shared
    assert _pool_uses_http2(shared) is False
    assert shared.timeout.read == 30.0
    assert shared.timeout.connect == 5.0
    assert shared.timeout.pool == 10.0


def test_anon_client_shares_the_same_http_client(local_supabase):
    anon = supabase_client.get_anon_client()
    assert anon.postgrest.session is supabase_client.get_http_client()
    # საერთო httpx-ში key-ები არ ინახება — თითო კლიენტი თავისას თავად ატანს
    assert "apikey" not in supabase_client.get_http_client().headers


def test_parallel_rpc_from_many_threads_on_one_shared_client(local_supabase):
    """ლაივის სცენარი: ბევრი თრედი ერთდროულად ერთ service client-ზე — ყველა მოთხოვნა სრულდება,
    თითო თრედი საკუთარ პასუხს იღებს (კავშირი თრედებს შორის არ ერევა) და key-ები ყოველ მოთხოვნას აქვს
    (საერთო httpx-ს header-ები არ აქვს — supabase-py თითო მოთხოვნას თავად ატანს).

    რეგრესიის დაცვაა და არა თვით ავარიის გამეორება: EAGAIN-ს HTTP/2 + TLS სჭირდება (ერთი SSL socket
    ბევრ თრედზე), აქ კი სერვერი plain HTTP/1.1-ია — ამიტომ ძველ კოდზეც გადის. ავარია ლოკალურ TLS + h2
    სერვერზე გამეორდა ცალკე (24 თრედი × 40 მოთხოვნა: `ReadError [WinError 10035]` / ReadTimeout
    HTTP/2-ზე, 0 შეცდომა HTTP/1.1-ზე) — არადეტერმინისტულია, ამიტომ CI-ში არ არის; ძველ კოდზე
    ვარდება `test_service_client_uses_one_shared_http1_client_with_timeout`."""
    sc = supabase_client.get_service_client()
    threads_n, per_thread = 16, 8
    results: dict[int, list] = {i: [] for i in range(threads_n)}
    errors: list[str] = []
    start = threading.Barrier(threads_n)

    def worker(i: int):
        start.wait()
        for j in range(per_thread):
            n = i * 1000 + j
            try:
                data = sc.rpc("admin_growth", {"n": n}).execute().data
                results[i].append((n, data))
            except Exception as exc:  # pragma: no cover - ჩავარდნისას ტესტი ქვემოთ აჩვენებს
                errors.append(f"{type(exc).__name__}: {exc}")

    ts = [threading.Thread(target=worker, args=(i,)) for i in range(threads_n)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(timeout=30)

    assert errors == []
    for i in range(threads_n):
        assert [d["echo"] for _, d in results[i]] == [n for n, _ in results[i]]
        assert len(results[i]) == per_thread
    seen = local_supabase.seen
    assert len(seen) == threads_n * per_thread
    assert all(s["path"] == "/rest/v1/rpc/admin_growth" for s in seen)
    assert all(s["apikey"] == SECRET and s["authorization"] == f"Bearer {SECRET}" for s in seen)
    # HTTP/1.1 pool: პარალელური თრედები ერთ კავშირზე არ „მულტიპლექსდება" — კავშირი ერთზე მეტია
    assert len({s["conn"] for s in seen}) > 1


def test_slow_response_hits_read_timeout(local_supabase, monkeypatch):
    """ძველ კოდზე ვარდება: timeout 120 წმ-ია, ამიტომ 2-წამიანი პასუხი უბრალოდ ბრუნდება."""
    monkeypatch.setattr(supabase_client, "HTTP_TIMEOUT", httpx.Timeout(0.3), raising=False)
    supabase_client.get_service_client.cache_clear()
    if hasattr(supabase_client, "get_http_client"):
        supabase_client.get_http_client.cache_clear()
    sc = supabase_client.get_service_client()

    t0 = time.monotonic()
    with pytest.raises(httpx.ReadTimeout):
        sc.rpc("slow", {}).execute()
    assert time.monotonic() - t0 < 1.5
