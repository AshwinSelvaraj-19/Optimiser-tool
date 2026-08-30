# Heaven Society

A real-time Windows gaming performance optimizer and emulator telemetry system built for MSI App Player / BlueStacks and Free Fire.

## Features

- **Real FPS Telemetry** — PresentMon 2.5.1 integration for accurate frame-timing data
- **Hardware Detection** — CPU, GPU (NVIDIA via NVML), RAM, display, thermal monitoring
- **Emulator Detection** — HD-Player.exe / MSI App Player / BlueStacks live process detection
- **Optimization Engine** — Power Plan, Game Mode, Emulator Priority with snapshot/rollback
- **A/B Benchmarking** — Repeated before/after measurement with confidence scoring
- **Frame Pacing Analysis** — Stability scoring, spike detection, coefficient of variation
- **Memory Analysis** — RAM pressure, emulator memory, safe process recommendations
- **Background Load Analysis** — Process classification without automatic termination
- **Disk & Storage Cleanup** — Safe temporary file removal with verification
- **Startup Analysis** — Read-only Windows startup entry detection
- **Thermal Monitoring** — GPU/CPU temperature tracking with throttling detection
- **Gaming Session Mode** — Controlled optimization lifecycle with rollback
- **Professional Reporting** — JSON export and CLI performance reports

## Installation

```bash
python -m pip install -r requirements.txt
```

### Requirements

- Python 3.10+
- Windows 10/11
- NVIDIA GPU (recommended for GPU telemetry)
- [PresentMon 2.5.1](https://github.com/GameTechDev/PresentMon/releases) for FPS telemetry

## Usage

### Launch GUI

```bash
python main.py
```

### Diagnostics

```bash
python main.py --check-prerequisites
python main.py --diagnostic
```

### FPS Telemetry

```bash
python main.py --presentmon-test
python main.py --telemetry --duration 30
python main.py --performance-session --duration 120
```

### Benchmarking

```bash
python main.py --benchmark --duration 15
python main.py --ab-benchmark --profile gaming --duration 15 --runs 3
```

### Optimization

```bash
python main.py --emulator-optimize --profile gaming
python main.py --windows-optimize --profile gaming
python main.py --analyze-gaming
```

### System Analysis

```bash
python main.py --memory-status
python main.py --memory-analyze
python main.py --disk-status
python main.py --disk-scan
python main.py --startup-status
python main.py --resource-status
python main.py --thermal-status
python main.py --hardware-profile
```

### Validation

```bash
python main.py --final-validation --profile gaming --duration 10 --runs 3
python main.py --report
```

## Architecture

```
phoenix_optimizer/
├── main.py                    # CLI entry point + GUI launcher
├── app/
│   ├── core/                  # Optimization engine, sessions, rollback
│   ├── performance/           # PresentMon, benchmarks, A/B testing
│   ├── system/                # CPU, GPU, RAM, disk, thermal, emulator
│   ├── cleanup/               # Safe system cleanup engine
│   ├── emulator/              # Emulator detection
│   ├── ui/                    # PySide6 compact silver/red UI
│   └── utils/                 # Logger, admin detection
├── profiles/                  # JSON optimization profiles
├── tests/                     # Comprehensive test suite
└── requirements.txt
```

## Important Notes

- **PresentMon** requires elevated privileges (UAC) for ETW-based frame capture
- **Emulator priority** changes require administrator privileges
- Some optimizations are **recommendation-only** for safety
- All metrics are **real measurements** — no fabricated data
- The application **does not** modify game files, memory, or inject code
- Cleanup operations are **safe** — personal files are never touched
- Every optimization has **snapshot/rollback** capability

## Test Suite

```bash
python -m pytest tests/ -q
```

## License

Internal project — see repository for details.
