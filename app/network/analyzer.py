"""
Network analysis engine — coordinates ping, jitter, packet loss, and DNS analysis.
"""

from dataclasses import dataclass, field
from typing import Optional

from app.network.ping import ping_monitor, PingResult
from app.network.jitter import jitter_analyzer, JitterReport
from app.network.packet_loss import packet_loss_analyzer, PacketLossReport
from app.utils.logger import get_logger

logger = get_logger("network.analyzer")


@dataclass
class NetworkReport:
    """Complete network analysis report."""
    ping_results: list = field(default_factory=list)
    jitter_reports: list = field(default_factory=list)
    packet_loss_reports: list = field(default_factory=list)
    overall_quality: str = "Unknown"
    gaming_suitability: str = "Unknown"
    recommendations: list = field(default_factory=list)


class NetworkAnalyzer:
    """Complete network diagnostics engine."""

    def analyze(self) -> NetworkReport:
        """Run full network analysis."""
        report = NetworkReport()

        # Measure ping to all targets
        ping_results = ping_monitor.measure_all(count=10)
        report.ping_results = ping_results

        # Analyze jitter
        for pr in ping_results:
            jitter = jitter_analyzer.analyze(pr)
            report.jitter_reports.append(jitter)

        # Analyze packet loss
        for pr in ping_results:
            pl = packet_loss_analyzer.analyze(pr)
            report.packet_loss_reports.append(pl)

        # Overall assessment
        report = self._assess(report)

        logger.info(f"Network quality: {report.overall_quality}")
        return report

    def _assess(self, report: NetworkReport) -> NetworkReport:
        """Assess overall network quality for gaming."""
        # Find the best ping result (usually gateway or lowest latency)
        if report.ping_results:
            best_ping = min(report.ping_results, key=lambda r: r.avg_latency_ms)
            avg_ping = best_ping.avg_latency_ms
        else:
            avg_ping = 0

        # Find worst jitter
        if report.jitter_reports:
            worst_jitter = max(report.jitter_reports, key=lambda r: r.jitter_ms)
            jitter = worst_jitter.jitter_ms
        else:
            jitter = 0

        # Find worst packet loss
        if report.packet_loss_reports:
            worst_loss = max(report.packet_loss_reports, key=lambda r: r.packet_loss_percent)
            loss = worst_loss.packet_loss_percent
        else:
            loss = 0

        # Overall quality
        if avg_ping < 30 and jitter < 5 and loss < 1:
            report.overall_quality = "EXCELLENT"
            report.gaming_suitability = "IDEAL — Network is excellent for competitive gaming"
        elif avg_ping < 50 and jitter < 15 and loss < 3:
            report.overall_quality = "GOOD"
            report.gaming_suitability = "SUITABLE — Good conditions for online gaming"
        elif avg_ping < 100 and jitter < 30 and loss < 5:
            report.overall_quality = "FAIR"
            report.gaming_suitability = "PLAYABLE — Noticeable latency, casual gaming OK"
        else:
            report.overall_quality = "POOR"
            report.gaming_suitability = "DIFFICULT — High latency/jitter will impact gaming"

        # Recommendations (informational only, NOT fps-related)
        report.recommendations.append(
            "IMPORTANT: Network quality affects ONLINE LATENCY, not FPS. "
            "Improving network does NOT increase frame rate."
        )

        if jitter > 15:
            report.recommendations.append(
                "High jitter detected. Use wired Ethernet connection if possible."
            )
        if loss > 1:
            report.recommendations.append(
                "Packet loss detected. Check router and ISP connection."
            )
        if avg_ping > 50:
            report.recommendations.append(
                "High latency to internet. Consider closer server selection in-game."
            )

        return report


# Singleton
network_analyzer = NetworkAnalyzer()
