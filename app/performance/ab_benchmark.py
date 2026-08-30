"""
A/B Benchmark engine — repeated measurement with reliability analysis.

Workflow:
  1. Repeated baseline captures (configurable count)
  2. Apply optimization profile
  3. Repeated optimized captures
  4. Outlier detection (IQR)
  5. Median aggregation
  6. Delta calculation
  7. Confidence classification
  8. Deterministic result

Every number comes from real PresentMon frame data.
"""

import json
import os
import time
from datetime import datetime
from typing import Optional, Callable, List

from app.performance.benchmark_models import BenchmarkResult
from app.performance.ab_models import (
    BenchmarkRun,
    RepeatedBenchmark,
    BenchmarkStatistics,
    ABComparison,
    BenchmarkReliability,
    detect_outliers_iqr,
    classify_reliability,
)
from app.utils.logger import get_logger

logger = get_logger("performance.ab_benchmark")

BENCHMARKS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "benchmarks"
)


def _single_capture(
    target_process: str,
    target_pid: int,
    duration: int,
    monitor_refresh: int,
) -> BenchmarkResult:
    """Run a single PresentMon capture. Returns real BenchmarkResult."""
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
            target=target_process, pid=target_pid,
        )

    # Get monitor refresh
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

    # Start PresentMon
    provider = PresentMonProvider()
    available, reason = provider.is_available()
    if not available:
        return BenchmarkResult.unavailable(
            reason=reason, target=target_process, pid=target_pid,
        )

    start_ok = provider.start(target_process=target_process, duration=duration)
    if not start_ok:
        return BenchmarkResult.failed(
            reason=provider.get_error_reason(),
            target=target_process, pid=target_pid,
        )

    # Wait for capture
    logger.info(f"Capture: {target_process} PID {target_pid} ({duration}s)")
    time.sleep(duration + 8)

    # Stop and parse
    provider.stop()
    samples = provider.get_samples()

    if len(samples) == 0:
        return BenchmarkResult(
            target_name=target_process, target_pid=target_pid,
            duration_seconds=duration, sample_count=0,
            monitor_refresh_hz=monitor_refresh,
            capture_status="FAILED", error="No frame samples",
        )

    # Get metrics for target
    metrics = provider.get_process_metrics(target_process) if target_process else provider.get_metrics()
    if not metrics.available:
        return BenchmarkResult(
            target_name=target_process, target_pid=target_pid,
            duration_seconds=duration, sample_count=len(samples),
            monitor_refresh_hz=monitor_refresh,
            capture_status="FAILED", error="Metrics calculation failed",
        )

    detected_pid = provider.get_target_pid() or target_pid

    result = BenchmarkResult(
        target_name=target_process,
        target_pid=detected_pid,
        duration_seconds=duration,
        sample_count=len(samples),
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

    # Cleanup
    kill_stale_phoenix_sessions("PhoenixPerf_")

    return result


def run_repeated_benchmark(
    target_process: str = "",
    target_pid: int = 0,
    duration: int = 15,
    runs: int = 3,
    monitor_refresh: int = 0,
    label: str = "",
    progress_callback: Optional[Callable] = None,
) -> RepeatedBenchmark:
    """
    Run multiple benchmark captures.
    Returns RepeatedBenchmark with all runs including outliers.
    """
    def _progress(pct: float, msg: str = ""):
        if progress_callback:
            progress_callback(pct, msg)

    repeated = RepeatedBenchmark(label=label)

    for i in range(runs):
        _progress(0, f"Run {i+1}/{runs} ({label})...")

        result = _single_capture(
            target_process=target_process,
            target_pid=target_pid,
            duration=duration,
            monitor_refresh=monitor_refresh,
        )

        run = BenchmarkRun(run_index=i, result=result)

        # Update target PID from first successful run
        if result.is_valid and not target_pid:
            target_pid = result.target_pid
            target_process = result.target_name

        repeated.runs.append(run)

        status = "OK" if result.is_valid else f"FAIL: {result.error}"
        logger.info(f"  Run {i+1}: {status}")

    # Outlier detection on FPS values from valid runs
    fps_values = [
        r.result.present_fps for r in repeated.valid_runs
        if r.result and r.result.present_fps is not None
    ]
    if len(fps_values) >= 4:
        outliers = detect_outliers_iqr(fps_values)
        valid_runs = repeated.valid_runs
        for idx, is_outlier in enumerate(outliers):
            if is_outlier:
                valid_runs[idx].is_outlier = True
                valid_runs[idx].outlier_reason = (
                    f"FPS outlier: {fps_values[idx]:.1f} "
                    f"(IQR detection)"
                )

    return repeated


def aggregate_repeated(
    repeated: RepeatedBenchmark,
) -> dict:
    """
    Aggregate valid runs into BenchmarkStatistics per metric.
    Returns dict of metric_name -> BenchmarkStatistics.
    """
    valid = repeated.valid_runs
    if not valid:
        return {}

    def _extract(metric_name: str) -> List[float]:
        values = []
        for r in valid:
            if r.result:
                val = getattr(r.result, metric_name, None)
                if val is not None:
                    values.append(float(val))
        return values

    metrics = [
        "present_fps", "median_fps", "one_percent_low",
        "zero_point_one_percent_low", "average_frame_time",
        "frame_time_variance", "stability",
    ]

    stats = {}
    for metric in metrics:
        values = _extract(metric)
        if values:
            stats[metric] = BenchmarkStatistics(
                values=values, label=f"{repeated.label}_{metric}"
            )

    return stats


def compute_ab_comparison(
    baseline: RepeatedBenchmark,
    optimized: RepeatedBenchmark,
    optimizations_applied: List[str] = None,
) -> ABComparison:
    """
    Compute A/B comparison from repeated benchmarks.
    Uses MEDIAN as primary comparison value (robust to outliers).
    """
    ab = ABComparison(
        baseline=baseline,
        optimized=optimized,
        optimizations_applied=optimizations_applied or [],
    )

    # Aggregate
    bl_stats = aggregate_repeated(baseline)
    op_stats = aggregate_repeated(optimized)
    ab.baseline_stats = bl_stats
    ab.optimized_stats = op_stats

    # Compute deltas using medians
    bl_fps = bl_stats.get("present_fps")
    op_fps = op_stats.get("present_fps")
    if bl_fps and op_fps and bl_fps.median and op_fps.median:
        ab.fps_delta = op_fps.median - bl_fps.median
        ab.fps_percent = _safe_pct(ab.fps_delta, bl_fps.median)

    bl_low1 = bl_stats.get("one_percent_low")
    op_low1 = op_stats.get("one_percent_low")
    if bl_low1 and op_low1 and bl_low1.median and op_low1.median:
        ab.one_low_delta = op_low1.median - bl_low1.median
        ab.one_low_percent = _safe_pct(ab.one_low_delta, bl_low1.median)

    bl_low01 = bl_stats.get("zero_point_one_percent_low")
    op_low01 = op_stats.get("zero_point_one_percent_low")
    if bl_low01 and op_low01 and bl_low01.median and op_low01.median:
        ab.zero_low_delta = op_low01.median - bl_low01.median
        ab.zero_low_percent = _safe_pct(ab.zero_low_delta, bl_low01.median)

    bl_ft = bl_stats.get("average_frame_time")
    op_ft = op_stats.get("average_frame_time")
    if bl_ft and op_ft and bl_ft.median and op_ft.median:
        ab.frame_time_delta = op_ft.median - bl_ft.median

    bl_var = bl_stats.get("frame_time_variance")
    op_var = op_stats.get("frame_time_variance")
    if bl_var and op_var and bl_var.median and op_var.median:
        ab.frame_variance_delta = op_var.median - bl_var.median

    bl_stab = bl_stats.get("stability")
    op_stab = op_stats.get("stability")
    if bl_stab and op_stab and bl_stab.median and op_stab.median:
        ab.stability_delta = op_stab.median - bl_stab.median

    # Classify reliability
    bl_cv = bl_fps.cv if bl_fps else None
    op_cv = op_fps.cv if op_fps else None
    reliability = classify_reliability(baseline, optimized, bl_cv, op_cv)
    ab.confidence = reliability.level

    # Determine result
    ab.result = _determine_result(ab, reliability)

    return ab


def _determine_result(ab: ABComparison, reliability: BenchmarkReliability) -> str:
    """
    Determine result using median deltas and reliability.
    Only claim improvement when confidence supports it.
    """
    if reliability.level == "INCONCLUSIVE":
        return "INCONCLUSIVE"

    improvements = 0
    regressions = 0

    # FPS: >= 1% median change
    if ab.fps_percent is not None:
        if ab.fps_percent >= 1.0:
            improvements += 1
        elif ab.fps_percent <= -1.0:
            regressions += 1

    # 1% Low: >= 3% median change
    if ab.one_low_percent is not None:
        if ab.one_low_percent >= 3.0:
            improvements += 1
        elif ab.one_low_percent <= -3.0:
            regressions += 1

    # Frame time: >= 3% change (negative = improvement)
    if ab.frame_time_delta is not None:
        bl_ft = ab.baseline_stats.get("average_frame_time") if ab.baseline_stats else None
        if bl_ft and bl_ft.median:
            ft_pct = (ab.frame_time_delta / bl_ft.median) * 100
            if ft_pct <= -3.0:
                improvements += 1
            elif ft_pct >= 3.0:
                regressions += 1

    # Stability: >= 5 points
    if ab.stability_delta is not None:
        if ab.stability_delta >= 5.0:
            improvements += 1
        elif ab.stability_delta <= -5.0:
            regressions += 1

    if improvements > 0 and regressions == 0:
        return "IMPROVED"
    elif regressions > 0 and improvements == 0:
        return "DEGRADED"
    elif improvements > 0 and regressions > 0:
        return "IMPROVED" if improvements > regressions else (
            "DEGRADED" if regressions > improvements else "UNCHANGED"
        )
    else:
        return "UNCHANGED"


def _safe_pct(delta: float, base: float) -> Optional[float]:
    if base == 0:
        return None
    return (delta / abs(base)) * 100.0


# ── Full A/B workflow ─────────────────────────────────────────

def run_ab_benchmark(
    profile_id: str = "gaming",
    duration: int = 15,
    runs: int = 3,
    progress_callback: Optional[Callable] = None,
) -> ABComparison:
    """
    Full A/B benchmark workflow:
      1. Detect target
      2. Repeated baseline
      3. Apply profile
      4. Repeated optimized
      5. Compare + classify
    """
    def _progress(pct: float, msg: str = ""):
        logger.info(f"[{pct*100:.0f}%] {msg}")
        if progress_callback:
            progress_callback(pct, msg)

    _progress(0.0, "Starting A/B benchmark...")

    # Detect target
    from app.performance.target_process import target_process_detector
    best = target_process_detector.select_best_target()
    if not best:
        _progress(1.0, "No emulator detected")
        return ABComparison(result="INCONCLUSIVE", confidence="INCONCLUSIVE")

    target_process = best.process_name
    target_pid = best.pid
    monitor_refresh = 0
    try:
        from app.system.display import display_monitor
        monitor_refresh = display_monitor.detect().refresh_rate_hz
    except Exception:
        pass

    _progress(0.02, f"Target: {target_process} PID {target_pid}")

    # Step 1: Repeated baseline
    _progress(0.05, f"Running {runs} baseline captures...")
    baseline = run_repeated_benchmark(
        target_process=target_process,
        target_pid=target_pid,
        duration=duration,
        runs=runs,
        monitor_refresh=monitor_refresh,
        label="baseline",
        progress_callback=lambda p, m: _progress(0.05 + p * 0.30, m),
    )

    _progress(0.35, f"Baseline: {baseline.valid_count}/{baseline.total_count} valid")

    if baseline.valid_count < 2:
        _progress(1.0, "Insufficient baseline data")
        return ABComparison(
            baseline=baseline,
            result="INCONCLUSIVE",
            confidence="INCONCLUSIVE",
        )

    # Step 2: Apply optimization
    _progress(0.40, f"Applying {profile_id} profile...")
    from app.core.optimizer import optimizer
    opt_report = optimizer.apply_profile(profile_id)
    applied_names = [r.name for r in opt_report.results if r.status == "APPLIED"]
    _progress(0.50, f"Applied: {len(applied_names)} optimizations")

    # Wait for system to stabilize
    time.sleep(3)

    # Step 3: Repeated optimized
    _progress(0.55, f"Running {runs} optimized captures...")
    optimized = run_repeated_benchmark(
        target_process=target_process,
        target_pid=target_pid,
        duration=duration,
        runs=runs,
        monitor_refresh=monitor_refresh,
        label="optimized",
        progress_callback=lambda p, m: _progress(0.55 + p * 0.35, m),
    )

    _progress(0.90, f"Optimized: {optimized.valid_count}/{optimized.total_count} valid")

    # Step 4: Compare
    _progress(0.95, "Computing A/B comparison...")
    ab = compute_ab_comparison(baseline, optimized, applied_names)

    _progress(1.0, f"Result: {ab.result} (Confidence: {ab.confidence})")

    # Save report
    _save_ab_report(ab, profile_id)

    return ab


def _save_ab_report(ab: ABComparison, profile_id: str):
    """Save A/B report to JSON."""
    try:
        os.makedirs(BENCHMARKS_DIR, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(BENCHMARKS_DIR, f"ab_{profile_id}_{ts}.json")
        with open(path, "w") as f:
            json.dump(ab.to_dict(), f, indent=2, default=str)
        logger.info(f"A/B report saved: {path}")
    except Exception as e:
        logger.error(f"Failed to save A/B report: {e}")


def run_ab_benchmark_cli(
    profile_id: str = "gaming",
    duration: int = 15,
    runs: int = 3,
):
    """CLI interface for A/B benchmark."""
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

    ab = run_ab_benchmark(
        profile_id=profile_id,
        duration=duration,
        runs=runs,
        progress_callback=_print_progress,
    )

    from app.performance.ab_models import format_ab_table
    print(format_ab_table(ab))
