"""
debug_ig.py — Instagram session diagnostic tool.

Usage:
  python debug_ig.py            # try username/password login
  python debug_ig.py <sessionid> # login via browser sessionid cookie
"""
import sys
import traceback
from pathlib import Path
from instagrapi import Client
from dotenv import load_dotenv
import os

load_dotenv(Path(__file__).parent / ".env")

USERNAME  = os.getenv("INSTAGRAM_USERNAME", "")
PASSWORD  = os.getenv("INSTAGRAM_PASSWORD", "")

SESSION_OUT = "storage/sessions/instagram.json"

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


def try_sessionid(sessionid: str) -> bool:
    print(f"\n[*] Trying sessionid login...")
    cl = Client()
    cl.delay_range = [2, 5]
    cl.set_device(DEVICE)
    cl.set_user_agent()
    try:
        cl.login_by_sessionid(sessionid)
        print("[+] sessionid login OK!")
        cl.dump_settings(SESSION_OUT)
        print(f"[+] Session saved → {SESSION_OUT}")
        return True
    except Exception as e:
        print(f"[-] sessionid login failed: {e}")
        traceback.print_exc()
        return False


def try_password() -> bool:
    print(f"\n[*] Trying username/password login: {USERNAME}")
    cl = Client()
    cl.delay_range = [3, 7]
    cl.set_device(DEVICE)
    cl.set_user_agent()
    try:
        cl.login(USERNAME, PASSWORD)
        print("[+] Login OK!")
        cl.dump_settings(SESSION_OUT)
        print(f"[+] Session saved → {SESSION_OUT}")
        return True
    except Exception as e:
        print(f"[-] ERROR TYPE : {type(e).__name__}")
        print(f"[-] ERROR TEXT : {e}")
        try:
            print("[-] LAST JSON  :", cl.last_json)
        except Exception:
            pass
        try:
            print("[-] RESPONSE   :", cl.private.response.text[:500])
        except Exception:
            pass
        traceback.print_exc()
        return False


if __name__ == "__main__":
    if len(sys.argv) > 1:
        try_sessionid(sys.argv[1])
    else:
        try_password()
