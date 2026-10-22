"""
VidFix - Persistent configuration.
Stored at ~/.config/vidfix/config.json so the user only sets things once.
"""

import json
import os

HOME = os.path.expanduser("~")
CONFIG_DIR = os.path.join(os.environ.get("HOME", HOME), ".config", "vidfix")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

DEFAULTS = {
    "lang": None,          # "en" | "id"
    "ram_gb": None,        # float, e.g. 7.3
    "ram_tier": None,      # "safe" | "balanced" | "full"
    "setup_done": False,   # first-run wizard completed?
}

_cache = None


def load() -> dict:
    global _cache
    if _cache is None:
        cfg = dict(DEFAULTS)
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
        except (OSError, ValueError):
            pass  # first run or corrupted file -> defaults
        _cache = cfg
    return _cache


def save():
    os.makedirs(CONFIG_DIR, exist_ok=True)
    tmp = CONFIG_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(load(), f, indent=2, ensure_ascii=False)
    os.replace(tmp, CONFIG_FILE)


def get(key: str):
    return load().get(key, DEFAULTS.get(key))


def set(key: str, value):
    load()[key] = value
    save()


def reset():
    global _cache
    _cache = None
    try:
        os.remove(CONFIG_FILE)
    except OSError:
        pass
