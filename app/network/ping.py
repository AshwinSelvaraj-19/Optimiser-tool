"""
Network ping measurement module.
Measures latency to game servers and general internet.
"""

import socket
import time
import threading
from dataclasses import dataclass
from typing import Optional

from app.utils.commands import run_command
from app.utils.logger import get_logger

logger = get_logger("network.ping")


@dataclass
class PingResult:
    """Ping measurement result."""
    host: str = ""
    ip_address: str = ""
    avg_latency_ms: float = 0.0
    min_latency_ms: float = 0.0
    max_latency_ms: float = 0.0
    packet_loss_percent: float = 0.0
    samples: list = None
    timestamp: float = 0.0

    def __post_init__(self):
        if self.samples is None:
            self.samples = []


class PingMonitor:
    """Network ping measurement."""

    def __init__(self):
        self._targets = [
            ("Google DNS", "8.8.8.8"),
            ("Cloudflare DNS", "1.1.1.1"),
            ("Gateway", self._get_default_gateway()),
        ]

    def _get_default_gateway(self) -> str:
        """Get the default gateway IP."""
        try:
            success, stdout, _ = run_command("ipconfig | findstr Default Gateway")
            if success and stdout:
                for line in stdout.split('\n'):
                    # Parse gateway from ipconfig output
                    import re
                    match = re.search(r'(\d+\.\d+\.\d+\.\d+)', line)
                    if match:
                        return match.group(1)
        except Exception:
            pass
        return "192.168.1.1"

    def measure_ping(self, host: str, count: int = 10, timeout: int = 2) -> PingResult:
        """Measure ping to a host."""
        result = PingResult(host=host)
        result.timestamp = time.time()

        # Resolve host
        try:
            result.ip_address = socket.gethostbyname(host)
        except socket.gaierror:
            logger.warning(f"Cannot resolve host: {host}")
            return result

        # Use Windows ping command for accurate measurement
        success, stdout, _ = run_command(
            f"ping -n {count} -w {timeout * 1000} {host}",
            timeout=timeout * count + 5,
        )

        if success and stdout:
            latencies = []
            for line in stdout.split('\n'):
                if 'time=' in line.lower():
                    import re
                    match = re.search(r'time[=<](\d+)', line)
                    if match:
                        latencies.append(float(match.group(1)))

            if latencies:
                result.samples = latencies
                result.avg_latency_ms = sum(latencies) / len(latencies)
                result.min_latency_ms = min(latencies)
                result.max_latency_ms = max(latencies)

            # Parse packet loss
            import re
            loss_match = re.search(r'(\d+)% loss', stdout)
            if loss_match:
                result.packet_loss_percent = float(loss_match.group(1))
        else:
            result.packet_loss_percent = 100.0

        return result

    def measure_all(self, count: int = 10) -> list:
        """Measure ping to all targets."""
        results = []
        for name, host in self._targets:
            if host:
                result = self.measure_ping(host, count)
                results.append(result)
        return results


# Singleton
ping_monitor = PingMonitor()
