"""
Benchmark CLI — runs real benchmark and outputs structured JSON report.
Usage: python main.py --benchmark [--duration 30] [--target PROCESS]

Uses PresentMon 2.5.1 via ShellExecuteW elevation for real frame timing.
"""

import json
import os
import time
from datetime import datetime
from typing import Optional

from app.utils.logger import get_logger, setup_logging

logger = get_logger("performance.benchmark_cli")

BENCHMARKS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "benchmarks"
)


def run_benchmark_cli(duration: int = 30, target_process: str = ""):
    """Execute benchmark from command line."""
    setup_logging()
    os.makedirs(BENCHMARKS_DIR, exist_ok=True)

    print("=" * 50)
    print("PHOENIX BENCHMARK")
    print("=" * 50)

    # Step 1: Detect environment
    print("\n[1/8] Detecting environment...")
    env = _detect_environment()
    _print_env(env)

    # Step 2: Detect PresentMon / FPS provider
    print("\n[2/8] Checking PresentMon...")
    from app.performance.presentmon_provider import find_presentmon, get_presentmon_version
    pm_path = find_presentmon()
    pm_available = False
    pm_version = None
    if pm_path:
        pm_version = get_presentmon_version(pm_path)
        print(f"  Found: {pm_path.name}")
        print(f"  Version: {pm_version or 'Unknown'}")
        print(f"  Path: {pm_path}")
        pm_available = True
    else:
        print("  PresentMon: NOT FOUND")
        print("  Install from: https://github.com/GameTechDev/PresentMon/releases")

    from app.performance.fps_provider import fps_registry
    providers = fps_registry.detect_available()
    fps_available = False
    active_provider = None
    for p in providers:
        status = "AVAILABLE" if p["available"] else "NOT AVAILABLE"
        print(f"  {p['name']}: {status}")
        if p["available"] and not fps_available:
            fps_available = True
            active_provider = p["name"]

    if not fps_available:
        print("\n  [!] FPS TELEMETRY UNAVAILABLE")
        print("  No frame-timing provider found.")
        print("  System metrics will still be collected.")

    # Step 3: Detect target process
    print("\n[3/8] Detecting target process...")
    from app.performance.target_process import target_process_detector
    candidates = target_process_detector.get_candidates()
    selected_target = None

    if not candidates:
        print("  No emulator process found.")
        print("  Launch MSI App Player / BlueStacks / LDPlayer to enable FPS measurement.")
        target_name = None
        target_pid = None
    else:
        for i, c in enumerate(candidates):
            print(f"  ({i+1}) {c.process_name} — {c.emulator}")
            print(f"      PID: {c.pid}  CPU: {c.cpu_percent:.1f}%  RAM: {c.memory_mb:.0f}MB")
            print(f"      Reason: {c.reason}")

        best = target_process_detector.select_best_target()
        if best:
            target_name = best.process_name
            target_pid = best.pid
            selected_target = best
            print(f"  -> Selected: {target_name} PID {target_pid}")
        else:
            target_name = None
            target_pid = None

    # Step 4: GPU association
    print("\n[4/8] Checking GPU association...")
    from app.performance.gpu_association import gpu_association_detector
    if target_pid:
        assoc = gpu_association_detector.detect_for_process(target_name, target_pid)
        print(f"  Process: {assoc.process_name} PID {assoc.pid}")
        print(f"  GPU: {assoc.gpu_name}")
        print(f"  Engine: {assoc.gpu_engine}")
        print(f"  Status: {assoc.status}")
        print(f"  Confidence: {assoc.confidence:.0%}")
        print(f"  Method: {assoc.method}")
    else:
        print("  No target process — GPU association cannot be determined")

    # Step 5: Start telemetry engine
    print("\n[5/8] Starting telemetry engine...")
    from app.core.telemetry import telemetry_engine
    telemetry_engine.start()
    print("  Telemetry engine started")

    # Step 6: Run PresentMon capture
    print(f"\n[6/8] Running PresentMon capture ({duration}s)...")

    fps_metrics = None
    presentmon_records = 0

    if pm_available:
        # Clean stale Phoenix sessions
        from app.performance.elevated_launcher import kill_stale_phoenix_sessions
        kill_stale_phoenix_sessions("PhoenixPerf_")
        time.sleep(0.5)

        # Launch PresentMon
        from app.performance.presentmon_provider import PresentMonProvider
        provider = PresentMonProvider()
        available, reason = provider.is_available()

        if available:
            print(f"  PresentMon: {provider.get_version()}")
            print(f"  Target: {target_name or 'ALL PROCESSES'}")
            print(f"  Duration: {duration}s")
            print(f"  Mode: Elevated capture via ShellExecuteW")

            # Start capture
            import psutil
            start_ok = provider.start(
                target_process=target_name or "",
                duration=duration,
            )

            if start_ok:
                # Wait for self-termination
                print("  Capturing...")
                wait_start = time.time()
                while time.time() - wait_start < duration + 30:
                    time.sleep(2)
                    elapsed = int(time.time() - wait_start)
                    csv_size = 0
                    if provider._csv_path and os.path.exists(provider._csv_path):
                        try:
                            csv_size = os.path.getsize(provider._csv_path)
                        except OSError:
                            pass
                    print(f"    [{elapsed:3d}s] CSV: {csv_size:>8,} bytes", end="\r")

                    # Check if PresentMon has exited
                    if provider._elevated_handle and provider._elevated_handle.pid:
                        try:
                            proc = psutil.Process(provider._elevated_handle.pid)
                            if not proc.is_running():
                                print(f"\n  PresentMon exited at {elapsed}s")
                                break
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            print(f"\n  PresentMon process gone at {elapsed}s")
                            break
                    elif elapsed >= duration + 5:
                        print(f"\n  Capture period elapsed at {elapsed}s")
                        break
                print()

                # Parse results
                provider.stop()
                presentmon_records = len(provider.get_samples())
                print(f"  Total records: {presentmon_records}")

                # Get target-specific metrics
                if target_name:
                    fps_metrics = provider.get_process_metrics(target_name)
                    target_records = [
                        s for s in provider.get_samples()
                        if getattr(s, "process_name", "") == target_name
                    ]
                    print(f"  Target records ({target_name}): {len(target_records)}")
                else:
                    fps_metrics = provider.get_metrics()

                if fps_metrics and fps_metrics.available:
                    print(f"  Average FPS: {fps_metrics.avg_fps:.1f}")
                    print(f"  1% Low: {fps_metrics.one_percent_low:.1f}")
                    print(f"  0.1% Low: {fps_metrics.point_one_percent_low:.1f}")
                else:
                    print(f"  FPS metrics: UNAVAILABLE")
                    if not target_name:
                        print(f"  (No target process — run with emulator active)")
            else:
                print(f"  PresentMon start FAILED: {provider.get_error_reason()}")
        else:
            print(f"  PresentMon unavailable: {reason}")
    else:
        print("  PresentMon not found — skipping FPS capture")

    # Step 7: Collect GPU telemetry samples
    print("\n[7/8] Collecting system telemetry...")
    gpu_samples = _collect_gpu_samples()

    # Step 8: Generate report
    print("\n[8/8] Generating report...")

    # Get system telemetry from telemetry engine
    import time as _time
    _time.sleep(2)  # Let telemetry stabilize
    frame = telemetry_engine.current

    report = {
        "timestamp": datetime.now().isoformat(),
        "duration_seconds": duration,
        "system": env,
        "fps_provider": {
            "available": fps_available or (pm_available and presentmon_records > 0),
            "provider": active_provider or ("PresentMon" if pm_available else "None"),
            "presentmon_version": pm_version,
            "presentmon_records": presentmon_records,
        },
        "target_process": {
            "name": target_name,
            "pid": target_pid,
        },
        "fps_metrics": None,
        "system_metrics": {
            "cpu_utilization": round(frame.cpu_utilization, 1),
            "gpu_utilization": round(frame.gpu_utilization, 1),
            "ram_percent": round(frame.ram_percent, 1),
            "gpu_temp": frame.gpu_temp,
            "gpu_clock_mhz": frame.gpu_clock_mhz,
            "gpu_memory_used_mb": round(frame.gpu_memory_used_mb, 0),
            "gpu_memory_total_mb": round(frame.gpu_memory_total_mb, 0),
        },
        "gpu_telemetry": gpu_samples,
    }

    if fps_metrics and fps_metrics.available:
        fm = fps_metrics
        report["fps_metrics"] = {
            "available": True,
            "provider": fm.provider_name,
            "avg_fps": round(fm.avg_fps, 1),
            "median_fps": round(fm.median_fps, 1),
            "min_fps": round(fm.min_fps, 1),
            "max_fps": round(fm.max_fps, 1),
            "one_percent_low": round(fm.one_percent_low, 1),
            "point_one_percent_low": round(fm.point_one_percent_low, 1),
            "avg_frame_time_ms": round(fm.avg_frame_time_ms, 2),
            "frame_time_variance": round(fm.frame_time_variance, 3),
            "frame_spikes": fm.frame_spikes,
            "stability_score": round(fm.stability_score, 1),
            "sample_count": fm.sample_count,
        }
    else:
        reason = "No FPS provider available" if not pm_available else "No target process found"
        if pm_available and presentmon_records > 0 and not target_name:
            reason = "PresentMon captured data but no emulator was running"
        report["fps_metrics"] = {
            "available": False,
            "reason": reason,
        }

    # Frame pacing analysis
    report["frame_pacing"] = None
    if fps_metrics and fps_metrics.available and provider and hasattr(provider, 'get_samples'):
        try:
            from app.performance.frame_pacing import frame_pacing_analyzer
            samples = provider.get_samples()
            pacing_result = frame_pacing_analyzer.analyze(samples)
            report["frame_pacing"] = {
                "classification": pacing_result.classification.value,
                "pacing_score": round(pacing_result.pacing_score, 1),
                "coefficient_of_variation": round(pacing_result.coefficient_of_variation, 4),
                "long_frame_percent": round(pacing_result.long_frame_percent, 2),
                "frame_spikes": pacing_result.frame_spikes,
                "consecutive_stutters": pacing_result.consecutive_stutters,
                "micro_stutters": pacing_result.micro_stutters,
                "severe_stutters": pacing_result.severe_stutters,
                "patterns": [p.value for p in pacing_result.detected_patterns],
            }
        except Exception as e:
            logger.debug(f"Frame pacing analysis error: {e}")

    # Print summary
    print("\n" + "=" * 50)
    print("BENCHMARK RESULT")
    print("=" * 50)

    # Get monitor refresh rate
    monitor_refresh = "N/A"
    try:
        from app.system.display import display_monitor
        display_info = display_monitor.detect()
        monitor_refresh = f"{display_info.refresh_rate_hz} Hz"
    except Exception:
        pass

    if report["fps_metrics"]["available"]:
        fm = report["fps_metrics"]
        print(f"\n  FPS Metrics (from PresentMon):")
        print(f"    Present FPS:   {fm['avg_fps']:.1f}")
        print(f"    Monitor:       {monitor_refresh}")
        print(f"    Median:        {fm['median_fps']:.1f}")
        print(f"    1% Low:        {fm['one_percent_low']:.1f}")
        print(f"    0.1% Low:      {fm['point_one_percent_low']:.1f}")
        print(f"    Frame Time:    {fm['avg_frame_time_ms']:.2f} ms")
        print(f"    Variance:      {fm['frame_time_variance']:.3f} ms2")
        print(f"    Spikes:        {fm['frame_spikes']}")
        print(f"    Stability:     {fm['stability_score']:.1f}/100")
        print(f"    Samples:       {fm['sample_count']}")

        # Frame pacing
        fp = report.get("frame_pacing")
        if fp:
            print(f"\n  Frame Pacing:")
            print(f"    Classification: {fp['classification']}")
            print(f"    Pacing Score:   {fp['pacing_score']:.0f}/100")
            print(f"    CV:             {fp['coefficient_of_variation']:.4f}")
            print(f"    Long Frames:    {fp['long_frame_percent']:.1f}%")
            print(f"    Micro-stutters: {fp['micro_stutters']}")
            print(f"    Max Consecutive:{fp['consecutive_stutters']}")
            if fp.get('patterns'):
                print(f"    Patterns:       {', '.join(fp['patterns'])}")
    else:
        print(f"\n  FPS Metrics: UNAVAILABLE")
        print(f"  Reason: {report['fps_metrics']['reason']}")

    sm = report["system_metrics"]
    print(f"\n  System Metrics:")
    print(f"    CPU:    {sm.get('cpu_utilization', 0):.1f}%")
    print(f"    GPU:    {sm.get('gpu_utilization', 0):.1f}%")
    print(f"    RAM:    {sm.get('ram_percent', 0):.1f}%")
    if sm.get('gpu_temp'):
        print(f"    GPU Temp: {sm['gpu_temp']}°C")
    if sm.get('gpu_clock_mhz'):
        print(f"    GPU Clock: {sm['gpu_clock_mhz']:.0f} MHz")
    if sm.get('gpu_memory_total_mb', 0) > 0:
        print(f"    VRAM: {sm.get('gpu_memory_used_mb', 0):.0f}/{sm['gpu_memory_total_mb']:.0f} MB")

    # Save JSON report
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = os.path.join(BENCHMARKS_DIR, f"benchmark_{timestamp_str}.json")
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\n  Report saved: {report_path}")

    print("\n" + "=" * 50)
    print("BENCHMARK COMPLETE")
    print("=" * 50)

    telemetry_engine.stop()

    # Clean up PresentMon processes
    from app.performance.elevated_launcher import kill_stale_phoenix_sessions
    kill_stale_phoenix_sessions("PhoenixPerf_")

    return report


def _detect_environment() -> dict:
    """Detect full system environment."""
    import platform
    env = {"os": platform.platform()}

    try:
        from app.system.cpu import cpu_monitor
        info = cpu_monitor.detect()
        env["cpu"] = f"{info.model} ({info.physical_cores}C/{info.logical_cores}T)"
    except Exception:
        env["cpu"] = "Unknown"

    try:
        from app.system.gpu import gpu_monitor
        gpus = gpu_monitor.detect()
        if gpus and gpus[0].name != "No GPU Detected":
            env["gpu"] = gpus[0].name
        else:
            env["gpu"] = "No GPU detected"
    except Exception:
        env["gpu"] = "Unknown"

    try:
        from app.system.memory import memory_monitor
        info = memory_monitor.detect()
        env["ram"] = f"{info.ram_total_gb:.1f} GB"
    except Exception:
        env["ram"] = "Unknown"

    try:
        from app.system.display import display_monitor
        info = display_monitor.detect()
        env["display"] = f"{info.resolution_x}x{info.resolution_y} @ {info.refresh_rate_hz}Hz"
    except Exception:
        env["display"] = "Unknown"

    try:
        from app.emulator.detector import emulator_detector
        emus = emulator_detector.detect_all()
        env["emulators"] = [e.DISPLAY_NAME for e in emus] if emus else ["None detected"]
    except Exception:
        env["emulators"] = ["Unknown"]

    return env


def _print_env(env: dict):
    print(f"  OS:        {env.get('os', 'Unknown')}")
    print(f"  CPU:       {env.get('cpu', 'Unknown')}")
    print(f"  GPU:       {env.get('gpu', 'Unknown')}")
    print(f"  RAM:       {env.get('ram', 'Unknown')}")
    print(f"  Display:   {env.get('display', 'Unknown')}")
    print(f"  Emulators: {', '.join(env.get('emulators', []))}")


def _collect_gpu_samples() -> dict:
    """Collect GPU telemetry samples."""
    from app.system.gpu import gpu_monitor
    try:
        gpus = gpu_monitor.detect()
        if not gpus or gpus[0].name == "No GPU Detected":
            return {"available": False}

        gpu = gpus[0]
        if gpu.vendor == "NVIDIA":
            gpu = gpu_monitor.update_nvidia(gpu)

        return {
            "available": True,
            "name": gpu.name,
            "utilization": gpu.utilization_gpu,
            "temperature": gpu.temperature_celsius,
            "clock_mhz": gpu.clock_core_mhz,
            "vram_used_mb": gpu.vram_used_mb,
            "vram_total_mb": gpu.vram_total_mb,
            "power_watts": gpu.power_draw_watts,
        }
    except Exception as e:
        return {"available": False, "error": str(e)}
