"""
VidFix - RAM detection & performance tiers.

Reads /proc/meminfo (Linux/Termux) to find total device RAM, then maps it
to a performance tier that controls:
  - FFmpeg encoder threads
  - x264 preset (speed)
  - FPS interpolation mode:  'blend' (cheap)  vs  'mci' (motion-compensated)

Math note:
  MemTotal is reported by the kernel in KiB. We convert with
      GiB = KiB / 1024 / 1024
  and round to the nearest standard phone RAM size (3, 4, 6, 8, 12, 16 GB)
  purely for display, keeping the exact float for calculations.
"""

import os

# Tiers chosen to match the "3/4/6/8/12/16 GB" selection screen.
STANDARD_SIZES = [3, 4, 6, 8, 12, 16]

TIERS = {
    "safe": {
        "label": "Safe (3-4 GB)",
        "threads": 4,
        "x264_preset": "veryfast",
        "mi_mode": "blend",       # cheap frame blending, low memory
        "max_fps": 60,            # 120 fps blocked on low RAM
    },
    "balanced": {
        "label": "Balanced (6-8 GB)",
        "threads": 6,
        "x264_preset": "medium",
        "mi_mode": "mci",         # motion-compensated interpolation
        "max_fps": 120,
    },
    "full": {
        "label": "Full Power (12 GB+)",
        "threads": min(8, os.cpu_count() or 8),
        "x264_preset": "medium",
        "mi_mode": "mci",
        "max_fps": 120,
    },
}


def detect_ram_gb() -> float | None:
    """Total RAM in GiB from /proc/meminfo, or None if unreadable (desktop/WSL)."""
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as f:
            first = f.readline()  # "MemTotal:  7643020 kB"
        kib = int(first.split()[1])
        return kib / 1024.0 / 1024.0
    except (OSError, ValueError, IndexError):
        return None


def nearest_standard(gb: float) -> int:
    """Snap a float RAM value to the closest marketed size (3,4,6,8,12,16)."""
    return min(STANDARD_SIZES, key=lambda s: abs(s - gb))


def tier_for_gb(gb: float) -> str:
    """RAM -> tier key.  <5 GiB safe,  <10 GiB balanced,  else full."""
    if gb < 5.0:
        return "safe"
    if gb < 10.0:
        return "balanced"
    return "full"


def tier_params(tier: str) -> dict:
    return TIERS.get(tier, TIERS["balanced"])
