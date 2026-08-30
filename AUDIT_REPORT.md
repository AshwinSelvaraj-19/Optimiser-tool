# PHOENIX OPTIMIZER — FULL CODE AUDIT REPORT

**Audit Date**: 2026-08-29  
**Test Machine**: AMD Ryzen 5 5625U (6C/12T), NVIDIA RTX 3050 Laptop 4GB, 16GB RAM, Windows 10/11  
**NVML**: Available (nvidia-ml-py installed)  
**WMI**: Available (wmi package installed)  
**Emulator Installed**: None detected

---

## HARDWARE DETECTION AUDIT

| Feature | Status | Evidence | Problem | Required Fix |
|---------|--------|----------|---------|-------------|
| CPU Model | REAL | Returns "AMD64 Family 25 Model 124" | Shows raw string, not human-readable name | Use WMI Win32_Processor.Name |
| CPU Cores/Threads | REAL | 6C/12T detected correctly | — | — |
| CPU Frequency | REAL | 3201 MHz detected | — | — |
| CPU Temperature | UNSUPPORTED | Returns None | This laptop doesn't expose CPU temp via psutil sensors | Display "N/A" in UI, do not fabricate |
| GPU Detection (NVML) | REAL | RTX 3050 detected, 4096MB VRAM | — | — |
| GPU Detection (WMI fallback) | REAL | Falls back to WMI when NVML unavailable | — | — |
| GPU Utilization | BROKEN | Always returns 0.0 | Telemetry worker crashes (see below) | Fix telemetry worker bug |
| GPU Temperature | BROKEN | Always null | Telemetry worker crashes | Fix telemetry worker bug |
| GPU Clock | BROKEN | Always 0.0 | Telemetry worker crashes | Fix telemetry worker bug |
| GPU VRAM Used | BROKEN | Always 0.0 | Telemetry worker crashes | Fix telemetry worker bug |
| RAM Detection | REAL | 15.3GB total, 56.9% used | — | — |
| Display Resolution | REAL | 1536x864 | — | — |
| Display Refresh Rate | REAL | 144Hz detected | — | — |
| Power Plan Detection | BROKEN | Returns "Scheme GUID:... (Turbo" | `active_plan_name` parsed incorrectly by `.split()` | Fix parser to extract name from parentheses |
| Power Plan GUID | BROKEN | Returns "Power" instead of GUID | Same parsing bug | Fix parser |
| Power Plan Listing | PARTIAL | Lists 4 plans but last shows "Turbo) *" | Regex doesn't strip trailing `)` or `*` | Fix regex |
| Game Mode Registry | REAL | Value=1, detected correctly | — | — |
| Emulator Detection | REAL | Correctly reports "None installed" | No emulator on test machine — cannot verify positive detection | Needs emulator to fully verify |
| Process Classification | PARTIAL | 94 UNKNOWN, 24 OPTIONAL | Too many UNKNOWN — needs more known process entries | Expand OPTIONAL_PROCESSES list |

---

## FPS TELEMETRY AUDIT

| Feature | Status | Evidence | Problem | Required Fix |
|---------|--------|----------|---------|-------------|
| FPS Measurement | UI ONLY | Benchmark returns 0.0 FPS | No actual FPS source — frame_time calc is just telemetry polling interval | Must show "FPS TELEMETRY: UNAVAILABLE" |
| 1% Low | UI ONLY | Returns 0.0 | Calculated from fake frame times (polling intervals, not actual frames) | Mark as unavailable |
| 0.1% Low | UI ONLY | Returns 0.0 | Same problem | Mark as unavailable |
| Frame Time | MOCKED | Returns ~1000ms (telemetry interval) | Measures time between telemetry polls, not GPU frame presentation | Must not present as frame time |
| Frame Variance | MOCKED | Variance of polling intervals | Not real frame variance | Mark as unavailable |
| Benchmark Engine | BROKEN | Runs for 30s but returns meaningless data | All FPS metrics are derived from telemetry polling timestamps, not actual game frames | Must display "FPS TELEMETRY UNAVAILABLE" |

### FPS VERDICT: The application has NO mechanism to obtain actual game/emulator FPS. All FPS/frame-time metrics are FABRICATED from telemetry polling intervals. This is the most critical issue.

---

## GPU-EMULATOR ASSIGNMENT AUDIT

| Feature | Status | Evidence | Problem | Required Fix |
|---------|--------|----------|---------|-------------|
| GPU Installed Detection | REAL | "NVIDIA GeForce RTX 3050 Laptop GPU" | — | — |
| GPU Used by Emulator | UNSUPPORTED | No emulator installed to test | Cannot determine which GPU an emulator process uses without running emulator | Need Win32_VideoController.ProcessId or D3D diagnostics |
| GPU Engine per-process | UNSUPPORTED | Windows doesn't expose per-process GPU engine via simple WMI | Would need DXGI or NVIDIA-specific APIs | Mark as "Requires emulator running" |

---

## MSI APP PLAYER AUDIT

| Feature | Status | Evidence | Problem | Required Fix |
|---------|--------|----------|---------|-------------|
| Registry Detection | REAL | Searches HKLM Uninstall key | — | — |
| Filesystem Detection | REAL | Checks common install paths | — | — |
| Process Detection | REAL | Checks tasklist for known processes | — | — |
| Config Read (CPU) | UNSUPPORTED | Returns "Auto" hardcoded | No actual config file parsing implemented | Implement real config parsing |
| Config Read (RAM) | UNSUPPORTED | Returns "Auto" hardcoded | Same | Implement real config parsing |
| Config Read (Resolution) | UNSUPPORTED | Returns "Auto" hardcoded | Same | Implement real config parsing |
| Config Read (FPS) | UNSUPPORTED | Returns "60" hardcoded | Same | Implement real config parsing |
| Config Read (Renderer) | UNSUPPORTED | Returns "Auto" hardcoded | Same | Implement real config parsing |
| Config Read (GPU) | UNSUPPORTED | Returns "Auto" hardcoded | Same | Implement real config parsing |
| Config Read (VSync) | UNSUPPORTED | Returns "Unknown" hardcoded | Same | Implement real config parsing |
| Config Write | BROKEN | `write_config` returns False | No actual file writing implemented | Implement or mark as READ ONLY |
| Config Backup | PARTIAL | `_config_backup` stores object | Backup is in-memory only, not persisted | Implement disk backup |
| Config Restore | BROKEN | Calls `write_config` which returns False | Cannot restore if cannot write | Implement or mark as READ ONLY |

---

## OPTIMIZATION AUDIT

| Optimization | CHECK | SNAPSHOT | APPLY | VERIFY | ROLLBACK | VERDICT |
|---|---|---|---|---|---|---|
| Power Mode | REAL (reads powercfg) | REAL (saves GUID) | REAL (sets powercfg) | REAL (re-reads) | REAL (restores GUID) | **FULLY FUNCTIONAL** |
| Game Mode | REAL (reads registry) | REAL (saves value) | REAL (writes registry) | REAL (re-reads) | REAL (restores value) | **FULLY FUNCTIONAL** |
| GPU Preference | REAL (detects GPU) | REAL (reads DX pref) | STUB (no actual change) | ALWAYS TRUE | NOOP | **NOT FUNCTIONAL** |
| Background Process | REAL (lists processes) | NOOP | STUB (prints message) | ALWAYS TRUE | NOOP | **NOT FUNCTIONAL** |
| Display Refresh | REAL (reads refresh) | REAL (saves rate) | STUB (no actual change) | ALWAYS TRUE | NOOP | **NOT FUNCTIONAL** |
| Overlay Control | STUB (always OPTIMIZABLE) | NOOP | STUB (no actual change) | ALWAYS TRUE | NOOP | **NOT FUNCTIONAL** |
| Emulator CPU | STUB (always OPTIMIZABLE) | NOOP | STUB (no actual change) | ALWAYS TRUE | NOOP | **NOT FUNCTIONAL** |
| Emulator RAM | STUB (always OPTIMIZABLE) | NOOP | STUB (no actual change) | ALWAYS TRUE | NOOP | **NOT FUNCTIONAL** |
| Emulator Resolution | STUB (always OPTIMIZABLE) | NOOP | STUB (no actual change) | ALWAYS TRUE | NOOP | **NOT FUNCTIONAL** |
| Emulator FPS | STUB (always OPTIMIZABLE) | NOOP | STUB (no actual change) | ALWAYS TRUE | NOOP | **NOT FUNCTIONAL** |
| VSync | STUB (always OPTIMIZABLE) | NOOP | STUB (no actual change) | ALWAYS TRUE | NOOP | **NOT FUNCTIONAL** |

### OPTIMIZATION VERDICT: Only 2 of 11 optimizations actually work (Power Mode, Game Mode). The other 9 are stubs that claim success without doing anything.

---

## SHADERS AUDIT

| Feature | Status | Evidence | Problem | Required Fix |
|---------|--------|----------|---------|-------------|
| Profile Loading | REAL | Loads JSON from profiles/shaders/ | — | — |
| Slider UI | REAL | Sliders render with values | — | — |
| Save Preset | REAL | Saves to custom.json | — | — |
| Apply | UI ONLY | `_apply()` just logs values | No display/emulator visual pipeline applies these values | Label as "PROFILE PARAMETERS ONLY" |
| Visual Effect | UNSUPPORTED | No rendering pipeline | These values don't affect any display output | Must not claim they affect Free Fire |

### SHADERS VERDICT: The UI works and presets save/load. But APPLY does nothing — there is no legitimate display rendering pipeline that uses these values. Must be labeled as profile parameters, not active shaders.

---

## BOTTLENECK ANALYZER AUDIT

| Feature | Status | Evidence | Problem | Required Fix |
|---------|--------|----------|---------|-------------|
| Rules Engine | REAL | Correctly identifies CPU/GPU/RAM/Thermal bottlenecks | — | — |
| Single Sample Problem | PARTIAL | Uses current telemetry frame only | Should use measurement window (10-30s) | Implement sliding window analysis |
| Confidence Calculation | PARTIAL | Based on single sample magnitude | Should be based on sustained behavior | Use windowed analysis |

---

## THERMAL ENGINE AUDIT

| Feature | Status | Evidence | Problem | Required Fix |
|---------|--------|----------|---------|-------------|
| GPU Temperature (NVML) | REAL | Would work with NVML (tested available) | Telemetry worker crashes so always null | Fix telemetry bug |
| CPU Temperature | UNSUPPORTED | `psutil.sensors_temperatures()` returns nothing on this AMD laptop | AMD laptops often don't expose via psutil | Show "N/A" — do not fabricate |
| Throttling Detection | PARTIAL | Based on temperature threshold only | Should also check clock drops | Add clock-based throttling detection |

---

## WINDOWS SAFETY AUDIT

| Feature | Status | Evidence | Problem | Required Fix |
|---------|--------|----------|---------|-------------|
| Critical Process Protection | REAL | 23 processes in CRITICAL_PROCESSES set | — | — |
| Security Process Protection | REAL | 9 processes in SECURITY_PROCESSES set | — | — |
| No Defender Modification | REAL | No code modifies Defender | — | — |
| No Firewall Modification | REAL | No code modifies Firewall | — | — |
| No Windows Update Disable | REAL | No code modifies Windows Update | — | — |
| Registry Backup | REAL | `backup_registry_key` saves values | — | — |
| Rollback | REAL | `rollback_engine` restores from snapshot | Only works for optimizations that actually store snapshots | — |
| Admin Detection | REAL | `is_admin()` checks correctly | — | — |

---

## CRITICAL BUGS

### BUG 1: Telemetry Worker Crash (CRITICAL)
**File**: `app/core/telemetry.py`, line ~113  
**Error**: `UnboundLocalError: cannot access local variable 'psutil'`  
**Cause**: The `_worker` method has `import psutil` inside the function body, but the module-level code at the bottom also imports psutil, creating a variable shadowing issue.  
**Impact**: ALL real-time telemetry is zero/null. GPU temp, utilization, clock, VRAM — all broken.  
**Fix**: Remove the local `import psutil` from `_worker`, use the module-level import.

### BUG 2: Power Plan Name Parsing (HIGH)
**File**: `app/system/power.py`  
**Problem**: `.split()` on `"Power Scheme GUID: ... (Turbo)"` returns `"Scheme"` as the name.  
**Raw output**: `'Power Scheme GUID: 6fecc5ae-...  (Turbo)'`  
**Current result**: name=`"Scheme GUID: ... (Turbo"`, guid=`"Power"`  
**Correct result**: name=`"Turbo"`, guid=`"6fecc5ae-..."`  
**Fix**: Parse with regex to extract GUID and name from parentheses.

### BUG 3: Available Plans Name Trailing Characters
**File**: `app/system/power.py`  
**Problem**: Plan names show `"Turbo) *"` instead of `"Turbo"`  
**Fix**: Strip trailing `)`, `*`, and whitespace from parsed names.

---

## SUMMARY

### VERIFIED (Real, Working)
1. ✅ CPU detection (model, cores, threads, frequency)
2. ✅ GPU detection via NVML (name, vendor, VRAM, driver)
3. ✅ GPU detection via WMI fallback
4. ✅ RAM detection (total, used, percentage)
5. ✅ Display detection (resolution, refresh rate)
6. ✅ Game Mode registry read/write
7. ✅ Process listing and classification
8. ✅ Snapshot creation and persistence
9. ✅ Snapshot restoration (for working optimizations)
10. ✅ Bottleneck analysis rules (single-sample mode)
11. ✅ Performance scoring math
12. ✅ Shader preset save/load
13. ✅ UI rendering and navigation
14. ✅ Logging system
15. ✅ Admin detection
16. ✅ Critical process whitelist

### BROKEN (Exists But Doesn't Work)
1. ❌ Telemetry worker (crashes on import)
2. ❌ Power plan name/GUID parsing
3. ❌ All GPU telemetry (utilization, temp, clock, VRAM used)
4. ❌ All FPS/frame-time metrics (no real source)
5. ❌ Benchmark engine (returns meaningless data)
6. ❌ 9 of 11 optimizations (stubs that claim success)
7. ❌ Emulator config read/write (hardcoded values)
8. ❌ Shader "Apply" (does nothing)

### UI-ONLY (Visual Only, No Backend)
1. 🎨 FPS display cards (show N/A correctly, but benchmark doesn't)
2. 🎨 Shader sliders (UI works, apply does nothing)
3. 🎨 Optimization status badges (show stub results as "APPLIED")
4. 🎨 Emulator config display (shows hardcoded values)

### UNSUPPORTED (Cannot Work Without External Factors)
1. 🚫 CPU temperature (AMD laptop doesn't expose via psutil)
2. 🚫 Emulator config (no emulator installed to test)
3. 🚫 GPU-emulator assignment (no running emulator)
4. 🚫 Actual game FPS measurement (no FPS source)

---

## REQUIRED FIXES (Priority Order)

1. **CRITICAL**: Fix telemetry worker `psutil` import bug
2. **CRITICAL**: Fix power plan name/GUID parsing
3. **CRITICAL**: Benchmark must show "FPS TELEMETRY UNAVAILABLE" instead of fake data
4. **HIGH**: Mark 9 non-functional optimizations as "NOT YET IMPLEMENTED"
5. **HIGH**: Mark shader Apply as "PROFILE PARAMETERS ONLY"
6. **HIGH**: Mark emulator config as "REQUIRES EMULATOR RUNNING"
7. **MEDIUM**: Add measurement window to bottleneck analyzer
8. **MEDIUM**: Expand process classification list
9. **MEDIUM**: Fix available plan name parsing (trailing characters)
