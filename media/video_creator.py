"""
media/video_creator.py — Instagram Reels creator
=================================================
Renders 9:16 vertical videos for Instagram Reels.
Output: ig_*.mp4 in storage/reels/
"""

import random
import logging
import subprocess
import shutil
from pathlib import Path
from typing import Optional, List, Dict

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

if not hasattr(Image, "ANTIALIAS"):
    Image.ANTIALIAS = Image.Resampling.LANCZOS

from moviepy.editor import (
    ImageClip,
    VideoFileClip,
    concatenate_videoclips,
    CompositeVideoClip,
)
from moviepy.video.fx.all import fadein, fadeout

from config import Config
from media.audio_manager import AudioManager, Platform
from media.logo_intro_builder import LogoIntroBuilder
from utils.helpers import get_timestamp

logger = logging.getLogger(__name__)


class VideoCreator:
    AUDIO_CODEC    = "aac"
    AUDIO_BITRATE  = "192k"
    CPU_CRF        = "18"
    CPU_PRESET     = "medium"

    TARGET_SCENES          = 5
    EXTRACT_SAFETY_MARGIN  = 0.5

    BRAND_TEXT = "@vienna_streetvibes"

    TEXTS_MINIMAL = ["Vienna", "Hidden Vienna", "Vienna Walk", "Street Vibes", "Quiet Vienna"]
    TEXTS_BOLD    = [
        "Vienna hits different", "This city has a mood",
        "POV: walking through Vienna", "Wait for this view", "Vienna street vibes",
    ]
    HOOK_TEXTS_SOFT = [
        "A quiet moment in Vienna", "Hidden Vienna",
        "Vienna looks different here", "Slow walk through Vienna",
    ]
    HOOK_TEXTS_CURIOSITY = [
        "WAIT FOR THE LAST SCENE", "DON'T BLINK",
        "THIS STREET FEELS UNREAL", "HIDDEN SPOT IN VIENNA", "THIS VIEW HITS DIFFERENT",
    ]

    VARIATION_PRESETS: List[Dict] = [
        {
            "name": "minimal", "text_style": "minimal", "hook_style": "soft",
            "cut_style": "cinematic", "show_main_text": True, "show_hook": True,
            "transition_max": 0.32, "micro_zoom": 0.010, "hook_zoom": 0.030,
            "hook_blur": 2.0, "box_alpha": 68,
        },
        {
            "name": "bold", "text_style": "bold", "hook_style": "curiosity",
            "cut_style": "medium", "show_main_text": True, "show_hook": True,
            "transition_max": 0.26, "micro_zoom": 0.014, "hook_zoom": 0.045,
            "hook_blur": 3.0, "box_alpha": 90,
        },
        {
            "name": "clean", "text_style": "minimal", "hook_style": "curiosity",
            "cut_style": "fast", "show_main_text": False, "show_hook": True,
            "transition_max": 0.22, "micro_zoom": 0.012, "hook_zoom": 0.040,
            "hook_blur": 2.5, "box_alpha": 84,
        },
    ]

    def __init__(self, config: Optional[Config] = None) -> None:
        self.config      = config or Config()
        self.audio_mgr   = AudioManager(self.config.MUSIC_BASE_DIR)
        self.logo_intro  = LogoIntroBuilder(self.config)
        self._gpu        = self._detect_gpu()
        self._apply_logo = True
        self.preset      = random.choice(self.VARIATION_PRESETS)

        logger.info(f"Renderer: {self._gpu} | Preset: {self.preset['name']}")

    # ── GPU detection ──────────────────────────────────────────────────────

    def _detect_gpu(self) -> str:
        try:
            result = subprocess.run(
                ["ffmpeg", "-hide_banner", "-encoders"],
                capture_output=True, text=True, timeout=8,
            )
            if "h264_amf" in (result.stdout + result.stderr).lower():
                return "AMD"
        except Exception as e:
            logger.warning(f"GPU detection failed: {e}")
        return "CPU"

    @staticmethod
    def _safe_close_clip(clip) -> None:
        try:
            if clip is not None:
                clip.close()
        except Exception:
            pass

    @staticmethod
    def _probe_readable(path: Path) -> bool:
        """Return True if ffprobe can extract a valid duration from path."""
        try:
            r = subprocess.run(
                [
                    "ffprobe", "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    str(path),
                ],
                capture_output=True, text=True, timeout=10,
            )
            return r.returncode == 0 and bool(r.stdout.strip())
        except Exception:
            return False

    # ── Public rendering methods ───────────────────────────────────────────

    def from_raw_video(
        self,
        video_path: Path,
        platform: str = "instagram",
        forced_music: Optional[Path] = None,
    ) -> Path:
        """Create an Instagram Reel from a single raw video file."""
        video_path = Path(video_path)
        if not video_path.exists():
            raise FileNotFoundError(f"Raw video not found: {video_path}")
        if not self._probe_readable(video_path):
            raise ValueError(
                f"Video unreadable — moov atom missing or file incomplete: {video_path.name}"
            )

        plat     = Platform.INSTAGRAM
        duration = random.randint(self.config.VIDEO_DURATION_MIN, self.config.VIDEO_DURATION_MAX)
        video    = None

        try:
            video = VideoFileClip(str(video_path)).without_audio()
            video = self._crop_9_16(video)
            video = self._apply_cinematic_effects(video)
            final = self._make_rhythmic_scenes_from_single_video(video, duration)

            if self.preset.get("show_main_text", True):
                final = self._add_text_overlay(final)
            if self.preset.get("show_hook", True):
                final = self._add_hook_overlay(final)

            return self._render_with_music(final, plat, "reel",
                                           video_name=video_path.name, forced_music=forced_music)
        finally:
            self._safe_close_clip(video)

    def from_multiple_raw(
        self,
        video_paths: List[Path],
        platform: str = "instagram",
        forced_music: Optional[Path] = None,
    ) -> Path:
        """Create an Instagram Reel by combining multiple raw video files."""
        candidates = [Path(v) for v in video_paths if Path(v).exists()]
        if not candidates:
            raise ValueError("No video files found (paths do not exist).")

        # Guard: reject files ffprobe cannot read (moov atom missing, truncated, etc.)
        valid_videos: List[Path] = []
        for v in candidates:
            if self._probe_readable(v):
                valid_videos.append(v)
            else:
                logger.warning(
                    "Skipping unreadable video '%s' "
                    "(ffprobe could not extract duration — file may be corrupt).",
                    v.name,
                )

        if not valid_videos:
            raise ValueError(
                "All selected video files are unreadable. "
                "They may be incomplete recordings (moov atom missing)."
            )
        if len(valid_videos) == 1:
            return self.from_raw_video(valid_videos[0], forced_music=forced_music)

        plat     = Platform.INSTAGRAM
        duration = random.randint(self.config.VIDEO_DURATION_MIN, self.config.VIDEO_DURATION_MAX)

        random.shuffle(valid_videos)
        selected_videos = valid_videos[: min(4, len(valid_videos))]

        scene_count     = self._choose_scene_count(duration)
        transition      = self._safe_transition_duration()
        scene_durations = self._rhythmic_scene_durations(duration, scene_count, transition)
        scene_sources   = self._build_scene_source_plan(selected_videos, scene_count)

        clips = []
        try:
            for idx, video_path in enumerate(scene_sources):
                clip = VideoFileClip(str(video_path)).without_audio()
                clip = self._crop_9_16(clip)
                clip = self._apply_cinematic_effects(clip)
                clip = self._extract_scene_from_clip(clip, scene_durations[idx], idx, scene_count)
                clip = self._prepare_transition_segment(clip, idx)
                if idx == 0:
                    clip = self._apply_hook_effect(clip)
                if idx > 0:
                    clip = clip.crossfadein(transition)
                clips.append(clip)

            final = concatenate_videoclips(clips, method="compose", padding=-transition)
            if final.duration > duration:
                final = final.subclip(0, duration)

            if self.preset.get("show_main_text", True):
                final = self._add_text_overlay(final)
            if self.preset.get("show_hook", True):
                final = self._add_hook_overlay(final)

            first_name = selected_videos[0].name if selected_videos else ""
            return self._render_with_music(final, plat, "multi",
                                           video_name=first_name, forced_music=forced_music)
        finally:
            for clip in clips:
                self._safe_close_clip(clip)

    # ── Cinematic effects ──────────────────────────────────────────────────

    def _apply_cinematic_effects(self, clip):
        return clip

    # ── Scene count / duration helpers ────────────────────────────────────

    def _choose_scene_count(self, target_duration: float) -> int:
        cut_style = self.preset.get("cut_style", "medium")
        if cut_style == "fast":
            return 4 if target_duration <= 25 else 5
        if cut_style == "cinematic":
            if target_duration <= 30: return 3
            if target_duration <= 45: return 4
            return 5
        if target_duration <= 25: return 3
        if target_duration <= 40: return 4
        return self.TARGET_SCENES

    def _rhythmic_scene_durations(self, target_duration: float, scene_count: int, transition: float) -> List[float]:
        usable   = target_duration + (scene_count - 1) * transition
        cut_style = self.preset.get("cut_style", "medium")
        if cut_style == "fast":
            weights = [0.22, 0.24, 0.25, 0.29] if scene_count == 4 else [0.17, 0.19, 0.20, 0.21, 0.23]
        elif cut_style == "cinematic":
            if scene_count == 3:   weights = [0.28, 0.34, 0.38]
            elif scene_count == 4: weights = [0.24, 0.26, 0.24, 0.26]
            else:                  weights = [0.19, 0.20, 0.20, 0.20, 0.21]
        else:
            if scene_count == 3:   weights = [0.25, 0.34, 0.41]
            elif scene_count == 4: weights = [0.20, 0.27, 0.24, 0.29]
            else:                  weights = [0.16, 0.21, 0.19, 0.21, 0.23]
        total = sum(weights[:scene_count])
        return [(usable * w / total) for w in weights[:scene_count]]

    def _build_scene_source_plan(self, selected_videos: List[Path], scene_count: int) -> List[Path]:
        return [selected_videos[i % len(selected_videos)] for i in range(scene_count)]

    def _make_rhythmic_scenes_from_single_video(self, video, target_duration: float):
        if video.duration <= 3:
            return video
        transition      = self._safe_transition_duration()
        scene_count     = self._choose_scene_count(target_duration)
        scene_durations = self._rhythmic_scene_durations(target_duration, scene_count, transition)
        segments = []

        for idx in range(scene_count):
            seg = self._extract_scene_from_clip(video, scene_durations[idx], idx, scene_count)
            seg = self._prepare_transition_segment(seg, idx)
            if idx == 0:
                seg = self._apply_hook_effect(seg)
            if idx > 0:
                seg = seg.crossfadein(transition)
            segments.append(seg)

        final = concatenate_videoclips(segments, method="compose", padding=-transition)
        if final.duration > target_duration:
            final = final.subclip(0, target_duration)
        return final

    def _extract_scene_from_clip(self, clip, scene_duration: float, scene_index: int, scene_count: int):
        if clip.duration <= scene_duration:
            return clip
        start = self._find_best_scene_start(clip, scene_duration, scene_index, scene_count)
        end   = min(start + scene_duration, clip.duration)
        return clip.subclip(start, end)

    def _find_best_scene_start(self, clip, scene_duration: float, scene_index: int, scene_count: int) -> float:
        max_start = max(0.0, clip.duration - scene_duration - self.EXTRACT_SAFETY_MARGIN)
        if max_start <= 0:
            return 0.0
        base_ratios = {
            3: [0.08, 0.50, 0.88],
            4: [0.06, 0.35, 0.62, 0.88],
            5: [0.05, 0.28, 0.50, 0.72, 0.90],
        }
        ratio_list = base_ratios.get(scene_count, base_ratios[5])
        base_ratio = ratio_list[min(scene_index, len(ratio_list) - 1)]
        candidate_ratios = [max(0.0, base_ratio - 0.06), base_ratio, min(1.0, base_ratio + 0.06)]
        best_start, best_score = max_start * base_ratio, -1.0
        for ratio in candidate_ratios:
            start = max_start * ratio
            score = self._score_scene_window(clip, start, scene_duration)
            if score > best_score:
                best_score, best_start = score, start
        return max(0.0, min(best_start, max_start))

    def _score_scene_window(self, clip, start: float, scene_duration: float) -> float:
        try:
            sample_times = [start + scene_duration * t for t in (0.20, 0.55, 0.85)]
            frames = []
            for t in sample_times:
                t     = max(0.0, min(t, clip.duration - 0.05))
                frame = clip.get_frame(t)
                small = Image.fromarray(frame).resize((80, 142))
                frames.append(np.asarray(small).astype(np.float32))
            gray = [(f[:, :, 0] * 0.299 + f[:, :, 1] * 0.587 + f[:, :, 2] * 0.114) for f in frames]
            motion     = float(np.mean(np.abs(gray[1] - gray[0])) + np.mean(np.abs(gray[2] - gray[1]))) / 2.0
            brightness = float(np.mean(gray[1]))
            contrast   = float(np.std(gray[1]))
            return float(
                min(motion / 22.0, 1.0) * 0.45
                + min(contrast / 55.0, 1.0) * 0.30
                + (1.0 - min(abs(brightness - 120.0) / 120.0, 1.0)) * 0.25
            )
        except Exception:
            return 0.0

    def _safe_transition_duration(self) -> float:
        transition     = getattr(self.config, "TRANSITION_DURATION", 0.5)
        max_transition = float(self.preset.get("transition_max", 0.28))
        return max(0.10, min(float(transition), max_transition))

    def _prepare_transition_segment(self, clip, index: int):
        try:
            clip          = self._micro_zoom(clip, reverse=bool(index % 2))
            fade_duration = min(0.14, max(0.04, clip.duration / 12))
            return clip.fx(fadein, fade_duration).fx(fadeout, fade_duration)
        except Exception as e:
            logger.warning(f"Transition skipped: {e}")
            return clip

    def _apply_hook_effect(self, clip):
        try:
            duration = max(clip.duration, 0.1)
            strength = float(self.preset.get("hook_zoom", 0.040))
            hooked   = clip.resize(lambda t: 1 + strength * min(t / max(duration * 0.35, 0.1), 1))
            hooked   = hooked.crop(
                x_center=self.config.VIDEO_WIDTH / 2,
                y_center=self.config.VIDEO_HEIGHT / 2,
                width=self.config.VIDEO_WIDTH, height=self.config.VIDEO_HEIGHT,
            )
            hooked = hooked.fl(lambda gf, t: self._hook_focus_frame(gf(t), t))
            return hooked.fx(fadein, 0.06)
        except Exception as e:
            logger.warning(f"Hook effect skipped: {e}")
            return clip

    def _hook_focus_frame(self, frame, t: float):
        try:
            hook_blur_duration = 0.75
            hook_max_blur      = float(self.preset.get("hook_blur", 2.5))
            if t >= hook_blur_duration:
                return frame
            blur_radius = hook_max_blur * (1.0 - max(0.0, min(t / hook_blur_duration, 1.0)))
            if blur_radius <= 0.15:
                return frame
            img = Image.fromarray(frame).filter(ImageFilter.GaussianBlur(radius=blur_radius))
            return np.asarray(img)
        except Exception:
            return frame

    def _micro_zoom(self, clip, reverse: bool = False):
        try:
            duration = max(clip.duration, 0.1)
            strength = float(self.preset.get("micro_zoom", 0.012))
            if reverse:
                resized = clip.resize(lambda t: 1 + strength * (1 - t / duration))
            else:
                resized = clip.resize(lambda t: 1 + strength * (t / duration))
            return resized.crop(
                x_center=self.config.VIDEO_WIDTH / 2, y_center=self.config.VIDEO_HEIGHT / 2,
                width=self.config.VIDEO_WIDTH, height=self.config.VIDEO_HEIGHT,
            )
        except Exception as e:
            logger.warning(f"Micro zoom skipped: {e}")
            return clip

    # ── Text / overlay helpers ─────────────────────────────────────────────

    def _choose_main_text(self) -> str:
        if self.preset.get("text_style") == "minimal":
            return random.choice(self.TEXTS_MINIMAL)
        return random.choice(self.TEXTS_BOLD)

    def _choose_hook_text(self) -> str:
        if self.preset.get("hook_style") == "soft":
            return random.choice(self.HOOK_TEXTS_SOFT)
        return random.choice(self.HOOK_TEXTS_CURIOSITY)

    def _load_font(self, size: int) -> ImageFont.ImageFont:
        font_path = getattr(self.config, "FONT_PATH", None)
        if font_path:
            try:
                return ImageFont.truetype(str(font_path), size)
            except Exception:
                pass
        try:
            return ImageFont.load_default(size=size)
        except TypeError:
            return ImageFont.load_default()

    def _add_text_overlay(self, clip, text: Optional[str] = None):
        try:
            text       = text or self._choose_main_text()
            w, h       = self.config.VIDEO_WIDTH, self.config.VIDEO_HEIGHT
            overlay    = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            draw       = ImageDraw.Draw(overlay)
            font       = self._load_font(54)
            small_font = self._load_font(30)
            sub_text   = self.BRAND_TEXT

            box_x1, box_y1, box_x2, box_y2 = 90, 125, w - 90, 265
            draw.rounded_rectangle(
                [(box_x1, box_y1), (box_x2, box_y2)],
                radius=26, fill=(0, 0, 0, int(self.preset.get("box_alpha", 82))),
            )
            font          = self._fit_font(draw, text, font, box_x2 - box_x1 - 60)
            main_bbox     = draw.textbbox((0, 0), text, font=font)
            sub_bbox      = draw.textbbox((0, 0), sub_text, font=small_font)
            draw.text(
                ((w - (main_bbox[2] - main_bbox[0])) / 2, box_y1 + 27),
                text, font=font, fill=(255, 255, 255, 245), stroke_width=2, stroke_fill=(0, 0, 0, 145),
            )
            draw.text(
                ((w - (sub_bbox[2] - sub_bbox[0])) / 2, box_y1 + 88),
                sub_text, font=small_font, fill=(255, 215, 0, 225),
            )
            overlay_clip = (
                ImageClip(np.array(overlay))
                .set_duration(clip.duration)
                .set_fps(self.config.VIDEO_FPS)
                .fadein(0.20).fadeout(0.20)
            )
            return CompositeVideoClip([clip, overlay_clip])
        except Exception as e:
            logger.warning(f"Text overlay skipped: {e}")
            return clip

    def _add_hook_overlay(self, clip):
        try:
            hook_text = self._choose_hook_text()
            w, h      = self.config.VIDEO_WIDTH, self.config.VIDEO_HEIGHT
            duration  = min(3.0, max(1.0, clip.duration))
            overlay   = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            draw      = ImageDraw.Draw(overlay)
            hook_font = self._load_font(72)

            box_x1, box_y1 = 65, int(h * 0.66)
            box_x2, box_y2 = w - 65, box_y1 + 155
            draw.rounded_rectangle([(box_x1, box_y1), (box_x2, box_y2)], radius=30, fill=(0, 0, 0, 125))
            hook_font   = self._fit_font(draw, hook_text, hook_font, box_x2 - box_x1 - 70)
            bbox        = draw.textbbox((0, 0), hook_text, font=hook_font)
            text_width  = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
            draw.text(
                ((w - text_width) / 2, box_y1 + (155 - text_height) / 2 - 8),
                hook_text, font=hook_font, fill=(255, 255, 255, 255), stroke_width=3, stroke_fill=(0, 0, 0, 180),
            )
            overlay_clip = (
                ImageClip(np.array(overlay))
                .set_duration(duration)
                .set_fps(self.config.VIDEO_FPS)
                .fadein(0.12).fadeout(0.25)
            )
            return CompositeVideoClip([clip, overlay_clip])
        except Exception as e:
            logger.warning(f"Hook overlay skipped: {e}")
            return clip

    def _fit_font(self, draw, text: str, font, max_width: int) -> ImageFont.ImageFont:
        try:
            while True:
                bbox  = draw.textbbox((0, 0), text, font=font)
                width = bbox[2] - bbox[0]
                if width <= max_width:
                    return font
                current_size = getattr(font, "size", 42)
                if current_size <= 24:
                    return font
                font = self._load_font(current_size - 4)
        except Exception:
            return font

    def _crop_9_16(self, clip):
        width, height  = clip.size
        target_w       = self.config.VIDEO_WIDTH
        target_h       = self.config.VIDEO_HEIGHT
        current_ratio  = width / height
        target_ratio   = target_w / target_h

        if current_ratio > target_ratio:
            scale = target_h / height
            new_w = int(width * scale)
            clip  = clip.resize((new_w, target_h))
            x1    = (new_w - target_w) // 2
            clip  = clip.crop(x1=x1, x2=x1 + target_w)
        else:
            scale = target_w / width
            new_h = int(height * scale)
            clip  = clip.resize((target_w, new_h))
            y1    = (new_h - target_h) // 2
            clip  = clip.crop(y1=y1, y2=y1 + target_h)
        return clip

    # ── Audio / render ─────────────────────────────────────────────────────

    def _render_with_music(
        self,
        clip,
        platform: Platform,
        source: str,
        video_name: str = "",
        forced_music: Optional[Path] = None,
        output_path: Optional[Path] = None,
    ) -> Path:
        if output_path is None:
            output = self.config.REELS_DIR / f"ig_{source}_{get_timestamp()}.mp4"
        else:
            output = output_path

        clip     = clip.without_audio()
        clip_dur = float(clip.duration)

        if forced_music is not None and forced_music.exists():
            bg_music = self.audio_mgr.create_audio_from_file(
                music_path=forced_music, video_duration=clip_dur, volume=0.25,
            )
        else:
            bg_music = self.audio_mgr.create_audio(
                video_duration=clip_dur, platform=platform, volume=0.25, video_name=video_name,
            )

        if bg_music is not None:
            clip = clip.set_audio(bg_music)
            logger.info(f"Audio attached: {float(bg_music.duration):.1f}s to {clip_dur:.1f}s video")
        else:
            logger.warning("No audio — video will be silent.")

        return self._render_final(clip, output)

    def _verify_output_dimensions(self, path: Path) -> None:
        try:
            result = subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", str(path)],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode == 0 and result.stdout.strip():
                parts = result.stdout.strip().split("x")
                if len(parts) == 2:
                    w, h = int(parts[0]), int(parts[1])
                    if w != self.config.VIDEO_WIDTH or h != self.config.VIDEO_HEIGHT:
                        logger.error(f"Dimension mismatch: {path.name} is {w}x{h}, "
                                     f"expected {self.config.VIDEO_WIDTH}x{self.config.VIDEO_HEIGHT}")
                    else:
                        logger.debug(f"Dimensions verified: {w}x{h} OK")
        except Exception as e:
            logger.warning(f"ffprobe check failed: {e}")

    def _render_final(self, clip, output: Path) -> Path:
        asset_type = self.config.logo_intro_asset_type()
        apply_logo = getattr(self, "_apply_logo", True)

        if asset_type == "image" and apply_logo:
            clip = self.logo_intro.prepend(clip)

        temp_output = output.with_name(f"_tmp_render_{get_timestamp()}.mp4")
        _audio_ref  = getattr(clip, "audio", None)

        try:
            logger.info("Rendering with MoviePy...")
            clip.write_videofile(
                str(temp_output),
                fps=self.config.VIDEO_FPS,
                codec="libx264",
                audio_codec=self.AUDIO_CODEC,
                audio_bitrate=self.AUDIO_BITRATE,
                preset="ultrafast",
                ffmpeg_params=[
                    "-crf", "20", "-pix_fmt", "yuv420p",
                    "-movflags", "+faststart",
                    "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
                ],
                verbose=False, logger=None,
            )

            if self._gpu == "AMD":
                try:
                    cmd = [
                        "ffmpeg", "-y", "-i", str(temp_output),
                        "-c:v", "h264_amf", "-quality", "quality", "-usage", "transcoding",
                        "-rc", "vbr_peak", "-b:v", "16M", "-maxrate", "20M", "-bufsize", "32M",
                        "-vf", f"scale={self.config.VIDEO_WIDTH}:{self.config.VIDEO_HEIGHT},setsar=1",
                        "-c:a", "copy", "-pix_fmt", "yuv420p",
                        "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
                        "-movflags", "+faststart", str(output),
                    ]
                    subprocess.run(cmd, check=True, capture_output=True, text=True)
                    self._verify_output_dimensions(output)
                    if asset_type == "video" and apply_logo:
                        output = self.logo_intro.prepend_to_file(output)
                    logger.info(f"Reel created (AMD GPU): {output.name}")
                    return output
                except Exception as e:
                    logger.warning(f"h264_amf failed — using CPU: {e}")

            scale_cmd = [
                "ffmpeg", "-y", "-i", str(temp_output),
                "-vf", f"scale={self.config.VIDEO_WIDTH}:{self.config.VIDEO_HEIGHT},setsar=1,format=yuv420p",
                "-c:v", "libx264", "-preset", "fast", "-crf", "18",
                "-c:a", "copy", "-movflags", "+faststart", str(output),
            ]
            scale_result = subprocess.run(scale_cmd, capture_output=True, text=True, timeout=300)
            if scale_result.returncode != 0:
                logger.warning(f"ffmpeg scale failed — direct copy:\n  {scale_result.stderr[-400:]}")
                shutil.move(str(temp_output), str(output))
            else:
                self._verify_output_dimensions(output)

            if asset_type == "video" and apply_logo:
                output = self.logo_intro.prepend_to_file(output)

            logger.info(f"Reel created (CPU): {output.name}")
            return output

        finally:
            if temp_output.exists():
                try:
                    temp_output.unlink()
                except Exception:
                    pass
            self._safe_close_clip(clip)
            _tmp_wav = getattr(_audio_ref, "_dshorts_tmp_path", None)
            if _tmp_wav and Path(_tmp_wav).exists():
                try:
                    Path(_tmp_wav).unlink()
                except Exception:
                    pass
            _audio_ref = None
