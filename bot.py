#!/usr/bin/env python3
"""
bot.py  —  Instagram Core Bot (Menuy Finglish)

Ejra:
    python bot.py

Menu ama:
    1. Sakht
       1. Sakht Story
       2. Sakht Reels
       3. Sakht Hardo
    2. Upload
       1. Upload Story
       2. Upload Reels
       3. Upload Hardo
    0. Khorooj
"""

from __future__ import annotations

import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Optional, Tuple

# ── Bootstrap ─────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

# ── Color support (colorama) ──────────────────────────────────────────────────
try:
    from colorama import Fore, Style, init as _cinit
    _cinit(autoreset=True)

    CY   = Fore.CYAN    + Style.BRIGHT   # titles / headers
    CW   = Fore.WHITE   + Style.BRIGHT   # menu numbers
    CG   = Fore.GREEN   + Style.BRIGHT   # success
    CR   = Fore.RED     + Style.BRIGHT   # error
    CM   = Fore.MAGENTA + Style.BRIGHT   # sub-header
    CYL  = Fore.YELLOW                   # hints / pending badge
    DIM  = Style.DIM                     # secondary text
    RST  = Style.RESET_ALL               # reset

except ImportError:
    class _Noop:                         # graceful fallback — no colors
        def __getattr__(self, _: str) -> str:
            return ""
    CY = CW = CG = CR = CM = CYL = DIM = RST = ""  # type: ignore[assignment]

# ── Project imports ───────────────────────────────────────────────────────────
try:
    from config import Config
    from main import (
        make_story_png,
        create_reel,
        upload_all,
        upload_pending_reels,
        upload_pending_stories,
    )
    _CFG = Config()
except ImportError as _err:
    print(f"\n  [KHATA] Import misfire: {_err}")
    print("  'pip install -r requirements.txt' ra ejra konid.")
    sys.exit(1)


# ══════════════════════════════════════════════════════════════════════════════
# UI helpers
# ══════════════════════════════════════════════════════════════════════════════

_W = 54   # total box width


def _cls() -> None:
    """Pake kardan terminal."""
    os.system("cls" if sys.platform == "win32" else "clear")


def _ruler(char: str = "─") -> str:
    return char * (_W - 2)


def _box(title: str, subtitle: str = "") -> str:
    """Draw a labelled box header."""
    pad   = _W - len(title) - 6
    lp    = pad // 2
    rp    = pad - lp
    top   = f"╔{'═' * (lp + 1)} {title} {'═' * (rp + 1)}╗"
    mid   = f"║  {subtitle:<{_W - 4}}║" if subtitle else ""
    bot   = f"╚{'═' * (_W - 2)}╝"
    return "\n".join(filter(None, [top, mid, bot]))


def _row(label: str, hint: str = "", num: str = "") -> str:
    """Format one menu row."""
    num_part  = f"{CW}{num:>3}.{RST}" if num else "    "
    hint_part = f"  {DIM}{hint}{RST}" if hint else ""
    return f"  {num_part}  {label}{hint_part}"


def _sep() -> str:
    return f"   {DIM}{_ruler()}{RST}"


def _ok(msg: str) -> None:
    print(f"\n{CG}  ✔  {msg}{RST}")


def _err(msg: str) -> None:
    print(f"\n{CR}  ✖  {msg}{RST}")


def _info(msg: str) -> None:
    print(f"\n{CYL}  →  {msg}{RST}")


def _pause() -> None:
    input(f"\n{DIM}  [ Enter bezanid ta edame bedid... ]{RST}")


# ── Pending counters ──────────────────────────────────────────────────────────

def _pending() -> Tuple[int, int]:
    """Return (n_stories, n_reels) waiting in local storage."""
    def _count(directory: Path, exts: set) -> int:
        try:
            return sum(
                1 for f in directory.iterdir()
                if f.is_file() and f.suffix.lower() in exts
            )
        except Exception:
            return 0

    return (
        _count(_CFG.STORIES_DIR, {".png", ".jpg", ".mp4"}),
        _count(_CFG.REELS_DIR,   {".mp4"}),
    )


# ── Action runner ─────────────────────────────────────────────────────────────

def _run(title: str, fn: Callable[[], Any]) -> None:
    """
    Execute *fn* with Finglish status messages.
    The function may call input() freely — stdin is untouched.
    """
    print(f"\n{CYL}  ⏳  {title} shoro mishavad...{RST}\n")
    try:
        result = fn()
        _ok(f"{title} ba movafaghiat anjam shod.")
        if isinstance(result, Path):
            print(f"{DIM}     📁  {result.name}{RST}")
    except KeyboardInterrupt:
        _err("Lagv shod (Ctrl+C).")
    except Exception as exc:
        _err(f"Khata: {exc}")
        if os.getenv("DEBUG"):
            traceback.print_exc()
    _pause()


# ══════════════════════════════════════════════════════════════════════════════
# Sub-menu: Sakht (Create)
# ══════════════════════════════════════════════════════════════════════════════

def _menu_sakht() -> None:
    while True:
        _cls()
        print()
        print(CM + _box("📸  SAKHT", "Besaz va zakhire kon — upload jodast") + RST)
        print()
        print(_row("Sakht Story",  "→  AI story bezar tu stories/",   "1"))
        print(_row("Sakht Reels",  "→  Reel bezar tu reels/",         "2"))
        print(_row("Sakht Hardo",  "→  Story + Reel har do zakhire",   "3"))
        print(_sep())
        print(_row("Bargasht", num="0"))
        print()

        choice = input(f"  {CYL}Entekhab:{RST} ").strip()

        if choice == "1":
            _run("Sakht Story", make_story_png)

        elif choice == "2":
            _run("Sakht Reels", create_reel)

        elif choice == "3":
            def _hardo_sakht() -> None:
                _info("[1/2]  Sakht Story...")
                make_story_png()
                _info("[2/2]  Sakht Reels...")
                create_reel()
            _run("Sakht Hardo", _hardo_sakht)

        elif choice in ("0", ""):
            break

        else:
            _err("Entekhab namotabar — dobare emtehan konid.")
            time.sleep(1)


# ══════════════════════════════════════════════════════════════════════════════
# Sub-menu: Upload
# ══════════════════════════════════════════════════════════════════════════════

def _menu_upload() -> None:
    while True:
        _cls()
        n_story, n_reel = _pending()
        n_total = n_story + n_reel

        print()
        print(CY + _box(
            "📤  UPLOAD",
            f"Pending: {n_story} Story  |  {n_reel} Reel",
        ) + RST)
        print()
        print(_row("Upload Story",  f"→  {n_story} file amadeh",       "1"))
        print(_row("Upload Reels",  f"→  {n_reel} file amadeh",        "2"))
        print(_row("Upload Hardo",  f"→  Story + Reels ({n_total} kol)","3"))
        print(_sep())
        print(_row("Bargasht", num="0"))
        print()

        choice = input(f"  {CYL}Entekhab:{RST} ").strip()

        if choice == "1":
            if n_story == 0:
                _err("Hich story-i baraye upload peyda nashod.")
                _pause()
            else:
                _run("Upload Story", upload_pending_stories)

        elif choice == "2":
            if n_reel == 0:
                _err("Hich reel-i baraye upload peyda nashod.")
                _pause()
            else:
                _run("Upload Reels", upload_pending_reels)

        elif choice == "3":
            if n_total == 0:
                _err("Hich file-i baraye upload peyda nashod.")
                _pause()
            else:
                _run("Upload Hardo", upload_all)

        elif choice in ("0", ""):
            break

        else:
            _err("Entekhab namotabar — dobare emtehan konid.")
            time.sleep(1)


# ══════════════════════════════════════════════════════════════════════════════
# Main menu
# ══════════════════════════════════════════════════════════════════════════════

def _menu_main() -> None:
    while True:
        _cls()
        n_story, n_reel = _pending()
        n_total = n_story + n_reel

        print()
        print(CY + _box(
            "📱  INSTAGRAM BOT",
            "Khodkaar ba Hoshi  —  Menuy Dasti",
        ) + RST)
        print()

        # Pending notification badge
        if n_total > 0:
            print(
                f"  {CYL}🔔  Pending: "
                f"{n_story} Story  |  {n_reel} Reel  "
                f"(upload lazem darand)"
                f"{RST}"
            )
            print()

        print(_row("📸  Sakht",   "→  Story ya Reel besaz",      "1"))
        print(_row("📤  Upload",  "→  Be Instagram befrest",      "2"))
        print(_sep())
        print(_row("Khorooj", num="0"))
        print()

        choice = input(f"  {CYL}Entekhab:{RST} ").strip()

        if choice == "1":
            _menu_sakht()

        elif choice == "2":
            _menu_upload()

        elif choice in ("0", ""):
            _cls()
            print(f"\n{CG}  Khoda Hafez! 👋{RST}\n")
            break

        else:
            _err("Entekhab namotabar.")
            time.sleep(1)


# ══════════════════════════════════════════════════════════════════════════════
# Entry point
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    try:
        _menu_main()
    except KeyboardInterrupt:
        print(f"\n\n{CR}  Lagv shod (Ctrl+C).{RST}\n")
        sys.exit(0)
