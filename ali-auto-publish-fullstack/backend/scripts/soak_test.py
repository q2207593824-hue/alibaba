# -*- coding: utf-8 -*-
"""
Soak / stability test for Ali Auto Publish backend.

Goals:
- Exercise key endpoints with concurrency
- Catch timeouts, 4xx/5xx, slow responses
- Produce a JSON report for later comparison

Usage:
  .\venv\Scripts\python.exe .\scripts\soak_test.py
  .\venv\Scripts\python.exe .\scripts\soak_test.py --seconds 180 --workers 8
"""

from __future__ import annotations

import argparse
import json
import random
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, asdict, field
from typing import Any, Dict, List, Optional, Tuple


DEFAULT_BASE = "http://127.0.0.1:8000"
DEFAULT_ADMIN_KEY = "change-me-admin"


@dataclass
class Stat:
    name: str
    method: str
    path: str
    ok: int = 0
    fail: int = 0
    timeout: int = 0
    min_ms: Optional[int] = None
    max_ms: Optional[int] = None
    total_ms: int = 0
    last_error: str = ""
    last_status: int = 0

    def add(self, ok: bool, elapsed_ms: int, status: int, err: str = "", is_timeout: bool = False):
        if ok:
            self.ok += 1
        else:
            self.fail += 1
        if is_timeout:
            self.timeout += 1
        self.last_status = int(status or 0)
        if err:
            self.last_error = err[:500]
        self.total_ms += int(elapsed_ms or 0)
        if self.min_ms is None or elapsed_ms < self.min_ms:
            self.min_ms = elapsed_ms
        if self.max_ms is None or elapsed_ms > self.max_ms:
            self.max_ms = elapsed_ms

    @property
    def count(self) -> int:
        return self.ok + self.fail

    @property
    def avg_ms(self) -> int:
        return int(self.total_ms / self.count) if self.count else 0


def _encode_path(path: str) -> str:
    # Only encode query string; keep route path readable.
    if "?" not in path:
        return path
    p, qs = path.split("?", 1)
    return p + "?" + urllib.parse.urlencode(urllib.parse.parse_qsl(qs, keep_blank_values=True))


def http_json(
    base: str,
    method: str,
    path: str,
    *,
    admin_key: str,
    token: str = "",
    device_id: str,
    timeout_s: float,
    body: Any = None,
) -> Tuple[int, Any, int, str, bool]:
    """
    Returns: (status, parsed_json_or_text, elapsed_ms, err, is_timeout)
    """
    url = base.rstrip("/") + _encode_path(path)
    headers = {
        "Content-Type": "application/json",
        "X-Admin-Key": admin_key,
        "X-Client-Device-Id": device_id,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            try:
                return resp.status, json.loads(raw), elapsed_ms, "", False
            except Exception:
                return resp.status, raw[:300], elapsed_ms, "", False
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        try:
            payload = json.loads(raw)
        except Exception:
            payload = raw[:300]
        return int(e.code), payload, elapsed_ms, "HTTPError", False
    except TimeoutError:
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        return 0, None, elapsed_ms, "TimeoutError", True
    except Exception as e:
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        return 0, None, elapsed_ms, f"{type(e).__name__}: {e}", False


def should_ok(status: int) -> bool:
    return 200 <= int(status or 0) < 400


def should_ok_or_empty(status: int, payload: Any) -> bool:
    # Some endpoints intentionally return empty structures when data files missing.
    if 200 <= int(status or 0) < 400:
        return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=DEFAULT_BASE)
    ap.add_argument("--admin-key", default=DEFAULT_ADMIN_KEY)
    ap.add_argument("--seconds", type=int, default=180)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--timeout", type=float, default=8.0)
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()

    random.seed(args.seed)
    base = str(args.base).strip()
    admin_key = str(args.admin_key).strip()
    seconds = max(10, int(args.seconds))
    workers = max(1, int(args.workers))
    timeout_s = max(1.0, float(args.timeout))
    device_id = f"soak-{int(time.time())}"

    # Endpoints list: include non-destructive CRUD-ish checks.
    targets: List[Tuple[str, str, str]] = [
        ("config.revision", "GET", "/api/config/revision"),
        ("config.get", "GET", "/api/config/"),
        ("upload.status", "GET", "/api/upload/status"),
        ("upload.available", "GET", "/api/upload/products/available"),
        ("analysis.overview", "GET", "/api/analysis/overview"),
        ("analysis.new_links", "GET", "/api/analysis/new-links/monitor?sheet_name=全店曝光次数"),
        ("data.status", "GET", "/api/data/download/status"),
        ("images.stats", "GET", "/api/images/stats"),
        ("video.status", "GET", "/api/video-bind/status"),
        ("video.preview", "GET", "/api/video-bind/new-links-preview"),
        ("tasks.list", "GET", "/api/tasks/list"),
        ("member.users", "GET", "/api/membership/admin/users?limit=20"),
        ("member.dashboard", "GET", "/api/membership/admin/dashboard?days=30"),
        # Idempotent delete with empty payload (should be OK)
        ("member.telemetry.delete_empty", "POST", "/api/membership/admin/telemetry/keywords/batch/delete"),
    ]

    stats: Dict[str, Stat] = {name: Stat(name=name, method=m, path=p) for name, m, p in targets}
    lock = threading.Lock()
    stop = threading.Event()
    started_at = time.time()
    deadline = started_at + seconds

    def worker(idx: int):
        # slight staggering
        time.sleep(0.05 * idx)
        while not stop.is_set():
            if time.time() >= deadline:
                break
            name, method, path = random.choice(targets)
            body = None
            if name == "member.telemetry.delete_empty":
                body = {"report_ids": []}
            status, payload, elapsed_ms, err, is_timeout = http_json(
                base,
                method,
                path,
                admin_key=admin_key,
                token="",
                device_id=device_id,
                timeout_s=timeout_s,
                body=body,
            )
            ok = should_ok_or_empty(status, payload)
            with lock:
                stats[name].add(ok=ok, elapsed_ms=elapsed_ms, status=status, err=err, is_timeout=is_timeout)
            # tiny think time to avoid pure hot-loop
            time.sleep(0.02)

    threads = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(workers)]
    for t in threads:
        t.start()

    try:
        while time.time() < deadline:
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        for t in threads:
            t.join(timeout=2.0)

    ended_at = time.time()
    by_fail = sorted(stats.values(), key=lambda s: (s.fail, s.timeout, s.avg_ms), reverse=True)

    report = {
        "base": base,
        "seconds": seconds,
        "workers": workers,
        "timeout_s": timeout_s,
        "started_at": int(started_at),
        "ended_at": int(ended_at),
        "duration_s": round(ended_at - started_at, 2),
        "stats": [
            {
                **asdict(s),
                "count": s.count,
                "avg_ms": s.avg_ms,
            }
            for s in by_fail
        ],
    }

    out_path = "scripts/soak_test_report.json"
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
    except Exception:
        traceback.print_exc()

    print("=== Soak Test Summary ===")
    total_ok = sum(s.ok for s in stats.values())
    total_fail = sum(s.fail for s in stats.values())
    total_timeout = sum(s.timeout for s in stats.values())
    print(f"total_ok={total_ok} total_fail={total_fail} total_timeout={total_timeout} report={out_path}")
    print("worst 8 endpoints:")
    for s in by_fail[:8]:
        print(f"- {s.name}: ok={s.ok} fail={s.fail} timeout={s.timeout} avg={s.avg_ms}ms max={s.max_ms}ms last={s.last_status} {s.last_error}")

    # return non-zero if any failure/timeout occurred
    return 0 if (total_fail == 0 and total_timeout == 0) else 2


if __name__ == "__main__":
    raise SystemExit(main())

