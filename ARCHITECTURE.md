# Heaven Society — Architecture

## Package Structure

```
app/
├── core/              Orchestration, state management, optimization logic
├── ui/                PySide6 GUI: pages, workers, theme
├── system/            Hardware monitoring: CPU, GPU, memory, thermal, display
├── performance/       Telemetry, benchmarking, FPS, frame analysis, PresentMon
├── input/             Input diagnostics, latency, gameplay analysis
├── emulator/          Emulator detection: BlueStacks, LDPlayer, MuMu, etc.
├── gaming/            Gaming lifecycle manager (Phase 61)
├── cleanup/           Disk/system cleanup engine
├── storage/           Storage intelligence and analysis
├── network/           Network analysis, jitter, ping, packet loss
└── utils/             Logger, registry, admin, commands
```

## Data Flow

```
Hardware Sensors ──→ System Monitors ──→ Telemetry Engine ──→ Telemetry Frame
                                                                    │
                              ┌─────────────────────────────────────┤
                              ↓                                     ↓
                    Analysis Modules                    UI Consumption
                    ├── BottleneckAnalyzer              ├── HomePage
                    ├── AdaptiveOptimizer               ├── MonitorPage
                    ├── RecommendationEngine             ├── OptimizerPage
                    ├── ResourceAnalyzer                 └── PerformancePage
                    ├── BackgroundAnalyzer
                    ├── HealthEngine
                    └── GamingOptimization
                              │
                              ↓
                    Optimization Engine
                    ├── Safety Gates
                    ├── Snapshot/Rollback
                    ├── Evidence Validation
                    └── Apply/Verify/Keep/Rollback
```

## State Ownership

| Owner | State | Lifetime |
|-------|-------|----------|
| `TelemetryEngine` | Live telemetry frames, history | App lifetime |
| `EmulatorController` | Target process detection, PID tracking | App lifetime |
| `OptimizationEngine` | Optimization plans, evidence sessions | Per-session |
| `GamingSessionManager` | Active gaming session, optimization decisions | Per-gaming-session |
| `GamingLifecycleManager` | Lifecycle state, changes, recommendations | Per-gaming-lifecycle |
| `RollbackManager` | Change records, undo history | Persistent (disk) |
| `SettingsManager` | User preferences, persisted config | Persistent (QSettings) |
| `NotificationManager` | Active notifications, cooldowns | App lifetime |
| `SubsystemRegistry` | Health status of all subsystems | App lifetime |

## Key Singletons

Every module below exposes a singleton instance at module level:

| Module | Singleton | Purpose |
|--------|-----------|---------|
| `core/telemetry.py` | `telemetry_engine` | Central telemetry collection |
| `core/emulator_controller.py` | `emulator_controller` | Emulator/process detection |
| `core/optimization_engine.py` | `optimization_engine` | Full optimization orchestration |
| `core/optimization_executor.py` | `optimization_executor` | Execute + verify optimizations |
| `core/optimizer.py` | `optimizer` | Simple optimization runner |
| `core/analyzer.py` | `bottleneck_analyzer` | Quick single-frame bottleneck analysis |
| `core/adaptive_optimizer.py` | `adaptive_optimizer` | Adaptive optimization decisions |
| `core/recommendation_engine.py` | `recommendation_engine` | Per-optimization recommendations |
| `core/intelligent_recommendation.py` | `intelligent_recommendation_engine` | System-wide recommendations |
| `core/health_engine.py` | `health_engine` | System health scoring (0-100) |
| `core/resource_analyzer.py` | `resource_analyzer` | Resource usage analysis |
| `core/settings.py` | `settings` | User settings |
| `core/notifications.py` | `notification_manager` | Notification management |
| `core/rollback_manager.py` | `rollback_manager` | Change tracking + undo |
| `core/snapshot.py` | `snapshot_manager` | Configuration snapshots |
| `core/rollback.py` | `rollback_engine` | Restore from snapshots |
| `core/scanner.py` | `hardware_scanner` | Hardware detection |
| `system/gpu.py` | `gpu_monitor` | GPU monitoring (NVML) |
| `system/cpu.py` | `cpu_monitor` | CPU monitoring |
| `system/memory.py` | `memory_monitor` | Memory monitoring |
| `system/thermal_monitor.py` | `thermal_diagnostics` | Thermal diagnostics |
| `system/background_analyzer.py` | `background_analyzer` | Background process analysis |
| `system/memory_optimizer.py` | `memory_optimizer` | Memory optimization |
| `performance/target_process.py` | `target_process_detector` | Target process detection |
| `performance/gpu_association.py` | `gpu_association_detector` | GPU-to-process association |
| `performance/fps_provider.py` | `fps_registry` | FPS measurement providers |
| `performance/bottleneck_analyzer.py` | (class only) | Multi-sample bottleneck correlation |
| `performance/realtime_telemetry.py` | `realtime_telemetry` | Real-time telemetry collection |
| `performance/gaming_session_analyzer.py` | `gaming_session_analyzer` | Gaming session analysis |
| `gaming/gaming_lifecycle.py` | `gaming_lifecycle` | Full gaming lifecycle orchestration |
| `cleanup/cleanup_center.py` | `cleanup_center` | Cleanup orchestration |
| `storage/storage_intelligence.py` | `storage_analyzer` | Storage analysis |

## Worker Architecture (UI)

All expensive diagnostics run in background `QThread` workers:

```
HomePage          → HomePageWorkerThread
OptimizerPage     → OptimizerWorkerThread
MonitorPage       → MonitorWorkerThread
```

Workers:
- Run in dedicated QThread
- Never touch Qt widgets directly
- Emit `finished(result)` signal with immutable data object
- GUI thread applies results via `_apply_*` methods (read-only from result)
- Overlap prevention: `if self._worker_thread and self._worker_thread.isRunning(): return`
- Stale result rejection: results delivered after page switch are safely ignored

## Timer Architecture

| Timer | Interval | Thread | Work |
|-------|----------|--------|------|
| Home `_timer` | 2s | GUI | Read cached telemetry |
| Optimizer `_refresh_timer` | 3s | GUI | Start background worker |
| Monitor `_timer` | 2s | GUI | Read cached telemetry + sparkline |
| Monitor `_diag_timer` | 15s | GUI | Start background worker |

## Known Architectural Debt

1. **Rollback layering**: `snapshot.py` + `rollback.py` + `rollback_manager.py` — three overlapping modules. The main flow uses `snapshot.py` + `rollback.py`. `rollback_manager.py` adds change tracking and crash recovery but is only used by CLI commands.

2. **Optimization layering**: `optimizer.py` + `optimization_executor.py` + `optimization_engine.py` — three orchestration layers. `optimization_engine.py` wraps `optimization_executor.py` with evidence validation.

3. **Gaming modules**: `gaming_session.py` + `gaming_optimization.py` + `gaming_session_analyzer.py` + `gaming_lifecycle.py` — four overlapping gaming systems with different APIs.

4. **Benchmark duplication**: `core/benchmark.py` + `performance/benchmark_engine.py` — two benchmark systems with different APIs.

5. **Frame analysis duplication**: `performance/frame_analyzer.py` + `performance/frame_pacing.py` — two frame analysis systems (different APIs, both used).

6. **Recommendation duplication**: `recommendation_engine.py` (per-optimization) + `intelligent_recommendation.py` (system-wide) — complementary but could share a common interface.

## Rules

- **No system modification without safety gate pass**
- **No optimization claim without measured evidence**
- **No fabricate FPS or performance values**
- **No process termination without user confirmation**
- **No game file modification**
- **No input injection or macro creation**
- **No anti-cheat bypass**
- **MEASURED / INFERRED / ESTIMATED / NOT_AVAILABLE data semantics preserved**
- **All expensive work in background workers, never on GUI thread**
