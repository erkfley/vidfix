#!/usr/bin/env python3
"""
VidFix - Video Enhancer for Termux
Entry point. Run:  python app.py           (interactive menu)
              or:  vidfix <file> [options]  (CLI mode)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from vidfix.menu import main          # noqa: E402

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
