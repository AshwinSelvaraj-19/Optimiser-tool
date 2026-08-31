"""
GPU monitoring and detection module.
Supports NVIDIA (via pynvml), AMD, and Intel integrated GPUs.
"""

import os
import time
from dataclasses import dataclass, field
from typing import Optional

from app.utils.logger import get_logger

logger = get_logger("system.gpu")

# Try importing pynvml for NVIDIA
# Suppress FutureWarning about pynvml deprecation — it still works fine
import warnings

try:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        warnings.simplefilter("ignore", FutureWarning)
        try:
            import pynvml

            pynvml.nvmlInit()
            NVML_AVAILABLE = True
        except Exception:
            NVML_AVAILABLE = False
            pynvml = None
except Exception:
    NVML_AVAILABLE = False
    pynvml = None


@dataclass
class GPUInfo:
    """GPU information."""

    name: str = "Unknown GPU"
    vendor: str = "Unknown"
    driver_version: str = ""
    vram_total_mb: float = 0.0
    vram_used_mb: float = 0.0
    temperature_celsius: float = 0.0
    utilization_gpu: float = 0.0
    utilization_memory: float = 0.0
    power_draw_watts: float = 0.0
    clock_core_mhz: float = 0.0
    clock_memory_mhz: float = 0.0
    is_discrete: bool = False
    is_integrated: bool = False
    uuid: str = ""
    pci_bus: str = ""


class GPUMonitor:
    """GPU detection and monitoring."""

    def __init__(self):
        self._gpus: list = []
        self._last_update: float = 0
        self._update_interval: float = 1.0  # Minimum 1s between updates

    def detect(self) -> list:
        """Detect all GPUs in the system."""
        gpus = []
        nvml_names = set()

        # Try NVIDIA via NVML first
        if NVML_AVAILABLE:
            try:
                nvml_gpus = self._detect_nvml()
                gpus.extend(nvml_gpus)
                for g in nvml_gpus:
                    nvml_names.add(g.name)
            except Exception as e:
                logger.debug(f"NVML detection error: {e}")

        # Try WMI for any GPU (skip duplicates already found via NVML)
        try:
            wmi_gpus = self._detect_wmi()
            for wgpu in wmi_gpus:
                if wgpu.name not in nvml_names:
                    gpus.append(wgpu)
                else:
                    # Merge WMI info into NVML entry if needed
                    for nvml_gpu in gpus:
                        if nvml_gpu.name == wgpu.name:
                            if not nvml_gpu.driver_version and wgpu.driver_version:
                                nvml_gpu.driver_version = wgpu.driver_version
                            break
        except Exception as e:
            logger.debug(f"WMI GPU detection error: {e}")

        # If nothing found, report unknown
        if not gpus:
            info = GPUInfo()
            info.name = "No GPU detected"
            gpus.append(info)

        self._gpus = gpus
        for gpu in gpus:
            gpu_type = (
                "Discrete"
                if gpu.is_discrete
                else ("Integrated" if gpu.is_integrated else "Unknown")
            )
            logger.info(f"GPU detected: {gpu.name} ({gpu.vendor}, {gpu_type})")

        return gpus

    def _detect_nvml(self) -> list:
        """Detect NVIDIA GPUs via NVML."""
        gpus = []
        try:
            device_count = pynvml.nvmlDeviceGetCount()
            for i in range(device_count):
                handle = pynvml.nvmlDeviceGetHandleByIndex(i)
                info = GPUInfo()

                # Name
                try:
                    info.name = pynvml.nvmlDeviceGetName(handle)
                    if isinstance(info.name, bytes):
                        info.name = info.name.decode("utf-8")
                except Exception:
                    info.name = f"NVIDIA GPU {i}"

                # UUID
                try:
                    info.uuid = pynvml.nvmlDeviceGetUUID(handle)
                    if isinstance(info.uuid, bytes):
                        info.uuid = info.uuid.decode("utf-8")
                except Exception:
                    pass

                # PCI bus
                try:
                    pci = pynvml.nvmlDeviceGetPciInfo(handle)
                    info.pci_bus = f"{pci.bus:02X}:{pci.device:02X}.{pci.function:02X}"
                except Exception:
                    pass

                # VRAM
                try:
                    mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
                    info.vram_total_mb = mem.total / (1024 * 1024)
                    info.vram_used_mb = mem.used / (1024 * 1024)
                except Exception:
                    pass

                # Temperature
                try:
                    info.temperature_celsius = pynvml.nvmlDeviceGetTemperature(
                        handle, pynvml.NVML_TEMPERATURE_GPU
                    )
                except Exception:
                    pass

                # Utilization
                try:
                    util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                    info.utilization_gpu = util.gpu
                    info.utilization_memory = util.memory
                except Exception:
                    pass

                # Power
                try:
                    info.power_draw_watts = pynvml.nvmlDeviceGetPowerUsage(handle) / 1000.0
                except Exception:
                    pass

                # Clocks
                try:
                    info.clock_core_mhz = pynvml.nvmlDeviceGetClockInfo(
                        handle, pynvml.NVML_CLOCK_GRAPHICS
                    )
                    info.clock_memory_mhz = pynvml.nvmlDeviceGetClockInfo(
                        handle, pynvml.NVML_CLOCK_MEM
                    )
                except Exception:
                    pass

                # Driver version
                try:
                    info.driver_version = pynvml.nvmlSystemGetDriverVersion()
                    if isinstance(info.driver_version, bytes):
                        info.driver_version = info.driver_version.decode("utf-8")
                except Exception:
                    pass

                info.vendor = "NVIDIA"
                info.is_discrete = True
                gpus.append(info)

        except Exception as e:
            logger.debug(f"NVML enumeration error: {e}")

        return gpus

    def _detect_wmi(self) -> list:
        """Detect GPUs via WMI as fallback."""
        gpus = []
        try:
            import pythoncom

            pythoncom.CoInitialize()
            # Suppress harmless pywin32 IUnknown::Release() SEH exceptions
            _devnull_fd = os.open(os.devnull, os.O_WRONLY)
            _old_stderr_fd = os.dup(2)
            os.dup2(_devnull_fd, 2)
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
                    info.is_integrated = (
                        info.vendor in ("Intel",) and "UHD" in info.name.lower()
                    )
                    info.is_discrete = (
                        info.vendor in ("NVIDIA", "AMD") and not info.is_integrated
                    )

                    gpus.append(info)
                del w
            finally:
                pythoncom.CoUninitialize()
                os.dup2(_old_stderr_fd, 2)
                os.close(_old_stderr_fd)
                os.close(_devnull_fd)

        except ImportError:
            logger.debug("WMI or pythoncom not available for GPU detection")
        except Exception as e:
            logger.error(f"WMI GPU detection error: {e}")

        return gpus

    def _identify_vendor(self, name: str) -> str:
        """Identify GPU vendor from name."""
        name_lower = name.lower()
        if (
            "nvidia" in name_lower
            or "geforce" in name_lower
            or "rtx" in name_lower
            or "gtx" in name_lower
        ):
            return "NVIDIA"
        elif "amd" in name_lower or "radeon" in name_lower:
            return "AMD"
        elif "intel" in name_lower:
            return "Intel"
        return "Unknown"

    def update_nvidia(self, gpu_info: GPUInfo) -> GPUInfo:
        """Update GPU info with latest NVML readings."""
        if not NVML_AVAILABLE:
            return gpu_info

        try:
            device_count = pynvml.nvmlDeviceGetCount()
            for i in range(device_count):
                handle = pynvml.nvmlDeviceGetHandleByIndex(i)
                try:
                    name = pynvml.nvmlDeviceGetName(handle)
                    if isinstance(name, bytes):
                        name = name.decode("utf-8")
                    if name == gpu_info.name:
                        try:
                            mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
                            gpu_info.vram_total_mb = mem.total / (1024 * 1024)
                            gpu_info.vram_used_mb = mem.used / (1024 * 1024)
                        except Exception:
                            pass

                        try:
                            gpu_info.temperature_celsius = pynvml.nvmlDeviceGetTemperature(
                                handle, pynvml.NVML_TEMPERATURE_GPU
                            )
                        except Exception:
                            pass

                        try:
                            util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                            gpu_info.utilization_gpu = util.gpu
                            gpu_info.utilization_memory = util.memory
                        except Exception:
                            pass

                        try:
                            gpu_info.power_draw_watts = (
                                pynvml.nvmlDeviceGetPowerUsage(handle) / 1000.0
                            )
                        except Exception:
                            pass

                        try:
                            gpu_info.clock_core_mhz = pynvml.nvmlDeviceGetClockInfo(
                                handle, pynvml.NVML_CLOCK_GRAPHICS
                            )
                            gpu_info.clock_memory_mhz = pynvml.nvmlDeviceGetClockInfo(
                                handle, pynvml.NVML_CLOCK_MEM
                            )
                        except Exception:
                            pass

                        break
                except Exception:
                    continue

        except Exception as e:
            logger.debug(f"NVML update error: {e}")

        return gpu_info

    def get_temperature(self) -> Optional[float]:
        """Get GPU temperature."""
        if not NVML_AVAILABLE or not self._gpus:
            return None
        for gpu in self._gpus:
            if gpu.is_discrete and gpu.temperature_celsius > 0:
                return gpu.temperature_celsius
        return None

    def get_utilization(self) -> Optional[float]:
        """Get GPU utilization."""
        if not NVML_AVAILABLE or not self._gpus:
            return None
        for gpu in self._gpus:
            if gpu.is_discrete:
                return gpu.utilization_gpu
        return None

    def get_vram_info(self) -> Optional[dict]:
        """Get VRAM usage."""
        if not NVML_AVAILABLE or not self._gpus:
            return None
        for gpu in self._gpus:
            if gpu.is_discrete:
                return {
                    "total_mb": gpu.vram_total_mb,
                    "used_mb": gpu.vram_used_mb,
                    "percent": (
                        (gpu.vram_used_mb / gpu.vram_total_mb * 100)
                        if gpu.vram_total_mb > 0
                        else 0
                    ),
                }
        return None

    def cleanup(self):
        """Clean up NVML resources."""
        global pynvml, NVML_AVAILABLE
        try:
            if NVML_AVAILABLE and pynvml:
                pynvml.nvmlShutdown()
        except Exception:
            pass


# Singleton instance
gpu_monitor = GPUMonitor()
