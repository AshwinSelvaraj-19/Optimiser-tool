"""
GPU monitoring and detection module.
Supports NVIDIA (via pynvml), AMD, and Intel integrated GPUs.
"""

import time
from dataclasses import dataclass, field
from typing import Optional

from app.utils.logger import get_logger

logger = get_logger("system.gpu")

# Try importing pynvml for NVIDIA
# Suppress FutureWarning about pynvml deprecation — it still works fine
import warnings as _warnings
_warnings.filterwarnings("ignore", category=FutureWarning, message=".*pynvml.*")
try:
    import pynvml
    NVML_AVAILABLE = True
except ImportError:
    NVML_AVAILABLE = False
    logger.debug("pynvml not available — NVIDIA GPU telemetry limited")


@dataclass
class GPUInfo:
    """Comprehensive GPU information."""
    name: str = "Unknown"
    vendor: str = "Unknown"
    index: int = 0
    driver_version: str = "Unknown"
    vram_total_mb: float = 0.0
    vram_used_mb: float = 0.0
    vram_free_mb: float = 0.0
    utilization_percent: float = 0.0
    utilization_gpu: float = 0.0
    utilization_memory: float = 0.0
    clock_core_mhz: float = 0.0
    clock_memory_mhz: float = 0.0
    temperature_celsius: Optional[float] = None
    power_draw_watts: Optional[float] = None
    power_limit_watts: Optional[float] = None
    power_state: str = "Unknown"
    fan_speed_percent: Optional[float] = None
    is_discrete: bool = False
    is_integrated: bool = False
    pci_bus: str = ""
    supports_nvenc: bool = False
    supports_cuda: bool = False
    cuda_cores: int = 0
    compute_capability: str = ""


class GPUMonitor:
    """GPU detection and monitoring with multi-vendor support."""

    def __init__(self):
        self._nvml_initialized = False

    def _init_nvml(self) -> bool:
        """Initialize NVIDIA Management Library."""
        if not NVML_AVAILABLE:
            return False
        if self._nvml_initialized:
            return True
        try:
            pynvml.nvmlInit()
            self._nvml_initialized = True
            return True
        except Exception as e:
            logger.debug(f"NVML init failed: {e}")
            return False

    def detect(self) -> list:
        """Detect all available GPUs."""
        gpus = []

        # Try NVIDIA
        nvidia_gpus = self._detect_nvidia()
        gpus.extend(nvidia_gpus)

        # Try WMI for any GPU
        if not gpus:
            wmi_gpus = self._detect_wmi()
            gpus.extend(wmi_gpus)

        if not gpus:
            logger.warning("No GPUs detected")
            gpus.append(GPUInfo(name="No GPU Detected", vendor="Unknown"))

        for gpu in gpus:
            gpu_type = "discrete" if gpu.is_discrete else ("integrated" if gpu.is_integrated else "unknown")
            logger.info(f"GPU detected: {gpu.name} ({gpu.vendor}, {gpu_type})")

        return gpus

    def _detect_nvidia(self) -> list:
        """Detect NVIDIA GPUs via NVML."""
        gpus = []
        if not self._init_nvml():
            return gpus

        try:
            count = pynvml.nvmlDeviceGetCount()
            for i in range(count):
                try:
                    handle = pynvml.nvmlDeviceGetHandleByIndex(i)
                    info = GPUInfo()
                    info.index = i
                    info.vendor = "NVIDIA"
                    info.is_discrete = True
                    info.is_integrated = False

                    try:
                        info.name = pynvml.nvmlDeviceGetName(handle)
                        if isinstance(info.name, bytes):
                            info.name = info.name.decode("utf-8")
                    except Exception:
                        info.name = "NVIDIA GPU"

                    try:
                        info.driver_version = pynvml.nvmlSystemGetDriverVersion()
                        if isinstance(info.driver_version, bytes):
                            info.driver_version = info.driver_version.decode("utf-8")
                    except Exception:
                        pass

                    # Memory
                    try:
                        mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
                        info.vram_total_mb = mem.total / (1024 * 1024)
                        info.vram_used_mb = mem.used / (1024 * 1024)
                        info.vram_free_mb = mem.free / (1024 * 1024)
                    except Exception:
                        pass

                    # PCI info
                    try:
                        pci = pynvml.nvmlDeviceGetPciInfo(handle)
                        info.pci_bus = f"{pci.bus:#04x}"
                    except Exception:
                        pass

                    # CUDA support
                    try:
                        info.supports_cuda = True
                        major, minor = pynvml.nvmlDeviceGetCudaComputeCapability(handle)
                        info.compute_capability = f"{major}.{minor}"
                    except Exception:
                        pass

                    gpus.append(info)
                except Exception as e:
                    logger.warning(f"Error detecting NVIDIA GPU {i}: {e}")
        except Exception as e:
            logger.debug(f"NVML count failed: {e}")

        return gpus

    def _detect_wmi(self) -> list:
        """Detect GPUs via WMI as fallback."""
        gpus = []
        try:
            import pythoncom
            pythoncom.CoInitialize()
            try:
                import wmi
                w = wmi.WMI(namespace="root\\cimv2")
                for gpu in w.Win32_VideoController():
                    info = GPUInfo()
                    info.name = gpu.Name or "Unknown GPU"
                    info.vendor = self._identify_vendor(info.name)

                    if hasattr(gpu, "AdapterRAM") and gpu.AdapterRAM:
                        info.vram_total_mb = gpu.AdapterRAM / (1024 * 1024)

                    info.driver_version = gpu.DriverVersion or "Unknown"
                    info.is_integrated = info.vendor in ("Intel",) and "UHD" in info.name.lower()
                    info.is_discrete = info.vendor in ("NVIDIA", "AMD") and not info.is_integrated

                    gpus.append(info)
            finally:
                pythoncom.CoUninitialize()

        except ImportError:
            logger.debug("WMI or pythoncom not available for GPU detection")
        except Exception as e:
            logger.error(f"WMI GPU detection error: {e}")

        return gpus

    def _identify_vendor(self, name: str) -> str:
        """Identify GPU vendor from name string."""
        name_lower = name.lower()
        if "nvidia" in name_lower or "geforce" in name_lower or "rtx" in name_lower or "gtx" in name_lower:
            return "NVIDIA"
        elif "amd" in name_lower or "radeon" in name_lower or "rx" in name_lower:
            return "AMD"
        elif "intel" in name_lower or "uhd" in name_lower or "iris" in name_lower:
            return "Intel"
        return "Unknown"

    def update_nvidia(self, gpu: GPUInfo) -> GPUInfo:
        """Update dynamic NVIDIA GPU metrics."""
        if not self._init_nvml():
            return gpu

        try:
            handle = pynvml.nvmlDeviceGetHandleByIndex(gpu.index)

            # Utilization
            try:
                util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                gpu.utilization_gpu = util.gpu
                gpu.utilization_memory = util.memory
                gpu.utilization_percent = util.gpu
            except Exception:
                pass

            # Clocks
            try:
                gpu.clock_core_mhz = pynvml.nvmlDeviceGetClockInfo(handle, pynvml.NVML_CLOCK_GRAPHICS)
                gpu.clock_memory_mhz = pynvml.nvmlDeviceGetClockInfo(handle, pynvml.NVML_CLOCK_MEM)
            except Exception:
                pass

            # Temperature
            try:
                gpu.temperature_celsius = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
            except Exception:
                pass

            # Power
            try:
                gpu.power_draw_watts = pynvml.nvmlDeviceGetPowerUsage(handle) / 1000.0
            except Exception:
                pass

            try:
                gpu.power_limit_watts = pynvml.nvmlDeviceGetPowerManagementLimit(handle) / 1000.0
            except Exception:
                pass

            # Power state
            try:
                perf_state = pynvml.nvmlDeviceGetPerformanceState(handle)
                gpu.power_state = f"P{perf_state}"
            except Exception:
                pass

            # Fan
            try:
                gpu.fan_speed_percent = pynvml.nvmlDeviceGetFanSpeed(handle)
            except Exception:
                pass

            # Memory update
            try:
                mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
                gpu.vram_used_mb = mem.used / (1024 * 1024)
                gpu.vram_free_mb = mem.free / (1024 * 1024)
            except Exception:
                pass

        except Exception as e:
            logger.error(f"NVIDIA GPU update error: {e}")

        return gpu

    def update(self, gpu: GPUInfo) -> GPUInfo:
        """Update GPU metrics based on vendor."""
        if gpu.vendor == "NVIDIA":
            return self.update_nvidia(gpu)
        # AMD/Intel updates would go here — limited without vendor SDKs
        return gpu

    def get_discrete_gpu(self, gpus: list) -> Optional[GPUInfo]:
        """Get the primary discrete GPU."""
        for gpu in gpus:
            if gpu.is_discrete:
                return gpu
        return gpus[0] if gpus else None

    def cleanup(self):
        """Shutdown NVML."""
        if self._nvml_initialized:
            try:
                pynvml.nvmlShutdown()
            except Exception:
                pass
            self._nvml_initialized = False


# Singleton
gpu_monitor = GPUMonitor()
