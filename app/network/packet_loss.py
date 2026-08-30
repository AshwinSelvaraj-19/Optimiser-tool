"""
Packet loss measurement module.
"""

from dataclasses import dataclass

from app.network.ping import PingResult
from app.utils.logger import get_logger

logger = get_logger("network.packet_loss")


@dataclass
class PacketLossReport:
    """Packet loss analysis."""
    host: str = ""
    packet_loss_percent: float = 0.0
    rating: str = "Unknown"  # EXCELLENT, GOOD, FAIR, POOR, BAD
    impact_on_gaming: str = ""


class PacketLossAnalyzer:
    """Analyzes packet loss impact on gaming."""

    def analyze(self, ping_result: PingResult) -> PacketLossReport:
        """Analyze packet loss."""
        report = PacketLossReport(
            host=ping_result.host,
            packet_loss_percent=ping_result.packet_loss_percent,
        )

        loss = ping_result.packet_loss_percent

        if loss == 0:
            report.rating = "EXCELLENT"
            report.impact_on_gaming = "No packet loss — optimal network conditions"
        elif loss < 1:
            report.rating = "GOOD"
            report.impact_on_gaming = "Minimal packet loss — negligible gaming impact"
        elif loss < 3:
            report.rating = "FAIR"
            report.impact_on_gaming = "Some packet loss — may cause occasional rubber-banding"
        elif loss < 5:
            report.rating = "POOR"
            report.impact_on_gaming = "Significant packet loss — frequent game lag and desync"
        else:
            report.rating = "BAD"
            report.impact_on_gaming = "Severe packet loss — gaming will be heavily impacted"

        logger.info(f"Packet loss ({report.host}): {loss:.1f}% — {report.rating}")
        return report


# Singleton
packet_loss_analyzer = PacketLossAnalyzer()
