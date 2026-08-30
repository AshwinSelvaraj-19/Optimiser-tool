"""
Network jitter analysis module.
Measures jitter from ping sample variance.
"""

from dataclasses import dataclass

from app.network.ping import PingResult
from app.utils.logger import get_logger

logger = get_logger("network.jitter")


@dataclass
class JitterReport:
    """Network jitter analysis."""
    host: str = ""
    avg_latency_ms: float = 0.0
    jitter_ms: float = 0.0
    jitter_rating: str = "Unknown"  # EXCELLENT, GOOD, FAIR, POOR, BAD
    stability_score: float = 0.0  # 0-100


class JitterAnalyzer:
    """Analyzes network jitter from ping samples."""

    def analyze(self, ping_result: PingResult) -> JitterReport:
        """Analyze jitter from ping samples."""
        report = JitterReport(host=ping_result.host)
        report.avg_latency_ms = ping_result.avg_latency_ms

        if not ping_result.samples or len(ping_result.samples) < 3:
            report.jitter_rating = "INSUFFICIENT DATA"
            return report

        samples = ping_result.samples
        avg = sum(samples) / len(samples)

        # Calculate jitter as mean absolute deviation from mean
        jitter = sum(abs(s - avg) for s in samples) / len(samples)
        report.jitter_ms = jitter

        # Rating
        if jitter < 2:
            report.jitter_rating = "EXCELLENT"
            report.stability_score = 95
        elif jitter < 5:
            report.jitter_rating = "GOOD"
            report.stability_score = 80
        elif jitter < 15:
            report.jitter_rating = "FAIR"
            report.stability_score = 60
        elif jitter < 30:
            report.jitter_rating = "POOR"
            report.stability_score = 35
        else:
            report.jitter_rating = "BAD"
            report.stability_score = 15

        logger.info(f"Jitter ({report.host}): {jitter:.1f}ms — {report.jitter_rating}")
        return report


# Singleton
jitter_analyzer = JitterAnalyzer()
