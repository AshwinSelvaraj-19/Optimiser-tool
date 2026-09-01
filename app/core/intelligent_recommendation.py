"""
Phase 51 — Intelligent Recommendation Engine.

Higher-level recommendation intelligence that combines multiple data sources
into actionable, evidence-based recommendations with cooldowns and history.

Differentiates from the existing RecommendationEngine (Phase 35):
  - Phase 35: per-optimization recommendations based on telemetry samples
  - Phase 51: system-wide intelligence combining disk, memory, CPU, GPU,
    thermal, cleanup, gaming, and optimization data into unified recommendations

Rules:
  - Never recommend optimization simply because an optimization exists
  - Use measured evidence
  - Avoid recommendation spam via cooldowns and history
  - Every recommendation has: title, explanation, evidence, severity,
    estimated benefit, risk, action, cooldown, expiration
  - Never execute anything automatically
"""

import json
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Tuple

from app.utils.logger import get_logger

logger = get_logger("core.intelligent_recommendation")


# ── Enums ────────────────────────────────────────────────────────

class RecommendationSeverity(Enum):
    """Severity levels for system-wide recommendations."""
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RecommendationAction(Enum):
    """Recommended action type."""
    NONE = "NONE"
    REVIEW = "REVIEW"
    APPLY = "APPLY"
    MONITOR = "MONITOR"
    ESCALATE = "ESCALATE"


# ── Models ───────────────────────────────────────────────────────

@dataclass
class RecommendationEvidence:
    """A single piece of evidence supporting a recommendation."""
    metric: str = ""
    value: Optional[float] = None
    threshold: Optional[float] = None
    unit: str = ""
    source: str = ""  # telemetry, cleanup, disk, etc.

    def to_dict(self) -> dict:
        return {
            "metric": self.metric,
            "value": self.value,
            "threshold": self.threshold,
            "unit": self.unit,
            "source": self.source,
        }


@dataclass
class SystemRecommendation:
    """A single system-wide recommendation."""
    id: str = ""
    title: str = ""
    explanation: str = ""
    severity: RecommendationSeverity = RecommendationSeverity.INFO
    evidence: List[RecommendationEvidence] = field(default_factory=list)
    estimated_benefit: str = ""
    risk: str = "NONE"
    action: RecommendationAction = RecommendationAction.NONE
    cooldown_seconds: float = 300.0  # 5 minutes default
    expiration_seconds: float = 3600.0  # 1 hour default
    created_at: float = 0.0
    expires_at: float = 0.0
    category: str = ""  # disk, memory, cpu, gpu, thermal, cleanup, gaming
    source_module: str = ""

    def __post_init__(self):
        if not self.id:
            self.id = f"rec_{uuid.uuid4().hex[:8]}"
        if self.created_at == 0.0:
            self.created_at = time.time()
        if self.expires_at == 0.0:
            self.expires_at = self.created_at + self.expiration_seconds

    @property
    def is_expired(self) -> bool:
        return time.time() > self.expires_at

    @property
    def severity_icon(self) -> str:
        icons = {
            RecommendationSeverity.INFO: "ℹ",
            RecommendationSeverity.LOW: "✓",
            RecommendationSeverity.MEDIUM: "⚠",
            RecommendationSeverity.HIGH: "⚠",
            RecommendationSeverity.CRITICAL: "🔴",
        }
        return icons.get(self.severity, "•")

    @property
    def severity_color(self) -> str:
        colors = {
            RecommendationSeverity.INFO: "#4CAF50",
            RecommendationSeverity.LOW: "#4CAF50",
            RecommendationSeverity.MEDIUM: "#FF9800",
            RecommendationSeverity.HIGH: "#FF5722",
            RecommendationSeverity.CRITICAL: "#F44336",
        }
        return colors.get(self.severity, "#9E9E9E")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "explanation": self.explanation,
            "severity": self.severity.value,
            "evidence": [e.to_dict() for e in self.evidence],
            "estimated_benefit": self.estimated_benefit,
            "risk": self.risk,
            "action": self.action.value,
            "category": self.category,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "is_expired": self.is_expired,
        }


@dataclass
class RecommendationRule:
    """
    A rule that evaluates system state and produces recommendations.

    Rules are the building blocks of the intelligent recommendation engine.
    Each rule defines:
      - What it checks (category, conditions)
      - When it fires (thresholds)
      - What it recommends (title, explanation, severity, action)
      - How often it can fire (cooldown)
    """
    rule_id: str = ""
    name: str = ""
    category: str = ""
    enabled: bool = True
    cooldown_seconds: float = 300.0
    min_severity: RecommendationSeverity = RecommendationSeverity.LOW

    def evaluate(self, context: Dict) -> Optional[SystemRecommendation]:
        """
        Evaluate the rule against the current system context.

        Args:
            context: Dict containing system metrics from all sources

        Returns:
            SystemRecommendation if rule fires, None otherwise
        """
        raise NotImplementedError


@dataclass
class RecommendationHistoryEntry:
    """A record of a past recommendation."""
    recommendation_id: str = ""
    title: str = ""
    severity: str = ""
    category: str = ""
    action_taken: str = ""
    timestamp: float = 0.0
    dismissed: bool = False

    def to_dict(self) -> dict:
        return {
            "recommendation_id": self.recommendation_id,
            "title": self.title,
            "severity": self.severity,
            "category": self.category,
            "action_taken": self.action_taken,
            "timestamp": self.timestamp,
            "dismissed": self.dismissed,
        }


# ── Built-in Rules ───────────────────────────────────────────────

class DiskPressureRule(RecommendationRule):
    """Check disk space pressure."""

    def __init__(self):
        super().__init__(
            rule_id="disk_pressure",
            name="Disk Pressure",
            category="disk",
            cooldown_seconds=600,
        )

    def evaluate(self, context: Dict) -> Optional[SystemRecommendation]:
        free_gb = context.get("disk_free_gb", 0)
        total_gb = context.get("disk_total_gb", 0)
        cleanup_bytes = context.get("cleanup_reclaimable_bytes", 0)

        if free_gb <= 0:
            return None

        if free_gb < 5:
            return SystemRecommendation(
                title="System storage critically low",
                explanation=(
                    f"Only {free_gb:.1f} GB free on system drive. "
                    f"{'Cleaning safe temporary files can help.' if cleanup_bytes > 0 else 'Consider freeing disk space.'}"
                ),
                severity=RecommendationSeverity.CRITICAL,
                evidence=[
                    RecommendationEvidence("disk_free_gb", free_gb, 5.0, "GB", "disk"),
                    RecommendationEvidence("disk_total_gb", total_gb, None, "GB", "disk"),
                ],
                estimated_benefit="May reclaim space for system stability",
                risk="LOW",
                action=RecommendationAction.REVIEW,
                cooldown_seconds=600,
                category="disk",
            )

        if free_gb < 15:
            return SystemRecommendation(
                title="Disk space running low",
                explanation=(
                    f"{free_gb:.1f} GB free. "
                    f"{'Safe cleanup available.' if cleanup_bytes > 0 else 'Monitor disk usage.'}"
                ),
                severity=RecommendationSeverity.HIGH,
                evidence=[
                    RecommendationEvidence("disk_free_gb", free_gb, 15.0, "GB", "disk"),
                ],
                estimated_benefit="Reclaim disk space",
                risk="NONE",
                action=RecommendationAction.REVIEW,
                cooldown_seconds=900,
                category="disk",
            )

        if free_gb < 30:
            return SystemRecommendation(
                title="Temporary files available for cleanup",
                explanation=f"{free_gb:.1f} GB free. Cleanup recommended when convenient.",
                severity=RecommendationSeverity.LOW,
                evidence=[
                    RecommendationEvidence("disk_free_gb", free_gb, 30.0, "GB", "disk"),
                ],
                estimated_benefit="Maintain healthy disk space",
                risk="NONE",
                action=RecommendationAction.MONITOR,
                cooldown_seconds=3600,
                category="disk",
            )

        return None


class MemoryPressureRule(RecommendationRule):
    """Check RAM pressure."""

    def __init__(self):
        super().__init__(
            rule_id="memory_pressure",
            name="Memory Pressure",
            category="memory",
            cooldown_seconds=300,
        )

    def evaluate(self, context: Dict) -> Optional[SystemRecommendation]:
        ram_percent = context.get("ram_percent", 0)
        ram_available_gb = context.get("ram_available_gb", 0)

        if ram_percent <= 0:
            return None

        if ram_percent >= 90:
            return SystemRecommendation(
                title="RAM pressure is critical",
                explanation=(
                    f"RAM at {ram_percent:.0f}% with {ram_available_gb:.1f} GB available. "
                    "System may be swapping, causing stuttering."
                ),
                severity=RecommendationSeverity.HIGH,
                evidence=[
                    RecommendationEvidence("ram_percent", ram_percent, 90.0, "%", "telemetry"),
                    RecommendationEvidence("ram_available_gb", ram_available_gb, 2.0, "GB", "telemetry"),
                ],
                estimated_benefit="Reduce memory pressure, improve frame consistency",
                risk="NONE",
                action=RecommendationAction.REVIEW,
                cooldown_seconds=300,
                category="memory",
            )

        if ram_percent >= 80:
            return SystemRecommendation(
                title="RAM usage is elevated",
                explanation=f"RAM at {ram_percent:.0f}%. Close unnecessary background applications.",
                severity=RecommendationSeverity.MEDIUM,
                evidence=[
                    RecommendationEvidence("ram_percent", ram_percent, 80.0, "%", "telemetry"),
                ],
                estimated_benefit="Free memory for gaming",
                risk="NONE",
                action=RecommendationAction.MONITOR,
                cooldown_seconds=600,
                category="memory",
            )

        return None


class ThermalRule(RecommendationRule):
    """Check thermal conditions."""

    def __init__(self):
        super().__init__(
            rule_id="thermal",
            name="Thermal Condition",
            category="thermal",
            cooldown_seconds=120,
        )

    def evaluate(self, context: Dict) -> Optional[SystemRecommendation]:
        gpu_temp = context.get("gpu_temp")
        thermal_status = context.get("thermal_status", "NORMAL")

        if gpu_temp is None or gpu_temp <= 0:
            return None

        if thermal_status == "THROTTLING" or gpu_temp >= 90:
            return SystemRecommendation(
                title="Thermal throttling detected",
                explanation=(
                    f"GPU at {gpu_temp:.0f}°C. "
                    "Performance is being reduced to manage temperature. "
                    "Additional performance optimizations may worsen thermals."
                ),
                severity=RecommendationSeverity.HIGH,
                evidence=[
                    RecommendationEvidence("gpu_temp", gpu_temp, 90.0, "°C", "telemetry"),
                    RecommendationEvidence("thermal_status", None, None, "", "telemetry"),
                ],
                estimated_benefit="Prevent thermal damage and performance loss",
                risk="LOW",
                action=RecommendationAction.REVIEW,
                cooldown_seconds=120,
                category="thermal",
            )

        if gpu_temp >= 80:
            return SystemRecommendation(
                title="GPU temperature elevated",
                explanation=f"GPU at {gpu_temp:.0f}°C. Approaching thermal throttling threshold.",
                severity=RecommendationSeverity.MEDIUM,
                evidence=[
                    RecommendationEvidence("gpu_temp", gpu_temp, 80.0, "°C", "telemetry"),
                ],
                estimated_benefit="Prevent thermal throttling",
                risk="NONE",
                action=RecommendationAction.MONITOR,
                cooldown_seconds=300,
                category="thermal",
            )

        return None


class CpuPressureRule(RecommendationRule):
    """Check CPU pressure."""

    def __init__(self):
        super().__init__(
            rule_id="cpu_pressure",
            name="CPU Pressure",
            category="cpu",
            cooldown_seconds=300,
        )

    def evaluate(self, context: Dict) -> Optional[SystemRecommendation]:
        cpu_percent = context.get("cpu_percent", 0)

        if cpu_percent <= 0:
            return None

        if cpu_percent >= 90:
            return SystemRecommendation(
                title="CPU utilization is critical",
                explanation=(
                    f"CPU at {cpu_percent:.0f}%. Frame delivery may be limited. "
                    "Background processes may be competing for CPU time."
                ),
                severity=RecommendationSeverity.HIGH,
                evidence=[
                    RecommendationEvidence("cpu_percent", cpu_percent, 90.0, "%", "telemetry"),
                ],
                estimated_benefit="Improve frame delivery consistency",
                risk="NONE",
                action=RecommendationAction.REVIEW,
                cooldown_seconds=300,
                category="cpu",
            )

        if cpu_percent >= 80:
            return SystemRecommendation(
                title="CPU utilization is high",
                explanation=f"CPU at {cpu_percent:.0f}%. Monitor for frame drops.",
                severity=RecommendationSeverity.MEDIUM,
                evidence=[
                    RecommendationEvidence("cpu_percent", cpu_percent, 80.0, "%", "telemetry"),
                ],
                estimated_benefit="Maintain smooth frame delivery",
                risk="NONE",
                action=RecommendationAction.MONITOR,
                cooldown_seconds=600,
                category="cpu",
            )

        return None


class CleanupAvailableRule(RecommendationRule):
    """Check if cleanup is available."""

    def __init__(self):
        super().__init__(
            rule_id="cleanup_available",
            name="Cleanup Available",
            category="cleanup",
            cooldown_seconds=1800,
        )

    def evaluate(self, context: Dict) -> Optional[SystemRecommendation]:
        cleanup_bytes = context.get("cleanup_reclaimable_bytes", 0)
        cleanup_items = context.get("cleanup_safe_items", 0)

        if cleanup_bytes <= 0 or cleanup_items <= 0:
            return None

        # Convert to human-readable
        if cleanup_bytes >= 1024 * 1024 * 1024:
            size_str = f"{cleanup_bytes / (1024**3):.1f} GB"
        elif cleanup_bytes >= 1024 * 1024:
            size_str = f"{cleanup_bytes / (1024**2):.0f} MB"
        else:
            size_str = f"{cleanup_bytes / 1024:.0f} KB"

        return SystemRecommendation(
            title="Cleanup recommended",
            explanation=(
                f"{size_str} of temporary data detected across {cleanup_items} categories. "
                "Safe to clean."
            ),
            severity=RecommendationSeverity.LOW,
            evidence=[
                RecommendationEvidence("cleanup_bytes", cleanup_bytes, None, "bytes", "cleanup"),
                RecommendationEvidence("cleanup_items", cleanup_items, None, "", "cleanup"),
            ],
            estimated_benefit=f"Reclaim {size_str} of disk space",
            risk="NONE",
            action=RecommendationAction.REVIEW,
            cooldown_seconds=1800,
            category="cleanup",
        )


class GamingOptimizationRule(RecommendationRule):
    """Check if gaming optimization is applicable."""

    def __init__(self):
        super().__init__(
            rule_id="gaming_optimization",
            name="Gaming Optimization",
            category="gaming",
            cooldown_seconds=600,
        )

    def evaluate(self, context: Dict) -> Optional[SystemRecommendation]:
        target_name = context.get("target_name", "")
        gaming_state = context.get("gaming_state", "IDLE")
        optimization_state = context.get("optimization_state", "N/A")

        if not target_name:
            return None

        if gaming_state == "DEGRADED":
            return SystemRecommendation(
                title="Gaming performance degraded",
                explanation=(
                    f"Emulator {target_name} is running but performance has degraded. "
                    "System resources may need attention."
                ),
                severity=RecommendationSeverity.MEDIUM,
                evidence=[
                    RecommendationEvidence("gaming_state", None, None, "", "gaming"),
                ],
                estimated_benefit="Restore gaming performance",
                risk="LOW",
                action=RecommendationAction.REVIEW,
                cooldown_seconds=300,
                category="gaming",
            )

        if gaming_state == "IDLE" and optimization_state != "N/A":
            return SystemRecommendation(
                title="Gaming optimization available",
                explanation=(
                    f"Emulator {target_name} detected. "
                    "Gaming optimizations can be applied for better performance."
                ),
                severity=RecommendationSeverity.LOW,
                evidence=[
                    RecommendationEvidence("target", None, None, "", "gaming"),
                ],
                estimated_benefit="Potential performance improvement",
                risk="LOW",
                action=RecommendationAction.REVIEW,
                cooldown_seconds=600,
                category="gaming",
            )

        return None


# ── Recommendation History ───────────────────────────────────────

class RecommendationHistory:
    """Tracks recommendation history to prevent spam and enable learning."""

    HISTORY_DIR = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "recommendation_history",
    )

    def __init__(self):
        self._entries: List[RecommendationHistoryEntry] = []
        self._last_fired: Dict[str, float] = {}  # rule_id -> timestamp
        self._load()

    def _load(self):
        """Load history from disk."""
        try:
            if not os.path.exists(self.HISTORY_DIR):
                return
            for fname in sorted(os.listdir(self.HISTORY_DIR)):
                if fname.endswith(".json"):
                    try:
                        with open(os.path.join(self.HISTORY_DIR, fname)) as f:
                            data = json.load(f)
                        entry = RecommendationHistoryEntry(**{
                            k: v for k, v in data.items()
                            if k in RecommendationHistoryEntry.__dataclass_fields__
                        })
                        self._entries.append(entry)
                    except Exception:
                        continue
        except Exception:
            pass

    def can_fire(self, rule_id: str, cooldown_seconds: float) -> bool:
        """Check if a rule can fire based on cooldown."""
        last = self._last_fired.get(rule_id, 0)
        return (time.time() - last) >= cooldown_seconds

    def record_fire(self, rule_id: str, recommendation: SystemRecommendation):
        """Record that a rule fired."""
        self._last_fired[rule_id] = time.time()

        entry = RecommendationHistoryEntry(
            recommendation_id=recommendation.id,
            title=recommendation.title,
            severity=recommendation.severity.value,
            category=recommendation.category,
            timestamp=time.time(),
        )
        self._entries.append(entry)

        # Persist
        self._save_entry(entry)

        # Keep last 200 entries in memory
        if len(self._entries) > 200:
            self._entries = self._entries[-200:]

    def record_action(self, recommendation_id: str, action: str):
        """Record that a user acted on a recommendation."""
        for entry in self._entries:
            if entry.recommendation_id == recommendation_id:
                entry.action_taken = action
                self._save_entry(entry)
                break

    def was_recently_recommended(self, title: str, within_seconds: float = 3600) -> bool:
        """Check if a similar recommendation was recently shown."""
        cutoff = time.time() - within_seconds
        for entry in reversed(self._entries):
            if entry.timestamp < cutoff:
                break
            if entry.title == title and not entry.dismissed:
                return True
        return False

    def get_recent(self, count: int = 20) -> List[RecommendationHistoryEntry]:
        """Get recent history entries."""
        return list(reversed(self._entries[-count:]))

    def _save_entry(self, entry: RecommendationHistoryEntry):
        """Save a single entry to disk."""
        try:
            os.makedirs(self.HISTORY_DIR, exist_ok=True)
            filepath = os.path.join(
                self.HISTORY_DIR,
                f"{entry.recommendation_id}.json",
            )
            with open(filepath, "w") as f:
                json.dump(entry.to_dict(), f, indent=2)
        except Exception:
            pass


# ── Intelligent Recommendation Engine ────────────────────────────

class IntelligentRecommendationEngine:
    """
    System-wide intelligent recommendation engine.

    Combines data from:
      - Telemetry (CPU, GPU, RAM, thermal)
      - Cleanup center (disk pressure, reclaimable bytes)
      - Gaming optimization (target, state)
      - Optimization engine (applied optimizations)

    Produces unified, cooldown-aware, spam-free recommendations.

    Never executes anything automatically.
    """

    def __init__(self):
        self._rules: List[RecommendationRule] = [
            DiskPressureRule(),
            MemoryPressureRule(),
            ThermalRule(),
            CpuPressureRule(),
            CleanupAvailableRule(),
            GamingOptimizationRule(),
        ]
        self._history = RecommendationHistory()
        self._active_recommendations: List[SystemRecommendation] = []
        self._last_evaluation: float = 0.0

    @property
    def active_recommendations(self) -> List[SystemRecommendation]:
        """Get current active (non-expired) recommendations."""
        self._active_recommendations = [
            r for r in self._active_recommendations
            if not r.is_expired
        ]
        return list(self._active_recommendations)

    @property
    def history(self) -> RecommendationHistory:
        return self._history

    def evaluate(self, context: Dict) -> List[SystemRecommendation]:
        """
        Evaluate all rules against the current system context.

        Returns list of new recommendations that fired.
        """
        now = time.time()

        # Don't re-evaluate too frequently
        if now - self._last_evaluation < 10:
            return []
        self._last_evaluation = now

        new_recommendations = []

        for rule in self._rules:
            if not rule.enabled:
                continue

            # Cooldown check
            if not self._history.can_fire(rule.rule_id, rule.cooldown_seconds):
                continue

            # Evaluate
            try:
                rec = rule.evaluate(context)
            except Exception as e:
                logger.debug(f"Rule {rule.rule_id} evaluation error: {e}")
                continue

            if rec is None:
                continue

            # Spam check — don't show same recommendation too frequently
            if self._history.was_recently_recommended(rec.title, within_seconds=rule.cooldown_seconds):
                continue

            # Record
            self._history.record_fire(rule.rule_id, rec)
            new_recommendations.append(rec)

        # Update active list
        self._active_recommendations.extend(new_recommendations)
        self._active_recommendations = [
            r for r in self._active_recommendations
            if not r.is_expired
        ]

        return new_recommendations

    def collect_context(self) -> Dict:
        """
        Collect system context from all available sources.

        Returns a dict suitable for rule evaluation.
        """
        context = {}

        # Telemetry
        try:
            from app.core.telemetry import telemetry_engine
            frame = telemetry_engine.current
            context["cpu_percent"] = frame.cpu_utilization
            context["gpu_percent"] = frame.gpu_utilization
            context["ram_percent"] = frame.ram_percent
            context["gpu_temp"] = frame.gpu_temp
            context["thermal_status"] = frame.thermal_status or "NORMAL"

            import psutil
            vm = psutil.virtual_memory()
            context["ram_available_gb"] = vm.available / (1024 ** 3)
        except Exception:
            pass

        # Disk
        try:
            import shutil
            usage = shutil.disk_usage("/")
            context["disk_free_gb"] = usage.free / (1024 ** 3)
            context["disk_total_gb"] = usage.total / (1024 ** 3)
        except Exception:
            pass

        # Cleanup
        try:
            from app.cleanup.cleanup_center import cleanup_center
            if cleanup_center.items:
                safe = [i for i in cleanup_center.items
                        if hasattr(i, 'safety') and i.safety.value == "SAFE" and i.selected]
                context["cleanup_reclaimable_bytes"] = sum(i.removable_size for i in safe)
                context["cleanup_safe_items"] = len(safe)
        except Exception:
            pass

        # Gaming
        try:
            from app.core.gaming_optimization import gaming_session_manager
            summary = gaming_session_manager.get_ui_summary()
            context["gaming_state"] = summary.get("state", "IDLE")
            context["target_name"] = summary.get("target_name", "")
        except Exception:
            pass

        # Optimization
        try:
            from app.core.optimization_engine import optimization_engine
            status = optimization_engine.get_status()
            context["optimization_state"] = status.current_phase
        except Exception:
            pass

        return context

    def get_system_health(self, context: Dict = None) -> Tuple[str, str]:
        """
        Get overall system health status.

        Returns (status_text, status_color).
        """
        if context is None:
            context = self.collect_context()

        # Check for critical issues
        if context.get("thermal_status") == "THROTTLING":
            return "THERMAL THROTTLING", "#F44336"

        gpu_temp = context.get("gpu_temp", 0)
        if gpu_temp and gpu_temp >= 90:
            return "THERMAL WARNING", "#FF5722"

        ram = context.get("ram_percent", 0)
        if ram >= 90:
            return "MEMORY CRITICAL", "#FF5722"

        cpu = context.get("cpu_percent", 0)
        if cpu >= 95:
            return "CPU SATURATED", "#FF5722"

        disk = context.get("disk_free_gb", 999)
        if disk < 5:
            return "DISK CRITICAL", "#F44336"

        # Check for warnings
        if ram >= 80:
            return "MEMORY PRESSURE", "#FF9800"
        if cpu >= 85:
            return "CPU HIGH", "#FF9800"
        if disk < 15:
            return "DISK LOW", "#FF9800"
        if gpu_temp and gpu_temp >= 80:
            return "THERMAL ELEVATED", "#FF9800"

        # All good
        active = self.active_recommendations
        if any(r.severity in (RecommendationSeverity.HIGH, RecommendationSeverity.CRITICAL)
               for r in active):
            return "ATTENTION NEEDED", "#FF9800"

        return "SYSTEM HEALTHY", "#4CAF50"

    # ── UI Summary ─────────────────────────────────────────────

    def get_ui_summary(self) -> Dict:
        """Get structured summary for UI consumption."""
        context = self.collect_context()
        health_text, health_color = self.get_system_health(context)
        active = self.active_recommendations

        return {
            "health_text": health_text,
            "health_color": health_color,
            "recommendation_count": len(active),
            "recommendations": [
                {
                    "title": r.title,
                    "explanation": r.explanation,
                    "severity": r.severity.value,
                    "severity_icon": r.severity_icon,
                    "severity_color": r.severity_color,
                    "action": r.action.value,
                    "category": r.category,
                }
                for r in active[:5]  # Top 5
            ],
        }

    # ── CLI Formatting ─────────────────────────────────────────

    def format_status(self) -> str:
        """Format current recommendations for CLI."""
        context = self.collect_context()
        health_text, _ = self.get_system_health(context)
        active = self.active_recommendations

        lines = []
        w = 55
        lines.append("=" * w)
        lines.append("  HEAVEN SOCIETY — SYSTEM RECOMMENDATIONS")
        lines.append("=" * w)
        lines.append("")

        # Health
        lines.append(f"  SYSTEM HEALTH: {health_text}")
        lines.append("")

        # Active recommendations
        if active:
            lines.append("  RECOMMENDATIONS")
            lines.append("  " + "-" * (w - 4))
            for rec in active:
                icon = rec.severity_icon
                lines.append(f"  {icon} [{rec.severity.value}] {rec.title}")
                lines.append(f"    {rec.explanation}")
                if rec.estimated_benefit:
                    lines.append(f"    Benefit: {rec.estimated_benefit}")
                if rec.risk and rec.risk != "NONE":
                    lines.append(f"    Risk: {rec.risk}")
                lines.append("")
        else:
            lines.append("  No active recommendations.")
            lines.append("  System appears healthy.")
            lines.append("")

        # Context summary
        lines.append("  CONTEXT")
        lines.append("  " + "-" * (w - 4))
        if context.get("cpu_percent"):
            lines.append(f"    CPU: {context['cpu_percent']:.0f}%")
        if context.get("ram_percent"):
            lines.append(f"    RAM: {context['ram_percent']:.0f}%")
        if context.get("gpu_percent"):
            lines.append(f"    GPU: {context['gpu_percent']:.0f}%")
        if context.get("gpu_temp"):
            lines.append(f"    GPU Temp: {context['gpu_temp']:.0f}°C")
        if context.get("disk_free_gb"):
            lines.append(f"    Disk: {context['disk_free_gb']:.1f} GB free")
        if context.get("target_name"):
            lines.append(f"    Target: {context['target_name']}")

        lines.append("")
        lines.append("=" * w)
        return "\n".join(lines)


# ── Singleton ─────────────────────────────────────────────────

intelligent_recommendation_engine = IntelligentRecommendationEngine()
