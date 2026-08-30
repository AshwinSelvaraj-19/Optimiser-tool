"""
Prerequisite checker — validates all required components.
Reports PASS/FAIL for each prerequisite with actionable guidance.
"""

import os
import subprocess
import shutil
from dataclasses import dataclass, field
from typing import Optional

from app.utils.logger import get_logger

logger = get_logger("performance.prerequisites")


@dataclass
class Prerequisite:
    """A single prerequisite check result."""
    name: str = ""
    status: str = "UNKNOWN"  # PASS, FAIL, WARN
    detail: str = ""
    action_required: str = ""


@dataclass
class PrerequisiteReport:
    """Complete prerequisite check report."""
    prerequisites: list = field(default_factory=list)
    all_passed: bool = False

    def add(self, name: str, status: str, detail: str, action: str = ""):
        self.prerequisites.append(Prerequisite(name=name, status=status, detail=detail, action_required=action))

    def evaluate(self):
        self.all_passed = all(p.status == "PASS" for p in self.prerequisites if p.status != "WARN")


class PrerequisiteChecker:
    """Checks all prerequisites for the optimization pipeline."""

    def check_all(self) -> PrerequisiteReport:
        """Run all prerequisite checks."""
        report = PrerequisiteReport()

        self._check_nvidia_gpu(report)
        self._check_nvml(report)
        self._check_msi_app_player(report)
        self._check_presentmon(report)
        self._check_display(report)
        self._check_windows_version(report)
        self._check_admin(report)

        # FPS provider status
        from app.performance.fps_provider import fps_registry
        providers = fps_registry.detect_available()
        fps_available = any(p["available"] for p in providers)
        if fps_available:
            active = next(p["name"] for p in providers if p["available"])
            report.add("FPS Provider", "PASS", f"Active: {active}")
        else:
            report.add("FPS Provider", "FAIL", "No frame-timing provider available",
                       "Install Intel PresentMon for real FPS measurement")

        report.evaluate()
        return report

    def _check_nvidia_gpu(self, report: PrerequisiteReport):
        try:
            from app.system.gpu import gpu_monitor
            gpus = gpu_monitor.detect()
            nvidia = [g for g in gpus if g.vendor == "NVIDIA"]
            if nvidia:
                report.add("NVIDIA GPU", "PASS", f"{nvidia[0].name} ({nvidia[0].vram_total_mb:.0f}MB)")
            else:
                report.add("NVIDIA GPU", "FAIL", "No NVIDIA GPU detected",
                           "NVIDIA GPU required for full GPU telemetry")
        except Exception as e:
            report.add("NVIDIA GPU", "FAIL", str(e))

    def _check_nvml(self, report: PrerequisiteReport):
        try:
            import pynvml
            pynvml.nvmlInit()
            count = pynvml.nvmlDeviceGetCount()
            pynvml.nvmlShutdown()
            report.add("NVML", "PASS", f"{count} GPU(s) accessible")
        except ImportError:
            report.add("NVML", "FAIL", "pynvml not installed",
                       "pip install pynvml")
        except Exception as e:
            report.add("NVML", "FAIL", str(e))

    def _check_msi_app_player(self, report: PrerequisiteReport):
        from app.emulator.detector import emulator_detector
        emus = emulator_detector.detect_all()
        msi = [e for e in emus if "MSI" in e.DISPLAY_NAME or "BlueStacks" in e.DISPLAY_NAME]
        if msi:
            e = msi[0]
            status = "RUNNING" if e.info.is_running else "Installed"
            detail = f"{e.DISPLAY_NAME} — {status}"
            if e.info.version:
                detail += f" (v{e.info.version})"
            if e.info.install_path:
                detail += f"\n    Path: {e.info.install_path}"
            report.add("MSI App Player", "PASS", detail)
        else:
            report.add("MSI App Player", "FAIL", "Not installed",
                       "Download and install MSI App Player from https://www.msi.com/Landing/msi-app-player")

    def _check_presentmon(self, report: PrerequisiteReport):
        from app.performance.presentmon_provider import find_presentmon, get_presentmon_version
        exe_path = find_presentmon()
        if exe_path:
            version = get_presentmon_version(exe_path)
            ver_str = f" v{version}" if version else ""
            report.add("PresentMon", "PASS", f"{exe_path.name}{ver_str}\n    Path: {exe_path}")
        else:
            report.add("PresentMon", "FAIL", "Not installed",
                       "Download from https://github.com/GameTechDev/PresentMon/releases")

    def _check_display(self, report: PrerequisiteReport):
        try:
            from app.system.display import display_monitor
            info = display_monitor.detect()
            report.add("Display", "PASS", f"{info.resolution_x}x{info.resolution_y} @ {info.refresh_rate_hz}Hz")
        except Exception as e:
            report.add("Display", "FAIL", str(e))

    def _check_windows_version(self, report: PrerequisiteReport):
        import platform
        ver = platform.platform()
        if "Windows" in ver:
            report.add("Windows", "PASS", ver)
        else:
            report.add("Windows", "WARN", f"Not Windows: {ver}", "Optimizations are Windows-specific")

    def _check_admin(self, report: PrerequisiteReport):
        from app.utils.admin import is_admin
        if is_admin():
            report.add("Admin", "PASS", "Running as administrator")
        else:
            report.add("Admin", "WARN", "Not administrator — some optimizations limited",
                       "Run as admin for full optimization access")


def print_prerequisite_report(report: PrerequisiteReport):
    """Print formatted prerequisite report."""
    print("=" * 50)
    print("PHOENIX PREREQUISITES")
    print("=" * 50)

    for p in report.prerequisites:
        icon = "[PASS]" if p.status == "PASS" else "[FAIL]" if p.status == "FAIL" else "[WARN]"
        print(f"\n  {p.name:<20} {icon}")
        for line in p.detail.split("\n"):
            print(f"    {line}")
        if p.action_required:
            print(f"    -> {p.action_required}")

    print("\n" + "-" * 50)
    if report.all_passed:
        print("  ALL PREREQUISITES MET")
    else:
        failed = [p for p in report.prerequisites if p.status == "FAIL"]
        print(f"  {len(failed)} prerequisite(s) missing")
        print("  Fix the issues above before running the full pipeline.")
    print("=" * 50)
