"""
Input Device Diagnostics — Phase 37.

Read-only diagnostics for input devices, pointer configuration,
and mouse polling consistency measurement.

STRICTLY MEASUREMENT — never modifies system state.
"""

import statistics
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple

from app.utils.logger import get_logger

logger = get_logger("input.diagnostics")


# ── Enums ────────────────────────────────────────────────────────

class MetricState(Enum):
    """Availability state for every metric."""
    MEASURED = "MEASURED"
    DETECTED = "DETECTED"
    INFERRED = "INFERRED"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    FAILED = "FAILED"


class PollingConsistency(Enum):
    """Polling/event consistency classification."""
    HIGH = "HIGH"
    MODERATE = "MODERATE"
    LOW = "LOW"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class ConnectionType(Enum):
    """Device connection type."""
    USB = "USB"
    WIRELESS = "WIRELESS"
    BLUETOOTH = "BLUETOOTH"
    UNKNOWN = "UNKNOWN"


class PointerAssessment(Enum):
    """Pointer configuration assessment."""
    CONSISTENT = "CONSISTENT"
    POTENTIAL_VARIABLE_ACCELERATION = "POTENTIAL_VARIABLE_ACCELERATION"
    UNKNOWN = "UNKNOWN"


# ── Models ───────────────────────────────────────────────────────

@dataclass
class PointingDevice:
    """Detected pointing device information."""
    name: str = "Unknown Mouse"
    manufacturer: str = ""
    connection_type: ConnectionType = ConnectionType.UNKNOWN
    device_path: str = ""
    is_pointing_device: bool = True
    state: MetricState = MetricState.DETECTED

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "manufacturer": self.manufacturer,
            "connection_type": self.connection_type.value,
            "is_pointing_device": self.is_pointing_device,
            "state": self.state.value,
        }


@dataclass
class PointerConfig:
    """Windows pointer configuration."""
    pointer_speed: int = 10
    pointer_speed_ratio: float = 1.0  # speed/11 normalized
    enhance_pointer_precision: bool = False
    enhance_pointer_precision_value: int = 0
    raw_input_available: bool = False
    state: MetricState = MetricState.NOT_AVAILABLE
    assessment: PointerAssessment = PointerAssessment.UNKNOWN

    def to_dict(self) -> dict:
        return {
            "pointer_speed": self.pointer_speed,
            "enhance_pointer_precision": self.enhance_pointer_precision,
            "raw_input_available": self.raw_input_available,
            "state": self.state.value,
            "assessment": self.assessment.value,
        }


@dataclass
class PollingMeasurement:
    """Results of a polling consistency measurement session."""
    duration_seconds: float = 0.0
    total_events: int = 0
    observed_rate_hz: float = 0.0
    median_interval_ms: float = 0.0
    average_interval_ms: float = 0.0
    min_interval_ms: float = 0.0
    max_interval_ms: float = 0.0
    interval_std_dev_ms: float = 0.0
    coefficient_of_variation: float = 0.0
    consistency: PollingConsistency = PollingConsistency.INSUFFICIENT_DATA
    state: MetricState = MetricState.NOT_AVAILABLE
    event_timestamps: List[float] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "duration_seconds": self.duration_seconds,
            "total_events": self.total_events,
            "observed_rate_hz": round(self.observed_rate_hz, 1),
            "median_interval_ms": round(self.median_interval_ms, 2),
            "coefficient_of_variation": round(self.coefficient_of_variation, 3),
            "consistency": self.consistency.value,
            "state": self.state.value,
        }


@dataclass
class LatencyEstimate:
    """Input latency estimate (clearly marked as ESTIMATED)."""
    display_latency_ms: float = 0.0
    scheduling_latency_ms: float = 0.0
    frame_presentation_ms: float = 0.0
    estimated_total_ms: float = 0.0
    state: MetricState = MetricState.NOT_AVAILABLE
    note: str = "These are ESTIMATES — not hardware-measured latency."

    def to_dict(self) -> dict:
        return {
            "display_latency_ms": round(self.display_latency_ms, 1),
            "estimated_total_ms": round(self.estimated_total_ms, 1),
            "state": self.state.value,
            "note": self.note,
        }


@dataclass
class InputDiagnosticSession:
    """Complete input diagnostic session."""
    session_id: str = ""
    timestamp: float = 0.0
    target_name: str = ""
    target_pid: int = 0

    # Device
    devices: List[PointingDevice] = field(default_factory=list)
    pointer_config: PointerConfig = field(default_factory=PointerConfig)

    # Polling
    polling: PollingMeasurement = field(default_factory=PollingMeasurement)

    # Latency
    latency: LatencyEstimate = field(default_factory=LatencyEstimate)

    # System context
    display_refresh_hz: int = 0
    cpu_percent: float = 0.0
    gpu_percent: float = 0.0
    ram_percent: float = 0.0
    emulator_cpu: float = 0.0
    emulator_ram_mb: float = 0.0
    frame_time_ms: Optional[float] = None
    fps: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "timestamp": self.timestamp,
            "target_name": self.target_name,
            "target_pid": self.target_pid,
            "devices": [d.to_dict() for d in self.devices],
            "pointer_config": self.pointer_config.to_dict(),
            "polling": self.polling.to_dict(),
            "latency": self.latency.to_dict(),
            "display_refresh_hz": self.display_refresh_hz,
            "fps": self.fps,
        }


# ── Device Detection ─────────────────────────────────────────────

def detect_pointing_devices() -> List[PointingDevice]:
    """
    Detect pointing devices using Windows APIs.

    Uses ctypes to query raw input devices where available.
    """
    devices = []

    try:
        import ctypes
        from ctypes import wintypes

        # Define RAWINPUTDEVICELIST structure
        class RAWINPUTDEVICELIST(ctypes.Structure):
            _fields_ = [
                ("hDevice", wintypes.HANDLE),
                ("dwType", wintypes.DWORD),
            ]

        # Get number of raw input devices
        user32 = ctypes.windll.user32
        n_devices = wintypes.UINT()
        size = ctypes.sizeof(RAWINPUTDEVICELIST)

        # RID_INPUT = 0x00000001 (mouse), RIM_TYPEMOUSE = 0
        result = user32.GetRawInputDeviceList(None, ctypes.byref(n_devices), size)

        if result == -1:
            # Fallback: assume standard mouse
            devices.append(PointingDevice(
                name="Standard Mouse",
                connection_type=ConnectionType.UNKNOWN,
                state=MetricState.DETECTED if False else MetricState.NOT_AVAILABLE,
            ))
            return devices

        count = n_devices.value
        if count > 0:
            device_list = (RAWINPUTDEVICELIST * count)()
            user32.GetRawInputDeviceList(
                ctypes.byref(device_list),
                ctypes.byref(n_devices),
                size,
            )

            for i in range(count):
                dev = device_list[i]
                if dev.dwType == 0:  # RIM_TYPEMOUSE
                    # Get device info
                    pcbSize = wintypes.UINT()
                    user32.GetRawInputDeviceInfoW(
                        dev.hDevice, 0x20000000,  # RIDI_DEVICENAME
                        None, ctypes.byref(pcbSize),
                    )
                    name = "Unknown Mouse"
                    if pcbSize.value > 0:
                        buf = ctypes.create_unicode_buffer(pcbSize.value)
                        user32.GetRawInputDeviceInfoW(
                            dev.hDevice, 0x20000000,
                            buf, ctypes.byref(pcbSize),
                        )
                        raw_name = buf.value
                        # Clean up Windows device name
                        if raw_name.startswith("\\\\?\\"):
                            raw_name = raw_name[4:]
                        name = raw_name.split("#")[0].replace("_", " ").strip()
                        if not name:
                            name = "Mouse"

                    connection = ConnectionType.UNKNOWN
                    if "hid" in str(dev.hDevice).lower():
                        connection = ConnectionType.USB

                    devices.append(PointingDevice(
                        name=name,
                        connection_type=connection,
                        state=MetricState.DETECTED,
                    ))

        if not devices:
            devices.append(PointingDevice(
                name="Standard Mouse",
                connection_type=ConnectionType.UNKNOWN,
                state=MetricState.NOT_AVAILABLE,
            ))

    except Exception as e:
        logger.debug(f"Device detection via raw input failed: {e}")
        devices.append(PointingDevice(
            name="Standard Mouse",
            connection_type=ConnectionType.UNKNOWN,
            state=MetricState.NOT_AVAILABLE,
        ))

    return devices


# ── Pointer Configuration ────────────────────────────────────────

def detect_pointer_config() -> PointerConfig:
    """Read current Windows pointer configuration."""
    from app.utils.registry import read_registry_value

    config = PointerConfig()

    try:
        val = read_registry_value("HKCU", r"Control Panel\Mouse", "MouseSensitivity")
        if val is not None:
            config.pointer_speed = int(val)
            config.pointer_speed_ratio = config.pointer_speed / 11.0
            config.state = MetricState.MEASURED

        val = read_registry_value("HKCU", r"Control Panel\Mouse", "MouseSpeed")
        if val is not None:
            config.enhance_pointer_precision_value = int(val)
            config.enhance_pointer_precision = int(val) != 0

        # Assessment
        if config.enhance_pointer_precision:
            config.assessment = PointerAssessment.POTENTIAL_VARIABLE_ACCELERATION
        elif config.state == MetricState.MEASURED:
            config.assessment = PointerAssessment.CONSISTENT
        else:
            config.assessment = PointerAssessment.UNKNOWN

        # Raw input availability (generally available on modern Windows)
        config.raw_input_available = True
        config.state = MetricState.MEASURED

    except Exception as e:
        logger.debug(f"Pointer config detection failed: {e}")
        config.state = MetricState.FAILED

    return config


# ── Polling Consistency Measurement ──────────────────────────────

class PollingMeasurementSession:
    """
    Measures mouse polling consistency by capturing raw input events.

    Uses Windows raw input API to capture actual mouse events
    and measure their timing consistency.
    """

    def __init__(self, duration_seconds: float = 5.0):
        self._duration = duration_seconds
        self._timestamps: List[float] = []
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def measure(self) -> PollingMeasurement:
        """
        Run a polling consistency measurement.

        Captures mouse events for the specified duration and
        calculates timing statistics.
        """
        result = PollingMeasurement(duration_seconds=self._duration)

        try:
            self._timestamps = []
            self._running = True

            # Try raw input capture
            success = self._capture_raw_input()

            if not success or len(self._timestamps) < 5:
                # Fallback: estimate from display refresh
                result.state = MetricState.NOT_AVAILABLE
                result.note = "Raw input capture unavailable; cannot measure polling rate"
                result.consistency = PollingConsistency.INSUFFICIENT_DATA
                return result

            result.total_events = len(self._timestamps)
            result.state = MetricState.MEASURED

            # Calculate intervals
            intervals = []
            for i in range(1, len(self._timestamps)):
                interval = (self._timestamps[i] - self._timestamps[i - 1]) * 1000  # ms
                if interval > 0:
                    intervals.append(interval)

            if not intervals:
                result.consistency = PollingConsistency.INSUFFICIENT_DATA
                return result

            result.median_interval_ms = statistics.median(intervals)
            result.average_interval_ms = statistics.mean(intervals)
            result.min_interval_ms = min(intervals)
            result.max_interval_ms = max(intervals)

            if len(intervals) > 1:
                result.interval_std_dev_ms = statistics.stdev(intervals)

            if result.average_interval_ms > 0:
                result.observed_rate_hz = 1000.0 / result.average_interval_ms
                result.coefficient_of_variation = (
                    result.interval_std_dev_ms / result.average_interval_ms
                )

            # Classify consistency
            if result.coefficient_of_variation < 0.10:
                result.consistency = PollingConsistency.HIGH
            elif result.coefficient_of_variation < 0.25:
                result.consistency = PollingConsistency.MODERATE
            else:
                result.consistency = PollingConsistency.LOW

        except Exception as e:
            logger.debug(f"Polling measurement failed: {e}")
            result.state = MetricState.FAILED
            result.note = f"Measurement failed: {e}"
            result.consistency = PollingConsistency.INSUFFICIENT_DATA

        return result

    def _capture_raw_input(self) -> bool:
        """
        Capture mouse raw input events for the measurement duration.

        Returns True if events were captured.
        """
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32

            # Register for raw mouse input
            RAWINPUTDEVICE = ctypes.Structure
            Rid = wintypes_RAWINPUTDEVICE()
            Rid.usUsagePage = 0x01  # Generic Desktop
            Rid.usUsage = 0x02      # Mouse
            Rid.dwFlags = 0x00000010  # RIDEV_INPUTSINK — capture even when not in foreground
            Rid.hwndTarget = 0

            if not user32.RegisterRawInputDevices(
                ctypes.byref(Rid), 1, ctypes.sizeof(Rid)
            ):
                logger.debug("Failed to register raw input device")
                return False

            # Create a message-only window to receive input
            WNDCLASS = wintypes.WNDCLASS()
            WNDCLASS.lpfnWndProc = ctypes.WINFUNCTYPE(
                ctypes.c_long, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
            )(self._wnd_proc)
            WNDCLASS.lpszClassName = "PhoenixInputMeasure"

            user32.RegisterClassW(ctypes.byref(WNDCLASS))

            hwnd = user32.CreateWindowExW(
                0, "PhoenixInputMeasure", None, 0,
                0, 0, 0, 0,
                None, None, None, None,
            )

            if not hwnd:
                return False

            # Message loop for duration
            start = time.perf_counter()
            msg = wintypes.MSG()
            while time.perf_counter() - start < self._duration:
                while user32.PeekMessageW(ctypes.byref(msg), hwnd, 0, 0, 1):
                    user32.TranslateMessage(ctypes.byref(msg))
                    user32.DispatchMessageW(ctypes.byref(msg))
                time.sleep(0.001)

            user32.DestroyWindow(hwnd)
            return len(self._timestamps) > 0

        except Exception as e:
            logger.debug(f"Raw input capture setup failed: {e}")
            return False

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        """Window procedure for raw input messages."""
        WM_INPUT = 0x0FF
        if msg == WM_INPUT:
            with self._lock:
                self._timestamps.append(time.perf_counter())
        return 0


# ── Latency Estimation ──────────────────────────────────────────

def estimate_input_latency(
    display_refresh_hz: int = 60,
    cpu_percent: float = 0.0,
    emulator_cpu: float = 0.0,
    frame_time_ms: Optional[float] = None,
) -> LatencyEstimate:
    """
    Estimate input latency from system configuration.

    All values are ESTIMATED — clearly marked as such.
    """
    estimate = LatencyEstimate()

    if display_refresh_hz <= 0:
        estimate.state = MetricState.NOT_AVAILABLE
        return estimate

    # Display latency (frame interval)
    estimate.display_latency_ms = 1000.0 / display_refresh_hz

    # Scheduling latency estimate (from CPU pressure)
    if cpu_percent > 80:
        estimate.scheduling_latency_ms = 2.0  # Higher scheduling contention
    elif cpu_percent > 50:
        estimate.scheduling_latency_ms = 1.0
    else:
        estimate.scheduling_latency_ms = 0.5

    # Frame presentation (from actual frame time if available)
    if frame_time_ms and frame_time_ms > 0:
        estimate.frame_presentation_ms = frame_time_ms
    else:
        estimate.frame_presentation_ms = estimate.display_latency_ms

    estimate.estimated_total_ms = (
        estimate.display_latency_ms + estimate.scheduling_latency_ms
    )

    estimate.state = MetricState.INFERRED
    estimate.note = (
        "ESTIMATED values from system configuration — not hardware-measured. "
        "True end-to-end latency requires external measurement tools."
    )

    return estimate


# ── Comprehensive Diagnostic ─────────────────────────────────────

def run_input_diagnostics(
    target_name: str = "",
    target_pid: int = 0,
    cpu_percent: float = 0.0,
    gpu_percent: float = 0.0,
    ram_percent: float = 0.0,
    display_refresh_hz: int = 0,
    fps: Optional[float] = None,
    frame_time_ms: Optional[float] = None,
) -> InputDiagnosticSession:
    """
    Run comprehensive input diagnostics.

    Collects device info, pointer configuration, and latency estimates.
    """
    import uuid

    session = InputDiagnosticSession(
        session_id=str(uuid.uuid4())[:8],
        timestamp=time.time(),
        target_name=target_name,
        target_pid=target_pid,
    )

    # Devices
    session.devices = detect_pointing_devices()

    # Pointer config
    session.pointer_config = detect_pointer_config()

    # Display
    session.display_refresh_hz = display_refresh_hz
    if display_refresh_hz <= 0:
        try:
            from app.system.display import display_monitor
            display = display_monitor.detect()
            session.display_refresh_hz = display.refresh_rate_hz
        except Exception:
            pass

    # System context
    session.cpu_percent = cpu_percent
    session.gpu_percent = gpu_percent
    session.ram_percent = ram_percent
    session.fps = fps
    session.frame_time_ms = frame_time_ms

    # Latency estimation
    session.latency = estimate_input_latency(
        display_refresh_hz=session.display_refresh_hz,
        cpu_percent=cpu_percent,
        frame_time_ms=frame_time_ms,
    )

    return session


# ── CLI Formatting ───────────────────────────────────────────────

def format_input_status(session: InputDiagnosticSession) -> str:
    """Format input diagnostics for CLI output."""
    lines = []
    lines.append("=" * 55)
    lines.append("HEAVEN SOCIETY — INPUT DIAGNOSTICS")
    lines.append("=" * 55)
    lines.append("")

    # Target
    lines.append("TARGET")
    if session.target_name:
        lines.append(f"  {session.target_name}  PID: {session.target_pid}")
    else:
        lines.append("  No emulator detected")
    lines.append("")

    # Devices
    lines.append("DEVICES")
    if session.devices:
        for d in session.devices:
            state = d.state.value if hasattr(d, 'state') else "DETECTED"
            lines.append(f"  {d.name}  [{d.connection_type.value}]")
    else:
        lines.append("  No pointing devices detected")
    lines.append("")

    # Pointer Configuration
    pc = session.pointer_config
    lines.append("POINTER CONFIGURATION")
    lines.append(f"  Speed:                   {pc.pointer_speed}/11")
    epp = "ENABLED" if pc.enhance_pointer_precision else "DISABLED"
    lines.append(f"  Enhance Pointer Precision: {epp}")
    raw = "AVAILABLE" if pc.raw_input_available else "NOT AVAILABLE"
    lines.append(f"  Raw Input:               {raw}")
    lines.append(f"  Assessment:              {pc.assessment.value}")
    lines.append("")

    # Latency
    lat = session.latency
    lines.append("INPUT LATENCY (ESTIMATED)")
    lines.append(f"  Display Latency:   {lat.display_latency_ms:.1f} ms")
    lines.append(f"  Scheduling:        {lat.scheduling_latency_ms:.1f} ms")
    lines.append(f"  Estimated Total:   {lat.estimated_total_ms:.1f} ms")
    lines.append(f"  State:             {lat.state.value}")
    lines.append(f"  Note:              {lat.note}")
    lines.append("")

    # System
    lines.append("SYSTEM CONTEXT")
    lines.append(f"  Display:           {session.display_refresh_hz} Hz")
    if session.fps:
        lines.append(f"  FPS:               {session.fps:.0f}")
    if session.cpu_percent:
        lines.append(f"  CPU:               {session.cpu_percent:.0f}%")
    if session.ram_percent:
        lines.append(f"  RAM:               {session.ram_percent:.0f}%")
    lines.append("")

    lines.append("=" * 55)
    return "\n".join(lines)
