"""
VidFix - Content auto-detection (real life / anime / game).

HEURISTIC MATH (all computed on downsampled RGB frames via ffmpeg rawvideo):

1) Unique color ratio
      u = |unique colors| / |pixels|
   Anime/cartoon use flat cel shading -> small palettes -> LOW u.
   Real footage has sensor dithering + natural gradients -> HIGH u.

2) Edge density (Sobel-free gradient magnitude on luma)
      G = sqrt(dx^2 + dy^2),  e = mean( G > tau )   with tau = 60/255
   Games & screen recordings (text HUD, UI) have HIGH e.

3) Noise sigma via Donoho's robust estimator on the Laplacian
      L = -4*f + up + down + left + right
      sigma = median(|L|) / 0.6745        (MAD of standard normal = 0.6745)
   Camera sensors always inject noise -> sigma HIGH for real life,
   near zero for rendered/game/anime content.

Decision tree (order matters):
      sigma >= 4.0                 -> real   (sensor noise present)
      u     <= 0.12                -> anime  (flat palettes)
      e     >= 0.28 and sigma < 4  -> game   (sharp synthetic edges)
      otherwise                    -> real   (sane default)

This is intentionally simple and fast (~80% accurate on common clips).
"""

import subprocess

import numpy as np

SAMPLE_W, SAMPLE_H = 160, 90          # tiny frames = fast + cheap
SAMPLES = 5


def _grab_frames(video: str, duration: float) -> list[np.ndarray]:
    """Pull SAMPLES downsampled RGB frames spread across the video."""
    frames = []
    span = max(duration - 0.5, 0.5)
    for i in range(SAMPLES):
        ts = 0.1 + span * i / SAMPLES
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-ss", f"{ts:.2f}", "-i", video,
            "-frames:v", "1",
            "-vf", f"scale={SAMPLE_W}:{SAMPLE_H}",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1",
        ]
        try:
            raw = subprocess.run(cmd, capture_output=True, timeout=30).stdout
        except (subprocess.TimeoutExpired, OSError):
            continue
        need = SAMPLE_W * SAMPLE_H * 3
        if len(raw) < need:
            continue
        arr = np.frombuffer(raw[:need], dtype=np.uint8)
        frames.append(arr.reshape(SAMPLE_H, SAMPLE_W, 3))
    return frames


def _luma(frame: np.ndarray) -> np.ndarray:
    """ITU-R BT.601 luma: Y = 0.299R + 0.587G + 0.114B (float 0..255)."""
    return (0.299 * frame[:, :, 0]
            + 0.587 * frame[:, :, 1]
            + 0.114 * frame[:, :, 2])


def unique_color_ratio(frame: np.ndarray) -> float:
    flat = frame.reshape(-1, 3)
    uniq = np.unique(flat, axis=0).shape[0]
    return uniq / max(flat.shape[0], 1)


def edge_density(frame: np.ndarray) -> float:
    y = _luma(frame)
    dx = np.abs(np.diff(y, axis=1))[:-1, :]      # horizontal gradient
    dy = np.abs(np.diff(y, axis=0))[:, :-1]      # vertical gradient
    mag = np.hypot(dx, dy)
    return float((mag > 60.0).mean())            # tau = 60/255


def noise_sigma(frame: np.ndarray) -> float:
    y = _luma(frame)
    lap = (-4.0 * y[1:-1, 1:-1]
           + y[:-2, 1:-1] + y[2:, 1:-1]
           + y[1:-1, :-2] + y[1:-1, 2:])
    mad = float(np.median(np.abs(lap)))
    return mad / 0.6745                          # Donoho estimator


def mean_luma(frames: list[np.ndarray]) -> float:
    """Average brightness 0..1 - used by the Auto-Fix color preset."""
    if not frames:
        return 0.5
    return float(np.mean([_luma(f).mean() for f in frames])) / 255.0


def classify(video: str, duration: float) -> dict:
    """
    Returns {'type': 'real'|'anime'|'game', 'colors': u, 'edges': e,
             'noise': sigma, 'luma': mean}
    Falls back to 'real' when sampling fails.
    """
    frames = _grab_frames(video, duration)
    if not frames:
        return {"type": "real", "colors": 0.0, "edges": 0.0,
                "noise": 0.0, "luma": 0.5, "ok": False}

    u = float(np.median([unique_color_ratio(f) for f in frames]))
    e = float(np.median([edge_density(f) for f in frames]))
    s = float(np.median([noise_sigma(f) for f in frames]))
    lum = mean_luma(frames)

    if s >= 4.0:
        ctype = "real"
    elif u <= 0.12:
        ctype = "anime"
    elif e >= 0.28:
        ctype = "game"
    else:
        ctype = "real"

    return {"type": ctype, "colors": u, "edges": e, "noise": s,
            "luma": lum, "ok": True}
