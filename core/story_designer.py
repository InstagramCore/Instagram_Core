"""
core/story_designer.py
Instagram Story graphic designer with Persian text support.
"""

import textwrap
import logging
from pathlib import Path
from typing import Dict, List, Optional

from PIL import Image, ImageDraw, ImageFont
from arabic_reshaper import reshape
from bidi.algorithm import get_display

from config import Config
from utils.helpers import get_timestamp

logger = logging.getLogger(__name__)

_SYSTEM_PERSIAN_FONTS = [
    "C:/Windows/Fonts/tahoma.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/trebuc.ttf",
    "/usr/share/fonts/truetype/noto/NotoNaskhArabic-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
]

TEST_PERSIAN_CHAR = "ا"


class StoryDesigner:
    """Story designer with Safe Area compliance and proper Persian rendering."""

    SAFE_MARGIN_LEFT   = 90
    SAFE_MARGIN_RIGHT  = 90
    SAFE_MARGIN_BOTTOM = 120
    SAFE_MARGIN_TOP    = 60

    BOX_PADDING = 24
    BOX_OPACITY = 170
    BOX_RADIUS  = 24

    BASE_FONT_SIZE = 38
    MIN_FONT_SIZE  = 24
    LINE_SPACING   = 1.5
    SECTION_GAP    = 30
    PERSIAN_MIN_HEIGHT = 320

    def __init__(self, config: Optional[Config] = None):
        self.config = config or Config()
        self._persian_font_cache: Dict[int, ImageFont.ImageFont] = {}

    # ═══════════════════════════════════════════════════════════════════
    # Public API
    # ═══════════════════════════════════════════════════════════════════

    def design(self, image: Image.Image, content: Dict[str, str]) -> Path:
        """
        Apply graphic design to the image and save as PNG.

        Args:
            image:   Raw image from DALL-E (PIL Image).
            content: {"english": "...", "persian": "...", "topic": "..."}

        Returns:
            Path to saved PNG.
        """
        logger.info("Designing story graphic...")

        img = image.resize(
            (self.config.VIDEO_WIDTH, self.config.VIDEO_HEIGHT),
            Image.Resampling.LANCZOS,
        ).convert("RGBA")

        w, h = img.size
        safe_bottom = h - self.SAFE_MARGIN_BOTTOM

        img  = self._add_dark_overlay(img, w, h)
        draw = ImageDraw.Draw(img)

        font_title, _ = self._load_english_fonts()

        safe_left  = self.SAFE_MARGIN_LEFT
        safe_right = w - self.SAFE_MARGIN_RIGHT
        safe_width = safe_right - safe_left
        center_x   = w // 2

        # Title
        title_y = int(h * 0.55)
        draw.text(
            (center_x, title_y), "VIENNA DAILY",
            fill=self.config.GOLD_COLOR, font=font_title, anchor="mm",
            stroke_width=2, stroke_fill=(0, 0, 0),
        )
        title_bb = draw.textbbox((center_x, title_y), "VIENNA DAILY", font=font_title, anchor="mm")
        y = title_bb[3] + 18

        # Separator
        draw.line([(150, y), (w - 150, y)], fill=self.config.GOLD_COLOR, width=2)
        y += 28

        # English body
        english_text  = content.get("english", "")
        max_en_height = safe_bottom - y - self.SECTION_GAP - self.PERSIAN_MIN_HEIGHT
        max_en_height = max(60, max_en_height)
        font_body, en_lines = self._auto_english_font(english_text, safe_width, max_en_height)

        # Measure English block
        sim_y, en_block_top, en_block_bottom = y, None, None
        for line in en_lines:
            bb = draw.textbbox((center_x, sim_y), line, font=font_body, anchor="mm")
            if en_block_top is None:
                en_block_top = bb[1]
            en_block_bottom = bb[3]
            sim_y = bb[3] + max(6, int((bb[3] - bb[1]) * 0.5))

        # Draw box behind English
        if en_lines and en_block_top is not None:
            en_overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            ImageDraw.Draw(en_overlay).rounded_rectangle(
                [(safe_left - self.BOX_PADDING, en_block_top - self.BOX_PADDING),
                 (safe_right + self.BOX_PADDING, en_block_bottom + self.BOX_PADDING)],
                radius=self.BOX_RADIUS, fill=(0, 0, 0, self.BOX_OPACITY),
            )
            img.paste(en_overlay, (0, 0), en_overlay)
            draw = ImageDraw.Draw(img)

        # Draw English text
        english_bottom_y = y
        for line in en_lines:
            line_bb = draw.textbbox((center_x, y), line, font=font_body, anchor="mm")
            draw.text((center_x, y), line, fill=self.config.WHITE_COLOR, font=font_body, anchor="mm")
            line_h = line_bb[3] - line_bb[1]
            english_bottom_y = line_bb[3]
            y = line_bb[3] + max(6, int(line_h * 0.5))

        # Persian text
        persian_y_start = max(english_bottom_y + self.SECTION_GAP, int(h * 0.65))
        persian_text    = content.get("persian", "")
        self._draw_persian_with_box(
            draw=draw, text=persian_text, y_start=persian_y_start,
            center_x=center_x, safe_left=safe_left, safe_right=safe_right,
            safe_bottom=safe_bottom, img=img, w=w, h=h,
        )

        # Instagram handle
        try:
            id_font = ImageFont.truetype(str(self.config.FONT_PATH), 30)
        except Exception:
            id_font = self._safe_default_font()
        draw.text(
            (center_x, h - 40),
            getattr(self.config, "INSTAGRAM_HANDLE", "@vienna_streetvibes"),
            fill=(180, 160, 0), font=id_font, anchor="mm",
        )

        output = self.config.STORIES_DIR / f"story_{get_timestamp()}.png"
        img.convert("RGB").save(str(output), "PNG", optimize=True)
        logger.info(f"Story saved: {output}")
        return output

    # ═══════════════════════════════════════════════════════════════════
    # Font loaders
    # ═══════════════════════════════════════════════════════════════════

    @staticmethod
    def _safe_default_font() -> ImageFont.ImageFont:
        try:
            return ImageFont.load_default(size=20)
        except TypeError:
            return ImageFont.load_default()

    @staticmethod
    def _font_size(font: ImageFont.ImageFont) -> int:
        return getattr(font, "size", 20)

    def _load_english_fonts(self):
        try:
            title = ImageFont.truetype(str(self.config.FONT_PATH), self.config.TITLE_FONT_SIZE)
            body  = ImageFont.truetype(str(self.config.FONT_PATH), self.config.BODY_FONT_SIZE)
            return title, body
        except Exception:
            logger.warning("English font not found — using default")
            default = self._safe_default_font()
            return default, default

    def _load_persian_font(self, size: int) -> ImageFont.ImageFont:
        if size in self._persian_font_cache:
            return self._persian_font_cache[size]

        candidates = []

        persian_cfg = getattr(self.config, "PERSIAN_FONT_PATH", None)
        if persian_cfg and Path(persian_cfg).is_file():
            candidates.append(str(persian_cfg))

        if Path(self.config.FONT_PATH).is_file():
            candidates.append(str(self.config.FONT_PATH))

        candidates.extend(_SYSTEM_PERSIAN_FONTS)

        fonts_dir = getattr(self.config, "FONTS_DIR", None)
        if fonts_dir and Path(fonts_dir).is_dir():
            for ttf in sorted(Path(fonts_dir).glob("*.ttf")):
                if ttf.is_file():
                    candidates.append(str(ttf))
            for ttf in sorted(Path(fonts_dir).glob("*.TTF")):
                if ttf.is_file():
                    candidates.append(str(ttf))

        for path in candidates:
            try:
                font = ImageFont.truetype(path, size)
                # getbbox() is the modern API (Pillow 8+); getmask() removed in Pillow 10
                bbox = font.getbbox(TEST_PERSIAN_CHAR)
                if bbox and (bbox[2] - bbox[0]) > 0:
                    logger.debug(f"Persian font: {Path(path).name} @ {size}px")
                    self._persian_font_cache[size] = font
                    return font
            except Exception:
                continue

        logger.warning(
            f"No Persian-capable font found! Put 'Vazirmatn-Bold.ttf' in {self.config.FONTS_DIR}"
        )
        fallback = self._safe_default_font()
        self._persian_font_cache[size] = fallback
        return fallback

    # ═══════════════════════════════════════════════════════════════════
    # Drawing helpers
    # ═══════════════════════════════════════════════════════════════════

    def _add_dark_overlay(self, img: Image.Image, w: int, h: int) -> Image.Image:
        overlay      = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        start_y      = int(h * 0.40)
        steps        = h - start_y

        for i in range(steps):
            alpha = int(self.config.OVERLAY_OPACITY * (i / steps))
            overlay_draw.line([(0, start_y + i), (w, start_y + i)], fill=(0, 0, 0, alpha))

        overlay_draw.rectangle(
            [0, int(h * 0.55), w, h],
            fill=(0, 0, 0, self.config.OVERLAY_OPACITY),
        )
        return Image.alpha_composite(img, overlay)

    def _calc_max_chars(self, safe_width: int, font: ImageFont.ImageFont) -> int:
        avg_char_width = self._font_size(font) * 0.55
        return max(10, int(safe_width / avg_char_width))

    def _wrap_text(self, text: str, font: ImageFont.ImageFont, max_width: int) -> List[str]:
        if not text:
            return []
        words, lines, current_line = text.split(), [], ""

        for word in words:
            test_line = f"{current_line} {word}".strip()
            try:
                bbox = font.getbbox(test_line)
                line_width = bbox[2] - bbox[0]
            except Exception:
                line_width = len(test_line) * self._font_size(font) * 0.55

            if line_width <= max_width:
                current_line = test_line
            else:
                if current_line:
                    lines.append(current_line)
                current_line = word

        if current_line:
            lines.append(current_line)
        return lines if lines else [text]

    def _auto_english_font(self, text: str, safe_width: int, max_height: int) -> tuple:
        if not text:
            return self._safe_default_font(), []

        for font_size in range(self.config.BODY_FONT_SIZE, self.MIN_FONT_SIZE - 1, -4):
            try:
                font = ImageFont.truetype(str(self.config.FONT_PATH), font_size)
            except Exception:
                font = self._safe_default_font()
            max_chars = self._calc_max_chars(safe_width, font)
            lines     = textwrap.wrap(text, width=max_chars)
            line_h    = int(self._font_size(font) * self.LINE_SPACING)
            if len(lines) * line_h <= max_height:
                return font, lines

        try:
            font = ImageFont.truetype(str(self.config.FONT_PATH), self.MIN_FONT_SIZE)
        except Exception:
            font = self._safe_default_font()
        max_chars = self._calc_max_chars(safe_width, font)
        return font, textwrap.wrap(text, width=max_chars)[:6]

    def _auto_persian_font_size(self, text: str, max_width: int, max_height: int, base_size: int) -> ImageFont.ImageFont:
        font_size = base_size
        while font_size >= self.MIN_FONT_SIZE:
            font         = self._load_persian_font(font_size)
            lines        = self._wrap_text(text, font, max_width)
            line_height  = int(font_size * self.LINE_SPACING)
            total_height = len(lines) * line_height
            if total_height <= max_height:
                return font
            font_size -= 4
        return self._load_persian_font(self.MIN_FONT_SIZE)

    def _fix_persian(self, text: str) -> str:
        try:
            return get_display(reshape(text))
        except Exception as e:
            logger.warning(f"RTL processing error: {e}")
            return text

    def _draw_persian_with_box(
        self, draw, text, y_start, center_x,
        safe_left, safe_right, safe_bottom, img, w, h,
    ) -> float:
        if not text:
            return y_start

        safe_width      = safe_right - safe_left
        max_text_height = min(int(safe_bottom - y_start - self.SAFE_MARGIN_TOP), int(h * 0.24))

        font  = self._auto_persian_font_size(text, safe_width, max_text_height, self.BASE_FONT_SIZE)
        lines = self._wrap_text(text, font, safe_width)

        line_height       = int(self._font_size(font) * self.LINE_SPACING)
        text_block_height = len(lines) * line_height

        box_x1 = safe_left  - self.BOX_PADDING
        box_y1 = y_start    - self.BOX_PADDING
        box_x2 = safe_right + self.BOX_PADDING
        box_y2 = min(y_start + text_block_height + self.BOX_PADDING, safe_bottom)

        overlay      = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        overlay_draw.rounded_rectangle(
            [(box_x1, box_y1), (box_x2, box_y2)],
            radius=self.BOX_RADIUS, fill=(0, 0, 0, self.BOX_OPACITY),
        )
        img.paste(overlay, (0, 0), overlay)

        y = y_start
        for line in lines:
            fixed = self._fix_persian(line)
            draw.text((center_x, y), fixed, fill=(255, 255, 255), font=font, anchor="ma")
            y += line_height
            if y + line_height > safe_bottom:
                logger.warning(f"Persian text truncated (not all {len(lines)} lines fit)")
                break

        return y + self.BOX_PADDING
