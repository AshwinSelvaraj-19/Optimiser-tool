"""
Optimization benchmark — before/after performance measurement.

Workflow:
  1. Detect target
  2. Baseline benchmark (PresentMon capture)
  3. Apply optimization profile
  4. Verify optimizations
  5. Post-optimization benchmark
  6. Compare results
  7. Report

Every number comes from real PresentMon frame data.
No fabricated values.
"""

import json
import os
import time
from datetime import datetime
from typing import Optional, Callable

from app.performance.benchmark_models import BenchmarkResult, BenchmarkComparison
from app.utils.logger import get_logger

logger = get_logger("performance.optimize_benchmark")

BENCHMARKS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "benchmarks"
)


def run_benchmark_capture(
    target_process: str = "",
    target_pid: int = 0,
    duration: int = 15,
    monitor_refresh: int = 0,
) -> BenchmarkResult:
    """
    Run a single PresentMon benchmark capture.

    Returns a BenchmarkResult with real measured data.
    If PresentMon cannot capture data, returns UNAVAILABLE.
    """
    from app.performance.presentmon_provider import PresentMonProvider, find_presentmon
    from app.performance.elevated_launcher import kill_stale_phoenix_sessions
    from app.performance.target_process import target_process_detector

    # Detect target if not specified
    if not target_process:
        best = target_process_detector.select_best_target()
        if best:
            target_process = best.process_name
            target_pid = best.pid
        else:
            return BenchmarkResult.no_target()

    # Check PresentMon
    pm_path = find_presentmon()
    if not pm_path:
        return BenchmarkResult.unavailable(
            reason="PresentMon not found",
            target=target_process,
            pid=target_pid,
        )

    # Get monitor refresh rate
    if not monitor_refresh:
        try:
            from app.system.display import display_monitor
            display_info = display_monitor.detect()
            monitor_refresh = display_info.refresh_rate_hz
        except Exception:
            pass

    # Clean stale sessions
    kill_stale_phoenix_sessions("PhoenixPerf_")
    time.sleep(0.5)

    # Create and start provider
    provider = PresentMonProvider()
    available, reason = provider.is_available()
    if not available:
        return BenchmarkResult.unavailable(
            reason=reason, target=target_process, pid=target_pid,
        )

    start_ok = provider.start(
        target_process=target_process,
        duration=duration,
    )
    if not start_ok:
        return BenchmarkResult.failed(
            reason=provider.get_error_reason(),
            target=target_process,
            pid=target_pid,
        )

    # Wait for capture to complete
    logger.info(f"Benchmark capture: {target_process} PID {target_pid} for {duration}s")
    time.sleep(duration + 8)  # Allow PresentMon to finish + flush

    # Stop and parse
    provider.stop()
    samples = provider.get_samples()
    sample_count = len(samples)

    if sample_count == 0:
        return BenchmarkResult(
            target_name=target_process,
            target_pid=target_pid,
            duration_seconds=duration,
            sample_count=0,
            monitor_refresh_hz=monitor_refresh,
            capture_status="FAILED",
            error="PresentMon produced no frame samples",
        )

    # Get metrics for the target process
    if target_process:
        metrics = provider.get_process_metrics(target_process)
    else:
        metrics = provider.get_metrics()

    if not metrics.available:
        return BenchmarkResult(
            target_name=target_process,
            target_pid=target_pid,
            duration_seconds=duration,
            sample_count=sample_count,
            monitor_refresh_hz=monitor_refresh,
            capture_status="FAILED",
            error="FPS metrics calculation failed",
        )

    # Get the actual PID from samples if available
    detected_pid = provider.get_target_pid() or target_pid

    result = BenchmarkResult(
        target_name=target_process,
        target_pid=detected_pid,
        duration_seconds=duration,
        sample_count=sample_count,
        monitor_refresh_hz=monitor_refresh,
        capture_status="COMPLETE",
        present_fps=round(metrics.avg_fps, 1),
        median_fps=round(metrics.median_fps, 1),
        min_fps=round(metrics.min_fps, 1),
        max_fps=round(metrics.max_fps, 1),
        one_percent_low=round(metrics.one_percent_low, 1),
        zero_point_one_percent_low=round(metrics.point_one_percent_low, 1),
        average_frame_time=round(metrics.avg_frame_time_ms, 2),
        frame_time_variance=round(metrics.frame_time_variance, 3),
        frame_spikes=metrics.frame_spikes,
        stability=round(metrics.stability_score, 1),
    )

    logger.info(
        f"Benchmark complete: {result.present_fps:.1f} FPS, "
        f"1% Low {result.one_percent_low:.1f}, "
        f"{result.sample_count} samples"
    )

    # Cleanup
    kill_stale_phoenix_sessions("PhoenixPerf_")

    return result


def run_optimization_benchmark(
    profile_id: str = "gaming",
    duration: int = 15,
    progress_callback: Optional[Callable] = None,
) -> BenchmarkComparison:
    """
    Full optimization benchmark workflow:
      1. Baseline benchmark
      2. Apply profile
      3. Post-optimization benchmark
      4. Compare

    Returns a BenchmarkComparison with real before/after data.
    """
    def _progress(pct: float, msg: str = ""):
        logger.info(f"[{pct*100:.0f}%] {msg}")
        if progress_callback:
            progress_callback(pct, msg)

    _progress(0.0, "Starting optimization benchmark...")

    # Step 1: Baseline benchmark
    _progress(0.05, "Running baseline benchmark...")
    baseline = run_benchmark_capture(duration=duration)
    _progress(0.35, f"Baseline: {baseline.present_fps or 'N/A'} FPS ({baseline.sample_count} samples)")

    if not baseline.is_valid:
        _progress(1.0, f"Baseline failed: {baseline.error}")
        return BenchmarkComparison(
            before=baseline,
            after=BenchmarkResult.unavailable(reason="Baseline failed"),
            result="INCONCLUSIVE",
        )

    # Step 2: Apply optimization profile
    _progress(0.40, f"Applying {profile_id} profile...")
    from app.core.optimizer import optimizer
    opt_report = optimizer.apply_profile(profile_id)

    applied_names = [
        r.name for r in opt_report.results if r.status == "APPLIED"
    ]
    _progress(0.60, f"Applied: {len(applied_names)} optimizations")

    # Step 3: Post-optimization benchmark
    _progress(0.65, "Running post-optimization benchmark...")
    # Wait for system to stabilize after optimization
    time.sleep(2)
    post = run_benchmark_capture(duration=duration)
    _progress(0.95, f"After: {post.present_fps or 'N/A'} FPS ({post.sample_count} samples)")

    # Step 4: Compare
    _progress(0.98, "Comparing results...")
    comparison = BenchmarkComparison(
        before=baseline,
        after=post,
        optimizations_applied=applied_names,
    )

    _progress(1.0, f"Result: {comparison.result}")

    # Save report
    _save_report(comparison, profile_id)

    return comparison


def run_optimization_benchmark_cli(
    profile_id: str = "gaming",
    duration: int = 15,
):
    """CLI interface for the optimization benchmark."""
    from app.utils.logger import setup_logging
    setup_logging()
    os.makedirs(BENCHMARKS_DIR, exist_ok=True)

    def _print_progress(pct: float, msg: str):
        bar_len = 30
        filled = int(bar_len * pct)
        bar = "=" * filled + "-" * (bar_len - filled)
        print(f"\r  [{bar}] {pct*100:.0f}% {msg}", end="", flush=True)
        if pct >= 1.0:
            print()

    comparison = run_optimization_benchmark(
        profile_id=profile_id,
        duration=duration,
        progress_callback=_print_progress,
    )

    from app.performance.benchmark_models import format_comparison_table
    print(format_comparison_table(comparison))


def _save_report(comparison: BenchmarkComparison, profile_id: str):
    """Save comparison report to JSON."""
    try:
        os.makedirs(BENCHMARKS_DIR, exist_ok=True)
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = os.path.join(
            BENCHMARKS_DIR,
            f"opt_benchmark_{profile_id}_{timestamp_str}.json",
        )
        with open(report_path, "w") as f:
            json.dump(comparison.to_dict(), f, indent=2, default=str)
        logger.info(f"Optimization benchmark report saved: {report_path}")
    except Exception as e:
        logger.error(f"Failed to save benchmark report: {e}")
