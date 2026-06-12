"""
main.py — Instagram Core Main Application
"""

import sys
import gc
import time as _time
import shutil as _shutil
import logging
from pathlib import Path
from typing import Optional, List

sys.path.insert(0, str(Path(__file__).parent))

from config import Config
from utils.helpers import setup_logger, probe_video

from core.content_generator import ContentGenerator
from core.image_generator import ImageGenerator
from core.story_designer import StoryDesigner
from media.video_creator import VideoCreator
from platforms.instagram_uploader import InstagramUploader


config = Config()
logger = setup_logger("InstagramCore", config.LOGS_DIR)

SUPPORTED_EXTS = {".mp4", ".mov", ".mkv", ".avi"}


# ══════════════════════════════════════════════════════════════════════════════
# STORY
# ══════════════════════════════════════════════════════════════════════════════

def make_story_png() -> Optional[Path]:
    """AI → image → story PNG."""
    print("\n  Create Story PNG")
    print("=" * 42)

    print("\n Step 1/3 — Generating AI content...")
    content = ContentGenerator(config).generate()
    print(f"   Topic  : {content.get('topic', '')}")
    print(f"   English: {content['english'][:60]}...")

    print("\n Step 2/3 — Generating AI image...")
    image = ImageGenerator(config).generate(
        content.get("image_prompt") or content["english"]
    )

    print("\n Step 3/3 — Designing story PNG...")
    story = StoryDesigner(config).design(image, content)
    print(f"\n Story saved: {story.name}")
    return story


def upload_story(story_path: Path) -> bool:
    """Upload a story PNG/MP4 to Instagram and move to uploaded/images/."""
    uploader = InstagramUploader(config)
    try:
        result = uploader.upload_story(story_path)
        if result.get("success"):
            dest = config.move_story_to_uploaded(story_path)
            print(f"   Moved to: uploaded/images/{dest.name}")
            return True
        else:
            print(f"   Upload failed: {result.get('error', 'unknown error')}")
            return False
    finally:
        uploader.close()


def make_and_upload_story() -> None:
    """Full pipeline: AI → story PNG → upload to Instagram."""
    story = make_story_png()
    if not story:
        return
    print(f"\n Uploading story to Instagram...")
    success = upload_story(story)
    if success:
        print(" Story uploaded successfully!")
    else:
        print(f" Story saved at: {story}")
        print(" You can upload it manually via option 3.")


def upload_pending_stories() -> None:
    """Upload all PNG/MP4 files in storage/stories/."""
    stories = sorted(
        [f for f in config.STORIES_DIR.iterdir()
         if f.is_file() and f.suffix.lower() in (".png", ".jpg", ".mp4")],
        key=lambda x: x.stat().st_mtime,
    )
    if not stories:
        print("\n No pending stories found in storage/stories/")
        return

    print(f"\n Found {len(stories)} story/stories to upload:")
    for i, s in enumerate(stories, 1):
        size_kb = s.stat().st_size / 1024
        print(f"   {i:2}. {s.name} ({size_kb:.0f} KB)")

    confirm = input(f"\nUpload all {len(stories)}? (Enter = yes / n = no): ").strip().lower()
    if confirm == "n":
        print("   Cancelled.")
        return

    uploader = InstagramUploader(config)
    ok = fail = 0
    try:
        for i, story in enumerate(stories, 1):
            print(f"\n  [{i}/{len(stories)}] {story.name}")
            result = uploader.upload_story(story)
            if result.get("success"):
                dest = config.move_story_to_uploaded(story)
                print(f"   Uploaded + moved to: uploaded/images/{dest.name}")
                ok += 1
            else:
                print(f"   Failed: {result.get('error', 'unknown')}")
                fail += 1
            if i < len(stories):
                print("   Waiting 30s before next upload...")
                _time.sleep(30)
    finally:
        uploader.close()

    print(f"\n Summary: {ok} uploaded / {fail} failed")


# ══════════════════════════════════════════════════════════════════════════════
# REELS
# ══════════════════════════════════════════════════════════════════════════════


def get_raw_videos() -> List[Path]:
    videos, seen = [], set()
    for v in config.RAW_VIDEOS_DIR.iterdir():
        if not v.is_file():
            continue
        if v.suffix.lower() not in SUPPORTED_EXTS:
            continue
        resolved = v.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        videos.append(v)
    videos.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    return videos


def _parse_video_selection(choice: str, total: int) -> Optional[List[int]]:
    choice = choice.strip()
    if choice == "0":
        return list(range(total))

    # Digit-string mode: "12" → [1,2]  "123" → [1,2,3]  "1234" → [1,2,3,4]
    # Condition: pure digits, no zero, every digit is a valid index, length > 1
    if (
        choice.isdigit()
        and len(choice) > 1
        and "0" not in choice
        and all(int(d) <= total for d in choice)
    ):
        seen_idx: set = set()
        result: List[int] = []
        for d in choice:
            i = int(d) - 1
            if i not in seen_idx:
                seen_idx.add(i)
                result.append(i)
        return result or None

    indices: List[int] = []
    try:
        for part in choice.split(","):
            part = part.strip()
            if "-" in part:
                a, b  = part.split("-", 1)
                start = int(a) - 1
                end   = int(b) - 1
                if not (0 <= start <= end < total):
                    return None
                indices.extend(range(start, end + 1))
            else:
                idx = int(part) - 1
                if not 0 <= idx < total:
                    return None
                indices.append(idx)
    except ValueError:
        return None
    seen_idx2: set = set()
    result2: List[int] = []
    for i in indices:
        if i not in seen_idx2:
            seen_idx2.add(i)
            result2.append(i)
    return result2 if result2 else None


def _analyze_video_mood(video_path: Path) -> str:
    """Analyze video frames to detect mood: energetic / cinematic / chill / trendy."""
    try:
        import numpy as _np
        from moviepy.editor import VideoFileClip as _VFC
        clip = _VFC(str(video_path), audio=False)
        dur  = clip.duration
        times = [max(0.0, min(dur * t, dur - 0.05)) for t in (0.10, 0.30, 0.55, 0.75, 0.92)]
        brightnesses: list = []
        saturations:  list = []
        motions:      list = []
        prev_gray = None
        for t in times:
            frame = clip.get_frame(t).astype(_np.float32)
            gray  = frame[:, :, 0] * 0.299 + frame[:, :, 1] * 0.587 + frame[:, :, 2] * 0.114
            brightnesses.append(float(_np.mean(gray)))
            r = frame[:, :, 0] / 255.0
            g = frame[:, :, 1] / 255.0
            b = frame[:, :, 2] / 255.0
            cmax = _np.maximum(_np.maximum(r, g), b)
            cmin = _np.minimum(_np.minimum(r, g), b)
            sat  = _np.where(cmax > 0.01, (cmax - cmin) / cmax, 0.0)
            saturations.append(float(_np.mean(sat)))
            if prev_gray is not None:
                motions.append(float(_np.mean(_np.abs(gray - prev_gray))))
            prev_gray = gray
        clip.close()

        brightness = float(_np.mean(brightnesses))
        saturation = float(_np.mean(saturations))
        motion     = float(_np.mean(motions)) if motions else 0.0

        if motion > 18 and saturation > 0.28:
            return "energetic"
        if brightness < 88 or saturation < 0.16:
            return "chill"
        if motion > 9:
            return "cinematic"
        return "trendy"
    except Exception:
        return "cinematic"


def _pick_music_for_video(selected_videos: List[Path]) -> Optional[Path]:
    """Auto-detect video mood and pick matching music. User can override."""
    import random as _random
    SUPPORTED = {".mp3", ".wav", ".m4a", ".aac"}
    music_dir = config.INSTAGRAM_MUSIC_DIR
    if not music_dir.exists():
        print(f"   Music folder not found: {music_dir}")
        return None

    mood_map: dict = {}
    for subfolder in sorted(music_dir.iterdir()):
        if not subfolder.is_dir():
            continue
        files = [f for f in subfolder.rglob("*") if f.is_file() and f.suffix.lower() in SUPPORTED]
        if files:
            mood_map[subfolder.name] = files
    if not mood_map:
        flat = [f for f in music_dir.rglob("*") if f.is_file() and f.suffix.lower() in SUPPORTED]
        if flat:
            mood_map["all"] = flat
    if not mood_map:
        print("   No music found in assets/music/instagram/ — using auto-select.")
        return None

    # Detect mood from first valid video
    print("\n   Analyzing video mood...", end="", flush=True)
    detected = _analyze_video_mood(selected_videos[0])
    print(f" {detected}")

    moods = sorted(mood_map.keys())

    # Find closest matching mood folder
    best_mood = detected if detected in mood_map else moods[0]
    auto_track = _random.choice(mood_map[best_mood])

    print(f"   Matched folder : {best_mood}")
    print(f"   Auto-selected  : {auto_track.name}")

    print("\n   Music mood options:")
    print("   0. Use auto-selected  ◄")
    for i, mood in enumerate(moods, 1):
        count  = len(mood_map[mood])
        marker = "  ◄ auto" if mood == best_mood else ""
        print(f"   {i}. {mood:<14} ({count} track{'s' if count > 1 else ''}){marker}")

    while True:
        choice = input("\nSelect mood (Enter/0 = auto): ").strip()
        if choice in ("", "0"):
            print(f"   Using: [{best_mood}] {auto_track.name}")
            return auto_track
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(moods):
                mood   = moods[idx]
                chosen = _random.choice(mood_map[mood])
                print(f"   Selected: [{mood}] {chosen.name}")
                return chosen
            print("   Invalid — try again")
        except ValueError:
            print("   Invalid — try again")


def create_reel() -> Optional[Path]:
    """Create an Instagram Reel from raw video(s)."""
    videos = get_raw_videos()
    if not videos:
        print(f"\n No raw videos found in: {config.RAW_VIDEOS_DIR}")
        return None

    # ffprobe validation — runs quickly, catches moov-atom / truncated files
    print("\n Checking video files...")
    ok_map: dict = {v: probe_video(v) for v in videos}

    print("\n Available raw videos:")
    for i, v in enumerate(videos, 1):
        size_mb = v.stat().st_size / (1024 * 1024)
        tag     = "" if ok_map[v] else "  ⚠  CORRUPT — will be skipped"
        print(f"   {i:2}. {v.name} ({size_mb:.1f} MB){tag}")
    if len(videos) > 1:
        print("\n   0. Combine ALL videos")
        print("   Tip: 1,3,5  or  2-5  or  12 (digits: vids 1&2)  or  123 (vids 1,2,3)")

    if len(videos) == 1:
        indices = [0]
        print("\n   (Tan-ha video auto-entekhaab shod)")
    else:
        while True:
            choice  = input("\nSelect video(s): ").strip()
            indices = _parse_video_selection(choice, len(videos))
            if indices is not None:
                break
            print("   Invalid input — try again")

    chosen   = [videos[i] for i in indices]
    corrupt  = [v for v in chosen if not ok_map[v]]
    selected = [v for v in chosen if ok_map[v]]

    if corrupt:
        print(f"\n   ⚠  {len(corrupt)} corrupt file(s) removed from selection:")
        for v in corrupt:
            print(f"      ✖  {v.name}  (moov atom missing or file incomplete)")

    if not selected:
        print("\n   No valid videos remain — cannot create reel.")
        return None

    print(f"\n Selected {len(selected)} valid video(s):")
    for v in selected:
        print(f"   • {v.name}")

    manual_music = _pick_music_for_video(selected)

    vc = VideoCreator(config)
    if len(selected) == 1:
        output = vc.from_raw_video(selected[0], forced_music=manual_music)
    else:
        output = vc.from_multiple_raw(selected, forced_music=manual_music)

    final_path = config.REELS_DIR / output.name
    if output.resolve() != final_path.resolve():
        _shutil.move(str(output), str(final_path))
        output = final_path

    print(f"\n Reel created: {output.name}")
    print(f"   Location: {config.REELS_DIR}")

    gc.collect()
    _time.sleep(1.5)
    for raw in selected:
        for attempt in range(4):
            try:
                config.move_to_raw_used(raw)
                logger.info(f"Raw archived: {raw.name}")
                break
            except PermissionError:
                gc.collect()
                _time.sleep(attempt * 2 + 1)
            except Exception as e:
                logger.warning(f"Could not archive '{raw.name}': {e}")
                break
        else:
            logger.warning(f"Could not archive raw video after 4 tries — still in raw/: {raw.name}")

    return output


def upload_reel(reel_path: Path, caption: str = "") -> bool:
    """Upload a Reel MP4 to Instagram and move to uploaded/reels/."""
    uploader = InstagramUploader(config)
    try:
        result = uploader.upload_reel(reel_path, caption=caption)
        if result.get("success"):
            dest = config.move_reel_to_uploaded(reel_path)
            print(f"   Moved to: uploaded/reels/{dest.name}")
            return True
        else:
            print(f"   Upload failed: {result.get('error', 'unknown error')}")
            return False
    finally:
        uploader.close()


def create_and_upload_reel() -> None:
    """Full pipeline: select raw video → create Reel → upload to Instagram."""
    reel = create_reel()
    if not reel:
        return
    print(f"\n Uploading reel to Instagram...")
    success = upload_reel(reel)
    if success:
        print(" Reel uploaded successfully!")
    else:
        print(f" Reel saved at: {reel}")
        print(" You can upload it manually via Upload → Reels.")


def upload_pending_reels() -> None:
    """Upload all MP4 files in storage/reels/."""
    reels = sorted(
        [f for f in config.REELS_DIR.iterdir()
         if f.is_file() and f.suffix.lower() == ".mp4"],
        key=lambda x: x.stat().st_mtime,
    )
    if not reels:
        print("\n No pending reels found in storage/reels/")
        return

    print(f"\n Found {len(reels)} reel(s) to upload:")
    for i, r in enumerate(reels, 1):
        size_mb = r.stat().st_size / (1024 * 1024)
        print(f"   {i:2}. {r.name} ({size_mb:.1f} MB)")

    confirm = input(f"\nUpload all {len(reels)}? (Enter = yes / n = no): ").strip().lower()
    if confirm == "n":
        print("   Cancelled.")
        return

    uploader = InstagramUploader(config)
    ok = fail = 0
    try:
        for i, reel in enumerate(reels, 1):
            print(f"\n  [{i}/{len(reels)}] {reel.name}")
            result = uploader.upload_reel(reel, caption="")
            if result.get("success"):
                dest = config.move_reel_to_uploaded(reel)
                print(f"   Uploaded + moved to: uploaded/reels/{dest.name}")
                ok += 1
            else:
                print(f"   Failed: {result.get('error', 'unknown')}")
                fail += 1
            if i < len(reels):
                print("   Waiting 60s before next upload...")
                _time.sleep(60)
    finally:
        uploader.close()

    print(f"\n Summary: {ok} uploaded / {fail} failed")


# ══════════════════════════════════════════════════════════════════════════════
# UPLOAD ALL
# ══════════════════════════════════════════════════════════════════════════════

def upload_all() -> None:
    """Upload all pending stories and reels."""
    print("\n Upload All Pending")
    print("=" * 42)

    stories = [f for f in config.STORIES_DIR.iterdir()
               if f.is_file() and f.suffix.lower() in (".png", ".jpg", ".mp4")]
    reels   = [f for f in config.REELS_DIR.iterdir()
               if f.is_file() and f.suffix.lower() == ".mp4"]

    total = len(stories) + len(reels)
    if total == 0:
        print("   No pending files found.")
        return

    print(f"   Stories : {len(stories)}")
    print(f"   Reels   : {len(reels)}")

    ok = fail = 0
    uploader = InstagramUploader(config)

    try:
        for i, story in enumerate(sorted(stories, key=lambda x: x.stat().st_mtime), 1):
            print(f"\n  [Story {i}/{len(stories)}] {story.name}")
            result = uploader.upload_story(story)
            if result.get("success"):
                dest = config.move_story_to_uploaded(story)
                print(f"   Uploaded + moved")
                ok += 1
            else:
                print(f"   Failed: {result.get('error', 'unknown')}")
                fail += 1
            if i < len(stories) or reels:
                _time.sleep(30)

        for i, reel in enumerate(sorted(reels, key=lambda x: x.stat().st_mtime), 1):
            print(f"\n  [Reel {i}/{len(reels)}] {reel.name}")
            result = uploader.upload_reel(reel, caption="")
            if result.get("success"):
                dest = config.move_reel_to_uploaded(reel)
                print(f"   Uploaded + moved")
                ok += 1
            else:
                print(f"   Failed: {result.get('error', 'unknown')}")
                fail += 1
            if i < len(reels):
                _time.sleep(60)

    finally:
        uploader.close()

    print(f"\n Summary: {ok} uploaded / {fail} failed")


# ══════════════════════════════════════════════════════════════════════════════
# SESSION
# ══════════════════════════════════════════════════════════════════════════════

def session_menu() -> None:
    while True:
        print("""
--------------------------------------------------
   Instagram Session
--------------------------------------------------
  1. Check status
  2. Force re-login (reset session)
  0. Back
--------------------------------------------------""")
        choice = input("  Select: ").strip()

        if choice == "1":
            uploader = InstagramUploader(config)
            status   = uploader.session_status()
            uploader.close()
            print(f"\n   Status: {status}")

        elif choice == "2":
            confirm = input("\n  Reset Instagram session? (Enter = yes / n = no): ").strip().lower()
            if confirm != "n":
                uploader = InstagramUploader(config)
                ok       = uploader.force_relogin()
                uploader.close()
                print("\n   Re-login successful!" if ok else "\n   Re-login failed — check credentials.")

        elif choice in ("0", ""):
            break

        else:
            print("  Invalid")

        if choice not in ("0", ""):
            input("\n  Press Enter to continue...")


# ══════════════════════════════════════════════════════════════════════════════
# MENU
# ══════════════════════════════════════════════════════════════════════════════

def _count_pending() -> tuple:
    stories = len([f for f in config.STORIES_DIR.iterdir()
                   if f.is_file() and f.suffix.lower() in (".png", ".jpg", ".mp4")])
    reels   = len([f for f in config.REELS_DIR.iterdir()
                   if f.is_file() and f.suffix.lower() == ".mp4"])
    return stories, reels


def main_menu() -> None:
    stories, reels = _count_pending()
    print(f"""
==========================================
         INSTAGRAM CORE
==========================================

  STORY:
    1. Create + Upload Story    (AI → upload)
    2. Create Story Only        (save PNG)
    3. Upload Pending Stories   ({stories} ready)

  REELS:
    4. Create Instagram Reel    (raw video)
    5. Upload Pending Reels     ({reels} ready)

  ALL:
    6. Upload Everything        ({stories + reels} total)

  TOOLS:
    7. Session Status / Reset

    0. Exit
==========================================""")


def main() -> None:
    while True:
        main_menu()
        choice = input("Select: ").strip()

        if choice == "1":
            make_and_upload_story()

        elif choice == "2":
            make_story_png()

        elif choice == "3":
            upload_pending_stories()

        elif choice == "4":
            create_reel()

        elif choice == "5":
            upload_pending_reels()

        elif choice == "6":
            upload_all()

        elif choice == "7":
            session_menu()
            continue

        elif choice == "0":
            print("\n Goodbye!")
            break

        else:
            print("  Invalid option")

        if choice not in ("0", "7"):
            input("\nPress Enter to continue...")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n Cancelled by user.")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        print(f"\n Fatal error: {e}")
        input("\nPress Enter to exit...")
