"""Mở Edge/Chrome "thường" cho bot rồi để Playwright gắn vào qua CDP (giống cách Selenium chạy).

Vì sao không dùng launch_persistent_context của Playwright: nó thêm khoảng 40 cờ (--enable-automation,
--disable-background-networking, --disable-sync, ...) và đặt navigator.webdriver = true. Với các cờ đó Bing từ chối
Visual Search ("Unable to process this search", upload trả 400). Mở trình duyệt chỉ với vài cờ tối thiểu thì
Visual Search chạy được và navigator.webdriver = false.

Cổng debug: --remote-debugging-port=0 để trình duyệt tự chọn cổng trống, chỉ nghe trên 127.0.0.1, đọc cổng từ file
DevToolsActivePort trong thư mục profile. Cổng đóng cùng trình duyệt.
"""

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

# Cờ đánh dấu trình duyệt do bot mở (để nhận ra bản mồ côi sau khi app bị tắt giữa chừng)
BOT_MARKER = "--remote-debugging-port=0"

_CANDIDATES = {
    "msedge": [r"Microsoft\Edge\Application\msedge.exe"],
    "chrome": [r"Google\Chrome\Application\chrome.exe"],
}


class LaunchError(RuntimeError):
    pass


def find_browser(channel: str) -> str:
    """Đường dẫn file chạy của trình duyệt theo kênh ("msedge" / "chrome" / "" = Chromium của Playwright)."""
    if not channel:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            path = p.chromium.executable_path
        if path and os.path.exists(path):
            return path
        raise LaunchError("Chưa cài Chromium của Playwright. Chạy: python -m playwright install chromium")
    roots = [os.environ.get(k) for k in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA")]
    for rel in _CANDIDATES.get(channel, []):
        for root in filter(None, roots):
            path = os.path.join(root, rel)
            if os.path.exists(path):
                return path
    found = shutil.which(channel)
    if found:
        return found
    raise LaunchError(f"Không tìm thấy trình duyệt '{channel}' trên máy")


def browser_version(exe: str):
    """Số phiên bản chính (vd "155") từ thư mục phiên bản nằm cạnh file chạy (Edge/Chrome trên Windows)."""
    folder = os.path.dirname(exe)
    try:
        versions = [d for d in os.listdir(folder) if d[:1].isdigit() and d.count(".") == 3]
    except OSError:
        return None
    return max(versions, key=lambda v: tuple(int(x) for x in v.split("."))).split(".")[0] if versions else None


def normal_user_agent(exe: str):
    """User-Agent của trình duyệt chạy bình thường. Chạy ẩn thì Edge tự ghi "HeadlessChrome" và Bing từ chối Visual Search."""
    major = browser_version(exe)
    if not major:
        return None
    ua = f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36"
    return ua + f" Edg/{major}.0.0.0" if os.path.basename(exe).lower() == "msedge.exe" else ua


def build_args(exe: str, user_data_dir: str, headless: bool, extra=()) -> list:
    """Dòng lệnh mở trình duyệt: chỉ các cờ cần thiết, không có cờ tự động hóa."""
    args = [exe, f"--user-data-dir={user_data_dir}", BOT_MARKER, "--remote-debugging-address=127.0.0.1",
            "--disable-blink-features=AutomationControlled", "--no-first-run", "--no-default-browser-check",
            "--window-size=1366,900", *extra]
    if os.path.basename(exe).lower() == "msedge.exe":
        args.append("--edge-skip-compat-layer-relaunch")  # để Edge không tự mở lại thành process khác
    if headless:
        # cửa sổ ẩn hẳn ra ngoài màn hình; KHÔNG thêm --disable-gpu (theo AutoRewarder, cờ đó làm hỏng việc đếm phút Edge)
        args += ["--headless=new", "--window-position=-32000,-32000", "--screen-info={0,0 1920x1080}"]
        ua = normal_user_agent(exe)
        if ua:
            args.append(f"--user-agent={ua}")
    return args + ["about:blank"]


def read_port(user_data_dir: str):
    """Cổng debug trình duyệt ghi ra (dòng đầu của DevToolsActivePort), None nếu chưa có."""
    f = Path(user_data_dir) / "DevToolsActivePort"
    try:
        first = f.read_text(encoding="utf-8").splitlines()[0].strip()
        return int(first) if first.isdigit() else None
    except (OSError, IndexError):
        return None


class Launched:
    """Trình duyệt bot đã mở: process + địa chỉ CDP."""

    def __init__(self, proc: subprocess.Popen, cdp_url: str):
        self.proc = proc
        self.cdp_url = cdp_url

    def alive(self) -> bool:
        return self.proc.poll() is None

    def close(self, browser=None, timeout: float = 10) -> None:
        """Đóng trình duyệt gọn gàng (để kịp lưu cookie / phiên đăng nhập), quá lâu thì buộc đóng."""
        if browser is not None:
            try:
                browser.new_browser_cdp_session().send("Browser.close")
            except Exception:
                pass
        try:
            self.proc.wait(timeout)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                pass


def launch(channel: str, user_data_dir: str, headless: bool, extra=(), timeout: float = 30) -> Launched:
    exe = find_browser(channel)
    (Path(user_data_dir) / "DevToolsActivePort").unlink(missing_ok=True)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
    proc = subprocess.Popen(build_args(exe, user_data_dir, headless, extra), creationflags=flags,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        port = read_port(user_data_dir)
        if port:
            return Launched(proc, f"http://127.0.0.1:{port}")
        if proc.poll() is not None:
            raise LaunchError("Trình duyệt đóng ngay khi mở (profile có thể đang mở ở cửa sổ khác)")
        time.sleep(0.2)
    proc.kill()
    raise LaunchError("Trình duyệt không mở cổng điều khiển sau 30 giây")
