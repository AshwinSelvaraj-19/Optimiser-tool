"""
Phoenix Performance Optimizer — Main Entry Point.

Usage:
    python main.py              Launch GUI
    python main.py --diagnostic Run diagnostic report
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def run_diagnostic():
    """Run full system diagnostic and print report."""
    import json
    from app.utils.logger import setup_logging
    setup_logging()

    print("=" * 50)
    print("PHOENIX DIAGNOSTIC")
    print("=" * 50)

    # OS
    import platform
    print(f"\nOS:\n  {platform.platform()}")

    # CPU
    try:
        from app.system.cpu import cpu_monitor
        info = cpu_monitor.detect()
        print(f"\nCPU:\n  Model: {info.model}\n  Cores: {info.physical_cores}C/{info.logical_cores}T\n  Frequency: {info.max_frequency_mhz:.0f} MHz")
        temp = cpu_monitor.get_temperature()
        print(f"  Temperature: {temp:.0f}°C" if temp else "  Temperature: N/A (not exposed by hardware)")
    except Exception as e:
        print(f"\nCPU:\n  ERROR: {e}")

    # RAM
    try:
        from app.system.memory import memory_monitor
        info = memory_monitor.detect()
        print(f"\nRAM:\n  Total: {info.ram_total_gb:.1f} GB\n  Used: {info.ram_used_gb:.1f} GB ({info.ram_percent:.1f}%)")
    except Exception as e:
        print(f"\nRAM:\n  ERROR: {e}")

    # GPU
    try:
        from app.system.gpu import gpu_monitor, NVML_AVAILABLE
        gpus = gpu_monitor.detect()
        print(f"\nGPU:\n  NVML: {'Available' if NVML_AVAILABLE else 'Not installed'}")
        for i, g in enumerate(gpus):
            gpu_type = "Discrete" if g.is_discrete else ("Integrated" if g.is_integrated else "Unknown")
            print(f"  GPU {i}: {g.name} ({g.vendor}, {gpu_type})")
            print(f"    VRAM: {g.vram_total_mb:.0f} MB")
            print(f"    Driver: {g.driver_version}")
        # GPU telemetry
        if gpus and gpus[0].vendor == "NVIDIA":
            g = gpu_monitor.update_nvidia(gpus[0])
            print(f"    Utilization: {g.utilization_gpu:.1f}%")
            print(f"    Temperature: {g.temperature_celsius}°C" if g.temperature_celsius else "    Temperature: N/A")
            print(f"    Clock: {g.clock_core_mhz:.0f} MHz" if g.clock_core_mhz else "    Clock: N/A")
            print(f"    VRAM Used: {g.vram_used_mb:.0f}/{g.vram_total_mb:.0f} MB")
    except Exception as e:
        print(f"\nGPU:\n  ERROR: {e}")

    # Display
    try:
        from app.system.display import display_monitor
        info = display_monitor.detect()
        print(f"\nDisplay:\n  Resolution: {info.resolution_x}x{info.resolution_y}\n  Refresh Rate: {info.refresh_rate_hz} Hz")
    except Exception as e:
        print(f"\nDisplay:\n  ERROR: {e}")

    # Emulator
    try:
        from app.emulator.detector import emulator_detector
        emus = emulator_detector.detect_all()
        print(f"\nEmulator:")
        if emus:
            for e in emus:
                status = "RUNNING" if e.info.is_running else "Installed (not running)"
                print(f"  {e.DISPLAY_NAME}: {status}")
                if e.info.install_path:
                    print(f"    Path: {e.info.install_path}")
                if e.info.version:
                    print(f"    Version: {e.info.version}")
                if e.info.config_path:
                    print(f"    Config: {e.info.config_path}")
        else:
            print("  No emulators detected")
    except Exception as e:
        print(f"\nEmulator:\n  ERROR: {e}")

    # GPU Used by Emulator
    print(f"\nGPU Used by Emulator:")
    print(f"  Requires running emulator to determine. Run diagnostic with emulator active.")

    # Power
    try:
        from app.system.power import power_monitor
        info = power_monitor.detect()
        print(f"\nPower:\n  Current: {info.active_plan_name}\n  GUID: {info.active_plan_guid}")
        if info.available_plans:
            print("  Available plans:")
            for p in info.available_plans:
                active = " *" if p["active"] else ""
                print(f"    - {p['name']}{active}")
    except Exception as e:
        print(f"\nPower:\n  ERROR: {e}")

    # Game Mode
    try:
        from app.utils.registry import read_registry_value
        gm = read_registry_value("HKCU", r"Software\Microsoft\GameBar", "AutoGameModeEnabled")
        print(f"\nGame Mode:\n  {'ENABLED' if gm == 1 else 'DISABLED'}")
    except Exception as e:
        print(f"\nGame Mode:\n  ERROR: {e}")

    # FPS Provider / PresentMon
    try:
        from app.performance.presentmon_provider import find_presentmon, get_presentmon_version
        pm_path = find_presentmon()
        print(f"\nPresentMon:")
        if pm_path:
            ver = get_presentmon_version(pm_path)
            print(f"  Executable: {pm_path.name}")
            print(f"  Version: {ver or 'Unknown'}")
            print(f"  Path: {pm_path}")
            print(f"  Available: YES")
        else:
            print(f"  Executable: NOT FOUND")
            print(f"  Available: NO")
            print(f"  Install from: https://github.com/GameTechDev/PresentMon/releases")

        from app.performance.fps_provider import fps_registry
        providers = fps_registry.detect_available()
        print(f"\nFPS Providers:")
        for p in providers:
            status = "AVAILABLE" if p["available"] else "NOT AVAILABLE"
            print(f"  {p['name']}: {status}")
            print(f"    {p['reason']}")
    except Exception as e:
        print(f"\nFPS Provider:\n  ERROR: {e}")

    # Target process
    try:
        from app.performance.target_process import target_process_detector
        candidates = target_process_detector.get_candidates()
        print(f"\nFPS Target:")
        if candidates:
            best = target_process_detector.select_best_target()
            print(f"  Best: {best.process_name} PID {best.pid}")
            print(f"  Emulator: {best.emulator}")
            print(f"  Reason: {best.reason}")
            print(f"  Confidence: {best.confidence:.0%}")
            print(f"  Candidates: {len(candidates)}")
        else:
            print(f"  No target process found")
            print(f"  Launch emulator to enable FPS measurement")
    except Exception as e:
        print(f"\nFPS Target:\n  ERROR: {e}")

    # Background Processes
    try:
        from app.system.processes import process_monitor
        procs = process_monitor.list_processes()
        cats = {}
        for p in procs:
            cats[p.category] = cats.get(p.category, 0) + 1
        print(f"\nProcesses:\n  Total: {len(procs)}")
        for cat, count in sorted(cats.items()):
            print(f"    {cat}: {count}")
    except Exception as e:
        print(f"\nProcesses:\n  ERROR: {e}")

    # Telemetry
    try:
        from app.core.telemetry import telemetry_engine
        telemetry_engine.start()
        import time
        time.sleep(2)
        frame = telemetry_engine.current
        print(f"\nTelemetry:")
        print(f"  CPU: {frame.cpu_utilization:.1f}%")
        print(f"  GPU: {frame.gpu_utilization:.1f}%")
        print(f"  RAM: {frame.ram_percent:.1f}%")
        print(f"  GPU Temp: {frame.gpu_temp}°C" if frame.gpu_temp else "  GPU Temp: N/A")
        print(f"  GPU Clock: {frame.gpu_clock_mhz:.0f} MHz" if frame.gpu_clock_mhz else "  GPU Clock: N/A")
        print(f"  GPU VRAM: {frame.gpu_memory_used_mb:.0f}/{frame.gpu_memory_total_mb:.0f} MB" if frame.gpu_memory_total_mb > 0 else "  GPU VRAM: N/A")
        telemetry_engine.stop()
    except Exception as e:
        print(f"\nTelemetry:\n  ERROR: {e}")

    # Bottleneck
    try:
        from app.core.telemetry import telemetry_engine
        from app.core.analyzer import bottleneck_analyzer
        telemetry_engine.start()
        import time
        time.sleep(1)
        frame = telemetry_engine.current
        analysis = bottleneck_analyzer.analyze(frame)
        print(f"\nBottleneck:")
        if analysis.primary_bottleneck:
            bn = analysis.primary_bottleneck
            print(f"  Type: {bn.name}")
            print(f"  Confidence: {bn.confidence:.0%}")
            print(f"  {bn.description}")
        telemetry_engine.stop()
    except Exception as e:
        print(f"\nBottleneck:\n  ERROR: {e}")

    print("\n" + "=" * 50)
    print("DIAGNOSTIC COMPLETE")
    print("=" * 50)


def main():
    """Initialize and launch the application."""
    if "--diagnostic" in sys.argv:
        run_diagnostic()
        return 0

    if "--validate" in sys.argv:
        from app.performance.validation import run_validation
        run_validation()
        return 0

    if "--check-prerequisites" in sys.argv:
        from app.performance.prerequisites import PrerequisiteChecker, print_prerequisite_report
        checker = PrerequisiteChecker()
        report = checker.check_all()
        print_prerequisite_report(report)
        return 0 if report.all_passed else 1

    if "--benchmark" in sys.argv:
        duration = 30
        for i, arg in enumerate(sys.argv):
            if arg == "--duration" and i + 1 < len(sys.argv):
                try:
                    duration = int(sys.argv[i + 1])
                except ValueError:
                    pass
        from app.performance.benchmark_cli import run_benchmark_cli
        run_benchmark_cli(duration=duration)
        return 0

    if "--optimize-benchmark" in sys.argv:
        profile_id = "gaming"
        duration = 15
        for i, arg in enumerate(sys.argv):
            if arg == "--profile" and i + 1 < len(sys.argv):
                profile_id = sys.argv[i + 1]
            if arg == "--duration" and i + 1 < len(sys.argv):
                try:
                    duration = int(sys.argv[i + 1])
                except ValueError:
                    pass
        from app.performance.optimize_benchmark import run_optimization_benchmark_cli
        run_optimization_benchmark_cli(profile_id=profile_id, duration=duration)
        return 0

    if "--ab-benchmark" in sys.argv:
        profile_id = "gaming"
        duration = 15
        runs = 3
        for i, arg in enumerate(sys.argv):
            if arg == "--profile" and i + 1 < len(sys.argv):
                profile_id = sys.argv[i + 1]
            if arg == "--duration" and i + 1 < len(sys.argv):
                try:
                    duration = int(sys.argv[i + 1])
                except ValueError:
                    pass
            if arg == "--runs" and i + 1 < len(sys.argv):
                try:
                    runs = int(sys.argv[i + 1])
                except ValueError:
                    pass
        from app.performance.ab_benchmark import run_ab_benchmark_cli
        run_ab_benchmark_cli(profile_id=profile_id, duration=duration, runs=runs)
        return 0

    if "--presentmon-test" in sys.argv:
        from app.performance.presentmon_test import run_presentmon_test
        run_presentmon_test()
        return 0

    if "--cleanup-scan" in sys.argv:
        from app.cleanup.cleanup_scanner import CleanupScanner
        from app.cleanup.cleanup_models import format_bytes, CleanupStatus
        scanner = CleanupScanner()
        items = scanner.scan()

        print("=" * 50)
        print("HEAVEN SOCIETY — CLEANUP SCAN")
        print("=" * 50)

        total_removable = 0
        total_files = 0

        for item in items:
            status_str = item.status.value if item.status else "UNKNOWN"
            print(f"\n  {item.name}")
            print(f"    Category:    {item.category.value}")
            print(f"    Path:        {item.path}")
            print(f"    Detected:    {item.size_display}")
            print(f"    Removable:   {item.removable_display}")
            print(f"    Files:       {item.removable_file_count} / {item.file_count}")
            print(f"    Status:      {status_str}")
            if item.requires_admin:
                print(f"    Admin:       Required")
            if item.reason:
                print(f"    Note:        {item.reason}")
            total_removable += item.removable_size
            total_files += item.removable_file_count

        print(f"\n  Total Removable: {format_bytes(total_removable)}")
        print(f"  Total Files:     {total_files:,}")
        print("\n" + "=" * 50)
        print("SCAN COMPLETE")
        print("=" * 50)
        return 0

    if "--cleanup" in sys.argv:
        print("Cleanup requires user selection.")
        print("Use the GUI CLEANUP tab or --cleanup-scan to view targets.")
        return 0

    if "--emulator-status" in sys.argv:
        from app.core.emulator_controller import emulator_controller
        status = emulator_controller.get_full_status()

        print("=" * 50)
        print("HEAVEN SOCIETY — EMULATOR STATUS")
        print("=" * 50)

        if not status["detected"]:
            print(f"\n  {status['message']}")
            print("\n" + "=" * 50)
            return 0

        target = status["target"]
        print(f"\nTARGET")
        print(f"  {target.name}  PID {target.pid}")
        print(f"  Emulator:    {target.emulator}")
        print(f"  Path:        {target.exe_path}")
        print(f"  Status:      {target.status}")
        print(f"  Confidence:  {target.confidence:.0%}")

        print(f"\nCURRENT STATE")
        print(f"  Priority:    {target.priority_name} ({target.priority})")
        print(f"  Affinity:    {target.affinity_cpus}/{target.total_cpus} CPUs")
        print(f"  CPU:         {target.cpu_percent:.1f}%")
        print(f"  RAM:         {target.memory_mb:.1f} MB ({target.memory_percent:.1f}%)")

        if target.gpu_name:
            print(f"\nGPU")
            print(f"  Adapter:     {target.gpu_name}")
            if target.gpu_engine:
                print(f"  Engine:      {target.gpu_engine}")

        mem = status["memory"]
        print(f"\nMEMORY")
        print(f"  System:      {mem.used_gb:.1f}/{mem.total_gb:.1f} GB ({mem.percent_used:.1f}%)")
        print(f"  Available:   {mem.available_gb:.1f} GB")
        print(f"  Pressure:    {mem.pressure_level}")
        if mem.recommendation:
            print(f"  Note:        {mem.recommendation}")

        gpu_diag = status["gpu"]
        if gpu_diag.gpu_name:
            print(f"\nGPU DIAGNOSTICS")
            print(f"  GPU:         {gpu_diag.gpu_name}")
            print(f"  Vendor:      {gpu_diag.gpu_vendor}")
            print(f"  Type:        {'Discrete' if gpu_diag.is_discrete else 'Integrated' if gpu_diag.is_integrated else 'Unknown'}")
            if gpu_diag.utilization > 0:
                print(f"  Utilization: {gpu_diag.utilization:.1f}%")
            if gpu_diag.temperature:
                print(f"  Temperature: {gpu_diag.temperature:.0f}°C")
            if gpu_diag.clock_mhz > 0:
                print(f"  Clock:       {gpu_diag.clock_mhz:.0f} MHz")
            if gpu_diag.vram_total_mb > 0:
                print(f"  VRAM:        {gpu_diag.vram_used_mb:.0f}/{gpu_diag.vram_total_mb:.0f} MB")
            if gpu_diag.display_refresh_hz > 0:
                print(f"  Display:     {gpu_diag.display_resolution} @ {gpu_diag.display_refresh_hz:.0f} Hz")
            if gpu_diag.gpu_bound is not None:
                bound = "GPU BOUND" if gpu_diag.gpu_bound else "CPU BOUND"
                print(f"  Analysis:    {bound}")

        # Background processes
        bg = status["background"]
        if bg:
            print(f"\nBACKGROUND PROCESSES (optional, >0.5% CPU or >50MB)")
            for p in bg[:8]:
                cat = {"SAFE_TO_RECOMMEND": "SAFE", "USER_APPLICATION": "USER", "SECURITY": "SEC"}.get(p.category, p.category)
                print(f"  [{cat}] {p.name}  CPU: {p.cpu_percent:.1f}%  RAM: {p.memory_mb:.0f}MB  {p.recommendation}")

        print("\n" + "=" * 50)
        print("STATUS COMPLETE")
        print("=" * 50)
        return 0

    if "--emulator-optimize" in sys.argv:
        profile_id = "gaming"
        for i, arg in enumerate(sys.argv):
            if arg == "--profile" and i + 1 < len(sys.argv):
                profile_id = sys.argv[i + 1]

        from app.core.emulator_controller import emulator_controller
        from app.core.optimizer import optimizer

        target = emulator_controller.detect_target()
        if not target:
            print("No emulator detected. Launch BlueStacks/MSI App Player first.")
            return 1

        print(f"\nTARGET: {target.name} PID {target.pid}")
        print(f"PROFILE: {profile_id.upper()}")
        print("\nApplying...")

        report = optimizer.apply_profile(profile_id)

        print(f"\nRESULT")
        print(f"  Applied:       {report.applied_count}")
        print(f"  Already Optimal: {report.already_optimal_count}")
        print(f"  Admin Required:  {report.requires_admin_count}")
        print(f"  Failed:        {report.failed_count}")
        print(f"  Recommendations: {report.recommendation_only_count}")

        for r in report.results:
            icon = {
                "APPLIED": "+", "ALREADY_OPTIMAL": "=",
                "REQUIRES_ADMIN": "!", "RECOMMENDATION_ONLY": "~",
                "FAILED": "x", "NOT_APPLICABLE": "-", "SKIPPED": "?",
            }.get(r.status, "?")
            print(f"  [{icon}] {r.name}: {r.status}  {r.message}")

        return 0

    if "--windows-status" in sys.argv:
        from app.system.windows_gaming import windows_gaming_analyzer
        from app.core.emulator_controller import emulator_controller

        target = emulator_controller.detect_target()
        t_name = target.name if target else ""
        t_pid = target.pid if target else 0

        report = windows_gaming_analyzer.analyze(t_name, t_pid)

        print("=" * 50)
        print("HEAVEN SOCIETY — WINDOWS GAMING STATUS")
        print("=" * 50)

        print(f"\n  Windows:  {report.windows_version}")
        print(f"  Admin:    {'YES' if report.is_admin else 'NO'}")
        if report.target_name:
            print(f"  Target:   {report.target_name} PID {report.target_pid}")

        print(f"\n  {'CONFIGURATION':<25} {'VALUE':<30} {'STATUS'}")
        print(f"  {'-'*25} {'-'*30} {'-'*15}")

        for item in report.items:
            status_icon = {
                "ENABLED": "ENABLED  [OK]",
                "DISABLED": "DISABLED [OK]",
                "AVAILABLE": "AVAILABLE  [-]",
                "NOT_AVAILABLE": "NOT AVAILABLE",
                "REQUIRES_ADMIN": "REQUIRES ADMIN",
                "UNKNOWN": "UNKNOWN",
            }.get(item.status, item.status)
            print(f"  {item.name:<25} {item.value:<30} {status_icon}")

        print(f"\n  RECOMMENDATIONS")
        print(f"  {'-'*40}")
        for rec in report.recommendations:
            print(f"  • {rec}")

        print("\n" + "=" * 50)
        print("DIAGNOSTICS COMPLETE")
        print("=" * 50)
        return 0

    if "--windows-optimize" in sys.argv:
        profile_id = "gaming"
        for i, arg in enumerate(sys.argv):
            if arg == "--profile" and i + 1 < len(sys.argv):
                profile_id = sys.argv[i + 1]

        from app.system.windows_gaming import windows_gaming_analyzer
        from app.core.optimizer import optimizer
        from app.core.emulator_controller import emulator_controller

        target = emulator_controller.detect_target()
        t_name = target.name if target else ""
        t_pid = target.pid if target else 0

        # Run diagnostics first
        report = windows_gaming_analyzer.analyze(t_name, t_pid)
        print(f"\nTARGET: {t_name or 'None'} PID {t_pid or 'N/A'}")
        print(f"PROFILE: {profile_id.upper()}")
        print("\nApplying...")

        opt_report = optimizer.apply_profile(profile_id)

        print(f"\nRESULT")
        print(f"  Applied:         {opt_report.applied_count}")
        print(f"  Already Optimal: {opt_report.already_optimal_count}")
        print(f"  Admin Required:  {opt_report.requires_admin_count}")
        print(f"  Failed:          {opt_report.failed_count}")
        print(f"  Recommendations: {opt_report.recommendation_only_count}")

        for r in opt_report.results:
            icon = {
                "APPLIED": "+", "ALREADY_OPTIMAL": "=",
                "REQUIRES_ADMIN": "!", "RECOMMENDATION_ONLY": "~",
                "FAILED": "x", "NOT_APPLICABLE": "-", "SKIPPED": "?",
            }.get(r.status, "?")
            print(f"  [{icon}] {r.name}: {r.status}  {r.message}")

        return 0

    if "--startup-status" in sys.argv:
        from app.system.startup_analyzer import startup_analyzer, StartupClassification

        analysis = startup_analyzer.analyze(force=True)

        print("=" * 50)
        print("HEAVEN SOCIETY — STARTUP STATUS")
        print("=" * 50)

        print(f"\nSUMMARY")
        print(f"  Total entries:     {analysis.total_entries}")
        print(f"  Enabled:           {analysis.enabled_entries}")
        print(f"  Optional:          {analysis.optional_entries}")
        print(f"  System:            {analysis.system_entries}")
        print(f"  Security:          {analysis.security_entries}")
        print(f"  Emulator:          {analysis.emulator_entries}")
        print(f"  Unknown:           {analysis.unknown_entries}")

        optional_ram = startup_analyzer.get_ram_usage_of_optional()
        if optional_ram > 0:
            print(f"  Optional RAM:      {optional_ram:.0f} MB")

        if analysis.entries:
            print(f"\nSTARTUP ENTRIES")
            print("-" * 50)
            for entry in analysis.entries:
                icon = {
                    StartupClassification.SAFE_TO_RECOMMEND: "[SAFE]",
                    StartupClassification.USER_APPLICATION: "[USER]",
                    StartupClassification.SECURITY: "[SEC]",
                    StartupClassification.SYSTEM: "[SYS]",
                    StartupClassification.EMULATOR: "[EMU]",
                }.get(entry.classification, "[??]")
                running = " (RUNNING)" if entry.is_running else ""
                disable = " [CAN DISABLE]" if entry.can_safely_disable else ""
                print(f"  {icon} {entry.name}{running}{disable}")
                print(f"       Source: {entry.source}")
                if entry.executable_path:
                    print(f"       Path:   {entry.executable_path[:60]}")
                print(f"       {entry.reason}")

        if analysis.optional_names:
            print(f"\nOPTIONAL (safe to recommend disabling)")
            print("-" * 50)
            for name in analysis.optional_names:
                print(f"  {name}")
        else:
            print(f"\nOPTIONAL")
            print(f"  No optional startup entries detected.")

        print(f"\nNOTE: Startup analysis is READ-ONLY.")
        print(f"      No entries were modified.")
        print(f"      Disable entries manually via Task Manager > Startup tab.")

        print("\n" + "=" * 50)
        print("STARTUP STATUS COMPLETE")
        print("=" * 50)
        return 0

    if "--resource-status" in sys.argv:
        from app.core.resource_analyzer import resource_analyzer
        from app.core.emulator_controller import emulator_controller
        from app.core.telemetry import telemetry_engine

        target = emulator_controller.detect_target()
        t_pid = target.pid if target else 0
        t_name = target.name if target else ""

        print("=" * 50)
        print("HEAVEN SOCIETY — RESOURCE STATUS")
        print("=" * 50)

        # RAM
        try:
            import psutil
            vm = psutil.virtual_memory()
            print(f"\nRAM")
            print(f"  Total:       {vm.total / (1024**3):.1f} GB")
            print(f"  Used:        {vm.used / (1024**3):.1f} GB ({vm.percent:.0f}%)")
            print(f"  Available:   {vm.available / (1024**3):.1f} GB")
        except Exception:
            print(f"\nRAM")
            print(f"  Not available")

        # CPU
        try:
            cpu_pct = psutil.cpu_percent(interval=0.5)
            cpu_count = psutil.cpu_count()
            print(f"\nCPU")
            print(f"  Utilization: {cpu_pct:.0f}%")
            print(f"  Cores:       {cpu_count}")
        except Exception:
            print(f"\nCPU")
            print(f"  Not available")

        # GPU
        try:
            from app.system.gpu import gpu_monitor
            gpu = gpu_monitor.detect()
            if gpu:
                g = gpu_monitor.update_nvidia(gpu[0]) if gpu[0].vendor == "NVIDIA" else gpu[0]
                print(f"\nGPU")
                print(f"  Model:       {g.name}")
                print(f"  Utilization: {g.utilization_gpu:.0f}%")
                print(f"  VRAM:        {g.vram_used_mb:.0f}/{g.vram_total_mb:.0f} MB")
                if g.temperature_c:
                    print(f"  Temperature: {g.temperature_c:.0f} C")
        except Exception:
            print(f"\nGPU")
            print(f"  Not available")

        # Emulator
        if t_name:
            try:
                proc = psutil.Process(t_pid)
                print(f"\nEMULATOR")
                print(f"  Process:     {t_name} PID {t_pid}")
                print(f"  CPU:         {proc.cpu_percent(interval=0.1):.0f}%")
                mem = proc.memory_info()
                print(f"  RAM:         {mem.rss / (1024*1024):.0f} MB")
                print(f"  Threads:     {proc.num_threads()}")
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                print(f"\nEMULATOR")
                print(f"  {t_name} PID {t_pid} — not accessible")
        else:
            print(f"\nEMULATOR")
            print(f"  No emulator detected")

        # Top memory consumers
        try:
            procs = []
            for p in psutil.process_iter(["name", "memory_info", "memory_percent"]):
                try:
                    info = p.info
                    mem = info.get("memory_info")
                    if mem:
                        procs.append((
                            info.get("name", "?"),
                            mem.rss / (1024 * 1024),
                            info.get("memory_percent", 0),
                        ))
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            procs.sort(key=lambda x: x[1], reverse=True)
            if procs:
                print(f"\nTOP MEMORY")
                for name, mb, pct in procs[:8]:
                    print(f"  {name:<25} {mb:>8.0f} MB  ({pct:.1f}%)")
        except Exception:
            pass

        print("\n" + "=" * 50)
        print("RESOURCE STATUS COMPLETE")
        print("=" * 50)
        return 0

    if "--game-session-status" in sys.argv:
        from app.system.game_session_monitor import game_session_monitor
        from app.core.emulator_controller import emulator_controller
        from app.system.memory_optimizer import memory_optimizer

        target = emulator_controller.detect_target()
        t_name = target.name if target else ""
        t_pid = target.pid if target else 0

        # Get memory pressure
        mem_diag = memory_optimizer.diagnose()
        mem_pressure = mem_diag.pressure_level if mem_diag else "UNKNOWN"

        # Capture snapshot
        report = game_session_monitor.create_report(
            target_name=t_name,
            target_pid=t_pid,
            memory_pressure=mem_pressure,
        )

        snap = report.before
        if not snap:
            print("Failed to capture snapshot")
            return 1

        print("=" * 50)
        print("HEAVEN SOCIETY — GAME SESSION STATUS")
        print("=" * 50)

        # Target
        print(f"\nTARGET")
        if t_name:
            print(f"  Process:     {t_name} PID {t_pid}")
        else:
            print(f"  No emulator detected")

        # System
        print(f"\nSYSTEM")
        print(f"  CPU:         {snap.cpu_percent:.0f}%")
        print(f"  RAM:         {snap.ram_used_gb:.1f}/{snap.ram_total_gb:.1f} GB ({snap.ram_percent:.0f}%)")
        print(f"  Available:   {snap.ram_available_gb:.1f} GB")
        if snap.gpu_utilization is not None:
            print(f"  GPU:         {snap.gpu_utilization:.0f}%")
        if snap.gpu_vram_used_mb is not None:
            print(f"  VRAM:        {snap.gpu_vram_used_mb:.0f}/{snap.gpu_vram_total_mb:.0f} MB")
        if snap.gpu_temperature is not None:
            print(f"  GPU Temp:    {snap.gpu_temperature:.0f} C")
        print(f"  Pressure:    {mem_pressure}")

        # Emulator
        if snap.emulator_name:
            print(f"\nEMULATOR")
            print(f"  Process:     {snap.emulator_name} PID {snap.emulator_pid}")
            print(f"  CPU:         {snap.emulator_cpu_percent:.0f}%")
            print(f"  RAM:         {snap.emulator_rss_mb:.0f} MB")
            print(f"  Threads:     {snap.emulator_threads}")

        # FPS
        if snap.present_fps is not None:
            print(f"\nFPS")
            print(f"  Present:     {snap.present_fps:.1f}")
            if snap.fps_1_low is not None:
                print(f"  1% Low:      {snap.fps_1_low:.1f}")
            if snap.frame_time_ms is not None:
                print(f"  Frame Time:  {snap.frame_time_ms:.2f} ms")
            if snap.stability is not None:
                print(f"  Stability:   {snap.stability:.1f}/100")
        else:
            print(f"\nFPS")
            print(f"  Not available (PresentMon not running)")

        # Bottleneck
        print(f"\nBOTTLENECK")
        print(f"  Type:        {report.bottleneck.value}")
        print(f"  Confidence:  {report.bottleneck_confidence:.0f}%")
        print(f"  Reason:      {report.bottleneck_reason}")

        # Recommendations
        if report.recommendations:
            print(f"\nRECOMMENDATIONS")
            for i, rec in enumerate(report.recommendations, 1):
                print(f"  {i}. [{rec.priority}] {rec.title}")
                print(f"     {rec.description}")
                print(f"     Evidence: {rec.measured_evidence}")

        print("\n" + "=" * 50)
        print("GAME SESSION STATUS COMPLETE")
        print("=" * 50)
        return 0

    if "--memory-status" in sys.argv:
        from app.system.memory_optimizer import memory_optimizer, ProcessCategory
        from app.core.emulator_controller import emulator_controller

        target = emulator_controller.detect_target()
        t_pid = target.pid if target else 0
        t_name = target.name if target else ""

        report = memory_optimizer.analyze(
            emulator_pid=t_pid,
            emulator_name=t_name,
        )

        print("=" * 50)
        print("HEAVEN SOCIETY — MEMORY STATUS")
        print("=" * 50)

        # System RAM
        if report.diagnostics:
            d = report.diagnostics
            print(f"\nSYSTEM RAM")
            print(f"  Total:       {d.total_gb:.1f} GB")
            print(f"  Used:        {d.used_gb:.1f} GB ({d.percent_used:.0f}%)")
            print(f"  Available:   {d.available_gb:.1f} GB")
            print(f"  Cached:      {d.cached_gb:.1f} GB")
            print(f"  Swap:        {d.swap_used_gb:.1f}/{d.swap_total_gb:.1f} GB ({d.swap_percent:.0f}%)")
            print(f"  Pressure:    {d.pressure_level}")
            if d.pressure_recommendation:
                print(f"  Note:        {d.pressure_recommendation}")

        # Emulator
        if report.emulator:
            e = report.emulator
            print(f"\nEMULATOR MEMORY")
            print(f"  Process:     {e.process_name} PID {e.pid}")
            print(f"  RSS:         {e.rss_mb:.0f} MB")
            print(f"  VMS:         {e.vms_mb:.0f} MB")
            if e.private_mb > 0:
                print(f"  Private:     {e.private_mb:.0f} MB")
            print(f"  % of RAM:    {e.emulator_pct_of_system:.1f}%")
            print(f"  High usage:  {'YES' if e.is_high_usage else 'NO'}")
            if e.child_count > 0:
                print(f"  Children:    {e.child_count} ({e.children_total_rss_mb:.0f} MB total)")
            if e.anomaly_detected:
                print(f"  ANOMALY:     {e.anomaly_reason}")
        else:
            print(f"\nEMULATOR MEMORY")
            print(f"  No emulator detected")

        # Standby
        if report.standby and report.standby.status == "DETECTED":
            print(f"\nSTANDBY MEMORY")
            print(f"  Status:      {report.standby.status}")
            print(f"  Modify:      {'Yes' if report.standby.can_modify else 'No (RECOMMENDATION ONLY)'}")
            if report.standby.recommendation:
                print(f"  Note:        {report.standby.recommendation}")

        # Top processes
        if report.processes:
            print(f"\nTOP MEMORY PROCESSES")
            for p in report.processes[:8]:
                cat = {
                    ProcessCategory.SAFE_TO_RECOMMEND: "SAFE",
                    ProcessCategory.USER_APPLICATION: "USER",
                    ProcessCategory.SECURITY: "SEC",
                    ProcessCategory.SYSTEM: "SYS",
                    ProcessCategory.EMULATOR: "EMU",
                }.get(p.category, "?")
                print(f"  [{cat}] {p.name:<25} {p.rss_mb:>8.0f} MB  {p.recommendation}")

        # Recommendations
        if report.recommendations:
            print(f"\nRECOMMENDATIONS")
            for i, rec in enumerate(report.recommendations, 1):
                print(f"  {i}. [{rec['priority']}] {rec['title']}")
                print(f"     {rec['description']}")
                print(f"     Why: {rec['reason']}")
        else:
            print(f"\nRECOMMENDATIONS")
            print(f"  No recommendations. Memory usage is healthy.")

        # Actions NOT performed
        if report.actions_not_performed:
            print(f"\nACTIONS NOT PERFORMED")
            for action in report.actions_not_performed:
                print(f"  - {action['action']}")
                print(f"    Why: {action['reason']}")

        print("\n" + "=" * 50)
        print("MEMORY STATUS COMPLETE")
        print("=" * 50)
        return 0

    if "--memory-analyze" in sys.argv:
        from app.system.memory_optimizer import memory_optimizer, ProcessCategory
        from app.core.emulator_controller import emulator_controller

        target = emulator_controller.detect_target()
        t_pid = target.pid if target else 0
        t_name = target.name if target else ""

        print("=" * 50)
        print("HEAVEN SOCIETY — MEMORY ANALYSIS")
        print("=" * 50)

        # Take before snapshot
        before = memory_optimizer.measure_snapshot()

        report = memory_optimizer.analyze(
            emulator_pid=t_pid,
            emulator_name=t_name,
        )

        # System RAM
        if report.diagnostics:
            d = report.diagnostics
            print(f"\nMEMORY STATUS")
            print(f"  Total:       {d.total_gb:.1f} GB")
            print(f"  Used:        {d.used_gb:.1f} GB ({d.percent_used:.0f}%)")
            print(f"  Available:   {d.available_gb:.1f} GB")
            print(f"  Pressure:    {d.pressure_level}")
            if d.pressure_recommendation:
                print(f"  Note:        {d.pressure_recommendation}")

        # Emulator memory
        if report.emulator:
            e = report.emulator
            print(f"\nEMULATOR MEMORY")
            print(f"  Process:     {e.process_name} PID {e.pid}")
            print(f"  RSS:         {e.rss_mb:.0f} MB")
            print(f"  % of RAM:    {e.emulator_pct_of_system:.1f}%")
            if e.anomaly_detected:
                print(f"  ANOMALY:     {e.anomaly_reason}")
        else:
            print(f"\nEMULATOR MEMORY")
            print(f"  No emulator detected")

        # Top memory users
        if report.processes:
            print(f"\nTOP MEMORY USERS")
            for p in report.processes[:10]:
                cat = {
                    ProcessCategory.SAFE_TO_RECOMMEND: "SAFE",
                    ProcessCategory.USER_APPLICATION: "USER",
                    ProcessCategory.SECURITY: "SEC",
                    ProcessCategory.SYSTEM: "SYS",
                    ProcessCategory.EMULATOR: "EMU",
                }.get(p.category, "?")
                closeable = "[CLOSE]" if p.can_safely_close else ""
                print(f"  [{cat}] {p.name:<25} {p.rss_mb:>8.0f} MB  {closeable}")

        # Safe to close
        safe = memory_optimizer.get_safe_closeable_processes(emulator_pid=t_pid)
        if safe:
            total_mb = sum(p["rss_mb"] for p in safe)
            print(f"\nSAFE TO CLOSE (estimated {total_mb:.0f} MB reclaimable)")
            for p in safe:
                print(f"  {p['name']:<25} PID {p['pid']:<8} {p['rss_mb']:.0f} MB  {p['reason']}")
        else:
            print(f"\nSAFE TO CLOSE")
            print(f"  No safe-to-close background processes detected.")

        # Recommendations
        if report.recommendations:
            print(f"\nRECOMMENDATIONS")
            for i, rec in enumerate(report.recommendations, 1):
                print(f"  {i}. [{rec['priority']}] {rec['title']}")
                print(f"     {rec['reason']}")

        print("\n" + "=" * 50)
        print("MEMORY ANALYSIS COMPLETE")
        print("=" * 50)
        return 0

    if "--memory-clean" in sys.argv:
        from app.system.memory_optimizer import memory_optimizer
        from app.core.emulator_controller import emulator_controller

        # Parse target PIDs from args
        pids = []
        for i, arg in enumerate(sys.argv):
            if arg == "--pid" and i + 1 < len(sys.argv):
                try:
                    pids.append(int(sys.argv[i + 1]))
                except ValueError:
                    pass

        if not pids:
            print("Usage: python main.py --memory-clean --pid <PID> [--pid <PID> ...]")
            print("")
            print("Safe to close processes are listed by --memory-analyze.")
            print("")
            print("WARNING: This operation is NON-ROLLBACKABLE.")
            print("Terminated processes cannot be restored.")
            return 1

        print("=" * 50)
        print("HEAVEN SOCIETY — MEMORY CLEANUP")
        print("=" * 50)
        print(f"\nTarget PIDs: {pids}")
        print(f"WARNING: Process termination is NON-ROLLBACKABLE.")
        print(f"")

        # Take before snapshot
        before = memory_optimizer.measure_snapshot()
        print(f"BEFORE")
        print(f"  Available RAM: {before['available_gb']:.1f} GB")
        print(f"  Used RAM:      {before['used_gb']:.1f} GB ({before['percent_used']:.0f}%)")
        print(f"  Pressure:      {before['pressure_level']}")

        # Execute closure
        results = memory_optimizer.close_selected_processes(pids=pids)

        # Take after snapshot
        after = memory_optimizer.measure_snapshot()
        print(f"\nAFTER")
        print(f"  Available RAM: {after['available_gb']:.1f} GB")
        print(f"  Used RAM:      {after['used_gb']:.1f} GB ({after['percent_used']:.0f}%)")
        print(f"  Pressure:      {after['pressure_level']}")

        # Results
        succeeded = sum(1 for r in results if r["success"])
        failed = sum(1 for r in results if not r["success"])
        print(f"\nRESULTS")
        print(f"  Succeeded: {succeeded}")
        print(f"  Failed:    {failed}")
        for r in results:
            icon = "OK" if r["success"] else "XX"
            print(f"  [{icon}] PID {r['pid']} {r['process_name']} {r['rss_mb']:.0f}MB")
            if r["error"]:
                print(f"       Error: {r['error']}")

        comparison = memory_optimizer.compare_snapshots(before, after)
        delta = comparison.get("delta", {})
        ram_delta = delta.get("available_gb", 0)
        print(f"\nRAM CHANGE")
        print(f"  Available: {ram_delta:+.2f} GB")

        print("\n" + "=" * 50)
        print("MEMORY CLEANUP COMPLETE")
        print("=" * 50)
        return 0

    if "--resource-status" in sys.argv:
        from app.core.resource_analyzer import resource_analyzer
        from app.core.emulator_controller import emulator_controller
        from app.core.telemetry import telemetry_engine

        target = emulator_controller.detect_target()
        t_pid = target.pid if target else 0
        t_name = target.name if target else ""

        # Get telemetry
        telemetry_engine.start()
        import time
        time.sleep(1)
        frame = telemetry_engine.current

        # Get GPU info
        gpu_info = {}
        try:
            from app.system.gpu import gpu_monitor
            gpus = gpu_monitor.detect()
            if gpus and gpus[0].vendor == "NVIDIA":
                gpu = gpu_monitor.update_nvidia(gpus[0])
                gpu_info = {
                    "vram_total_mb": gpu.vram_total_mb,
                    "vram_used_mb": gpu.vram_used_mb,
                    "utilization": gpu.utilization_gpu,
                    "temperature": gpu.temperature_celsius,
                }
        except Exception:
            pass

        status = resource_analyzer.analyze(
            emulator_pid=t_pid,
            emulator_name=t_name,
            telemetry_frame=frame,
            gpu_info=gpu_info,
        )

        print("=" * 50)
        print("HEAVEN SOCIETY — RESOURCE STATUS")
        print("=" * 50)

        # RAM
        if status.ram:
            r = status.ram
            print(f"\nRAM")
            print(f"  Total:       {r.total_gb:.1f} GB")
            print(f"  Used:        {r.used_gb:.1f} GB ({r.percent_used:.0f}%)")
            print(f"  Available:   {r.available_gb:.1f} GB")
            print(f"  Swap:        {r.swap_used_gb:.1f}/{r.swap_total_gb:.1f} GB ({r.swap_percent:.0f}%)")
            print(f"  Pressure:    {r.pressure_level}")

        # Emulator
        if status.emulator:
            e = status.emulator
            print(f"\nEMULATOR")
            print(f"  Process:     {e.name} PID {e.pid}")
            print(f"  CPU:         {e.cpu_percent:.1f}%")
            print(f"  RAM:         {e.rss_mb:.0f} MB ({e.memory_percent:.1f}%)")
            print(f"  Threads:     {e.num_threads}")
            if e.num_handles > 0:
                print(f"  Handles:     {e.num_handles}")
            print(f"  Priority:    {e.priority_name}")
            print(f"  Affinity:    {e.affinity_cpus}/{e.total_cpus} CPUs")
            print(f"  Uptime:      {e.uptime_hours:.1f}h")
            if e.child_count > 0:
                print(f"  Children:    {e.child_count}")
        else:
            print(f"\nEMULATOR")
            print(f"  No emulator detected")

        # GPU
        if gpu_info:
            print(f"\nGPU")
            print(f"  Utilization: {gpu_info.get('utilization', 0):.1f}%")
            print(f"  VRAM:        {gpu_info.get('vram_used_mb', 0):.0f}/{gpu_info.get('vram_total_mb', 0):.0f} MB")
            if gpu_info.get("temperature"):
                print(f"  Temperature: {gpu_info['temperature']:.0f} C")

        # Bottleneck
        if status.bottleneck:
            b = status.bottleneck
            print(f"\nBOTTLENECK")
            print(f"  Classification: {b.classification}")
            print(f"  Confidence:     {b.confidence:.0%}")
            print(f"  {b.description}")

        # Recommendations
        if status.recommendations:
            print(f"\nRECOMMENDATIONS")
            for rec in status.recommendations:
                print(f"  [{rec.priority}] {rec.title}")
                print(f"    {rec.description}")
                print(f"    Why: {rec.reason}")

        print("\n" + "=" * 50)
        print("RESOURCE STATUS COMPLETE")
        print("=" * 50)

        telemetry_engine.stop()
        return 0

    if "--resource-recommendations" in sys.argv:
        from app.core.resource_analyzer import resource_analyzer
        from app.core.emulator_controller import emulator_controller
        from app.core.telemetry import telemetry_engine

        target = emulator_controller.detect_target()
        t_pid = target.pid if target else 0
        t_name = target.name if target else ""

        telemetry_engine.start()
        import time
        time.sleep(1)
        frame = telemetry_engine.current

        status = resource_analyzer.analyze(
            emulator_pid=t_pid,
            emulator_name=t_name,
            telemetry_frame=frame,
        )

        print("=" * 50)
        print("HEAVEN SOCIETY — RESOURCE RECOMMENDATIONS")
        print("=" * 50)

        if not status.recommendations:
            print("\n  No recommendations. System is well-optimized.")
        else:
            for i, rec in enumerate(status.recommendations, 1):
                print(f"\n  {i}. [{rec.priority}] {rec.title}")
                print(f"     Category:  {rec.category}")
                print(f"     Detail:    {rec.description}")
                print(f"     Why:       {rec.reason}")
                print(f"     Impact:    {rec.estimated_impact}")
                print(f"     Auto-apply: {'Yes' if rec.can_auto_apply else 'No'}")

        print("\n" + "=" * 50)
        print("RECOMMENDATIONS COMPLETE")
        print("=" * 50)

        telemetry_engine.stop()
        return 0

    if "--background-status" in sys.argv:
        from app.system.background_analyzer import background_analyzer, CompetitionLevel
        from app.core.emulator_controller import emulator_controller

        target = emulator_controller.detect_target()
        t_pid = target.pid if target else 0
        t_name = target.name if target else ""

        result = background_analyzer.analyze(
            emulator_pid=t_pid,
            emulator_name=t_name,
            force=True,
        )

        print("=" * 50)
        print("HEAVEN SOCIETY — BACKGROUND LOAD STATUS")
        print("=" * 50)

        if t_name:
            print(f"\nTARGET")
            print(f"  {t_name}  PID {t_pid}")
        else:
            print(f"\nTARGET")
            print(f"  No emulator detected")

        print(f"\nPROCESSES")
        print(f"  Total:       {result.total_count}")
        print(f"  Significant: {result.significant_count}")

        # CPU Competition
        if result.cpu_competition:
            c = result.cpu_competition
            print(f"\nCPU COMPETITION")
            print(f"  Level:       {c.level.value}")
            print(f"  Outside CPU: {c.total_competition_cpu:.1f}%")
            if c.cpu_competing_processes:
                print(f"  Competing:")
                for p in c.cpu_competing_processes[:5]:
                    print(f"    {p.name:<30} CPU: {p.cpu_percent:>5.1f}%  RAM: {p.ram_mb:>6.0f}MB  [{p.category.value}]")

        # RAM Competition
        if result.ram_competition:
            c = result.ram_competition
            print(f"\nRAM COMPETITION")
            print(f"  Level:       {c.level.value}")
            print(f"  Outside RAM: {c.total_competition_ram_mb / 1024:.1f} GB")
            if c.ram_competing_processes:
                print(f"  Competing:")
                for p in c.ram_competing_processes[:5]:
                    print(f"    {p.name:<30} RAM: {p.ram_mb:>6.0f}MB  CPU: {p.cpu_percent:>5.1f}%  [{p.category.value}]")

        # Disk Competition
        if result.disk_competition:
            c = result.disk_competition
            print(f"\nDISK COMPETITION")
            print(f"  Level:       {c.level.value}")
            if c.disk_competing_processes:
                print(f"  Competing:")
                for p in c.disk_competing_processes[:5]:
                    total_io = p.io_read_mb + p.io_write_mb
                    print(f"    {p.name:<30} I/O: {total_io:>6.0f}MB  [{p.category.value}]")

        # Safe-to-recommend candidates
        if result.safe_candidates:
            print(f"\nSAFE TO CLOSE")
            print(f"  Found {len(result.safe_candidates)} optional process(es):")
            for p in result.safe_candidates[:8]:
                print(f"    {p.name:<30} CPU: {p.cpu_percent:>5.1f}%  RAM: {p.ram_mb:>6.0f}MB  Score: {p.gaming_impact_score:.0f}")
        else:
            print(f"\nSAFE TO CLOSE")
            print(f"  No safe-to-close candidates found")

        # Overall
        print(f"\nOVERALL")
        print(f"  Impact:      {result.overall_impact_level.value}")
        print(f"  {result.overall_description}")

        print("\n" + "=" * 50)
        print("BACKGROUND STATUS COMPLETE")
        print("=" * 50)
        return 0

    if "--disk-status" in sys.argv:
        from app.system.disk_analyzer import disk_analyzer, StoragePressure
        from app.cleanup.cleanup_models import format_bytes

        diag = disk_analyzer.diagnose(force=True)

        print("=" * 50)
        print("HEAVEN SOCIETY — DISK STATUS")
        print("=" * 50)

        if diag.system_drive:
            d = diag.system_drive
            print(f"\nSYSTEM DRIVE")
            print(f"  Device:      {d.device}")
            print(f"  Mount:       {d.mountpoint}")
            print(f"  Filesystem:  {d.filesystem}")
            print(f"  Total:       {format_bytes(d.total_bytes)}")
            print(f"  Used:        {format_bytes(d.used_bytes)} ({d.percent_used:.0f}%)")
            print(f"  Free:        {format_bytes(d.free_bytes)}")
            print(f"  Type:        {d.disk_type}")
        else:
            print(f"\nSYSTEM DRIVE")
            print(f"  Not detected")

        print(f"\nSTORAGE PRESSURE")
        print(f"  Level:       {diag.pressure_level.value}")
        print(f"  {diag.pressure_description}")

        if diag.reclaimable_targets:
            print(f"\nRECLAIMABLE STORAGE")
            for t in diag.reclaimable_targets:
                print(f"  {t.name:<25} {format_bytes(t.estimated_bytes):>10}  [{t.status}]")
            print(f"\n  Total:       {format_bytes(diag.total_reclaimable_bytes)}")
            print(f"  Auto-safe:   {format_bytes(diag.total_reclaimable_safe)}")
        else:
            print(f"\nRECLAIMABLE STORAGE")
            print(f"  No targets detected")

        print("\n" + "=" * 50)
        print("DISK STATUS COMPLETE")
        print("=" * 50)
        return 0

    if "--disk-scan" in sys.argv:
        from app.cleanup.cleanup_scanner import CleanupScanner
        from app.cleanup.cleanup_models import format_bytes, CleanupStatus
        from app.system.disk_analyzer import disk_analyzer

        print("=" * 50)
        print("HEAVEN SOCIETY — DISK SCAN")
        print("=" * 50)

        # Disk diagnostics
        diag = disk_analyzer.diagnose(force=True)
        if diag.system_drive:
            d = diag.system_drive
            print(f"\nDISK STATUS")
            print(f"  {d.mountpoint}  {format_bytes(d.free_bytes)} free / {format_bytes(d.total_bytes)} total ({d.percent_used:.0f}% used)  {d.disk_type}")
            print(f"  Pressure: {diag.pressure_level.value}")

        # Detailed scan
        print(f"\nCLEANUP TARGETS")
        print("-" * 50)

        scanner = CleanupScanner()
        items = scanner.scan()

        total_reclaimable = 0
        for item in items:
            status_icon = {
                CleanupStatus.AVAILABLE: "[AVAILABLE]",
                CleanupStatus.RECOMMENDATION_ONLY: "[RECOMMEND]",
                CleanupStatus.REQUIRES_ADMIN: "[ADMIN]",
                CleanupStatus.NOT_AVAILABLE: "[N/A]",
            }.get(item.status, "[??]")

            print(f"\n  {item.name}")
            print(f"    Files:       {item.file_count}")
            print(f"    Size:        {item.size_display}")
            print(f"    Removable:   {item.removable_display}")
            print(f"    Status:      {status_icon} {item.status.value}")
            print(f"    Path:        {item.path[:60]}")
            if item.skipped_file_count > 0:
                print(f"    Locked:      {item.skipped_file_count} files")
            if item.reason:
                print(f"    Note:        {item.reason}")

            if item.status == CleanupStatus.AVAILABLE:
                total_reclaimable += item.removable_size

        # Reclaimable from disk analyzer
        reclaimable_targets = diag.reclaimable_targets
        if reclaimable_targets:
            print(f"\nADDITIONAL RECLAIMABLE")
            print("-" * 50)
            for t in reclaimable_targets:
                print(f"  {t.name:<25} {format_bytes(t.estimated_bytes):>10}  [{t.status}]")
            total_reclaimable += sum(t.estimated_bytes for t in reclaimable_targets
                                     if t.status in ("SAFE", "DETECTED"))

        print(f"\nTOTAL ESTIMATED RECLAIMABLE: {format_bytes(total_reclaimable)}")
        print(f"\nNote: Shader cache and browser cache are RECOMMENDATION ONLY.")
        print(f"      Recycle Bin requires explicit user confirmation.")
        print(f"      Only User Temp is safe for automatic cleanup.")

        print("\n" + "=" * 50)
        print("DISK SCAN COMPLETE")
        print("=" * 50)
        return 0

    if "--disk-clean" in sys.argv:
        from app.cleanup.cleanup_scanner import CleanupScanner
        from app.cleanup.cleanup_engine import CleanupEngine
        from app.cleanup.cleanup_models import format_bytes, CleanupStatus
        from app.system.disk_analyzer import disk_analyzer

        # Parse target selection
        targets = []
        for i, arg in enumerate(sys.argv):
            if arg == "--target" and i + 1 < len(sys.argv):
                targets.append(sys.argv[i + 1])

        if not targets:
            print("Usage: python main.py --disk-clean --target <target_id> [--target <target_id> ...]")
            print("")
            print("Available targets (from --disk-scan):")
            print("  user_temp         User TEMP directory")
            print("  system_temp       System TEMP directory (requires admin)")
            print("")
            print("WARNING: Only safe targets are cleaned.")
            print("         Shader cache and browser cache are not cleaned automatically.")
            print("         Recycle Bin requires explicit confirmation.")
            return 1

        print("=" * 50)
        print("HEAVEN SOCIETY — DISK CLEANUP")
        print("=" * 50)
        print(f"\nTargets: {', '.join(targets)}")

        # Scan first
        scanner = CleanupScanner()
        items = scanner.scan()

        # Measure before
        before_state = disk_analyzer.measure_disk_state()
        print(f"\nBEFORE")
        if before_state.get("free_bytes"):
            print(f"  Free: {format_bytes(before_state['free_bytes'])}")
            print(f"  Used: {format_bytes(before_state['used_bytes'])} ({before_state['percent_used']:.0f}%)")

        # Filter to requested targets
        target_map = {item.id: item for item in items}
        selected = []
        for t in targets:
            if t in target_map:
                item = target_map[t]
                if item.status == CleanupStatus.AVAILABLE and item.can_delete:
                    item.selected = True
                    selected.append(item)
                    print(f"  Selected: {item.name} ({item.removable_display})")
                elif item.status == CleanupStatus.REQUIRES_ADMIN:
                    print(f"  Skipped: {item.name} — requires admin")
                elif item.status == CleanupStatus.RECOMMENDATION_ONLY:
                    print(f"  Skipped: {item.name} — recommendation only")
                else:
                    print(f"  Skipped: {item.name} — {item.status.value}")
            else:
                print(f"  Unknown target: {t}")

        if not selected:
            print("\nNo valid targets selected for cleanup.")
            print("=" * 50)
            return 0

        # Execute cleanup
        print(f"\nCleaning {len(selected)} target(s)...")
        engine = CleanupEngine()
        session = engine.clean(selected)

        # Measure after
        after_state = disk_analyzer.measure_disk_state()
        comparison = disk_analyzer.compare_disk_states(before_state, after_state)
        delta = comparison.get("delta", {})

        print(f"\nAFTER")
        if after_state.get("free_bytes"):
            print(f"  Free: {format_bytes(after_state['free_bytes'])}")
            print(f"  Used: {format_bytes(after_state['used_bytes'])} ({after_state['percent_used']:.0f}%)")

        # Results
        print(f"\nRESULTS")
        print(f"  Session:     {session.session_id}")
        print(f"  Selected:    {session.selected_items}")
        print(f"  Successful:  {session.successful_items}")
        print(f"  Failed:      {session.failed_items}")
        print(f"  Files deleted: {session.files_deleted}")
        print(f"  Bytes freed: {session.bytes_freed_display}")
        print(f"  Verification: {session.verification_passed} passed, {session.verification_failed} failed")

        if delta.get("free_bytes"):
            freed = delta["free_bytes"]
            print(f"\nDISK CHANGE")
            print(f"  Free space:  {freed:+d} bytes ({format_bytes(abs(freed))})")

        print("\n" + "=" * 50)
        print("DISK CLEANUP COMPLETE")
        print("=" * 50)
        return 0

    if "--shader-status" in sys.argv:
        from app.system.shader_cache import shader_cache_manager

        diag = shader_cache_manager.diagnose(force=True)

        print("=" * 50)
        print("HEAVEN SOCIETY — SHADER CACHE STATUS")
        print("=" * 50)

        from app.system.shader_cache import _format_bytes
        if diag.detected_count == 0:
            print(f"\n  No shader caches detected.")
        else:
            print(f"\n  Detected: {diag.detected_count} cache(es)")
            print(f"  Total:    {_format_bytes(diag.total_size_bytes)}")
            print(f"  Files:    {diag.total_files:,}")

            for info in diag.caches:
                if not info.exists:
                    continue
                print(f"\n  {info.name}")
                print(f"    Path:         {info.path}")
                print(f"    Status:       {info.status.value}")
                print(f"    Files:        {info.file_count:,}")
                print(f"    Size:         {info.total_size_display}")
                print(f"    Oldest:       {info.oldest_file_display}")
                print(f"    Newest:       {info.newest_file_display}")
                print(f"    Last Modified: {info.last_modified_display}")
                print(f"    Cleanup:      RECOMMENDATION ONLY")
                if info.recompilation_warning:
                    print(f"    Warning:      {info.recompilation_warning[:120]}")

        print(f"\n  {diag.recommendation}")

        print("\n" + "=" * 50)
        print("SHADER STATUS COMPLETE")
        print("=" * 50)
        return 0

    if "--shader-cleanup" in sys.argv:
        from app.system.shader_cache import shader_cache_manager, ShaderCacheType

        # Parse which cache to clean (default: all detected)
        target = "all"
        for i, arg in enumerate(sys.argv):
            if arg == "--cache" and i + 1 < len(sys.argv):
                target = sys.argv[i + 1].lower()

        print("=" * 50)
        print("HEAVEN SOCIETY — SHADER CACHE CLEANUP")
        print("=" * 50)

        diag = shader_cache_manager.diagnose(force=True)

        cache_map = {
            "nvidia_dx": ShaderCacheType.NVIDIA_DX,
            "nvidia_dxcache": ShaderCacheType.NVIDIA_DX,
            "nvidia_gl": ShaderCacheType.NVIDIA_GL,
            "nvidia_glcache": ShaderCacheType.NVIDIA_GL,
            "amd_dx": ShaderCacheType.AMD_DX,
            "amd_dxcache": ShaderCacheType.AMD_DX,
            "directx": ShaderCacheType.DIRECTX_PIPELINE,
            "d3d": ShaderCacheType.DIRECTX_PIPELINE,
        }

        targets_to_clean = []
        if target == "all":
            targets_to_clean = [c.cache_type for c in diag.caches if c.exists and c.file_count > 0]
        elif target in cache_map:
            ct = cache_map[target]
            matching = [c for c in diag.caches if c.cache_type == ct and c.exists]
            if matching:
                targets_to_clean = [ct]
            else:
                print(f"\n  Cache not found: {target}")
                print("=" * 50)
                return 1
        else:
            print(f"\n  Unknown cache: {target}")
            print(f"  Available: nvidia_dx, nvidia_gl, amd_dx, directx, all")
            print("=" * 50)
            return 1

        if not targets_to_clean:
            print(f"\n  No shader caches to clean.")
            print("=" * 50)
            return 0

        print(f"\n  Cleaning {len(targets_to_clean)} cache(es)...")
        print(f"  Warning: Shaders will recompile on next game launch.")

        total_freed = 0
        total_deleted = 0
        all_success = True

        for ct in targets_to_clean:
            print(f"\n  {ct.value}...", end=" ", flush=True)
            result = shader_cache_manager.cleanup_cache(ct)
            if result.success:
                print(f"OK ({result.bytes_freed_display}, {result.files_deleted} files)")
                total_freed += result.bytes_freed
                total_deleted += result.files_deleted
            elif result.files_deleted > 0:
                print(f"PARTIAL ({result.files_deleted} deleted, {result.files_failed} locked)")
                total_freed += result.bytes_freed
                total_deleted += result.files_deleted
            else:
                print(f"FAILED: {result.message}")
                all_success = False

        from app.cleanup.cleanup_models import format_bytes as _fmt
        print(f"\n  TOTAL: {_fmt(total_freed)} freed, {total_deleted} files deleted")
        if all_success:
            print(f"  Verification: PASSED")
        else:
            print(f"  Verification: PARTIAL (some files locked)")

        print(f"\n  Expect 1-3 minutes of shader recompilation on next game launch.")

        print("\n" + "=" * 50)
        print("SHADER CLEANUP COMPLETE")
        print("=" * 50)
        return 0

    if "--input-status" in sys.argv:
        from app.performance.input_latency import input_latency_analyzer, ResponsivenessLevel, PointerPrecision, BottleneckType

        report = input_latency_analyzer.analyze(force=True)

        print("=" * 50)
        print("HEAVEN SOCIETY — INPUT RESPONSIVENESS")
        print("=" * 50)

        # Overall
        print(f"\nRESPONSIVENESS")
        print(f"  Score:       {report.responsiveness_score:.0f}/100")
        print(f"  Level:       {report.responsiveness_level.value}")
        print(f"  Bottleneck:  {report.identified_bottleneck.value}")
        if report.bottleneck_description:
            print(f"  Detail:      {report.bottleneck_description}")
        print(f"  Confidence:  {report.bottleneck_confidence * 100:.0f}%")

        # Mouse
        m = report.mouse
        print(f"\nMOUSE SETTINGS (MEASURED)")
        ep = m.enhanced_precision.value if m.enhanced_precision else "UNKNOWN"
        print(f"  Pointer Speed:         {m.pointer_speed}")
        print(f"  Enhanced Precision:    {ep}")
        print(f"  Mouse Trails:          {m.pointer_trails}")
        print(f"  Detection Confidence:  {m.detect_confidence * 100:.0f}%")
        if m.recommendation:
            print(f"  Note:                  {m.recommendation}")

        # Display
        d = report.display
        print(f"\nDISPLAY (MEASURED)")
        if d.resolution_x > 0:
            print(f"  Resolution:    {d.resolution_x}x{d.resolution_y}")
            print(f"  Refresh Rate:  {d.refresh_rate_hz} Hz")
            print(f"  Quality:       {d.refresh_rate_quality} (HEURISTIC)")
            if d.gpu_name:
                print(f"  GPU:           {d.gpu_name}")
        else:
            print(f"  Not detected")
        if d.recommendation:
            print(f"  Note:          {d.recommendation}")

        # Emulator
        e = report.emulator
        print(f"\nEMULATOR (MEASURED)")
        if e.is_detected:
            print(f"  Process:       {e.process_name} PID {e.pid}")
            print(f"  Priority:      {e.priority}")
            print(f"  Affinity:      {e.affinity_cpus}/{e.total_cpus} CPUs")
            print(f"  CPU:           {e.cpu_percent:.1f}%")
            print(f"  RAM:           {e.memory_mb:.0f} MB")
            if e.gpu_name:
                print(f"  GPU:           {e.gpu_name}")
        else:
            print(f"  Not detected")
        if e.recommendation:
            print(f"  Note:          {e.recommendation}")

        # Frame Pacing
        fp = report.frame_pacing
        print(f"\nFRAME PACING (MEASURED)")
        if fp.is_measured and fp.sample_count > 0:
            print(f"  Provider:       {fp.provider}")
            print(f"  Samples:        {fp.sample_count}")
            print(f"  Present FPS:    {fp.present_fps:.1f}")
            print(f"  Median FPS:     {fp.median_fps:.1f}")
            print(f"  1%% Low:         {fp.one_percent_low:.1f}")
            print(f"  0.1%% Low:       {fp.point_one_percent_low:.1f}")
            print(f"  Frame Time:     {fp.avg_frame_time_ms:.2f} ms")
            print(f"  Variance:       {fp.frame_time_variance:.2f} ms²")
            print(f"  Spikes:         {fp.frame_spikes}")
            print(f"  Stability:      {fp.stability_score:.0f}/100")
        else:
            print(f"  No capture data")
            print(f"  Run a benchmark to measure frame pacing")
        if fp.recommendation:
            print(f"  Note:           {fp.recommendation}")

        # Background
        bg = report.background
        print(f"\nBACKGROUND LOAD (MEASURED)")
        print(f"  CPU outside emulator:  {bg.total_cpu_outside_emulator:.1f}%")
        print(f"  Competing processes:   {bg.competing_process_count}")
        print(f"  High CPU processes:    {bg.high_cpu_process_count}")
        print(f"  RAM outside emulator:  {bg.total_ram_outside_mb:.0f} MB")
        print(f"  Impact Level:          {bg.impact_level}")
        if bg.recommendation:
            print(f"  Note:                  {bg.recommendation}")

        # Recommendations
        if report.recommendations:
            print(f"\nRECOMMENDATIONS")
            for i, rec in enumerate(report.recommendations, 1):
                print(f"  {i}. {rec}")

        # Disclaimers
        print(f"\nDISCLAIMERS")
        for d_text in report.disclaimers:
            print(f"  \u2022 {d_text}")

        print("\n" + "=" * 50)
        print("INPUT RESPONSIVENESS COMPLETE")
        print("=" * 50)
        return 0

    if "--frame-pacing" in sys.argv:
        from app.performance.frame_pacing import frame_pacing_analyzer, PacingClassification
        from app.performance.presentmon_provider import PresentMonProvider, find_presentmon
        from app.performance.fps_provider import fps_registry
        import time as _time

        print("=" * 50)
        print("HEAVEN SOCIETY — FRAME PACING ANALYSIS")
        print("=" * 50)

        # Check PresentMon availability
        pm_path = find_presentmon()
        if not pm_path:
            print("\n  PresentMon not found.")
            print("  Frame pacing requires PresentMon for real frame data.")
            print("  Install from: https://github.com/GameTechDev/PresentMon/releases")
            print("=" * 50)
            return 1

        from app.performance.presentmon_provider import get_presentmon_version
        pm_ver = get_presentmon_version(pm_path)
        print(f"\n  PresentMon: {pm_path.name}")
        print(f"  Version:    {pm_ver or 'Unknown'}")

        # Detect target
        from app.core.emulator_controller import emulator_controller
        target = emulator_controller.detect_target()
        target_name = ""
        if target:
            target_name = target.name
            print(f"  Target:     {target.name} PID {target.pid}")
        else:
            print(f"  Target:     Not detected — capturing all processes")

        # Parse duration
        duration = 10
        for i, arg in enumerate(sys.argv):
            if arg == "--duration" and i + 1 < len(sys.argv):
                try:
                    duration = int(sys.argv[i + 1])
                except ValueError:
                    pass

        print(f"\n  Capturing {duration}s of frame data...")

        # Run PresentMon capture
        pm = PresentMonProvider()
        available, reason = pm.is_available()
        if not available:
            print(f"  Cannot start PresentMon: {reason}")
            print("=" * 50)
            return 1

        started = pm.start(target_process=target_name, duration=duration)
        if not started:
            print("  Failed to start PresentMon capture.")
            print("=" * 50)
            return 1

        # Wait for capture to complete
        print("  Capturing... ", end="", flush=True)
        for _ in range(duration + 15):
            _time.sleep(1)
            if not pm.is_running():
                break
        print("done")

        # Stop and parse
        pm.stop()
        samples = pm.get_samples()

        if not samples:
            print("  No frame samples captured.")
            print("=" * 50)
            return 1

        print(f"  Captured {len(samples)} frame samples")

        # Analyze
        result = frame_pacing_analyzer.analyze(samples)

        # Output
        print(f"\nFRAME PACING")
        print(f"  Classification:  {result.classification.value}")
        print(f"  Pacing Score:    {result.pacing_score:.0f}/100")
        print(f"  Samples:         {result.sample_count}")
        print(f"  Duration:        {result.duration_seconds:.1f}s")

        print(f"\nFPS METRICS")
        print(f"  Average:         {result.avg_fps:.1f}")
        print(f"  Median:          {result.median_fps:.1f}")
        print(f"  Min:             {result.min_fps:.1f}")
        print(f"  Max:             {result.max_fps:.1f}")
        print(f"  1% Low:          {result.one_percent_low:.1f}")
        print(f"  0.1% Low:        {result.point_one_percent_low:.1f}")

        print(f"\nFRAME TIME")
        print(f"  Average:         {result.avg_frame_time_ms:.2f} ms")
        print(f"  Median:          {result.median_frame_time_ms:.2f} ms")
        print(f"  Stdev:           {result.frame_time_stdev:.2f} ms")
        print(f"  CV:              {result.coefficient_of_variation:.3f}")

        print(f"\nPERCENTILES")
        p = result.percentiles
        print(f"  P1 (worst):      {p.p1:.2f} ms")
        print(f"  P5:              {p.p5:.2f} ms")
        print(f"  P10:             {p.p10:.2f} ms")
        print(f"  P25:             {p.p25:.2f} ms")
        print(f"  P50 (median):    {p.p50:.2f} ms")
        print(f"  P75:             {p.p75:.2f} ms")
        print(f"  P90:             {p.p90:.2f} ms")
        print(f"  P95:             {p.p95:.2f} ms")
        print(f"  P99 (best):      {p.p99:.2f} ms")
        print(f"  IQR:             {p.interquartile_range:.2f} ms")

        print(f"\nSTUTTERS")
        print(f"  Frame Spikes:    {result.frame_spikes}")
        print(f"  Long Frames:     {result.long_frame_count} ({result.long_frame_percent:.1f}%)")
        print(f"  Micro-stutters:  {result.micro_stutters}")
        print(f"  Severe:          {result.severe_stutters}")
        print(f"  Huge spikes:     {result.huge_spikes}")
        print(f"  Max consecutive: {result.consecutive_stutters}")

        if result.avg_gpu_busy_ms > 0 or result.avg_cpu_busy_ms > 0:
            print(f"\nGPU/CPU TIMING")
            if result.avg_gpu_busy_ms > 0:
                print(f"  GPU Busy:        {result.avg_gpu_busy_ms:.2f} ms")
            if result.avg_cpu_busy_ms > 0:
                print(f"  CPU Busy:        {result.avg_cpu_busy_ms:.2f} ms")
            if result.gpu_utilization > 0:
                print(f"  GPU Util:        {result.gpu_utilization:.1f}%")

        if result.detected_patterns:
            print(f"\nPATTERNS")
            for pat in result.detected_patterns:
                conf = result.pattern_confidences.get(pat.value, 0)
                desc = result.pattern_descriptions.get(pat.value, "")
                print(f"  {pat.value} ({conf * 100:.0f}% confidence)")
                if desc:
                    print(f"    {desc}")

        if result.recommendations:
            print(f"\nRECOMMENDATIONS")
            for i, rec in enumerate(result.recommendations, 1):
                print(f"  {i}. {rec}")

        print(f"\n" + "=" * 50)
        print("FRAME PACING ANALYSIS COMPLETE")
        print("=" * 50)
        return 0

    if "--thermal-status" in sys.argv:
        from app.system.thermal_monitor import (
            thermal_diagnostics, ThermalState, ThrottleIndicator,
        )

        diag = thermal_diagnostics.diagnose(force=True)

        print("=" * 50)
        print("HEAVEN SOCIETY — THERMAL STATUS")
        print("=" * 50)

        # Overall
        state_colors = {
            ThermalState.NORMAL: "OK",
            ThermalState.WARM: "WARM",
            ThermalState.HOT: "HOT",
            ThermalState.THROTTLING_RISK: "THROTTLING",
            ThermalState.UNKNOWN: "UNKNOWN",
        }
        print(f"\nTHERMAL STATE")
        print(f"  State:       {diag.thermal_state.value}")
        print(f"  Max Temp:    {diag.max_temperature:.0f}°C" if diag.max_temperature > 0 else "  Max Temp:    N/A")

        # GPU
        g = diag.gpu
        print(f"\nGPU (MEASURED)")
        if g.name:
            print(f"  Name:        {g.name}")
        if g.temperature_celsius is not None:
            print(f"  Temperature: {g.temperature_celsius:.0f}°C")
        else:
            print(f"  Temperature: N/A")
        print(f"  Utilization: {g.utilization_gpu:.0f}%")
        if g.clock_core_mhz > 0:
            print(f"  Clock:       {g.clock_core_mhz:.0f} MHz")
        if g.power_draw_watts is not None:
            print(f"  Power:       {g.power_draw_watts:.1f}W", end="")
            if g.power_limit_watts:
                print(f" / {g.power_limit_watts:.0f}W limit")
            else:
                print()
        if g.fan_speed_percent is not None:
            print(f"  Fan:         {g.fan_speed_percent:.0f}%")
        print(f"  VRAM:        {g.vram_used_mb:.0f}/{g.vram_total_mb:.0f} MB ({g.vram_percent:.0f}%)")
        if g.power_utilization is not None:
            print(f"  Power Util:  {g.power_utilization:.0f}%")

        # CPU
        c = diag.cpu
        print(f"\nCPU (MEASURED)")
        if c.model:
            print(f"  Model:       {c.model[:50]}")
        if c.temperature_celsius is not None:
            print(f"  Temperature: {c.temperature_celsius:.0f}°C")
        else:
            print(f"  Temperature: N/A (psutil sensors not available)")
        print(f"  Utilization: {c.utilization_percent:.0f}%")
        if c.frequency_mhz > 0:
            print(f"  Frequency:   {c.frequency_mhz:.0f} MHz")
            if c.max_frequency_mhz > 0:
                print(f"  Max Freq:    {c.max_frequency_mhz:.0f} MHz ({c.frequency_ratio:.0%})")

        # Memory
        m = diag.memory
        print(f"\nMEMORY (MEASURED)")
        print(f"  RAM:         {m.used_gb:.1f}/{m.total_gb:.1f} GB ({m.percent_used:.0f}%)")
        print(f"  Available:   {m.available_gb:.1f} GB")
        print(f"  Swap:        {m.swap_percent:.0f}%")
        print(f"  Pressure:    {m.pressure_level}")

        # Throttle indicators
        print(f"\nTHROTTLE INDICATORS (HEURISTIC)")
        for ind in diag.throttle_indicators:
            if ind == ThrottleIndicator.NONE:
                print(f"  None detected")
            else:
                print(f"  {ind.value}")
        print(f"  Confidence:  {diag.throttle_confidence * 100:.0f}%")

        # Correlation
        corr = diag.correlation
        if corr.temperature_trend or corr.clock_trend or corr.frame_time_trend:
            print(f"\nPERFORMANCE CORRELATION (HEURISTIC)")
            if corr.temperature_trend:
                print(f"  Temp Trend:  {corr.temperature_trend}")
            if corr.clock_trend:
                print(f"  Clock Trend: {corr.clock_trend}")
            if corr.frame_time_trend:
                print(f"  FT Trend:    {corr.frame_time_trend}")
            print(f"  Strength:    {corr.correlation_strength:.0%}")
            if corr.correlation_description:
                print(f"  {corr.correlation_description}")

        # Recommendations
        if diag.recommendations:
            print(f"\nRECOMMENDATIONS")
            for i, rec in enumerate(diag.recommendations, 1):
                print(f"  {i}. {rec}")

        # Disclaimers
        print(f"\nDISCLAIMERS")
        for d_text in diag.disclaimers:
            print(f"  \u2022 {d_text}")

        print("\n" + "=" * 50)
        print("THERMAL STATUS COMPLETE")
        print("=" * 50)
        return 0

    if "--power-status" in sys.argv:
        from app.system.power_analyzer import (
            power_analyzer, PowerClassification, BatteryState,
            ProcessorPerformanceState,
        )

        result = power_analyzer.analyze(force=True)

        print("=" * 50)
        print("HEAVEN SOCIETY — POWER & PERFORMANCE STATE")
        print("=" * 50)

        # Overall
        print(f"\nCLASSIFICATION")
        print(f"  State:       {result.classification.value}")
        print(f"  Reason:      {result.classification_reason}")

        # Battery
        b = result.battery
        print(f"\nPOWER SOURCE (MEASURED)")
        print(f"  State:       {b.state.value}")
        if b.percent is not None:
            print(f"  Battery:     {b.percent:.0f}%")
        if b.seconds_left is not None and b.seconds_left > 0:
            hours = b.seconds_left // 3600
            mins = (b.seconds_left % 3600) // 60
            print(f"  Time Left:   {hours}h {mins}m")
        print(f"  Plugged:     {'Yes' if b.power_plugged else 'No'}")

        # Power Plan
        print(f"\nPOWER PLAN (MEASURED)")
        print(f"  Active:      {result.power_plan_name}")
        print(f"  Performance: {'Yes' if result.power_plan_is_performance else 'No'}")

        # Windows Power Mode
        wm = result.windows_power_mode
        print(f"\nWINDOWS POWER MODE (MEASURED)")
        if wm.power_mode:
            print(f"  Mode:        {wm.power_mode}")
        else:
            print(f"  Mode:        Unknown")

        # Processor
        p = result.processor
        print(f"\nPROCESSOR (MEASURED)")
        print(f"  State:       {p.performance_state.value}")
        print(f"  Cores:       {p.core_count}")
        if p.current_frequency_mhz > 0:
            print(f"  Frequency:   {p.current_frequency_mhz:.0f} MHz")
            if p.max_frequency_mhz > 0:
                print(f"  Max Freq:    {p.max_frequency_mhz:.0f} MHz ({p.frequency_ratio:.0%})")
        print(f"  Utilization: {p.utilization_percent:.0f}%")
        print(f"  Throttle:    {p.throttle_min_percent}%-{p.throttle_max_percent}%")
        if p.boost_mode >= 0:
            boost_names = {0: "Disabled", 1: "Enabled", 2: "Aggressive"}
            print(f"  Boost:       {boost_names.get(p.boost_mode, f'Mode {p.boost_mode}')}")

        # GPU
        g = result.gpu
        print(f"\nGPU (MEASURED)")
        if g.name:
            print(f"  Name:        {g.name}")
        if g.power_draw_watts is not None:
            print(f"  Power:       {g.power_draw_watts:.1f}W", end="")
            if g.power_limit_watts:
                print(f" / {g.power_limit_watts:.0f}W limit")
            else:
                print()
        if g.power_utilization is not None:
            print(f"  Power Util:  {g.power_utilization:.0f}%")
        if g.temperature is not None:
            print(f"  Temperature: {g.temperature:.0f}°C")
        print(f"  Utilization: {g.utilization:.0f}%")
        if g.clock_mhz > 0:
            print(f"  Clock:       {g.clock_mhz:.0f} MHz")
        print(f"  VRAM:        {g.vram_used_mb:.0f}/{g.vram_total_mb:.0f} MB")
        if g.power_state:
            print(f"  Perf State:  {g.power_state}")

        # Display
        d = result.display
        if d.refresh_rate_hz > 0:
            print(f"\nDISPLAY (MEASURED)")
            print(f"  Resolution:  {d.resolution_x}x{d.resolution_y}")
            print(f"  Refresh:     {d.refresh_rate_hz} Hz")

        # Recommendations
        if result.recommendations:
            print(f"\nRECOMMENDATIONS")
            for i, rec in enumerate(result.recommendations, 1):
                print(f"  {i}. {rec}")

        # Disclaimers
        print(f"\nDISCLAIMERS")
        for d_text in result.disclaimers:
            print(f"  \u2022 {d_text}")

        print("\n" + "=" * 50)
        print("POWER STATUS COMPLETE")
        print("=" * 50)
        return 0

    if "--hardware-profile" in sys.argv:
        from app.core.hardware_profile import analyze_hardware_profile, print_hardware_profile

        result = analyze_hardware_profile()
        print_hardware_profile(result)
        print("HARDWARE PROFILE COMPLETE")
        return 0

    if "--analyze-gaming" in sys.argv:
        from app.core.adaptive_optimizer import adaptive_optimizer
        from app.performance.realtime_telemetry import RealtimeTelemetry
        from app.performance.presentmon_provider import PresentMonProvider
        from app.core.optimizer import optimizer
        import time as _time

        duration = 10
        for i, arg in enumerate(sys.argv):
            if arg == "--duration" and i + 1 < len(sys.argv):
                try:
                    duration = int(sys.argv[i + 1])
                except ValueError:
                    pass

        print("=" * 50)
        print("HEAVEN SOCIETY — GAMING ANALYSIS")
        print("=" * 50)

        # Detect target
        from app.emulator.detector import emulator_detector
        emus = emulator_detector.detect_all()
        target_pid = 0
        target_name = ""
        if emus:
            emu = emus[0]
            target_pid = getattr(emu, 'pid', 0) or 0
            target_name = getattr(emu, 'process_name', '') or getattr(emu, 'name', 'Emulator')
            print(f"\nTARGET")
            print(f"  Emulator:    {target_name}")
            print(f"  PID:         {target_pid}")
        else:
            print(f"\nTARGET")
            print(f"  Status:      No emulator detected")

        # Collect telemetry
        engine = RealtimeTelemetry(interval_ms=500, max_samples=duration * 2 + 10)
        pm = PresentMonProvider()
        pm_available, _ = pm.is_available()
        if pm_available and target_name:
            pm.start(target_process=target_name, duration=duration + 5)
            if pm.is_running():
                engine.set_fps_provider(pm)

        session = engine.start_session(target_name, target_pid)
        try:
            for _ in range(duration):
                _time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            engine.stop_session()
            if pm.is_running():
                pm.stop()

        samples = engine.recent_snapshots()
        state, confidence, evidence = adaptive_optimizer.classify_state(samples)

        # Get optimization states
        opt_status = optimizer.get_current_status()
        states = {o["id"]: o.get("status", "UNKNOWN") for o in opt_status.get("optimizations", [])}

        is_admin = False
        try:
            from app.utils.admin import is_admin as check_admin
            is_admin = check_admin()
        except Exception:
            pass

        plan = adaptive_optimizer.generate_plan(
            samples=samples, state=state, state_confidence=confidence,
            state_evidence=evidence, optimization_states=states,
            target_name=target_name, target_pid=target_pid, is_admin=is_admin,
        )

        # Profile suitability
        from app.core.adaptive_optimizer import ProfileSuitability
        suitability = adaptive_optimizer.assess_profile_suitability(
            plan.recommended_profile, state, confidence, is_admin, samples,
        )

        state_str = state.value.replace("_", " ").title()
        print(f"\nBOTTLENECK")
        print(f"  Type:        {state_str}")
        print(f"  Confidence:  {confidence}%")
        for ev in evidence[:5]:
            print(f"  Detail:      {ev}")

        print(f"\nRECOMMENDED PROFILE: {plan.recommended_profile.upper()}")
        print(f"  Suitability: {suitability.suitability.value}")
        print(f"  Reason:      {suitability.reason}")

        applicable = [a for a in plan.actions if a.status.value not in ("SKIPPED_NOT_IN_PROFILE",)]
        if applicable:
            print(f"\nACTIONS ({len(applicable)})")
            for a in applicable:
                icon = {"APPLIED": "+", "ALREADY_OPTIMAL": "=", "REQUIRES_ADMIN": "!",
                        "RECOMMENDATION_ONLY": "~", "NOT_AVAILABLE": "-"}.get(a.status.value, "?")
                print(f"  {icon} {a.optimization_name:24s} {a.status.value}")
                print(f"    {a.reason}")
        else:
            print(f"\nNo applicable actions.")

        # Assessment
        if state.value == "OPTIMAL":
            print(f"\nASSESSMENT")
            print(f"  No clear performance bottleneck detected. System appears balanced.")
        elif state.value == "INSUFFICIENT_DATA":
            print(f"\nASSESSMENT")
            print(f"  Insufficient telemetry data to assess gaming performance.")
        else:
            print(f"\nASSESSMENT")
            print(f"  {state_str} detected with {confidence}% confidence.")

        print("\n" + "=" * 50)
        print("GAMING ANALYSIS COMPLETE")
        print("=" * 50)
        return 0

    if "--report" in sys.argv:
        from app.core.performance_report import performance_report_generator

        # Parse args
        export_json = "--json" in sys.argv
        json_path = None
        for i, arg in enumerate(sys.argv):
            if arg == "--json" and i + 1 < len(sys.argv):
                json_path = sys.argv[i + 1]

        report = performance_report_generator.generate()

        # Print CLI report
        print(performance_report_generator.format_cli(report))

        # Export JSON if requested
        if export_json:
            path = performance_report_generator.export_json(report, json_path)
            print(f"\nJSON report exported: {path}")

        return 0

    if "--validate-opt" in sys.argv:
        from app.core.optimization_evidence import (
            optimization_evidence_engine, EvidenceVerdict
        )
        from app.core.profiles import get_profile, get_all_profiles

        # Parse args
        profile_id = "gaming"
        duration = 8
        for i, arg in enumerate(sys.argv):
            if arg == "--profile" and i + 1 < len(sys.argv):
                profile_id = sys.argv[i + 1]
            if arg == "--duration" and i + 1 < len(sys.argv):
                try:
                    duration = int(sys.argv[i + 1])
                except ValueError:
                    pass

        profile = get_profile(profile_id)
        if not profile:
            print(f"Unknown profile: {profile_id}")
            print(f"Available: {', '.join(p.id for p in get_all_profiles())}")
            return 1

        print("=" * 50)
        print("HEAVEN SOCIETY -- OPTIMIZATION VALIDATION")
        print("=" * 50)
        print(f"\nProfile:  {profile.name}")
        print(f"Duration: {duration}s per measurement")

        # Collect applicable optimization IDs
        opt_ids = [po.opt_id for po in profile.optimizations]
        opt_names = {po.opt_id: po.name for po in profile.optimizations}

        print(f"Optimizations: {len(opt_ids)}")
        for oid in opt_ids:
            print(f"  - {opt_names.get(oid, oid)}")

        print(f"\n{'=' * 50}")
        print("Running validation...")
        print(f"{'=' * 50}\n")

        session = optimization_evidence_engine.validate_profile(
            profile_id=profile_id,
            optimization_ids=opt_ids,
            optimization_names=opt_names,
            duration=duration,
        )

        # Print results
        print("\n" + "=" * 50)
        print("VALIDATION RESULTS")
        print("=" * 50)

        for ev in session.evidence_list:
            icon = {
                EvidenceVerdict.BENEFICIAL: "+",
                EvidenceVerdict.NEUTRAL: "=",
                EvidenceVerdict.HARMFUL: "-",
                EvidenceVerdict.INCONCLUSIVE: "?",
                EvidenceVerdict.SKIPPED: "~",
            }.get(ev.verdict, "?")

            print(f"\n  {icon} {ev.optimization_name}")
            print(f"    Verdict:  {ev.verdict.value}")
            print(f"    Reason:   {ev.verdict_reason}")
            if ev.fps_delta is not None:
                print(f"    FPS:      {ev.fps_delta:+.1f} ({ev.fps_delta_percent:+.1f}%)")
            if ev.one_low_delta is not None:
                print(f"    1% Low:   {ev.one_low_delta:+.1f}")
            if ev.frame_time_delta is not None:
                print(f"    Frame T:  {ev.frame_time_delta:+.2f}ms")
            if ev.was_rolled_back:
                print(f"    ROLLED BACK: {ev.rollback_reason}")

        # Summary
        print("\n" + "=" * 50)
        print("SUMMARY")
        print("=" * 50)
        print(f"  Beneficial:     {session.beneficial_count}")
        print(f"  Neutral:        {session.neutral_count}")
        print(f"  Harmful:        {session.harmful_count}")
        print(f"  Inconclusive:   {session.inconclusive_count}")
        print(f"  Skipped:        {session.skipped_count}")
        print(f"  Duration:       {session.duration_seconds:.1f}s")

        if session.harmful_count > 0:
            print(f"\n  NOTE: {session.harmful_count} optimization(s) caused regression")
            print(f"        and were automatically rolled back.")

        print("\n" + "=" * 50)
        print("VALIDATION COMPLETE")
        print("=" * 50)
        return 0

    if "--gaming-session" in sys.argv:
        from app.core.gaming_session import (
            gaming_session_engine, GamingSession, SessionState
        )
        from app.core.profiles import get_profile, get_all_profiles

        # Parse args
        profile_id = "gaming"
        action = "start"  # start, stop, status, restore
        for i, arg in enumerate(sys.argv):
            if arg == "--profile" and i + 1 < len(sys.argv):
                profile_id = sys.argv[i + 1]
            if arg == "--stop":
                action = "stop"
            if arg == "--restore":
                action = "restore"
            if arg == "--status":
                action = "status"

        print("=" * 50)
        print("HEAVEN SOCIETY -- GAMING SESSION")
        print("=" * 50)

        if action == "status":
            session = gaming_session_engine.session
            if session:
                print(f"\nSession:  {session.session_id}")
                print(f"State:    {session.state.value}")
                print(f"Profile:  {session.profile_name or session.profile_id}")
                print(f"Target:   {session.target_name} PID={session.target_pid}")
                print(f"Started:  {session.started_at}")
                if session.applied_count > 0:
                    print(f"Applied:  {session.applied_count} optimization(s)")
                if session.telemetry_history:
                    print(f"Samples:  {len(session.telemetry_history)}")
            else:
                print("\nNo active session")

            # Show recent sessions
            from app.core.gaming_session import load_sessions
            sessions = load_sessions()
            if sessions:
                print(f"\nRecent sessions: {len(sessions)}")
                for s in sessions[-3:]:
                    print(f"  {s.session_id} | {s.state.value} | {s.profile_id} | {s.duration_seconds:.0f}s")
            print("\n" + "=" * 50)
            return 0

        elif action == "stop":
            if not gaming_session_engine.is_active:
                print("\nNo active session to stop")
                print("=" * 50)
                return 0

            session = gaming_session_engine.stop_session()
            print(f"\nSession:  {session.session_id}")
            print(f"Duration: {session.duration_seconds:.1f}s")
            print(f"Target:   {session.target_name} PID={session.target_pid}")
            if session.target_lost:
                print("  NOTE: Target process was lost during session")
            if session.applied_count > 0:
                print(f"Applied:  {session.applied_count} optimization(s)")
                print(f"  Restored: {'Yes' if session.snapshot_restored else 'No'}")
            if session.final.avg_cpu is not None:
                print(f"Final:    CPU={session.final.avg_cpu:.0f}% GPU={session.final.avg_gpu:.0f}% RAM={session.final.avg_ram:.0f}%")
            if session.errors:
                print(f"Errors:   {len(session.errors)}")
                for e in session.errors:
                    print(f"  - {e}")
            print("\n" + "=" * 50)
            print("SESSION STOPPED")
            print("=" * 50)
            return 0

        elif action == "restore":
            session = gaming_session_engine.restore_session()
            if session.session_id:
                print(f"\nSession:  {session.session_id}")
                print(f"Restored: {'Yes' if session.snapshot_restored else 'No'}")
                if session.errors:
                    for e in session.errors:
                        print(f"  Error: {e}")
            else:
                print("\nNo session to restore")
            print("\n" + "=" * 50)
            return 0

        else:  # start
            profile = get_profile(profile_id)
            if not profile:
                print(f"\nUnknown profile: {profile_id}")
                print(f"Available: {', '.join(p.id for p in get_all_profiles())}")
                return 1

            print(f"\nProfile:  {profile.name}")
            print(f"Starting gaming session...")

            session = gaming_session_engine.start_session(profile_id)

            print(f"\nSession:  {session.session_id}")
            print(f"State:    {session.state.value}")
            print(f"Target:   {session.target_name} PID={session.target_pid}")

            if session.state == SessionState.FAILED:
                print(f"\nFailed:")
                for e in session.errors:
                    print(f"  - {e}")
                print("\n" + "=" * 50)
                print("SESSION FAILED")
                print("=" * 50)
                return 1

            if session.baseline.avg_cpu is not None:
                print(f"Baseline: CPU={session.baseline.avg_cpu:.0f}% GPU={session.baseline.avg_gpu:.0f}% RAM={session.baseline.avg_ram:.0f}%")

            if session.applied_count > 0:
                print(f"\nApplied optimizations:")
                for opt in session.optimizations:
                    if opt.status == "APPLIED":
                        v = "verified" if opt.verified else "unverified"
                        print(f"  + {opt.name} ({v})")
                    elif opt.status == "ALREADY_OPTIMAL":
                        print(f"  = {opt.name} (already optimal)")
                    elif opt.status == "REQUIRES_ADMIN":
                        print(f"  ! {opt.name} (requires admin)")
                    elif opt.status == "RECOMMENDATION_ONLY":
                        print(f"  ~ {opt.name} (recommendation only)")

            print(f"\nSession is ACTIVE. Use --gaming-session --stop to end.")

            # Wait for user to stop
            print("\nPress Enter to stop the session...")
            try:
                input()
            except (EOFError, KeyboardInterrupt):
                pass

            # Stop session
            session = gaming_session_engine.stop_session()
            print(f"\nSession ended: {session.duration_seconds:.1f}s")
            if session.final.avg_cpu is not None:
                print(f"Final:    CPU={session.final.avg_cpu:.0f}% GPU={session.final.avg_gpu:.0f}% RAM={session.final.avg_ram:.0f}%")
            print("=" * 50)
            print("SESSION COMPLETE")
            print("=" * 50)
            return 0

    if "--emulator-benchmark" in sys.argv:
        profile_id = "gaming"
        duration = 15
        runs = 3
        for i, arg in enumerate(sys.argv):
            if arg == "--profile" and i + 1 < len(sys.argv):
                profile_id = sys.argv[i + 1]
            if arg == "--duration" and i + 1 < len(sys.argv):
                try:
                    duration = int(sys.argv[i + 1])
                except ValueError:
                    pass
            if arg == "--runs" and i + 1 < len(sys.argv):
                try:
                    runs = int(sys.argv[i + 1])
                except ValueError:
                    pass

        from app.performance.ab_benchmark import run_ab_benchmark_cli
        run_ab_benchmark_cli(profile_id=profile_id, duration=duration, runs=runs)
        return 0

    if "--telemetry-status" in sys.argv:
        from app.performance.realtime_telemetry import realtime_telemetry
        import time as _time

        # Quick 3-second capture for status
        print("=" * 50)
        print("HEAVEN SOCIETY — TELEMETRY STATUS")
        print("=" * 50)
        print()

        # Detect target
        from app.emulator.detector import emulator_detector
        emus = emulator_detector.detect_all()
        target_pid = 0
        target_name = ""
        if emus:
            emu = emus[0]
            target_pid = getattr(emu, 'pid', 0) or 0
            target_name = getattr(emu, 'process_name', '') or getattr(emu, 'name', 'Emulator')

        if target_pid > 0:
            print(f"TARGET")
            print(f"  {target_name}  PID: {target_pid}")
        else:
            print("TARGET")
            print("  No emulator detected")
        print()

        # Quick capture
        session = realtime_telemetry.start_session(target_name, target_pid)
        _time.sleep(3)
        realtime_telemetry.stop_session()

        status = realtime_telemetry.get_status_dict()
        latest = status.get("latest", {})
        summary_data = status.get("summary", {})
        bottleneck_data = status.get("bottleneck", {})

        print("PERFORMANCE")
        if latest.get("fps") is not None:
            print(f"  FPS:           {latest['fps']:.1f}")
        else:
            print("  FPS:           N/A")
        if latest.get("one_percent_low") is not None:
            print(f"  1% Low:        {latest['one_percent_low']:.1f}")
        else:
            print("  1% Low:        N/A")
        if latest.get("frame_time_ms") is not None:
            print(f"  Frame Time:    {latest['frame_time_ms']:.2f} ms")
        else:
            print("  Frame Time:    N/A")
        print()

        print("SYSTEM")
        if latest.get("cpu_percent") is not None:
            print(f"  CPU:           {latest['cpu_percent']:.1f}%")
        else:
            print("  CPU:           N/A")
        if latest.get("gpu_percent") is not None:
            print(f"  GPU:           {latest['gpu_percent']:.1f}%")
        else:
            print("  GPU:           N/A")
        if latest.get("ram_used_mb") is not None:
            used_gb = latest['ram_used_mb'] / 1024
            total_gb = (latest.get('ram_total_mb') or 0) / 1024
            print(f"  RAM:           {used_gb:.1f}/{total_gb:.1f} GB")
        else:
            print("  RAM:           N/A")
        print()

        print("THERMALS")
        if latest.get("gpu_temp_c") is not None:
            print(f"  GPU:           {latest['gpu_temp_c']:.0f}\u00b0C")
        else:
            print("  GPU:           N/A")
        if latest.get("cpu_temperature_c") is not None:
            print(f"  CPU:           {latest['cpu_temperature_c']:.0f}\u00b0C")
        else:
            print("  CPU:           N/A")
        print()

        bn_type = bottleneck_data.get("bottleneck", "INSUFFICIENT_DATA")
        bn_conf = bottleneck_data.get("confidence", 0)
        pacing = status.get("frame_pacing", "INSUFFICIENT_DATA")
        print(f"BOTTLENECK:     {bn_type}")
        print(f"CONFIDENCE:     {bn_conf}%")
        print(f"FRAME PACING:   {pacing}")
        print()

        overhead = status.get("overhead", {})
        print(f"SAMPLES:        {status.get('sample_count', 0)}")
        print(f"OVERHEAD:       {overhead.get('avg_collection_time_ms', 0):.1f}ms avg")
        print()
        print("=" * 50)
        return 0

    if "--telemetry" in sys.argv:
        from app.performance.realtime_telemetry import RealtimeTelemetry
        from app.performance.presentmon_provider import PresentMonProvider
        import time as _time

        duration = 30
        interval_ms = 500
        for i, arg in enumerate(sys.argv):
            if arg == "--duration" and i + 1 < len(sys.argv):
                try:
                    duration = int(sys.argv[i + 1])
                except ValueError:
                    pass
            if arg == "--interval" and i + 1 < len(sys.argv):
                try:
                    interval_ms = int(float(sys.argv[i + 1]) * 1000)
                except ValueError:
                    pass

        print("=" * 50)
        print("HEAVEN SOCIETY — REAL-TIME TELEMETRY")
        print("=" * 50)
        print(f"Duration: {duration}s  |  Interval: {interval_ms}ms")
        print()

        # Detect target
        from app.emulator.detector import emulator_detector
        emus = emulator_detector.detect_all()
        target_pid = 0
        target_name = ""
        if emus:
            emu = emus[0]
            if hasattr(emu, 'pid') and emu.pid:
                target_pid = emu.pid
                target_name = getattr(emu, 'process_name', '') or getattr(emu, 'name', 'Emulator')
                print(f"TARGET")
                print(f"  {target_name}  PID: {target_pid}")
            else:
                print(f"Emulator detected but PID unavailable")
        else:
            print("TARGET")
            print("  No emulator detected")
        print()

        # Create engine
        engine = RealtimeTelemetry(interval_ms=interval_ms, max_samples=duration * 1000 // interval_ms + 10)

        # Try PresentMon
        pm = PresentMonProvider()
        pm_available, pm_reason = pm.is_available()
        if pm_available and target_name:
            print(f"PresentMon: {pm_reason}")
            print(f"Starting PresentMon for {target_name}...")
            pm_started = pm.start(target_process=target_name, duration=duration + 5)
            if pm_started:
                engine.set_fps_provider(pm)
            else:
                print(f"PresentMon start failed: {pm.get_error_reason()}")
        else:
            print(f"PresentMon: {pm_reason}")
        print()

        # Start session
        session = engine.start_session(target_name, target_pid)

        # Progress dots
        print(f"Collecting telemetry for {duration}s ", end="", flush=True)
        try:
            for _ in range(duration):
                _time.sleep(1)
                print(".", end="", flush=True)
        except KeyboardInterrupt:
            print("\nInterrupted.")
        finally:
            engine.stop_session()
            if pm.is_running():
                pm.stop()
        print()

        # Results
        status = engine.get_status_dict()
        latest = status.get("latest", {})
        summary_data = status.get("summary", {})
        bottleneck_data = status.get("bottleneck", {})
        pacing = status.get("frame_pacing", "INSUFFICIENT_DATA")

        print()
        print("TELEMETRY RESULTS")
        print("-" * 50)
        print(f"Samples: {session.sample_count if session else status.get('sample_count', 0)}")
        print(f"Duration: {session.get_duration():.1f}s" if session else "")
        print(f"Frame Pacing: {pacing}")
        print()

        print("PERFORMANCE")
        if latest.get("fps") is not None:
            print(f"  FPS:           {latest['fps']:.1f}")
        else:
            print("  FPS:           NOT_AVAILABLE")
        if summary_data.get("median_fps") is not None:
            print(f"  Median FPS:    {summary_data['median_fps']:.1f}")
        if summary_data.get("one_percent_low") is not None:
            print(f"  1% Low:        {summary_data['one_percent_low']:.1f}")
        if summary_data.get("point_one_percent_low") is not None:
            print(f"  0.1% Low:      {summary_data['point_one_percent_low']:.1f}")
        if summary_data.get("avg_frame_time_ms") is not None:
            print(f"  Frame Time:    {summary_data['avg_frame_time_ms']:.2f} ms")
        if summary_data.get("frame_spikes") is not None:
            print(f"  Frame Spikes:  {summary_data['frame_spikes']}")
        if summary_data.get("stability_rating") is not None:
            print(f"  Stability:     {summary_data['stability_rating']} ({summary_data.get('stability_score', 0):.0f}/100)")
        print()

        print("SYSTEM")
        if summary_data.get("avg_cpu_percent") is not None:
            print(f"  CPU Avg:       {summary_data['avg_cpu_percent']:.1f}%  Peak: {summary_data.get('peak_cpu_percent', 0):.1f}%")
        if summary_data.get("avg_gpu_percent") is not None:
            print(f"  GPU Avg:       {summary_data['avg_gpu_percent']:.1f}%  Peak: {summary_data.get('peak_gpu_percent', 0):.1f}%")
        elif summary_data.get("gpu_vram_total"):
            print(f"  GPU VRAM:      {summary_data.get('gpu_vram_used_avg', 0):.0f}/{summary_data['gpu_vram_total']:.0f} MB")
        if summary_data.get("avg_ram_used_mb") is not None:
            used_gb = summary_data['avg_ram_used_mb'] / 1024
            total_gb = (summary_data.get('ram_total_mb') or 0) / 1024
            avail_gb = (summary_data.get('avg_ram_available_mb') or 0) / 1024
            print(f"  RAM:           {used_gb:.1f}/{total_gb:.1f} GB  Avail: {avail_gb:.1f} GB")
        print()

        print("THERMALS")
        if summary_data.get("avg_gpu_temp") is not None:
            print(f"  GPU Avg:       {summary_data['avg_gpu_temp']:.0f}\u00b0C  Peak: {summary_data.get('max_gpu_temp', 0):.0f}\u00b0C")
        else:
            print("  GPU:           N/A")
        print()

        print("BOTTLENECK")
        bn_type = bottleneck_data.get("bottleneck", "INSUFFICIENT_DATA")
        bn_conf = bottleneck_data.get("confidence", 0)
        conf_label = "HIGH" if bn_conf >= 70 else ("MODERATE" if bn_conf >= 40 else ("LOW" if bn_conf > 0 else "INCONCLUSIVE"))
        print(f"  Result:        {bn_type}")
        print(f"  Confidence:    {conf_label} ({bn_conf}%)")
        for ev in bottleneck_data.get("evidence", [])[:3]:
            print(f"  Evidence:      {ev}")
        for rec in bottleneck_data.get("recommendations", [])[:2]:
            print(f"  Recommendation: {rec}")
        print()

        overhead = status.get("overhead", {})
        print("OVERHEAD")
        print(f"  Collection:    {overhead.get('avg_collection_time_ms', 0):.1f}ms avg, {overhead.get('peak_collection_time_ms', 0):.1f}ms peak")
        print(f"  CPU Impact:    {overhead.get('cpu_overhead_percent', 0):.2f}%")
        print()
        print("=" * 50)
        return 0

    if "--performance-session" in sys.argv:
        from app.performance.telemetry_collector import TelemetryCollector
        from app.performance.telemetry_models import TelemetrySession
        from app.performance.bottleneck_analyzer import BottleneckAnalyzer
        from app.performance.presentmon_provider import PresentMonProvider
        import time as _time

        duration = 120
        for i, arg in enumerate(sys.argv):
            if arg == "--duration" and i + 1 < len(sys.argv):
                try:
                    duration = int(sys.argv[i + 1])
                except ValueError:
                    pass

        print("=" * 50)
        print("HEAVEN SOCIETY — PERFORMANCE SESSION")
        print("=" * 50)
        print(f"Duration: {duration}s")
        print()

        session = TelemetrySession(
            started_at=_time.time(),
            duration_seconds=duration,
        )

        # Detect target
        from app.emulator.detector import emulator_detector
        emus = emulator_detector.detect_all()
        if emus:
            emu = emus[0]
            pid = getattr(emu, 'pid', 0) or 0
            name = getattr(emu, 'process_name', '') or getattr(emu, 'name', 'Emulator')
            session.target_name = name
            session.target_pid = pid
            print(f"Target: {name} PID: {pid}")
        else:
            print("No emulator detected")

        # Hardware info
        from app.core.scanner import hardware_scanner
        profile = hardware_scanner.scan()
        if hasattr(profile, 'cpu') and profile.cpu:
            session.cpu_model = getattr(profile.cpu, 'model', '') or "Unknown"
        if hasattr(profile, 'gpus') and profile.gpus:
            session.gpu_model = getattr(profile.gpus[0], 'name', '') or "Unknown"
        if hasattr(profile, 'memory') and profile.memory:
            session.total_ram_mb = (getattr(profile.memory, 'ram_total_gb', 0) or 0) * 1024

        # Start PresentMon
        pm = PresentMonProvider()
        pm_available, _ = pm.is_available()
        if pm_available and session.target_name:
            pm.start(target_process=session.target_name, duration=duration + 10)

        # Start collector
        collector = TelemetryCollector(interval_ms=500, max_samples=duration * 2 + 10)
        if session.target_pid > 0:
            collector.set_target(session.target_pid, session.target_name)
        if pm.is_running():
            collector.set_fps_provider(pm)
        collector.start()

        print(f"\nSession running for {duration}s...\n")

        try:
            _time.sleep(duration)
        except KeyboardInterrupt:
            print("\nInterrupted.")
        finally:
            collector.stop()
            if pm.is_running():
                pm.stop()

        session.completed_at = _time.time()
        summary = collector.calculate_summary()

        # Fill session from summary
        session.sample_count = summary.sample_count
        session.avg_fps = summary.avg_fps
        session.median_fps = summary.median_fps
        session.min_fps = summary.min_fps
        session.max_fps = summary.max_fps
        session.one_percent_low = summary.one_percent_low
        session.avg_frame_time_ms = summary.avg_frame_time_ms
        session.frame_spikes = summary.frame_spikes
        session.avg_cpu_percent = summary.avg_cpu_percent
        session.peak_cpu_percent = summary.peak_cpu_percent
        session.avg_gpu_percent = summary.avg_gpu_percent
        session.peak_gpu_percent = summary.peak_gpu_percent
        session.max_gpu_temp = summary.max_gpu_temp
        session.avg_ram_used_mb = summary.avg_ram_used_mb
        session.avg_emulator_cpu = summary.avg_emulator_cpu
        session.avg_emulator_ram_mb = summary.avg_emulator_ram_mb

        # Bottleneck
        analyzer = BottleneckAnalyzer()
        session.bottleneck = analyzer.analyze_samples(collector.samples)

        # Print results
        print("SESSION RESULTS")
        print("-" * 50)
        print(f"Duration: {session.get_duration():.1f}s  Samples: {session.sample_count}")
        print()

        if session.avg_fps is not None:
            print(f"FPS  Avg: {session.avg_fps:.1f}  Med: {session.median_fps:.1f}  1% Low: {session.one_percent_low:.1f}")
        else:
            print("FPS: NOT_AVAILABLE")

        if session.avg_cpu_percent is not None:
            print(f"CPU  Avg: {session.avg_cpu_percent:.1f}%  Peak: {session.peak_cpu_percent:.1f}%")

        if session.avg_gpu_percent is not None:
            print(f"GPU  Avg: {session.avg_gpu_percent:.1f}%  Peak: {session.peak_gpu_percent:.1f}%")
            if session.max_gpu_temp:
                print(f"     Temp: {session.max_gpu_temp:.0f}°C")

        if session.avg_ram_used_mb is not None:
            print(f"RAM  Used: {session.avg_ram_used_mb / 1024:.1f} GB")

        if session.avg_emulator_cpu is not None:
            print(f"Emulator  CPU: {session.avg_emulator_cpu:.1f}%  RAM: {session.avg_emulator_ram_mb:.0f} MB")

        if session.bottleneck:
            print()
            print(f"Bottleneck: {session.bottleneck.bottleneck.value} ({session.bottleneck.confidence}% confidence)")
            for ev in session.bottleneck.evidence[:3]:
                print(f"  {ev}")

        print()
        print("=" * 50)
        return 0

    if "--recommendations" in sys.argv:
        from app.core.recommendation_engine import recommendation_engine
        from app.performance.realtime_telemetry import RealtimeTelemetry
        from app.performance.presentmon_provider import PresentMonProvider
        from app.core.optimizer import optimizer
        import time as _time

        duration = 15
        for i, arg in enumerate(sys.argv):
            if arg == "--duration" and i + 1 < len(sys.argv):
                try:
                    duration = int(sys.argv[i + 1])
                except ValueError:
                    pass

        print("=" * 55)
        print("HEAVEN SOCIETY — PERFORMANCE ASSESSMENT")
        print("=" * 55)
        print(f"Collecting telemetry for {duration}s...")
        print()

        # Detect target
        from app.emulator.detector import emulator_detector
        emus = emulator_detector.detect_all()
        target_pid = 0
        target_name = ""
        if emus:
            emu = emus[0]
            target_pid = getattr(emu, 'pid', 0) or 0
            target_name = getattr(emu, 'process_name', '') or getattr(emu, 'name', 'Emulator')

        # Create telemetry engine
        engine = RealtimeTelemetry(
            interval_ms=500,
            max_samples=duration * 2 + 10,
        )

        # Try PresentMon
        pm = PresentMonProvider()
        pm_available, _ = pm.is_available()
        if pm_available and target_name:
            pm.start(target_process=target_name, duration=duration + 5)
            if pm.is_running():
                engine.set_fps_provider(pm)

        # Collect telemetry
        session = engine.start_session(target_name, target_pid)

        print(f"Collecting ", end="", flush=True)
        try:
            for _ in range(duration):
                _time.sleep(1)
                print(".", end="", flush=True)
        except KeyboardInterrupt:
            print("\nInterrupted.")
        finally:
            engine.stop_session()
            if pm.is_running():
                pm.stop()
        print()
        print()

        # Get bottleneck
        bottleneck = engine.get_bottleneck()
        samples = engine.recent_snapshots()

        # Get optimization states
        opt_status = optimizer.get_current_status()
        states = {}
        for opt in opt_status.get("optimizations", []):
            states[opt["id"]] = opt.get("status", "UNKNOWN")

        # Run recommendation engine
        rec_session = recommendation_engine.analyze(
            samples=samples,
            bottleneck_type=bottleneck.bottleneck,
            bottleneck_confidence=bottleneck.confidence,
            bottleneck_evidence=bottleneck.evidence,
            optimization_states=states,
            target_name=target_name,
            target_pid=target_pid,
            duration_seconds=duration,
        )

        print(recommendation_engine.format_session(rec_session))
        return 0

    if "--adaptive-status" in sys.argv:
        from app.core.adaptive_optimizer import adaptive_optimizer
        from app.performance.realtime_telemetry import RealtimeTelemetry
        from app.performance.presentmon_provider import PresentMonProvider
        from app.core.optimizer import optimizer
        import time as _time

        duration = 10
        for i, arg in enumerate(sys.argv):
            if arg == "--duration" and i + 1 < len(sys.argv):
                try:
                    duration = int(sys.argv[i + 1])
                except ValueError:
                    pass

        print("Collecting telemetry...", flush=True)

        # Detect target
        from app.emulator.detector import emulator_detector
        emus = emulator_detector.detect_all()
        target_pid = 0
        target_name = ""
        if emus:
            emu = emus[0]
            target_pid = getattr(emu, 'pid', 0) or 0
            target_name = getattr(emu, 'process_name', '') or getattr(emu, 'name', 'Emulator')

        engine = RealtimeTelemetry(interval_ms=500, max_samples=duration * 2 + 10)

        pm = PresentMonProvider()
        pm_available, _ = pm.is_available()
        if pm_available and target_name:
            pm.start(target_process=target_name, duration=duration + 5)
            if pm.is_running():
                engine.set_fps_provider(pm)

        session = engine.start_session(target_name, target_pid)
        try:
            for _ in range(duration):
                _time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            engine.stop_session()
            if pm.is_running():
                pm.stop()

        samples = engine.recent_snapshots()
        state, confidence, evidence = adaptive_optimizer.classify_state(samples)

        opt_status = optimizer.get_current_status()
        states = {o["id"]: o.get("status", "UNKNOWN") for o in opt_status.get("optimizations", [])}

        is_admin = False
        try:
            from app.utils.admin import is_admin as check_admin
            is_admin = check_admin()
        except Exception:
            pass

        plan = adaptive_optimizer.generate_plan(
            samples=samples, state=state, state_confidence=confidence,
            state_evidence=evidence, optimization_states=states,
            target_name=target_name, target_pid=target_pid, is_admin=is_admin,
        )

        print(adaptive_optimizer.format_status(plan))
        return 0

    if "--adaptive-plan" in sys.argv:
        from app.core.adaptive_optimizer import adaptive_optimizer
        from app.performance.realtime_telemetry import RealtimeTelemetry
        from app.performance.presentmon_provider import PresentMonProvider
        from app.core.optimizer import optimizer
        import time as _time

        duration = 10
        for i, arg in enumerate(sys.argv):
            if arg == "--duration" and i + 1 < len(sys.argv):
                try:
                    duration = int(sys.argv[i + 1])
                except ValueError:
                    pass

        print("Collecting telemetry for plan...", flush=True)

        from app.emulator.detector import emulator_detector
        emus = emulator_detector.detect_all()
        target_pid = 0
        target_name = ""
        if emus:
            emu = emus[0]
            target_pid = getattr(emu, 'pid', 0) or 0
            target_name = getattr(emu, 'process_name', '') or getattr(emu, 'name', 'Emulator')

        engine = RealtimeTelemetry(interval_ms=500, max_samples=duration * 2 + 10)
        pm = PresentMonProvider()
        pm_available, _ = pm.is_available()
        if pm_available and target_name:
            pm.start(target_process=target_name, duration=duration + 5)
            if pm.is_running():
                engine.set_fps_provider(pm)

        session = engine.start_session(target_name, target_pid)
        try:
            for _ in range(duration):
                _time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            engine.stop_session()
            if pm.is_running():
                pm.stop()

        samples = engine.recent_snapshots()
        state, confidence, evidence = adaptive_optimizer.classify_state(samples)

        opt_status = optimizer.get_current_status()
        states = {o["id"]: o.get("status", "UNKNOWN") for o in opt_status.get("optimizations", [])}

        is_admin = False
        try:
            from app.utils.admin import is_admin as check_admin
            is_admin = check_admin()
        except Exception:
            pass

        plan = adaptive_optimizer.generate_plan(
            samples=samples, state=state, state_confidence=confidence,
            state_evidence=evidence, optimization_states=states,
            target_name=target_name, target_pid=target_pid, is_admin=is_admin,
        )

        print(adaptive_optimizer.format_plan(plan))
        return 0

    if "--adaptive-optimize" in sys.argv:
        from app.core.adaptive_optimizer import adaptive_optimizer
        from app.performance.realtime_telemetry import RealtimeTelemetry
        from app.performance.presentmon_provider import PresentMonProvider
        from app.core.optimizer import optimizer
        import time as _time

        profile_id = "gaming"
        duration = 10
        for i, arg in enumerate(sys.argv):
            if arg == "--profile" and i + 1 < len(sys.argv):
                profile_id = sys.argv[i + 1]
            if arg == "--duration" and i + 1 < len(sys.argv):
                try:
                    duration = int(sys.argv[i + 1])
                except ValueError:
                    pass

        print("=" * 55)
        print("HEAVEN SOCIETY — ADAPTIVE OPTIMIZATION")
        print("=" * 55)
        print(f"Profile: {profile_id.upper()}  Duration: {duration}s")
        print()

        from app.emulator.detector import emulator_detector
        emus = emulator_detector.detect_all()
        target_pid = 0
        target_name = ""
        if emus:
            emu = emus[0]
            target_pid = getattr(emu, 'pid', 0) or 0
            target_name = getattr(emu, 'process_name', '') or getattr(emu, 'name', 'Emulator')
            print(f"TARGET: {target_name} PID: {target_pid}")
        else:
            print("TARGET: No emulator detected")
        print()

        engine = RealtimeTelemetry(interval_ms=500, max_samples=duration * 2 + 10)
        pm = PresentMonProvider()
        pm_available, _ = pm.is_available()
        if pm_available and target_name:
            pm.start(target_process=target_name, duration=duration + 5)
            if pm.is_running():
                engine.set_fps_provider(pm)

        session = engine.start_session(target_name, target_pid)
        print(f"Collecting baseline telemetry ({duration}s)...", flush=True)
        try:
            for _ in range(duration):
                _time.sleep(1)
                print(".", end="", flush=True)
        except KeyboardInterrupt:
            pass
        finally:
            engine.stop_session()
            if pm.is_running():
                pm.stop()
        print()

        samples = engine.recent_snapshots()
        state, confidence, evidence = adaptive_optimizer.classify_state(samples)
        state_str = state.value.replace("_", " ").title()
        print(f"STATE: {state_str} ({confidence}% confidence)")

        opt_status = optimizer.get_current_status()
        states = {o["id"]: o.get("status", "UNKNOWN") for o in opt_status.get("optimizations", [])}

        is_admin = False
        try:
            from app.utils.admin import is_admin as check_admin
            is_admin = check_admin()
        except Exception:
            pass

        plan = adaptive_optimizer.generate_plan(
            samples=samples, state=state, state_confidence=confidence,
            state_evidence=evidence, optimization_states=states,
            profile_id=profile_id, target_name=target_name,
            target_pid=target_pid, is_admin=is_admin,
        )

        # Execute plan
        print("\nExecuting plan...")
        plan = adaptive_optimizer.execute_plan(plan)

        applied = [a for a in plan.actions if a.status.value == "APPLIED"]
        optimal = [a for a in plan.actions if a.status.value == "ALREADY_OPTIMAL"]
        admin = [a for a in plan.actions if a.status.value == "REQUIRES_ADMIN"]
        failed = [a for a in plan.actions if a.status.value == "FAILED"]
        rec_only = [a for a in plan.actions if a.status.value == "RECOMMENDATION_ONLY"]

        print(f"\nRESULTS")
        print(f"  Applied:    {len(applied)}")
        print(f"  Optimal:    {len(optimal)}")
        print(f"  Admin:      {len(admin)}")
        print(f"  Failed:     {len(failed)}")
        print(f"  Review:     {len(rec_only)}")

        for a in applied:
            print(f"  ✓ {a.optimization_name}: {a.reason}")
        for a in admin:
            print(f"  ! {a.optimization_name}: {a.reason}")
        for a in rec_only:
            print(f"  • {a.optimization_name}: {a.reason}")

        print()
        print("=" * 55)
        return 0

    if "--input-diagnostics" in sys.argv:
        from app.input.input_diagnostics import run_input_diagnostics, format_input_status
        from app.core.optimizer import optimizer

        opt_status = optimizer.get_current_status()
        target_name = opt_status.get("target_name", "")
        target_pid = opt_status.get("target_pid", 0)

        session = run_input_diagnostics(target_name=target_name, target_pid=target_pid)
        print(format_input_status(session))
        return 0

    if "--input-test" in sys.argv:
        from app.input.input_diagnostics import (
            PollingMeasurementSession, detect_pointing_devices,
            detect_pointer_config, InputDiagnosticSession,
        )
        import time as _time
        import uuid as _uuid

        duration = 5
        for i, arg in enumerate(sys.argv):
            if arg == "--duration" and i + 1 < len(sys.argv):
                try:
                    duration = int(sys.argv[i + 1])
                except ValueError:
                    pass

        print("=" * 55)
        print("HEAVEN SOCIETY — INPUT POLLING TEST")
        print("=" * 55)
        print(f"Duration: {duration}s  |  Move your mouse during measurement")
        print()

        # Measure polling
        print("Measuring mouse event rate...")
        poll_session = PollingMeasurementSession(duration_seconds=duration)
        polling = poll_session.measure()
        print()

        # Pointer config
        pointer = detect_pointer_config()

        print("RESULTS")
        print("-" * 55)
        if polling.state.value == "MEASURED":
            print(f"  Events Captured:   {polling.total_events}")
            print(f"  Observed Rate:    {polling.observed_rate_hz:.0f} Hz")
            print(f"  Median Interval:  {polling.median_interval_ms:.2f} ms")
            print(f"  Std Deviation:    {polling.interval_std_dev_ms:.2f} ms")
            print(f"  CV:               {polling.coefficient_of_variation:.3f}")
            print(f"  Consistency:      {polling.consistency.value}")
        else:
            print(f"  Status:           {polling.state.value}")
            print(f"  Note:             {polling.note}")
        print()
        epp = "ENABLED" if pointer.enhance_pointer_precision else "DISABLED"
        print(f"  Pointer Precision: {epp}")
        print(f"  Pointer Speed:    {pointer.pointer_speed}/11")
        print()
        print("=" * 55)
        return 0

    if "--input-latency" in sys.argv:
        from app.input.input_diagnostics import estimate_input_latency
        from app.input.latency import latency_diagnostics
        from app.system.display import display_monitor

        display = display_monitor.detect()
        report = latency_diagnostics.diagnose(
            display_refresh_hz=display.refresh_rate_hz,
        )
        estimate = estimate_input_latency(
            display_refresh_hz=display.refresh_rate_hz,
        )

        print("=" * 55)
        print("HEAVEN SOCIETY — INPUT LATENCY DIAGNOSTICS")
        print("=" * 55)
        print()
        print(f"  Display Refresh:      {display.refresh_rate_hz} Hz")
        print(f"  Display Latency:      {report.estimated_display_latency_ms:.1f} ms (frame interval)")
        print(f"  Scheduling Latency:   {estimate.scheduling_latency_ms:.1f} ms (estimated)")
        print(f"  Estimated Total:      {estimate.estimated_total_ms:.1f} ms")
        print()
        print(f"  NOTE: {estimate.note}")
        print()
        separation = latency_diagnostics.separate_settings_from_reality()
        print("  Settings (measurable):")
        for item in separation["input_settings"]["includes"]:
            print(f"    - {item}")
        print()
        print(f"  Actual Latency: {separation['actual_latency']['note']}")
        print()
        print("=" * 55)
        return 0

    if "--gameplay-diagnostics" in sys.argv:
        from app.input.input_diagnostics import run_input_diagnostics
        from app.input.gameplay_diagnostics import run_gameplay_diagnostics, format_gameplay_diagnostics
        from app.performance.realtime_telemetry import RealtimeTelemetry
        from app.performance.presentmon_provider import PresentMonProvider
        from app.core.optimizer import optimizer
        import time as _time

        duration = 10
        for i, arg in enumerate(sys.argv):
            if arg == "--duration" and i + 1 < len(sys.argv):
                try:
                    duration = int(sys.argv[i + 1])
                except ValueError:
                    pass

        # Detect target
        from app.emulator.detector import emulator_detector
        emus = emulator_detector.detect_all()
        target_pid = 0
        target_name = ""
        if emus:
            emu = emus[0]
            target_pid = getattr(emu, 'pid', 0) or 0
            target_name = getattr(emu, 'process_name', '') or getattr(emu, 'name', 'Emulator')

        # Collect telemetry
        engine = RealtimeTelemetry(interval_ms=500, max_samples=duration * 2 + 10)
        pm = PresentMonProvider()
        pm_available, _ = pm.is_available()
        if pm_available and target_name:
            pm.start(target_process=target_name, duration=duration + 5)
            if pm.is_running():
                engine.set_fps_provider(pm)

        print(f"Collecting gameplay telemetry ({duration}s)...", flush=True)
        session = engine.start_session(target_name, target_pid)
        try:
            for _ in range(duration):
                _time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            engine.stop_session()
            if pm.is_running():
                pm.stop()

        samples = engine.recent_snapshots()

        # Run input diagnostics
        opt_status = optimizer.get_current_status()
        input_session = run_input_diagnostics(
            target_name=target_name, target_pid=target_pid,
        )

        # Run gameplay diagnostics
        gameplay = run_gameplay_diagnostics(
            samples=samples, input_session=input_session,
            target_name=target_name, target_pid=target_pid,
        )

        print(format_gameplay_diagnostics(gameplay))
        return 0

    if "--sensitivity-analysis" in sys.argv:
        from app.input.gameplay_diagnostics import (
            SensitivityData, SensitivityDataType, analyze_sensitivity,
        )

        # Parse user-provided values
        data = SensitivityData(data_type=SensitivityDataType.USER_REPORTED)
        for i, arg in enumerate(sys.argv):
            if arg == "--dpi" and i + 1 < len(sys.argv):
                try:
                    data.dpi = int(sys.argv[i + 1])
                except ValueError:
                    pass
            if arg == "--sens" and i + 1 < len(sys.argv):
                try:
                    data.general_sensitivity = int(sys.argv[i + 1])
                except ValueError:
                    pass
            if arg == "--red-dot" and i + 1 < len(sys.argv):
                try:
                    data.red_dot = int(sys.argv[i + 1])
                except ValueError:
                    pass
            if arg == "--2x" and i + 1 < len(sys.argv):
                try:
                    data.scope_2x = int(sys.argv[i + 1])
                except ValueError:
                    pass
            if arg == "--4x" and i + 1 < len(sys.argv):
                try:
                    data.scope_4x = int(sys.argv[i + 1])
                except ValueError:
                    pass
            if arg == "--sniper" and i + 1 < len(sys.argv):
                try:
                    data.sniper = int(sys.argv[i + 1])
                except ValueError:
                    pass

        analysis = analyze_sensitivity(data)

        print("=" * 55)
        print("HEAVEN SOCIETY — SENSITIVITY ANALYSIS")
        print("=" * 55)
        print()
        print("  Data Type: USER_REPORTED (not measured)")
        print()
        if data.dpi:
            print(f"  DPI:                 {data.dpi}")
        if data.general_sensitivity:
            print(f"  General Sensitivity: {data.general_sensitivity}")
        if data.red_dot:
            print(f"  Red Dot:             {data.red_dot}")
        if data.scope_2x:
            print(f"  2x Scope:            {data.scope_2x}")
        if data.scope_4x:
            print(f"  4x Scope:            {data.scope_4x}")
        if data.sniper:
            print(f"  Sniper:              {data.sniper}")
        print()

        if analysis.effective_dpi:
            print(f"  Effective DPI:       {analysis.effective_dpi:.0f}")
        if analysis.cm_per_360:
            print(f"  Est. cm/360:         {analysis.cm_per_360:.1f} cm")
        if analysis.scope_scaling:
            print(f"\n  Scope Scaling:")
            for name, scale in analysis.scope_scaling.items():
                print(f"    {name:12s}  ×{scale:.2f}")
        if analysis.warnings:
            print(f"\n  WARNINGS:")
            for w in analysis.warnings:
                print(f"    ⚠ {w}")
        if analysis.recommendations:
            print(f"\n  NOTES:")
            for r in analysis.recommendations:
                print(f"    {r}")
        print()
        print("=" * 55)
        return 0

    if "--input-report" in sys.argv:
        from app.input.input_diagnostics import run_input_diagnostics, format_input_status
        from app.input.gameplay_diagnostics import run_gameplay_diagnostics, format_gameplay_diagnostics
        from app.core.optimizer import optimizer
        from app.performance.realtime_telemetry import RealtimeTelemetry
        from app.performance.presentmon_provider import PresentMonProvider
        import time as _time
        import json as _json
        import os as _os

        duration = 10
        for i, arg in enumerate(sys.argv):
            if arg == "--duration" and i + 1 < len(sys.argv):
                try:
                    duration = int(sys.argv[i + 1])
                except ValueError:
                    pass

        # Detect target
        from app.emulator.detector import emulator_detector
        emus = emulator_detector.detect_all()
        target_pid = 0
        target_name = ""
        if emus:
            emu = emus[0]
            target_pid = getattr(emu, 'pid', 0) or 0
            target_name = getattr(emu, 'process_name', '') or getattr(emu, 'name', 'Emulator')

        print(f"Collecting data ({duration}s)...", flush=True)
        engine = RealtimeTelemetry(interval_ms=500, max_samples=duration * 2 + 10)
        pm = PresentMonProvider()
        pm_available, _ = pm.is_available()
        if pm_available and target_name:
            pm.start(target_process=target_name, duration=duration + 5)
            if pm.is_running():
                engine.set_fps_provider(pm)

        session = engine.start_session(target_name, target_pid)
        try:
            for _ in range(duration):
                _time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            engine.stop_session()
            if pm.is_running():
                pm.stop()

        samples = engine.recent_snapshots()
        input_session = run_input_diagnostics(target_name=target_name, target_pid=target_pid)
        gameplay = run_gameplay_diagnostics(
            samples=samples, input_session=input_session,
            target_name=target_name, target_pid=target_pid,
        )

        print(format_input_status(input_session))
        print(format_gameplay_diagnostics(gameplay))

        # Save report
        report = gameplay.to_dict()
        report["input"] = input_session.to_dict()
        report_path = _os.path.join("reports", f"input_report_{gameplay.session_id}.json")
        _os.makedirs("reports", exist_ok=True)
        with open(report_path, "w") as f:
            _json.dump(report, f, indent=2)
        print(f"Report saved: {report_path}")
        return 0

    if "--responsiveness-status" in sys.argv:
        from app.input.responsiveness_analyzer import analyze_responsiveness, format_responsiveness
        from app.input.input_diagnostics import run_input_diagnostics
        from app.performance.realtime_telemetry import RealtimeTelemetry
        from app.performance.presentmon_provider import PresentMonProvider
        from app.core.optimizer import optimizer
        import time as _time

        duration = 5
        for i, arg in enumerate(sys.argv):
            if arg == "--duration" and i + 1 < len(sys.argv):
                try:
                    duration = int(sys.argv[i + 1])
                except ValueError:
                    pass

        # Detect target
        from app.emulator.detector import emulator_detector
        emus = emulator_detector.detect_all()
        target_pid = 0
        target_name = ""
        if emus:
            emu = emus[0]
            target_pid = getattr(emu, 'pid', 0) or 0
            target_name = getattr(emu, 'process_name', '') or getattr(emu, 'name', 'Emulator')

        # Collect telemetry
        engine = RealtimeTelemetry(interval_ms=500, max_samples=duration * 2 + 10)
        pm = PresentMonProvider()
        pm_available, _ = pm.is_available()
        if pm_available and target_name:
            pm.start(target_process=target_name, duration=duration + 5)
            if pm.is_running():
                engine.set_fps_provider(pm)

        session = engine.start_session(target_name, target_pid)
        try:
            for _ in range(duration):
                _time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            engine.stop_session()
            if pm.is_running():
                pm.stop()

        samples = engine.recent_snapshots()
        input_session = run_input_diagnostics(target_name=target_name, target_pid=target_pid)
        result = analyze_responsiveness(
            samples=samples, input_session=input_session,
            target_name=target_name, target_pid=target_pid,
            duration_seconds=duration,
        )
        print(format_responsiveness(result))
        return 0

    if "--responsiveness-test" in sys.argv:
        from app.input.responsiveness_analyzer import analyze_responsiveness, format_responsiveness
        from app.input.input_diagnostics import run_input_diagnostics, PollingMeasurementSession
        from app.performance.realtime_telemetry import RealtimeTelemetry
        from app.performance.presentmon_provider import PresentMonProvider
        import time as _time
        import threading as _threading

        duration = 10
        for i, arg in enumerate(sys.argv):
            if arg == "--duration" and i + 1 < len(sys.argv):
                try:
                    duration = int(sys.argv[i + 1])
                except ValueError:
                    pass

        print("=" * 55)
        print("HEAVEN SOCIETY — RESPONSIVENESS TEST")
        print("=" * 55)
        print(f"Duration: {duration}s  |  Move mouse during measurement")
        print()

        # Detect target
        from app.emulator.detector import emulator_detector
        emus = emulator_detector.detect_all()
        target_pid = 0
        target_name = ""
        if emus:
            emu = emus[0]
            target_pid = getattr(emu, 'pid', 0) or 0
            target_name = getattr(emu, 'process_name', '') or getattr(emu, 'name', 'Emulator')
            print(f"TARGET: {target_name} PID: {target_pid}")
        else:
            print("TARGET: No emulator detected")
        print()

        # Start polling measurement in parallel
        poll_session = PollingMeasurementSession(duration_seconds=duration)
        poll_thread = _threading.Thread(target=poll_session.measure, daemon=True)
        poll_thread.start()

        # Collect telemetry
        engine = RealtimeTelemetry(interval_ms=500, max_samples=duration * 2 + 10)
        pm = PresentMonProvider()
        pm_available, _ = pm.is_available()
        if pm_available and target_name:
            pm.start(target_process=target_name, duration=duration + 5)
            if pm.is_running():
                engine.set_fps_provider(pm)

        print(f"Collecting ({duration}s)... ", end="", flush=True)
        telem_session = engine.start_session(target_name, target_pid)
        try:
            for _ in range(duration):
                _time.sleep(1)
                print(".", end="", flush=True)
        except KeyboardInterrupt:
            pass
        finally:
            engine.stop_session()
            if pm.is_running():
                pm.stop()
        print()

        # Wait for polling
        poll_thread.join(timeout=2)

        samples = engine.recent_snapshots()
        input_session = run_input_diagnostics(target_name=target_name, target_pid=target_pid)
        # Attach actual polling measurement
        input_session.polling = poll_session.measure()

        result = analyze_responsiveness(
            samples=samples, input_session=input_session,
            target_name=target_name, target_pid=target_pid,
            duration_seconds=duration,
        )
        print(format_responsiveness(result))
        return 0

    if "--responsiveness-report" in sys.argv:
        from app.input.responsiveness_analyzer import analyze_responsiveness, format_responsiveness
        from app.input.input_diagnostics import run_input_diagnostics
        from app.performance.realtime_telemetry import RealtimeTelemetry
        from app.performance.presentmon_provider import PresentMonProvider
        import time as _time
        import json as _json
        import os as _os

        duration = 30
        for i, arg in enumerate(sys.argv):
            if arg == "--duration" and i + 1 < len(sys.argv):
                try:
                    duration = int(sys.argv[i + 1])
                except ValueError:
                    pass

        # Detect target
        from app.emulator.detector import emulator_detector
        emus = emulator_detector.detect_all()
        target_pid = 0
        target_name = ""
        if emus:
            emu = emus[0]
            target_pid = getattr(emu, 'pid', 0) or 0
            target_name = getattr(emu, 'process_name', '') or getattr(emu, 'name', 'Emulator')

        print(f"Collecting data ({duration}s)...", flush=True)
        engine = RealtimeTelemetry(interval_ms=500, max_samples=duration * 2 + 10)
        pm = PresentMonProvider()
        pm_available, _ = pm.is_available()
        if pm_available and target_name:
            pm.start(target_process=target_name, duration=duration + 5)
            if pm.is_running():
                engine.set_fps_provider(pm)

        session = engine.start_session(target_name, target_pid)
        try:
            for _ in range(duration):
                _time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            engine.stop_session()
            if pm.is_running():
                pm.stop()

        samples = engine.recent_snapshots()
        input_session = run_input_diagnostics(target_name=target_name, target_pid=target_pid)
        result = analyze_responsiveness(
            samples=samples, input_session=input_session,
            target_name=target_name, target_pid=target_pid,
            duration_seconds=duration,
        )

        print(format_responsiveness(result))

        # Save report
        report_path = _os.path.join("reports", f"responsiveness_{result.session_id}.json")
        _os.makedirs("reports", exist_ok=True)
        with open(report_path, "w") as f:
            _json.dump(result.to_dict(), f, indent=2)
        print(f"Report saved: {report_path}")
        return 0

    if "--optimization-status" in sys.argv:
        from app.core.optimization_executor import optimization_executor
        status = optimization_executor.get_status()

        print("=" * 55)
        print("HEAVEN SOCIETY — OPTIMIZATION STATUS")
        print("=" * 55)

        print(f"\n  Busy: {status['busy']}")
        print(f"  Session History: {status['history_count']}")

        if status["last_session"]:
            ls = status["last_session"]
            print(f"\nLAST SESSION")
            print(f"  ID:          {ls['session_id']}")
            print(f"  Profile:     {ls['profile_name'] or ls['profile_id']}")
            print(f"  Target:      {ls['target_name'] or 'None'} PID {ls['target_pid']}")
            print(f"  Status:      {ls['status']}")
            print(f"  Duration:    {ls['duration_seconds']:.1f}s")
            print(f"  Applied:     {ls['applied_count']}")
            print(f"  Kept:        {ls['kept_count']}")
            print(f"  Rolled Back: {ls['rolled_back_count']}")
            print(f"  Failed:      {ls['failed_count']}")
            print(f"  Admin Req:   {ls['admin_required_count']}")
            print(f"  Optimal:     {ls['already_optimal_count']}")
            print(f"  Recommend:   {ls['recommendation_only_count']}")
        else:
            print(f"\n  No session recorded.")

        print("\n" + "=" * 55)
        print("STATUS COMPLETE")
        print("=" * 55)
        return 0

    if "--optimize-preview" in sys.argv:
        from app.core.optimization_executor import optimization_executor
        profile_id = "gaming"
        for i, arg in enumerate(sys.argv):
            if arg == "--profile" and i + 1 < len(sys.argv):
                profile_id = sys.argv[i + 1]

        session = optimization_executor.preview(profile_id=profile_id)
        print(optimization_executor.format_preview(session))
        return 0

    if "--optimize-auto" in sys.argv:
        from app.core.optimization_executor import optimization_executor
        profile_id = "gaming"
        for i, arg in enumerate(sys.argv):
            if arg == "--profile" and i + 1 < len(sys.argv):
                profile_id = sys.argv[i + 1]

        # Detect thermal state
        thermal_state = "UNKNOWN"
        try:
            from app.system.gpu import gpu_monitor
            gpus = gpu_monitor.detect()
            if gpus and gpus[0].vendor == "NVIDIA":
                g = gpu_monitor.update_nvidia(gpus[0])
                if g.temperature_celsius:
                    if g.temperature_celsius >= 90:
                        thermal_state = "THROTTLING_RISK"
                    elif g.temperature_celsius >= 80:
                        thermal_state = "HOT"
                    elif g.temperature_celsius >= 70:
                        thermal_state = "WARM"
                    else:
                        thermal_state = "NORMAL"
        except Exception:
            pass

        session = optimization_executor.execute(
            profile_id=profile_id,
            thermal_state=thermal_state,
        )
        print(session.format_cli())
        return 0

    if "--optimize-verify" in sys.argv:
        from app.core.optimization_executor import optimization_executor
        result = optimization_executor.verify_session()

        print("=" * 55)
        print("HEAVEN SOCIETY — OPTIMIZATION VERIFICATION")
        print("=" * 55)

        print(f"\n  Status: {result['status']}")
        if "session_status" in result:
            print(f"  Session: {result['session_status']}")

        if "results" in result:
            print(f"\n  OPTIMIZATIONS")
            print("-" * 55)
            for opt_id, info in result["results"].items():
                icon = "[OK]" if info["verified"] else "[XX]"
                print(f"  {icon} {info['name']}: {info['status']}")

        print("\n" + "=" * 55)
        print("VERIFICATION COMPLETE")
        print("=" * 55)
        return 0

    if "--optimize-rollback" in sys.argv:
        from app.core.optimization_executor import optimization_executor
        result = optimization_executor.rollback_last()

        print("=" * 55)
        print("HEAVEN SOCIETY — OPTIMIZATION ROLLBACK")
        print("=" * 55)

        print(f"\n  Success: {result.success}")
        print(f"  Message: {result.message}")
        if result.restored_entries:
            print(f"\n  RESTORED")
            for entry in result.restored_entries:
                print(f"    [OK] {entry}")
        if result.failed_entries:
            print(f"\n  FAILED")
            for entry in result.failed_entries:
                print(f"    [XX] {entry}")

        print("\n" + "=" * 55)
        print("ROLLBACK COMPLETE")
        print("=" * 55)
        return 0

    if "--optimize-engine-run" in sys.argv:
        from app.core.optimization_engine import optimization_engine
        profile_id = "gaming"
        mode = "auto"
        for i, arg in enumerate(sys.argv):
            if arg == "--profile" and i + 1 < len(sys.argv):
                profile_id = sys.argv[i + 1]
            if arg == "--mode" and i + 1 < len(sys.argv):
                mode = sys.argv[i + 1]

        result = optimization_engine.run(profile_id=profile_id, mode=mode)
        print(result.format_cli())
        return 0

    if "--optimize-engine-dry-run" in sys.argv:
        from app.core.optimization_engine import optimization_engine
        profile_id = "gaming"
        for i, arg in enumerate(sys.argv):
            if arg == "--profile" and i + 1 < len(sys.argv):
                profile_id = sys.argv[i + 1]

        result = optimization_engine.run(profile_id=profile_id, mode="dry_run")
        print(result.format_cli())
        return 0

    if "--optimize-engine-status" in sys.argv:
        from app.core.optimization_engine import optimization_engine
        status = optimization_engine.get_status()

        print("=" * 55)
        print("HEAVEN SOCIETY — OPTIMIZATION ENGINE STATUS")
        print("=" * 55)
        print(f"\n  Busy:   {status.is_busy}")
        print(f"  Phase:  {status.current_phase}")
        print(f"  Admin:  {status.is_admin}")
        print(f"  Target: {status.target_name or 'None'} PID {status.target_pid}")
        print(f"  History: {status.history_count} runs")

        if status.last_run:
            lr = status.last_run
            print(f"\nLAST RUN")
            print(f"  ID:       {lr['run_id']}")
            print(f"  Profile:  {lr['profile_name'] or lr['profile_id']}")
            print(f"  Target:   {lr['target_name'] or 'None'} PID {lr['target_pid']}")
            print(f"  Verdict:  {lr['verdict']}")
            print(f"  Duration: {lr['duration_seconds']:.1f}s")
            print(f"  Applied:  {lr['applied_count']}")
            print(f"  Kept:     {lr['kept_count']}")
            print(f"  Rolled:   {lr['rolled_back_count']}")
            print(f"  Failed:   {lr['failed_count']}")
        else:
            print(f"\n  No run recorded.")

        print("\n" + "=" * 55)
        return 0

    if "--optimize-engine-rollback" in sys.argv:
        from app.core.optimization_engine import optimization_engine
        result = optimization_engine.rollback_last()

        print("=" * 55)
        print("HEAVEN SOCIETY — OPTIMIZATION ENGINE ROLLBACK")
        print("=" * 55)
        print(f"\n  Success: {result['success']}")
        print(f"  Message: {result['message']}")
        print("\n" + "=" * 55)
        return 0

    if "--optimize-engine-history" in sys.argv:
        from app.core.optimization_engine import optimization_engine
        count = 10
        for i, arg in enumerate(sys.argv):
            if arg == "--count" and i + 1 < len(sys.argv):
                try:
                    count = int(sys.argv[i + 1])
                except ValueError:
                    pass

        history = optimization_engine.load_history(count)

        print("=" * 55)
        print("HEAVEN SOCIETY — OPTIMIZATION ENGINE HISTORY")
        print("=" * 55)
        print(f"\n  Recent runs: {len(history)}")
        print("")

        for run in history:
            print(f"  {run.get('run_id', 'N/A')}  {run.get('profile_name', run.get('profile_id', 'N/A'))}")
            print(f"    Verdict: {run.get('verdict', 'N/A')}  Target: {run.get('target_name', 'N/A')}")
            print(f"    Applied: {run.get('kept_count', 0)}  Rolled back: {run.get('rolled_back_count', 0)}  Failed: {run.get('failed_count', 0)}")
            print(f"    Duration: {run.get('duration_seconds', 0):.1f}s")
            print("")

        print("=" * 55)
        return 0

    if "--gaming-opt-status" in sys.argv:
        from app.core.gaming_optimization import gaming_session_manager
        summary = gaming_session_manager.get_ui_summary()

        print("=" * 55)
        print("HEAVEN SOCIETY — GAMING OPTIMIZATION STATUS")
        print("=" * 55)
        print(f"\n  State:    {summary['state']}")
        print(f"  Target:   {summary['target_name'] or 'None'} PID {summary['target_pid']}")
        print(f"  Duration: {summary['duration_seconds']:.0f}s")
        print(f"  Ticks:    {summary['total_ticks']}")
        print(f"  Applied:  {summary['optimizations_applied']}")
        print("")

        if summary['baseline_cpu'] is not None:
            print("  BASELINE")
            print(f"    CPU: {summary['baseline_cpu']:.1f}%  GPU: {summary['baseline_gpu'] or 0:.1f}%  RAM: {summary['baseline_ram'] or 0:.1f}%")
            if summary['baseline_fps'] is not None:
                print(f"    FPS: {summary['baseline_fps']:.1f}")
            print("")

        print("  CURRENT")
        if summary['cpu'] is not None:
            print(f"    CPU: {summary['cpu']:.1f}%  GPU: {summary['gpu'] or 0:.1f}%  RAM: {summary['ram'] or 0:.1f}%")
        if summary['fps'] is not None:
            print(f"    FPS: {summary['fps']:.1f}  Frame: {summary['frame_time'] or 0:.1f}ms")
        if summary['gpu_temp'] is not None:
            print(f"    GPU Temp: {summary['gpu_temp']:.0f}°C")

        print("")
        print(f"  Last Action: {summary['last_action']}")
        print(f"  Last Reason: {summary['last_reason']}")
        print("\n" + "=" * 55)
        return 0

    if "--gaming-opt-start" in sys.argv:
        from app.core.gaming_optimization import gaming_session_manager
        profile_id = "gaming"
        for i, arg in enumerate(sys.argv):
            if arg == "--profile" and i + 1 < len(sys.argv):
                profile_id = sys.argv[i + 1]

        session = gaming_session_manager.start_session(profile_id=profile_id)
        print("=" * 55)
        print("HEAVEN SOCIETY — GAMING SESSION STARTED")
        print("=" * 55)
        print(f"\n  Session:  {session.session_id}")
        print(f"  Target:   {session.target_name or 'None'} PID {session.target_pid}")
        print(f"  State:    {session.state}")
        print(f"  Profile:  {profile_id}")
        print("\n" + "=" * 55)
        return 0

    if "--gaming-opt-stop" in sys.argv:
        from app.core.gaming_optimization import gaming_session_manager
        session = gaming_session_manager.stop_session()
        print(session.format_cli())
        return 0

    if "--gaming-opt-tick" in sys.argv:
        from app.core.gaming_optimization import gaming_session_manager
        ticks = 5
        for i, arg in enumerate(sys.argv):
            if arg == "--ticks" and i + 1 < len(sys.argv):
                try:
                    ticks = int(sys.argv[i + 1])
                except ValueError:
                    pass

        if not gaming_session_manager.is_active:
            gaming_session_manager.start_session()

        for i in range(ticks):
            decision = gaming_session_manager.tick()
            if decision:
                print(f"  Tick {i+1}: {decision.action.value} — {decision.reason}")
            else:
                print(f"  Tick {i+1}: no decision")
            time.sleep(2)

        summary = gaming_session_manager.get_ui_summary()
        print(f"\n  State: {summary['state']}  Ticks: {summary['total_ticks']}  Applied: {summary['optimizations_applied']}")
        return 0

    if "--gaming-opt-report" in sys.argv:
        from app.core.gaming_optimization import gaming_session_manager
        history = gaming_session_manager.load_history(5)

        print("=" * 55)
        print("HEAVEN SOCIETY — GAMING OPTIMIZATION HISTORY")
        print("=" * 55)
        print(f"\n  Recent sessions: {len(history)}")
        print("")

        for s in history:
            print(f"  {s.get('session_id', 'N/A')}  Target: {s.get('target_name', 'N/A')}")
            print(f"    Duration: {s.get('duration_seconds', 0):.0f}s  Applied: {s.get('optimizations_applied', 0)}  Ticks: {s.get('total_ticks', 0)}")
            print("")

        print("=" * 55)
        return 0

    if "--cleanup-center-scan" in sys.argv:
        from app.cleanup.cleanup_center import cleanup_center
        items = cleanup_center.scan()
        print(cleanup_center.format_scan_results())
        return 0

    if "--cleanup-center-preview" in sys.argv:
        from app.cleanup.cleanup_center import cleanup_center
        if not cleanup_center.items:
            cleanup_center.scan()
        print(cleanup_center.format_preview())
        return 0

    if "--cleanup-center-clean" in sys.argv:
        from app.cleanup.cleanup_center import cleanup_center
        mode = "safe"
        for i, arg in enumerate(sys.argv):
            if arg == "--mode" and i + 1 < len(sys.argv):
                mode = sys.argv[i + 1]

        if not cleanup_center.items:
            cleanup_center.scan()

        if mode == "safe":
            result = cleanup_center.clean_safe()
        else:
            print("Use --mode safe for automated safe cleanup.")
            print("For selective cleanup, use the GUI.")
            return 0

        print("=" * 55)
        print("HEAVEN SOCIETY — CLEANUP COMPLETE")
        print("=" * 55)
        print(f"\n  Freed:     {result.bytes_freed_display}")
        print(f"  Files:     {result.files_deleted}")
        print(f"  Success:   {result.successful_items}")
        print(f"  Failed:    {result.failed_items}")
        print(f"  Duration:  {result.duration_seconds:.1f}s")
        print(f"  Message:   {result.message}")
        print("\n" + "=" * 55)
        return 0

    if "--cleanup-center-recommend" in sys.argv:
        from app.cleanup.cleanup_center import cleanup_center
        if not cleanup_center.items:
            cleanup_center.scan()

        preview = cleanup_center.get_preview()
        recs = preview.get("recommendations", [])

        print("=" * 55)
        print("HEAVEN SOCIETY — CLEANUP RECOMMENDATIONS")
        print("=" * 55)
        print(f"\n  Disk: {preview['disk_free_gb']:.1f} GB free / {preview['disk_total_gb']:.1f} GB")
        print(f"  Pressure: {preview['disk_pressure']}")
        print(f"  Safe to clean: {preview['total_safe_display']}")
        print(f"  Review needed: {preview['total_review_display']}")
        blocked_total = sum(b.get('size', 0) for b in preview.get('blocked_items', []))
        from app.cleanup.cleanup_models import format_bytes
        print(f"  Do not touch:  {format_bytes(blocked_total)}")
        print("")

        if recs:
            print("  RECOMMENDATIONS")
            print("  " + "-" * 51)
            for rec in recs:
                print(f"    [{rec['priority']}] {rec['title']}")
                print(f"      {rec['description']}")
                print(f"      Estimated: {rec['estimated_freed_display']}")
                print("")
        else:
            print("  No cleanup recommendations at this time.")

        print("=" * 55)
        return 0

    if "--session-start" in sys.argv:
        from app.performance.gaming_session_analyzer import gaming_session_analyzer
        from app.core.emulator_controller import emulator_controller

        target = emulator_controller.detect_target()
        t_name = target.name if target else ""
        t_pid = target.pid if target else 0

        session_id = gaming_session_analyzer.start_session(
            target_name=t_name, target_pid=t_pid,
        )

        print("=" * 55)
        print("HEAVEN SOCIETY — GAMING SESSION STARTED")
        print("=" * 55)
        print(f"\n  Session:  {session_id}")
        print(f"  Target:   {t_name or 'None'} PID {t_pid}")
        print(f"\n  Session is now running.")
        print(f"  Use --session-status to check progress.")
        print(f"  Use --session-stop to end and generate report.")
        print("\n" + "=" * 55)
        return 0

    if "--session-status" in sys.argv:
        from app.performance.gaming_session_analyzer import gaming_session_analyzer
        status = gaming_session_analyzer.get_session_status()
        print(gaming_session_analyzer.format_status(status))
        return 0

    if "--session-stop" in sys.argv:
        from app.performance.gaming_session_analyzer import gaming_session_analyzer
        from app.core.emulator_controller import emulator_controller
        import time as _time

        duration = 30
        for i, arg in enumerate(sys.argv):
            if arg == "--duration" and i + 1 < len(sys.argv):
                try:
                    duration = int(sys.argv[i + 1])
                except ValueError:
                    pass

        # Auto-start if no session running
        if not gaming_session_analyzer.is_running:
            target = emulator_controller.detect_target()
            t_name = target.name if target else ""
            t_pid = target.pid if target else 0
            gaming_session_analyzer.start_session(t_name, t_pid)
            print(f"Auto-started session: {gaming_session_analyzer.session_id}")

        # Collect telemetry samples during the session
        from app.performance.realtime_telemetry import realtime_telemetry

        telemetry = realtime_telemetry
        if not telemetry.is_running:
            telemetry.start_session(
                gaming_session_analyzer._target_name,
                gaming_session_analyzer._target_pid,
            )

        print(f"Collecting {duration}s of telemetry...")
        try:
            for _ in range(duration):
                _time.sleep(1)
                sample = telemetry.latest_snapshot()
                if sample:
                    gaming_session_analyzer.ingest_sample(sample)
        except KeyboardInterrupt:
            pass

        if telemetry.is_running:
            telemetry.stop_session()

        report = gaming_session_analyzer.stop_session()
        if report:
            print(gaming_session_analyzer.format_report(report))
        else:
            print("No session to stop.")
        return 0

    # ── Phase 51: Intelligent Recommendations ──────────────────────
    if "--intelligent-recommendations" in sys.argv:
        from app.core.intelligent_recommendation import (
            intelligent_recommendation_engine,
        )
        print(intelligent_recommendation_engine.format_status())
        return 0

    if "--recommendation-history" in sys.argv:
        from app.core.intelligent_recommendation import (
            intelligent_recommendation_engine,
        )
        history = intelligent_recommendation_engine.history.get_recent(20)
        history = [e.to_dict() for e in history]
        print("\n  RECOMMENDATION HISTORY")
        print("  " + "-" * 40)
        if history:
            for h in history:
                print(f"  [{h.get('severity', '?')}] {h.get('title', '?')}")
                print(f"    Category: {h.get('category', '?')}")
                print(f"    Action: {h.get('action_taken', 'none')}")
        else:
            print("  No history available.")
        print()
        return 0

    if "--final-validation" in sys.argv:
        from app.core.validation_engine import run_final_validation

        # Parse args
        profile_id = "gaming"
        runs = 3
        duration = 10
        for i, arg in enumerate(sys.argv):
            if arg == "--profile" and i + 1 < len(sys.argv):
                profile_id = sys.argv[i + 1]
            if arg == "--duration" and i + 1 < len(sys.argv):
                try:
                    duration = int(sys.argv[i + 1])
                except ValueError:
                    pass
            if arg == "--runs" and i + 1 < len(sys.argv):
                try:
                    runs = int(sys.argv[i + 1])
                except ValueError:
                    pass

        report = run_final_validation(
            profile_id=profile_id, runs=runs, duration=duration
        )

        # Print the formatted report
        print(report.format_cli())
        return 0

    from app.utils.logger import setup_logging
    logger = setup_logging()
    logger.info("Initializing Heaven Society...")

    from app.utils.admin import is_admin
    if is_admin():
        logger.info("Running with administrator privileges")
    else:
        logger.info("Running as standard user — some optimizations limited")

    from app.core.scanner import hardware_scanner
    hardware_scanner.scan(force=True)

    from app.core.telemetry import telemetry_engine
    telemetry_engine.start()

    from app.emulator.detector import emulator_detector
    emulators = emulator_detector.detect_all()
    logger.info(f"Detected {len(emulators)} emulator(s)")

    # Detect FPS providers
    from app.performance.fps_provider import fps_registry
    providers = fps_registry.detect_available()
    for p in providers:
        logger.info(f"FPS Provider: {p['name']} — {p['status'] if 'status' in p else 'available' if p['available'] else 'unavailable'}")

    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt

    app = QApplication(sys.argv)
    app.setApplicationName("Phoenix Performance Optimizer")
    app.setApplicationVersion("1.0.0")

    from PySide6.QtGui import QFont
    font = QFont("Segoe UI", 10)
    app.setFont(font)

    from app.ui.main_window import MainWindow
    window = MainWindow()
    window.show()

    logger.info("Application started successfully")
    exit_code = app.exec()

    telemetry_engine.stop()
    from app.system.gpu import gpu_monitor
    gpu_monitor.cleanup()

    logger.info(f"Application exited with code {exit_code}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
