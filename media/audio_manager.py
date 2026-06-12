"""
media/audio_manager.py
======================
Platform-aware music manager.

ROOT CAUSE OF MID-VIDEO SILENCE — FIXED IN THIS VERSION
---------------------------------------------------------

Bug 1 — [original] * loops → same reader reference
  Old code:
      parts  = [original] * loops   ← N refs to ONE AudioFileClip object
      looped = concatenate_audioclips(parts)
  concatenate_audioclips iterates over parts and calls each clip's reader
  sequentially. Because all items point to the SAME reader, after the first
  pass the file position is at EOF — every subsequent "copy" reads nothing
  → silence for the looped portion.

  FIX: _build_audio_clip_with_ffmpeg() — all trimming, looping, volume,
  and fading is done by a SINGLE ffmpeg subprocess call. ffmpeg handles
  looping via -stream_loop, volume via -af volume=, fades via afade.
  No MoviePy lazy-clip chain involved at all.

Bug 2 — GC of AudioFileClip during render
  MoviePy's write_videofile() is lazy. If the Python AudioFileClip object
  that holds the audio is garbage-collected before rendering completes,
  the underlying reader closes → silence in the rendered file.

  FIX: _build_audio_clip_with_ffmpeg writes to a temp WAV file on disk.
  The returned AudioFileClip reads from that file. The file is on disk —
  it cannot be GC'd. The clip object just needs to survive until
  write_videofile() finishes, which it does because video_creator holds
  a reference to it.

Bug 3 — Logo intro adds N seconds AFTER audio is trimmed
  Logo intro is prepended via ffmpeg concat AFTER write_videofile.
  The final video is longer than the audio by logo_duration seconds.

  FIX: logo_intro_builder uses -af apad in ffmpeg concat so the audio
  track is padded with silence to match the full video length. This is
  inaudible because the music already has a fade-out applied.
"""

import json
import logging
import os
import random
import subprocess
import tempfile
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from moviepy.editor import AudioFileClip

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Music history — از تکرار موزیک جلوگیری می‌کند
# ─────────────────────────────────────────────────────────────────────────────

_HISTORY_FILE = Path(__file__).parent.parent / "storage" / "music_history.json"
_MAX_HISTORY  = 30  # از بین N موزیک آخر تکرار نکن


def _load_music_history() -> List[str]:
    try:
        if _HISTORY_FILE.is_file():
            data = json.loads(_HISTORY_FILE.read_text(encoding="utf-8"))
            return data.get("played", [])
    except Exception:
        pass
    return []


def _save_music_history(played: List[str]) -> None:
    try:
        _HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        _HISTORY_FILE.write_text(
            json.dumps({"played": played[-_MAX_HISTORY:]}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning(f"music_history save error: {e}")


def _pick_no_repeat(candidates: List[Path]) -> Optional[Path]:
    """
    از لیست candidates یکی انتخاب می‌کند که اخیراً پخش نشده.
    وقتی همه پخش شدند → تاریخچه پاک و از اول شروع می‌کند.
    """
    if not candidates:
        return None

    played       = _load_music_history()
    played_names = set(played[-_MAX_HISTORY:])
    fresh        = [c for c in candidates if c.name not in played_names]

    if not fresh:
        logger.info(f"همه {len(candidates)} موزیک پخش شدند — تاریخچه ریست شد")
        played = []
        fresh  = list(candidates)
        _save_music_history([])

    selected = random.choice(fresh)
    played.append(selected.name)
    _save_music_history(played)

    logger.info(
        f"موزیک (no-repeat): {selected.name} | "
        f"تاریخچه: {min(len(played), _MAX_HISTORY)}/{len(candidates)}"
    )
    return selected


# ─────────────────────────────────────────────────────────────────────────────
# Beat sync helpers
# ─────────────────────────────────────────────────────────────────────────────

def detect_beats(music_path: Path) -> List[float]:
    """
    Beat timestamps (ثانیه) را از فایل موزیک برمی‌گرداند.
    اگر librosa نباشد → لیست خالی (graceful fallback).
    """
    try:
        import librosa  # type: ignore
    except ImportError:
        logger.warning("librosa نصب نیست — beat sync غیرفعال. pip install librosa soundfile")
        return []
    try:
        y, sr = librosa.load(str(music_path), sr=None, duration=120.0, mono=True)
        tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
        beat_times: List[float] = librosa.frames_to_time(beat_frames, sr=sr).tolist()
        tempo_bpm = float(tempo.item()) if hasattr(tempo, "item") else float(tempo)
        logger.info(f"Beat detection: {len(beat_times)} beats @ {tempo_bpm:.1f} BPM — {music_path.name}")
        return beat_times
    except Exception as exc:
        logger.warning(f"Beat detection خطا: {exc}")
        return []


def snap_to_beat(proposed: float, beats: List[float], window: float = 0.25) -> float:
    """
    proposed را به نزدیک‌ترین beat در بازه window ثانیه snap می‌کند.
    اگر beat ای در بازه نباشد، proposed را بدون تغییر برمی‌گرداند.
    """
    if not beats:
        return proposed
    nearest = min(beats, key=lambda b: abs(b - proposed))
    if abs(nearest - proposed) <= window:
        logger.debug(f"Beat snap: {proposed:.3f}s → {nearest:.3f}s (Δ={abs(nearest-proposed)*1000:.0f}ms)")
        return nearest
    return proposed


def find_music_offset(beats: List[float], first_cut_time: float) -> float:
    """
    محاسبه می‌کند موزیک باید از چه لحظه‌ای شروع کند تا
    اولین cut ویدیو دقیقاً روی یک beat بیفتد.

    منطق:
      - first_cut_time = زمان اولین cut در ویدیو (ثانیه از ابتدای ویدیو)
      - beat period = فاصله میانگین بین beat ها
      - offset = کوچک‌ترین عدد مثبت که:
            (first_cut_time + offset) % beat_period ≈ 0
        یعنی: موزیک از offset ثانیه شروع می‌کند،
        وقتی ویدیو به first_cut_time می‌رسد، موزیک دقیقاً روی یک beat است.

    مثال:
      beats هر ۰.۶۲۵ ثانیه (۹۶ BPM)
      first_cut = ۹.۵ ثانیه
      9.5 / 0.625 = 15.2  → باقی‌مانده = 0.2 beat = 0.125 ثانیه
      → موزیک از 0.125 ثانیه جلوتر شروع کن تا cut روی beat بیفتد
    """
    if not beats or len(beats) < 4:
        return 0.0

    # محاسبه beat period از میانگین فاصله‌ها
    diffs = [beats[i+1] - beats[i] for i in range(min(len(beats)-1, 16))]
    beat_period = sum(diffs) / len(diffs)

    if beat_period <= 0.05:
        return 0.0

    # چقدر first_cut از یک beat کامل فاصله دارد
    remainder = first_cut_time % beat_period
    offset = remainder  # موزیک را به اندازه remainder جلو ببر

    # اگر offset خیلی کوچک باشد (تقریباً روی beat) صفر کن
    if offset < 0.05:
        offset = 0.0

    logger.info(
        f"Music offset: {offset:.3f}s | beat_period={beat_period:.3f}s | "
        f"first_cut={first_cut_time:.3f}s → روی beat align شد"
    )
    return offset


class Platform(Enum):
    YOUTUBE   = "youtube"
    INSTAGRAM = "instagram"


class AudioManager:
    SUPPORTED_FORMATS = {".mp3", ".wav", ".m4a", ".aac"}

    MOOD_KEYWORDS = {
        "chill":     ["cafe", "coffee", "rain", "night", "evening", "sunset", "calm"],
        "cinematic": ["street", "city", "vienna", "walk", "palace", "museum", "schonbrunn"],
        "energetic": ["dance", "crowd", "people", "party", "fast", "market"],
        "trendy":    ["reels", "viral", "trend", "instagram", "shorts"],
    }

    PLATFORM_DEFAULTS = {
        Platform.YOUTUBE:   ["cinematic", "calm", "chill", "energetic", "random"],
        Platform.INSTAGRAM: ["trendy", "chill", "energetic", "cinematic", "random"],
    }

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)
        self.dirs: Dict[Platform, Path] = {
            Platform.YOUTUBE:   self.base_dir / "youtube",
            Platform.INSTAGRAM: self.base_dir / "instagram",
        }
        self._cache: Dict[Platform, Dict[str, List[Path]]] = {}
        self._scan()

    # ──────────────────────────────────────────────────────────────────
    # Scanning
    # ──────────────────────────────────────────────────────────────────

    def _scan(self) -> None:
        for platform, folder in self.dirs.items():
            folder.mkdir(parents=True, exist_ok=True)
            mood_map: Dict[str, List[Path]] = {}
            for file in folder.rglob("*"):
                if file.is_file() and file.suffix.lower() in self.SUPPORTED_FORMATS:
                    mood = file.parent.name.lower()
                    if mood == platform.value:
                        mood = "random"
                    mood_map.setdefault(mood, []).append(file)
            self._cache[platform] = mood_map
            total = sum(len(f) for f in mood_map.values())
            if total:
                logger.info(f"[{platform.value}] {total} music file(s) indexed.")
            else:
                logger.debug(f"[{platform.value}] Music folder empty: {folder}")

    # ──────────────────────────────────────────────────────────────────
    # Selection
    # ──────────────────────────────────────────────────────────────────

    def _detect_mood(self, video_name: str = "") -> str:
        name = video_name.lower()
        for mood, keywords in self.MOOD_KEYWORDS.items():
            if any(word in name for word in keywords):
                return mood
        return "random"

    def get_random(self, platform: Platform, video_name: str = "") -> Optional[Path]:
        """
        موزیک انتخاب می‌کند:
        1. mood ویدیو را تشخیص می‌دهد
        2. از همان mood که اخیراً پخش نشده انتخاب می‌کند
        3. اگر همه آن mood پخش شد → mood بعدی را امتحان می‌کند
        4. اگر همه چیز پخش شد → تاریخچه ریست و از mood اصلی شروع می‌کند
        """
        mood_map = self._cache.get(platform, {})
        if not mood_map:
            logger.warning(f"[{platform.value}] No music files available.")
            return None

        detected   = self._detect_mood(video_name)
        priorities = [detected] + [
            m for m in self.PLATFORM_DEFAULTS.get(platform, ["random"])
            if m != detected
        ]
        for m in mood_map:
            if m not in priorities:
                priorities.append(m)

        played       = _load_music_history()
        played_names = set(played[-_MAX_HISTORY:])

        # هر mood را به ترتیب اولویت امتحان کن
        for mood in priorities:
            tracks = mood_map.get(mood, [])
            if not tracks:
                continue
            fresh = [t for t in tracks if t.name not in played_names]
            if fresh:
                selected = random.choice(fresh)
                played.append(selected.name)
                _save_music_history(played)
                logger.info(f"[{platform.value}] ✅ {selected.name} [mood={mood}]")
                return selected

        # همه پخش شدند → تاریخچه ریست، از mood اصلی شروع
        logger.info(f"[{platform.value}] همه ترک‌ها پخش شدند — تاریخچه ریست شد")
        _save_music_history([])
        primary = mood_map.get(detected) or next(iter(mood_map.values()), [])
        if primary:
            selected = random.choice(primary)
            _save_music_history([selected.name])
            logger.info(f"[{platform.value}] ✅ (after reset) {selected.name} [mood={detected}]")
            return selected

        return None

    def select_music(
        self,
        platform: Platform,
        video_name: str = "",
        forced_path: Optional[Path] = None,
    ) -> Optional[Path]:
        """
        موزیک را انتخاب می‌کند — باید قبل از ساخت صحنه‌ها صدا زده شود.
        forced_path: اگر کاربر دستی انتخاب کرده باشد.
        """
        if forced_path is not None and forced_path.is_file():
            logger.info(f"[{platform.value}] موزیک دستی: {forced_path.name}")
            return forced_path
        return self.get_random(platform, video_name)

    # ──────────────────────────────────────────────────────────────────
    # Core audio builder — 100% ffmpeg, no MoviePy lazy chain
    # ──────────────────────────────────────────────────────────────────

    @staticmethod
    def _get_audio_duration(path: Path) -> float:
        """Read audio file duration with ffprobe."""
        try:
            result = subprocess.run(
                [
                    "ffprobe", "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    str(path),
                ],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode == 0 and result.stdout.strip():
                return float(result.stdout.strip())
        except Exception as e:
            logger.warning(f"ffprobe duration failed for {path.name}: {e}")
        return 0.0

    @staticmethod
    def _build_audio_with_ffmpeg(
        music_path: Path,
        target_duration: float,
        volume: float,
        music_offset: float = 0.0,   # ← جدید: offset برای beat alignment
        fade_in: float  = 1.0,
        fade_out: float = 2.5,
    ) -> Optional[Path]:
        """
        یک WAV دقیقاً به اندازه target_duration ثانیه می‌سازد.

        music_offset: موزیک از این لحظه شروع می‌کند (ثانیه).
          محاسبه شده توسط find_music_offset() تا اولین cut ویدیو
          دقیقاً روی یک beat موزیک بیفتد.
          offset با atrim در filter chain اعمال می‌شود (نه input -ss)
          تا -stream_loop -1 درست کار کند.
        """
        music_dur = AudioManager._get_audio_duration(music_path)
        if music_dur <= 0:
            logger.error(f"Could not read duration: {music_path.name}")
            return None

        if music_offset < 0.0:
            logger.warning(f"Negative music_offset {music_offset:.3f}s clamped to 0.0")
            music_offset = 0.0
        if music_dur > 0 and music_offset >= music_dur:
            music_offset = music_offset % music_dur

        target_dur   = float(target_duration)
        fade_out_dur = min(fade_out, target_dur * 0.10)
        fade_in_dur  = min(fade_in,  target_dur * 0.05)

        tmp = tempfile.NamedTemporaryFile(
            suffix=".wav", delete=False, prefix="dshorts_audio_"
        )
        tmp_path = Path(tmp.name)
        tmp.close()

        af_parts = []
        if music_offset > 0.01:
            af_parts.append(f"atrim=start={music_offset:.4f},asetpts=PTS-STARTPTS")

        if volume != 1.0:
            af_parts.append(f"volume={volume:.4f}")
        if fade_in_dur > 0.05:
            af_parts.append(f"afade=t=in:st=0:d={fade_in_dur:.2f}")
        fade_out_start = max(0.0, target_dur - fade_out_dur)
        if fade_out_dur > 0.05:
            af_parts.append(f"afade=t=out:st={fade_out_start:.2f}:d={fade_out_dur:.2f}")

        af_filter = ",".join(af_parts) if af_parts else "anull"

        cmd = [
            "ffmpeg", "-y",
            "-stream_loop", "-1",
            "-i", str(music_path),
            "-t", str(target_dur),
            "-af", af_filter,
            "-ar", "44100",
            "-ac", "2",
            "-c:a", "pcm_s16le",
            str(tmp_path),
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if result.returncode != 0:
                logger.error(
                    f"ffmpeg audio build failed ({music_path.name}):\n"
                    f"  {result.stderr[-600:]}"
                )
                tmp_path.unlink(missing_ok=True)
                return None

            out_dur = AudioManager._get_audio_duration(tmp_path)
            if out_dur < target_dur * 0.98:
                logger.error(
                    f"Audio too short: {out_dur:.1f}s vs {target_dur:.1f}s — {music_path.name}"
                )
                tmp_path.unlink(missing_ok=True)
                return None

            logger.info(
                f"Audio ✅ {out_dur:.1f}s | vol={volume:.0%} | "
                f"offset={music_offset:.3f}s | {music_path.name}"
            )
            return tmp_path

        except subprocess.TimeoutExpired:
            logger.error(f"ffmpeg audio timeout: {music_path.name}")
            tmp_path.unlink(missing_ok=True)
            return None
        except Exception as e:
            logger.error(f"ffmpeg audio exception: {e}")
            tmp_path.unlink(missing_ok=True)
            return None

    # ──────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────

    def create_audio(
        self,
        video_duration: float,
        platform: "Platform",
        volume: float = 0.25,
        video_name: str = "",
        _forced_path: Optional[Path] = None,
        music_offset: float = 0.0,   # ← جدید: برای beat alignment
    ) -> Optional[AudioFileClip]:
        """
        یک AudioFileClip آماده برمی‌گرداند.

        music_offset: موزیک از این ثانیه شروع می‌کند تا اولین
        cut ویدیو دقیقاً روی یک beat بیفتد. محاسبه با find_music_offset().
        """
        music_path = _forced_path if _forced_path else self.get_random(platform, video_name)
        if not music_path:
            logger.warning(f"[{platform.value}] No music — video will be silent.")
            return None

        tmp_path: Optional[Path] = None
        try:
            tmp_path = self._build_audio_with_ffmpeg(
                music_path      = music_path,
                target_duration = float(video_duration),
                volume          = volume,
                music_offset    = music_offset,
            )
            if tmp_path is None:
                return None

            clip = AudioFileClip(str(tmp_path))
            clip._dshorts_tmp_path = tmp_path
            return clip

        except Exception as e:
            logger.error(f"create_audio failed: {e}", exc_info=True)
            if tmp_path:
                tmp_path.unlink(missing_ok=True)
            return None

    def create_audio_from_file(
        self,
        music_path: Path,
        video_duration: float,
        volume: float = 0.25,
        music_offset: float = 0.0,   # ← جدید
    ) -> Optional[AudioFileClip]:
        """همان create_audio اما با فایل مشخص (برای beat sync)."""
        music_path = Path(music_path)
        if not music_path.exists():
            logger.error(f"Music file not found: {music_path}")
            return None
        return self.create_audio(
            video_duration = video_duration,
            platform       = Platform.YOUTUBE,
            volume         = volume,
            video_name     = music_path.name,
            _forced_path   = music_path,
            music_offset   = music_offset,
        )

    def list_all(self) -> Dict[str, List[str]]:
        return {
            platform.value: [
                str(file.relative_to(self.dirs[platform]))
                for files in moods.values()
                for file in files
            ]
            for platform, moods in self._cache.items()
        }


def remove_audio(video_clip):
    return video_clip.without_audio()
