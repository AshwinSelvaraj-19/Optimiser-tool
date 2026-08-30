"""
Optimization Evidence — Evidence-Based Validation Engine (Phase 26)

Validates each optimization by measuring real before/after performance.

Pipeline:
  1. Capture baseline (FPS, CPU, GPU, RAM, frame metrics)
  2. Apply exactly one optimization
  3. Capture post state
  4. Compare measurements
  5. Determine: BENEFICIAL / NEUTRAL / HARMFUL / INCONCLUSIVE
  6. If harmful → safely restore

IMPORTANT:
- Never claim improvement without measured evidence
- Never fabricate performance numbers
- If capture fails → INCONCLUSIVE, not HARMFUL
- If PID changes → INCONCLUSIVE, not HARMFUL
- If insufficient samples → INCONCLUSIVE
- Only rollback genuinely harmful changes

All values originate from real PresentMon and telemetry data.
"""

import json
import os
import time
import statistics
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Tuple
from enum import Enum

from app.utils.logger import get_logger

logger = get_logger("core.optimization_evidence")


# ── Evidence Verdicts ─────────────────────────────────────────

class EvidenceVerdict(Enum):
    """Final verdict for a single optimization test."""
    BENEFICIAL = "BENEFICIAL"         # Measurable improvement
    NEUTRAL = "NEUTRAL"               # No meaningful change
    HARMFUL = "HARMFUL"               # Measurable regression → restore
    INCONCLUSIVE = "INCONCLUSIVE"     # Insufficient data to judge
    SKIPPED = "SKIPPED"              # Not testable (already optimal, etc.)


class CaptureStatus(Enum):
    """Status of a measurement capture."""
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"
    NO_TARGET = "NO_TARGET"
    TIMEOUT = "TIMEOUT"
    UAC_DENIED = "UAC_DENIED"


# ── Measurement Snapshot ──────────────────────────────────────

@dataclass
class MeasurementSnapshot:
    """A point-in-time measurement of system + performance metrics."""
    # Frame metrics (from PresentMon)
    present_fps: Optional[float] = None
    one_percent_low: Optional[float] = None
    zero_point_one_percent_low: Optional[float] = None
    average_frame_time: Optional[float] = None  # ms
    frame_time_variance: Optional[float] = None
    frame_spikes: Optional[int] = None
    stability: Optional[float] = None  # 0-100
    sample_count: int = 0
    capture_duration: float = 0.0  # seconds

    # System metrics (from telemetry)
    cpu_utilization: Optional[float] = None
    gpu_utilization: Optional[float] = None
    ram_percent: Optional[float] = None
    gpu_temp: Optional[float] = None

    # Target
    target_name: str = ""
    target_pid: int = 0

    # Status
    capture_status: CaptureStatus = CaptureStatus.FAILED
    error: str = ""
    timestamp: float = 0.0

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()

    @property
    def is_valid(self) -> bool:
        return (
            self.capture_status == CaptureStatus.COMPLETE
            and self.sample_count > 0
            and self.present_fps is not None
        )

    def to_dict(self) -> dict:
        return {
            "present_fps": self.present_fps,
            "one_percent_low": self.one_percent_low,
            "zero_point_one_percent_low": self.zero_point_one_percent_low,
            "average_frame_time": self.average_frame_time,
            "frame_time_variance": self.frame_time_variance,
            "frame_spikes": self.frame_spikes,
            "stability": self.stability,
            "sample_count": self.sample_count,
            "capture_duration": self.capture_duration,
            "cpu_utilization": self.cpu_utilization,
            "gpu_utilization": self.gpu_utilization,
            "ram_percent": self.ram_percent,
            "gpu_temp": self.gpu_temp,
            "target_name": self.target_name,
            "target_pid": self.target_pid,
            "capture_status": self.capture_status.value,
            "error": self.error,
            "timestamp": self.timestamp,
        }


# ── Optimization Evidence ─────────────────────────────────────

@dataclass
class OptimizationEvidence:
    """Complete evidence record for testing a single optimization."""
    # Optimization identity
    optimization_id: str = ""
    optimization_name: str = ""
    profile_id: str = ""

    # Measurements
    baseline: MeasurementSnapshot = field(default_factory=MeasurementSnapshot)
    post: MeasurementSnapshot = field(default_factory=MeasurementSnapshot)

    # Deltas
    fps_delta: Optional[float] = None
    fps_delta_percent: Optional[float] = None
    one_low_delta: Optional[float] = None
    frame_time_delta: Optional[float] = None
    stability_delta: Optional[float] = None

    # Verdict
    verdict: EvidenceVerdict = EvidenceVerdict.INCONCLUSIVE
    verdict_reason: str = ""

    # Significance thresholds
    fps_significance_threshold: float = 2.0  # FPS change must be > 2 to be significant
    percent_significance_threshold: float = 1.5  # % change must be > 1.5%

    # Action taken
    was_applied: bool = False
    was_rolled_back: bool = False
    rollback_reason: str = ""

    # Metadata
    session_id: str = ""
    test_duration: float = 0.0  # seconds for this test
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()

    @property
    def is_benchmark_valid(self) -> bool:
        return self.baseline.is_valid and self.post.is_valid

    @property
    def same_target(self) -> bool:
        """Check if baseline and post measured the same target PID."""
        if self.baseline.target_pid == 0 or self.post.target_pid == 0:
            return False
        return self.baseline.target_pid == self.post.target_pid

    def calculate_deltas(self):
        """Calculate metric deltas from baseline and post."""
        if not self.baseline.is_valid or not self.post.is_valid:
            return

        # FPS delta
        if self.baseline.present_fps is not None and self.post.present_fps is not None:
            self.fps_delta = self.post.present_fps - self.baseline.present_fps
            if self.baseline.present_fps > 0:
                self.fps_delta_percent = (self.fps_delta / self.baseline.present_fps) * 100

        # 1% Low delta
        if self.baseline.one_percent_low is not None and self.post.one_percent_low is not None:
            self.one_low_delta = self.post.one_percent_low - self.baseline.one_percent_low

        # Frame time delta (lower is better)
        if self.baseline.average_frame_time is not None and self.post.average_frame_time is not None:
            self.frame_time_delta = self.post.average_frame_time - self.baseline.average_frame_time

        # Stability delta
        if self.baseline.stability is not None and self.post.stability is not None:
            self.stability_delta = self.post.stability - self.baseline.stability

    def determine_verdict(self):
        """Determine the verdict based on measured deltas."""
        self.calculate_deltas()

        # Not enough data
        if not self.is_benchmark_valid:
            self.verdict = EvidenceVerdict.INCONCLUSIVE
            self.verdict_reason = "Insufficient benchmark data — baseline or post capture failed"
            return

        # Target changed
        if not self.same_target:
            self.verdict = EvidenceVerdict.INCONCLUSIVE
            self.verdict_reason = (
                f"Target PID changed: {self.baseline.target_pid} → {self.post.target_pid}"
            )
            return

        # Insufficient samples
        if self.baseline.sample_count < 30 or self.post.sample_count < 30:
            self.verdict = EvidenceVerdict.INCONCLUSIVE
            self.verdict_reason = (
                f"Insufficient samples: baseline={self.baseline.sample_count}, "
                f"post={self.post.sample_count} (need ≥30)"
            )
            return

        # Evaluate changes
        fps_change = self.fps_delta or 0.0
        fps_pct = self.fps_delta_percent or 0.0
        one_low_change = self.one_low_delta or 0.0
        ft_change = self.frame_time_delta or 0.0

        # Determine if change is meaningful
        fps_significant = abs(fps_change) > self.fps_significance_threshold or abs(fps_pct) > self.percent_significance_threshold
        one_low_significant = abs(one_low_change) > 1.0  # 1% low change > 1 FPS
        ft_significant = abs(ft_change) > 0.3  # frame time change > 0.3ms

        # HARMFUL: FPS dropped significantly or frame time increased significantly
        if fps_change < -self.fps_significance_threshold and fps_pct < -self.percent_significance_threshold:
            self.verdict = EvidenceVerdict.HARMFUL
            self.verdict_reason = (
                f"FPS decreased by {abs(fps_change):.1f} ({abs(fps_pct):.1f}%) — "
                f"potential regression"
            )
            return

        if ft_change > 0.5 and fps_change < 0:
            self.verdict = EvidenceVerdict.HARMFUL
            self.verdict_reason = (
                f"Frame time increased by {ft_change:.2f}ms with FPS decrease — "
                f"performance regression"
            )
            return

        # BENEFICIAL: FPS increased significantly or 1% low improved
        if fps_change > self.fps_significance_threshold and fps_pct > self.percent_significance_threshold:
            self.verdict = EvidenceVerdict.BENEFICIAL
            self.verdict_reason = (
                f"FPS increased by +{fps_change:.1f} (+{fps_pct:.1f}%) — "
                f"measurable improvement"
            )
            return

        if one_low_change > 2.0 and fps_change >= 0:
            self.verdict = EvidenceVerdict.BENEFICIAL
            self.verdict_reason = (
                f"1% Low improved by +{one_low_change:.1f} — "
                f"reduced stuttering"
            )
            return

        # NEUTRAL: Small or no change
        self.verdict = EvidenceVerdict.NEUTRAL
        self.verdict_reason = (
            f"FPS change {fps_change:+.1f} ({fps_pct:+.1f}%) — "
            f"within noise margin"
        )

    def to_dict(self) -> dict:
        """Serialize for JSON storage."""
        return {
            "optimization_id": self.optimization_id,
            "optimization_name": self.optimization_name,
            "profile_id": self.profile_id,
            "baseline": self.baseline.to_dict(),
            "post": self.post.to_dict(),
            "fps_delta": self.fps_delta,
            "fps_delta_percent": self.fps_delta_percent,
            "one_low_delta": self.one_low_delta,
            "frame_time_delta": self.frame_time_delta,
            "stability_delta": self.stability_delta,
            "verdict": self.verdict.value,
            "verdict_reason": self.verdict_reason,
            "was_applied": self.was_applied,
            "was_rolled_back": self.was_rolled_back,
            "rollback_reason": self.rollback_reason,
            "session_id": self.session_id,
            "test_duration": self.test_duration,
            "timestamp": self.timestamp,
        }


# ── Evidence Session ──────────────────────────────────────────

@dataclass
class EvidenceSession:
    """Complete evidence collection session for one or more optimizations."""
    session_id: str = ""
    profile_id: str = ""
    started_at: str = ""
    completed_at: str = ""
    duration_seconds: float = 0.0

    # Results
    evidence_list: List[OptimizationEvidence] = field(default_factory=list)

    # Summary counts
    beneficial_count: int = 0
    neutral_count: int = 0
    harmful_count: int = 0
    inconclusive_count: int = 0
    skipped_count: int = 0

    # Target
    target_name: str = ""
    target_pid: int = 0

    def __post_init__(self):
        if not self.session_id:
            self.session_id = f"evidence_{uuid.uuid4().hex[:8]}"
        if not self.started_at:
            self.started_at = datetime.now().isoformat()

    def add_evidence(self, evidence: OptimizationEvidence):
        """Add evidence and update counts."""
        self.evidence_list.append(evidence)
        if evidence.verdict == EvidenceVerdict.BENEFICIAL:
            self.beneficial_count += 1
        elif evidence.verdict == EvidenceVerdict.NEUTRAL:
            self.neutral_count += 1
        elif evidence.verdict == EvidenceVerdict.HARMFUL:
            self.harmful_count += 1
        elif evidence.verdict == EvidenceVerdict.INCONCLUSIVE:
            self.inconclusive_count += 1
        elif evidence.verdict == EvidenceVerdict.SKIPPED:
            self.skipped_count += 1

    def finalize(self):
        """Finalize the session."""
        self.completed_at = datetime.now().isoformat()
        try:
            start = datetime.fromisoformat(self.started_at)
            end = datetime.fromisoformat(self.completed_at)
            self.duration_seconds = (end - start).total_seconds()
        except Exception:
            pass

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "profile_id": self.profile_id,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_seconds": self.duration_seconds,
            "target_name": self.target_name,
            "target_pid": self.target_pid,
            "beneficial_count": self.beneficial_count,
            "neutral_count": self.neutral_count,
            "harmful_count": self.harmful_count,
            "inconclusive_count": self.inconclusive_count,
            "skipped_count": self.skipped_count,
            "evidence": [e.to_dict() for e in self.evidence_list],
        }


# ── Evidence Storage ──────────────────────────────────────────

EVIDENCE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "evidence_sessions"
)


def _ensure_evidence_dir():
    os.makedirs(EVIDENCE_DIR, exist_ok=True)


def save_evidence_session(session: EvidenceSession):
    """Save an evidence session to local JSON."""
    _ensure_evidence_dir()
    path = os.path.join(EVIDENCE_DIR, f"{session.session_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(session.to_dict(), f, indent=2, default=str)
    logger.info(f"Evidence session saved: {path}")


def load_evidence_sessions() -> List[EvidenceSession]:
    """Load all saved evidence sessions."""
    _ensure_evidence_dir()
    sessions = []
    for fname in sorted(os.listdir(EVIDENCE_DIR)):
        if fname.endswith(".json"):
            try:
                path = os.path.join(EVIDENCE_DIR, fname)
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                session = EvidenceSession(
                    session_id=data.get("session_id", ""),
                    profile_id=data.get("profile_id", ""),
                    started_at=data.get("started_at", ""),
                    completed_at=data.get("completed_at", ""),
                    duration_seconds=data.get("duration_seconds", 0),
                    target_name=data.get("target_name", ""),
                    target_pid=data.get("target_pid", 0),
                )
                for ev_data in data.get("evidence", []):
                    ev = OptimizationEvidence(
                        optimization_id=ev_data.get("optimization_id", ""),
                        optimization_name=ev_data.get("optimization_name", ""),
                        profile_id=ev_data.get("profile_id", ""),
                        verdict=EvidenceVerdict(ev_data.get("verdict", "INCONCLUSIVE")),
                        verdict_reason=ev_data.get("verdict_reason", ""),
                        fps_delta=ev_data.get("fps_delta"),
                        fps_delta_percent=ev_data.get("fps_delta_percent"),
                        one_low_delta=ev_data.get("one_low_delta"),
                        frame_time_delta=ev_data.get("frame_time_delta"),
                        stability_delta=ev_data.get("stability_delta"),
                        was_applied=ev_data.get("was_applied", False),
                        was_rolled_back=ev_data.get("was_rolled_back", False),
                        timestamp=ev_data.get("timestamp", ""),
                    )
                    session.add_evidence(ev)
                sessions.append(session)
            except Exception as e:
                logger.debug(f"Failed to load {fname}: {e}")
    return sessions


# ── Evidence Engine ───────────────────────────────────────────

class OptimizationEvidenceEngine:
    """
    Validates optimizations by measuring real before/after performance.

    Pipeline:
      1. Capture baseline
      2. Apply one optimization
      3. Capture post
      4. Compare
      5. Verdict
      6. Rollback if harmful
    """

    def __init__(self):
        self._lock = None
        try:
            import threading
            self._lock = threading.Lock()
        except Exception:
            pass

    def capture_baseline(
        self,
        duration: int = 8,
        target_name: str = "",
        target_pid: int = 0,
    ) -> MeasurementSnapshot:
        """Capture a baseline measurement using PresentMon."""
        return self._capture(duration, target_name, target_pid)

    def capture_post(
        self,
        duration: int = 8,
        target_name: str = "",
        target_pid: int = 0,
    ) -> MeasurementSnapshot:
        """Capture a post-optimization measurement."""
        return self._capture(duration, target_name, target_pid)

    def _capture(
        self,
        duration: int,
        target_name: str,
        target_pid: int,
    ) -> MeasurementSnapshot:
        """Run a PresentMon capture and return a measurement snapshot."""
        snap = MeasurementSnapshot(
            target_name=target_name,
            target_pid=target_pid,
        )

        try:
            from app.performance.presentmon_provider import find_presentmon
            pm_path = find_presentmon()
            if not pm_path:
                snap.capture_status = CaptureStatus.FAILED
                snap.error = "PresentMon not found"
                return snap

            # Use PresentMon to capture
            from app.performance.presentmon_provider import PresentMonProvider
            provider = PresentMonProvider(pm_path)

            # Start capture
            success = provider.start_capture(
                duration=duration,
                target_pid=target_pid if target_pid else None,
            )
            if not success:
                snap.capture_status = CaptureStatus.FAILED
                snap.error = "Failed to start PresentMon capture"
                return snap

            # Wait for capture to complete
            csv_path = provider.wait_for_capture(timeout=duration + 15)
            if not csv_path or not os.path.exists(csv_path):
                snap.capture_status = CaptureStatus.FAILED
                snap.error = "No CSV output from PresentMon"
                return snap

            # Parse CSV
            from app.performance.presentmon_provider import parse_presentmon_csv
            frame_records = parse_presentmon_csv(csv_path)

            # Filter to target if specified
            target_records = frame_records
            if target_name:
                target_records = [
                    r for r in frame_records
                    if r.get("Application", "").lower() == target_name.lower()
                ]

            if not target_records:
                snap.capture_status = CaptureStatus.FAILED
                snap.error = f"No records for target: {target_name}"
                return snap

            # Calculate frame metrics
            frame_times = []
            for r in target_records:
                ft = r.get("MsBetweenPresents")
                if ft is not None and ft > 0:
                    frame_times.append(ft)

            if len(frame_times) < 10:
                snap.capture_status = CaptureStatus.FAILED
                snap.error = f"Insufficient frame data: {len(frame_times)} frames"
                return snap

            # Calculate metrics
            snap.sample_count = len(frame_times)
            snap.capture_duration = sum(frame_times) / 1000.0

            # FPS
            avg_ft = statistics.mean(frame_times)
            snap.average_frame_time = avg_ft
            snap.present_fps = 1000.0 / avg_ft if avg_ft > 0 else 0.0

            # Median FPS
            fps_values = [1000.0 / ft for ft in frame_times if ft > 0]
            if fps_values:
                snap.present_fps = statistics.mean(fps_values)

            # 1% Low
            sorted_fps = sorted(fps_values)
            if len(sorted_fps) >= 10:
                idx_1pct = max(1, int(len(sorted_fps) * 0.01))
                snap.one_percent_low = statistics.mean(sorted_fps[:idx_1pct])

                idx_01pct = max(1, int(len(sorted_fps) * 0.001))
                snap.zero_point_one_percent_low = statistics.mean(sorted_fps[:idx_01pct])

            # Variance
            if len(frame_times) > 1:
                snap.frame_time_variance = statistics.variance(frame_times)

            # Spikes (> 2x median)
            median_ft = statistics.median(frame_times)
            snap.frame_spikes = sum(1 for ft in frame_times if ft > median_ft * 2)

            # Stability score (0-100) based on CV
            if avg_ft > 0 and len(frame_times) > 1:
                stdev = statistics.stdev(frame_times)
                cv = stdev / avg_ft
                snap.stability = max(0, min(100, 100 - (cv * 100)))

            snap.capture_status = CaptureStatus.COMPLETE

            # System metrics
            try:
                import psutil
                snap.cpu_utilization = psutil.cpu_percent(interval=0.5)
                vm = psutil.virtual_memory()
                snap.ram_percent = vm.percent
            except Exception:
                pass

            try:
                from app.system.gpu import gpu_monitor
                gpus = gpu_monitor.detect()
                if gpus:
                    gpu = gpu_monitor.update(gpus[0])
                    snap.gpu_utilization = gpu.utilization_percent
                    snap.gpu_temp = gpu.temperature_celsius
            except Exception:
                pass

            # Cleanup CSV
            try:
                os.remove(csv_path)
            except Exception:
                pass

        except Exception as e:
            snap.capture_status = CaptureStatus.FAILED
            snap.error = str(e)
            logger.error(f"Capture failed: {e}")

        return snap

    def validate_optimization(
        self,
        optimization_id: str,
        optimization_name: str,
        profile_id: str = "",
        duration: int = 8,
    ) -> OptimizationEvidence:
        """
        Validate a single optimization end-to-end.

        Pipeline:
          1. Detect target
          2. Capture baseline
          3. Apply optimization
          4. Capture post
          5. Determine verdict
          6. Rollback if harmful
        """
        start_time = time.time()
        evidence = OptimizationEvidence(
            optimization_id=optimization_id,
            optimization_name=optimization_name,
            profile_id=profile_id,
            session_id=f"evidence_{uuid.uuid4().hex[:8]}",
        )

        logger.info(f"[EVIDENCE] Validating: {optimization_name}")

        # Step 1: Detect target
        target_name, target_pid = self._detect_target()
        if not target_name or not target_pid:
            evidence.verdict = EvidenceVerdict.INCONCLUSIVE
            evidence.verdict_reason = "No emulator target detected"
            evidence.test_duration = time.time() - start_time
            logger.info(f"[EVIDENCE] {optimization_name}: INCONCLUSIVE — no target")
            return evidence

        evidence.baseline.target_name = target_name
        evidence.baseline.target_pid = target_pid
        evidence.post.target_name = target_name

        # Step 2: Capture baseline
        logger.info(f"[EVIDENCE] {optimization_name}: Capturing baseline...")
        evidence.baseline = self.capture_baseline(
            duration=duration, target_name=target_name, target_pid=target_pid
        )
        evidence.baseline.target_name = target_name
        evidence.baseline.target_pid = target_pid

        if not evidence.baseline.is_valid:
            evidence.verdict = EvidenceVerdict.INCONCLUSIVE
            evidence.verdict_reason = f"Baseline capture failed: {evidence.baseline.error}"
            evidence.test_duration = time.time() - start_time
            logger.info(f"[EVIDENCE] {optimization_name}: INCONCLUSIVE — baseline failed")
            return evidence

        # Step 3: Apply optimization
        logger.info(f"[EVIDENCE] {optimization_name}: Applying optimization...")
        apply_success = self._apply_single_optimization(optimization_id)
        evidence.was_applied = apply_success

        if not apply_success:
            evidence.verdict = EvidenceVerdict.SKIPPED
            evidence.verdict_reason = "Failed to apply optimization"
            evidence.test_duration = time.time() - start_time
            logger.info(f"[EVIDENCE] {optimization_name}: SKIPPED — apply failed")
            return evidence

        # Step 4: Capture post
        logger.info(f"[EVIDENCE] {optimization_name}: Capturing post-optimization...")
        time.sleep(1.0)  # Allow system to stabilize
        evidence.post = self.capture_post(
            duration=duration, target_name=target_name, target_pid=target_pid
        )
        evidence.post.target_name = target_name

        # Verify target didn't change
        if evidence.post.target_pid != target_pid:
            evidence.post.target_pid = target_pid  # Keep original for comparison

        # Step 5: Determine verdict
        evidence.determine_verdict()

        # Step 6: Rollback if harmful
        if evidence.verdict == EvidenceVerdict.HARMFUL:
            logger.warning(f"[EVIDENCE] {optimization_name}: HARMFUL — rolling back")
            rollback_success = self._rollback_single_optimization(optimization_id)
            evidence.was_rolled_back = rollback_success
            evidence.rollback_reason = (
                "Automatically rolled back due to performance regression"
                if rollback_success else
                "Rollback attempted but may have failed"
            )

        evidence.test_duration = time.time() - start_time

        logger.info(
            f"[EVIDENCE] {optimization_name}: {evidence.verdict.value} — "
            f"{evidence.verdict_reason}"
        )
        return evidence

    def validate_profile(
        self,
        profile_id: str,
        optimization_ids: List[str],
        optimization_names: Dict[str, str],
        duration: int = 8,
    ) -> EvidenceSession:
        """
        Validate all optimizations in a profile sequentially.

        Returns an EvidenceSession with results for each optimization.
        """
        session = EvidenceSession(
            profile_id=profile_id,
        )

        target_name, target_pid = self._detect_target()
        session.target_name = target_name
        session.target_pid = target_pid

        for opt_id in optimization_ids:
            opt_name = optimization_names.get(opt_id, opt_id)

            # Skip non-applicable optimizations
            if not self._is_optimization_applicable(opt_id):
                evidence = OptimizationEvidence(
                    optimization_id=opt_id,
                    optimization_name=opt_name,
                    profile_id=profile_id,
                    verdict=EvidenceVerdict.SKIPPED,
                    verdict_reason="Not applicable or already optimal",
                )
                session.add_evidence(evidence)
                continue

            evidence = self.validate_optimization(
                optimization_id=opt_id,
                optimization_name=opt_name,
                profile_id=profile_id,
                duration=duration,
            )
            session.add_evidence(evidence)

        session.finalize()
        save_evidence_session(session)
        return session

    def _detect_target(self) -> Tuple[str, int]:
        """Detect current emulator target."""
        try:
            from app.performance.target_process import target_process_detector
            best = target_process_detector.select_best_target()
            if best:
                return best.process_name, best.pid
        except Exception as e:
            logger.debug(f"Target detection: {e}")
        return "", 0

    def _is_optimization_applicable(self, opt_id: str) -> bool:
        """Check if an optimization is applicable before testing."""
        try:
            from app.core.optimizations import get_optimization_by_id
            opt = get_optimization_by_id(opt_id)
            if not opt:
                return False
            check = opt.check()
            return check.status.value in ("OPTIMIZABLE", "CHECKED")
        except Exception:
            return False

    def _apply_single_optimization(self, opt_id: str) -> bool:
        """Apply a single optimization and verify."""
        try:
            from app.core.optimizations import get_optimization_by_id
            opt = get_optimization_by_id(opt_id)
            if not opt:
                return False

            # Snapshot
            try:
                opt.snapshot()
            except Exception:
                pass

            # Apply
            result = opt.apply()
            if result.status.value != "APPLIED":
                return False

            # Verify
            time.sleep(0.3)
            verified = opt.verify()
            return verified

        except Exception as e:
            logger.error(f"Apply failed for {opt_id}: {e}")
            return False

    def _rollback_single_optimization(self, opt_id: str) -> bool:
        """Rollback a single optimization."""
        try:
            from app.core.optimizations import get_optimization_by_id
            opt = get_optimization_by_id(opt_id)
            if not opt:
                return False

            result = opt.restore()
            return result.status.value in ("VERIFIED", "REVERTED", "APPLIED")

        except Exception as e:
            logger.error(f"Rollback failed for {opt_id}: {e}")
            return False


# ── Singleton ─────────────────────────────────────────────────

optimization_evidence_engine = OptimizationEvidenceEngine()
