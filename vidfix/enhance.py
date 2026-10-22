"""
VidFix - Enhancement engine (FFmpeg pipeline builder + runner).

Filter order inside a single ffmpeg pass (fast + quality-safe):
    1. upscale  (scale lanczos + unsharp mask)   -> once per source frame
    2. color    (eq / curves / colorbalance)     -> once per source frame
    3. fps      (minterpolate)                   -> LAST: new frames inherit
                                                    the finished look, and we
                                                    only pay interpolation cost
                                                    on already-graded frames.

Math implemented by FFmpeg (C speed) on our behalf:
  - Lanczos resampling:  L(x) = sinc(x) * sinc(x/3), |x| < 3
  - Unsharp mask:        out = in + a * (in - blur(in))
  - Gamma correction:    out = 255 * (in/255)^(1/gamma)
  - S-curve contrast:    cubic spline through control points
  - Frame blending:      out = (1-a)*A + a*B
  - Motion compensation: adaptive overlapped block motion estimation (aobmc)

Math implemented by VidFix itself:
  - even-dimension rounding for H.264:  dim = round(dim/2) * 2
  - aspect-fit inside a target box
  - adaptive gamma from measured mean luma
  - rough render-time estimation
"""

import os
import re
import shutil
import subprocess
import time

from . import ram as ram_mod

# ----------------------------------------------------------------- probe ----

def probe(path: str) -> dict | None:
    """Read width/height/fps/duration via ffprobe."""
    cmd = ["ffprobe", "-v", "error",
           "-select_streams", "v:0",
           "-show_entries",
           "stream=width,height,r_frame_rate:format=duration",
           "-of", "default=nw=1", path]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True,
                             timeout=30).stdout
    except (subprocess.TimeoutExpired, OSError):
        return None
    info = {}
    for line in out.splitlines():
        k, _, v = line.partition("=")
        info[k.strip()] = v.strip()
    try:
        num, _, den = info["r_frame_rate"].partition("/")
        fps = float(num) / float(den or 1)
        return {"w": int(info["width"]), "h": int(info["height"]),
                "fps": fps, "dur": float(info.get("duration", 0) or 0)}
    except (KeyError, ValueError, ZeroDivisionError):
        return None


# ------------------------------------------------------------- math utils ---

def even(x: int) -> int:
    """H.264 wants even dimensions:  dim = round(dim / 2) * 2."""
    return max(2, int(round(x / 2.0)) * 2)


def fit_inside(src_w: int, src_h: int, box_w: int, box_h: int) -> tuple[int, int]:
    """Aspect-preserving fit of (src_w,src_h) inside (box_w,box_h), evenized."""
    r = min(box_w / src_w, box_h / src_h)
    return even(src_w * r), even(src_h * r)


def adaptive_gamma(mean_luma: float) -> float:
    """
    Auto-Fix gamma from measured brightness (luma in 0..1).
    Dark clip  -> lift midtones;  bright/flat clip -> tiny pull-back.
    gamma = 1 + 0.5*(0.42 - luma)      when luma < 0.42
    gamma = 1 - 0.8*(luma - 0.68)      when luma > 0.68
    clamped to [0.9, 1.35].
    """
    if mean_luma < 0.42:
        g = 1.0 + 0.5 * (0.42 - mean_luma)
    elif mean_luma > 0.68:
        g = 1.0 - 0.8 * (mean_luma - 0.68)
    else:
        g = 1.0
    return max(0.9, min(1.35, g))


# ---------------------------------------------------------- filter builders -

UP_TARGETS = {1: (1280, 720), 2: (1920, 1080),
              3: (2560, 1440), 4: (3840, 2160)}

UP_NAMES = {0: "keep", 1: "HD 720p", 2: "FHD 1080p", 3: "QHD 1440p",
            4: "UHD 4K", 5: "custom"}
COL_NAMES = {0: "keep", 1: "Auto-Fix", 2: "Vivid", 3: "Cinematic", 4: "custom"}
FPS_NAMES = {0: "keep", 1: "30 fps", 2: "60 fps", 3: "120 fps", 4: "custom"}

SHARP_BY_CONTENT = {"real": 0.7, "anime": 0.5, "game": 0.85}
SAT_VIVID = {"real": 1.12, "anime": 1.18, "game": 1.14}


def build_upscale(level, content, src_w, src_h, custom=None):
    """Returns (filter_str|None, target_w, target_h)."""
    if level == 0:
        return None, src_w, src_h
    box = custom if level == 5 else UP_TARGETS[level]
    tw, th = fit_inside(src_w, src_h, box[0], box[1])
    sharp = SHARP_BY_CONTENT.get(content, 0.7)
    # scale=lanczos  then  unsharp:  out = in + a*(in - blur(in))
    f = (f"scale={tw}:{th}:flags=lanczos,"
         f"unsharp=5:5:{sharp:.2f}:5:5:0.0")
    return f, tw, th


def build_color(level, content, analysis, custom=None):
    """Returns filter_str|None. `analysis` may be None (CLI fast path)."""
    if level == 0:
        return None
    luma = (analysis or {}).get("luma", 0.5)

    if level == 1:                                   # Auto-Fix
        g = adaptive_gamma(luma)
        sat = 1.10 if content == "anime" else 1.08
        return f"eq=gamma={g:.2f}:contrast=1.06:saturation={sat:.2f}"

    if level == 2:                                   # Vivid
        sat = SAT_VIVID.get(content, 1.12)
        s_curve = "curves=all='0/0 0.25/0.22 0.5/0.5 0.75/0.79 1/1'"
        warm = "colorbalance=rs=0.03:bs=-0.03"
        return f"{s_curve},eq=saturation={sat:.2f},{warm}"

    if level == 3:                                   # Cinematic
        lift = "curves=all='0/0.035 0.25/0.24 0.5/0.5 0.75/0.77 1/0.965'"
        cool = "colorbalance=gs=-0.02:bs=0.05:rm=-0.03"
        return f"{lift},eq=contrast=1.08:saturation=0.96,{cool}"

    if level == 4 and custom:                        # Custom sliders
        b = custom.get("brightness", 0) / 100.0 * 0.4
        c = 1.0 + custom.get("contrast", 0) / 100.0 * 0.5
        s = 1.0 + custom.get("saturation", 0) / 100.0 * 0.6
        temp = custom.get("temperature", 0) / 100.0 * 0.15
        f = f"eq=brightness={b:.3f}:contrast={c:.2f}:saturation={s:.2f}"
        if abs(temp) > 0.001:
            f += (f",colorbalance=rs={temp:.3f}:bs={-temp:.3f}")
        return f
    return None


def build_fps(level, tier_key, custom=None):
    """Returns (filter_str|None, out_fps|None). May cap by tier."""
    tier = ram_mod.tier_params(tier_key)
    if level == 0:
        return None, None
    if level == 4:
        fps = int(custom or 60)
        fps = min(max(fps, 10), tier["max_fps"])
    else:
        fps = {1: 30, 2: 60, 3: 120}[level]
        fps = min(fps, tier["max_fps"])

    if tier["mi_mode"] == "blend":
        # linear cross-fade between neighbour frames: (1-a)*A + a*B
        return f"minterpolate=fps={fps}:mi_mode=blend", fps
    # motion-compensated: adaptive overlapped block motion estimation,
    # bidirectional ME, variate-size block MC, fdiff scene-cut guard
    return (f"minterpolate=fps={fps}:mi_mode=mci:mc_mode=aobmc:"
            f"me_mode=bidir:vsbmc=1:scd=fdiff:scd_threshold=8"), fps


# -------------------------------------------------------------- estimation --

def estimate_minutes(dur_s, tier_key, src_w, src_h, tw, th, fps_out, fps_in):
    """Very rough render-time model (clearly labelled as an estimate)."""
    if not dur_s:
        return 1.0
    base = dur_s / 60.0
    area = (tw * th) / max(src_w * src_h, 1)
    up_cost = 0.30 * area if area > 1.01 else 0.05
    if fps_out:
        ratio = max(fps_out, 1) / max(fps_in or 30, 1)
        mode = ram_mod.tier_params(tier_key)["mi_mode"]
        interp_cost = max(0.0, ratio - 1.0) * (1.2 if mode == "blend" else 7.0)
    else:
        interp_cost = 0.0
    return max(0.3, base * (1.0 + up_cost + interp_cost))


# ----------------------------------------------------------------- runner ---

class VidFixError(RuntimeError):
    pass


def _wake_lock(on: bool):
    cmd = "termux-wake-lock" if on else "termux-wake-unlock"
    if shutil.which(cmd):
        try:
            subprocess.run([cmd], capture_output=True, timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            pass


def _notify_progress(line: str, total_s: float, printer):
    m = re.match(r"(\w+)=(.*)", line.strip())
    if not m:
        return
    key, val = m.groups()
    secs = None
    if key == "out_time_us":
        try:
            secs = int(val) / 1_000_000.0
        except ValueError:
            pass
    elif key == "out_time_ms":          # ffmpeg quirk: actually microseconds
        try:
            secs = int(val) / 1_000_000.0
        except ValueError:
            pass
    if secs is not None and printer and total_s > 0:
        pct = min(100.0, secs / total_s * 100.0)
        printer(pct)


def process(src: str, opts: dict, analysis=None, printer=None,
            on_pct=None) -> dict:
    """
    Run the full pipeline.  opts keys:
      content, up_level, up_custom, col_level, col_custom,
      fps_level, fps_custom, tier_key
    Returns {'ok':bool,'output':str,'seconds':float,'code':int}
    """
    info = probe(src)
    if not info:
        raise VidFixError("probe_failed")

    tier_key = opts["tier_key"]
    tier = ram_mod.tier_params(tier_key)

    filters = []
    up_f, tw, th = build_upscale(opts["up_level"], opts["content"],
                                 info["w"], info["h"], opts.get("up_custom"))
    if up_f:
        filters.append(up_f)
    col_f = build_color(opts["col_level"], opts["content"], analysis,
                        opts.get("col_custom"))
    if col_f:
        filters.append(col_f)
    fps_f, out_fps = build_fps(opts["fps_level"], tier_key,
                               opts.get("fps_custom"))
    if fps_f:
        filters.append(fps_f)
    if not filters:
        raise VidFixError("nothing_to_do")
    if not up_f:  # keep odd-size sources valid for the encoder
        filters.append("scale=trunc(iw/2)*2:trunc(ih/2)*2")

    out = os.path.join(os.path.dirname(os.path.abspath(src)),
                       os.path.splitext(os.path.basename(src))[0]
                       + "_enhanced.mp4")

    base_cmd = (["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                 "-nostats", "-progress", "pipe:1",
                 "-i", src,
                 "-vf", ",".join(filters),
                 "-c:v", "libx264",
                 "-preset", tier["x264_preset"],
                 "-crf", "18",
                 "-pix_fmt", "yuv420p",
                 "-threads", str(tier["threads"]),
                 "-movflags", "+faststart"])

    # --- attempt 1: copy original audio -------------------------------
    cmd = base_cmd + ["-c:a", "copy", out]
    audio_fallback = False
    t0 = time.time()
    _wake_lock(True)
    try:
        code = _run_ffmpeg(cmd, info["dur"], on_pct)
        if code != 0:
            # --- attempt 2: re-encode audio to AAC ------------------------
            audio_fallback = True
            cmd = base_cmd + ["-c:a", "aac", "-b:a", "192k", out]
            code = _run_ffmpeg(cmd, info["dur"], on_pct)
    finally:
        _wake_lock(False)

    if code != 0:
        return {"ok": False, "output": out, "seconds": time.time() - t0,
                "code": code, "audio_fallback": audio_fallback}

    return {"ok": True, "output": out, "seconds": time.time() - t0,
            "code": 0, "audio_fallback": audio_fallback,
            "src": info, "target": (tw, th), "fps_out": out_fps}


def _run_ffmpeg(cmd: list, total_s: float, on_pct) -> int:
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            _notify_progress(line, total_s, on_pct)
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        raise
    return proc.returncode
