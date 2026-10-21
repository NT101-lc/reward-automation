"""Phát hiện trình duyệt đang giữ thư mục profile của app (Edge mồ côi sau khi app bị tắt giữa chừng)."""

import json
import subprocess
import sys
from pathlib import Path

from .edge_launcher import BOT_MARKER

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class ProfileInUse(Exception):
    pass


def _browser_processes() -> list:
    """[(pid, commandline, parent_alive)] của các tiến trình trình duyệt chính (không tính tiến trình con --type=...)."""
    if sys.platform != "win32":
        return []
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='msedge.exe' or Name='chrome.exe'\" | "
          "Where-Object { $_.CommandLine -and $_.CommandLine -notlike '*--type=*' } | "
          "Select-Object ProcessId, CommandLine, @{n='ParentAlive';e={[bool](Get-Process -Id $_.ParentProcessId "
          "-ErrorAction SilentlyContinue)}} | ConvertTo-Json -Compress")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True,
                             timeout=20, creationflags=_NO_WINDOW).stdout.strip()
    except Exception:
        return []
    if not out:
        return []
    data = json.loads(out)
    if isinstance(data, dict):
        data = [data]
    return [(d["ProcessId"], d["CommandLine"], bool(d.get("ParentAlive"))) for d in data]


def _uses_dir(cmdline: str, profile_dir: Path) -> bool:
    want = str(profile_dir.resolve()).lower().rstrip("\\")
    low = cmdline.lower().replace('"', "")
    i = low.find("--user-data-dir=")
    if i < 0:
        return False
    rest = low[i + len("--user-data-dir="):]
    return rest.startswith(want) and (len(rest) == len(want) or rest[len(want)] in " \\")


def free_profile(profile_dir: Path, log=print) -> None:
    """Đảm bảo không còn trình duyệt nào giữ profile_dir.

    - Trình duyệt do bot mở mà chương trình mở nó đã tắt (mồ côi) -> đóng nó.
    - Trình duyệt của một bot ĐANG chạy (app khác, script khác) -> báo lỗi, không đụng vào.
    - Cửa sổ trình duyệt bình thường đang dùng profile -> báo lỗi rõ ràng, không đụng vào.
    """
    for pid, cmd, parent_alive in _browser_processes():
        if not _uses_dir(cmd, profile_dir):
            continue
        bot_owned = "--remote-debugging-pipe" in cmd or BOT_MARKER in cmd  # bot mở (Playwright cũ / edge_launcher)
        if bot_owned and parent_alive:
            raise ProfileInUse(f"Tài khoản này đang được bot chạy ở nơi khác (pid {pid}). Đợi chạy xong hoặc bấm Dừng.")
        if bot_owned:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, creationflags=_NO_WINDOW)
            log(f"Đã đóng trình duyệt cũ của bot còn chạy ngầm (pid {pid}) đang giữ profile")
        else:
            raise ProfileInUse(f"Profile đang mở trong một cửa sổ trình duyệt khác (pid {pid}). "
                               "Đóng cửa sổ đó rồi chạy lại.")
