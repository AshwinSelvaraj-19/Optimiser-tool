"""
PresentMon Live Test — verifies real frame capture end-to-end.

Usage: python main.py --presentmon-test

Launches PresentMon elevated via ShellExecuteW,
captures CSV output, parses real frame data,
and verifies FPS calculation from actual frame timestamps.
"""

import os
import sys
import time
from typing import Optional

import psutil

from app.utils.logger import get_logger, setup_logging

logger = get_logger("performance.presentmon_test")


def run_presentmon_test(duration: int = 15):
    """Run a focused PresentMon capture test."""
    setup_logging()

    print("=" * 60)
    print("PRESENTMON LIVE TEST")
    print("=" * 60)

    # Step 1: Find PresentMon
    print("\n[1/7] Finding PresentMon...")
    from app.performance.presentmon_provider import find_presentmon, get_presentmon_version
    pm_path = find_presentmon()
    if not pm_path:
        print("  Status: NOT FOUND")
        print("  Install from: https://github.com/GameTechDev/PresentMon/releases")
        return
    print(f"  Executable: {pm_path.name}")
    ver = get_presentmon_version(pm_path)
    print(f"  Version: {ver or 'Unknown'}")
    print(f"  Path: {pm_path}")

    # Step 2: Detect target process
    print(f"\n[2/7] Detecting target process...")
    from app.performance.target_process import target_process_detector
    candidates = target_process_detector.get_candidates()
    target_name = None
    target_pid = None

    if candidates:
        for i, c in enumerate(candidates):
            print(f"  ({i+1}) {c.process_name} PID {c.pid} -- {c.emulator}")
        best = target_process_detector.select_best_target()
        if best:
            target_name = best.process_name
            target_pid = best.pid
            print(f"  -> Selected: {target_name} PID {target_pid}")
            print(f"     Reason: {best.reason}")
            print(f"     Confidence: {best.confidence:.0%}")
    else:
        print("  No emulator process found.")
        print("  PresentMon will capture ALL processes.")

    # Step 3: Check admin status
    print(f"\n[3/7] Checking privileges...")
    from app.utils.admin import is_admin
    admin = is_admin()
    print(f"  Admin: {'YES' if admin else 'NO'}")
    if not admin:
        print("  PresentMon requires elevated ETW access.")
        print("  Will attempt ShellExecuteW elevation (UAC prompt).")

    # Step 4: Launch PresentMon
    print(f"\n[4/7] Launching PresentMon (capture {duration}s)...")

    from app.performance.elevated_launcher import kill_stale_phoenix_sessions
    kill_stale_phoenix_sessions("PhoenixPerf_")
    time.sleep(1)

    from app.performance.presentmon_provider import PresentMonProvider
    provider = PresentMonProvider()

    available, reason = provider.is_available()
    if not available:
        print(f"  Status: UNAVAILABLE -- {reason}")
        return

    start_time = time.time()
    started = provider.start(target_process=target_name or "", duration=duration)
    start_elapsed = time.time() - start_time
    print(f"  Start result: {'OK' if started else 'FAILED'}")
    print(f"  Start time: {start_elapsed:.1f}s")
    print(f"  State: {provider.get_state()}")

    if not started:
        print(f"  Error: {provider.get_error_reason()}")
        print("\n  Troubleshooting:")
        print("  1. Accept the UAC prompt when it appears")
        print("  2. Ensure no other PresentMon session is active")
        print("  3. Try running as Administrator directly")
        return

    # Step 5: Wait for PresentMon to self-terminate
    print(f"\n[5/7] Waiting for PresentMon to self-terminate ({duration}s capture)...")
    wait_start = time.time()
    try:
        while time.time() - wait_start < duration + 30:
            time.sleep(2)
            elapsed = int(time.time() - wait_start)
            csv_size = 0
            if provider._csv_path and os.path.exists(provider._csv_path):
                try:
                    csv_size = os.path.getsize(provider._csv_path)
                except OSError:
                    pass
            print(f"  [{elapsed:3d}s] CSV: {csv_size:>8,} bytes", end="\r")

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
    except KeyboardInterrupt:
        print("\n  Interrupted by user")

    # Step 6: Parse CSV
    print(f"\n[6/7] Parsing captured CSV...")
    provider.stop()

    # Step 7: Results
    print(f"\n[7/7] Results")

    all_samples = provider.get_samples()

    # Capture status — use COMPLETE after stop() returns
    capture_status = provider.get_state()
    # Process status — check if PresentMon process is still running
    process_stopped = True
    if provider._elevated_handle and provider._elevated_handle.pid:
        try:
            proc = psutil.Process(provider._elevated_handle.pid)
            process_stopped = not proc.is_running()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            process_stopped = True

    print(f"  PresentMon: {pm_path.name}")
    print(f"  Version: {ver or 'Unknown'}")
    print(f"  Capture Status: {capture_status}")
    print(f"  Target: {target_name or 'NONE'}")
    if target_name:
        target_running = False
        try:
            for proc in psutil.process_iter(['pid', 'name']):
                if proc.info['name'] == target_name:
                    target_running = True
                    break
        except Exception:
            pass
        print(f"  Target Status: {'RUNNING' if target_running else 'STOPPED'}")
    print(f"  PresentMon Process: {'STOPPED' if process_stopped else 'RUNNING'}")
    print(f"  Total records: {len(all_samples)}")

    target_records = []
    if target_name:
        target_records = [
            s for s in all_samples
            if getattr(s, "process_name", "") == target_name
        ]
        print(f"  Target records ({target_name}): {len(target_records)}")

        pids = set(s.pid for s in target_records)
        if pids:
            print(f"  Target PIDs: {sorted(pids)}")

    # Frame telemetry
    print(f"\n{'=' * 60}")
    print(f"FRAME TELEMETRY")
    print(f"{'=' * 60}")

    if target_records and len(target_records) > 2:
        print(f"\n  Source: {target_name}")
        print(f"  Records: {len(target_records)}")

        metrics = provider.get_process_metrics(target_name)
        if metrics.available:
            # Get monitor refresh rate
            monitor_refresh = "N/A"
            try:
                from app.system.display import display_monitor
                display_info = display_monitor.detect()
                monitor_refresh = f"{display_info.refresh_rate_hz} Hz"
            except Exception:
                pass

            print(f"\n  Present FPS:      {metrics.avg_fps:.1f}")
            print(f"  Monitor Refresh:  {monitor_refresh}")
            print(f"  Median FPS:       {metrics.median_fps:.1f}")
            print(f"  Min FPS:          {metrics.min_fps:.1f}")
            print(f"  Max FPS:          {metrics.max_fps:.1f}")
            print(f"  1% Low:           {metrics.one_percent_low:.1f}")
            print(f"  0.1% Low:         {metrics.point_one_percent_low:.1f}")
            print(f"  Avg Frame Time:   {metrics.avg_frame_time_ms:.2f} ms")
            print(f"  Frame Variance:   {metrics.frame_time_variance:.3f} ms2")
            print(f"  Frame Spikes:     {metrics.frame_spikes}")
            print(f"  Stability:        {metrics.stability_score:.1f}/100")
            print(f"  Samples:          {metrics.sample_count}")
        else:
            print(f"  Metrics: UNAVAILABLE (insufficient data)")
    elif all_samples and len(all_samples) > 2:
        print(f"\n  Source: ALL PROCESSES (no target filter)")
        print(f"  Records: {len(all_samples)}")

        processes = {}
        for s in all_samples:
            pname = getattr(s, "process_name", "unknown")
            if pname not in processes:
                processes[pname] = []
            processes[pname].append(s)

        for pname, records in sorted(
            processes.items(), key=lambda x: -len(x[1])
        )[:5]:
            pids = set(r.pid for r in records)
            avg_ft = sum(r.frame_time_ms for r in records if r.frame_time_ms > 0) / max(1, len(records))
            est_fps = 1000.0 / avg_ft if avg_ft > 0 else 0
            print(f"  {pname}: {len(records)} records, "
                  f"PIDs={sorted(pids)}, "
                  f"avg_frame={avg_ft:.2f}ms, "
                  f"~{est_fps:.0f} Present FPS")
    else:
        print(f"\n  Status: UNAVAILABLE")
        print(f"  Reason: Insufficient frame data captured")
        if not all_samples:
            print(f"  No records received from PresentMon.")
            print(f"  Possible causes:")
            print(f"    - UAC was cancelled")
            print(f"    - ETW session permission denied")
            print(f"    - PresentMon process failed to start")
            if provider.get_error_reason():
                print(f"    - {provider.get_error_reason()}")

    if all_samples:
        print(f"\n  First 5 records:")
        for i, s in enumerate(all_samples[:5]):
            pname = getattr(s, "process_name", "?")
            pid = getattr(s, "pid", 0)
            ft = s.frame_time_ms
            dt = getattr(s, "display_ms", 0)
            print(f"    [{i}] {pname} PID={pid} "
                  f"frame={ft:.2f}ms display={dt:.2f}ms "
                  f"sync={s.sync_interval} mode={s.present_mode}")

    # Cleanup verification
    print(f"\n{'=' * 60}")
    print(f"CLEANUP")
    print(f"{'=' * 60}")

    from app.performance.elevated_launcher import find_presentmon_processes
    remaining = find_presentmon_processes(session_name="PhoenixPerf_")
    if remaining:
        print(f"  WARNING: {len(remaining)} Phoenix PresentMon process(es) still running")
        for p in remaining:
            print(f"    PID={p['pid']} {p['name']}")
    else:
        print(f"  Clean: No stale Phoenix PresentMon processes")

    all_pm = find_presentmon_processes()
    if all_pm:
        print(f"  PresentMon processes on system: {len(all_pm)}")
        for p in all_pm:
            print(f"    PID={p['pid']} {p['name']}")
    else:
        print(f"  No PresentMon processes running")

    # Verify temp CSV cleanup
    temp_dir = os.path.join(os.environ.get("TEMP", os.environ.get("TMP", "")))
    csv_files = [f for f in os.listdir(temp_dir) if f.startswith("phoenix_pm_") and f.endswith(".csv")] if temp_dir and os.path.isdir(temp_dir) else []
    if not csv_files:
        print(f"  TEMP CSV CLEANUP: PASS")
    else:
        print(f"  WARNING: {len(csv_files)} phoenix_pm_*.csv file(s) remain in TEMP:")
        for f in csv_files:
            print(f"    {f}")

    # Summary
    print(f"\n{'=' * 60}")
    print(f"SUMMARY")
    print(f"{'=' * 60}")
    print(f"  PresentMon: {pm_path.name}")
    print(f"  Version: {ver or 'Unknown'}")
    print(f"  Capture Status: {capture_status}")
    print(f"  Target: {target_name or 'NONE'}")
    print(f"  Target PID: {target_pid or 'N/A'}")
    print(f"  Total records: {len(all_samples)}")
    if target_name:
        print(f"  Target records: {len(target_records)}")

    if target_records and len(target_records) > 2:
        metrics = provider.get_process_metrics(target_name)
        if metrics.available:
            print(f"  Present FPS: {metrics.avg_fps:.1f}")
            print(f"  1% Low: {metrics.one_percent_low:.1f}")
            print(f"  0.1% Low: {metrics.point_one_percent_low:.1f}")
            print(f"\n  RESULT: PASS -- Real FPS data captured")
        else:
            print(f"\n  RESULT: FAIL -- Insufficient target data")
    else:
        print(f"\n  RESULT: FAIL -- No target frame data")

    print(f"\n{'=' * 60}")
    print(f"TEST COMPLETE")
    print(f"{'=' * 60}")
