"""
config.py — Central configuration for Instagram_Core
"""

import os
import shutil
from pathlib import Path
from dataclasses import dataclass, field
from typing import Tuple, List

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


@dataclass
class Config:
    """Central configuration for Instagram_Core."""

    BASE_DIR: Path = BASE_DIR
    ENV_FILE: Path = BASE_DIR / ".env"

    # ==============================
    # API KEYS
    # ==============================
    OPENAI_API_KEY:     str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    GEMINI_API_KEY:     str = field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))
    INSTAGRAM_USERNAME: str = field(default_factory=lambda: os.getenv("INSTAGRAM_USERNAME", ""))
    INSTAGRAM_PASSWORD: str = field(default_factory=lambda: os.getenv("INSTAGRAM_PASSWORD", ""))
    INSTAGRAM_EMAIL:    str = field(default_factory=lambda: os.getenv("INSTAGRAM_EMAIL", ""))
    INSTAGRAM_HANDLE:   str = field(default_factory=lambda: os.getenv("INSTAGRAM_HANDLE", "@vienna_streetvibes"))
    INSTAGRAM_PROXY:    str = field(default_factory=lambda: os.getenv("INSTAGRAM_PROXY", ""))

    # ==============================
    # ASSETS
    # ==============================
    ASSETS_DIR:          Path = field(default_factory=lambda: BASE_DIR / "assets")
    RAW_VIDEOS_DIR:      Path = field(default_factory=lambda: BASE_DIR / "assets" / "videos" / "raw")
    RAW_VIDEOS_USED_DIR: Path = field(default_factory=lambda: BASE_DIR / "assets" / "videos" / "raw" / "used")

    MUSIC_BASE_DIR:      Path = field(default_factory=lambda: BASE_DIR / "assets" / "music")
    INSTAGRAM_MUSIC_DIR: Path = field(default_factory=lambda: BASE_DIR / "assets" / "music" / "instagram")

    FONTS_DIR:         Path = field(default_factory=lambda: BASE_DIR / "assets" / "fonts")
    FONT_PATH:         Path = field(default_factory=lambda: BASE_DIR / "assets" / "fonts" / "Montserrat-Bold.ttf")
    PERSIAN_FONT_PATH: Path = field(default_factory=lambda: BASE_DIR / "assets" / "fonts" / "Vazirmatn-Bold.ttf")

    # ==============================
    # LOGO INTRO
    # ==============================
    LOGO_INTRO_ENABLED:  bool  = field(default_factory=lambda: os.getenv("LOGO_INTRO_ENABLED", "0") not in ("0", "false", "no"))
    LOGO_INTRO_VIDEO:    Path  = field(default_factory=lambda: BASE_DIR / "assets" / "logo_intro.mp4")
    LOGO_INTRO_IMAGE:    Path  = field(default_factory=lambda: BASE_DIR / "assets" / "logo.png")
    LOGO_INTRO_DURATION: float = field(default_factory=lambda: float(os.getenv("LOGO_INTRO_DURATION", "3.0")))
    LOGO_INTRO_FADE:     float = field(default_factory=lambda: float(os.getenv("LOGO_INTRO_FADE", "0.4")))

    # ==============================
    # STORAGE
    # ==============================
    STORAGE_DIR:         Path = field(default_factory=lambda: BASE_DIR / "storage")
    STORIES_DIR:         Path = field(default_factory=lambda: BASE_DIR / "storage" / "stories")
    REELS_DIR:           Path = field(default_factory=lambda: BASE_DIR / "storage" / "reels")
    SESSIONS_DIR:        Path = field(default_factory=lambda: BASE_DIR / "storage" / "sessions")
    LOGS_DIR:            Path = field(default_factory=lambda: BASE_DIR / "storage" / "logs")

    UPLOADED_IMAGES_DIR: Path = field(default_factory=lambda: BASE_DIR / "storage" / "uploaded" / "images")
    UPLOADED_REELS_DIR:  Path = field(default_factory=lambda: BASE_DIR / "storage" / "uploaded" / "reels")

    # Alias used by video_creator.py
    @property
    def PENDING_VIDEOS_DIR(self) -> Path:
        return self.REELS_DIR

    # ==============================
    # VIDEO SETTINGS
    # ==============================
    VIDEO_WIDTH:  int = 1080
    VIDEO_HEIGHT: int = 1920
    VIDEO_FPS:    int = 30

    VIDEO_DURATION_MIN: int = 25
    VIDEO_DURATION_MAX: int = 58

    TRANSITION_DURATION: float = 0.5
    ZOOM_SPEED:          float = 0.02

    # ==============================
    # STORY SETTINGS
    # ==============================
    OVERLAY_OPACITY: int = 110
    GOLD_COLOR:  Tuple[int, int, int] = (255, 215, 0)
    WHITE_COLOR: Tuple[int, int, int] = (255, 255, 255)

    TITLE_FONT_SIZE: int = 70
    BODY_FONT_SIZE:  int = 45

    # ==============================
    # GPT / DALL-E
    # ==============================
    GPT_MODEL:        str   = "gpt-4o"
    GPT_TEMPERATURE:  float = 0.8
    GPT_MAX_TOKENS:   int   = 250

    DALL_E_MODEL:   str = "dall-e-3"
    DALL_E_SIZE:    str = "1024x1792"
    DALL_E_QUALITY: str = "standard"

    # ==============================
    # CONTENT TOPICS
    # ==============================
    TOPIC_ROTATION: Tuple[Tuple[str, ...], ...] = (
        ("Vienna History", "Vienna Architecture and Landmarks", "Habsburg Empire and Palace",
         "Vienna Ring Road and Grand Buildings", "Vienna Old Town Secrets"),
        ("Austrian Culture and Traditions", "Vienna Coffee House Culture",
         "Austrian Festivals and Holidays", "Vienna Ball Season and Opera", "Austrian Customs and Daily Life"),
        ("Mozart and Vienna Music History", "Sigmund Freud and Viennese Psychology",
         "Gustav Klimt and Vienna Art", "Famous Austrian Scientists and Inventors", "Austrian Emperors and Royalty"),
        ("Viennese Cuisine and Recipes", "Austrian Wine and Vineyards",
         "Vienna Coffeehouse Pastries", "Austrian Beer and Brewing", "Vienna Street Food and Markets"),
        ("Austrian Alps and Mountains", "Vienna Woods and Nature",
         "Austrian Lakes and Rivers", "Danube River and Vienna", "Austrian Wildlife and Forests"),
        ("Vienna Philharmonic and Classical Music", "Vienna Opera and Theater",
         "Austrian Painters and Sculptures", "Vienna University and Science History", "Austrian Nobel Prize Winners"),
        ("Habsburg Dynasty and Austrian Empire", "World War I and Austria",
         "Austro-Hungarian Empire", "Vienna Congress and Diplomacy", "Austrian Republic History"),
        ("Surprising Vienna Facts", "Vienna Underground and Secrets",
         "Vienna Cemeteries and Famous Graves", "Weird Austrian Laws and Traditions", "Vienna World Records and Firsts"),
    )

    TOPICS: Tuple[str, ...] = (
        "Vienna History", "Vienna Architecture and Landmarks", "Habsburg Empire and Palace",
        "Austrian Culture and Traditions", "Vienna Coffee House Culture",
        "Mozart and Vienna Music History", "Gustav Klimt and Vienna Art",
        "Viennese Cuisine and Recipes", "Austrian Wine and Vineyards",
        "Austrian Alps and Mountains", "Danube River and Vienna",
        "Vienna Philharmonic and Classical Music", "Vienna Opera and Theater",
        "Habsburg Dynasty and Austrian Empire", "World War I and Austria",
        "Surprising Vienna Facts", "Vienna Underground and Secrets",
    )

    # ==============================
    # RETRY SETTINGS
    # ==============================
    MAX_RETRIES: int   = 3
    RETRY_DELAY: float = 2.0

    def __post_init__(self) -> None:
        self.ensure_directories()

    def ensure_directories(self) -> None:
        directories: List[Path] = [
            self.ASSETS_DIR,
            self.RAW_VIDEOS_DIR,
            self.RAW_VIDEOS_USED_DIR,
            self.MUSIC_BASE_DIR,
            self.INSTAGRAM_MUSIC_DIR,
            self.FONTS_DIR,
            self.STORAGE_DIR,
            self.STORIES_DIR,
            self.REELS_DIR,
            self.SESSIONS_DIR,
            self.LOGS_DIR,
            self.UPLOADED_IMAGES_DIR,
            self.UPLOADED_REELS_DIR,
        ]
        for d in directories:
            d.mkdir(parents=True, exist_ok=True)

    # ─────────────────────────────────────────────
    # Logo Intro helper
    # ─────────────────────────────────────────────

    def logo_intro_asset_type(self) -> str:
        if not self.LOGO_INTRO_ENABLED:
            return "none"
        v = self.LOGO_INTRO_VIDEO
        if v.is_file():
            return "video"
        if v.is_dir():
            mp4s = sorted(v.glob("*.mp4"))
            if mp4s:
                object.__setattr__(self, "LOGO_INTRO_VIDEO", mp4s[0])
                return "video"
        if self.LOGO_INTRO_IMAGE.is_file():
            return "image"
        return "none"

    # ─────────────────────────────────────────────
    # File movement helpers
    # ─────────────────────────────────────────────

    def move_to_raw_used(self, raw_video_path: Path) -> Path:
        if not raw_video_path.is_file():
            return self.RAW_VIDEOS_USED_DIR / raw_video_path.name
        destination = self.RAW_VIDEOS_USED_DIR / raw_video_path.name
        if destination.is_file():
            from datetime import datetime
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            destination = self.RAW_VIDEOS_USED_DIR / f"{raw_video_path.stem}_{stamp}{raw_video_path.suffix}"
        shutil.move(str(raw_video_path), str(destination))
        return destination

    def move_story_to_uploaded(self, story_path: Path) -> Path:
        if not story_path.is_file():
            raise FileNotFoundError(f"Story not found: {story_path}")
        dest = self.UPLOADED_IMAGES_DIR / story_path.name
        shutil.move(str(story_path), str(dest))
        return dest

    def move_reel_to_uploaded(self, reel_path: Path) -> Path:
        if not reel_path.is_file():
            raise FileNotFoundError(f"Reel not found: {reel_path}")
        dest = self.UPLOADED_REELS_DIR / reel_path.name
        shutil.move(str(reel_path), str(dest))
        return dest

    def is_ready_for_instagram(self) -> bool:
        return bool(self.INSTAGRAM_USERNAME and self.INSTAGRAM_PASSWORD)

    def __repr__(self) -> str:
        return f"Config(base_dir={self.BASE_DIR.name})"
