# Heaven Society v1.0.0 — Release Notes

## Release Date
September 2026

## What's New

### Core Optimization Engine
- Evidence-based optimization with before/after measurement
- Safe rollback for every applied change
- Crash recovery for incomplete sessions
- Data-driven optimization profiles (Balanced, Gaming, Competitive, Battery, Performance)

### Gaming Lifecycle
- Automatic game/emulator detection
- Baseline capture → recommendation → approval → apply → monitor → restore
- Temporary changes automatically restored when game closes
- Permanent changes require explicit user confirmation

### Real-time Monitoring
- CPU, GPU, RAM, VRAM, FPS, frame-time, temperature telemetry
- Bounded history buffers with sparkline visualization
- Background resource intelligence (top consumers, pressure detection)
- System health scoring across 6 categories

### Input Diagnostics
- Mouse polling consistency measurement
- Pointer configuration analysis (Enhance Pointer Precision)
- Input-to-frame correlation analysis
- Responsiveness classification and scoring

### Storage Intelligence
- Quick and deep storage scans
- Drive health assessment
- Largest directory analysis
- Cleanup recommendations

### Cleanup Center
- Safe temporary file cleanup with preview
- Categorized by safety (Safe, Review, Do Not Touch)
- User confirmation before any deletion

### Notification System
- Intelligent cooldowns and duplicate suppression
- Severity escalation (Info, Recommendation, Warning, Critical)
- Game mode awareness — no spam during gameplay

### Floating Panel UI
- Compact, movable floating control panel
- Always-on-top toggle for gaming
- Gaming Mode with compact metrics display
- Lazy page loading for fast startup
- Background workers prevent GUI freezing

### Error Boundaries
- Subsystem health tracking — no single failure crashes the GUI
- Graceful degradation with NOT_AVAILABLE states
- Managed workers with cancellation and timeout
- Corrupted config recovery with backup

## System Requirements
- Windows 10/11 (64-bit)
- Python 3.10+
- PySide6, psutil

## Performance
- Startup: ~1.3 seconds
- Page navigation: <25ms (after lazy load)
- GUI callbacks: <16ms (all critical paths)
- Background workers: non-blocking

## Safety
- No game file modification
- No input injection or macros
- No anti-cheat bypass
- All optimizations reversible
- Crash recovery for interrupted sessions

## Known Limitations
- FPS measurement requires PresentMon installed separately
- GPU temperature reading depends on NVML support
- Some WMI operations produce benign COM cleanup warnings
- AMD GPU thermal reading may report N/A on dual-GPU systems
