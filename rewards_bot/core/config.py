import copy
import json
import os
from pathlib import Path

# thư mục gốc dự án (chứa rewards_bot/ và data/)
BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
PROFILES_DIR = DATA_DIR / "profiles"
SETTINGS_FILE = DATA_DIR / "settings.json"
HISTORY_FILE = DATA_DIR / "search_history.json"
POINTS_HISTORY_FILE = DATA_DIR / "points_history.json"  # số liệu điểm theo ngày cho biểu đồ
DASHBOARD_FILE = DATA_DIR / "dashboard.json"  # điểm + trạng thái task lần cuối, để mở app là thấy ngay
LOG_DIR = DATA_DIR / "logs"  # nhật ký mỗi ngày 1 file
LOCK_FILE = DATA_DIR / "app.lock"  # chỉ cho 1 cửa sổ app chạy cùng lúc

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
    "do_visual": True,  # Visual Search: tải 1 ảnh lên bằng nút camera của Bing Images
    "do_browse": False,
    "theme": "system",  # giao diện: "system" (theo Windows) / "light" / "dark" / "cyberpunk"
    "bypass_proxy": True,  # trình duyệt của bot không đi qua proxy hệ thống
    "browse_minutes": 30,
    # mode: "managed" = cửa sổ riêng do app mở (data/profiles/<dir>)
    #       "cdp"     = gắn vào trình duyệt đang mở với --remote-debugging-port
    # dir: tên thư mục phiên đăng nhập, cố định từ lúc tạo (đổi tên tài khoản không đổi thư mục)
    "profiles": [],
}

# lỗi đọc file gần nhất (để giao diện / log báo cho người dùng thay vì âm thầm reset)
LOAD_WARNINGS: list = []


# ---------------------------------------------------------------- đọc/ghi JSON an toàn
def write_json(path: Path, data, indent=None) -> None:
    """Ghi atomic: ghi ra file tạm rồi thay thế; bản cũ được giữ ở <file>.bak."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=indent)
        f.flush()
        os.fsync(f.fileno())
    if path.exists():
        os.replace(path, path.with_suffix(path.suffix + ".bak"))
    os.replace(tmp, path)


def read_json(path: Path, default):
    """Đọc JSON; file hỏng thì dùng <file>.bak và ghi cảnh báo; không có gì thì trả default."""
    for p in (path, path.with_suffix(path.suffix + ".bak")):
        if not p.exists():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if p != path:
                LOAD_WARNINGS.append(f"{path.name} bị hỏng, đã khôi phục từ bản sao lưu")
            return data
        except Exception:
            if p == path:
                LOAD_WARNINGS.append(f"{path.name} bị hỏng")
    return copy.deepcopy(default)


# ---------------------------------------------------------------- thư mục profile
def safe_dir_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_ " else "_" for c in name).strip() or "profile"


def new_profile_dir(name: str, taken=()) -> str:
    """Tên thư mục mới chưa ai dùng cho tài khoản `name`."""
    base = safe_dir_name(name)
    used = set(taken)
    cand, i = base, 2
    while cand in used or (PROFILES_DIR / cand).exists():
        cand, i = f"{base}_{i}", i + 1
    return cand


def profile_dir(profile) -> Path:
    """Thư mục phiên đăng nhập của 1 profile (dict có 'dir'; chuỗi = cách cũ suy ra từ tên)."""
    if isinstance(profile, dict):
        return PROFILES_DIR / (profile.get("dir") or safe_dir_name(profile["name"]))
    return PROFILES_DIR / safe_dir_name(profile)


def _migrate(s: dict) -> bool:
    """Profile cũ chưa có 'dir' -> gán thư mục đang dùng (suy từ tên). Trả True nếu có thay đổi."""
    changed = False
    for p in s.get("profiles", []):
        if not p.get("dir"):
            p["dir"] = safe_dir_name(p["name"])
            changed = True
    return changed


# ---------------------------------------------------------------- cài đặt
def load_settings() -> dict:
    s = copy.deepcopy(DEFAULT_SETTINGS)
    s.update(read_json(SETTINGS_FILE, {}))
    if _migrate(s):
        save_settings(s)
    return s


def save_settings(s: dict) -> None:
    write_json(SETTINGS_FILE, s, indent=2)
