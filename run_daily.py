"""
run_daily.py — Automated daily Instagram pipeline

Runs once per day (via Windows Task Scheduler or manually):
  1. Create Story  — AI content → image → story PNG → upload to Instagram
  2. Create Reel   — oldest raw video → Instagram Reel (saved, not uploaded)

Usage:
  python run_daily.py                   # full pipeline
  python run_daily.py --no-story        # skip story creation
  python run_daily.py --no-reel         # skip reel creation
  python run_daily.py --upload-reel     # also upload reel after creating
  python run_daily.py --force           # ignore already-ran-today check
"""

import sys
import gc
import time
import shutil
import logging
import argparse
import subprocess
from datetime import datetime, date
from pathlib import Path
from typing import Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent))

from config import Config
from utils.helpers import setup_logger
from core.content_generator import ContentGenerator
from core.image_generator import ImageGenerator
from core.story_designer import StoryDesigner
from media.video_creator import VideoCreator
from platforms.instagram_uploader import InstagramUploader

SUPPORTED_EXTS = {".mp4", ".mov", ".mkv", ".avi"}


# ── Lock / already-ran guard ──────────────────────────────────────────────────

def _lock_file(config: Config, run_date: date) -> Path:
    return config.LOGS_DIR / f"daily_ran_{run_date.isoformat()}.lock"


def _already_ran(config: Config) -> bool:
    return _lock_file(config, date.today()).exists()


def _mark_ran(config: Config, run_date: date) -> None:
    _lock_file(config, run_date).write_text(datetime.now().isoformat())


# ── Helpers ───────────────────────────────────────────────────────────────────

def _probe_readable(path: Path) -> bool:
    """Return True only if ffprobe can extract a valid duration (moov atom present)."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=10,
        )
        return r.returncode == 0 and bool(r.stdout.strip())
    except Exception:
        return False


def _pick_oldest_raw(config: Config) -> Optional[Path]:
    videos = [
        v for v in config.RAW_VIDEOS_DIR.iterdir()
        if v.is_file() and v.suffix.lower() in SUPPORTED_EXTS
    ]
    if not videos:
        return None
    videos.sort(key=lambda v: v.stat().st_mtime)
    for video in videos:
        if _probe_readable(video):
            return video
        print(f"   Skipping corrupt video: {video.name}")
    return None


# ── Step 1: Story ─────────────────────────────────────────────────────────────

def _make_and_upload_story(
    config: Config, logger: logging.Logger
) -> Tuple[Optional[Path], bool]:
    logger.info("Daily story: starting AI pipeline")
    try:
        print("   Generating AI content...")
        content = ContentGenerator(config).generate()
        print(f"   Topic  : {content.get('topic', '?')}")
        print(f"   English: {content['english'][:60]}...")

        print("   Generating AI image...")
        image = ImageGenerator(config).generate(
            content.get("image_prompt") or content["english"]
        )

        print("   Designing story PNG...")
        story = StoryDesigner(config).design(image, content)
        logger.info(f"Story PNG: {story.name}")
        print(f"   Story  : {story.name}")

        print("   Uploading to Instagram Story...")
        uploader = InstagramUploader(config)
        try:
            result = uploader.upload_story(story)
        finally:
            uploader.close()

        if result.get("success"):
            dest = config.move_story_to_uploaded(story)
            logger.info(f"Story uploaded + moved: {dest.name}")
            print(f"   Uploaded + moved to uploaded/images/")
            return dest, True
        else:
            logger.error(f"Story upload failed: {result.get('error')}")
            print(f"   Upload failed: {result.get('error', 'unknown')}")
            print(f"   Story saved at: {story} (upload manually via option 3)")
            return story, False

    except Exception as e:
        logger.error(f"Daily story failed: {e}", exc_info=True)
        print(f"   Failed: {e}")
        return None, False


# ── Step 2: Reel ──────────────────────────────────────────────────────────────

def _make_reel(
    config: Config, logger: logging.Logger, upload: bool = False
) -> Optional[Path]:
    video = _pick_oldest_raw(config)
    if not video:
        logger.warning("No raw videos — skipping Reel")
        print("   No raw videos found — skipping Reel")
        return None

    logger.info(f"Reel source: {video.name}")
    print(f"   Raw: {video.name}")

    try:
        vc     = VideoCreator(config)
        output = vc.from_raw_video(video)

        final = config.REELS_DIR / output.name
        if output.resolve() != final.resolve():
            shutil.move(str(output), str(final))
            output = final

        logger.info(f"Reel created: {output.name}")
        print(f"   Reel : {output.name}")

        if upload:
            print("   Uploading Reel to Instagram...")
            uploader = InstagramUploader(config)
            try:
                result = uploader.upload_reel(output, caption="")
            finally:
                uploader.close()

            if result.get("success"):
                dest = config.move_reel_to_uploaded(output)
                logger.info(f"Reel uploaded: {dest.name}")
                print(f"   Uploaded + moved to uploaded/reels/")
                output = dest
            else:
                logger.warning(f"Reel upload failed: {result.get('error')}")
                print(f"   Upload failed (reel saved locally): {result.get('error')}")

        gc.collect()
        time.sleep(1.5)
        for attempt in range(4):
            try:
                config.move_to_raw_used(video)
                logger.info(f"Raw archived: {video.name}")
                break
            except PermissionError:
                gc.collect()
                time.sleep(attempt * 2 + 1)
            except Exception as e:
                logger.warning(f"Could not archive raw '{video.name}': {e}")
                break

        return output

    except Exception as e:
        logger.error(f"Reel creation failed: {e}", exc_info=True)
        print(f"   Failed: {e}")
        return None


# ── Main pipeline ─────────────────────────────────────────────────────────────

def run_daily(
    do_story:      bool = True,
    do_reel:       bool = True,
    upload_reel:   bool = False,
    force:         bool = False,
) -> int:
    config = Config()
    logger = setup_logger("InstagramDaily", config.LOGS_DIR)
    run_date = date.today()

    if not force and _already_ran(config):
        print(f"\n Daily pipeline already ran today ({run_date}). Use --force to override.")
        logger.info("Skipped: already ran today")
        return 0

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"\n{'='*48}")
    print(f"   INSTAGRAM DAILY AUTO  —  {now}")
    print(f"{'='*48}")
    logger.info(f"Daily pipeline started: {now}")

    story_path: Optional[Path] = None
    reel_path:  Optional[Path] = None
    story_ok    = False

    # ── 1. Story ──────────────────────────────────────────────────────────
    if do_story:
        print("\n[1/2] Instagram Story")
        print("─" * 40)
        story_path, story_ok = _make_and_upload_story(config, logger)

    # ── 2. Reel ───────────────────────────────────────────────────────────
    if do_reel:
        print("\n[2/2] Instagram Reel")
        print("─" * 40)
        reel_path = _make_reel(config, logger, upload=upload_reel)

    # ── Summary ───────────────────────────────────────────────────────────
    print(f"\n{'='*48}")
    print("   DAILY SUMMARY")
    print(f"{'='*48}")

    if story_path:
        status = "Uploaded" if story_ok else "Saved (upload pending)"
        print(f"   Story : {story_path.name}  ({status})")
    else:
        print("   Story : skipped / failed")

    if reel_path:
        status = "Uploaded" if upload_reel else "Saved (upload manually)"
        print(f"   Reel  : {reel_path.name}  ({status})")
    else:
        print("   Reel  : skipped / failed")

    print(f"{'='*48}\n")

    logger.info("Daily pipeline complete")
    _mark_ran(config, run_date)
    return 0


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Instagram automated daily pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python run_daily.py                   # story + reel (build only)\n"
            "  python run_daily.py --no-reel         # only story\n"
            "  python run_daily.py --upload-reel     # also upload reel\n"
            "  python run_daily.py --force           # ignore already-ran guard\n"
        ),
    )
    parser.add_argument("--no-story",    action="store_true", help="Skip story creation")
    parser.add_argument("--no-reel",     action="store_true", help="Skip reel creation")
    parser.add_argument("--upload-reel", action="store_true", help="Upload reel after creating")
    parser.add_argument("--force",       action="store_true", help="Ignore already-ran-today guard")
    args = parser.parse_args()

    return run_daily(
        do_story    = not args.no_story,
        do_reel     = not args.no_reel,
        upload_reel = args.upload_reel,
        force       = args.force,
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n Cancelled by user")
        raise SystemExit(0)
    except Exception as e:
        print(f"\n Fatal error: {e}")
        raise SystemExit(1)
