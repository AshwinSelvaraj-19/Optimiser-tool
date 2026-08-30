"""
PresentMon 2.5.1 FPS provider — real frame-timing via PresentMon CSV output.

Discovery: searches common paths for PresentMon executable.
Session: launches PresentMon elevated via ShellExecuteW 'runas' for ETW access.
          PresentMon self-terminates via --timed + --terminate_after_timed.
          We wait for exit, then parse the CSV.
Parsing: extracts real frame presentation timestamps from CSV v2 columns.
Metrics: calculates FPS, 1% low, frame time, variance from real data.

PresentMon 2.5.1 key CLI flags:
  --output_file PATH     Write CSV to PATH
  --no_console_stats     Suppress console stats display
  --timed SECONDS        Stop after N seconds
  --terminate_after_timed  Exit after timed capture completes
  --process_name NAME    Filter by process (repeatable)
  --session_name NAME    Unique session name
  --stop_existing_session  Stop existing session with same name before starting

IMPORTANT: Elevated PresentMon processes CANNOT be killed from non-elevated
contexts (taskkill returns Access Denied). We use --timed + --terminate_after_timed
so PresentMon exits naturally, then we parse the CSV after exit.
"""

import csv
import glob
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional

import psutil

from app.performance.fps_provider import FPSProvider, FPSMetrics, FrameSample
from app.utils.logger import get_logger

logger = get_logger("performance.presentmon")


def find_presentmon() -> Optional[Path]:
    """
    Search for PresentMon executable.
    Returns Path if found, None otherwise.
    Search order:
    1. %USERPROFILE%\\Downloads\\PresentMon-*.exe
    2. %LOCALAPPDATA%\\Intel\\PresentMon
    3. %PROGRAMFILES%\\Intel\\PresentMon
    4. %PROGRAMFILES(X86)%\\Intel\\PresentMon
    5. PATH
    """
    # 1. Downloads folder — glob for any PresentMon version
    downloads = os.path.expandvars(r"%USERPROFILE%\Downloads")
    if os.path.isdir(downloads):
        for pattern in ["PresentMon*.exe", "presentmon*.exe"]:
            matches = glob.glob(os.path.join(downloads, pattern))
            if matches:
                matches.sort(key=os.path.getmtime, reverse=True)
                path = Path(matches[0])
                logger.info(f"Found PresentMon in Downloads: {path}")
                return path

    # 2-4. Common install directories
    search_dirs = [
        os.path.expandvars(r"%LOCALAPPDATA%\Intel\PresentMon"),
        os.path.expandvars(r"%PROGRAMFILES%\Intel\PresentMon"),
        os.path.expandvars(r"%PROGRAMFILES(X86)%\Intel\PresentMon"),
        r"C:\Program Files\Intel\PresentMon",
        r"C:\Program Files (x86)\Intel\PresentMon",
    ]
    for d in search_dirs:
        if os.path.isdir(d):
            for fname in os.listdir(d):
                if fname.lower().endswith(".exe") and "presentmon" in fname.lower():
                    path = Path(os.path.join(d, fname))
                    logger.info(f"Found PresentMon in {d}: {path}")
                    return path

    # 5. PATH
    for name in ["presentmon.exe", "presentmon64.exe"]:
        found = shutil.which(name)
        if found:
            path = Path(found)
            logger.info(f"Found PresentMon in PATH: {path}")
            return path

    logger.info("PresentMon not found")
    return None


def get_presentmon_version(exe_path: Path) -> Optional[str]:
    """Get PresentMon version by running --version."""
    try:
        result = subprocess.run(
            [str(exe_path), "--version"],
            capture_output=True, text=True, timeout=5
        )
        output = result.stdout + result.stderr
        match = re.search(r"(\d+\.\d+\.\d+)", output)
        if match:
            return match.group(1)
        return output.strip()[:50] if output.strip() else None
    except Exception as e:
        logger.debug(f"Version detection failed: {e}")
        return None


def _cleanup_csv(csv_path: str, max_retries: int = 5, retry_delay: float = 1.0) -> bool:
    """
    Safely delete a temporary PresentMon CSV file.

    Retries up to max_retries times with retry_delay seconds between attempts
    in case the file is temporarily locked by PresentMon's file handle.

    Returns True if deletion succeeded or file never existed.
    Logs clearly on success and failure.
    """
    if not csv_path:
        return True

    if not os.path.exists(csv_path):
        return True

    for attempt in range(1, max_retries + 1):
        try:
            os.remove(csv_path)
            logger.info(f"Temporary CSV removed: {csv_path}")
            return True
        except PermissionError:
            if attempt < max_retries:
                logger.debug(
                    f"CSV locked (attempt {attempt}/{max_retries}), "
                    f"waiting {retry_delay}s..."
                )
                time.sleep(retry_delay)
            else:
                logger.warning(
                    f"Failed to remove temporary CSV after "
                    f"{max_retries} attempts: {csv_path}"
                )
                return False
        except OSError as e:
            logger.warning(f"Failed to remove temporary CSV: {csv_path} — {e}")
            return False

    return False


def cleanup_stale_csvs() -> int:
    """
    Remove stale Heaven Society CSV files from previous crashed/interrupted captures.

    Only removes files matching phoenix_pm_*.csv from the system temp directory.
    Returns the number of files removed.
    """
    temp_dir = tempfile.gettempdir()
    removed = 0

    try:
        for fname in os.listdir(temp_dir):
            if fname.startswith("phoenix_pm_") and fname.endswith(".csv"):
                fpath = os.path.join(temp_dir, fname)
                try:
                    os.remove(fpath)
                    logger.info(f"Removed stale CSV: {fpath}")
                    removed += 1
                except OSError as e:
                    logger.debug(f"Could not remove stale CSV: {fpath} — {e}")
    except OSError as e:
        logger.debug(f"Error scanning temp directory for stale CSVs: {e}")

    if removed > 0:
        logger.info(f"Cleaned up {removed} stale CSV file(s)")
    return removed


class PresentMonProvider(FPSProvider):
    """Real FPS provider using PresentMon 2.5.1 CSV output."""

    name = "PresentMon"

    # PresentMon 2.5.1 CSV columns
    COL_APPLICATION = "Application"
    COL_PROCESS_ID = "ProcessID"
    COL_TIME = "TimeInMs"
    COL_FRAME_TIME = "MsBetweenPresents"
    COL_DISPLAY_TIME = "MsBetweenDisplayChange"
    COL_CPU_BUSY = "MsCPUBusy"
    COL_CPU_WAIT = "MsCPUWait"
    COL_GPU_LATENCY = "MsGPULatency"
    COL_GPU_TIME = "MsGPUTime"
    COL_GPU_BUSY = "MsGPUBusy"
    COL_GPU_WAIT = "MsGPUWait"
    COL_PRESENT_MODE = "PresentMode"
    COL_SYNC_INTERVAL = "SyncInterval"
    COL_RENDER_LATENCY = "MsRenderPresentLatency"
    COL_DISPLAYED = "MsUntilDisplayed"
    COL_ALL_INPUT_LATENCY = "MsAllInputToPhotonLatency"

    def __init__(self):
        self._exe_path: Optional[Path] = None
        self._version: Optional[str] = None
        self._elevated_handle = None  # ElevatedProcess from launcher
        self._csv_path: Optional[str] = None
        self._samples: list = []
        self._running = False
        self._target_process: str = ""
        self._session_name: str = ""
        self._needs_elevation: bool = False
        self._permission_ok: bool = True
        self._state: str = "UNAVAILABLE"
        self._error_reason: str = ""
        self._capture_duration: int = 300  # --timed value

        # Startup stale CSV cleanup
        try:
            cleanup_stale_csvs()
        except Exception as e:
            logger.debug(f"Startup stale CSV cleanup: {e}")

    def is_available(self) -> tuple:
        """Check if PresentMon is installed and accessible."""
        self._exe_path = find_presentmon()
        if not self._exe_path:
            return False, (
                "PresentMon not found. Install from "
                "https://github.com/GameTechDev/PresentMon/releases"
            )

        if not self._exe_path.exists():
            return False, f"PresentMon path does not exist: {self._exe_path}"

        self._version = get_presentmon_version(self._exe_path)
        version_str = f" v{self._version}" if self._version else ""
        return True, f"Found{version_str}: {self._exe_path}"

    def get_version(self) -> Optional[str]:
        return self._version

    def get_path(self) -> Optional[str]:
        return str(self._exe_path) if self._exe_path else None

    def get_state(self) -> str:
        return self._state

    def get_error_reason(self) -> str:
        return self._error_reason

    def start(self, target_process: str = "", duration: int = 300) -> bool:
        """
        Start PresentMon capture session.

        Uses ShellExecuteW with 'runas' verb to properly elevate.
        PresentMon self-terminates via --timed + --terminate_after_timed.
        We wait for the CSV to appear, then collect data while it runs.

        Args:
            target_process: Process name to filter (e.g. "HD-Player.exe")
            duration: Capture duration in seconds (PresentMon --timed)
        """
        if self._running:
            logger.warning("PresentMon already running")
            return False

        if not self._exe_path or not self._exe_path.exists():
            available, reason = self.is_available()
            if not available:
                logger.error(f"Cannot start PresentMon: {reason}")
                return False

        self._target_process = target_process
        self._samples = []
        self._state = "STARTING"
        self._error_reason = ""
        self._capture_duration = duration

        # Create unique session name
        self._session_name = f"PhoenixPerf_{os.getpid()}"

        # Output CSV to temp directory
        self._csv_path = os.path.join(
            tempfile.gettempdir(),
            f"phoenix_pm_{self._session_name}.csv"
        )

        # Remove old CSV if it exists
        _cleanup_csv(self._csv_path, max_retries=2, retry_delay=0.5)

        # Clean stale Phoenix sessions first
        from app.performance.elevated_launcher import (
            kill_stale_phoenix_sessions,
        )
        kill_stale_phoenix_sessions(self._session_name)
        time.sleep(0.5)

        # Build PresentMon 2.5.1 command
        cmd = [
            str(self._exe_path),
            "--output_file", self._csv_path,
            "--no_console_stats",
            "--timed", str(duration),
            "--terminate_after_timed",
            "--session_name", self._session_name,
            "--stop_existing_session",
        ]

        if target_process:
            cmd.extend(["--process_name", target_process])

        logger.info(f"Starting PresentMon: {' '.join(cmd)}")

        # Launch elevated via ShellExecuteW
        from app.performance.elevated_launcher import launch_elevated
        self._elevated_handle = launch_elevated(
            exe_path=str(self._exe_path),
            args=cmd[1:],
            session_name=self._session_name,
            wait_for_child=True,
            child_timeout=15.0,
        )

        if not self._elevated_handle:
            self._state = "FAILED"
            self._error_reason = (
                "PresentMon elevation failed. "
                "UAC may have been cancelled."
            )
            logger.error(self._error_reason)
            # Cleanup CSV if it was partially created
            _cleanup_csv(self._csv_path)
            return False

        self._running = True
        self._state = "CAPTURING"

        # Wait for CSV to appear and grow
        csv_ready = False
        logger.info("Waiting for PresentMon CSV data...")
        for wait_i in range(20):
            time.sleep(1.0)

            if (
                self._csv_path
                and os.path.exists(self._csv_path)
                and os.path.getsize(self._csv_path) > 100
            ):
                csv_ready = True
                size = os.path.getsize(self._csv_path)
                logger.info(f"PresentMon CSV ready after {wait_i+1}s ({size} bytes)")
                break

            # Check if the process died before producing CSV
            if self._elevated_handle.pid:
                try:
                    proc = psutil.Process(self._elevated_handle.pid)
                    if not proc.is_running():
                        self._state = "FAILED"
                        self._error_reason = "PresentMon process exited unexpectedly"
                        logger.error(self._error_reason)
                        self._running = False
                        _cleanup_csv(self._csv_path)
                        return False
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

        if not csv_ready:
            logger.warning(
                "PresentMon CSV not ready after 20s. "
                "Process may still be initializing."
            )

        logger.info(
            f"PresentMon started: PID={self._elevated_handle.pid} "
            f"session={self._session_name} "
            f"csv={self._csv_path} "
            f"duration={duration}s"
        )
        return True

    def stop(self) -> bool:
        """
        Stop PresentMon and parse captured CSV data.

        Strategy: Wait for the elevated PresentMon to self-terminate,
        then parse the CSV. CSV cleanup happens in a finally block
        so it executes on success, failure, timeout, or exception.
        """
        if not self._running and not self._elevated_handle:
            # Try to parse existing CSV anyway
            if self._csv_path and os.path.exists(self._csv_path):
                try:
                    self._samples = self._parse_csv(self._csv_path)
                finally:
                    _cleanup_csv(self._csv_path)
                return bool(self._samples)
            return True

        self._state = "STOPPING"
        self._running = False

        try:
            # Wait for the elevated PresentMon to self-terminate
            if self._elevated_handle and self._elevated_handle.pid:
                logger.info(
                    f"Waiting for PresentMon PID={self._elevated_handle.pid} "
                    f"to self-terminate..."
                )
                try:
                    proc = psutil.Process(self._elevated_handle.pid)
                    gone, alive = psutil.wait_procs([proc], timeout=30)
                    if gone:
                        logger.info(f"PresentMon PID={self._elevated_handle.pid} exited")
                    elif alive:
                        logger.warning(
                            f"PresentMon PID={self._elevated_handle.pid} "
                            f"still running after 30s. "
                            f"CSV may still be locked."
                        )
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    logger.info("PresentMon process not accessible (may have exited)")

            self._elevated_handle = None

            # Wait for CSV to flush after process termination
            csv_found = False
            for wait_i in range(5):
                time.sleep(1.0)
                if (
                    self._csv_path
                    and os.path.exists(self._csv_path)
                    and os.path.getsize(self._csv_path) > 100
                ):
                    csv_found = True
                    break

            if csv_found:
                # Parse CSV with retry for file handle release
                for retry in range(5):
                    file_size = os.path.getsize(self._csv_path)
                    logger.info(
                        f"PresentMon CSV: {self._csv_path} "
                        f"({file_size} bytes, attempt {retry+1})"
                    )
                    try:
                        self._samples = self._parse_csv(self._csv_path)
                        logger.info(
                            f"PresentMon captured {len(self._samples)} frame samples"
                        )
                        break
                    except PermissionError:
                        logger.info(f"CSV file locked, waiting... (attempt {retry+1})")
                        time.sleep(2.0)
                    except Exception as e:
                        logger.error(f"CSV parse error: {e}")
                        break

                self._state = "COMPLETE" if self._samples else "FAILED"
            else:
                logger.warning("No PresentMon CSV output found")
                self._state = "FAILED"

        finally:
            # CRITICAL: Always clean up CSV file
            _cleanup_csv(self._csv_path)

            # Verify no stale PresentMon process remains
            if self._session_name:
                from app.performance.elevated_launcher import (
                    find_presentmon_processes,
                )
                remaining = find_presentmon_processes(
                    session_name=self._session_name
                )
                if remaining:
                    logger.warning(
                        f"{len(remaining)} stale PresentMon process(es) "
                        f"remaining for session {self._session_name}"
                    )

        return bool(self._samples)

    def _parse_csv(self, csv_path: str) -> list:
        """Parse PresentMon 2.5.1 CSV output for frame timestamps."""
        samples = []
        try:
            with open(csv_path, "r", encoding="utf-8-sig", errors="replace") as f:
                reader = csv.DictReader(f)

                if not reader.fieldnames:
                    logger.warning("PresentMon CSV has no headers")
                    return samples

                clean_fields = [fn.strip() for fn in reader.fieldnames]
                logger.info(
                    f"PresentMon CSV columns ({len(clean_fields)}): "
                    f"{clean_fields[:10]}..."
                )

                field_map = {}
                for fn in reader.fieldnames:
                    field_map[fn.strip().lower()] = fn

                def get_col(name):
                    return field_map.get(name.lower(), name)

                col_app = get_col(self.COL_APPLICATION)
                col_pid = get_col(self.COL_PROCESS_ID)
                col_time = get_col(self.COL_TIME)
                col_frame = get_col(self.COL_FRAME_TIME)
                col_display = get_col(self.COL_DISPLAY_TIME)
                col_cpu_busy = get_col(self.COL_CPU_BUSY)
                col_gpu_busy = get_col(self.COL_GPU_BUSY)
                col_gpu_time = get_col(self.COL_GPU_TIME)
                col_gpu_latency = get_col(self.COL_GPU_LATENCY)
                col_render_latency = get_col(self.COL_RENDER_LATENCY)
                col_displayed = get_col(self.COL_DISPLAYED)
                col_present_mode = get_col(self.COL_PRESENT_MODE)
                col_sync = get_col(self.COL_SYNC_INTERVAL)
                col_input_latency = get_col(self.COL_ALL_INPUT_LATENCY)

                def safe_float(row, col, default=0.0):
                    val = row.get(col, "")
                    if not val or val.strip() in ("NA", "", "N/A"):
                        return default
                    try:
                        return float(val)
                    except (ValueError, TypeError):
                        return default

                for row in reader:
                    try:
                        process_name = row.get(col_app, "").strip()
                        pid = int(safe_float(row, col_pid, 0))
                        time_ms = safe_float(row, col_time, 0)
                        if time_ms <= 0:
                            continue

                        frame_time_ms = safe_float(row, col_frame, 0)
                        display_ms = safe_float(row, col_display, 0)
                        cpu_ms = safe_float(row, col_cpu_busy, 0)
                        gpu_busy = safe_float(row, col_gpu_busy, 0)
                        gpu_time = safe_float(row, col_gpu_time, 0)
                        gpu_latency = safe_float(row, col_gpu_latency, 0)
                        render_latency = safe_float(row, col_render_latency, 0)
                        displayed_ms = safe_float(row, col_displayed, 0)
                        input_latency = safe_float(row, col_input_latency, 0)
                        present_mode = row.get(col_present_mode, "").strip()
                        sync_interval = int(safe_float(row, col_sync, 0))

                        sample = FrameSample(
                            timestamp=time_ms / 1000.0,
                            frame_time_ms=frame_time_ms,
                        )
                        sample.process_name = process_name
                        sample.pid = pid
                        sample.cpu_ms = cpu_ms
                        sample.display_ms = display_ms
                        sample.gpu_ms = gpu_time
                        sample.sync_interval = sync_interval
                        sample.present_mode = present_mode
                        sample.gpu_busy = gpu_busy
                        sample.gpu_latency = gpu_latency
                        sample.render_latency = render_latency
                        sample.displayed_ms = displayed_ms
                        sample.input_latency = input_latency

                        samples.append(sample)

                    except Exception as e:
                        logger.debug(f"CSV row parse error: {e}")
                        continue

        except Exception as e:
            logger.error(f"Failed to parse PresentMon CSV: {e}")

        return samples

    def is_running(self) -> bool:
        return self._running

    def get_samples(self) -> list:
        return self._samples

    def get_latest_sample(self) -> Optional[FrameSample]:
        return self._samples[-1] if self._samples else None

    def get_process_metrics(self, process_name: str) -> FPSMetrics:
        """Get metrics filtered to a specific process."""
        filtered = [
            s for s in self._samples
            if getattr(s, "process_name", "") == process_name
        ]
        if not filtered:
            return FPSMetrics(
                available=False,
                provider_name=f"{self.name} {self._version or ''}".strip()
            )

        frame_times = [
            s.frame_time_ms for s in filtered if s.frame_time_ms > 0
        ]
        if len(frame_times) < 2:
            return FPSMetrics(
                available=False,
                provider_name=f"{self.name} {self._version or ''}".strip()
            )

        return self._calculate_metrics(
            frame_times, f"{process_name} via {self.name}"
        )

    def get_target_pid(self) -> Optional[int]:
        """Get PID of the target process, if known."""
        if self._target_process:
            for s in self._samples:
                if getattr(s, "process_name", "") == self._target_process:
                    return getattr(s, "pid", None)
        return None

    def get_metrics(self) -> FPSMetrics:
        """Calculate metrics from all captured samples."""
        if not self._samples:
            return FPSMetrics(
                available=False,
                provider_name=f"{self.name} {self._version or ''}".strip()
            )

        frame_times = [
            s.frame_time_ms for s in self._samples if s.frame_time_ms > 0
        ]
        if len(frame_times) < 2:
            return FPSMetrics(
                available=False,
                provider_name=f"{self.name} {self._version or ''}".strip()
            )

        provider_label = f"{self.name} {self._version or ''}".strip()
        if self._target_process:
            provider_label += f" ({self._target_process})"
        return self._calculate_metrics(frame_times, provider_label)

    def _calculate_metrics(
        self, frame_times: list, provider_label: str = ""
    ) -> FPSMetrics:
        """Calculate real FPS metrics from actual frame presentation times."""
        import statistics

        n = len(frame_times)
        if n < 2:
            return FPSMetrics(
                available=False,
                provider_name=provider_label or self.name
            )

        fps_values = [1000.0 / ft for ft in frame_times if ft > 0]
        if not fps_values:
            return FPSMetrics(
                available=False,
                provider_name=provider_label or self.name
            )

        sorted_fps = sorted(fps_values)
        sorted_ft = sorted(frame_times)

        p1_idx = max(0, int(len(sorted_fps) * 0.01))
        p01_idx = max(0, int(len(sorted_fps) * 0.001))

        avg_ft = statistics.mean(frame_times)
        spike_threshold = avg_ft * 2

        return FPSMetrics(
            available=True,
            provider_name=provider_label or f"{self.name} {self._version or ''}".strip(),
            sample_count=n,
            duration_seconds=sum(frame_times) / 1000.0,
            avg_fps=statistics.mean(fps_values),
            median_fps=statistics.median(fps_values),
            min_fps=min(fps_values),
            max_fps=max(fps_values),
            one_percent_low=sorted_fps[p1_idx],
            point_one_percent_low=sorted_fps[p01_idx],
            avg_frame_time_ms=statistics.mean(frame_times),
            median_frame_time_ms=statistics.median(frame_times),
            frame_time_variance=(
                statistics.variance(frame_times) if n > 1 else 0
            ),
            frame_spikes=sum(
                1 for ft in frame_times if ft > spike_threshold
            ),
            frame_drops=sum(1 for ft in frame_times if ft > 100),
            stability_score=self._calc_stability(frame_times),
        )

    def _calc_stability(self, frame_times: list) -> float:
        """Calculate frame stability score (0-100)."""
        import statistics
        if len(frame_times) < 2:
            return 50
        mean = statistics.mean(frame_times)
        if mean <= 0:
            return 50
        cv = statistics.stdev(frame_times) / mean
        return max(0, min(100, 100 - (cv * 200)))
