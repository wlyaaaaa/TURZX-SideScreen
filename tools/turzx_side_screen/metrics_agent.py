from __future__ import annotations

import argparse
import asyncio
from collections import deque
import csv
import ctypes
from ctypes import wintypes
import datetime as dt
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import threading
import time
from typing import Any, Callable
from urllib.parse import urlencode, urlsplit
import urllib.request
import warnings
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 18765
SCHEMA_VERSION = 1
CPU_INITIAL_SAMPLE_WAIT_SECONDS = 0.05
GPU_CACHE_TTL_SECONDS = 1.0
GPU_FAILURE_CACHE_TTL_SECONDS = 3.0
GPU_LAST_GOOD_MAX_AGE_SECONDS = 30.0
NVIDIA_SMI_TIMEOUT_SECONDS = 0.8
WEATHER_CACHE_TTL_SECONDS = 600.0
WEATHER_FAILURE_CACHE_TTL_SECONDS = 30.0
LHM_SENSOR_URL = "http://127.0.0.1:8085/data.json"
LHM_SENSOR_CACHE_TTL_SECONDS = 1.0
NETWORK_LATENCY_TTL_SECONDS = 2.0
NETWORK_PING_TARGET = "223.5.5.5"
TIMEAUDIT_CACHE_TTL_SECONDS = 1.0
TOP_PROCESSES_CACHE_TTL_SECONDS = 5.0
TOP_PROCESSES_HELPER_MAX_AGE_SECONDS = 10.0
DEFAULT_DISPLAY_TIMEZONE = "Asia/Shanghai"
TIMEAUDIT_DSN = os.environ.get("TIMEAUDIT_DSN") or None
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
WEATHER_SHIM_BASE_URL = "http://127.0.0.1:18080"
TOP_PROCESSES_CACHE_PATH = os.environ.get(
    "TURZX_TOP_PROCESSES_CACHE",
    os.path.join(os.path.dirname(__file__), "out", "top-processes.json"),
)
DATA_TRUST_LOG_PATH = os.environ.get(
    "TURZX_DATA_TRUST_LOG",
    os.path.join(os.path.dirname(__file__), "out", "data-trust.jsonl"),
)
DATA_TRUST_LOG_INTERVAL_SECONDS = 5.0
_sequence = 0
_gpu_cache_value: dict[str, Any] | None = None
_gpu_cache_expires_at = 0.0
_gpu_last_good_value: dict[str, Any] | None = None
_gpu_last_good_at = 0.0
_lhm_cache_value: dict[str, Any] | None = None
_lhm_cache_expires_at = 0.0
_lhm_cache_lock = threading.Lock()
_lhm_refreshing = False
_timeaudit_cache_value: dict[str, Any] | None = None
_timeaudit_cache_expires_at = 0.0
_timeaudit_cache_lock = threading.Lock()
_timeaudit_refreshing = False
_weather_cache_value: dict[str, Any] | None = None
_weather_cache_expires_at = 0.0
_weather_cache_key: str | None = None
_config_cache: dict[str, Any] | None = None
_config_cache_mtime: float | None = None
_top_processes_cache_value: list[dict[str, Any]] | None = None
_top_processes_cache_expires_at = 0.0
_top_processes_cache_limit = 0
_top_processes_cache_lock = threading.Lock()
_top_processes_refreshing = False
_data_trust_log_lock = threading.Lock()
_data_trust_last_logged_at = 0.0
_data_trust_last_log_key: str | None = None
_cpu_history: deque[float] = deque(maxlen=120)
_gpu_history: deque[float] = deque(maxlen=120)

WEATHER_LOCATION_ALIASES = {
    "北京": "116.4074,39.9042",
    "beijing": "116.4074,39.9042",
    "田家庵": "101220405",
    "tianjiaan": "101220405",
}

DRIVE_TYPE_NAMES = {
    0: "unknown",
    1: "no_root_dir",
    2: "removable",
    3: "fixed",
    4: "network",
    5: "cdrom",
    6: "ramdisk",
}


def display_time_iso_from_utc(
    value: dt.datetime,
    timezone_name: str | None = None,
) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.timezone.utc)
    return (
        value.astimezone(display_tzinfo(timezone_name))
        .replace(microsecond=0)
        .isoformat()
    )


def display_tzinfo(timezone_name: str | None = None) -> dt.tzinfo:
    name = timezone_name or configured_timezone_name()
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return dt.timezone(dt.timedelta(hours=8), name="CST")


def configured_timezone_name() -> str:
    config = _load_config()
    time_config = config.get("time") if isinstance(config.get("time"), dict) else {}
    value = time_config.get("timezone")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return DEFAULT_DISPLAY_TIMEZONE


def utc_now_iso() -> str:
    return (
        dt.datetime.now(dt.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def next_sequence() -> int:
    global _sequence
    _sequence += 1
    return _sequence


def empty_snapshot() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "timestamp_unix_ms": 0,
        "sequence": 0,
        "time": None,
        "weather": {
            "city": None,
            "summary": None,
            "condition": None,
            "temperature_celsius": None,
            "temperature_c": None,
            "temperature_text": None,
            "aqi": None,
            "humidity_percent": None,
            "wind_text": None,
            "source": "fallback",
            "updated_at": None,
        },
        "alert": {
            "level": "ok",
            "message": None,
            "items": [],
        },
        "foreground_app": {
            "title": None,
            "process_id": None,
            "process_name": None,
            "exe_path": None,
            "source": "fallback",
        },
        "cpu": {
            "model": None,
            "usage_percent": None,
            "temperature_celsius": None,
            "power_watts": None,
            "clock_ghz": None,
            "clock_mhz": None,
            "core_voltage": None,
            "load_history_percent": [],
            "logical_count": os.cpu_count(),
            "status": "idle",
            "source": "fallback",
        },
        "gpu": {
            "model": None,
            "usage_percent": None,
            "temperature_c": None,
            "temperature_celsius": None,
            "name": None,
            "power_watts": None,
            "core_voltage": None,
            "core_clock_mhz": None,
            "core_clock_ghz": None,
            "memory_clock_mhz": None,
            "memory_clock_ghz": None,
            "mem_clock_mhz": None,
            "vram_used_gb": None,
            "vram_total_gb": None,
            "load_history_percent": [],
            "status": "idle",
            "source": "fallback",
        },
        "fps": {
            "current": None,
            "average": None,
            "low_1_percent": None,
            "frame_time_ms": None,
            "status": "idle",
            "source": "fallback",
        },
        "memory": {
            "used_percent": None,
            "used_gb": None,
            "available_gb": None,
            "total_gb": None,
            "vram_usage_percent": None,
            "vram_used_gb": None,
            "vram_total_gb": None,
            "source": "fallback",
        },
        "disks": [],
        "network": {
            "rx_bytes_per_sec": None,
            "tx_bytes_per_sec": None,
            "addresses": [],
            "source": "stdlib",
        },
        "top_processes": [],
        "health": {
            "status": "ok",
            "detail": None,
            "dpc_latency_us": None,
            "hard_page_faults_per_second": None,
            "refresh_interval_seconds": None,
            "generated_at": None,
            "errors": [],
        },
        "trust": {
            "score": 0,
            "level": "unknown",
            "summary": None,
            "worst_component": None,
            "missing_count": 0,
            "fallback_count": 0,
            "stale_count": 0,
            "log_path": "out/data-trust.jsonl",
            "items": [],
        },
    }


def build_snapshot() -> dict[str, Any]:
    snapshot = empty_snapshot()
    now_dt = dt.datetime.now(dt.timezone.utc)
    now = (
        now_dt.replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
    snapshot["timestamp_unix_ms"] = int(now_dt.timestamp() * 1000)
    snapshot["sequence"] = next_sequence()
    snapshot["time"] = display_time_iso_from_utc(now_dt)
    snapshot["health"]["generated_at"] = now

    errors: list[dict[str, str]] = []
    collectors: list[tuple[str, Callable[[], Any]]] = [
        ("weather", read_weather_snapshot),
        ("foreground_app", read_foreground_app),
        ("cpu", read_cpu_snapshot),
        ("gpu", read_gpu_snapshot),
        ("fps", read_fps_snapshot),
        ("memory", read_memory_snapshot),
        ("disks", enumerate_disks),
        ("network", read_network_snapshot),
        ("top_processes", read_top_processes),
    ]

    for key, collector in collectors:
        try:
            snapshot[key] = collector()
        except Exception as exc:  # Keep the HTTP schema stable even on partial failure.
            errors.append(
                {
                    "component": key,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )

    _merge_gpu_vram_into_memory(snapshot)
    _merge_lhm_sensors(snapshot)
    snapshot["health"]["errors"] = errors
    snapshot["health"]["status"] = "ok" if not errors else "degraded"
    snapshot["health"]["detail"] = "模块正常运转中" if not errors else f"采集异常 {len(errors)} 项"
    snapshot["health"]["refresh_interval_seconds"] = _configured_refresh_interval_seconds()
    snapshot["health"]["dpc_latency_us"] = _SCHEDULER_LATENCY_SAMPLER.sample()
    snapshot["trust"] = build_trust_snapshot(snapshot)
    _maybe_write_data_trust_log(snapshot)
    return snapshot


def build_trust_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    items = [
        _trust_cpu(snapshot.get("cpu")),
        _trust_gpu(snapshot.get("gpu")),
        _trust_fps(snapshot.get("fps")),
        _trust_weather(snapshot.get("weather")),
        _trust_memory(snapshot.get("memory")),
        _trust_disks(snapshot.get("disks")),
        _trust_network(snapshot.get("network")),
        _trust_apps(snapshot.get("top_processes")),
        _trust_health(snapshot.get("health")),
    ]
    weights = {
        "cpu": 16,
        "gpu": 16,
        "fps": 10,
        "weather": 12,
        "memory": 10,
        "disks": 10,
        "network": 12,
        "apps": 10,
        "health": 4,
    }
    total_weight = sum(weights.get(str(item.get("component")), 1) for item in items)
    weighted = sum(_trust_item_score(item) * weights.get(str(item.get("component")), 1) for item in items)
    score = int(round(weighted / total_weight)) if total_weight else 0
    missing_count = sum(1 for item in items if int(item.get("missing_count") or 0) > 0)
    missing_field_count = sum(int(item.get("missing_count") or 0) for item in items)
    fallback_count = sum(1 for item in items if item.get("fallback"))
    stale_count = sum(1 for item in items if item.get("status") == "stale")
    worst = min(items, key=lambda item: (_trust_item_score(item), str(item.get("component")))) if items else None
    level = "ok"
    if score < 35:
        level = "bad"
    elif score < 90 or missing_count > 0 or fallback_count > 0 or stale_count > 0:
        level = "warn"
    return {
        "score": score,
        "level": level,
        "summary": f"可信度 {score}/100",
        "worst_component": None if worst is None else worst.get("component"),
        "worst_label": None if worst is None else worst.get("label"),
        "missing_count": missing_count,
        "missing_field_count": missing_field_count,
        "fallback_count": fallback_count,
        "stale_count": stale_count,
        "log_path": "out/data-trust.jsonl",
        "items": items,
    }


def _trust_cpu(cpu: Any) -> dict[str, Any]:
    data = cpu if isinstance(cpu, dict) else {}
    score = 100
    missing: list[str] = []
    if _parse_float(data.get("usage_percent")) is None:
        missing.append("usage")
        score = min(score, 25)
    for key in ("temperature_celsius", "power_watts", "clock_mhz", "core_voltage"):
        if _parse_float(data.get(key)) is None:
            missing.append(key)
            score -= 5
    source = _empty_to_none(data.get("source")) or "fallback"
    fallback = _is_fallback_source(source)
    if fallback:
        score = min(score, 75)
    return _trust_item("cpu", "CPU", score, source, missing, fallback, _detail_from_missing("CPU", missing))


def _trust_gpu(gpu: Any) -> dict[str, Any]:
    data = gpu if isinstance(gpu, dict) else {}
    score = 100
    missing: list[str] = []
    if _parse_float(data.get("usage_percent")) is None:
        missing.append("usage")
        score = min(score, 25)
    for key in ("temperature_celsius", "power_watts", "core_clock_mhz", "memory_clock_mhz", "core_voltage"):
        if _parse_float(data.get(key)) is None:
            missing.append(key)
            score -= 4
    source = _empty_to_none(data.get("source")) or "fallback"
    stale = source.endswith("+stale") or data.get("status") == "stale"
    fallback = _is_fallback_source(source)
    if fallback:
        score = min(score, 75)
    if stale:
        score = min(score, 85)
    item = _trust_item("gpu", "GPU", score, source, missing, fallback, _detail_from_missing("GPU", missing))
    if stale:
        item["status"] = "stale"
        item["detail"] = "GPU 探针短暂失败，使用最近可信值"
    return item


def _trust_fps(fps: Any) -> dict[str, Any]:
    data = fps if isinstance(fps, dict) else {}
    source = _empty_to_none(data.get("source")) or "fallback"
    missing: list[str] = []
    score = 100
    if _parse_float(data.get("current")) is None:
        missing.append("current")
        score = 70
    if _parse_float(data.get("frame_time_ms")) is None:
        missing.append("frame_time")
        score = min(score, 75)
    fallback = _is_fallback_source(source)
    if fallback:
        score = min(score, 75)
    detail = "游戏帧捕获正常" if not missing else "无游戏帧或等待 PresentMon/RTSS"
    return _trust_item("fps", "FPS", score, source, missing, fallback, detail)


def _trust_weather(weather: Any) -> dict[str, Any]:
    data = weather if isinstance(weather, dict) else {}
    source = _empty_to_none(data.get("source")) or "fallback"
    missing: list[str] = []
    score = 100
    if _empty_to_none(data.get("city")) is None:
        missing.append("city")
        score -= 10
    if _parse_float(data.get("temperature_celsius") if data.get("temperature_celsius") is not None else data.get("temperature_c")) is None:
        missing.append("temperature")
        score = min(score, 45)
    if _empty_to_none(data.get("condition")) is None and _empty_to_none(data.get("summary")) is None:
        missing.append("condition")
        score -= 10
    fallback = _is_fallback_source(source)
    if fallback:
        score = min(score, 65)
    return _trust_item("weather", "天气", score, source, missing, fallback, _detail_from_missing("天气", missing))


def _trust_memory(memory: Any) -> dict[str, Any]:
    data = memory if isinstance(memory, dict) else {}
    source = _empty_to_none(data.get("source")) or "fallback"
    missing: list[str] = []
    score = 100
    if _parse_float(data.get("ram_usage_percent") if data.get("ram_usage_percent") is not None else data.get("used_percent")) is None:
        missing.append("ram")
        score = min(score, 45)
    if _parse_float(data.get("vram_usage_percent")) is None:
        score -= 8
    fallback = _is_fallback_source(source)
    if fallback and missing:
        score = min(score, 70)
    return _trust_item("memory", "内存", score, source, missing, fallback and bool(missing), _detail_from_missing("内存", missing))


def _trust_disks(disks: Any) -> dict[str, Any]:
    disk_list = disks if isinstance(disks, list) else []
    missing: list[str] = []
    score = 100
    if not disk_list:
        missing.append("drives")
        score = 45
    else:
        bad_rows = 0
        for disk in disk_list:
            if not isinstance(disk, dict) or _empty_to_none(disk.get("drive")) is None or _parse_float(disk.get("used_percent") if disk.get("used_percent") is not None else disk.get("usage_percent")) is None:
                bad_rows += 1
        if bad_rows:
            missing.append(f"{bad_rows}rows")
            score = max(60, 100 - bad_rows * 10)
    return _trust_item("disks", "磁盘", score, "stdlib", missing, False, _detail_from_missing("磁盘", missing))


def _trust_network(network: Any) -> dict[str, Any]:
    data = network if isinstance(network, dict) else {}
    source = _empty_to_none(data.get("source")) or "stdlib"
    missing: list[str] = []
    score = 100
    if _parse_float(data.get("download_bytes_per_second") if data.get("download_bytes_per_second") is not None else data.get("rx_bytes_per_sec")) is None:
        missing.append("download")
        score = min(score, 50)
    if _parse_float(data.get("upload_bytes_per_second") if data.get("upload_bytes_per_second") is not None else data.get("tx_bytes_per_sec")) is None:
        missing.append("upload")
        score = min(score, 50)
    if _parse_float(data.get("ping_ms")) is None:
        missing.append("ping")
        score = min(score, 82)
    if _parse_float(data.get("jitter_ms")) is None:
        score -= 4
    fallback = _is_fallback_source(source)
    return _trust_item("network", "网络", score, source, missing, fallback, _detail_from_missing("网络", missing))


def _trust_apps(processes: Any) -> dict[str, Any]:
    process_list = processes if isinstance(processes, list) else []
    missing: list[str] = []
    score = 100
    if not process_list:
        missing.append("processes")
        score = 45
    else:
        with_cpu = [item for item in process_list if isinstance(item, dict) and _parse_float(item.get("cpu_percent")) is not None]
        if not with_cpu:
            missing.append("cpu_delta")
            score = 72
    return _trust_item("apps", "应用", score, "top_processes_helper", missing, False, _detail_from_missing("应用", missing))


def _trust_health(health: Any) -> dict[str, Any]:
    data = health if isinstance(health, dict) else {}
    errors = data.get("errors") if isinstance(data.get("errors"), list) else []
    missing = [str(error.get("component") if isinstance(error, dict) else "error") for error in errors]
    score = 100 if not errors else max(50, 100 - len(errors) * 25)
    return _trust_item("health", "采集", score, "metrics_agent", missing, False, "模块正常" if not errors else f"采集异常 {len(errors)} 项")


def _trust_item(
    component: str,
    label: str,
    score: float,
    source: str,
    missing: list[str],
    fallback: bool,
    detail: str,
) -> dict[str, Any]:
    normalized_score = max(0, min(100, int(round(score))))
    status = "ok"
    if normalized_score < 50:
        status = "missing"
    elif normalized_score < 90 or missing or fallback:
        status = "warn"
    return {
        "component": component,
        "label": label,
        "score": normalized_score,
        "status": status,
        "source": source,
        "missing": missing,
        "missing_count": len(missing),
        "fallback": bool(fallback),
        "detail": detail,
    }


def _trust_item_score(item: dict[str, Any]) -> int:
    try:
        return int(item.get("score") or 0)
    except (TypeError, ValueError):
        return 0


def _is_fallback_source(source: Any) -> bool:
    text = (_empty_to_none(source) or "").lower()
    return not text or text == "fallback" or text.endswith("+fallback")


def _detail_from_missing(label: str, missing: list[str]) -> str:
    if not missing:
        return f"{label} 数据完整"
    return f"{label} 缺 " + "/".join(missing[:3])


def write_data_trust_log(
    log_path: str | os.PathLike[str],
    trust: dict[str, Any],
    timestamp_unix_ms: int | None = None,
) -> None:
    target = os.fspath(log_path)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    payload = {
        "timestamp_unix_ms": int(timestamp_unix_ms if timestamp_unix_ms is not None else time.time() * 1000),
        "score": trust.get("score"),
        "level": trust.get("level"),
        "worst_component": trust.get("worst_component"),
        "worst_label": trust.get("worst_label"),
        "missing_count": trust.get("missing_count"),
        "missing_field_count": trust.get("missing_field_count"),
        "fallback_count": trust.get("fallback_count"),
        "stale_count": trust.get("stale_count"),
        "items": trust.get("items", []),
    }
    with open(target, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")


def _maybe_write_data_trust_log(snapshot: dict[str, Any]) -> None:
    global _data_trust_last_logged_at, _data_trust_last_log_key

    trust = snapshot.get("trust")
    if not isinstance(trust, dict):
        return
    key = f"{trust.get('level')}:{trust.get('score')}:{trust.get('worst_component')}:{trust.get('missing_count')}:{trust.get('fallback_count')}"
    now = time.monotonic()
    with _data_trust_log_lock:
        if _data_trust_last_log_key == key and now - _data_trust_last_logged_at < DATA_TRUST_LOG_INTERVAL_SECONDS:
            return
        try:
            write_data_trust_log(
                DATA_TRUST_LOG_PATH,
                trust,
                timestamp_unix_ms=_parse_int(str(snapshot.get("timestamp_unix_ms"))) or int(time.time() * 1000),
            )
        except OSError:
            return
        _data_trust_last_logged_at = now
        _data_trust_last_log_key = key


def read_weather_snapshot() -> dict[str, Any]:
    global _weather_cache_expires_at, _weather_cache_key, _weather_cache_value

    config = _load_config()
    weather_config = config.get("weather") if isinstance(config.get("weather"), dict) else {}
    city = _empty_to_none(weather_config.get("city")) or "北京"
    location = _weather_location_for_city(city)
    cache_key = f"{city}|{location}"
    now = time.monotonic()
    if (
        _weather_cache_value is not None
        and _weather_cache_key == cache_key
        and now < _weather_cache_expires_at
    ):
        return dict(_weather_cache_value)

    query = urlencode({"location": location, "lang": "zh"})
    url = f"{WEATHER_SHIM_BASE_URL}/v7/weather/now?{query}"

    try:
        payload = _fetch_json(url, timeout=4.0)
        snapshot = _weather_from_qweather_payload(city, payload)
        ttl = WEATHER_CACHE_TTL_SECONDS if snapshot.get("source") == "weather_shim" else WEATHER_FAILURE_CACHE_TTL_SECONDS
    except Exception:
        if _weather_cache_value is not None and _weather_cache_key == cache_key:
            return dict(_weather_cache_value)
        snapshot = _fallback_weather_snapshot(city)
        ttl = WEATHER_FAILURE_CACHE_TTL_SECONDS

    _weather_cache_value = dict(snapshot)
    _weather_cache_key = cache_key
    _weather_cache_expires_at = time.monotonic() + ttl
    return snapshot


def _weather_from_qweather_payload(city: str | None, payload: dict[str, Any]) -> dict[str, Any]:
    now = payload.get("now") if isinstance(payload, dict) else None
    if not isinstance(now, dict) or str(payload.get("code", "200")) != "200":
        return _fallback_weather_snapshot(city)

    temp = _round_float_or_none(now.get("temp"))
    condition = _empty_to_none(now.get("text"))
    humidity = _round_float_or_none(now.get("humidity"))
    aqi = _round_float_or_none(now.get("aqi"))
    wind_dir = _empty_to_none(now.get("windDir"))
    wind_scale = _empty_to_none(now.get("windScale"))
    wind_text = None
    if wind_dir and wind_scale:
        wind_text = f"{wind_dir} {wind_scale}级"
    elif wind_dir:
        wind_text = wind_dir

    return {
        "city": _weather_display_city(city),
        "summary": condition,
        "condition": condition,
        "temperature_celsius": temp,
        "temperature_c": temp,
        "temperature_text": f"{int(round(temp))}°C" if temp is not None else None,
        "aqi": int(round(aqi)) if aqi is not None else None,
        "humidity_percent": humidity,
        "wind_text": wind_text,
        "source": "weather_shim",
        "updated_at": _empty_to_none(payload.get("updateTime")) or _empty_to_none(now.get("obsTime")),
    }


def _fallback_weather_snapshot(city: str | None = None) -> dict[str, Any]:
    snapshot = empty_snapshot()["weather"]
    snapshot["city"] = _empty_to_none(city)
    return snapshot


def _weather_location_for_city(city: str | None) -> str:
    text = _empty_to_none(city)
    if text is None:
        return WEATHER_LOCATION_ALIASES["北京"]
    return WEATHER_LOCATION_ALIASES.get(text, WEATHER_LOCATION_ALIASES.get(text.lower(), text))


def _weather_display_city(city: str | None) -> str | None:
    text = _empty_to_none(city)
    if text == "田家庵":
        return "淮南·田家庵"
    return text


def _fetch_json(url: str, timeout: float) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        body = response.read().decode("utf-8")
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise ValueError("JSON payload must be an object")
    return payload


def _load_config() -> dict[str, Any]:
    global _config_cache, _config_cache_mtime

    try:
        mtime = os.path.getmtime(CONFIG_PATH)
    except OSError:
        return {}

    if _config_cache is not None and _config_cache_mtime == mtime:
        return _config_cache

    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}

    _config_cache = payload if isinstance(payload, dict) else {}
    _config_cache_mtime = mtime
    return _config_cache


def read_lhm_sensor_snapshot() -> dict[str, Any]:
    now = time.monotonic()
    with _lhm_cache_lock:
        if _lhm_cache_value is not None and now < _lhm_cache_expires_at:
            return dict(_lhm_cache_value)

        stale = dict(_lhm_cache_value) if _lhm_cache_value is not None else {}
        _start_lhm_sensor_refresh_locked()
        return stale


def _start_lhm_sensor_refresh_locked() -> None:
    global _lhm_refreshing

    if _lhm_refreshing:
        return
    _lhm_refreshing = True
    thread = threading.Thread(target=_refresh_lhm_sensor_cache, daemon=True)
    thread.start()


def _refresh_lhm_sensor_cache() -> None:
    global _lhm_cache_expires_at, _lhm_cache_value, _lhm_refreshing

    try:
        payload = _fetch_json(LHM_SENSOR_URL, timeout=0.8)
        snapshot = _lhm_sensor_snapshot_from_payload(payload)
    except Exception:
        snapshot = {}

    with _lhm_cache_lock:
        if snapshot or _lhm_cache_value is None:
            _lhm_cache_value = dict(snapshot)
        _lhm_cache_expires_at = time.monotonic() + LHM_SENSOR_CACHE_TTL_SECONDS
        _lhm_refreshing = False


def _reset_lhm_cache_for_tests() -> None:
    global _lhm_cache_expires_at, _lhm_cache_value, _lhm_refreshing

    with _lhm_cache_lock:
        _lhm_cache_value = None
        _lhm_cache_expires_at = 0.0
        _lhm_refreshing = False


def _lhm_sensor_snapshot_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    flat: dict[str, Any] = {}
    _flatten_lhm_payload(payload, "", flat)

    cpu_temp = None
    cpu_power = None
    cpu_vcore = None
    cpu_clock = None
    gpu_voltage = None
    gpu_hotspot = None

    for key, raw in flat.items():
        lower = key.lower()
        value = _parse_float(raw)
        if value is None:
            continue

        if lower.endswith("/voltages/vcore"):
            cpu_vcore = round(value, 3)
        elif lower.endswith("/powers/package") and "gpu" not in lower:
            cpu_power = round(value, 1)
        elif "/clocks/" in lower and lower.endswith("/cores (average)"):
            cpu_clock = round(value, 1)
        elif "/temperatures/" in lower and "core (tctl/tdie)" in lower:
            cpu_temp = round(value, 1)
        elif "nvidia" in lower and lower.endswith("gpu core voltage"):
            gpu_voltage = round(value, 3)
        elif "nvidia" in lower and "/temperatures/" in lower and ("hot spot" in lower or "junction" in lower):
            if gpu_hotspot is None or "hot spot" in lower:
                gpu_hotspot = round(value, 1)

    return {
        "cpu_temperature_celsius": cpu_temp,
        "cpu_power_watts": cpu_power,
        "cpu_core_voltage": cpu_vcore,
        "cpu_clock_mhz": cpu_clock,
        "gpu_core_voltage": gpu_voltage,
        "gpu_hotspot_temperature_celsius": gpu_hotspot,
        "source": "lhm",
    }


def _flatten_lhm_payload(node: Any, path: str, out: dict[str, Any]) -> None:
    if not isinstance(node, dict):
        return
    text = _empty_to_none(node.get("Text")) or ""
    current = f"{path}/{text}" if text else path
    value = _empty_to_none(node.get("Value"))
    if value is not None:
        out[current] = value
    for child in node.get("Children") or []:
        _flatten_lhm_payload(child, current, out)


def _merge_lhm_sensors(snapshot: dict[str, Any]) -> None:
    sensors = read_lhm_sensor_snapshot()
    if not sensors:
        return

    cpu = snapshot.get("cpu")
    if isinstance(cpu, dict):
        _set_if_not_none(cpu, "temperature_celsius", sensors.get("cpu_temperature_celsius"))
        _set_if_not_none(cpu, "power_watts", sensors.get("cpu_power_watts"))
        _set_if_not_none(cpu, "core_voltage", sensors.get("cpu_core_voltage"))
        cpu_clock_mhz = sensors.get("cpu_clock_mhz")
        _set_if_not_none(cpu, "clock_mhz", cpu_clock_mhz)
        if cpu_clock_mhz is not None:
            cpu["clock_ghz"] = _mhz_to_ghz(cpu_clock_mhz)
        if any(cpu.get(key) is not None for key in ("temperature_celsius", "power_watts", "core_voltage", "clock_mhz")):
            cpu["source"] = _append_source(cpu.get("source"), "lhm")

    gpu = snapshot.get("gpu")
    if isinstance(gpu, dict):
        _set_if_not_none(gpu, "core_voltage", sensors.get("gpu_core_voltage"))
        if sensors.get("gpu_core_voltage") is not None:
            gpu["source"] = _append_source(gpu.get("source"), "lhm")


def _set_if_not_none(target: dict[str, Any], key: str, value: Any) -> None:
    if value is not None:
        target[key] = value


def _append_source(source: Any, suffix: str) -> str:
    text = _empty_to_none(source)
    if text is None or text == "fallback":
        return suffix
    if suffix in text.split("+"):
        return text
    return f"{text}+{suffix}"


def _configured_refresh_interval_seconds() -> float | None:
    config = _load_config()
    for section_name, key in (("metrics", "pollMs"), ("screen", "dataRefreshMs")):
        section = config.get(section_name)
        if not isinstance(section, dict):
            continue
        value = _parse_float(section.get(key))
        if value is not None and value > 0:
            return round(value / 1000.0, 3)
    return None


class SchedulerLatencySampler:
    def __init__(
        self,
        sleep: Callable[[float], None] | None = None,
        now: Callable[[], float] | None = None,
        target_seconds: float = 0.001,
    ):
        self._sleep = sleep or time.sleep
        self._now = now or time.perf_counter
        self._target_seconds = target_seconds

    def sample(self) -> float | None:
        try:
            start = self._now()
            self._sleep(self._target_seconds)
            elapsed = self._now() - start
        except Exception:
            return None
        jitter_us = max(0.0, (elapsed - self._target_seconds) * 1_000_000.0)
        return round(min(jitter_us, 100_000.0), 1)


_SCHEDULER_LATENCY_SAMPLER = SchedulerLatencySampler()


def read_cpu_snapshot() -> dict[str, Any]:
    try:
        usage_percent = _CPU_SAMPLER.sample()
        if usage_percent is None and _CPU_SAMPLER.has_baseline:
            time.sleep(CPU_INITIAL_SAMPLE_WAIT_SECONDS)
            usage_percent = _CPU_SAMPLER.sample()
    except Exception:
        usage_percent = None

    if usage_percent is None:
        psutil_snapshot = _read_cpu_snapshot_psutil()
        return psutil_snapshot or _fallback_cpu_snapshot()

    _append_history(_cpu_history, usage_percent)
    clock_mhz = _read_cpu_clock_mhz_psutil()
    return _cpu_snapshot(
        source="win32_getsystemtimes+psutil" if clock_mhz is not None else "win32_getsystemtimes",
        usage_percent=usage_percent,
        clock_mhz=clock_mhz,
    )


def read_gpu_snapshot() -> dict[str, Any]:
    global _gpu_cache_expires_at, _gpu_cache_value, _gpu_last_good_at, _gpu_last_good_value

    now = time.monotonic()
    if _gpu_cache_value is not None and now < _gpu_cache_expires_at:
        return dict(_gpu_cache_value)

    snapshot = _read_gpu_snapshot_nvml()
    if snapshot is None:
        snapshot = _read_gpu_snapshot_nvidia_smi()
    if snapshot is None:
        if _gpu_last_good_value is not None and now - _gpu_last_good_at <= GPU_LAST_GOOD_MAX_AGE_SECONDS:
            snapshot = dict(_gpu_last_good_value)
            source = str(snapshot.get("source") or "gpu").removesuffix("+stale")
            snapshot["source"] = source + "+stale"
            snapshot["status"] = "stale"
        else:
            snapshot = _fallback_gpu_snapshot()
    else:
        _gpu_last_good_value = dict(snapshot)
        _gpu_last_good_at = now

    ttl = (
        GPU_FAILURE_CACHE_TTL_SECONDS
        if snapshot["source"] == "fallback"
        else GPU_CACHE_TTL_SECONDS
    )
    _gpu_cache_value = dict(snapshot)
    _gpu_cache_expires_at = now + ttl
    return snapshot


class CpuUsageSampler:
    def __init__(self, read_times: Callable[[], tuple[int, int, int] | None] | None = None):
        self._read_times = read_times or _read_windows_cpu_times
        self._last = self._safe_read_times()

    @property
    def has_baseline(self) -> bool:
        return self._last is not None

    def sample(self) -> float | None:
        current = self._safe_read_times()
        if current is None:
            return None

        previous = self._last
        self._last = current
        if previous is None:
            return None

        idle_delta = current[0] - previous[0]
        kernel_delta = current[1] - previous[1]
        user_delta = current[2] - previous[2]
        total_delta = kernel_delta + user_delta
        if total_delta <= 0 or idle_delta < 0:
            return None

        busy_delta = max(total_delta - idle_delta, 0)
        usage = min(max((busy_delta / total_delta) * 100.0, 0.0), 100.0)
        return round(usage, 1)

    def _safe_read_times(self) -> tuple[int, int, int] | None:
        try:
            return self._read_times()
        except Exception:
            return None


def _read_windows_cpu_times() -> tuple[int, int, int] | None:
    if os.name != "nt":
        return None

    class FILETIME(ctypes.Structure):
        _fields_ = [
            ("dwLowDateTime", wintypes.DWORD),
            ("dwHighDateTime", wintypes.DWORD),
        ]

    idle = FILETIME()
    kernel = FILETIME()
    user = FILETIME()
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetSystemTimes.argtypes = [
        ctypes.POINTER(FILETIME),
        ctypes.POINTER(FILETIME),
        ctypes.POINTER(FILETIME),
    ]
    kernel32.GetSystemTimes.restype = wintypes.BOOL

    if not kernel32.GetSystemTimes(
        ctypes.byref(idle),
        ctypes.byref(kernel),
        ctypes.byref(user),
    ):
        return None

    return (
        _filetime_to_int(idle),
        _filetime_to_int(kernel),
        _filetime_to_int(user),
    )


def _filetime_to_int(value: Any) -> int:
    return (int(value.dwHighDateTime) << 32) | int(value.dwLowDateTime)


def _fallback_cpu_snapshot() -> dict[str, Any]:
    return _cpu_snapshot(
        source="fallback",
        usage_percent=None,
        clock_mhz=None,
    )


def _read_cpu_snapshot_psutil() -> dict[str, Any] | None:
    psutil = _optional_import("psutil")
    if psutil is None:
        return None

    try:
        usage_percent = _round_float_or_none(psutil.cpu_percent(interval=None))
    except Exception:
        usage_percent = None

    try:
        freq = psutil.cpu_freq()
        clock_mhz = getattr(freq, "current", None) if freq else None
    except Exception:
        clock_mhz = None

    if usage_percent is None and clock_mhz is None:
        return None

    if usage_percent is not None:
        _append_history(_cpu_history, usage_percent)
    return _cpu_snapshot(
        source="psutil",
        usage_percent=usage_percent,
        clock_mhz=clock_mhz,
    )


def _read_cpu_clock_mhz_psutil() -> float | None:
    psutil = _optional_import("psutil")
    if psutil is None:
        return None

    try:
        freq = psutil.cpu_freq()
        return _round_float_or_none(getattr(freq, "current", None) if freq else None)
    except Exception:
        return None


def _cpu_snapshot(
    *,
    source: str,
    usage_percent: Any,
    clock_mhz: Any,
) -> dict[str, Any]:
    usage_value = _round_float_or_none(usage_percent)
    clock_value = _round_float_or_none(clock_mhz)
    return {
        "model": _read_cpu_model(),
        "usage_percent": usage_value,
        "temperature_celsius": None,
        "power_watts": None,
        "clock_ghz": _mhz_to_ghz(clock_value),
        "clock_mhz": clock_value,
        "core_voltage": None,
        "load_history_percent": list(_cpu_history),
        "logical_count": os.cpu_count(),
        "status": _load_status(usage_value),
        "source": source,
    }


def _read_gpu_snapshot_nvml() -> dict[str, Any] | None:
    pynvml = _optional_import("pynvml")
    if pynvml is None:
        return None

    initialized = False
    try:
        pynvml.nvmlInit()
        initialized = True
        if pynvml.nvmlDeviceGetCount() < 1:
            return None

        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        utilization = _safe_nvml_value(
            lambda: pynvml.nvmlDeviceGetUtilizationRates(handle)
        )
        usage_percent = getattr(utilization, "gpu", None) if utilization else None
        name = _decode_text(_safe_nvml_value(lambda: pynvml.nvmlDeviceGetName(handle)))
        temperature_c = _safe_nvml_value(
            lambda: pynvml.nvmlDeviceGetTemperature(
                handle,
                pynvml.NVML_TEMPERATURE_GPU,
            )
        )
        core_clock_mhz = _safe_nvml_value(
            lambda: pynvml.nvmlDeviceGetClockInfo(
                handle,
                pynvml.NVML_CLOCK_GRAPHICS,
            )
        )
        mem_clock_mhz = _safe_nvml_value(
            lambda: pynvml.nvmlDeviceGetClockInfo(
                handle,
                pynvml.NVML_CLOCK_MEM,
            )
        )
        power_mw = _safe_nvml_value(lambda: pynvml.nvmlDeviceGetPowerUsage(handle))
        memory_info = _safe_nvml_value(lambda: pynvml.nvmlDeviceGetMemoryInfo(handle))

        return _gpu_snapshot(
            source="nvml",
            name=name,
            usage_percent=usage_percent,
            temperature_c=temperature_c,
            power_watts=_mw_to_watts(power_mw),
            core_clock_mhz=core_clock_mhz,
            memory_clock_mhz=mem_clock_mhz,
            vram_used_gb=_bytes_to_gb(int(memory_info.used)) if memory_info else None,
            vram_total_gb=_bytes_to_gb(int(memory_info.total)) if memory_info else None,
        )
    except Exception:
        return None
    finally:
        if initialized:
            _safe_nvml_value(pynvml.nvmlShutdown)


def _safe_nvml_value(read_value: Callable[[], Any]) -> Any:
    try:
        return read_value()
    except Exception:
        return None


def _read_gpu_snapshot_nvidia_smi() -> dict[str, Any] | None:
    if shutil.which("nvidia-smi") is None:
        return None

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,utilization.gpu,temperature.gpu,"
                "power.draw,clocks.current.graphics,clocks.current.memory,"
                "memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=NVIDIA_SMI_TIMEOUT_SECONDS,
            creationflags=creationflags,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None

    if result.returncode != 0:
        return None

    return _parse_nvidia_smi_csv(result.stdout)


def _parse_nvidia_smi_csv(output: str) -> dict[str, Any] | None:
    for row in csv.reader(output.splitlines()):
        if not row or not any(cell.strip() for cell in row):
            continue
        if len(row) < 5:
            return None

        return _gpu_snapshot(
            source="nvidia-smi",
            name=_empty_to_none(row[0]),
            usage_percent=_parse_float(row[1]),
            temperature_c=_parse_float(row[2]),
            power_watts=_parse_float(row[3]) if len(row) >= 8 else None,
            core_clock_mhz=_parse_float(row[4] if len(row) >= 8 else row[3]),
            memory_clock_mhz=_parse_float(row[5] if len(row) >= 8 else row[4]),
            vram_used_gb=_mib_to_gb(_parse_float(row[6])) if len(row) >= 8 else None,
            vram_total_gb=_mib_to_gb(_parse_float(row[7])) if len(row) >= 8 else None,
        )

    return None


def _gpu_snapshot(
    *,
    source: str,
    name: str | None,
    usage_percent: Any,
    temperature_c: Any,
    power_watts: Any,
    core_clock_mhz: Any,
    memory_clock_mhz: Any,
    vram_used_gb: Any,
    vram_total_gb: Any,
) -> dict[str, Any]:
    usage_value = _round_float_or_none(usage_percent)
    _append_history(_gpu_history, usage_value)
    temp_value = _round_float_or_none(temperature_c)
    core_clock_value = _round_float_or_none(core_clock_mhz)
    memory_clock_value = _round_float_or_none(memory_clock_mhz)
    return {
        "model": name,
        "usage_percent": usage_value,
        "temperature_c": temp_value,
        "temperature_celsius": temp_value,
        "name": name,
        "power_watts": _round_float2_or_none(power_watts),
        "core_voltage": None,
        "core_clock_mhz": core_clock_value,
        "core_clock_ghz": _mhz_to_ghz(core_clock_value),
        "memory_clock_mhz": memory_clock_value,
        "memory_clock_ghz": _mhz_to_ghz(memory_clock_value),
        "mem_clock_mhz": memory_clock_value,
        "vram_used_gb": _round_float2_or_none(vram_used_gb),
        "vram_total_gb": _round_float2_or_none(vram_total_gb),
        "load_history_percent": list(_gpu_history),
        "status": _load_status(usage_value),
        "source": source,
    }


def _fallback_gpu_snapshot() -> dict[str, Any]:
    return _gpu_snapshot(
        source="fallback",
        name=None,
        usage_percent=None,
        temperature_c=None,
        power_watts=None,
        core_clock_mhz=None,
        memory_clock_mhz=None,
        vram_used_gb=None,
        vram_total_gb=None,
    )


def _optional_import(name: str) -> Any:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)
            return importlib.import_module(name)
    except Exception:
        return None


def _read_cpu_model() -> str | None:
    if os.name == "nt":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
            ) as key:
                value, _ = winreg.QueryValueEx(key, "ProcessorNameString")
                return _empty_to_none(value)
        except Exception:
            pass

    return _empty_to_none(platform.processor())


def _merge_gpu_vram_into_memory(snapshot: dict[str, Any]) -> None:
    memory = snapshot.get("memory")
    gpu = snapshot.get("gpu")
    if not isinstance(memory, dict) or not isinstance(gpu, dict):
        return

    used = _round_float2_or_none(gpu.get("vram_used_gb"))
    total = _round_float2_or_none(gpu.get("vram_total_gb"))
    memory["vram_used_gb"] = used
    memory["vram_total_gb"] = total
    memory["vram_usage_percent"] = (
        round((used / total) * 100.0, 1)
        if used is not None and total not in (None, 0)
        else None
    )


def _append_history(history: deque[float], value: float | None) -> None:
    if value is not None:
        history.append(float(value))


def _mhz_to_ghz(value: float | None) -> float | None:
    return round(value / 1000.0, 3) if value is not None else None


def _mw_to_watts(value: Any) -> float | None:
    parsed = _parse_float(value)
    return round(parsed / 1000.0, 2) if parsed is not None else None


def _mib_to_gb(value: float | None) -> float | None:
    return round(value / 1024.0, 2) if value is not None else None


def _reset_gpu_cache_for_tests() -> None:
    global _gpu_cache_expires_at, _gpu_cache_value, _gpu_last_good_at, _gpu_last_good_value
    _gpu_cache_value = None
    _gpu_cache_expires_at = 0.0
    _gpu_last_good_value = None
    _gpu_last_good_at = 0.0


def _load_status(usage_percent: float | None) -> str:
    if usage_percent is None or usage_percent < 30.0:
        return "idle"
    if usage_percent < 85.0:
        return "active"
    return "busy"


def _decode_text(value: Any) -> str | None:
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    return _empty_to_none(value)


def _empty_to_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.upper() in {"N/A", "[N/A]", "[NOT SUPPORTED]"}:
        return None
    return text


def _parse_float(value: Any) -> float | None:
    text = _empty_to_none(value)
    if text is None:
        return None
    for suffix in ("%", "MHz", "C"):
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
    match = re.search(r"[-+]?[0-9]+(?:[.,][0-9]+)?", text)
    if match:
        text = match.group(0).replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def _round_float_or_none(value: Any) -> float | None:
    parsed = _parse_float(value)
    return round(parsed, 1) if parsed is not None else None


def _round_float2_or_none(value: Any) -> float | None:
    parsed = _parse_float(value)
    return round(parsed, 2) if parsed is not None else None


def _positive_float_or_none(value: Any) -> float | None:
    parsed = _parse_float(value)
    return parsed if parsed is not None and parsed > 0 else None


def _round_int_or_none(value: Any) -> int | None:
    parsed = _parse_float(value)
    return int(round(parsed)) if parsed is not None else None


_CPU_SAMPLER = CpuUsageSampler()


def read_timeaudit_latest_snapshot() -> dict[str, Any]:
    now = time.monotonic()
    with _timeaudit_cache_lock:
        if _timeaudit_cache_value is not None and now < _timeaudit_cache_expires_at:
            return dict(_timeaudit_cache_value)

        stale = dict(_timeaudit_cache_value) if _timeaudit_cache_value is not None else {}
        _start_timeaudit_refresh_locked()
        return stale


def _start_timeaudit_refresh_locked() -> None:
    global _timeaudit_refreshing

    if _timeaudit_refreshing:
        return
    _timeaudit_refreshing = True
    thread = threading.Thread(target=_refresh_timeaudit_cache, daemon=True)
    thread.start()


def _refresh_timeaudit_cache() -> None:
    global _timeaudit_cache_expires_at, _timeaudit_cache_value, _timeaudit_refreshing

    snapshot: dict[str, Any] = {}
    try:
        snapshot = asyncio.run(_read_timeaudit_latest_snapshot_async())
    except Exception:
        snapshot = {}

    with _timeaudit_cache_lock:
        if snapshot or _timeaudit_cache_value is None:
            _timeaudit_cache_value = dict(snapshot)
        _timeaudit_cache_expires_at = time.monotonic() + TIMEAUDIT_CACHE_TTL_SECONDS
        _timeaudit_refreshing = False


def _reset_timeaudit_cache_for_tests() -> None:
    global _timeaudit_cache_expires_at, _timeaudit_cache_value, _timeaudit_refreshing

    with _timeaudit_cache_lock:
        _timeaudit_cache_value = None
        _timeaudit_cache_expires_at = 0.0
        _timeaudit_refreshing = False


async def _read_timeaudit_latest_snapshot_async() -> dict[str, Any]:
    if not TIMEAUDIT_DSN:
        return {}

    asyncpg = _optional_import("asyncpg")
    if asyncpg is None:
        return {}

    conn = await asyncpg.connect(TIMEAUDIT_DSN)
    try:
        row = await conn.fetchrow(
            """
            SELECT timestamp,
                   current_fps,
                   average_fps,
                   one_percent_low_fps,
                   frametime_ms,
                   frametime_jitter
            FROM public.fact_system_hardware
            ORDER BY timestamp DESC
            LIMIT 1
            """
        )
    finally:
        await conn.close()

    return dict(row) if row else {}


def read_fps_snapshot() -> dict[str, Any]:
    timeaudit = read_timeaudit_latest_snapshot()
    current = _positive_float_or_none(timeaudit.get("current_fps"))
    if current is not None:
        average = _positive_float_or_none(timeaudit.get("average_fps"))
        low_1_percent = _positive_float_or_none(timeaudit.get("one_percent_low_fps"))
        frame_time = _positive_float_or_none(timeaudit.get("frametime_ms"))
        return {
            "current": current,
            "average": average,
            "low_1_percent": low_1_percent,
            "frame_time_ms": frame_time,
            "status": "active",
            "source": "timeaudit_postgres",
        }

    return {
        "current": None,
        "average": None,
        "low_1_percent": None,
        "frame_time_ms": None,
        "status": "idle",
        "source": "fallback",
    }


def read_memory_snapshot() -> dict[str, Any]:
    if os.name != "nt":
        return _fallback_memory_snapshot()

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", wintypes.DWORD),
            ("dwMemoryLoad", wintypes.DWORD),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    status = MEMORYSTATUSEX()
    status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(MEMORYSTATUSEX)]
    kernel32.GlobalMemoryStatusEx.restype = wintypes.BOOL
    if not kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return _fallback_memory_snapshot()

    total = int(status.ullTotalPhys)
    available = int(status.ullAvailPhys)
    used = max(total - available, 0)
    return {
        "used_percent": round(float(status.dwMemoryLoad), 1),
        "used_gb": _bytes_to_gb(used),
        "available_gb": _bytes_to_gb(available),
        "total_gb": _bytes_to_gb(total),
        "source": "win32",
    }


def _fallback_memory_snapshot() -> dict[str, Any]:
    return {
        "used_percent": None,
        "used_gb": None,
        "available_gb": None,
        "total_gb": None,
        "source": "fallback",
    }


def read_foreground_app() -> dict[str, Any]:
    fallback = {
        "title": None,
        "process_id": None,
        "process_name": None,
        "exe_path": None,
        "source": "fallback",
    }
    if os.name != "nt":
        return fallback

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    ]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD

    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return fallback

    length = user32.GetWindowTextLengthW(hwnd)
    title_buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, title_buffer, length + 1)

    pid = wintypes.DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

    exe_path = _process_image_path(pid.value) if pid.value else None
    return {
        "title": title_buffer.value or None,
        "process_id": int(pid.value) if pid.value else None,
        "process_name": os.path.basename(exe_path) if exe_path else None,
        "exe_path": exe_path,
        "source": "win32",
    }


def _process_image_path(pid: int) -> str | None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    process_query_limited_information = 0x1000
    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        return None

    try:
        size = wintypes.DWORD(32768)
        path_buffer = ctypes.create_unicode_buffer(size.value)
        ok = kernel32.QueryFullProcessImageNameW(
            handle,
            0,
            path_buffer,
            ctypes.byref(size),
        )
        return path_buffer.value if ok else None
    finally:
        kernel32.CloseHandle(handle)


def enumerate_disks() -> list[dict[str, Any]]:
    if os.name != "nt":
        return [_fallback_disk_info()]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetLogicalDrives.restype = wintypes.DWORD
    kernel32.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
    kernel32.GetDriveTypeW.restype = wintypes.UINT
    kernel32.GetDiskFreeSpaceExW.argtypes = [
        wintypes.LPCWSTR,
        ctypes.POINTER(ctypes.c_ulonglong),
        ctypes.POINTER(ctypes.c_ulonglong),
        ctypes.POINTER(ctypes.c_ulonglong),
    ]
    kernel32.GetDiskFreeSpaceExW.restype = wintypes.BOOL
    kernel32.GetVolumeInformationW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.LPWSTR,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPWSTR,
        wintypes.DWORD,
    ]
    kernel32.GetVolumeInformationW.restype = wintypes.BOOL

    mask = kernel32.GetLogicalDrives()
    disks: list[dict[str, Any]] = []

    for index in range(26):
        if not mask & (1 << index):
            continue
        root = f"{chr(ord('A') + index)}:\\"
        disks.append(_windows_disk_info(kernel32, root))

    return disks or [_fallback_disk_info()]


def _windows_disk_info(kernel32: Any, root: str) -> dict[str, Any]:
    drive_type_code = int(kernel32.GetDriveTypeW(root))
    label = _windows_volume_label(kernel32, root)

    free_to_caller = ctypes.c_ulonglong(0)
    total_bytes = ctypes.c_ulonglong(0)
    total_free_bytes = ctypes.c_ulonglong(0)
    ok = kernel32.GetDiskFreeSpaceExW(
        root,
        ctypes.byref(free_to_caller),
        ctypes.byref(total_bytes),
        ctypes.byref(total_free_bytes),
    )

    total = int(total_bytes.value) if ok else 0
    free = int(total_free_bytes.value) if ok else 0
    used_percent = round(((total - free) / total) * 100, 1) if total else None

    return {
        "drive": root,
        "label": label,
        "used_percent": used_percent,
        "free_gb": _bytes_to_gb(free) if total else None,
        "total_gb": _bytes_to_gb(total) if total else None,
        "drive_type": DRIVE_TYPE_NAMES.get(drive_type_code, "unknown"),
    }


def _windows_volume_label(kernel32: Any, root: str) -> str | None:
    label_buffer = ctypes.create_unicode_buffer(261)
    filesystem_buffer = ctypes.create_unicode_buffer(261)
    serial_number = wintypes.DWORD(0)
    max_component_length = wintypes.DWORD(0)
    filesystem_flags = wintypes.DWORD(0)

    ok = kernel32.GetVolumeInformationW(
        root,
        label_buffer,
        len(label_buffer),
        ctypes.byref(serial_number),
        ctypes.byref(max_component_length),
        ctypes.byref(filesystem_flags),
        filesystem_buffer,
        len(filesystem_buffer),
    )
    return label_buffer.value or None if ok else None


def _fallback_disk_info() -> dict[str, Any]:
    usage = shutil.disk_usage(os.path.abspath(os.sep))
    used = usage.total - usage.free
    return {
        "drive": os.path.abspath(os.sep),
        "label": None,
        "used_percent": round((used / usage.total) * 100, 1) if usage.total else None,
        "free_gb": _bytes_to_gb(usage.free),
        "total_gb": _bytes_to_gb(usage.total),
        "drive_type": "fixed",
    }


class NetworkRateSampler:
    def __init__(
        self,
        read_counters: Callable[[], Any | None] | None = None,
        now: Callable[[], float] | None = None,
        latency_sampler: Any | None = None,
    ):
        self._read_counters = read_counters or _read_network_counters_psutil
        self._now = now or time.monotonic
        self._latency_sampler = latency_sampler or NetworkLatencySampler()
        self._last: tuple[float, int, int] | None = None

    def sample(self) -> dict[str, Any]:
        current = self._safe_read_counters()
        timestamp = self._now()
        rx_rate = None
        tx_rate = None
        latency = self._latency_sampler.sample()

        if current is not None:
            rx_total = _parse_counter_int(getattr(current, "bytes_recv", None))
            tx_total = _parse_counter_int(getattr(current, "bytes_sent", None))
            if rx_total is not None and tx_total is not None:
                if self._last is not None:
                    previous_time, previous_rx, previous_tx = self._last
                    elapsed = timestamp - previous_time
                    rx_delta = rx_total - previous_rx
                    tx_delta = tx_total - previous_tx
                    if elapsed > 0 and rx_delta >= 0 and tx_delta >= 0:
                        rx_rate = round(rx_delta / elapsed, 1)
                        tx_rate = round(tx_delta / elapsed, 1)
                self._last = (timestamp, rx_total, tx_total)

        source_parts = []
        if current is not None:
            source_parts.append("psutil")
        if latency.get("source") == "ping":
            source_parts.append("ping")

        return {
            "rx_bytes_per_sec": rx_rate,
            "tx_bytes_per_sec": tx_rate,
            "download_bytes_per_second": rx_rate,
            "upload_bytes_per_second": tx_rate,
            "ping_ms": latency.get("ping_ms"),
            "jitter_ms": latency.get("jitter_ms"),
            "packet_loss_percent": latency.get("packet_loss_percent"),
            "addresses": _local_addresses(),
            "source": "+".join(source_parts) if source_parts else "fallback",
        }

    def _safe_read_counters(self) -> Any | None:
        try:
            return self._read_counters()
        except Exception:
            return None


def _read_network_counters_psutil() -> Any | None:
    psutil = _optional_import("psutil")
    if psutil is None:
        return None
    try:
        return psutil.net_io_counters()
    except Exception:
        return None


def _parse_counter_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class NetworkLatencySampler:
    def __init__(
        self,
        read_ping_ms: Callable[[], float | None] | None = None,
        now: Callable[[], float] | None = None,
        ttl_seconds: float = NETWORK_LATENCY_TTL_SECONDS,
    ):
        self._read_ping_ms = read_ping_ms or _read_ping_ms
        self._now = now or time.monotonic
        self._ttl_seconds = ttl_seconds
        self._last_result: dict[str, Any] | None = None
        self._last_expires_at = 0.0
        self._history: deque[float] = deque(maxlen=15)

    def sample(self) -> dict[str, Any]:
        now = self._now()
        if self._last_result is not None and now < self._last_expires_at:
            return dict(self._last_result)

        ping_ms = _round_float_or_none(self._read_ping_ms())
        if ping_ms is None:
            result = {
                "ping_ms": None,
                "jitter_ms": None,
                "packet_loss_percent": 100.0,
                "source": "ping",
            }
        else:
            self._history.append(ping_ms)
            result = {
                "ping_ms": ping_ms,
                "jitter_ms": _network_jitter(self._history),
                "packet_loss_percent": 0.0,
                "source": "ping",
            }

        self._last_result = dict(result)
        self._last_expires_at = now + self._ttl_seconds
        return result


def _network_jitter(history: deque[float]) -> float:
    values = list(history)
    if len(values) < 2:
        return 0.0
    diffs = [abs(values[index] - values[index - 1]) for index in range(1, len(values))]
    return round(sum(diffs) / len(diffs), 1)


def _read_ping_ms() -> float | None:
    target = _network_ping_target()
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        result = subprocess.run(
            ["ping", "-n", "1", "-w", "1000", target],
            capture_output=True,
            text=True,
            encoding="mbcs" if os.name == "nt" else "utf-8",
            errors="replace",
            timeout=1.5,
            creationflags=creationflags,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return _parse_ping_ms(result.stdout)


def _parse_ping_ms(output: str) -> float | None:
    match = re.search(r"(?:time|时间)\s*[=<]\s*([0-9]+(?:\.[0-9]+)?)\s*ms", output, re.IGNORECASE)
    if match:
        return _round_float_or_none(match.group(1))
    match = re.search(r"(?:Average|平均)\s*=\s*([0-9]+(?:\.[0-9]+)?)\s*ms", output, re.IGNORECASE)
    if match:
        return _round_float_or_none(match.group(1))
    return None


def _network_ping_target() -> str:
    config = _load_config()
    network = config.get("network")
    if isinstance(network, dict):
        target = _empty_to_none(network.get("pingHost"))
        if target is not None:
            return target
    return NETWORK_PING_TARGET


_NETWORK_SAMPLER = NetworkRateSampler()


def read_network_snapshot() -> dict[str, Any]:
    return _NETWORK_SAMPLER.sample()


def _local_addresses() -> list[str]:
    addresses: set[str] = {"127.0.0.1"}

    # Avoid hostname/FQDN DNS lookups here; they can block the /snapshot endpoint
    # for several seconds on some Windows networks.
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.settimeout(0.05)
            probe.connect(("8.8.8.8", 80))
            addresses.add(str(probe.getsockname()[0]))
    except OSError:
        pass

    return sorted(addresses)


class ProcessActivitySampler:
    def __init__(
        self,
        process_iter: Callable[..., Any] | None = None,
        now: Callable[[], float] | None = None,
        cpu_count: int | None = None,
    ):
        self._process_iter = process_iter
        self._now = now or time.monotonic
        self._cpu_count = max(int(cpu_count or os.cpu_count() or 1), 1)
        self._last_cpu: dict[tuple[int, float | None], tuple[float, float]] = {}

    def sample(self, limit: int = 5) -> list[dict[str, Any]]:
        process_iter = self._process_iter or _psutil_process_iter
        timestamp = self._now()
        current_cache: dict[tuple[int, float | None], tuple[float, float]] = {}
        processes: list[dict[str, Any]] = []

        try:
            iterator = process_iter(
                attrs=["pid", "name", "create_time", "cpu_times", "memory_info"]
            )
        except TypeError:
            iterator = process_iter()
        except Exception:
            return []

        for process in iterator or []:
            info = getattr(process, "info", None)
            if not isinstance(info, dict):
                continue

            pid = _parse_int(info.get("pid"))
            name = _empty_to_none(info.get("name"))
            if pid is None or name is None:
                continue
            if _is_ignored_process(pid, name):
                continue

            create_time = _round_float2_or_none(info.get("create_time"))
            cpu_seconds = _process_cpu_seconds(info.get("cpu_times"))
            memory_mb = _memory_info_mb(info.get("memory_info"))
            cpu_percent = None
            key = (pid, create_time)
            if cpu_seconds is not None:
                previous = self._last_cpu.get(key)
                if previous is not None:
                    previous_time, previous_cpu_seconds = previous
                    elapsed = timestamp - previous_time
                    delta = cpu_seconds - previous_cpu_seconds
                    if elapsed > 0 and delta >= 0:
                        cpu_percent = round(
                            min(max((delta / elapsed) * 100.0 / self._cpu_count, 0.0), 100.0),
                            1,
                        )
                current_cache[key] = (timestamp, cpu_seconds)

            processes.append(
                {
                    "name": name,
                    "description": None,
                    "pid": pid,
                    "cpu_percent": cpu_percent,
                    "gpu_percent": None,
                    "memory_mb": memory_mb,
                    "memory_gb": round(memory_mb / 1024.0, 2) if memory_mb is not None else None,
                    "source": "psutil",
                }
            )

        processes = _aggregate_processes_by_name(processes)
        self._last_cpu = current_cache
        if any((item.get("cpu_percent") or 0) > 0 for item in processes):
            sort_key = lambda item: item["cpu_percent"] if item["cpu_percent"] is not None else -1
        else:
            sort_key = lambda item: item["memory_mb"] if item["memory_mb"] is not None else -1
        return sorted(processes, key=sort_key, reverse=True)[:limit]


def _psutil_process_iter(attrs: list[str]) -> Any:
    psutil = _optional_import("psutil")
    if psutil is None:
        return []
    try:
        return psutil.process_iter(attrs=attrs)
    except Exception:
        return []


def _process_cpu_seconds(cpu_times: Any) -> float | None:
    user = _parse_float(getattr(cpu_times, "user", None))
    system = _parse_float(getattr(cpu_times, "system", None))
    if user is None and system is None:
        return None
    return float(user or 0.0) + float(system or 0.0)


def _memory_info_mb(memory_info: Any) -> float | None:
    rss = _parse_counter_int(getattr(memory_info, "rss", None))
    return round(rss / (1024.0 * 1024.0), 1) if rss is not None else None


def _aggregate_processes_by_name(processes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for process in processes:
        name = _empty_to_none(process.get("name"))
        if name is None:
            continue
        key = name.lower()
        group = grouped.get(key)
        if group is None:
            group = {
                "name": name,
                "description": process.get("description"),
                "pid": process.get("pid"),
                "cpu_percent": None,
                "gpu_percent": None,
                "memory_mb": None,
                "memory_gb": None,
                "source": process.get("source"),
            }
            grouped[key] = group

        if process.get("cpu_percent") is not None:
            group["cpu_percent"] = round(
                (group["cpu_percent"] or 0.0) + float(process["cpu_percent"]),
                1,
            )
        if process.get("gpu_percent") is not None:
            group["gpu_percent"] = round(
                (group["gpu_percent"] or 0.0) + float(process["gpu_percent"]),
                1,
            )
        if process.get("memory_mb") is not None:
            group["memory_mb"] = round(
                (group["memory_mb"] or 0.0) + float(process["memory_mb"]),
                1,
            )
            group["memory_gb"] = round(group["memory_mb"] / 1024.0, 2)

    return list(grouped.values())


_PROCESS_SAMPLER = ProcessActivitySampler()


def read_top_processes(limit: int = 5) -> list[dict[str, Any]]:
    return _read_top_processes_helper_cache(limit)


def _read_top_processes_helper_cache(limit: int = 5) -> list[dict[str, Any]]:
    try:
        with open(TOP_PROCESSES_CACHE_PATH, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return []

    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        return []

    generated_at = _parse_float(payload.get("generated_at_unix_ms"))
    if generated_at is None:
        return []
    age_seconds = (time.time() * 1000 - generated_at) / 1000.0
    if age_seconds < 0 or age_seconds > TOP_PROCESSES_HELPER_MAX_AGE_SECONDS:
        return []

    processes = payload.get("processes")
    if not isinstance(processes, list):
        return []

    normalized: list[dict[str, Any]] = []
    for process in processes:
        if not isinstance(process, dict):
            continue
        name = _empty_to_none(process.get("name"))
        if name is None:
            continue
        memory_mb = _round_float_or_none(process.get("memory_mb"))
        normalized.append(
            {
                "name": name,
                "description": process.get("description"),
                "pid": _parse_int(process.get("pid")),
                "cpu_percent": _round_float_or_none(process.get("cpu_percent")),
                "gpu_percent": _round_float_or_none(process.get("gpu_percent")),
                "memory_mb": memory_mb,
                "memory_gb": _round_float2_or_none(process.get("memory_gb"))
                if process.get("memory_gb") is not None
                else (round(memory_mb / 1024.0, 2) if memory_mb is not None else None),
                "source": _empty_to_none(process.get("source")) or "top_processes_helper",
            }
        )

    return normalized[:limit]


def _start_top_processes_refresh_locked(limit: int) -> None:
    global _top_processes_refreshing

    if _top_processes_refreshing:
        return
    _top_processes_refreshing = True
    thread = threading.Thread(target=_refresh_top_processes_cache, args=(limit,), daemon=True)
    thread.start()


def _refresh_top_processes_cache(limit: int = 5) -> None:
    global _top_processes_cache_expires_at, _top_processes_cache_limit, _top_processes_cache_value, _top_processes_refreshing

    try:
        psutil_processes = _PROCESS_SAMPLER.sample(limit)
        processes = psutil_processes if psutil_processes else _read_top_processes_tasklist(limit)
    except Exception:
        processes = []

    with _top_processes_cache_lock:
        _top_processes_cache_value = [dict(process) for process in processes]
        _top_processes_cache_limit = limit
        _top_processes_cache_expires_at = time.monotonic() + TOP_PROCESSES_CACHE_TTL_SECONDS
        _top_processes_refreshing = False


def _reset_top_processes_cache_for_tests() -> None:
    global _top_processes_cache_expires_at, _top_processes_cache_limit, _top_processes_cache_value, _top_processes_refreshing

    with _top_processes_cache_lock:
        _top_processes_cache_value = None
        _top_processes_cache_expires_at = 0.0
        _top_processes_cache_limit = 0
        _top_processes_refreshing = False


def _read_top_processes_tasklist(limit: int = 5) -> list[dict[str, Any]]:
    if os.name != "nt":
        return []

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        result = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=2,
            creationflags=creationflags,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []

    if result.returncode != 0:
        return []

    processes: list[dict[str, Any]] = []
    for row in csv.reader(result.stdout.splitlines()):
        if len(row) < 5:
            continue
        memory_kb = _parse_memory_kb(row[4])
        pid = _parse_int(row[1])
        name = row[0]
        if pid is not None and _is_ignored_process(pid, name):
            continue
        processes.append(
            {
                "name": name,
                "pid": pid,
                "cpu_percent": None,
                "gpu_percent": None,
                "memory_mb": round(memory_kb / 1024, 1) if memory_kb is not None else None,
            }
        )

    return sorted(
        processes,
        key=lambda item: item["memory_mb"] if item["memory_mb"] is not None else -1,
        reverse=True,
    )[:limit]


def _parse_memory_kb(value: str) -> int | None:
    digits = "".join(ch for ch in value if ch.isdigit())
    return int(digits) if digits else None


def _is_ignored_process(pid: int, name: str) -> bool:
    normalized = name.strip().lower()
    return pid == 0 or normalized in {"system idle process", "idle"}


def _parse_int(value: str) -> int | None:
    try:
        return int(value)
    except ValueError:
        return None


def _bytes_to_gb(value: int) -> float:
    return round(value / (1024**3), 2)


def make_handler(snapshot_provider: Callable[[], dict[str, Any]]) -> type[BaseHTTPRequestHandler]:
    class SnapshotHandler(BaseHTTPRequestHandler):
        server_version = "TURZXMetricsAgent/1.0"

        def do_GET(self) -> None:
            if urlsplit(self.path).path != "/snapshot":
                self.send_error(404, "Not Found")
                return

            try:
                payload = snapshot_provider()
            except Exception as exc:
                payload = empty_snapshot()
                now = utc_now_iso()
                payload["time"] = now
                payload["health"] = {
                    "status": "degraded",
                    "generated_at": now,
                    "errors": [
                        {
                            "component": "snapshot",
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    ],
                }

            body = json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            return

    return SnapshotHandler


def create_server(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    snapshot_provider: Callable[[], dict[str, Any]] | None = None,
) -> ThreadingHTTPServer:
    provider = snapshot_provider or build_snapshot
    return ThreadingHTTPServer((host, port), make_handler(provider))


def run_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
    server = create_server(host, port)
    print(f"TURZX metrics agent listening on http://{host}:{port}/snapshot")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TURZX side screen metrics agent")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args(argv)

    run_server(args.host, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
