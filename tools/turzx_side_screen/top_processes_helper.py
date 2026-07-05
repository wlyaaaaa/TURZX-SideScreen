from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import time
from typing import Any

import metrics_agent


DEFAULT_INTERVAL_SECONDS = 3.0
MIN_LOOP_SLEEP_SECONDS = 0.2
SCHEMA_VERSION = 1
_PROCESS_SAMPLER = metrics_agent.ProcessActivitySampler()


def default_cache_path() -> Path:
    return Path(__file__).resolve().parent / "out" / "top-processes.json"


def collect_top_processes(limit: int = 5) -> list[dict[str, Any]]:
    psutil_processes = _PROCESS_SAMPLER.sample(limit)
    processes = psutil_processes if psutil_processes else metrics_agent._read_top_processes_tasklist(limit)
    normalized: list[dict[str, Any]] = []
    for process in processes[:limit]:
        item = dict(process)
        item["source"] = "top_processes_helper"
        normalized.append(item)
    return normalized


def write_cache_atomic(
    cache_path: str | os.PathLike[str],
    processes: list[dict[str, Any]],
    generated_at_unix_ms: int | None = None,
) -> None:
    target = Path(cache_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_unix_ms": int(generated_at_unix_ms if generated_at_unix_ms is not None else time.time() * 1000),
        "processes": processes,
    }
    temp = target.with_name(target.name + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(temp, target)


def _loop_sleep_seconds(started_monotonic: float, finished_monotonic: float, interval_seconds: float) -> float:
    elapsed_seconds = max(0.0, finished_monotonic - started_monotonic)
    return max(MIN_LOOP_SLEEP_SECONDS, interval_seconds - elapsed_seconds)


def run_loop(cache_path: Path, interval_seconds: float, limit: int) -> None:
    while True:
        started = time.monotonic()
        try:
            write_cache_atomic(cache_path, collect_top_processes(limit))
        except Exception:
            # Keep the side screen alive; the main agent will use the previous cache.
            pass
        time.sleep(_loop_sleep_seconds(started, time.monotonic(), max(interval_seconds, MIN_LOOP_SLEEP_SECONDS)))


def main() -> int:
    parser = argparse.ArgumentParser(description="Write TURZX top-process cache JSON.")
    parser.add_argument("--cache-path", default=str(default_cache_path()))
    parser.add_argument("--interval-seconds", type=float, default=DEFAULT_INTERVAL_SECONDS)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    cache_path = Path(args.cache_path)
    if args.once:
        write_cache_atomic(cache_path, collect_top_processes(args.limit))
        return 0

    run_loop(cache_path, args.interval_seconds, args.limit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
