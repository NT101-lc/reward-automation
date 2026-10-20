import json
from pathlib import Path

# thư mục gốc dự án (chứa rewards_bot/ và data/)
BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
PROFILES_DIR = DATA_DIR / "profiles"
SETTINGS_FILE = DATA_DIR / "settings.json"
HISTORY_FILE = DATA_DIR / "search_history.json"
POINTS_HISTORY_FILE = DATA_DIR / "points_history.json"  # số liệu điểm theo ngày cho biểu đồ
DASHBOARD_FILE = DATA_DIR / "dashboard.json"  # điểm + trạng thái task lần cuối, để mở app là thấy ngay

DEFAULT_SETTINGS = {
    "search_delay_min": 8,
    "search_delay_max": 20,
    "extra_searches": 2,
    "browser_channel": "msedge",
    "headless": False,
    "max_parallel": 3,
    "history_days": 30,
    "do_quests": True,
    "do_pc": True,
    "do_mobile": True,
    "do_images": True,
    "image_searches": 6,
    "do_browse": False,
    "bypass_proxy": True,  # trình duyệt của bot không đi qua proxy hệ thống
    "browse_minutes": 30,
    # mode: "managed" = cửa sổ riêng do app mở (data/profiles/<name>)
    #       "cdp"     = gắn vào trình duyệt đang mở với --remote-debugging-port
    "profiles": [{"name": "Profile 1", "mode": "managed", "cdp_port": 9222}],
}


def load_settings() -> dict:
    s = json.loads(json.dumps(DEFAULT_SETTINGS))
    if SETTINGS_FILE.exists():
        try:
            s.update(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
        except Exception:
            pass
    return s


def save_settings(s: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(s, indent=2, ensure_ascii=False), encoding="utf-8")


def profile_dir(name: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_ " else "_" for c in name).strip() or "profile"
    return PROFILES_DIR / safe
