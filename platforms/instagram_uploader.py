"""
platforms/instagram_uploader.py
Instagram uploader — Stories + Reels.
"""

import time
import random
import logging
from pathlib import Path
from typing import Dict, Optional

from instagrapi import Client
from instagrapi.exceptions import (
    LoginRequired, ChallengeRequired, PleaseWaitFewMinutes,
    ClientLoginRequired, ClientUnauthorizedError,
)

try:
    from instagrapi.exceptions import ChallengeUnknownStep
except ImportError:
    ChallengeUnknownStep = ChallengeRequired

try:
    from instagrapi.exceptions import ClipNotUpload, PhotoNotUpload, VideoNotUpload
    _UPLOAD_EXC = (ClipNotUpload, PhotoNotUpload, VideoNotUpload)
except ImportError:
    _UPLOAD_EXC = ()

_SESSION_EXPIRED_TYPES = (LoginRequired, ClientLoginRequired, ClientUnauthorizedError)

_CHALLENGE_MSG = (
    "Instagram is blocking automated login with a security challenge.\n"
    "Steps to fix:\n"
    "  1. Open Instagram on your phone or browser and log in manually\n"
    "  2. Approve any security prompt (email code, SMS code, or 'Was this you?')\n"
    "  3. Wait 5-10 minutes, then run again.\n"
    "  If it keeps happening, log in from the same IP/device manually first."
)


def _is_login_error(exc: Exception) -> bool:
    if _UPLOAD_EXC and isinstance(exc, _UPLOAD_EXC):
        return "login" in str(exc).lower()
    return isinstance(exc, _SESSION_EXPIRED_TYPES)


logger = logging.getLogger(__name__)


_DEVICE_SETTINGS = {
    "app_version": "269.0.0.18.75",
    "android_version": 26,
    "android_release": "8.0.0",
    "dpi": "480dpi",
    "resolution": "1080x1920",
    "manufacturer": "OnePlus",
    "device": "devitron",
    "model": "6T Dev",
    "cpu": "qcom",
    "version_code": "314665256",
}


class InstagramUploader:
    def __init__(self, config):
        self.config = config
        self.client = self._make_client()

        self.session_file = self.config.SESSIONS_DIR / "instagram.json"
        self.session_file.parent.mkdir(parents=True, exist_ok=True)

        self._login()

    def _make_client(self) -> Client:
        cl = Client()
        cl.delay_range = [3, 6]
        cl.set_device(_DEVICE_SETTINGS)
        cl.set_user_agent()
        proxy = getattr(self.config, "INSTAGRAM_PROXY", "") or ""
        if proxy:
            cl.set_proxy(proxy)
            logger.info(f"Instagram proxy set: {proxy.split('@')[-1]}")
        return cl

    # ── Login / Session ────────────────────────────────────────────────────

    def _login(self) -> None:
        username = self.config.INSTAGRAM_USERNAME
        password = self.config.INSTAGRAM_PASSWORD

        if not username or not password:
            raise ValueError("Instagram username/password missing in .env")

        if self.session_file.exists():
            try:
                self.client.load_settings(str(self.session_file))
                self.client.get_timeline_feed()
                logger.info("Instagram session loaded")
                return
            except (ChallengeRequired, ChallengeUnknownStep) as e:
                logger.warning(f"Session blocked by challenge: {e}")
                self.session_file.unlink(missing_ok=True)
                raise RuntimeError(_CHALLENGE_MSG) from e
            except Exception as e:
                logger.warning(f"Session invalid: {e} — fresh login")
                self.session_file.unlink(missing_ok=True)
                self.client = self._make_client()

        time.sleep(random.uniform(3, 7))

        try:
            self.client.login(username, password)
            self.client.dump_settings(str(self.session_file))
            logger.info("New Instagram session saved")
        except (ChallengeRequired, ChallengeUnknownStep) as e:
            raise RuntimeError(_CHALLENGE_MSG) from e
        except PleaseWaitFewMinutes as e:
            raise RuntimeError(
                "Instagram rate limiting this account. Wait 15-30 min and try again."
            ) from e
        except Exception as e:
            raise RuntimeError(f"Instagram login failed: {e}") from e

    def _relogin_once(self) -> None:
        logger.info("Re-login Instagram...")
        self.session_file.unlink(missing_ok=True)
        self.client = self._make_client()
        time.sleep(random.uniform(5, 10))
        self._login()

    def force_relogin(self) -> bool:
        logger.info("Force re-login Instagram...")
        self.session_file.unlink(missing_ok=True)
        for old in self.config.SESSIONS_DIR.glob("*.json"):
            try:
                old.unlink()
                logger.info(f"Session removed: {old.name}")
            except Exception:
                pass
        try:
            self._login()
            return True
        except Exception as e:
            logger.error(f"Force re-login failed: {e}")
            return False

    def session_status(self) -> str:
        if not self.session_file.exists():
            return "session file not found"
        try:
            self.client.get_timeline_feed()
            return "session is valid"
        except Exception as e:
            return f"session invalid: {e}"

    def close(self) -> None:
        try:
            self.client.dump_settings(str(self.session_file))
        except Exception:
            pass

    # ── Story ─────────────────────────────────────────────────────────────

    def upload_story(self, media_path: Path) -> Dict:
        """
        Upload photo (.jpg/.png) or video (.mp4) to Instagram Story.
        File movement is the caller's responsibility.
        """
        media_path = Path(media_path)
        if not media_path.is_file():
            return {"success": False, "error": f"File not found: {media_path}"}

        is_video = media_path.suffix.lower() == ".mp4"

        def _do():
            if is_video:
                return self.client.video_upload_to_story(str(media_path))
            return self.client.photo_upload_to_story(str(media_path))

        try:
            media = _do()
            logger.info(f"Story uploaded: {media.pk}")
            time.sleep(2)
            return {"success": True, "id": str(media.pk)}
        except Exception as e:
            if not _is_login_error(e):
                logger.error(f"Story upload failed: {e}", exc_info=True)
                return {"success": False, "error": str(e)}
            try:
                self._relogin_once()
                media = _do()
                logger.info(f"Story uploaded after re-login: {media.pk}")
                time.sleep(2)
                return {"success": True, "id": str(media.pk)}
            except Exception as re_e:
                logger.error(f"Story upload failed after re-login: {re_e}")
                return {"success": False, "error": str(re_e)}

    # ── Reel ──────────────────────────────────────────────────────────────

    def upload_reel(
        self,
        video_path: Path,
        caption: str = "",
        cover_path: Optional[Path] = None,
    ) -> Dict:
        """
        Upload a 9:16 MP4 as an Instagram Reel.
        File movement is the caller's responsibility.
        """
        video_path = Path(video_path)
        if not video_path.is_file():
            return {"success": False, "error": f"File not found: {video_path}"}

        def _do():
            kwargs = dict(path=str(video_path), caption=caption)
            if cover_path and Path(cover_path).is_file():
                kwargs["thumbnail"] = str(cover_path)
            return self.client.clip_upload(**kwargs)

        try:
            media = _do()
            logger.info(f"Reel uploaded: {media.pk}")
            time.sleep(3)
            return {"success": True, "id": str(media.pk)}
        except Exception as e:
            if not _is_login_error(e):
                logger.error(f"Reel upload failed: {e}", exc_info=True)
                return {"success": False, "error": str(e)}
            try:
                self._relogin_once()
                media = _do()
                logger.info(f"Reel uploaded after re-login: {media.pk}")
                time.sleep(3)
                return {"success": True, "id": str(media.pk)}
            except Exception as re_e:
                logger.error(f"Reel upload failed after re-login: {re_e}")
                return {"success": False, "error": str(re_e)}
