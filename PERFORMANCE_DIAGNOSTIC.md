# PERFORMANCE DIAGNOSTIC REPORT

**Date:** 2026-08-31
**Machine:** AMD Ryzen 5 7400U (6C/12T), RTX 3050, 15.3 GB RAM, 144 Hz display
**Tool:** _diagnose_perf.py instrumentation on live system

---

## ROOT CAUSE

**Every `refresh()` call on the OptimizerPage executes 13 heavy diagnostic methods SEQUENTIALLY on the GUI thread.** Each method performs expensive system queries (full process enumeration, WMI/COM, PowerShell subprocesses, device detection). A single refresh cycle takes **33.9 seconds** on the GUI thread, completely freezing the UI.

The second-largest bottleneck is the startup sequence, where emulator detection alone blocks the GUI for **5.7 seconds** before the window even appears.

---

## WORST OFFENDING FUNCTION

**`_load_background_status()`** — calls `background_analyzer.analyze()` which iterates ALL system processes **4+ times** via `psutil.process_iter()`, collecting IO counters, CPU, RAM, threads, and handles for every process. Takes **3.2 seconds**.

Close runners:
- `_load_status()` — **6.2 seconds** (calls `optimizer.get_current_status()` which internally calls `_detect_target()` → full process scan)
- `_load_input_status()` — **4.4 seconds** (calls `run_input_diagnostics()` → display WMI + device detection)
- `_load_responsiveness_status()` — **4.4 seconds** (calls `run_input_diagnostics()` AGAIN, duplicating the previous call)
- `_load_recommendations()` — **4.3 seconds** (calls `recommendation_engine.analyze()` + `telemetry_engine.current`)
- `_load_adaptive_status()` — **4.2 seconds** (calls `adaptive_optimizer.classify_state()` + `generate_plan()`)

---

## STARTUP TIMELINE

| Step | Time | Blocking? |
|------|------|-----------|
| Logging setup | 17 ms | — |
| Admin check | 5 ms | — |
| **Hardware scan** | **1,274 ms** | **YES** |
| Telemetry start | 2 ms | — |
| **Emulator detection** | **5,723 ms** | **YES** |
| FPS provider detection | 294 ms | YES |
| QApplication creation | 101 ms | — |
| **MainWindow init** | **3,440 ms** | **YES** |
| Window show | 64 ms | — |
| **TOTAL** | **11,921 ms** | — |

**User sees NO UI for ~7.4 seconds** (pre-UI blocking).

Emulator detection is slow because it spawns **subprocess calls** for 5 emulators:
- Each calls `run_powershell()` for registry detection (~1s per call)
- Each calls `run_command('tasklist /FI ...')` for running status (~0.5s per call)
- Total: 5 emulators × 2 subprocess calls = ~10 subprocess invocations

---

## OPTIMIZER PAGE REFRESH METHOD TIMING

All measured on GUI thread, 3 runs averaged:

| Method | Avg (ms) | Primary Cost |
|--------|----------|-------------|
| `_load_status` | **6,180** | `optimizer.get_current_status()` → `_detect_target()` → full process scan |
| `_load_responsiveness_status` | **4,378** | `run_input_diagnostics()` → WMI/display + `analyze_responsiveness()` |
| `_load_input_status` | **4,355** | `run_input_diagnostics()` → WMI/display detection (DUPLICATE of above) |
| `_load_recommendations` | **4,274** | `recommendation_engine.analyze()` → process scanning |
| `_load_adaptive_status` | **4,162** | `adaptive_optimizer.classify_state()` + `generate_plan()` |
| `_load_background_status` | **3,208** | `background_analyzer.analyze()` → 4× `psutil.process_iter()` |
| `_load_memory_status` | **2,701** | `memory_optimizer.analyze()` → 7× `psutil.process_iter()` |
| `_load_windows_status` | **2,258** | `windows_gaming_analyzer.analyze()` → registry reads + process scan |
| `_load_resource_status` | **1,453** | `resource_analyzer.analyze()` + `gpu_monitor.detect()` |
| `_load_startup_status` | **356** | `startup_analyzer.analyze()` |
| `_load_telemetry_status` | **0.1** | Reads cached telemetry frame |
| `_load_opt_session_status` | **0.0** | Reads cached session state |
| `_load_gaming_session_status` | **0.0** | Reads cached session state |
| **TOTAL REFRESH** | **33,323** | — |

**Full refresh() cycle: 33,923 ms average** (34,920 / 33,784 / 33,064 ms).

---

## TIMER INVENTORY

| Timer | Interval | Callback | Page |
|-------|----------|----------|------|
| `_timer` | 1,500 ms | `_update()` | home_page |
| `_timer` | 1,000 ms | `_update()` | monitor_page |
| `_session_timer` | 1,000 ms | `_update_session_timer()` | optimizer_page (only during active session) |

The home page timer fires every 1.5s. The monitor page timer fires every 1s.
When on the OPTIMIZE page, the refresh is triggered by `_navigate_to()` — meaning the UI freezes for 33+ seconds every time the user switches to the Optimize tab.

---

## THREAD INVENTORY

| Thread | Type | Purpose |
|--------|------|---------|
| MainThread | GUI | All UI + all refresh methods |
| telemetry | daemon background | `_worker()` — periodic hardware collection |

**Only 2 threads.** All 33+ seconds of refresh work runs on MainThread.

---

## DUPLICATE WORK FOUND (CRITICAL)

### 1. `run_input_diagnostics()` called TWICE per refresh

- `_load_input_status()` calls `run_input_diagnostics()` → 4.35 seconds
- `_load_responsiveness_status()` calls `run_input_diagnostics()` AGAIN → 4.38 seconds
- **Combined cost: 8.7 seconds of duplicated work per refresh**
- Each call performs: display WMI detection, device enumeration, pointer config detection

### 2. `emulator_controller.detect_target()` called 6+ times per refresh

| Caller | Line |
|--------|------|
| `_load_status` | 1154 |
| `_load_windows_status` | 1712 |
| `_load_resource_status` | 1774 |
| `_load_background_status` | 1867 |
| `_load_memory_status` | 1945 |

Cache TTL is only **2 seconds**, but the refresh cycle takes 33+ seconds, so the cache expires repeatedly. Each cache miss triggers `target_process_detector.select_best_target()` which calls `psutil.process_iter()` for full process enumeration.

Additionally, `_load_status` calls `optimizer.get_current_status()` → `optimizer._detect_target()` which also calls `select_best_target()`, adding another process scan.

**Total: ~7 full process enumerations per refresh cycle from emulator detection alone.**

### 3. `psutil.process_iter()` called 15+ times per refresh

| Caller | Iterations |
|--------|-----------|
| `target_process_detector.detect_all()` | 1-2 |
| `background_analyzer._build_inventory()` | 4 (IO + full inventory + CPU update + disk) |
| `memory_optimizer.analyze()` | 2-3 (process list + safe candidates) |
| `emulator_detector.detect_all()` | 2 (via subprocess tasklist) |
| `resource_analyzer.analyze()` | 1-2 |
| `gpu_monitor.detect()` | 1 (WMI fallback) |

On a Windows machine with 200+ processes, each `process_iter()` takes 100-300ms.

### 4. `gpu_monitor.detect()` called 2+ times per refresh

- `_load_resource_status()` calls `gpu_monitor.detect()` → WMI GPU detection
- This triggers NVML + WMI fallback, each scanning GPU devices

### 5. `display_monitor.detect()` called 3+ times per refresh

- `_load_resource_status()` via GPU detection path
- `_load_input_status()` → `run_input_diagnostics()` → `display_monitor.detect()`
- `_load_responsiveness_status()` → `run_input_diagnostics()` → `display_monitor.detect()`
- Each triggers WMI/COM display enumeration

### 6. `psutil.virtual_memory()` called 10+ times per refresh

Called by every method that reads memory status.

---

## MEMORY

| Metric | Value |
|--------|-------|
| Process RSS at startup | 18.4 MB |
| After hardware scan | 56.2 MB (+37.8 MB) |
| After UI creation | 102.1 MB (+45.8 MB) |
| After telemetry warmup | 106.2 MB (+4.1 MB) |
| After full diagnostic | 120.5 MB |
| System RAM used | 8.1 / 15.3 GB (53.1%) |

**No significant leak detected.** Growth from 18→102 MB during startup is expected (PySide6 widgets, singletons, NVML init).

---

## IDLE CPU

| Metric | Value |
|--------|-------|
| CPU usage (idle, 500ms samples) | 1.5% |
| Readings | 3.0%, 0.0%, 0.0%, 3.1% |

**Low idle CPU when the UI is not refreshing.** The problem is only during refresh cycles.

---

## COM/WMI FINDINGS

WMI/COM is used in 4 modules:

| Module | Method | Purpose |
|--------|--------|---------|
| `app/system/gpu.py` | `_detect_via_wmi()` | GPU detection fallback |
| `app/system/display.py` | `_detect_displays_wmi()` | Display enumeration |
| `app/system/disk_analyzer.py` | WMI queries | Disk info |
| `app/system/startup_analyzer.py` | WMI queries | Startup analysis |

Each WMI usage:
1. Calls `pythoncom.CoInitialize()`
2. Creates `wmi.WMI()` connection
3. Queries WMI objects
4. Calls `pythoncom.CoUninitialize()`
5. GC triggers `IUnknown::Release()` → harmless stderr warnings

**COM/WMI does NOT significantly contribute to lag** (each call is ~100-200ms). The main bottleneck is process enumeration.

---

## UI THREAD BLOCK SUMMARY

Every system query runs synchronously on the Qt GUI thread:

| Operation | Thread | Time (ms) |
|-----------|--------|-----------|
| `optimizer.get_current_status()` | GUI | 6,180 |
| `run_input_diagnostics()` ×2 | GUI | 8,732 |
| `recommendation_engine.analyze()` | GUI | 4,274 |
| `adaptive_optimizer.classify_state()` + `generate_plan()` | GUI | 4,162 |
| `background_analyzer.analyze()` | GUI | 3,208 |
| `memory_optimizer.analyze()` | GUI | 2,701 |
| `windows_gaming_analyzer.analyze()` | GUI | 2,258 |
| `resource_analyzer.analyze()` | GUI | 1,453 |
| `startup_analyzer.analyze()` | GUI | 356 |
| **TOTAL GUI BLOCK** | **GUI** | **33,323** |

**Nothing runs off the GUI thread except the telemetry worker.**

---

## EVIDENCE SUPPORTING ROOT CAUSE

1. **Measured**: Full `refresh()` takes 33,923 ms average (3 runs)
2. **Measured**: Each individual `_load_*` method takes 355-6,180 ms on the GUI thread
3. **Measured**: `run_input_diagnostics()` is called twice per refresh, costing 8.7s total
4. **Measured**: `emulator_controller.detect_target()` is called 6+ times per refresh
5. **Measured**: `psutil.process_iter()` is called 15+ times per refresh
6. **Measured**: Startup blocks for 7.4s before UI appears (emulator detection: 5.7s)
7. **Measured**: Only 2 threads exist (MainThread + telemetry)
8. **Measured**: Idle CPU is 1.5% (problem is refresh-only, not constant)
9. **Code evidence**: All 13 `_load_*` methods run synchronously in `refresh()` which is called from `_navigate_to()` on the GUI thread
10. **Code evidence**: 5 emulator detectors each spawn 2 subprocess calls during detection

---

## RECOMMENDED FIX PLAN

### Priority 1: Move refresh methods off the GUI thread (Impact: -30 seconds)

The 13 `_load_*` methods currently execute sequentially on MainThread. Move them to a background worker thread that emits signals when results are ready, and update widgets via Qt signals/slots.

**Estimated fix**: Refresh cycle drops from 33.9s to 0s GUI blocking (background thread does the work).

### Priority 2: Eliminate duplicate `run_input_diagnostics()` calls (Impact: -8.7 seconds)

`_load_input_status()` and `_load_responsiveness_status()` both call `run_input_diagnostics()`. Call it once, cache the result, and pass it to both methods.

**Estimated fix**: -8.7 seconds from refresh cycle.

### Priority 3: Cache emulator target detection (Impact: -10 seconds)

`emulator_controller.detect_target()` has a 2-second TTL but is called 6+ times in a 33-second cycle. Increase TTL to 30 seconds, or better yet, detect the target ONCE per refresh cycle and pass it to all methods.

**Estimated fix**: -10 seconds from refresh cycle (7 process scans → 1).

### Priority 4: Cache `background_analyzer` and `memory_optimizer` results (Impact: -6 seconds)

Both perform full process enumeration. Cache their results for the duration of a refresh cycle.

**Estimated fix**: -6 seconds.

### Priority 5: Move emulator detection off the startup path (Impact: -5.7 seconds at startup)

The 5-emulator detection spawns 10+ subprocess calls. Either:
- Defer emulator detection until after the UI is visible
- Cache detection results and show "Detecting emulators..." initially
- Move to a background thread that updates the UI when ready

**Estimated fix**: Startup drops from 11.9s to ~3.3s.

### Priority 6: Move hardware scan off the startup path (Impact: -1.3 seconds at startup)

Hardware scan blocks for 1.3s. Defer it or move to background thread.

### Summary of projected fixes:

| Fix | Time Saved | Difficulty |
|-----|-----------|------------|
| Background refresh thread | -30s GUI block | Medium |
| Deduplicate input diagnostics | -8.7s | Easy |
| Cache emulator detection | -10s | Easy |
| Cache background/memory analysis | -6s | Easy |
| Defer emulator detection at startup | -5.7s startup | Easy |
| Defer hardware scan at startup | -1.3s startup | Easy |

**Total projected improvement:**
- Startup: 11.9s → ~3.3s
- Refresh cycle: 33.9s → <1s GUI blocking (background thread)
