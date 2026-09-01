"""
Phase 60 — System Health Scoring Engine.

Calculate a meaningful 0-100 system health score based on measurable
conditions. Every deduction has an explainable contributing factor.

Categories:
  PERFORMANCE — CPU/GPU utilization headroom
  THERMAL — GPU/CPU temperature status
  MEMORY — RAM pressure and availability
  STORAGE — Disk free space and pressure
  BACKGROUND LOAD — Non-essential process resource consumption
  GAMING READINESS — Emulator detected, FPS available, optimization state

Rules:
  - Do NOT create arbitrary scores to make the UI look impressive
  - Every score must have explainable contributing factors
  - Recommendations must directly correspond to the factors
  - Every value comes from real measurements
  - NOT_AVAILABLE for unmeasurable metrics
"""

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

from app.utils.logger import get_logger

logger = get_logger("core.health_engine")


# ── Enums ────────────────────────────────────────────────────────


class HealthCategory(Enum):
    """Health scoring categories."""
    PERFORMANCE = "PERFORMANCE"
    THERMAL = "THERMAL"
    MEMORY = "MEMORY"
    STORAGE = "STORAGE"
    BACKGROUND_LOAD = "BACKGROUND_LOAD"
    GAMING_READINESS = "GAMING_READINESS"


class IssueSeverity(Enum):
    """Severity of a health issue."""
    NONE = "NONE"
    MINOR = "MINOR"
    MODERATE = "MODERATE"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


# ── Data Models ────────────────────────────────────────────────────


@dataclass
class HealthMetric:
    """A single health measurement with score contribution."""
    category: HealthCategory = HealthCategory.PERFORMANCE
    name: str = ""
    description: str = ""

    # Measured value
    measured_value: Optional[float] = None
    measured_unit: str = ""
    available: bool = False

    # Scoring
    base_score: float = 100.0  # max possible for this metric
    deduction: float = 0.0  # points deducted
    final_score: float = 100.0  # base - deduction

    # Explanation
    explanation: str = ""
    recommendation: str = ""

    @property
    def has_deduction(self) -> bool:
        return self.deduction > 0

    def to_dict(self) -> dict:
        return {
            "category": self.category.value,
            "name": self.name,
            "description": self.description,
            "measured_value": self.measured_value,
            "measured_unit": self.measured_unit,
            "available": self.available,
            "base_score": self.base_score,
            "deduction": self.deduction,
            "final_score": self.final_score,
            "explanation": self.explanation,
            "recommendation": self.recommendation,
        }


@dataclass
class HealthIssue:
    """A specific health issue that causes a score deduction."""
    category: HealthCategory = HealthCategory.PERFORMANCE
    severity: IssueSeverity = IssueSeverity.NONE
    title: str = ""
    explanation: str = ""
    deduction: float = 0.0
    measured_value: Optional[float] = None
    threshold: Optional[float] = None
    recommendation: str = ""

    def to_dict(self) -> dict:
        return {
            "category": self.category.value,
            "severity": self.severity.value,
            "title": self.title,
            "explanation": self.explanation,
            "deduction": self.deduction,
            "measured_value": self.measured_value,
            "threshold": self.threshold,
            "recommendation": self.recommendation,
        }


@dataclass
class HealthScore:
    """Complete health score with all contributing factors."""
    timestamp: float = 0.0
    overall_score: float = 100.0
    category_scores: Dict[str, float] = field(default_factory=dict)
    metrics: List[HealthMetric] = field(default_factory=list)
    issues: List[HealthIssue] = field(default_factory=list)

    # Metadata
    confidence: float = 0.0  # 0-100, how confident we are in the score
    data_completeness: float = 0.0  # % of metrics that were actually measured

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()

    @property
    def grade(self) -> str:
        if self.overall_score >= 90:
            return "EXCELLENT"
        if self.overall_score >= 75:
            return "GOOD"
        if self.overall_score >= 60:
            return "FAIR"
        if self.overall_score >= 40:
            return "POOR"
        return "CRITICAL"

    @property
    def grade_color(self) -> str:
        if self.overall_score >= 90:
            return "#4CAF50"
        if self.overall_score >= 75:
            return "#8BC34A"
        if self.overall_score >= 60:
            return "#FF9800"
        if self.overall_score >= 40:
            return "#FF5722"
        return "#F44336"

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "overall_score": self.overall_score,
            "grade": self.grade,
            "category_scores": self.category_scores,
            "metrics": [m.to_dict() for m in self.metrics],
            "issues": [i.to_dict() for i in self.issues],
            "confidence": self.confidence,
            "data_completeness": self.data_completeness,
        }


# ══════════════════════════════════════════════════════════════════
# Health Engine
# ══════════════════════════════════════════════════════════════════


class HealthEngine:
    """
    Calculates system health from measurable conditions.
    Every deduction has an explainable cause.
    """

    def __init__(self):
        self._last_score: Optional[HealthScore] = None

    @property
    def last_score(self) -> Optional[HealthScore]:
        return self._last_score

    def calculate(self, context: Optional[Dict] = None) -> HealthScore:
        """
        Calculate the full system health score.
        If context not provided, collects from live telemetry.
        """
        if context is None:
            context = self._collect_context()

        score = HealthScore()
        metrics = []
        issues = []
        category_scores = {}

        # ── PERFORMANCE ──────────────────────────────────
        perf_metrics, perf_issues = self._score_performance(context)
        metrics.extend(perf_metrics)
        issues.extend(perf_issues)
        category_scores["PERFORMANCE"] = self._category_score(perf_metrics)

        # ── THERMAL ──────────────────────────────────────
        thermal_metrics, thermal_issues = self._score_thermal(context)
        metrics.extend(thermal_metrics)
        issues.extend(thermal_issues)
        category_scores["THERMAL"] = self._category_score(thermal_metrics)

        # ── MEMORY ───────────────────────────────────────
        mem_metrics, mem_issues = self._score_memory(context)
        metrics.extend(mem_metrics)
        issues.extend(mem_issues)
        category_scores["MEMORY"] = self._category_score(mem_metrics)

        # ── STORAGE ──────────────────────────────────────
        stor_metrics, stor_issues = self._score_storage(context)
        metrics.extend(stor_metrics)
        issues.extend(stor_issues)
        category_scores["STORAGE"] = self._category_score(stor_metrics)

        # ── BACKGROUND LOAD ──────────────────────────────
        bg_metrics, bg_issues = self._score_background(context)
        metrics.extend(bg_metrics)
        issues.extend(bg_issues)
        category_scores["BACKGROUND_LOAD"] = self._category_score(bg_metrics)

        # ── GAMING READINESS ─────────────────────────────
        game_metrics, game_issues = self._score_gaming_readiness(context)
        metrics.extend(game_metrics)
        issues.extend(game_issues)
        category_scores["GAMING_READINESS"] = self._category_score(game_metrics)

        # ── Compute overall ──────────────────────────────
        total_deduction = sum(i.deduction for i in issues)
        score.overall_score = max(0.0, 100.0 - total_deduction)
        score.category_scores = category_scores
        score.metrics = metrics
        score.issues = issues

        # Confidence based on data completeness
        available_metrics = sum(1 for m in metrics if m.available)
        total_metrics = len(metrics) if metrics else 1
        score.data_completeness = (available_metrics / total_metrics) * 100
        score.confidence = score.data_completeness

        self._last_score = score
        return score

    # ── Category Scorers ──────────────────────────────────────

    def _score_performance(self, ctx: Dict) -> Tuple[List[HealthMetric], List[HealthIssue]]:
        """Score CPU/GPU utilization headroom."""
        metrics = []
        issues = []

        # CPU headroom
        cpu = ctx.get("cpu_percent")
        m = HealthMetric(
            category=HealthCategory.PERFORMANCE,
            name="CPU Headroom",
            description="Available CPU capacity",
            measured_value=cpu, measured_unit="%",
            available=cpu is not None and cpu > 0,
        )
        if cpu is not None and cpu > 0:
            m.final_score = max(0, 100 - max(0, cpu - 70) * 2)
            m.deduction = max(0, cpu - 70) * 2 if cpu > 70 else 0
            m.explanation = f"CPU at {cpu:.0f}%"
            if cpu > 90:
                m.recommendation = "CPU is saturated. Close unnecessary background processes."
                issues.append(HealthIssue(
                    category=HealthCategory.PERFORMANCE,
                    severity=IssueSeverity.CRITICAL,
                    title="CPU saturated",
                    explanation=f"CPU at {cpu:.0f}%. Frame delivery may be affected.",
                    deduction=m.deduction,
                    measured_value=cpu, threshold=90.0,
                    recommendation="Close unnecessary background processes.",
                ))
            elif cpu > 80:
                m.recommendation = "CPU is high. Monitor for frame drops."
                issues.append(HealthIssue(
                    category=HealthCategory.PERFORMANCE,
                    severity=IssueSeverity.MODERATE,
                    title="CPU utilization high",
                    explanation=f"CPU at {cpu:.0f}%.",
                    deduction=m.deduction,
                    measured_value=cpu, threshold=80.0,
                ))
        else:
            m.explanation = "CPU data not available"
            m.final_score = 80  # neutral deduction for missing data
        metrics.append(m)

        # GPU headroom
        gpu = ctx.get("gpu_percent")
        m2 = HealthMetric(
            category=HealthCategory.PERFORMANCE,
            name="GPU Headroom",
            description="Available GPU capacity",
            measured_value=gpu, measured_unit="%",
            available=gpu is not None and gpu > 0,
        )
        if gpu is not None and gpu > 0:
            m2.final_score = max(0, 100 - max(0, gpu - 85) * 3)
            m2.deduction = max(0, gpu - 85) * 3 if gpu > 85 else 0
            m2.explanation = f"GPU at {gpu:.0f}%"
            if gpu > 95:
                m2.recommendation = "GPU is saturated. This is the limiting factor."
                issues.append(HealthIssue(
                    category=HealthCategory.PERFORMANCE,
                    severity=IssueSeverity.CRITICAL,
                    title="GPU saturated",
                    explanation=f"GPU at {gpu:.0f}%. Workload is GPU-bound.",
                    deduction=m2.deduction,
                    measured_value=gpu, threshold=95.0,
                ))
        else:
            m2.explanation = "GPU data not available"
            m2.final_score = 80
        metrics.append(m2)

        return metrics, issues

    def _score_thermal(self, ctx: Dict) -> Tuple[List[HealthMetric], List[HealthIssue]]:
        """Score thermal conditions."""
        metrics = []
        issues = []

        gpu_temp = ctx.get("gpu_temp")
        m = HealthMetric(
            category=HealthCategory.THERMAL,
            name="GPU Temperature",
            description="GPU thermal state",
            measured_value=gpu_temp, measured_unit="°C",
            available=gpu_temp is not None and gpu_temp > 0,
        )
        if gpu_temp is not None and gpu_temp > 0:
            if gpu_temp >= 90:
                m.final_score = max(0, 100 - (gpu_temp - 80) * 5)
                m.deduction = (gpu_temp - 80) * 5
                m.explanation = f"GPU at {gpu_temp:.0f}°C — throttling likely"
                m.recommendation = "Reduce GPU load. Additional performance settings may worsen thermals."
                issues.append(HealthIssue(
                    category=HealthCategory.THERMAL,
                    severity=IssueSeverity.CRITICAL,
                    title="GPU thermal throttling risk",
                    explanation=f"GPU at {gpu_temp:.0f}°C. Performance may be reduced.",
                    deduction=m.deduction,
                    measured_value=gpu_temp, threshold=90.0,
                    recommendation="Reduce GPU load or improve airflow.",
                ))
            elif gpu_temp >= 80:
                m.final_score = max(0, 100 - (gpu_temp - 70) * 3)
                m.deduction = (gpu_temp - 70) * 3
                m.explanation = f"GPU at {gpu_temp:.0f}°C — elevated"
                issues.append(HealthIssue(
                    category=HealthCategory.THERMAL,
                    severity=IssueSeverity.MODERATE,
                    title="GPU temperature elevated",
                    explanation=f"GPU at {gpu_temp:.0f}°C.",
                    deduction=m.deduction,
                    measured_value=gpu_temp, threshold=80.0,
                ))
            else:
                m.final_score = 100
                m.explanation = f"GPU at {gpu_temp:.0f}°C — healthy"
        else:
            m.explanation = "GPU temperature not available"
            m.final_score = 80
        metrics.append(m)

        # CPU temperature (if available)
        cpu_temp = ctx.get("cpu_temp")
        if cpu_temp is not None and cpu_temp > 0:
            m2 = HealthMetric(
                category=HealthCategory.THERMAL,
                name="CPU Temperature",
                description="CPU thermal state",
                measured_value=cpu_temp, measured_unit="°C",
                available=True,
            )
            if cpu_temp >= 90:
                m2.final_score = max(0, 100 - (cpu_temp - 80) * 5)
                m2.deduction = (cpu_temp - 80) * 5
                m2.explanation = f"CPU at {cpu_temp:.0f}°C — throttling risk"
                issues.append(HealthIssue(
                    category=HealthCategory.THERMAL,
                    severity=IssueSeverity.CRITICAL,
                    title="CPU thermal throttling risk",
                    explanation=f"CPU at {cpu_temp:.0f}°C.",
                    deduction=m2.deduction,
                    measured_value=cpu_temp, threshold=90.0,
                ))
            elif cpu_temp >= 80:
                m2.deduction = (cpu_temp - 70) * 2
                m2.final_score = max(0, 100 - m2.deduction)
                m2.explanation = f"CPU at {cpu_temp:.0f}°C — elevated"
            else:
                m2.final_score = 100
                m2.explanation = f"CPU at {cpu_temp:.0f}°C — healthy"
            metrics.append(m2)

        return metrics, issues

    def _score_memory(self, ctx: Dict) -> Tuple[List[HealthMetric], List[HealthIssue]]:
        """Score RAM pressure."""
        metrics = []
        issues = []

        ram = ctx.get("ram_percent")
        ram_avail = ctx.get("ram_available_gb")
        m = HealthMetric(
            category=HealthCategory.MEMORY,
            name="RAM Pressure",
            description="System memory utilization",
            measured_value=ram, measured_unit="%",
            available=ram is not None and ram > 0,
        )
        if ram is not None and ram > 0:
            if ram >= 95:
                m.deduction = 15
                m.explanation = f"RAM at {ram:.0f}% — critically high"
                m.recommendation = "System may be swapping. Close memory-heavy applications."
                issues.append(HealthIssue(
                    category=HealthCategory.MEMORY,
                    severity=IssueSeverity.CRITICAL,
                    title="RAM critically high",
                    explanation=f"RAM at {ram:.0f}%{f', {ram_avail:.1f} GB available' if ram_avail else ''}.",
                    deduction=15,
                    measured_value=ram, threshold=95.0,
                    recommendation="Close memory-heavy applications.",
                ))
            elif ram >= 90:
                m.deduction = 10
                m.explanation = f"RAM at {ram:.0f}% — high pressure"
                issues.append(HealthIssue(
                    category=HealthCategory.MEMORY,
                    severity=IssueSeverity.MAJOR,
                    title="RAM pressure high",
                    explanation=f"RAM at {ram:.0f}%.",
                    deduction=10,
                    measured_value=ram, threshold=90.0,
                    recommendation="Monitor memory usage. Consider closing background apps.",
                ))
            elif ram >= 80:
                m.deduction = 5
                m.explanation = f"RAM at {ram:.0f}% — moderate pressure"
                issues.append(HealthIssue(
                    category=HealthCategory.MEMORY,
                    severity=IssueSeverity.MINOR,
                    title="RAM usage elevated",
                    explanation=f"RAM at {ram:.0f}%.",
                    deduction=5,
                    measured_value=ram, threshold=80.0,
                ))
            else:
                m.explanation = f"RAM at {ram:.0f}% — healthy"
            m.final_score = max(0, 100 - m.deduction)
        else:
            m.explanation = "RAM data not available"
            m.final_score = 80
        metrics.append(m)

        return metrics, issues

    def _score_storage(self, ctx: Dict) -> Tuple[List[HealthMetric], List[HealthIssue]]:
        """Score disk free space."""
        metrics = []
        issues = []

        free_gb = ctx.get("disk_free_gb")
        m = HealthMetric(
            category=HealthCategory.STORAGE,
            name="Disk Free Space",
            description="Available storage capacity",
            measured_value=free_gb, measured_unit="GB",
            available=free_gb is not None and free_gb > 0,
        )
        if free_gb is not None and free_gb > 0:
            if free_gb < 5:
                m.deduction = 15
                m.explanation = f"{free_gb:.1f} GB free — critically low"
                m.recommendation = "Clean temporary files immediately."
                issues.append(HealthIssue(
                    category=HealthCategory.STORAGE,
                    severity=IssueSeverity.CRITICAL,
                    title="Disk space critically low",
                    explanation=f"Only {free_gb:.1f} GB free.",
                    deduction=15,
                    measured_value=free_gb, threshold=5.0,
                    recommendation="Clean temporary files immediately.",
                ))
            elif free_gb < 15:
                m.deduction = 8
                m.explanation = f"{free_gb:.1f} GB free — running low"
                issues.append(HealthIssue(
                    category=HealthCategory.STORAGE,
                    severity=IssueSeverity.MODERATE,
                    title="Disk space low",
                    explanation=f"{free_gb:.1f} GB free.",
                    deduction=8,
                    measured_value=free_gb, threshold=15.0,
                    recommendation="Consider cleanup when convenient.",
                ))
            elif free_gb < 30:
                m.deduction = 3
                m.explanation = f"{free_gb:.1f} GB free — approaching capacity"
            else:
                m.explanation = f"{free_gb:.1f} GB free — healthy"
            m.final_score = max(0, 100 - m.deduction)
        else:
            m.explanation = "Disk data not available"
            m.final_score = 80
        metrics.append(m)

        return metrics, issues

    def _score_background(self, ctx: Dict) -> Tuple[List[HealthMetric], List[HealthIssue]]:
        """Score background process load."""
        metrics = []
        issues = []

        bg_cpu = ctx.get("background_cpu", 0)
        bg_ram = ctx.get("background_ram_mb", 0)

        m = HealthMetric(
            category=HealthCategory.BACKGROUND_LOAD,
            name="Background CPU",
            description="CPU used by non-essential processes",
            measured_value=bg_cpu, measured_unit="%",
            available=bg_cpu > 0,
        )
        if bg_cpu > 0:
            if bg_cpu > 50:
                m.deduction = 10
                m.explanation = f"Background processes using {bg_cpu:.0f}% CPU"
                m.recommendation = "Close unnecessary background applications."
                issues.append(HealthIssue(
                    category=HealthCategory.BACKGROUND_LOAD,
                    severity=IssueSeverity.MODERATE,
                    title="High background CPU usage",
                    explanation=f"Background processes consuming {bg_cpu:.0f}% CPU.",
                    deduction=10,
                    measured_value=bg_cpu, threshold=50.0,
                    recommendation="Close unnecessary background applications.",
                ))
            elif bg_cpu > 20:
                m.deduction = 3
                m.explanation = f"Background processes using {bg_cpu:.0f}% CPU"
            else:
                m.explanation = f"Background CPU: {bg_cpu:.0f}% — low"
            m.final_score = max(0, 100 - m.deduction)
        else:
            m.explanation = "Background CPU data not available"
            m.final_score = 85
        metrics.append(m)

        # Background RAM
        m2 = HealthMetric(
            category=HealthCategory.BACKGROUND_LOAD,
            name="Background RAM",
            description="RAM used by non-essential processes",
            measured_value=bg_ram, measured_unit="MB",
            available=bg_ram > 0,
        )
        if bg_ram > 0:
            if bg_ram > 4000:
                m2.deduction = 8
                m2.explanation = f"Background processes using {bg_ram:.0f} MB RAM"
                issues.append(HealthIssue(
                    category=HealthCategory.BACKGROUND_LOAD,
                    severity=IssueSeverity.MODERATE,
                    title="High background memory usage",
                    explanation=f"Background processes consuming {bg_ram:.0f} MB.",
                    deduction=8,
                    measured_value=bg_ram, threshold=4000.0,
                    recommendation="Close unnecessary background applications.",
                ))
            elif bg_ram > 2000:
                m2.deduction = 3
                m2.explanation = f"Background processes using {bg_ram:.0f} MB RAM"
            else:
                m2.explanation = f"Background RAM: {bg_ram:.0f} MB — low"
            m2.final_score = max(0, 100 - m2.deduction)
        else:
            m2.explanation = "Background RAM data not available"
            m2.final_score = 85
        metrics.append(m2)

        return metrics, issues

    def _score_gaming_readiness(self, ctx: Dict) -> Tuple[List[HealthMetric], List[HealthIssue]]:
        """Score gaming readiness."""
        metrics = []
        issues = []

        # Target detection
        target = ctx.get("target_name", "")
        m = HealthMetric(
            category=HealthCategory.GAMING_READINESS,
            name="Target Detection",
            description="Game/emulator process detected",
            measured_value=1.0 if target else 0.0,
            available=True,
        )
        if target:
            m.explanation = f"Target: {target}"
            m.final_score = 100
        else:
            m.explanation = "No game/emulator detected"
            m.final_score = 70  # neutral — not a health problem
            m.deduction = 0
        metrics.append(m)

        # FPS availability
        fps = ctx.get("fps")
        m2 = HealthMetric(
            category=HealthCategory.GAMING_READINESS,
            name="FPS Data",
            description="Frame rate measurement available",
            measured_value=fps, measured_unit="FPS",
            available=fps is not None and fps > 0,
        )
        if fps is not None and fps > 0:
            m2.explanation = f"FPS: {fps:.0f}"
            m2.final_score = 100
            if fps < 30:
                m2.deduction = 10
                m2.final_score = 90
                issues.append(HealthIssue(
                    category=HealthCategory.GAMING_READINESS,
                    severity=IssueSeverity.MODERATE,
                    title="Low frame rate",
                    explanation=f"FPS at {fps:.0f}.",
                    deduction=10,
                    measured_value=fps, threshold=30.0,
                    recommendation="Investigate performance bottleneck.",
                ))
        else:
            m2.explanation = "FPS data not available"
            m2.final_score = 80
        metrics.append(m2)

        return metrics, issues

    # ── Helpers ──────────────────────────────────────────────

    def _category_score(self, metrics: List[HealthMetric]) -> float:
        """Calculate category score from its metrics."""
        if not metrics:
            return 100.0
        scores = [m.final_score for m in metrics if m.available]
        if not scores:
            return 80.0  # neutral for missing data
        return sum(scores) / len(scores)

    def _collect_context(self) -> Dict:
        """Collect live system context for scoring."""
        ctx = {}

        try:
            from app.core.telemetry import telemetry_engine
            frame = telemetry_engine.current
            ctx["cpu_percent"] = frame.cpu_utilization
            ctx["gpu_percent"] = frame.gpu_utilization
            ctx["ram_percent"] = frame.ram_percent
            ctx["gpu_temp"] = frame.gpu_temp
            ctx["cpu_temp"] = frame.cpu_temperature_c
        except Exception:
            pass

        try:
            import psutil
            vm = psutil.virtual_memory()
            ctx["ram_available_gb"] = vm.available / (1024 ** 3)
        except Exception:
            pass

        try:
            disk = psutil.disk_usage("C:\\")
            ctx["disk_free_gb"] = disk.free / (1024 ** 3)
        except Exception:
            pass

        try:
            from app.core.emulator_controller import emulator_controller
            target = emulator_controller.detect_target()
            if target:
                ctx["target_name"] = target.name
        except Exception:
            pass

        try:
            from app.performance.fps_provider import fps_registry
            if fps_registry.active and hasattr(fps_registry.active, 'get_metrics'):
                metrics = fps_registry.active.get_metrics()
                if metrics and metrics.available and metrics.sample_count > 0:
                    ctx["fps"] = metrics.median_fps if metrics.median_fps > 0 else metrics.avg_fps
        except Exception:
            pass

        # Background load from process intelligence
        try:
            from app.system.process_intelligence import process_intelligence
            scan = process_intelligence.last_scan
            if scan:
                ctx["background_cpu"] = scan.total_background_cpu
                ctx["background_ram_mb"] = scan.total_background_memory_mb
        except Exception:
            pass

        return ctx

    # ── Format ──────────────────────────────────────────────

    def format_score(self, score: Optional[HealthScore] = None) -> str:
        """Format health score for CLI display."""
        score = score or self._last_score
        if not score:
            score = self.calculate()

        lines = []
        lines.append("=" * 55)
        lines.append("  SYSTEM HEALTH")
        lines.append("=" * 55)

        # Overall
        s = int(score.overall_score)
        lines.append(f"\n  SCORE: {s}/100  [{score.grade}]")
        lines.append(f"  Confidence: {score.confidence:.0f}%  Data: {score.data_completeness:.0f}%")

        # Category breakdown
        lines.append(f"\n  CATEGORIES")
        lines.append("  " + "-" * 51)
        for cat, cat_score in sorted(score.category_scores.items()):
            bar_len = int(cat_score / 5)
            bar = "=" * bar_len + "." * (20 - bar_len)
            lines.append(f"    {cat:<20} [{bar}] {cat_score:.0f}")

        # Deductions
        deductions = [i for i in score.issues if i.deduction > 0]
        if deductions:
            lines.append(f"\n  DEDUCTIONS")
            lines.append("  " + "-" * 51)
            for issue in sorted(deductions, key=lambda i: -i.deduction):
                lines.append(f"    -{issue.deduction:.0f}  {issue.title}")
                lines.append(f"         {issue.explanation}")
                if issue.recommendation:
                    lines.append(f"         -> {issue.recommendation}")
        else:
            lines.append(f"\n  No deductions — system is healthy.")

        # Metrics detail
        lines.append(f"\n  METRICS")
        lines.append("  " + "-" * 51)
        for m in score.metrics:
            if m.available:
                val = f"{m.measured_value:.1f}{m.measured_unit}"
            else:
                val = "N/A"
            ded = f" (-{m.deduction:.0f})" if m.deduction > 0 else ""
            lines.append(f"    {m.name:<25} {val:>10}  score: {m.final_score:.0f}{ded}")

        lines.append("\n" + "=" * 55)
        return "\n".join(lines)

    def format_brief(self, score: Optional[HealthScore] = None) -> str:
        """Format a brief one-line health summary."""
        score = score or self._last_score
        if not score:
            score = self.calculate()
        return f"Health: {int(score.overall_score)}/100 [{score.grade}]"


# ── Singleton ────────────────────────────────────────────────────

health_engine = HealthEngine()
