"""Giao diện web (pywebview + Edge WebView2). Python giữ toàn bộ logic, JS chỉ hiển thị.

JS gọi Python qua window.pywebview.api.<hàm>(); Python đẩy sự kiện (log, trạng thái, bảng search)
sang JS theo lô mỗi 250ms qua window.onEvents([...]).
"""

import json
import queue
import threading
import time
from pathlib import Path

import webview

from ..core.config import (DASHBOARD_FILE, HISTORY_FILE, POINTS_HISTORY_FILE, load_settings, profile_dir,
                           save_settings)
from ..core.runner import Runner
from ..search.bank import QueryBank
from ..search.catalog import CATEGORIES, all_queries

WEB_DIR = Path(__file__).resolve().parent / "web"
SETTING_KEYS = ("search_delay_min", "search_delay_max", "extra_searches", "browser_channel", "headless",
                "max_parallel", "history_days", "do_quests", "do_pc", "do_mobile", "do_images", "image_searches",
                "do_browse", "browse_minutes")


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_json(path: Path, data) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


class Api:
    """Các hàm JS gọi được. Tên hàm không bắt đầu bằng '_' mới được lộ ra JS."""

    def __init__(self):
        self._window = None
        self._settings = load_settings()
        self._events: queue.Queue = queue.Queue()
        self._bank = QueryBank(HISTORY_FILE, int(self._settings.get("history_days", 30)))
        self._bank.on_change = lambda kind, payload: self._events.put({"type": "bank", "kind": kind, "data": payload})
        self._runner = Runner(
            self._bank,
            log=lambda n, m: self._events.put({"type": "log", "name": n, "msg": m, "time": time.strftime("%H:%M:%S")}),
            status=self._on_status,
            done=lambda n: self._events.put({"type": "done", "name": n}),
        )
        cache = _load_json(DASHBOARD_FILE)
        self._pstate = {n: {"state": "Sẵn sàng", "progress": "", **d} for n, d in cache.items()}
        self._history = _load_json(POINTS_HISTORY_FILE)
        self._lock = threading.Lock()
        self._bank.generate(60)

    # ------------------------------------------------------------ nội bộ
    def _on_status(self, name: str, data: dict) -> None:
        with self._lock:
            st = self._pstate.setdefault(name, {"state": "Sẵn sàng", "progress": ""})
            st.update(data)
            if data.get("stats") and data["stats"].get("available") is not None:
                self._history.setdefault(name, {})[time.strftime("%Y-%m-%d")] = data["stats"]
                _write_json(POINTS_HISTORY_FILE, self._history)
            if any(k in data for k in ("tasks", "points", "stats")):
                keep = ("points", "today", "tasks", "stats", "icons", "updated")
                _write_json(DASHBOARD_FILE, {n: {k: s.get(k) for k in keep if k in s} for n, s in self._pstate.items()})
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
                "bank": self._bank.rows,
                "catalog": {"categories": len(CATEGORIES), "queries": len(all_queries())},
            }

    def save_profile(self, old_name, profile: dict) -> dict:
        name = (profile.get("name") or "").strip()
        if not name:
            return {"ok": False, "error": "Nhập tên profile."}
        if name != old_name and self._find(name):
            return {"ok": False, "error": "Đã có profile tên này."}
        if old_name and self._runner.is_running(old_name):
            return {"ok": False, "error": "Dừng profile trước khi sửa."}
        p = {"name": name, "mode": profile.get("mode", "managed"), "cdp_port": int(profile.get("cdp_port") or 9222)}
        old = self._find(old_name) if old_name else None
        if old:
            old.update(p)
            if old_name != name and old_name in self._pstate:
                self._pstate[name] = self._pstate.pop(old_name)
        else:
            self._profiles().append(p)
        save_settings(self._settings)
        return {"ok": True, "profiles": self._profiles()}

    def delete_profiles(self, names: list) -> dict:
        names = [n for n in names if not self._runner.is_running(n)]
        self._settings["profiles"] = [p for p in self._profiles() if p["name"] not in names]
        save_settings(self._settings)
        return {"ok": True, "profiles": self._profiles()}

    def start(self, names, action: str = "run") -> dict:
        profs = self._profiles() if not names else [p for p in map(self._find, names) if p]
        self._runner.start(profs, dict(self._settings), action=action)
        return {"ok": True, "running": list(self._runner.running)}

    def stop(self, names=None) -> dict:
        self._runner.stop(names or None)
        return {"ok": True}

    def save_settings(self, partial: dict) -> dict:
        for k, v in partial.items():
            if k in SETTING_KEYS:
                self._settings[k] = v
        if self._settings["search_delay_max"] < self._settings["search_delay_min"]:
            self._settings["search_delay_max"] = self._settings["search_delay_min"]
        self._bank.history_days = int(self._settings["history_days"])
        save_settings(self._settings)
        return {"ok": True, "settings": {k: self._settings.get(k) for k in SETTING_KEYS}}

    def generate_queries(self, n: int) -> dict:
        return {"ok": True, "rows": self._bank.generate(int(n))}

    def clear_query_history(self) -> dict:
        self._bank.clear_history()
        return {"ok": True}

    def export_csv(self) -> dict:
        res = self._window.create_file_dialog(webview.SAVE_DIALOG, save_filename="bang_search.csv",
                                              file_types=("CSV (*.csv)",))
        if not res:
            return {"ok": False}
        path = res if isinstance(res, str) else res[0]
        self._bank.export_csv(path)
        return {"ok": True, "path": path}

    def profile_folder(self, name: str) -> str:
        return str(profile_dir(name))


def main() -> None:
    api = Api()
    window = webview.create_window("Microsoft Rewards Bot", url=str(WEB_DIR / "index.html"), js_api=api,
                                   width=1320, height=880, min_size=(1020, 680), background_color="#F5F6FA")
    api._window = window

    def on_closing():
        api._runner.stop()

    window.events.closing += on_closing
    threading.Thread(target=api._pump, daemon=True).start()
    webview.start(gui="edgechromium", debug=False)
