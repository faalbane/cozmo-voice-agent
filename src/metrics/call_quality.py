"""Call quality metrics: MOS estimation, jitter, packet loss.

Uses the ITU-T E-model (simplified) to estimate Mean Opinion Score
from network quality parameters available via LiveKit RTC stats.
"""

import logging

logger = logging.getLogger(__name__)


def estimate_mos(
    latency_ms: float,
    jitter_ms: float,
    packet_loss_pct: float,
) -> float:
    """Estimate Mean Opinion Score using simplified E-model.

    Based on ITU-T G.107 simplified for VoIP quality estimation.
    Returns MOS on scale 1.0-4.5 (theoretical max for VoIP).

    Args:
        latency_ms: One-way delay in milliseconds
        jitter_ms: Jitter in milliseconds
        packet_loss_pct: Packet loss as percentage (0-100)
    """
    # R-factor calculation (simplified E-model)
    # Base R-factor for G.711 codec
    r = 93.2

    # Delay impairment (Id)
    # Accounts for one-way delay and effective jitter
    effective_delay = latency_ms + jitter_ms * 2
    if effective_delay < 160:
        id_factor = 0
    else:
        id_factor = 0.024 * effective_delay + 0.11 * (effective_delay - 177.3) * (
            1 if effective_delay > 177.3 else 0
        )

    # Equipment impairment (Ie) based on packet loss
    # Using G.711 codec assumptions
    ie_factor = 0 + 30 * (1 - (1 / (1 + packet_loss_pct / 10)))

    r = r - id_factor - ie_factor

    # Clamp R-factor to valid range
    r = max(0, min(100, r))

    # Convert R-factor to MOS
    if r < 0:
        mos = 1.0
    elif r > 100:
        mos = 4.5
    else:
        mos = 1 + 0.035 * r + r * (r - 60) * (100 - r) * 7e-6

    return round(max(1.0, min(4.5, mos)), 2)


def assess_quality(mos: float) -> str:
    """Return a human-readable quality assessment from MOS score."""
    if mos >= 4.0:
        return "Excellent"
    elif mos >= 3.6:
        return "Good"
    elif mos >= 3.1:
        return "Fair"
    elif mos >= 2.6:
        return "Poor"
    else:
        return "Bad"
