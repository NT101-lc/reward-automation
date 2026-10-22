"""Giao diện web (pywebview + Edge WebView2). Python giữ toàn bộ logic, JS chỉ hiển thị.

JS gọi Python qua window.pywebview.api.<hàm>(); Python đẩy sự kiện (log, trạng thái)
sang JS theo lô mỗi 250ms qua window.onEvents([...]).
"""

import json
import queue
import sys
import threading
import time
from pathlib import Path

import webview

from ..core import credentials, security
from ..core import config
from ..core.config import (DATA_DIR, DASHBOARD_FILE, HISTORY_FILE, POINTS_HISTORY_FILE, load_settings, new_profile_dir,
                           read_json, save_settings, write_json)
from ..core.runner import Runner
from ..search.bank import QueryBank

WEB_DIR = Path(__file__).resolve().parent / "web"
# Kiểu và khoảng hợp lệ của từng cài đặt: mọi giá trị từ giao diện đều được kiểm tra trước khi lưu
SETTING_SCHEMA = {
    "search_delay_min": (int, 1, 600), "search_delay_max": (int, 1, 600), "extra_searches": (int, 0, 20),
    "max_parallel": (int, 1, 10), "history_days": (int, 0, 365),
    "browse_minutes": (int, 1, 240),
    "headless": (bool,), "do_quests": (bool,), "do_pc": (bool,), "do_mobile": (bool,), "do_visual": (bool,),
    "do_browse": (bool,), "bypass_proxy": (bool,),
    "browser_channel": (str, ("msedge", "chrome", "")),
    "theme": (str, ("system", "light", "dark", "cyberpunk")),
}
SETTING_KEYS = tuple(SETTING_SCHEMA)
ACTIONS = {"run", "refresh", "login", "check"}
NAME_MAX = 40
BAD_NAME_CHARS = set('\\/:*?"<>|')  # ký tự không hợp lệ trong tên thư mục Windows


def _clean_setting(key, value):
    """Trả về giá trị đã kiểm tra, hoặc raise ValueError."""
    kind, *rule = SETTING_SCHEMA[key]
    if kind is bool:
        if not isinstance(value, bool):
            raise ValueError(f"{key} phải là bật/tắt")
        return value
    if kind is int:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or int(value) != value:
            raise ValueError(f"{key} phải là số nguyên")
        lo, hi = rule
        if not lo <= value <= hi:
            raise ValueError(f"{key} phải trong khoảng {lo}-{hi}")
        return int(value)
    if value not in rule[0]:
        raise ValueError(f"{key} không hợp lệ")
    return value


def _missing(tasks: list) -> list:
    """Các task chưa xong: [{"t": tiêu đề, "g": nhóm, "p": đã làm, "m": cần}] (Daily Set, Keep earning, hoạt động...)."""
    out = []
    for r in tasks:
        if not isinstance(r, dict) or r.get("done") or r.get("group") == "Task thêm":
            continue
        out.append({"t": str(r.get("title", ""))[:80], "g": r.get("group", ""), "p": r.get("progress"), "m": r.get("max")})
    return out


def _save(path: Path, data) -> None:
    try:
        write_json(path, data)
    except OSError:
        pass


class Api:
    """Các hàm JS gọi được. Tên hàm không bắt đầu bằng '_' mới được lộ ra JS."""

    def __init__(self):
        self._window = None
        self._settings = load_settings()
        self._events: queue.Queue = queue.Queue()
        # câu search vẫn sinh tự động (đa lĩnh vực, không trùng) dù không còn trang bảng search
        self._bank = QueryBank(HISTORY_FILE, int(self._settings.get("history_days", 30)))
        self._runner = Runner(
            self._bank,
            log=lambda n, m: self._events.put({"type": "log", "name": n, "msg": m, "time": time.strftime("%H:%M:%S")}),
            status=self._on_status,
            done=lambda n: self._events.put({"type": "done", "name": n}),
        )
        cache = read_json(DASHBOARD_FILE, {})
        self._pstate = {n: {"state": "Sẵn sàng", "progress": "", **d} for n, d in cache.items()}
        self._history = read_json(POINTS_HISTORY_FILE, {})
        self._lock = threading.Lock()
        for w in config.LOAD_WARNINGS:  # file dữ liệu hỏng -> báo trong nhật ký thay vì âm thầm bỏ qua
            self._events.put({"type": "log", "name": "app", "msg": "cảnh báo: " + w, "time": time.strftime("%H:%M:%S")})

    # ------------------------------------------------------------ nội bộ
    def _on_status(self, name: str, data: dict) -> None:
        with self._lock:
            st = self._pstate.setdefault(name, {"state": "Sẵn sàng", "progress": ""})
            st.update(data)
            if data.get("stats") and data["stats"].get("available") is not None:
                day = {**data["stats"]}
                if isinstance(data.get("tasks"), list):  # việc còn thiếu trong ngày, cho trang Lịch sử
                    day["missing"] = _missing(data["tasks"])
                self._history.setdefault(name, {})[time.strftime("%Y-%m-%d")] = day
                _save(POINTS_HISTORY_FILE, self._history)
            if any(k in data for k in ("tasks", "points", "stats", "check")):
                keep = ("points", "today", "tasks", "stats", "icons", "streak", "updated", "check", "check_time")
                _save(DASHBOARD_FILE, {n: {k: s.get(k) for k in keep if k in s} for n, s in self._pstate.items()})
        self._events.put({"type": "status", "name": name, "data": data,
                          "history": self._history.get(name) if "stats" in data else None})

    def _pump(self) -> None:
        """Gửi sự kiện sang JS theo lô."""
        while True:
            batch = [self._events.get()]
            time.sleep(0.25)
            while not self._events.empty() and len(batch) < 500:
                batch.append(self._events.get_nowait())
            if self._window:
                try:
                    self._window.evaluate_js(f"window.onEvents && window.onEvents({json.dumps(batch, ensure_ascii=False)})")
                except Exception:
                    pass

    def _profiles(self) -> list:
        return self._settings["profiles"]

    def _find(self, name):
        return next((p for p in self._profiles() if p["name"] == name), None)

    # ------------------------------------------------------------ gọi từ JS
    def bootstrap(self) -> dict:
        with self._lock:
            return {
                "settings": {k: self._settings.get(k) for k in SETTING_KEYS},
                "profiles": self._profiles(),
                "pstate": self._pstate,
                "history": self._history,
                "running": list(self._runner.running),
                "credentials": self._cred_info(),
            }

    @staticmethod
    def _cred_info() -> dict:
        """Chỉ cho giao diện biết tài khoản nào đã lưu mật khẩu (kèm email), không bao giờ gửi mật khẩu."""
        return {"supported": credentials.supported(), "emails": credentials.emails()}

    def save_credentials(self, name, email, password) -> dict:
        if not isinstance(name, str) or not self._find(name):
            return {"ok": False, "error": "Không có tài khoản này."}
        if not credentials.supported():
            return {"ok": False, "error": "Chỉ lưu được mật khẩu trên Windows (mã hóa DPAPI)."}
        try:
            credentials.save(name, str(email or ""), str(password or ""))
        except (ValueError, OSError) as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True, "credentials": self._cred_info()}

    def delete_credentials(self, name) -> dict:
        if isinstance(name, str):
            credentials.remove(name)
        return {"ok": True, "credentials": self._cred_info()}

    def save_profile(self, old_name, profile: dict) -> dict:
        if not isinstance(profile, dict):
            return {"ok": False, "error": "Dữ liệu không hợp lệ."}
        name = str(profile.get("name") or "").strip()
        if not name:
            return {"ok": False, "error": "Nhập tên profile."}
        if len(name) > NAME_MAX or BAD_NAME_CHARS & set(name) or not name.isprintable():
            return {"ok": False, "error": f'Tên tối đa {NAME_MAX} ký tự, không chứa các ký tự {" ".join(sorted(BAD_NAME_CHARS))}'}
        mode = profile.get("mode", "managed")
        if mode not in ("managed", "cdp"):
            return {"ok": False, "error": "Chế độ không hợp lệ."}
        try:
            port = security.validate_port(profile.get("cdp_port") or 9222)
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        if name != old_name and self._find(name):
            return {"ok": False, "error": "Đã có profile tên này."}
        if old_name and self._runner.is_running(old_name):
            return {"ok": False, "error": "Dừng profile trước khi sửa."}
        p = {"name": name, "mode": mode, "cdp_port": port}
        old = self._find(old_name) if old_name else None
        with self._lock:
            if old:
                old.update(p)  # giữ nguyên old["dir"]: đổi tên không làm mất phiên đăng nhập
                if old_name != name:
                    for store in (self._pstate, self._history):
                        if old_name in store:
                            store[name] = store.pop(old_name)
                    _save(POINTS_HISTORY_FILE, self._history)
                    credentials.rename(old_name, name)
            else:
                p["dir"] = new_profile_dir(name, taken=[x.get("dir") for x in self._profiles()])
                self._profiles().append(p)
            save_settings(self._settings)
        return {"ok": True, "profiles": self._profiles()}

    def delete_profiles(self, names: list) -> dict:
        names = [n for n in (names or []) if isinstance(n, str) and not self._runner.is_running(n)]
        self._settings["profiles"] = [p for p in self._profiles() if p["name"] not in names]
        save_settings(self._settings)
        for n in names:  # xóa tài khoản thì xóa luôn mật khẩu đã lưu
            credentials.remove(n)
        return {"ok": True, "profiles": self._profiles()}

    def start(self, names, action: str = "run") -> dict:
        if action not in ACTIONS:
            return {"ok": False, "error": "Lệnh không hợp lệ", "running": list(self._runner.running)}
        profs = self._profiles() if not names else [p for p in map(self._find, names) if p]
        self._runner.start(profs, dict(self._settings), action=action)
        return {"ok": True, "running": list(self._runner.running)}

    def stop(self, names=None) -> dict:
        self._runner.stop(names or None)
        return {"ok": True}

    def save_settings(self, partial: dict) -> dict:
        try:
            clean = {k: _clean_setting(k, v) for k, v in (partial or {}).items() if k in SETTING_SCHEMA}
        except ValueError as e:
            return {"ok": False, "error": str(e), "settings": {k: self._settings.get(k) for k in SETTING_KEYS}}
        self._settings.update(clean)
        if self._settings["search_delay_max"] < self._settings["search_delay_min"]:
            self._settings["search_delay_max"] = self._settings["search_delay_min"]
        self._bank.history_days = int(self._settings["history_days"])
        save_settings(self._settings)
        return {"ok": True, "settings": {k: self._settings.get(k) for k in SETTING_KEYS}}


def _windows_dark() -> bool:
    """Windows đang dùng giao diện tối cho ứng dụng?"""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
    except (OSError, ImportError):  # ImportError: không phải Windows (không có winreg)
        return False


def _window_background(theme: str) -> str:
    """Màu nền cửa sổ khi trang chưa vẽ xong, khớp sáng/tối để không bị nháy."""
    if theme == "cyberpunk":
        return "#0b1022"
    dark = theme == "dark" or (theme == "system" and _windows_dark())
    return "#151f2c" if dark else "#f6f8fb"


def main() -> None:
    security.harden_data_dir(DATA_DIR)
    api = Api()
    window = webview.create_window("Microsoft Rewards Bot", url=str(WEB_DIR / "index.html"), js_api=api,
                                   width=1320, height=880, min_size=(1020, 680),
                                   background_color=_window_background(api._settings.get("theme", "system")),
                                   text_select=True)  # cho bôi đen / copy nhật ký
    api._window = window

    def on_closing():
        # dừng bot và đợi trình duyệt đóng hẳn, tránh để Edge chạy ngầm giữ profile
        api._runner.stop()
        api._runner.wait(15)

    window.events.closing += on_closing
    threading.Thread(target=api._pump, daemon=True).start()
    # http_server: pywebview phục vụ thư mục web/ qua 127.0.0.1 (cổng ngẫu nhiên) để CSP 'self' áp dụng được;
    # trang mở bằng file:// thì Chromium không coi là 'self' và chặn luôn app.js
    # Windows: Edge WebView2. Linux/macOS: để pywebview tự chọn (GTK/WebKitGTK, Qt hoặc Cocoa)
    webview.start(gui="edgechromium" if sys.platform == "win32" else None, debug=False, http_server=True)
