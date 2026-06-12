"""Quick Instagram login diagnostic — handles Bloks checkpoint challenge."""
import sys
import time
from pathlib import Path
from instagrapi import Client
from dotenv import load_dotenv
import os

load_dotenv(Path(__file__).parent / ".env")

USERNAME = os.getenv("INSTAGRAM_USERNAME", "")
PASSWORD = os.getenv("INSTAGRAM_PASSWORD", "")
EMAIL    = os.getenv("INSTAGRAM_EMAIL", "")

DEVICE = {
    "app_version":     "269.0.0.18.75",
    "android_version": 26,
    "android_release": "8.0.0",
    "dpi":             "480dpi",
    "resolution":      "1080x1920",
    "manufacturer":    "OnePlus",
    "device":          "devitron",
    "model":           "6T Dev",
    "cpu":             "qcom",
    "version_code":    "314665256",
}

SETTINGS_OUT = "storage/sessions/instagram.json"
TEMP_SETTINGS = "storage/sessions/_challenge_tmp.json"

Path("storage/sessions").mkdir(parents=True, exist_ok=True)


def make_client(load_temp=False) -> Client:
    cl = Client()
    cl.delay_range = [2, 4]
    cl.set_device(DEVICE)
    cl.set_user_agent()
    if load_temp and Path(TEMP_SETTINGS).exists():
        cl.load_settings(TEMP_SETTINGS)
        print(f"[*] Loaded previous device state (UUID: {cl.uuid})")
    else:
        print(f"[*] Device UUID: {cl.uuid}")
    return cl


def try_login(cl: Client, user: str, pwd: str) -> bool:
    try:
        cl.login(user, pwd)
        cl.dump_settings(SETTINGS_OUT)
        # remove temp file if exists
        Path(TEMP_SETTINGS).unlink(missing_ok=True)
        print(f"[+] Login OK! Session saved → {SETTINGS_OUT}")
        return True
    except Exception as e:
        msg = str(e)
        if "challenge" in msg.lower() or "checkpoint" in msg.lower() or "bloks" in msg.lower() or "verify" in msg.lower():
            # Save client state so next attempt uses same UUID
            cl.dump_settings(TEMP_SETTINGS)
            print(f"\n[!] Instagram needs manual verification.")
            print(f"    UUID saved: {cl.uuid}")
            print(f"\n    Steps to fix:")
            print(f"    1. Open Instagram App on your phone")
            print(f"    2. Go to: Settings → Security → Login Activity")
            print(f"    3. Find the recent login attempt → tap 'This Was Me'")
            print(f"    4. Come back here and press Enter to retry")
            input("\n    Press Enter after approving in the app... ")
            return None  # Signal: retry needed
        else:
            print(f"[-] Login failed: {msg}")
            return False


if __name__ == "__main__":
    # Try to reuse previous device state if challenge was pending
    load_temp = Path(TEMP_SETTINGS).exists()
    if load_temp:
        print("[*] Resuming from previous challenge attempt...")

    for attempt in range(3):
        cl = make_client(load_temp=(attempt > 0 or load_temp))

        print(f"\n[*] Attempt {attempt + 1} — username: {USERNAME}")
        result = try_login(cl, USERNAME, PASSWORD)

        if result is True:
            sys.exit(0)
        elif result is None:
            # Challenge pending — retry with same settings
            load_temp = True
            time.sleep(3)
            continue
        else:
            # Hard fail — try email
            if EMAIL:
                print(f"\n[*] Trying email: {EMAIL}")
                cl2 = make_client(load_temp=False)
                result2 = try_login(cl2, EMAIL, PASSWORD)
                if result2 is True:
                    sys.exit(0)
            break

    print("\n[!] Login failed. Check Instagram app for any pending verification.")
