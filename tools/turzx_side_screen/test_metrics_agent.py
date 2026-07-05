import json
from pathlib import Path
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent))

import metrics_agent


REQUIRED_SNAPSHOT_KEYS = {
    "schema_version",
    "timestamp_unix_ms",
    "sequence",
    "time",
    "weather",
    "alert",
    "foreground_app",
    "cpu",
    "gpu",
    "fps",
    "memory",
    "disks",
    "network",
    "top_processes",
    "health",
    "trust",
}


class MetricsAgentTests(unittest.TestCase):
    def setUp(self):
        if hasattr(metrics_agent, "_reset_gpu_cache_for_tests"):
            metrics_agent._reset_gpu_cache_for_tests()

    def test_build_snapshot_has_stable_schema(self):
        fake_disk = {
            "drive": "C:\\",
            "label": "Windows",
            "used_percent": 50.0,
            "free_gb": 10.0,
            "total_gb": 20.0,
            "drive_type": "fixed",
        }

        with (
            patch.object(
                metrics_agent,
                "read_weather_snapshot",
                return_value=metrics_agent.empty_snapshot()["weather"],
            ),
            patch.object(metrics_agent, "enumerate_disks", return_value=[fake_disk]),
            patch.object(metrics_agent, "read_top_processes", return_value=[]),
            patch.object(
                metrics_agent,
                "read_network_snapshot",
                return_value=metrics_agent.empty_snapshot()["network"],
            ),
            patch.object(
                metrics_agent,
                "read_foreground_app",
                return_value=metrics_agent.empty_snapshot()["foreground_app"],
            ),
        ):
            snapshot = metrics_agent.build_snapshot()

        self.assertEqual(REQUIRED_SNAPSHOT_KEYS, set(snapshot.keys()))
        self.assertEqual(1, snapshot["schema_version"])
        self.assertIsInstance(snapshot["timestamp_unix_ms"], int)
        self.assertIsInstance(snapshot["sequence"], int)
        self.assertIsInstance(snapshot["disks"], list)
        self.assertIsInstance(snapshot["top_processes"], list)
        self.assertIsInstance(snapshot["health"], dict)
        self.assertIn("status", snapshot["health"])
        self.assertIsInstance(snapshot["trust"], dict)
        self.assertIn("score", snapshot["trust"])
        self.assertIn("items", snapshot["trust"])

    def test_data_trust_scores_missing_fallback_sources_lower(self):
        snapshot = metrics_agent.empty_snapshot()
        snapshot["weather"]["source"] = "fallback"
        snapshot["weather"]["temperature_celsius"] = None
        snapshot["cpu"]["source"] = "fallback"
        snapshot["cpu"]["usage_percent"] = None
        snapshot["gpu"]["source"] = "fallback"
        snapshot["gpu"]["usage_percent"] = None
        snapshot["network"]["download_bytes_per_second"] = 1024
        snapshot["network"]["upload_bytes_per_second"] = 2048
        snapshot["network"]["ping_ms"] = None
        snapshot["top_processes"] = []
        snapshot["health"]["errors"] = [{"component": "gpu", "error": "probe failed"}]

        trust = metrics_agent.build_trust_snapshot(snapshot)

        self.assertLess(trust["score"], 75)
        self.assertEqual("warn", trust["level"])
        self.assertGreaterEqual(trust["missing_count"], 3)
        self.assertIn(trust["worst_component"], {"cpu", "gpu", "weather", "apps"})

    def test_data_trust_scores_live_sources_higher(self):
        snapshot = metrics_agent.empty_snapshot()
        snapshot["weather"].update(
            {
                "source": "weather_shim",
                "city": "田家庵",
                "temperature_celsius": 31,
                "condition": "晴",
                "updated_at": "2026-07-05T08:20:00+08:00",
            }
        )
        snapshot["cpu"].update(
            {
                "source": "windows_api+lhm",
                "usage_percent": 37.0,
                "temperature_celsius": 63.0,
                "power_watts": 145.0,
                "clock_mhz": 5557.0,
                "core_voltage": 1.27,
            }
        )
        snapshot["gpu"].update(
            {
                "source": "nvml+lhm",
                "usage_percent": 18.0,
                "temperature_celsius": 54.0,
                "power_watts": 154.0,
                "core_clock_mhz": 2835.0,
                "memory_clock_mhz": 16401.0,
                "core_voltage": 1.0,
            }
        )
        snapshot["fps"].update(
            {
                "source": "presentmon",
                "status": "active",
                "current": 144.0,
                "frame_time_ms": 6.9,
            }
        )
        snapshot["memory"].update(
            {
                "source": "psutil+nvml",
                "ram_usage_percent": 34.0,
                "vram_usage_percent": 14.0,
            }
        )
        snapshot["disks"] = [{"drive": "C:\\", "used_percent": 44.0, "free_gb": 120.0, "total_gb": 512.0}]
        snapshot["network"].update(
            {
                "source": "stdlib+ping",
                "download_bytes_per_second": 1024,
                "upload_bytes_per_second": 2048,
                "ping_ms": 18.0,
                "jitter_ms": 2.0,
                "packet_loss_percent": 0.0,
            }
        )
        snapshot["top_processes"] = [{"name": "Typora.exe", "cpu_percent": 8.0, "memory_mb": 512.0}]

        trust = metrics_agent.build_trust_snapshot(snapshot)

        self.assertGreaterEqual(trust["score"], 90)
        self.assertEqual("ok", trust["level"])
        self.assertEqual(0, trust["missing_count"])
        self.assertEqual("ok", trust["items"][0]["status"])

    def test_data_trust_log_writes_jsonl_summary(self):
        log_path = Path(__file__).resolve().parent / "out" / "data-trust-test.jsonl"
        log_path.parent.mkdir(exist_ok=True)
        if log_path.exists():
            log_path.unlink()

        trust = {
            "score": 82,
            "level": "warn",
            "worst_component": "fps",
            "missing_count": 1,
            "fallback_count": 0,
            "items": [{"component": "fps", "status": "idle", "score": 70}],
        }

        metrics_agent.write_data_trust_log(log_path, trust, timestamp_unix_ms=123456)

        payload = json.loads(log_path.read_text(encoding="utf-8").strip())
        self.assertEqual(123456, payload["timestamp_unix_ms"])
        self.assertEqual(82, payload["score"])
        self.assertEqual("fps", payload["worst_component"])
        self.assertEqual(1, payload["missing_count"])

    def test_display_time_uses_configured_china_timezone(self):
        value = metrics_agent.display_time_iso_from_utc(
            metrics_agent.dt.datetime(2026, 7, 4, 20, 25, 30, tzinfo=metrics_agent.dt.timezone.utc),
            "Asia/Shanghai",
        )

        self.assertEqual("2026-07-05T04:25:30+08:00", value)

    def test_enumerate_disks_returns_expected_structure(self):
        disks = metrics_agent.enumerate_disks()

        self.assertIsInstance(disks, list)
        self.assertGreaterEqual(len(disks), 1)
        for disk in disks:
            self.assertEqual(
                {
                    "drive",
                    "label",
                    "used_percent",
                    "free_gb",
                    "total_gb",
                    "drive_type",
                },
                set(disk.keys()),
            )
            self.assertRegex(disk["drive"], r"^[A-Z]:\\$")

    def test_snapshot_handler_returns_json(self):
        expected = metrics_agent.empty_snapshot()
        expected["time"] = "2026-07-04T00:00:00Z"
        expected["disks"] = [
            {
                "drive": "C:\\",
                "label": "Windows",
                "used_percent": 50.0,
                "free_gb": 10.0,
                "total_gb": 20.0,
                "drive_type": "fixed",
            }
        ]

        server = metrics_agent.create_server(
            "127.0.0.1",
            0,
            snapshot_provider=lambda: expected,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        try:
            host, port = server.server_address
            with urllib.request.urlopen(
                f"http://{host}:{port}/snapshot",
                timeout=2,
            ) as response:
                body = response.read()

            payload = json.loads(body.decode("utf-8"))
            self.assertEqual(200, response.status)
            self.assertEqual("application/json", response.headers["Content-Type"])
            self.assertEqual(expected, payload)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_local_addresses_does_not_depend_on_dns_lookup(self):
        with patch.object(
            metrics_agent.socket,
            "getaddrinfo",
            side_effect=AssertionError("DNS lookup should not be used"),
        ):
            addresses = metrics_agent._local_addresses()

        self.assertIsInstance(addresses, list)

    def test_weather_snapshot_parses_weather_shim_payload(self):
        payload = {
            "code": "200",
            "updateTime": "2026-07-05T08:20:00+08:00",
            "now": {
                "temp": "31",
                "text": "晴",
                "humidity": "38",
                "windDir": "北",
                "windScale": "2",
            },
        }

        weather = metrics_agent._weather_from_qweather_payload("北京", payload)

        self.assertEqual("北京", weather["city"])
        self.assertEqual(31.0, weather["temperature_celsius"])
        self.assertEqual("31°C", weather["temperature_text"])
        self.assertEqual("晴", weather["condition"])
        self.assertEqual(38.0, weather["humidity_percent"])
        self.assertEqual("北 2级", weather["wind_text"])
        self.assertEqual("weather_shim", weather["source"])

    def test_parse_float_accepts_libre_hardware_monitor_degree_text(self):
        self.assertEqual(66.4, metrics_agent._parse_float("66.4 ｡紊"))
        self.assertEqual(1.308, metrics_agent._parse_float("1.308 V"))

    def test_lhm_sensor_snapshot_extracts_cpu_and_gpu_physical_metrics(self):
        payload = {
            "Text": "Sensor",
            "Children": [
                {
                    "Text": "WLY",
                    "Children": [
                        {
                            "Text": "AMD Ryzen 9 9950X3D",
                            "Children": [
                                {
                                    "Text": "Clocks",
                                    "Children": [
                                        {"Text": "Cores (Average)", "Value": "5557.0 MHz"},
                                        {"Text": "Cores (Average Effective)", "Value": "1734.0 MHz"},
                                    ],
                                },
                                {"Text": "Powers", "Children": [{"Text": "Package", "Value": "144.8 W"}]},
                                {"Text": "Temperatures", "Children": [{"Text": "Core (Tctl/Tdie)", "Value": "66.4 ｡紊"}]},
                            ],
                        },
                        {
                            "Text": "Gigabyte X870E AORUS PRO ICE",
                            "Children": [
                                {"Text": "Voltages", "Children": [{"Text": "Vcore", "Value": "1.308 V"}]},
                            ],
                        },
                        {
                            "Text": "NVIDIA GeForce RTX 5090 D",
                            "Children": [
                                {"Text": "Voltages", "Children": [{"Text": "GPU Core Voltage", "Value": "0.985 V"}]},
                            ],
                        },
                    ],
                }
            ],
        }

        sensors = metrics_agent._lhm_sensor_snapshot_from_payload(payload)

        self.assertEqual(66.4, sensors["cpu_temperature_celsius"])
        self.assertEqual(144.8, sensors["cpu_power_watts"])
        self.assertEqual(1.308, sensors["cpu_core_voltage"])
        self.assertEqual(5557.0, sensors["cpu_clock_mhz"])
        self.assertEqual(0.985, sensors["gpu_core_voltage"])

    def test_build_snapshot_merges_lhm_metrics_and_refresh_interval(self):
        fake_cpu = metrics_agent.empty_snapshot()["cpu"]
        fake_cpu["clock_mhz"] = 4292.0
        fake_cpu["clock_ghz"] = 4.29
        fake_gpu = metrics_agent._fallback_gpu_snapshot()
        fake_memory = metrics_agent.empty_snapshot()["memory"]
        lhm = {
            "cpu_temperature_celsius": 66.4,
            "cpu_power_watts": 144.8,
            "cpu_core_voltage": 1.308,
            "cpu_clock_mhz": 5557.0,
            "gpu_core_voltage": 0.985,
        }

        with (
            patch.object(metrics_agent, "read_weather_snapshot", return_value=metrics_agent.empty_snapshot()["weather"]),
            patch.object(metrics_agent, "enumerate_disks", return_value=[]),
            patch.object(metrics_agent, "read_top_processes", return_value=[]),
            patch.object(metrics_agent, "read_network_snapshot", return_value=metrics_agent.empty_snapshot()["network"]),
            patch.object(metrics_agent, "read_foreground_app", return_value=metrics_agent.empty_snapshot()["foreground_app"]),
            patch.object(metrics_agent, "read_cpu_snapshot", return_value=fake_cpu),
            patch.object(metrics_agent, "read_gpu_snapshot", return_value=fake_gpu),
            patch.object(metrics_agent, "read_memory_snapshot", return_value=fake_memory),
            patch.object(metrics_agent, "read_lhm_sensor_snapshot", return_value=lhm),
            patch.object(metrics_agent, "_configured_refresh_interval_seconds", return_value=0.5),
            patch.object(metrics_agent, "_SCHEDULER_LATENCY_SAMPLER", SimpleNamespace(sample=lambda: 430.0)),
        ):
            snapshot = metrics_agent.build_snapshot()

        self.assertEqual(66.4, snapshot["cpu"]["temperature_celsius"])
        self.assertEqual(144.8, snapshot["cpu"]["power_watts"])
        self.assertEqual(1.308, snapshot["cpu"]["core_voltage"])
        self.assertEqual(5557.0, snapshot["cpu"]["clock_mhz"])
        self.assertEqual(5.557, snapshot["cpu"]["clock_ghz"])
        self.assertEqual(0.985, snapshot["gpu"]["core_voltage"])
        self.assertEqual(0.5, snapshot["health"]["refresh_interval_seconds"])
        self.assertEqual(430.0, snapshot["health"]["dpc_latency_us"])

    def test_lhm_sensor_snapshot_returns_stale_cache_while_background_refresh_runs(self):
        if hasattr(metrics_agent, "_reset_lhm_cache_for_tests"):
            metrics_agent._reset_lhm_cache_for_tests()
        cached = {"cpu_clock_mhz": 5557.0, "source": "lhm"}
        metrics_agent._lhm_cache_value = cached
        metrics_agent._lhm_cache_expires_at = 0.0
        refresh_calls = []

        with (
            patch.object(
                metrics_agent,
                "_fetch_json",
                side_effect=AssertionError("sync LHM fetch should not run"),
            ),
            patch.object(
                metrics_agent,
                "_start_lhm_sensor_refresh_locked",
                side_effect=lambda: refresh_calls.append(True),
            ),
        ):
            sensors = metrics_agent.read_lhm_sensor_snapshot()

        self.assertEqual(cached, sensors)
        self.assertEqual([True], refresh_calls)

    def test_lhm_sensor_snapshot_cold_cache_returns_empty_without_blocking(self):
        if hasattr(metrics_agent, "_reset_lhm_cache_for_tests"):
            metrics_agent._reset_lhm_cache_for_tests()
        refresh_calls = []

        with (
            patch.object(
                metrics_agent,
                "_fetch_json",
                side_effect=AssertionError("sync LHM fetch should not run"),
            ),
            patch.object(
                metrics_agent,
                "_start_lhm_sensor_refresh_locked",
                side_effect=lambda: refresh_calls.append(True),
            ),
        ):
            sensors = metrics_agent.read_lhm_sensor_snapshot()

        self.assertEqual({}, sensors)
        self.assertEqual([True], refresh_calls)

    def test_network_rate_sampler_reports_bytes_per_second_from_delta(self):
        readings = iter(
            [
                SimpleNamespace(bytes_recv=1_000, bytes_sent=2_000),
                SimpleNamespace(bytes_recv=2_024, bytes_sent=3_024),
            ]
        )
        timestamps = iter([10.0, 10.5])
        sampler = metrics_agent.NetworkRateSampler(
            read_counters=lambda: next(readings),
            now=lambda: next(timestamps),
        )

        first = sampler.sample()
        second = sampler.sample()

        self.assertIsNone(first["rx_bytes_per_sec"])
        self.assertIsNone(first["tx_bytes_per_sec"])
        self.assertEqual(2048.0, second["rx_bytes_per_sec"])
        self.assertEqual(2048.0, second["tx_bytes_per_sec"])

    def test_network_latency_sampler_reports_ping_jitter_and_loss(self):
        readings = iter([55.0, 61.0, None])
        timestamps = iter([10.0, 13.0, 16.0])
        sampler = metrics_agent.NetworkLatencySampler(
            read_ping_ms=lambda: next(readings),
            now=lambda: next(timestamps),
            ttl_seconds=0.0,
        )

        first = sampler.sample()
        second = sampler.sample()
        third = sampler.sample()

        self.assertEqual(55.0, first["ping_ms"])
        self.assertEqual(0.0, first["jitter_ms"])
        self.assertEqual(0.0, first["packet_loss_percent"])
        self.assertEqual(61.0, second["ping_ms"])
        self.assertEqual(6.0, second["jitter_ms"])
        self.assertEqual(100.0, third["packet_loss_percent"])

    def test_process_activity_sampler_reports_cpu_and_memory_from_deltas(self):
        class FakeProcess:
            def __init__(self, pid, name, cpu_seconds, rss):
                self.info = {
                    "pid": pid,
                    "name": name,
                    "create_time": 1.0,
                    "cpu_times": SimpleNamespace(user=cpu_seconds, system=0.0),
                    "memory_info": SimpleNamespace(rss=rss),
                }

        samples = iter(
            [
                [FakeProcess(10, "game.exe", 1.0, 3 * 1024 * 1024 * 1024)],
                [FakeProcess(10, "game.exe", 1.5, 3 * 1024 * 1024 * 1024)],
            ]
        )
        timestamps = iter([20.0, 21.0])
        sampler = metrics_agent.ProcessActivitySampler(
            process_iter=lambda attrs=None: next(samples),
            now=lambda: next(timestamps),
            cpu_count=2,
        )

        first = sampler.sample(limit=1)
        second = sampler.sample(limit=1)

        self.assertIsNone(first[0]["cpu_percent"])
        self.assertEqual(25.0, second[0]["cpu_percent"])
        self.assertEqual(3072.0, second[0]["memory_mb"])

    def test_process_activity_sampler_excludes_system_idle_process(self):
        class FakeProcess:
            def __init__(self, pid, name, cpu_seconds, rss):
                self.info = {
                    "pid": pid,
                    "name": name,
                    "create_time": 1.0,
                    "cpu_times": SimpleNamespace(user=cpu_seconds, system=0.0),
                    "memory_info": SimpleNamespace(rss=rss),
                }

        sampler = metrics_agent.ProcessActivitySampler(
            process_iter=lambda attrs=None: [
                FakeProcess(0, "System Idle Process", 10.0, 0),
                FakeProcess(20, "chrome.exe", 2.0, 512 * 1024 * 1024),
            ],
            now=lambda: 30.0,
            cpu_count=2,
        )

        processes = sampler.sample(limit=5)

        self.assertEqual(["chrome.exe"], [process["name"] for process in processes])

    def test_process_activity_sampler_aggregates_processes_by_app_name(self):
        class FakeProcess:
            def __init__(self, pid, name, cpu_seconds, rss):
                self.info = {
                    "pid": pid,
                    "name": name,
                    "create_time": float(pid),
                    "cpu_times": SimpleNamespace(user=cpu_seconds, system=0.0),
                    "memory_info": SimpleNamespace(rss=rss),
                }

        samples = iter(
            [
                [
                    FakeProcess(20, "chrome.exe", 1.0, 512 * 1024 * 1024),
                    FakeProcess(21, "chrome.exe", 2.0, 256 * 1024 * 1024),
                ],
                [
                    FakeProcess(20, "chrome.exe", 1.2, 512 * 1024 * 1024),
                    FakeProcess(21, "chrome.exe", 2.4, 256 * 1024 * 1024),
                ],
            ]
        )
        timestamps = iter([40.0, 41.0])
        sampler = metrics_agent.ProcessActivitySampler(
            process_iter=lambda attrs=None: next(samples),
            now=lambda: next(timestamps),
            cpu_count=2,
        )

        sampler.sample(limit=5)
        processes = sampler.sample(limit=5)

        self.assertEqual(1, len(processes))
        self.assertEqual("chrome.exe", processes[0]["name"])
        self.assertEqual(30.0, processes[0]["cpu_percent"])
        self.assertEqual(768.0, processes[0]["memory_mb"])

    def test_top_processes_reads_helper_cache_file_without_sampling(self):
        if hasattr(metrics_agent, "_reset_top_processes_cache_for_tests"):
            metrics_agent._reset_top_processes_cache_for_tests()
        cache_path = Path(__file__).resolve().parent / "out" / "test-top-processes.json"
        cache_path.parent.mkdir(exist_ok=True)
        payload = {
            "schema_version": 1,
            "generated_at_unix_ms": int(time.time() * 1000),
            "processes": [
                {
                    "name": "Typora.exe",
                    "description": None,
                    "pid": 42,
                    "cpu_percent": 3.0,
                    "gpu_percent": None,
                    "memory_mb": 512.0,
                    "memory_gb": 0.5,
                    "source": "top_processes_helper",
                }
            ],
        }
        cache_path.write_text(json.dumps(payload), encoding="utf-8")

        with (
            patch.object(metrics_agent, "TOP_PROCESSES_CACHE_PATH", str(cache_path)),
            patch.object(
                metrics_agent,
                "_PROCESS_SAMPLER",
                SimpleNamespace(sample=lambda limit=5: (_ for _ in ()).throw(AssertionError("main agent must not sample processes"))),
            ),
        ):
            processes = metrics_agent.read_top_processes()

        self.assertEqual("Typora.exe", processes[0]["name"])
        self.assertEqual("top_processes_helper", processes[0]["source"])

    def test_top_processes_refresh_interval_keeps_dashboard_feeling_live(self):
        self.assertLessEqual(metrics_agent.TOP_PROCESSES_HELPER_MAX_AGE_SECONDS, 10.0)
        self.assertGreaterEqual(metrics_agent.TOP_PROCESSES_HELPER_MAX_AGE_SECONDS, 8.0)

    def test_top_processes_ignores_stale_helper_cache_without_blocking(self):
        if hasattr(metrics_agent, "_reset_top_processes_cache_for_tests"):
            metrics_agent._reset_top_processes_cache_for_tests()
        cache_path = Path(__file__).resolve().parent / "out" / "test-top-processes-stale.json"
        cache_path.parent.mkdir(exist_ok=True)
        payload = {
            "schema_version": 1,
            "generated_at_unix_ms": int((time.time() - 60) * 1000),
            "processes": [
                {
                    "name": "stale.exe",
                    "description": None,
                    "pid": 99,
                    "cpu_percent": 99.0,
                    "gpu_percent": None,
                    "memory_mb": 1.0,
                    "memory_gb": 0.0,
                    "source": "top_processes_helper",
                }
            ],
        }
        cache_path.write_text(json.dumps(payload), encoding="utf-8")
        with (
            patch.object(metrics_agent, "TOP_PROCESSES_CACHE_PATH", str(cache_path)),
            patch.object(
                metrics_agent,
                "_PROCESS_SAMPLER",
                SimpleNamespace(sample=lambda limit=5: (_ for _ in ()).throw(AssertionError("sync sample should not run"))),
            ),
        ):
            processes = metrics_agent.read_top_processes()

        self.assertEqual([], processes)

    def test_top_processes_helper_writes_cache_atomically(self):
        import importlib.util

        helper_path = Path(__file__).resolve().parent / "top_processes_helper.py"
        spec = importlib.util.spec_from_file_location("top_processes_helper_test", helper_path)
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        cache_path = Path(__file__).resolve().parent / "out" / "helper-write-test.json"
        cache_path.parent.mkdir(exist_ok=True)

        helper.write_cache_atomic(
            cache_path,
            [{"name": "Typora.exe", "cpu_percent": 7.5, "memory_mb": 512.0}],
            generated_at_unix_ms=123456,
        )

        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        self.assertEqual(1, payload["schema_version"])
        self.assertEqual(123456, payload["generated_at_unix_ms"])
        self.assertEqual("Typora.exe", payload["processes"][0]["name"])

    def test_top_processes_helper_reuses_sampler_for_cpu_deltas(self):
        import importlib.util

        helper_path = Path(__file__).resolve().parent / "top_processes_helper.py"
        spec = importlib.util.spec_from_file_location("top_processes_helper_test", helper_path)
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)

        class FakeSampler:
            def __init__(self):
                self.calls = 0

            def sample(self, limit=5):
                self.calls += 1
                return [
                    {
                        "name": "Game.exe",
                        "pid": 100,
                        "cpu_percent": float(self.calls),
                        "memory_mb": 512.0,
                    }
                ]

        fake_sampler = FakeSampler()
        helper._PROCESS_SAMPLER = fake_sampler

        first = helper.collect_top_processes(limit=5)
        second = helper.collect_top_processes(limit=5)

        self.assertEqual(2, fake_sampler.calls)
        self.assertEqual(1.0, first[0]["cpu_percent"])
        self.assertEqual(2.0, second[0]["cpu_percent"])

    def test_top_processes_helper_loop_compensates_for_sampling_cost(self):
        import importlib.util

        helper_path = Path(__file__).resolve().parent / "top_processes_helper.py"
        spec = importlib.util.spec_from_file_location("top_processes_helper_test", helper_path)
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)

        self.assertAlmostEqual(2.4, helper._loop_sleep_seconds(10.0, 10.6, 3.0), places=2)
        self.assertAlmostEqual(0.2, helper._loop_sleep_seconds(10.0, 13.5, 3.0), places=2)

    def test_fps_snapshot_does_not_report_placeholder_zero_as_real_value(self):
        with patch.object(metrics_agent, "read_timeaudit_latest_snapshot", return_value={}):
            fps = metrics_agent.read_fps_snapshot()

        self.assertIsNone(fps["current"])
        self.assertEqual("fallback", fps["source"])

    def test_timeaudit_snapshot_is_disabled_when_dsn_missing(self):
        if hasattr(metrics_agent, "_reset_timeaudit_cache_for_tests"):
            metrics_agent._reset_timeaudit_cache_for_tests()
        with patch.object(metrics_agent, "TIMEAUDIT_DSN", None):
            snapshot = metrics_agent.read_timeaudit_latest_snapshot()

        self.assertEqual({}, snapshot)

    def test_fps_snapshot_uses_timeaudit_latest_row_when_present(self):
        with patch.object(
            metrics_agent,
            "read_timeaudit_latest_snapshot",
            return_value={
                "current_fps": 144.4,
                "average_fps": 141.2,
                "one_percent_low_fps": 118.6,
                "frametime_ms": 6.9,
            },
        ):
            fps = metrics_agent.read_fps_snapshot()

        self.assertEqual(144.4, fps["current"])
        self.assertEqual(141.2, fps["average"])
        self.assertEqual(118.6, fps["low_1_percent"])
        self.assertEqual(6.9, fps["frame_time_ms"])
        self.assertEqual("timeaudit_postgres", fps["source"])

    def test_timeaudit_latest_snapshot_returns_stale_cache_while_background_refresh_runs(self):
        if hasattr(metrics_agent, "_reset_timeaudit_cache_for_tests"):
            metrics_agent._reset_timeaudit_cache_for_tests()
        cached = {"current_fps": 144.0}
        metrics_agent._timeaudit_cache_value = cached
        metrics_agent._timeaudit_cache_expires_at = 0.0
        refresh_calls = []

        with (
            patch.object(
                metrics_agent.asyncio,
                "run",
                side_effect=AssertionError("sync TimeAudit query should not run"),
            ),
            patch.object(
                metrics_agent,
                "_start_timeaudit_refresh_locked",
                side_effect=lambda: refresh_calls.append(True),
            ),
        ):
            snapshot = metrics_agent.read_timeaudit_latest_snapshot()

        self.assertEqual(cached, snapshot)
        self.assertEqual([True], refresh_calls)

    def test_timeaudit_latest_snapshot_cold_cache_returns_empty_without_blocking(self):
        if hasattr(metrics_agent, "_reset_timeaudit_cache_for_tests"):
            metrics_agent._reset_timeaudit_cache_for_tests()
        refresh_calls = []

        with (
            patch.object(
                metrics_agent.asyncio,
                "run",
                side_effect=AssertionError("sync TimeAudit query should not run"),
            ),
            patch.object(
                metrics_agent,
                "_start_timeaudit_refresh_locked",
                side_effect=lambda: refresh_calls.append(True),
            ),
        ):
            snapshot = metrics_agent.read_timeaudit_latest_snapshot()

        self.assertEqual({}, snapshot)
        self.assertEqual([True], refresh_calls)

    def test_gpu_snapshot_falls_back_with_stable_schema_when_sources_fail(self):
        with (
            patch.object(metrics_agent, "_read_gpu_snapshot_nvml", return_value=None),
            patch.object(metrics_agent, "_read_gpu_snapshot_nvidia_smi", return_value=None),
        ):
            gpu = metrics_agent.read_gpu_snapshot()

        self.assertEqual(
            {
                "usage_percent",
                "temperature_c",
                "temperature_celsius",
                "name",
                "model",
                "power_watts",
                "core_voltage",
                "core_clock_mhz",
                "core_clock_ghz",
                "memory_clock_mhz",
                "memory_clock_ghz",
                "mem_clock_mhz",
                "vram_used_gb",
                "vram_total_gb",
                "load_history_percent",
                "status",
                "source",
            },
            set(gpu.keys()),
        )
        self.assertIsNone(gpu["usage_percent"])
        self.assertIsNone(gpu["temperature_c"])
        self.assertIsNone(gpu["name"])
        self.assertIsNone(gpu["core_clock_mhz"])
        self.assertIsNone(gpu["mem_clock_mhz"])
        self.assertEqual("fallback", gpu["source"])

    def test_parse_nvidia_smi_csv_returns_gpu_metrics(self):
        gpu = metrics_agent._parse_nvidia_smi_csv(
            "NVIDIA GeForce RTX 5090 D, 24, 57, 2947, 16601\n"
        )

        self.assertEqual("NVIDIA GeForce RTX 5090 D", gpu["name"])
        self.assertEqual(24.0, gpu["usage_percent"])
        self.assertEqual(57, gpu["temperature_c"])
        self.assertEqual(2947, gpu["core_clock_mhz"])
        self.assertEqual(16601, gpu["memory_clock_mhz"])
        self.assertEqual(16601, gpu["mem_clock_mhz"])
        self.assertEqual("nvidia-smi", gpu["source"])

    def test_gpu_snapshot_uses_nvml_when_available(self):
        class FakeNvml:
            NVML_TEMPERATURE_GPU = 0
            NVML_CLOCK_GRAPHICS = 0
            NVML_CLOCK_MEM = 2

            def nvmlInit(self):
                pass

            def nvmlDeviceGetCount(self):
                return 1

            def nvmlDeviceGetHandleByIndex(self, index):
                return object()

            def nvmlDeviceGetName(self, handle):
                return b"NVIDIA GeForce RTX 5090 D"

            def nvmlDeviceGetUtilizationRates(self, handle):
                return SimpleNamespace(gpu=28, memory=14)

            def nvmlDeviceGetTemperature(self, handle, sensor):
                return 58

            def nvmlDeviceGetPowerUsage(self, handle):
                return 174390

            def nvmlDeviceGetClockInfo(self, handle, clock_type):
                return 16601 if clock_type == self.NVML_CLOCK_MEM else 3217

            def nvmlDeviceGetMemoryInfo(self, handle):
                return SimpleNamespace(
                    used=4529 * 1024 * 1024,
                    total=32607 * 1024 * 1024,
                )

            def nvmlShutdown(self):
                pass

        with patch.object(metrics_agent, "_optional_import", return_value=FakeNvml()):
            gpu = metrics_agent._read_gpu_snapshot_nvml()

        self.assertEqual("NVIDIA GeForce RTX 5090 D", gpu["name"])
        self.assertEqual(28.0, gpu["usage_percent"])
        self.assertEqual(58.0, gpu["temperature_celsius"])
        self.assertEqual(174.39, gpu["power_watts"])
        self.assertEqual(3217.0, gpu["core_clock_mhz"])
        self.assertEqual(16601.0, gpu["memory_clock_mhz"])
        self.assertEqual(4.42, gpu["vram_used_gb"])
        self.assertEqual(31.84, gpu["vram_total_gb"])
        self.assertEqual("nvml", gpu["source"])

    def test_nvidia_smi_reader_uses_timeout_and_returns_none_on_timeout(self):
        with (
            patch.object(metrics_agent.shutil, "which", return_value="nvidia-smi"),
            patch.object(
                metrics_agent.subprocess,
                "run",
                side_effect=subprocess.TimeoutExpired("nvidia-smi", 0.1),
            ) as run,
        ):
            self.assertIsNone(metrics_agent._read_gpu_snapshot_nvidia_smi())

        self.assertIn("timeout", run.call_args.kwargs)
        self.assertLessEqual(run.call_args.kwargs["timeout"], 1.0)

    def test_cpu_usage_sampler_reports_percent_from_time_delta(self):
        readings = iter(
            [
                (100, 1_000, 1_000),
                (125, 1_100, 1_100),
            ]
        )
        sampler = metrics_agent.CpuUsageSampler(lambda: next(readings))

        self.assertEqual(87.5, sampler.sample())

    def test_cpu_snapshot_has_stable_schema_when_sampler_fails(self):
        sampler = metrics_agent.CpuUsageSampler(lambda: None)

        with (
            patch.object(metrics_agent, "_CPU_SAMPLER", sampler),
            patch.object(metrics_agent, "_optional_import", return_value=None),
        ):
            cpu = metrics_agent.read_cpu_snapshot()

        self.assertEqual(
            {
                "model",
                "usage_percent",
                "temperature_celsius",
                "power_watts",
                "clock_ghz",
                "clock_mhz",
                "core_voltage",
                "load_history_percent",
                "logical_count",
                "status",
                "source",
            },
            set(cpu.keys()),
        )
        self.assertIsNone(cpu["usage_percent"])
        self.assertEqual("fallback", cpu["source"])

    def test_cpu_snapshot_uses_psutil_when_available(self):
        sampler = metrics_agent.CpuUsageSampler(lambda: None)
        fake_psutil = SimpleNamespace(
            cpu_percent=lambda interval=None: 42.5,
            cpu_freq=lambda: SimpleNamespace(current=5557.0),
        )

        with (
            patch.object(metrics_agent, "_CPU_SAMPLER", sampler),
            patch.object(metrics_agent, "_optional_import", return_value=fake_psutil),
            patch.object(metrics_agent, "_read_cpu_model", return_value="AMD Ryzen 9"),
        ):
            cpu = metrics_agent.read_cpu_snapshot()

        self.assertEqual("AMD Ryzen 9", cpu["model"])
        self.assertEqual(42.5, cpu["usage_percent"])
        self.assertEqual(5557.0, cpu["clock_mhz"])
        self.assertEqual("active", cpu["status"])
        self.assertEqual("psutil", cpu["source"])
        self.assertGreaterEqual(len(cpu["load_history_percent"]), 1)

    def test_cpu_snapshot_combines_win32_usage_with_psutil_clock(self):
        readings = iter(
            [
                (100, 1_000, 1_000),
                (150, 1_100, 1_100),
            ]
        )
        sampler = metrics_agent.CpuUsageSampler(lambda: next(readings))
        fake_psutil = SimpleNamespace(
            cpu_percent=lambda interval=None: 99.0,
            cpu_freq=lambda: SimpleNamespace(current=5557.0),
        )

        with (
            patch.object(metrics_agent, "_CPU_SAMPLER", sampler),
            patch.object(metrics_agent, "_optional_import", return_value=fake_psutil),
            patch.object(metrics_agent, "_read_cpu_model", return_value="AMD Ryzen 9"),
        ):
            cpu = metrics_agent.read_cpu_snapshot()

        self.assertEqual(75.0, cpu["usage_percent"])
        self.assertEqual(5557.0, cpu["clock_mhz"])
        self.assertEqual("win32_getsystemtimes+psutil", cpu["source"])

    def test_build_snapshot_copies_vram_into_memory_block(self):
        fake_gpu = metrics_agent._fallback_gpu_snapshot()
        fake_gpu["vram_used_gb"] = 4.42
        fake_gpu["vram_total_gb"] = 31.84
        fake_memory = metrics_agent.empty_snapshot()["memory"]

        with (
            patch.object(metrics_agent, "read_weather_snapshot", return_value=metrics_agent.empty_snapshot()["weather"]),
            patch.object(metrics_agent, "enumerate_disks", return_value=[]),
            patch.object(metrics_agent, "read_top_processes", return_value=[]),
            patch.object(metrics_agent, "read_network_snapshot", return_value=metrics_agent.empty_snapshot()["network"]),
            patch.object(metrics_agent, "read_foreground_app", return_value=metrics_agent.empty_snapshot()["foreground_app"]),
            patch.object(metrics_agent, "read_cpu_snapshot", return_value=metrics_agent.empty_snapshot()["cpu"]),
            patch.object(metrics_agent, "read_gpu_snapshot", return_value=fake_gpu),
            patch.object(metrics_agent, "read_memory_snapshot", return_value=fake_memory),
        ):
            snapshot = metrics_agent.build_snapshot()

        self.assertEqual(4.42, snapshot["memory"]["vram_used_gb"])
        self.assertEqual(31.84, snapshot["memory"]["vram_total_gb"])
        self.assertEqual(13.9, snapshot["memory"]["vram_usage_percent"])


if __name__ == "__main__":
    unittest.main()
