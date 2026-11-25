"""Run one AIS connection and a bounded, read-only HTTP API."""
import asyncio
from collections import defaultdict, deque
import json
import logging
import math
import os
from pathlib import Path
import random
import re
import signal
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from .model import normalize, utc, POSITION_TYPES, STATIC_TYPES
from .store import Store

ROOT = Path(__file__).resolve().parents[1]
LOG = logging.getLogger("harbournow")


def load_config(path):
    config = json.loads(Path(path).read_text())
    for key, low, high in [("retention_days", 1, 90), ("stale_seconds", 60, 86400), ("transition_gap_seconds", 60, 3600), ("track_interval_seconds", 10, 3600)]:
        value = config.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise ValueError(f"Invalid {key}")
    harbours = config.get("harbours")
    if not isinstance(harbours, list) or not 1 <= len(harbours) <= 20:
        raise ValueError("Configure between 1 and 20 harbours")
    ids = set()
    for harbour in harbours:
        if not re.fullmatch(r"[a-z0-9-]{1,40}", harbour.get("id", "")) or harbour["id"] in ids:
            raise ValueError("Harbour IDs must be unique slugs")
        ids.add(harbour["id"])
        for field in ["center", "subscription_bbox", "boundary", "anchorage"]:
            points = [harbour[field]] if field == "center" else harbour[field]
            if not points or len(points) > 200:
                raise ValueError("Invalid map geometry")
            for point in points:
                if not isinstance(point, list) or len(point) != 2 or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in point) or not -85 <= point[0] <= 85 or not -180 <= point[1] <= 180:
                    raise ValueError("Invalid map coordinates")
        if len(harbour["subscription_bbox"]) != 2 or len(harbour["boundary"]) < 3 or len(harbour["anchorage"]) < 3:
            raise ValueError("Invalid bounding box or polygon")
        if not isinstance(harbour.get("zoom"), int) or isinstance(harbour["zoom"], bool) or not 9 <= harbour["zoom"] <= 16:
            raise ValueError("Map zoom must be 9–16")
        if not isinstance(harbour.get("name"), str) or not 1 <= len(harbour["name"]) <= 100:
            raise ValueError("Harbour needs a short name")
        try:
            ZoneInfo(harbour.get("timezone", ""))
        except (ZoneInfoNotFoundError, ValueError, TypeError):
            raise ValueError("Use a valid IANA harbour timezone") from None
    return config


class BoundedHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 32

    def __init__(self, *args, **kwargs):
        self.slots = threading.BoundedSemaphore(24)
        super().__init__(*args, **kwargs)

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(15)
        return connection, address

    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            try:
                request.sendall(b"HTTP/1.0 503 Service Unavailable\r\nContent-Length: 0\r\nRetry-After: 10\r\n\r\n")
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()


async def maintenance(store, stop):
    while not stop.is_set():
        store.prune(time.time())
        try:
            await asyncio.wait_for(stop.wait(), timeout=300)
        except asyncio.TimeoutError:
            pass


async def collect(store, key, stop):
    from websockets.asyncio.client import connect
    backoff = 2
    while not stop.is_set():
        try:
            store.meta("connection", {"state": "connecting", "at": time.time()})
            async with connect("wss://stream.aisstream.io/v0/stream", compression="deflate", max_size=262144, max_queue=16, open_timeout=20, ping_interval=20, ping_timeout=30, close_timeout=5) as socket:
                await socket.send(json.dumps({"APIKey": key, "BoundingBoxes": [h["subscription_bbox"] for h in store.config["harbours"]], "FilterMessageTypes": sorted(POSITION_TYPES | STATIC_TYPES)}))
                connected_at = time.time()
                store.meta("connection", {"state": "connected", "at": connected_at, "compression_confirmed": False})
                messages = 0
                last_health = 0
                async for payload in socket:
                    if stop.is_set():
                        return
                    now = time.time()
                    try:
                        envelope = json.loads(payload)
                    except (ValueError, UnicodeDecodeError):
                        continue
                    if not isinstance(envelope, dict):
                        continue
                    if "error" in envelope or "Error" in envelope:
                        # Provider errors may include subscription details: never log payloads.
                        raise RuntimeError("Provider rejected the subscription")
                    if envelope.get("MessageType") == "SubscriptionConfirmation":
                        body = envelope.get("Message", {}).get("SubscriptionConfirmation", {})
                        if not body.get("CompressionEnabled"):
                            raise RuntimeError("Compressed subscription was not confirmed")
                        store.meta("connection", {"state": "connected", "at": connected_at, "compression_confirmed": True})
                        continue
                    observation = normalize(envelope, now)
                    if observation and store.ingest(observation):
                        messages += 1
                        if now-last_health >= 15:
                            store.meta("last_observation_at", now)
                            store.meta("session_observations", messages)
                            last_health = now
                    if now-connected_at > 60:
                        backoff = 2
            if not stop.is_set():
                raise ConnectionError("Stream ended")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Never log the request, raw exception text, key, or response payload.
            LOG.warning("AIS connection interrupted (%s); reconnecting", type(exc).__name__)
            store.meta("connection", {"state": "reconnecting", "at": time.time(), "reason": "The upstream stream was interrupted. Observations may be incomplete."})
            await asyncio.sleep(backoff+random.uniform(0, backoff/3))
            backoff = min(120, backoff*2)


def handler_factory(store, origins, web_root):
    buckets = defaultdict(deque)
    bucket_lock = threading.Lock()
    ids = {h["id"] for h in store.config["harbours"]}

    class Handler(BaseHTTPRequestHandler):
        server_version = "HarbourNow"
        sys_version = ""

        def log_message(self, format, *args):
            # Do not log arbitrary query strings or attacker-controlled headers.
            LOG.info("HTTP %s", getattr(self, "response_code", "request"))

        def _headers(self, code, kind, length, cache="no-store"):
            self.response_code = code
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(length))
            self.send_header("Cache-Control", cache)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
            self.send_header("Vary", "Origin")
            origin = self.headers.get("Origin")
            if origin in origins:
                self.send_header("Access-Control-Allow-Origin", origin)
            self.end_headers()

        def _json(self, code, value, cache="no-store"):
            data = json.dumps(value, allow_nan=False, separators=(",", ":")).encode()
            self._headers(code, "application/json; charset=utf-8", len(data), cache)
            if self.command != "HEAD":
                self.wfile.write(data)

        def do_HEAD(self):
            self.do_GET()

        def do_OPTIONS(self):
            origin = self.headers.get("Origin")
            if origin not in origins:
                return self._json(403, {"error": "Origin is not permitted"})
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS")
            self.send_header("Access-Control-Max-Age", "600")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_GET(self):
            now = time.time()
            if len(self.path) > 2048:
                return self._json(414, {"error": "URL is too long"})
            with bucket_lock:
                address = self.client_address[0]
                if address not in buckets and len(buckets) > 10000:
                    buckets.clear()
                queue = buckets[address]
                while queue and queue[0] < now-60:
                    queue.popleft()
                if len(queue) >= 600:
                    return self._json(429, {"error": "Please wait before requesting again"})
                queue.append(now)
            parsed = urlsplit(self.path)
            if not parsed.path.startswith("/api/"):
                return self._static(parsed.path)
            if self.headers.get("Origin") and self.headers["Origin"] not in origins:
                return self._json(403, {"error": "Origin is not permitted"})
            try:
                query = parse_qs(parsed.query, max_num_fields=8, keep_blank_values=True)
                if any(len(v) != 1 for v in query.values()):
                    raise ValueError("Repeated query parameter")
                harbour = query.get("harbour", [store.config["harbours"][0]["id"]])[0]
                if harbour not in ids:
                    raise ValueError("Unknown harbour")
                base = {"generated_at": utc(now), "source": "AISStream", "retention_days": store.config["retention_days"], "stale_seconds": store.config["stale_seconds"]}
                if parsed.path == "/api/v1/health":
                    meta = store.metadata()
                    connection = meta.get("connection", {"state": "starting"})
                    latest = meta.get("last_observation_at")
                    fresh = latest is not None and now-latest < store.config["stale_seconds"]
                    return self._json(200, {**base, "service": "ok", "feed": connection, "observations_fresh": fresh, "last_observation_at": utc(latest), "configured": meta.get("configured", False)})
                if parsed.path == "/api/v1/harbours":
                    return self._json(200, {**base, "harbours": store.config["harbours"]}, "public, max-age=300")
                if parsed.path == "/api/v1/ships":
                    return self._json(200, {**base, "harbour": harbour, "ships": store.snapshot(harbour, now)}, "public, max-age=15")
                if parsed.path == "/api/v1/events":
                    hours = int(query.get("hours", ["24"])[0])
                    if not 1 <= hours <= min(720, store.config["retention_days"]*24):
                        raise ValueError("hours must fit the configured retention period")
                    return self._json(200, {**base, "harbour": harbour, "hours": hours, "counts": store.counts(harbour, now-hours*3600), "events": store.events(harbour, now-hours*3600)}, "public, max-age=30")
                if parsed.path == "/api/v1/track":
                    mmsi = query.get("mmsi", [""])[0]
                    if not re.fullmatch(r"[1-9][0-9]{8}", mmsi):
                        raise ValueError("Use a nine-digit MMSI")
                    return self._json(200, {**base, "mmsi": mmsi, "track": store.track(mmsi, now-86400)}, "public, max-age=30")
                return self._json(404, {"error": "Unknown API route"})
            except (ValueError, KeyError):
                return self._json(400, {"error": "Invalid query parameters"})

        def _static(self, path):
            # An explicit generated-file allowlist excludes .env, database and source.
            path = "/index.html" if path == "/" else path
            if not re.fullmatch(r"/[a-zA-Z0-9_./-]+", path) or ".." in path or path.startswith("/."):
                return self._json(404, {"error": "Not found"})
            file = web_root / path.lstrip("/")
            if not file.is_file() or file.suffix not in {".html", ".css", ".js", ".mjs", ".json", ".svg", ".ico"} or web_root.resolve() not in file.resolve().parents:
                return self._json(404, {"error": "Not found"})
            kind = {".html": "text/html", ".css": "text/css", ".js": "text/javascript", ".mjs": "text/javascript", ".json": "application/json", ".svg": "image/svg+xml", ".ico": "image/x-icon"}[file.suffix]
            data = file.read_bytes()
            self._headers(200, kind+"; charset=utf-8", len(data), "public, max-age=300")
            if self.command != "HEAD":
                self.wfile.write(data)
    return Handler


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = load_config(os.getenv("HARBOUR_CONFIG", str(ROOT / "config/harbours.json")))
    db_path = Path(os.getenv("DATABASE_PATH", "/data/harbournow.sqlite"))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    store = Store(str(db_path), config)
    key = os.getenv("AISSTREAM_API_KEY", "").strip()
    store.meta("configured", bool(key))
    origins = {x.strip().rstrip("/") for x in os.getenv("ALLOWED_ORIGINS", "https://coolcode.ca,https://jsdyer.github.io").split(",") if x.strip()}
    server = BoundedHTTPServer((os.getenv("BIND_HOST", "127.0.0.1"), int(os.getenv("PORT", "8090"))), handler_factory(store, origins, ROOT / "dist"))
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    LOG.info("Harbour Now HTTP service started")
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    task = asyncio.create_task(collect(store, key, stop)) if key else None
    cleanup = asyncio.create_task(maintenance(store, stop))
    if not key:
        store.meta("connection", {"state": "not_configured", "at": time.time()})
        LOG.warning("AISSTREAM_API_KEY is not configured; serving explicit offline state")
    await stop.wait()
    await cleanup
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    store.meta("connection", {"state": "stopped", "at": time.time()})
    server.shutdown()
    server.server_close()


if __name__ == "__main__":
    asyncio.run(main())
