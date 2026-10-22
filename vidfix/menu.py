"""
VidFix - Interactive bilingual menu + non-interactive CLI mode.
"""

import builtins
import argparse
import os
import sys

from . import __version__, BANNER, APP_NAME
from . import config, detect, enhance, ram as ram_mod
from .lang import t, set_lang, available_langs


def safe_input(prompt=""):
    """input() that survives EOF (non-interactive shells) gracefully."""
    try:
        return builtins.input(prompt)
    except EOFError:
        return ""
    except KeyboardInterrupt:
        print()
        raise SystemExit(130)


# ------------------------------------------------------------ input helpers -

def ask_int(prompt: str, lo: int, hi: int, default=None) -> int:
    while True:
        raw = safe_input(prompt).strip()
        if raw == "" and default is not None:
            return default
        try:
            v = int(raw)
            if lo <= v <= hi:
                return v
        except ValueError:
            pass
        print("  " + t("bad_choice"))


def confirm(prompt: str, default_yes=True) -> bool:
    """Prompt string must already include its own '[Y/n]:' suffix."""
    raw = safe_input(prompt).strip().lower()
    if raw == "":
        return default_yes
    return raw in ("y", "yes")


def pause():
    input_ok = safe_input("\n" + t("any_key"))


# ------------------------------------------------------------- first setup --

def language_setup(save=True):
    print(t("choose_lang"))
    langs = available_langs()
    names = {"en": "1) English", "id": "2) Bahasa Indonesia"}
    for code in langs:
        print(f"  {names.get(code, code)}")
    while True:
        raw = safe_input(t("choose")).strip()
        if raw in ("1", "2"):
            code = langs[int(raw) - 1]
            break
        print("  " + t("lang_bad"))
    set_lang(code)
    if save:
        config.set("lang", code)
    return code


def ram_setup():
    print("\n" + t("ram_menu_title"))
    gb = ram_mod.detect_ram_gb()
    if gb:
        tier = ram_mod.tier_for_gb(gb)
        print("  " + t("ram_detected", gb=gb, tier=ram_mod.tier_params(tier)["label"]))
        if safe_input("  " + t("ram_confirm")).strip().lower() not in ("n", "no"):
            config.set("ram_gb", round(gb, 1))
            config.set("ram_tier", tier)
            print("  " + t("ram_saved", gb=gb, tier=tier))
            return
    sizes = ram_mod.STANDARD_SIZES
    for i, s in enumerate(sizes, 1):
        print(f"  [{i}] {s} GB")
    print(f"  [{len(sizes) + 1}] {t('ram_menu_custom')}")
    pick = ask_int("  " + t("choose"), 1, len(sizes) + 1)
    if pick <= len(sizes):
        gb = float(sizes[pick - 1])
    else:
        while True:
            try:
                gb = float(safe_input("  " + t("ram_prompt_gb")).replace(",", "."))
                if 1 <= gb <= 64:
                    break
            except ValueError:
                pass
            print("  " + t("ram_bad"))
    tier = ram_mod.tier_for_gb(gb)
    config.set("ram_gb", gb)
    config.set("ram_tier", tier)
    print("  " + t("ram_saved", gb=gb, tier=tier))


def first_run():
    print("\n" + t("first_run_title"))
    language_setup()
    ram_setup()
    config.set("setup_done", True)
    print()


# ------------------------------------------------------------------ flows ---

def show_banner():
    print(BANNER)


def main():
    # CLI mode first: it must never block on the first-run wizard
    if len(sys.argv) > 1:
        cli_mode()
        return

    lang = config.get("lang")
    if lang:
        set_lang(lang)
    show_banner()
    if not config.get("setup_done"):
        first_run()

    while True:
        print(t("main_title"))
        print(f"  [1] {t('m1')}")
        print(f"  [2] {t('m2')}")
        print(f"  [3] {t('m3')}")
        print(f"  [0] {t('m0')}")
        c = safe_input("\n" + t("choose")).strip()
        if c == "1":
            enhance_flow()
        elif c == "2":
            settings_flow()
        elif c == "3":
            about()
        elif c == "0":
            print(t("bye"))
            return
        else:
            print(t("bad_choice"))
        print()


def enhance_flow(prefill=None):
    print("\n" + t("file_prompt"))
    path = (prefill or safe_input("> ").strip().strip("'\""))
    path = os.path.expanduser(path)
    if not os.path.isfile(path):
        print("  " + t("file_not_found", p=path))
        return
    info = enhance.probe(path)
    if not info:
        print("  " + t("file_invalid", p=path))
        return

    # ---- content detection (math: color ratio / edges / Donoho sigma) ----
    print("\n" + t("analyzing"))
    analysis = detect.classify(path, info["dur"])
    if analysis["ok"]:
        print("  " + t("detect_header"))
        print("  " + t("detect_line", col=analysis["colors"],
                       edge=analysis["edges"], noise=analysis["noise"]))
        print("  " + t("detect_result", ctype=analysis["type"]))
        if safe_input("  " + t("detect_ok", ctype=analysis["type"])).strip().lower() \
                in ("n", "no"):
            analysis["type"] = content_menu()
    else:
        print("  " + t("analysis_fail"))
        analysis["type"] = content_menu()

    opts = {"content": analysis["type"],
            "tier_key": config.get("ram_tier") or "balanced"}
    tier = ram_mod.tier_params(opts["tier_key"])

    # ---- upscaling ----
    opts["up_level"] = upscale_menu(opts["tier_key"])
    opts["up_custom"] = None
    if opts["up_level"] == 5:
        opts["up_custom"] = custom_res_menu()

    # ---- color ----
    opts["col_level"] = color_menu()
    opts["col_custom"] = None
    if opts["col_level"] == 4:
        opts["col_custom"] = color_sliders_menu()

    # ---- fps ----
    opts["fps_level"] = fps_menu(tier)
    opts["fps_custom"] = None
    if opts["fps_level"] == 4:
        while True:
            try:
                v = int(safe_input("  " + t("f_custom")))
                if 10 <= v <= 120:
                    opts["fps_custom"] = v
                    break
            except ValueError:
                pass
            print("  " + t("f_bad"))

    # ---- summary ----
    up_f, tw, th = enhance.build_upscale(opts["up_level"], opts["content"],
                                         info["w"], info["h"],
                                         opts["up_custom"])
    fps_out = None
    if opts["fps_level"]:
        _, fps_out = enhance.build_fps(opts["fps_level"], opts["tier_key"],
                                       opts["fps_custom"])
    est = enhance.estimate_minutes(info["dur"], opts["tier_key"],
                                   info["w"], info["h"], tw, th,
                                   fps_out, info["fps"])
    print("\n" + t("sum_title"))
    print("  " + t("sum_source", src=os.path.basename(path)))
    print("  " + t("sum_res", sw=info["w"], sh=info["h"], tw=tw, th=th))
    print("  " + t("sum_up", v=enhance.UP_NAMES[opts["up_level"]]
                   + (f" {opts['up_custom'][0]}x{opts['up_custom'][1]}"
                      if opts["up_level"] == 5 else "")))
    print("  " + t("sum_col", v=enhance.COL_NAMES[opts["col_level"]]))
    print("  " + t("sum_fps", v=(enhance.FPS_NAMES[opts["fps_level"]]
                                 if not opts["fps_custom"]
                                 else f"{opts['fps_custom']} fps")))
    print("  " + t("sum_content", v=opts["content"]))
    print("  " + t("sum_time", m=est))
    if not confirm("\n  " + t("sum_go")):
        return

    # ---- process ----
    print("  " + t("wake"))
    last = {"p": -1}

    def on_pct(pct):
        if pct - last["p"] >= 1.0 or pct >= 100:
            last["p"] = pct
            print("\r  " + t("processing", pct=pct), end="", flush=True)

    try:
        result = enhance.process(path, opts, analysis=analysis, on_pct=on_pct)
    except enhance.VidFixError as e:
        print("\n")
        key = str(e)
        print("  " + (t("no_filter") if key == "nothing_to_do"
                      else t("file_invalid", p=path)))
        return
    except KeyboardInterrupt:
        print("\n\n  " + t("err_interrupted"))
        return
    print()

    if result["ok"]:
        print("\n" + t("done_title"))
        print("  " + t("done_out", out=result["output"]))
        print("  " + t("done_size",
                       mb=os.path.getsize(result["output"]) / 1e6))
        print("  " + t("done_time", t=result["seconds"] / 60.0))
    else:
        print("\n  " + t("err_ffmpeg", code=result["code"]))


def content_menu() -> str:
    print("\n  " + t("content_menu_title"))
    print(f"  [1] {t('c_auto')}")
    print(f"  [2] {t('c_real')}")
    print(f"  [3] {t('c_anime')}")
    print(f"  [4] {t('c_game')}")
    pick = ask_int("  " + t("choose"), 1, 4, default=2)
    return {1: "real", 2: "real", 3: "anime", 4: "game"}[pick]


def upscale_menu(tier_key) -> int:
    print("\n  " + t("up_title"))
    for i, key in enumerate(["u0", "u1", "u2", "u3", "u4", "u5"]):
        print(f"  [{i}] {t(key)}")
    lvl = ask_int("  " + t("choose"), 0, 5, default=2)
    if lvl == 4 and tier_key == "safe":
        print("  " + t("u_warn_4k"))
    return lvl


def custom_res_menu():
    while True:
        w = ask_int("  " + t("u_custom_w"), 16, 7680)
        h = ask_int("  " + t("u_custom_h"), 16, 4320)
        if w % 2 == 0 and h % 2 == 0:
            return (w, h)
        print("  " + t("u_bad_res"))


def color_menu() -> int:
    print("\n  " + t("col_title"))
    for i, key in enumerate(["col0", "col1", "col2", "col3", "col4"]):
        print(f"  [{i}] {t(key)}")
    return ask_int("  " + t("choose"), 0, 4, default=1)


def color_sliders_menu():
    vals = {}
    for key, attr in [("col_bright", "brightness"), ("col_contr", "contrast"),
                      ("col_sat", "saturation"), ("col_temp", "temperature")]:
        while True:
            try:
                vals[attr] = int(safe_input("  " + t(key)))
                break
            except ValueError:
                vals[attr] = 0
                break
    return vals


def fps_menu(tier) -> int:
    print("\n  " + t("fps_title"))
    for i, key in enumerate(["f0", "f1", "f2", "f3", "f4"]):
        print(f"  [{i}] {t(key)}")
    lvl = ask_int("  " + t("choose"), 0, 4, default=2)
    if lvl == 3 and tier["max_fps"] < 120:
        print("  " + t("f_safe_block"))
    elif lvl == 3:
        print("  " + t("f_warn_120"))
    return lvl


def settings_flow():
    while True:
        print("\n" + t("set_title"))
        lang = config.get("lang") or "en"
        ram = config.get("ram_gb")
        tier = config.get("ram_tier") or "balanced"
        print(f"  [1] {t('set_lang')}        -> {lang}")
        print(f"  [2] {t('set_ram')}  -> {ram} GB ({tier})")
        print(f"  [3] {t('set_reset')}")
        print(f"  [0] {t('m0')}")
        c = safe_input("\n" + t("choose")).strip()
        if c == "1":
            language_setup()
            print("  " + t("set_done"))
        elif c == "2":
            ram_setup()
        elif c == "3":
            config.reset()
            print("  " + t("set_reset_done"))
            first_run()
            return
        elif c == "0":
            return
        else:
            print(t("bad_choice"))


def about():
    print("\n" + t("about_title"))
    print("  " + t("about_body"))
    print(f"\n  {APP_NAME} v{__version__}")
    pause()


# ------------------------------------------------------------------ CLI -----

def cli_mode():
    ap = argparse.ArgumentParser(
        prog="vidfix",
        description=f"{APP_NAME} v{__version__} - "
                    "video enhancer for Termux "
                    "(upscale / color / fps).")
    ap.add_argument("file", help="video file")
    ap.add_argument("-u", "--upscale", type=int, choices=range(0, 6),
                    default=2, help="0 keep, 1 720p, 2 1080p, 3 1440p, "
                                    "4 4K, 5 custom(--res)")
    ap.add_argument("--res", type=str, default=None,
                    help="custom resolution WxH (with -u 5)")
    ap.add_argument("-c", "--color", type=int, choices=range(0, 5),
                    default=1, help="0 keep, 1 auto-fix, 2 vivid, "
                                    "3 cinematic, 4 custom sliders")
    ap.add_argument("-f", "--fps", type=int, choices=range(0, 5),
                    default=2, help="0 keep, 1 30fps, 2 60fps, 3 120fps, "
                                    "4 custom(--fps-val)")
    ap.add_argument("--fps-val", type=int, default=None,
                    help="custom fps (with -f 4)")
    ap.add_argument("--content", choices=["auto", "real", "anime", "game"],
                    default="auto")
    ap.add_argument("--lang", choices=["en", "id"], default=None)
    ap.add_argument("--yes", action="store_true",
                    help="run without confirmation prompt")
    a = ap.parse_args()

    if a.lang:
        set_lang(a.lang)
        config.set("lang", a.lang)

    up_custom = None
    if a.upscale == 5:
        if not a.res or "x" not in a.res:
            sys.exit("--res WxH required with -u 5")
        w, h = a.res.lower().split("x")
        up_custom = (enhance.even(int(w)), enhance.even(int(h)))

    path = os.path.expanduser(a.file)
    info = enhance.probe(path)
    if not info:
        sys.exit(t("file_invalid", p=path))

    analysis = None
    content = a.content
    if content == "auto":
        print(t("analyzing"))
        analysis = detect.classify(path, info["dur"])
        content = analysis.get("type", "real")
        print(t("detect_result", ctype=content))

    tier_key = config.get("ram_tier") or ram_mod.tier_for_gb(
        ram_mod.detect_ram_gb() or 8.0)
    opts = {"content": content, "tier_key": tier_key,
            "up_level": a.upscale, "up_custom": up_custom,
            "col_level": a.color, "col_custom": None,
            "fps_level": a.fps, "fps_custom": a.fps_val}

    print(t("wake"))
    last = {"p": -1}

    def on_pct(pct):
        if pct - last["p"] >= 1.0 or pct >= 100:
            last["p"] = pct
            print("\r" + t("processing", pct=pct), end="", flush=True)

    try:
        result = enhance.process(path, opts, analysis=analysis, on_pct=on_pct)
    except enhance.VidFixError as e:
        sys.exit(t("no_filter") if str(e) == "nothing_to_do"
                 else t("file_invalid", p=path))
    print()

    if result["ok"]:
        print(t("done_title"))
        print("  " + t("done_out", out=result["output"]))
        print("  " + t("done_size", mb=os.path.getsize(result["output"]) / 1e6))
        print("  " + t("done_time", t=result["seconds"] / 60.0))
    else:
        sys.exit(t("err_ffmpeg", code=result["code"]))
