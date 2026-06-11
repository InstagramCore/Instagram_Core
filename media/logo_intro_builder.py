"""
media/logo_intro_builder.py — Logo Animation Intro Builder
===========================================================

FIX: Permission denied on Windows
----------------------------------
Windows locks files opened in Explorer / Media Player.
MoviePy's VideoFileClip calls ffmpeg directly on the path — if Windows has
the file handle locked, ffmpeg gets "Permission denied".

Solution: use ffmpeg concat demuxer to prepend logo at file level.
MoviePy never opens logo_intro.mp4.

FIX: -c:v copy + -af apad incompatibility
------------------------------------------
When -c:v copy is used, ffmpeg stream-copies the video and CANNOT apply
audio filters (-af) at the same time — this causes either a silent output
or an ffmpeg error depending on version.

Fix: use -c:v libx264 (fast re-encode with ultrafast preset) for the
concat output so audio filters work correctly. The quality loss is
negligible since the source is already h264.

FIX: landscape logo shrinks and adds black bars (scale+pad → -filter_complex)
------------------------------------------------------------------------------
The old approach used a single -vf scale+pad applied to the concat demuxer
output.  Because ffmpeg uses the FIRST clip's dimensions for the output,
the landscape logo (1920×1080) was letterboxed into a 1080×1920 frame,
producing black bars.

Fix: switch to two separate -i inputs + -filter_complex so each input is
scaled independently before the concat filter joins them:

  [0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920[v0]
  → logo: scale-up to fill 1080×1920, crop to exact size (no black bars)

  [1:v]scale=1080:1920[v1]
  → main video: already 1080×1920, scale is a no-op

  [v0][v1]concat=n=2:v=1:a=0[vout]
  → join into a single video stream

Audio is mapped from input 1 (main video) with aresample+apad to cover
the full output duration, including silence during the logo segment.
"""

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image

from moviepy.editor import ImageClip, concatenate_videoclips
from moviepy.video.fx.all import fadein, fadeout

logger = logging.getLogger(__name__)


class LogoIntroBuilder:
    """
    Prepends a logo intro to rendered videos.

    Two modes
    ---------
    1. ffmpeg-level merge (MP4 asset): logo + main video concatenated
       purely via ffmpeg subprocess — MoviePy never opens logo_intro.mp4.
    2. MoviePy ImageClip (PNG/JPG asset): generates fade-in/out clip
       from image and prepends via ffmpeg concat (written to temp MP4 first).
    """

    def __init__(self, config) -> None:
        self.config = config

    # ─────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────

    def prepend_to_file(self, rendered_mp4: Path) -> Path:
        """
        Prepend logo intro to an already-rendered MP4 file using ffmpeg.
        Never opens logo_intro.mp4 with MoviePy — bypasses Windows locks.
        """
        if not getattr(self.config, "LOGO_INTRO_ENABLED", True):
            logger.debug("Logo intro disabled — skipping.")
            return rendered_mp4

        asset_type = self.config.logo_intro_asset_type()

        if asset_type == "video":
            result = self._ffmpeg_concat(rendered_mp4)
            if result is not None:
                return result
            logger.info("ffmpeg concat failed — trying PNG image fallback.")
            if (getattr(self.config, "LOGO_INTRO_IMAGE", None)
                    and self.config.LOGO_INTRO_IMAGE.is_file()):
                return self._image_prepend_to_file(rendered_mp4)
            return rendered_mp4

        elif asset_type == "image":
            return self._image_prepend_to_file(rendered_mp4)

        else:
            logger.debug("Logo intro: no asset — skipping.")
            return rendered_mp4

    def prepend(self, main_clip):
        """
        Legacy MoviePy-level prepend.
        Used only when asset_type == 'image' (PNG/JPG).
        For MP4 assets use prepend_to_file() from VideoCreator._render_final.
        """
        if not getattr(self.config, "LOGO_INTRO_ENABLED", True):
            return main_clip

        asset_type = self.config.logo_intro_asset_type()

        if asset_type == "image":
            intro = self._build_from_image()
            if intro is None:
                return main_clip
            return self._concat_clips(intro, main_clip)

        return main_clip

    # ─────────────────────────────────────────────────────────────────────
    # ffmpeg-level concat (MP4 asset)
    # ─────────────────────────────────────────────────────────────────────

    def _ffmpeg_concat(self, main_mp4: Path) -> Optional[Path]:
        """
        Concat logo_intro.mp4 + main_mp4 using ffmpeg filter_complex.

        Uses two separate -i inputs so each stream is scaled independently
        before the concat filter joins them.  This prevents the landscape
        logo from forcing the output to 1920×1080.

        Video filter_complex:
          [0:v] logo  → scale-up + crop to w×h (no black bars)
          [1:v] main  → scale to w×h (no-op if already correct)
          concat → [vout]

        Audio: mapped from input 1 (main video) with aresample+apad so
        the audio track covers the full output duration.
        """
        logo_path = self.config.LOGO_INTRO_VIDEO
        suffix = main_mp4.suffix
        w = getattr(self.config, "VIDEO_WIDTH", 1080)
        h = getattr(self.config, "VIDEO_HEIGHT", 1920)

        tmp_out = main_mp4.with_name(f"_logo_concat_{main_mp4.stem}{suffix}")

        import os as _os
        _threads = max(1, min((_os.cpu_count() or 1) - 1, 8))

        _filter_complex = (
            f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h}[v0];"
            f"[1:v]scale={w}:{h}[v1];"
            f"[v0][v1]concat=n=2:v=1:a=0[vout]"
        )

        try:
            cmd = [
                "ffmpeg", "-y",
                "-i", str(logo_path),
                "-i", str(main_mp4),
                "-filter_complex", _filter_complex,
                "-map", "[vout]",
                "-map", "1:a?",
                # Re-encode video so audio filters and pts reset work correctly
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-crf", "20",
                "-pix_fmt", "yuv420p",
                "-colorspace", "bt709",
                "-color_primaries", "bt709",
                "-color_trc", "bt709",
                "-vsync", "2",
                # Re-encode audio + async resample + pad silence to full duration
                "-c:a", "aac",
                "-b:a", "192k",
                "-af", "aresample=async=1,apad",
                "-shortest",
                "-movflags", "+faststart",
                "-threads", str(_threads),
                str(tmp_out),
            ]

            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=180,
            )

            if result.returncode != 0:
                err = (result.stderr or "").strip()
                logger.warning(
                    f"ffmpeg logo concat failed (code {result.returncode}):\n"
                    f"  {err[-500:]}"
                )
                return None

            shutil.move(str(tmp_out), str(main_mp4))
            logger.info(f"Logo intro (MP4 ffmpeg concat) prepended → {main_mp4.name}")
            return main_mp4

        except subprocess.TimeoutExpired:
            logger.warning("ffmpeg logo concat timed out")
            return None
        except Exception as e:
            logger.warning(f"ffmpeg logo concat exception: {e}")
            return None
        finally:
            _safe_unlink(tmp_out)

    # ─────────────────────────────────────────────────────────────────────
    # Image-based intro (PNG/JPG → short video clip)
    # ─────────────────────────────────────────────────────────────────────

    def _image_prepend_to_file(self, main_mp4: Path) -> Path:
        """
        Build a PNG-based intro clip, write it to temp MP4,
        then concat with main video via ffmpeg filter_complex.

        Uses two separate -i inputs + -filter_complex (same approach as
        _ffmpeg_concat) so each stream is scaled independently — no black bars.
        """
        intro_clip = self._build_from_image()
        if intro_clip is None:
            return main_mp4

        tmp_intro = main_mp4.with_name(f"_logo_img_{main_mp4.stem}.mp4")
        tmp_out: Optional[Path] = None

        w = getattr(self.config, "VIDEO_WIDTH", 1080)
        h = getattr(self.config, "VIDEO_HEIGHT", 1920)

        try:
            intro_clip.write_videofile(
                str(tmp_intro),
                fps=getattr(self.config, "VIDEO_FPS", 30),
                codec="libx264",
                audio=False,
                preset="ultrafast",
                ffmpeg_params=["-pix_fmt", "yuv420p"],
                verbose=False,
                logger=None,
            )

            suffix = main_mp4.suffix
            tmp_out = main_mp4.with_name(f"_logo_img_concat_{main_mp4.stem}{suffix}")

            _filter_complex = (
                f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
                f"crop={w}:{h}[v0];"
                f"[1:v]scale={w}:{h}[v1];"
                f"[v0][v1]concat=n=2:v=1:a=0[vout]"
            )

            cmd = [
                "ffmpeg", "-y",
                "-i", str(tmp_intro),
                "-i", str(main_mp4),
                "-filter_complex", _filter_complex,
                "-map", "[vout]",
                "-map", "1:a?",
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-crf", "20",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac",
                "-b:a", "192k",
                "-af", "aresample=async=1,apad",
                "-shortest",
                "-movflags", "+faststart",
                str(tmp_out),
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)

            if result.returncode != 0:
                logger.warning(f"Image intro concat failed: {result.stderr[-300:]}")
                return main_mp4

            shutil.move(str(tmp_out), str(main_mp4))
            logger.info(f"Logo intro (image) prepended → {main_mp4.name}")
            return main_mp4

        except Exception as e:
            logger.warning(f"Image intro prepend failed: {e}")
            return main_mp4
        finally:
            _safe_unlink(tmp_intro)
            _safe_unlink(tmp_out)

    def _build_from_image(self) -> Optional[object]:
        """Generate a MoviePy ImageClip from the logo PNG."""
        path = self.config.LOGO_INTRO_IMAGE
        duration = float(getattr(self.config, "LOGO_INTRO_DURATION", 3.0))
        fade = float(getattr(self.config, "LOGO_INTRO_FADE", 0.4))
        target_fps = getattr(self.config, "VIDEO_FPS", 30)
        w = self.config.VIDEO_WIDTH
        h = self.config.VIDEO_HEIGHT

        try:
            with Image.open(path) as source_img:
                pil_img = source_img.convert("RGBA")
                max_logo_w = int(w * 0.60)
                max_logo_h = int(h * 0.60)
                pil_img.thumbnail((max_logo_w, max_logo_h), Image.Resampling.LANCZOS)

                bg = Image.new("RGBA", (w, h), (0, 0, 0, 255))
                logo_w, logo_h = pil_img.size
                bg.paste(pil_img, ((w - logo_w) // 2, (h - logo_h) // 2), mask=pil_img.split()[3])
                frame = np.array(bg.convert("RGB"))

            clip = (
                ImageClip(frame)
                .set_duration(duration)
                .set_fps(target_fps)
            )
            clip = clip.fx(fadein, min(fade, duration / 4))
            clip = clip.fx(fadeout, min(fade, duration / 4))
            logger.info(f"Logo intro image clip built: {duration:.1f}s")
            return clip

        except Exception as e:
            logger.warning(f"Logo intro image build failed: {e}")
            return None

    def _concat_clips(self, intro, main_clip):
        """MoviePy-level concat (image intro only)."""
        try:
            target_fps = getattr(self.config, "VIDEO_FPS", 30)
            w = self.config.VIDEO_WIDTH
            h = self.config.VIDEO_HEIGHT

            intro = intro.resize((w, h)).set_fps(target_fps)
            main_clip = main_clip.resize((w, h))
            if not hasattr(main_clip, "fps") or main_clip.fps is None:
                main_clip = main_clip.set_fps(target_fps)

            result = concatenate_videoclips([intro, main_clip], method="compose")
            logger.info(f"Logo intro (image clip) prepended: {result.duration:.1f}s total")
            return result
        except Exception as e:
            logger.warning(f"Logo intro clip concat failed: {e}")
            _safe_close(intro)
            return main_clip


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _safe_close(clip) -> None:
    try:
        if clip is not None:
            clip.close()
    except Exception:
        pass


def _safe_unlink(path: Optional[Path]) -> None:
    try:
        if path and Path(path).exists():
            Path(path).unlink()
    except Exception:
        pass
