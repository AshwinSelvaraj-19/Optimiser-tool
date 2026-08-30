"""
GPU-Emulator association detection.
Determines which GPU adapter a running process is using.
Uses NVML per-process GPU tracking and Windows GPU engine telemetry.
"""

import time
from dataclasses import dataclass
from typing import Optional

from app.utils.logger import get_logger

logger = get_logger("performance.gpu_association")

try:
    import pynvml
    NVML_AVAILABLE = True
except ImportError:
    NVML_AVAILABLE = False


@dataclass
class GPUAssociation:
    """GPU association for a specific process."""
    process_name: str = ""
    pid: int = 0
    gpu_name: str = "Unknown"
    gpu_index: int = -1
    gpu_engine: str = "Unknown"
    gpu_utilization: float = 0.0
    gpu_memory_used_mb: float = 0.0
    status: str = "UNVERIFIED"  # DISCRETE ACTIVE, INTEGRATED ACTIVE, UNVERIFIED, NOT RUNNING
    confidence: float = 0.0
    method: str = ""


class GPUAssociationDetector:
    """Detects which GPU a process is using."""

    def __init__(self):
        self._nvml_initialized = False

    def _init_nvml(self) -> bool:
        if not NVML_AVAILABLE:
            return False
        if self._nvml_initialized:
            return True
        try:
            pynvml.nvmlInit()
            self._nvml_initialized = True
            return True
        except Exception:
            return False

    def detect_for_process(self, process_name: str, pid: int = 0) -> GPUAssociation:
        """Detect GPU association for a specific process."""
        result = GPUAssociation(process_name=process_name, pid=pid)

        if not self._init_nvml():
            result.status = "UNVERIFIED"
            result.method = "NVML not available"
            return result

        try:
            # Get all GPU handles
            device_count = pynvml.nvmlDeviceGetCount()
            
            for gpu_idx in range(device_count):
                handle = pynvml.nvmlDeviceGetHandleByIndex(gpu_idx)
                
                # Get GPU name
                try:
                    gpu_name = pynvml.nvmlDeviceGetName(handle)
                    if isinstance(gpu_name, bytes):
                        gpu_name = gpu_name.decode()
                except Exception:
                    gpu_name = f"GPU {gpu_idx}"

                # Try to get per-process GPU usage
                try:
                    # nvmlDeviceGetComputeRunningProcesses or GraphicsRunningProcesses
                    procs = pynvml.nvmlDeviceGetGraphicsRunningProcesses(handle)
                    for proc_info in procs:
                        if pid > 0 and proc_info.pid == pid:
                            result.gpu_name = gpu_name
                            result.gpu_index = gpu_idx
                            result.gpu_memory_used_mb = proc_info.usedGpuMemory / (1024 * 1024) if proc_info.usedGpuMemory else 0
                            result.gpu_engine = "3D (Graphics)"
                            result.confidence = 0.8
                            result.method = "NVML GraphicsRunningProcesses"
                            
                            # Check if discrete
                            if "NVIDIA" in gpu_name.upper() or "GEFORCE" in gpu_name.upper() or "RTX" in gpu_name.upper() or "GTX" in gpu_name.upper():
                                result.status = "DISCRETE GPU ACTIVE"
                            elif "INTEL" in gpu_name.upper() or "UHD" in gpu_name.upper():
                                result.status = "INTEGRATED GPU ACTIVE"
                            else:
                                result.status = "GPU ACTIVE"
                            
                            logger.info(f"GPU association found: {process_name} PID {pid} -> {gpu_name} ({result.status})")
                            return result
                
                except pynvml.NVMLError:
                    pass

                # Try compute processes
                try:
                    procs = pynvml.nvmlDeviceGetComputeRunningProcesses(handle)
                    for proc_info in procs:
                        if pid > 0 and proc_info.pid == pid:
                            result.gpu_name = gpu_name
                            result.gpu_index = gpu_idx
                            result.gpu_memory_used_mb = proc_info.usedGpuMemory / (1024 * 1024) if proc_info.usedGpuMemory else 0
                            result.gpu_engine = "Compute"
                            result.confidence = 0.7
                            result.method = "NVML ComputeRunningProcesses"
                            result.status = "GPU ACTIVE (Compute)"
                            return result
                except pynvml.NVMLError:
                    pass

            # No process found on any GPU
            result.status = "UNVERIFIED"
            result.method = "Process not found in NVML GPU process lists"
            result.confidence = 0.3
            logger.info(f"GPU association: {process_name} PID {pid} — not found in NVML process lists")

        except Exception as e:
            result.status = "UNVERIFIED"
            result.method = f"Error: {e}"
            logger.error(f"GPU association detection error: {e}")

        return result

    def detect_all_gpu_processes(self) -> list:
        """List all processes currently using any GPU."""
        results = []
        if not self._init_nvml():
            return results

        try:
            device_count = pynvml.nvmlDeviceGetCount()
            for gpu_idx in range(device_count):
                handle = pynvml.nvmlDeviceGetHandleByIndex(gpu_idx)
                try:
                    gpu_name = pynvml.nvmlDeviceGetName(handle)
                    if isinstance(gpu_name, bytes):
                        gpu_name = gpu_name.decode()
                except Exception:
                    gpu_name = f"GPU {gpu_idx}"

                for proc_type, get_procs in [
                    ("Graphics", pynvml.nvmlDeviceGetGraphicsRunningProcesses),
                    ("Compute", pynvml.nvmlDeviceGetComputeRunningProcesses),
                ]:
                    try:
                        procs = get_procs(handle)
                        for proc_info in procs:
                            results.append({
                                "pid": proc_info.pid,
                                "gpu_name": gpu_name,
                                "gpu_index": gpu_idx,
                                "engine": proc_type,
                                "vram_used_mb": proc_info.usedGpuMemory / (1024 * 1024) if proc_info.usedGpuMemory else 0,
                            })
                    except pynvml.NVMLError:
                        pass
        except Exception as e:
            logger.error(f"GPU process enumeration error: {e}")

        return results

    def cleanup(self):
        if self._nvml_initialized:
            try:
                pynvml.nvmlShutdown()
            except Exception:
                pass
            self._nvml_initialized = False


# Singleton
gpu_association_detector = GPUAssociationDetector()
