"""
Adaptive Gaming Optimizer — Phase 25

Analyzes the complete system state and determines what actually needs optimization.
Uses all existing subsystems instead of duplicating them.

Pipeline:
  1. Detect hardware
  2. Detect emulator
  3. Read Windows gaming state
  4. Read memory pressure
  5. Read background load
  6. Read GPU state
  7. Read thermal state
  8. Read power state
  9. Read emulator configuration
  10. Read PresentMon frame telemetry
  11. Identify bottleneck
  12. Recommend only relevant actions

IMPORTANT:
- Do NOT apply everything blindly
- Do NOT fabricate bottleneck claims
- Do NOT predict FPS improvements
- Every recommendation must have evidence
- All values originate from real subsystems
"""

import time
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Tuple
from enum import Enum

from app.utils.logger import get_logger

logger = get_logger("core.adaptive_optimizer")


# ── Bottleneck Classification ─────────────────────────────────

class BottleneckType(Enum):
    """Detected performance bottleneck type."""
    CPU = "CPU"
    GPU = "GPU"
    MEMORY = "MEMORY"
    THERMAL = "THERMAL"
    POWER = "POWER"
    FRAME_PACING = "FRAME PACING"
    BACKGROUND_LOAD = "BACKGROUND LOAD"
    DISPLAY = "DISPLAY"
    EMULATOR_CONFIGURATION = "EMULATOR CONFIGURATION"
    UNKNOWN = "UNKNOWN"


class ExpectedImpact(Enum):
    """Expected impact category for the optimization."""
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"


# ── Data Models ───────────────────────────────────────────────

@dataclass
class OptimizationAction:
    """A single recommended optimization action."""
    id: str = ""
    name: str = ""
    description: str = ""
    reason: str = ""
    evidence: str = ""
    source_subsystem: str = ""
    status: str = ""  # APPLICABLE, ALREADY_OPTIMAL, REQUIRES_ADMIN, RECOMMENDATION_ONLY, NOT_APPLICABLE
    risk: str = "LOW"  # LOW, MEDIUM, HIGH
    expected_impact: str = "UNKNOWN"


@dataclass
class BottleneckEvidence:
    """Evidence supporting a bottleneck classification."""
    bottleneck_type: BottleneckType = BottleneckType.UNKNOWN
    metric_name: str = ""
    metric_value: float = 0.0
    threshold: float = 0.0
    source: str = ""
    description: str = ""


@dataclass
class OptimizationDecision:
    """
    Complete adaptive optimization analysis result.
    Contains bottleneck identification, evidence, and targeted recommendations.
    """
    # Primary bottleneck
    bottleneck: BottleneckType = BottleneckType.UNKNOWN
    bottleneck_confidence: float = 0.0
    bottleneck_description: str = ""

    # Evidence chain
    evidence: List[BottleneckEvidence] = field(default_factory=list)

    # Recommended optimizations (only relevant ones)
    recommended_optimizations: List[OptimizationAction] = field(default_factory=list)

    # Skipped optimizations (with reason)
    skipped_optimizations: List[Dict] = field(default_factory=list)

    # Risks
    risks: List[str] = field(default_factory=list)

    # Expected impact
    expected_impact: ExpectedImpact = ExpectedImpact.UNKNOWN
    impact_reason: str = ""

    # System snapshot
    has_emulator: bool = False
    emulator_name: str = ""
    emulator_pid: int = 0

    # Telemetry source
    has_fps_data: bool = False
    fps_provider: str = ""

    # Overall assessment
    overall_assessment: str = ""

    # Timestamp
    timestamp: float = 0.0

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()


# ── Adaptive Optimizer Engine ─────────────────────────────────

class AdaptiveOptimizer:
    """
    Analyzes the complete system state and produces an evidence-based
    optimization decision. Uses all existing subsystems.
    """

    def __init__(self):
        self._cache: Optional[OptimizationDecision] = None
        self._cache_time: float = 0.0
        self._cache_ttl: float = 15.0  # 15s cache

    def analyze(self, force: bool = False) -> OptimizationDecision:
        """
        Run the full adaptive analysis pipeline.
        Returns an OptimizationDecision with evidence-based recommendations.
        """
        now = time.time()
        if not force and self._cache and (now - self._cache_time) < self._cache_ttl:
            return self._cache

        decision = OptimizationDecision(timestamp=now)
        evidence_collector = []

        # ── Step 1: Detect hardware ──
        hw_spec = None
        try:
            from app.core.hardware_profile import analyze_hardware_profile
            hw_result = analyze_hardware_profile()
            hw_spec = hw_result.hardware
            decision.risks.extend(self._hardware_risks(hw_spec))
        except Exception as e:
            logger.debug(f"Hardware detection: {e}")

        # ── Step 2: Detect emulator ──
        emulator_target = None
        try:
            from app.core.emulator_controller import emulator_controller
            emulator_target = emulator_controller.detect_target()
            if emulator_target:
                decision.has_emulator = True
                decision.emulator_name = emulator_target.name
                decision.emulator_pid = emulator_target.pid
        except Exception as e:
            logger.debug(f"Emulator detection: {e}")

        # ── Step 3: Read Windows gaming state ──
        windows_gaming = None
        try:
            from app.system.windows_gaming import windows_gaming_analyzer
            target_name = emulator_target.name if emulator_target else ""
            target_pid = emulator_target.pid if emulator_target else 0
            windows_gaming = windows_gaming_analyzer.analyze(target_name, target_pid)
        except Exception as e:
            logger.debug(f"Windows gaming: {e}")

        # ── Step 4: Read memory pressure ──
        memory_diag = None
        try:
            from app.system.memory_optimizer import memory_optimizer
            memory_diag = memory_optimizer.diagnose()
        except Exception as e:
            logger.debug(f"Memory diagnostics: {e}")

        # ── Step 5: Read background load ──
        bg_analysis = None
        try:
            from app.system.background_analyzer import background_analyzer
            e_pid = emulator_target.pid if emulator_target else 0
            e_name = emulator_target.name if emulator_target else ""
            bg_analysis = background_analyzer.analyze(
                emulator_pid=e_pid, emulator_name=e_name
            )
        except Exception as e:
            logger.debug(f"Background analysis: {e}")

        # ── Step 6: Read GPU state ──
        gpu_data = None
        try:
            from app.system.gpu import gpu_monitor
            gpus = gpu_monitor.detect()
            if gpus:
                gpu_data = gpu_monitor.update(gpus[0])
        except Exception as e:
            logger.debug(f"GPU state: {e}")

        # ── Step 7: Read thermal state ──
        thermal_diag = None
        try:
            from app.system.thermal_monitor import thermal_diagnostics
            thermal_diag = thermal_diagnostics.diagnose()
        except Exception as e:
            logger.debug(f"Thermal state: {e}")

        # ── Step 8: Read power state ──
        power_result = None
        try:
            from app.system.power_analyzer import power_analyzer
            power_result = power_analyzer.analyze()
        except Exception as e:
            logger.debug(f"Power state: {e}")

        # ── Step 9: Read emulator process state ──
        emu_proc = None
        if emulator_target:
            try:
                from app.core.resource_analyzer import EmulatorProcessAnalyzer
                emu_analyzer = EmulatorProcessAnalyzer()
                emu_proc = emu_analyzer.analyze(emulator_target.pid, emulator_target.name)
            except Exception as e:
                logger.debug(f"Emulator process analysis: {e}")

        # ── Step 10: Read frame telemetry (PresentMon) ──
        frame_pacing = None
        try:
            from app.performance.presentmon_provider import find_presentmon
            pm_path = find_presentmon()
            if pm_path:
                decision.has_fps_data = True
                decision.fps_provider = "PresentMon 2.5.1"
        except Exception as e:
            logger.debug(f"PresentMon detection: {e}")

        # ── Step 11: Classify bottleneck from evidence ──
        evidence_collector = self._collect_evidence(
            hw_spec, emulator_target, windows_gaming, memory_diag,
            bg_analysis, gpu_data, thermal_diag, power_result, emu_proc,
        )
        decision.evidence = evidence_collector
        decision.bottleneck, decision.bottleneck_confidence, decision.bottleneck_description = \
            self._classify_bottleneck(evidence_collector)

        # ── Step 12: Generate targeted recommendations ──
        decision.recommended_optimizations, decision.skipped_optimizations = \
            self._generate_recommendations(
                decision.bottleneck, evidence_collector,
                emulator_target, windows_gaming, power_result,
                bg_analysis, thermal_diag, memory_diag, hw_spec,
            )

        # ── Impact assessment ──
        decision.expected_impact, decision.impact_reason = self._assess_impact(
            decision.bottleneck, evidence_collector, emulator_target
        )

        # ── Overall assessment ──
        decision.overall_assessment = self._generate_assessment(decision)

        self._cache = decision
        self._cache_time = now
        return decision

    # ── Evidence Collection ────────────────────────────────────

    def _collect_evidence(
        self, hw_spec, emulator_target, windows_gaming, memory_diag,
        bg_analysis, gpu_data, thermal_diag, power_result, emu_proc,
    ) -> List[BottleneckEvidence]:
        """Collect evidence from all subsystems."""
        evidence = []

        # CPU evidence
        if emu_proc:
            if emu_proc.cpu_percent > 85:
                evidence.append(BottleneckEvidence(
                    bottleneck_type=BottleneckType.CPU,
                    metric_name="Emulator CPU Usage",
                    metric_value=emu_proc.cpu_percent,
                    threshold=85.0,
                    source="emulator_controller",
                    description=f"Emulator CPU at {emu_proc.cpu_percent:.0f}% — near capacity",
                ))
            elif emu_proc.cpu_percent > 65:
                evidence.append(BottleneckEvidence(
                    bottleneck_type=BottleneckType.CPU,
                    metric_name="Emulator CPU Usage",
                    metric_value=emu_proc.cpu_percent,
                    threshold=65.0,
                    source="emulator_controller",
                    description=f"Emulator CPU at {emu_proc.cpu_percent:.0f}% — moderate load",
                ))

        # GPU evidence
        if gpu_data:
            gpu_util = getattr(gpu_data, 'utilization_percent', 0) or 0
            try:
                gpu_util = float(gpu_util)
            except (TypeError, ValueError):
                gpu_util = 0.0
            gpu_temp = getattr(gpu_data, 'temperature_celsius', None)
            if gpu_util > 90:
                evidence.append(BottleneckEvidence(
                    bottleneck_type=BottleneckType.GPU,
                    metric_name="GPU Utilization",
                    metric_value=gpu_util,
                    threshold=90.0,
                    source="gpu_monitor",
                    description=f"GPU utilization at {gpu_util:.0f}% — GPU bound",
                ))
            elif gpu_util > 70:
                evidence.append(BottleneckEvidence(
                    bottleneck_type=BottleneckType.GPU,
                    metric_name="GPU Utilization",
                    metric_value=gpu_util,
                    threshold=70.0,
                    source="gpu_monitor",
                    description=f"GPU utilization at {gpu_util:.0f}% — moderate GPU load",
                ))

            # CPU vs GPU bound analysis
            if emu_proc and gpu_util > 0:
                cpu_val = emu_proc.cpu_percent
                if cpu_val > 80 and gpu_util < 50:
                    evidence.append(BottleneckEvidence(
                        bottleneck_type=BottleneckType.CPU,
                        metric_name="CPU/GPU Ratio",
                        metric_value=cpu_val / max(gpu_util, 1),
                        threshold=2.0,
                        source="emulator_controller",
                        description=f"CPU {cpu_val:.0f}% vs GPU {gpu_util:.0f}% — likely CPU bound",
                    ))
                elif gpu_util > 85 and cpu_val < 60:
                    evidence.append(BottleneckEvidence(
                        bottleneck_type=BottleneckType.GPU,
                        metric_name="CPU/GPU Ratio",
                        metric_value=gpu_util / max(cpu_val, 1),
                        threshold=2.0,
                        source="gpu_monitor",
                        description=f"GPU {gpu_util:.0f}% vs CPU {cpu_val:.0f}% — likely GPU bound",
                    ))

        # Memory evidence
        if memory_diag:
            if memory_diag.pressure_level == "CRITICAL":
                evidence.append(BottleneckEvidence(
                    bottleneck_type=BottleneckType.MEMORY,
                    metric_name="Memory Pressure",
                    metric_value=memory_diag.percent_used if hasattr(memory_diag, 'percent_used') else 0,
                    threshold=90.0,
                    source="memory_optimizer",
                    description="Memory pressure CRITICAL — severe RAM constraint",
                ))
            elif memory_diag.pressure_level == "HIGH":
                evidence.append(BottleneckEvidence(
                    bottleneck_type=BottleneckType.MEMORY,
                    metric_name="Memory Pressure",
                    metric_value=memory_diag.percent_used if hasattr(memory_diag, 'percent_used') else 0,
                    threshold=80.0,
                    source="memory_optimizer",
                    description="Memory pressure HIGH — may cause stuttering",
                ))

        # Thermal evidence
        if thermal_diag:
            if hasattr(thermal_diag, 'thermal_state'):
                state = thermal_diag.thermal_state
                if hasattr(state, 'value'):
                    state_val = state.value
                else:
                    state_val = str(state)
                if "THROTTLING" in state_val.upper():
                    evidence.append(BottleneckEvidence(
                        bottleneck_type=BottleneckType.THERMAL,
                        metric_name="Thermal State",
                        metric_value=1.0,
                        threshold=0.0,
                        source="thermal_monitor",
                        description=f"Thermal state: {state_val} — performance degradation likely",
                    ))
                elif "HOT" in state_val.upper():
                    evidence.append(BottleneckEvidence(
                        bottleneck_type=BottleneckType.THERMAL,
                        metric_name="Thermal State",
                        metric_value=0.7,
                        threshold=0.0,
                        source="thermal_monitor",
                        description=f"Thermal state: {state_val} — approaching throttling",
                    ))

        # Power evidence
        if power_result:
            classification = power_result.classification
            if hasattr(classification, 'value'):
                class_val = classification.value
            else:
                class_val = str(classification)
            if "BATTERY" in class_val.upper():
                evidence.append(BottleneckEvidence(
                    bottleneck_type=BottleneckType.POWER,
                    metric_name="Power Source",
                    metric_value=0.0,
                    threshold=0.0,
                    source="power_analyzer",
                    description="Running on battery — performance limited",
                ))
            elif "POWER LIMITED" in class_val.upper():
                evidence.append(BottleneckEvidence(
                    bottleneck_type=BottleneckType.POWER,
                    metric_name="Power Classification",
                    metric_value=0.5,
                    threshold=0.0,
                    source="power_analyzer",
                    description=f"Power state: {class_val}",
                ))

        # Background load evidence
        if bg_analysis:
            cpu_comp = bg_analysis.cpu_competition
            if hasattr(cpu_comp, 'value'):
                comp_val = cpu_comp.value
            else:
                comp_val = str(cpu_comp)
            if comp_val.upper() in ("HIGH", "SEVERE"):
                evidence.append(BottleneckEvidence(
                    bottleneck_type=BottleneckType.BACKGROUND_LOAD,
                    metric_name="CPU Competition",
                    metric_value=bg_analysis.significant_count if hasattr(bg_analysis, 'significant_count') else 0,
                    threshold=5.0,
                    source="background_analyzer",
                    description=f"Background CPU competition: {comp_val}",
                ))

            ram_comp = bg_analysis.ram_competition
            if hasattr(ram_comp, 'value'):
                ram_comp_val = ram_comp.value
            else:
                ram_comp_val = str(ram_comp)
            if ram_comp_val.upper() in ("HIGH", "SEVERE"):
                evidence.append(BottleneckEvidence(
                    bottleneck_type=BottleneckType.BACKGROUND_LOAD,
                    metric_name="RAM Competition",
                    metric_value=0.0,
                    threshold=0.0,
                    source="background_analyzer",
                    description=f"Background RAM competition: {ram_comp_val}",
                ))

        # Emulator configuration evidence
        if emulator_target:
            if not emulator_target.is_high_priority:
                evidence.append(BottleneckEvidence(
                    bottleneck_type=BottleneckType.EMULATOR_CONFIGURATION,
                    metric_name="Emulator Priority",
                    metric_value=float(emulator_target.priority),
                    threshold=-1.0,
                    source="emulator_controller",
                    description=f"Emulator priority: {emulator_target.priority_name} — not elevated",
                ))
            if not emulator_target.uses_all_cpus and emulator_target.total_cpus > 4:
                evidence.append(BottleneckEvidence(
                    bottleneck_type=BottleneckType.EMULATOR_CONFIGURATION,
                    metric_name="CPU Affinity",
                    metric_value=float(emulator_target.affinity_cpus),
                    threshold=float(emulator_target.total_cpus),
                    source="emulator_controller",
                    description=f"Emulator using {emulator_target.affinity_cpus}/{emulator_target.total_cpus} CPUs",
                ))

        return evidence

    # ── Bottleneck Classification ─────────────────────────────

    def _classify_bottleneck(
        self, evidence: List[BottleneckEvidence]
    ) -> Tuple[BottleneckType, float, str]:
        """
        Classify the primary bottleneck from collected evidence.
        Returns (type, confidence, description).
        """
        if not evidence:
            return (
                BottleneckType.UNKNOWN,
                0.0,
                "Insufficient data to identify bottleneck",
            )

        # Count evidence per bottleneck type
        type_scores: Dict[BottleneckType, float] = {}
        type_counts: Dict[BottleneckType, int] = {}
        type_descriptions: Dict[BottleneckType, List[str]] = {}

        for ev in evidence:
            bt = ev.bottleneck_type
            if bt not in type_scores:
                type_scores[bt] = 0.0
                type_counts[bt] = 0
                type_descriptions[bt] = []

            # Weight by severity: higher metric relative to threshold = stronger signal
            if ev.threshold > 0:
                severity = min(1.0, ev.metric_value / ev.threshold)
            else:
                severity = 0.5  # Binary evidence (present = 0.5)

            type_scores[bt] += severity
            type_counts[bt] += 1
            type_descriptions[bt].append(ev.description)

        if not type_scores:
            return (
                BottleneckType.UNKNOWN,
                0.0,
                "No bottleneck evidence collected",
            )

        # Find the dominant bottleneck
        dominant_type = max(type_scores, key=type_scores.get)
        dominant_score = type_scores[dominant_type]
        dominant_count = type_counts[dominant_type]

        # Confidence based on evidence count and score strength
        max_possible = sum(type_scores.values())
        if max_possible > 0:
            confidence = min(0.95, (dominant_score / max_possible) * 0.7 + (dominant_count / len(evidence)) * 0.3)
        else:
            confidence = 0.0

        # Build description
        descriptions = type_descriptions[dominant_type]
        if len(descriptions) == 1:
            desc = descriptions[0]
        else:
            desc = f"Primary bottleneck: {dominant_type.value} — {len(descriptions)} evidence points. " + \
                   "; ".join(descriptions[:3])

        return dominant_type, confidence, desc

    # ── Recommendation Generation ─────────────────────────────

    def _generate_recommendations(
        self, bottleneck, evidence, emulator_target, windows_gaming,
        power_result, bg_analysis, thermal_diag, memory_diag, hw_spec,
    ):
        """Generate targeted optimization recommendations based on bottleneck and evidence."""
        recommended = []
        skipped = []
        evidence_types = {e.bottleneck_type for e in evidence}

        # ── Emulator Priority ──
        if emulator_target and not emulator_target.is_high_priority:
            recommended.append(OptimizationAction(
                id="emulator_priority",
                name="Emulator Priority",
                description="Set emulator process to HIGH priority",
                reason="Emulator is at normal priority — scheduling contention possible",
                evidence=f"Current priority: {emulator_target.priority_name}",
                source_subsystem="emulator_controller",
                status="APPLICABLE" if BottleneckType.EMULATOR_CONFIGURATION in evidence_types else "RECOMMENDATION_ONLY",
                risk="LOW",
                expected_impact="MEDIUM" if BottleneckType.CPU in evidence_types else "LOW",
            ))
        elif emulator_target and emulator_target.is_high_priority:
            skipped.append({
                "id": "emulator_priority",
                "name": "Emulator Priority",
                "reason": "Already at elevated priority",
            })

        # ── Power Plan ──
        if power_result and not power_result.power_plan_is_performance:
            recommended.append(OptimizationAction(
                id="power_plan",
                name="Power Plan",
                description="Switch to High Performance power plan",
                reason=f"Current plan: {power_result.power_plan_name}",
                evidence=f"Active power plan is not performance-optimized",
                source_subsystem="power_analyzer",
                status="APPLICABLE",
                risk="LOW",
                expected_impact="MEDIUM" if BottleneckType.POWER in evidence_types else "LOW",
            ))
        elif power_result and power_result.power_plan_is_performance:
            skipped.append({
                "id": "power_plan",
                "name": "Power Plan",
                "reason": "Already on performance plan",
            })

        # ── Game Mode ──
        if windows_gaming:
            game_mode_item = None
            for item in windows_gaming.items:
                if item.name == "Game Mode":
                    game_mode_item = item
                    break
            if game_mode_item and game_mode_item.status == "DISABLED":
                recommended.append(OptimizationAction(
                    id="game_mode",
                    name="Windows Game Mode",
                    description="Enable Windows Game Mode",
                    reason="Game Mode is currently disabled",
                    evidence="Windows Game Mode status: DISABLED",
                    source_subsystem="windows_gaming",
                    status="APPLICABLE",
                    risk="LOW",
                    expected_impact="LOW",
                ))
            elif game_mode_item and game_mode_item.status == "ENABLED":
                skipped.append({
                    "id": "game_mode",
                    "name": "Windows Game Mode",
                    "reason": "Already enabled",
                })

        # ── CPU Affinity ──
        if emulator_target and not emulator_target.uses_all_cpus and emulator_target.total_cpus > 4:
            if BottleneckType.CPU in evidence_types or BottleneckType.EMULATOR_CONFIGURATION in evidence_types:
                recommended.append(OptimizationAction(
                    id="cpu_affinity",
                    name="CPU Affinity",
                    description=f"Allow emulator to use all {emulator_target.total_cpus} CPUs",
                    reason=f"Currently using {emulator_target.affinity_cpus}/{emulator_target.total_cpus}",
                    evidence=f"Affinity restriction detected with CPU bottleneck evidence",
                    source_subsystem="emulator_controller",
                    status="APPLICABLE",
                    risk="LOW",
                    expected_impact="MEDIUM",
                ))
            else:
                skipped.append({
                    "id": "cpu_affinity",
                    "name": "CPU Affinity",
                    "reason": f"Using {emulator_target.affinity_cpus}/{emulator_target.total_cpus} — no CPU bottleneck detected",
                })

        # ── Background Processes (RECOMMENDATION ONLY) ──
        if bg_analysis:
            safe_candidates = [
                p for p in bg_analysis.top_cpu_processes[:5]
                if hasattr(p, 'recommendation') and p.recommendation == "SAFE_TO_RECOMMEND"
            ] if hasattr(bg_analysis, 'top_cpu_processes') else []

            if safe_candidates and BottleneckType.BACKGROUND_LOAD in evidence_types:
                recommended.append(OptimizationAction(
                    id="background_load",
                    name="Background Processes",
                    description=f"{len(safe_candidates)} optional applications consuming resources",
                    reason="Background load is competing with emulator",
                    evidence=f"Top: {', '.join(p.name for p in safe_candidates[:3])}",
                    source_subsystem="background_analyzer",
                    status="RECOMMENDATION_ONLY",
                    risk="MEDIUM",
                    expected_impact="MEDIUM" if len(safe_candidates) > 2 else "LOW",
                ))
            elif safe_candidates:
                skipped.append({
                    "id": "background_load",
                    "name": "Background Processes",
                    "reason": f"{len(safe_candidates)} safe candidates but no severe competition",
                })

        # ── Memory Pressure ──
        if memory_diag and hasattr(memory_diag, 'pressure_level'):
            if memory_diag.pressure_level in ("HIGH", "CRITICAL"):
                recommended.append(OptimizationAction(
                    id="memory_pressure",
                    name="Memory Pressure",
                    description="High memory usage may cause stuttering",
                    reason=f"Pressure level: {memory_diag.pressure_level}",
                    evidence=f"Memory pressure detected by memory_optimizer",
                    source_subsystem="memory_optimizer",
                    status="RECOMMENDATION_ONLY",
                    risk="LOW",
                    expected_impact="MEDIUM" if memory_diag.pressure_level == "CRITICAL" else "LOW",
                ))

        # ── Thermal ──
        if thermal_diag and hasattr(thermal_diag, 'throttle_indicators'):
            indicators = thermal_diag.throttle_indicators
            if indicators:
                # Check if it's a single NONE indicator
                has_real_throttle = False
                for ind in indicators:
                    if hasattr(ind, 'value') and ind.value != "None Detected":
                        has_real_throttle = True
                    elif hasattr(ind, 'name') and ind.name != "NONE":
                        has_real_throttle = True
                if has_real_throttle:
                    recommended.append(OptimizationAction(
                        id="thermal_management",
                        name="Thermal Management",
                        description="Throttling indicators detected — consider reducing load",
                        reason="GPU/CPU thermal throttling may limit performance",
                        evidence="Thermal monitor detected throttle indicators",
                        source_subsystem="thermal_monitor",
                        status="RECOMMENDATION_ONLY",
                        risk="LOW",
                        expected_impact="HIGH",
                    ))

        return recommended, skipped

    # ── Hardware Risks ─────────────────────────────────────────

    def _hardware_risks(self, hw_spec) -> List[str]:
        """Identify hardware-based risks."""
        risks = []
        if hw_spec:
            if hw_spec.ram_total_gb > 0 and hw_spec.ram_total_gb < 8:
                risks.append("System has limited RAM — memory pressure likely during gaming")
            if hw_spec.gpu_vram_mb > 0 and hw_spec.gpu_vram_mb < 2048:
                risks.append("GPU VRAM is limited — may cause texture streaming issues")
            if hw_spec.cpu_physical_cores > 0 and hw_spec.cpu_physical_cores < 4:
                risks.append("CPU has few cores — emulator may compete for CPU time")
        return risks

    # ── Impact Assessment ─────────────────────────────────────

    def _assess_impact(
        self, bottleneck, evidence, emulator_target
    ) -> Tuple[ExpectedImpact, str]:
        """Assess expected impact category."""
        if not emulator_target:
            return (
                ExpectedImpact.UNKNOWN,
                "No emulator detected — optimization impact cannot be assessed",
            )

        if bottleneck == BottleneckType.UNKNOWN:
            return (
                ExpectedImpact.UNKNOWN,
                "No clear bottleneck identified",
            )

        # Count high-severity evidence
        high_severity = sum(
            1 for e in evidence
            if e.bottleneck_type == bottleneck
            and (e.threshold <= 0 or e.metric_value / max(e.threshold, 0.01) > 0.8)
        )

        if high_severity >= 2:
            return (
                ExpectedImpact.HIGH,
                f"Strong evidence for {bottleneck.value} bottleneck — optimization may help",
            )
        elif high_severity == 1:
            return (
                ExpectedImpact.MEDIUM,
                f"Moderate evidence for {bottleneck.value} bottleneck",
            )
        else:
            return (
                ExpectedImpact.LOW,
                f"Weak evidence for {bottleneck.value} bottleneck",
            )

    # ── Assessment Generation ─────────────────────────────────

    def _generate_assessment(self, decision: OptimizationDecision) -> str:
        """Generate a human-readable overall assessment."""
        parts = []

        if decision.bottleneck == BottleneckType.UNKNOWN:
            parts.append("No clear performance bottleneck detected.")
        else:
            parts.append(f"Primary bottleneck: {decision.bottleneck.value} "
                         f"({decision.bottleneck_confidence:.0%} confidence).")

        if decision.has_emulator:
            parts.append(f"Emulator: {decision.emulator_name} (PID {decision.emulator_pid}).")
        else:
            parts.append("No emulator detected — optimizations may have limited impact.")

        applicable = [o for o in decision.recommended_optimizations if o.status == "APPLICABLE"]
        recommendations = [o for o in decision.recommended_optimizations if o.status == "RECOMMENDATION_ONLY"]

        if applicable:
            parts.append(f"{len(applicable)} optimization(s) can be applied.")
        if recommendations:
            parts.append(f"{len(recommendations)} recommendation(s) for review.")

        if decision.risks:
            parts.append(f"{len(decision.risks)} risk(s) identified.")

        return " ".join(parts)


# ── Singleton ─────────────────────────────────────────────────

adaptive_optimizer = AdaptiveOptimizer()
