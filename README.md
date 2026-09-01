# Heaven Society — Gaming Optimization Suite

A comprehensive, evidence-based PC gaming optimization tool built with PySide6.

## Features

- **Real-time telemetry** — CPU, GPU, RAM, FPS, frame-time, temperature monitoring
- **Smart optimization** — Safe, reversible Windows gaming optimizations with rollback
- **Gaming lifecycle** — Automatic detection → baseline → recommend → apply → monitor → restore
- **Input diagnostics** — Mouse polling consistency, pointer configuration, input latency analysis
- **System health** — 6-category scoring: Performance, Thermal, Memory, Storage, Background Load, Gaming Readiness
- **Cleanup center** — Safe temporary file cleanup with preview and categorization
- **Benchmark engine** — Before/after comparison with measurable evidence
- **Floating panel** — Compact, movable, always-on-top gaming companion UI

## Requirements

- Windows 10/11 (64-bit)
- Python 3.10+
- PySide6
- psutil
- pynvml (NVIDIA GPU monitoring, optional)

## Installation

```bash
pip install PySide6 psutil pynvml
```

## Usage

### GUI Mode

```bash
python main.py
```

### CLI Mode

```bash
# System health check
python main.py --health-score

# Telemetry status
python main.py --telemetry-status

# Storage scan
python main.py --storage-scan

# Process analysis
python main.py --process-scan

# Gaming lifecycle
python main.py --gaming-lifecycle-start
python main.py --gaming-lifecycle-stop

# Optimization preview (read-only)
python main.py --optimize-preview

# Rollback check
python main.py --rollback-check

# Full diagnostics
python main.py --gameplay-diagnostics --duration 10
```

## Architecture

```
app/
├── core/           # Optimization engine, rollback, profiles, settings
├── gaming/         # Gaming lifecycle orchestrator
├── input/          # Input diagnostics and responsiveness
├── performance/    # Telemetry, benchmarks, FPS, frame analysis
├── storage/        # Storage intelligence
├── system/         # CPU, GPU, RAM, display, process monitoring
├── ui/             # PySide6 GUI (floating panel)
├── cleanup/        # Safe cleanup engine
├── emulator/       # BlueStacks, MSI, LDPlayer detection
└── utils/          # Logging, admin, registry helpers
```

## Safety

- **No game file modification** — Never touches game binaries or configs
- **No input injection** — Does not simulate mouse/keyboard input
- **No anti-cheat bypass** — Respects all game security mechanisms
- **Reversible changes** — Every optimization can be rolled back
- **Evidence-based** — Recommendations based on measured data, not guesses
- **Crash recovery** — Detects incomplete sessions on startup

## License

Private — Heaven Society
