"""Mở giao diện web trong Edge ẩn với API giả: không lỗi JS, CSP không chặn app.js, các trang render được."""
import functools
import http.server
import json
import shutil
import subprocess
import threading
from pathlib import Path

import pytest

from conftest import FIXTURES

WEB = Path(__file__).resolve().parents[1] / "rewards_bot" / "ui" / "web"
playwright = pytest.importorskip("playwright.sync_api")


def test_app_js_syntax():
    if not shutil.which("node"):
        pytest.skip("không có node")
    r = subprocess.run(["node", "--check", str(WEB / "app.js")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


@pytest.fixture(scope="module")
def server():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(WEB))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def boot_data():
    from rewards_bot.core import rewards_page as rp
    items = json.loads((FIXTURES / "rewards_items.json").read_text(encoding="utf-8"))
    st = rp.empty_state()
    rp.parse_page(items["dashboard"], st)
    rp.parse_page(items["earn"], st)
    rp.parse_breakdown(items["breakdown"], st)
    check = [{"level": "ok", "title": "Đăng nhập rewards.bing.com", "detail": "3,417 điểm"},
             {"level": "fail", "title": "Tài khoản trên bing.com", "detail": "<b>sai tài khoản</b>"}]
    return {
        "settings": {"search_delay_min": 8, "search_delay_max": 20, "extra_searches": 2, "browser_channel": "msedge",
                     "headless": True, "max_parallel": 3, "history_days": 30, "do_quests": True, "do_pc": True,
                     "do_mobile": True, "do_visual": True, "do_browse": False,
                     "browse_minutes": 30, "bypass_proxy": True, "theme": "light"},
        "profiles": [{"name": "acc <img src=x onerror=alert(1)>", "mode": "managed", "cdp_port": 9222, "dir": "a"}],
        "pstate": {"acc <img src=x onerror=alert(1)>": {
            "state": "Sẵn sàng", "points": 3417, "today": 98, "tasks": rp.build_task_rows(st), "stats": rp.stats(st),
            "icons": rp.group_icons(st), "check": check, "check_time": "10:00 20/10",
            "streak": {"stamps": {"progress": 3, "max": 12, "bonus": 1000}, "daily_streak": 11, "streaks": [
                {"title": "Bing Search Streak", "day": 4, "of": 7, "today": "1/1", "today_done": True, "img": ""},
                {"title": "<img src=x onerror=alert(2)>", "day": 0, "of": 7, "today": "0/1", "today_done": False,
                 "img": ""}]}}},
        "history": {"acc <img src=x onerror=alert(1)>": {
            "2026-10-20": {"available": 3517, "pc": 90, "mobile": 60, "offers": 47},
            "2026-10-21": {"available": 3696, "pc": 90, "mobile": 60, "offers": 29}}},
        "running": [],
    }


SHOT = None  # đặt đường dẫn để chụp ảnh khi xem giao diện bằng tay


def test_pages_render_without_errors(server):
    boot = boot_data()
    mock = ("window.__B = " + json.dumps(boot) + ";"
            "window.pywebview = { api: new Proxy({}, { get: (_, k) => async () => k === 'bootstrap' ? window.__B"
            " : {ok: true, running: [], settings: window.__B.settings, profiles: window.__B.profiles} }) };"
            "window.addEventListener('load', () => window.dispatchEvent(new Event('pywebviewready')));")
    with playwright.sync_playwright() as p:
        try:
            b = p.chromium.launch(channel="msedge", headless=True)
        except Exception:
            pytest.skip("không mở được Edge")
        pg = b.new_page()
        errors, dialogs = [], []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.on("console", lambda m: m.type == "error" and "favicon" not in m.text and "Failed to load resource" not in m.text
              and errors.append(m.text))
        pg.on("dialog", lambda d: (dialogs.append(d.message), d.dismiss()))
        pg.add_init_script(mock)
        pg.goto(server + "/index.html")
        pg.wait_for_function("document.querySelectorAll('.chip').length === 1", timeout=10000)
        assert pg.locator("#check-panel").is_visible()
        assert pg.locator("#check-list li.fail").count() == 1
        assert pg.locator("#stamps .stamp").count() >= 5
        assert pg.locator("#streak-panel").is_visible()
        assert pg.locator("#stamp-grid .sdot").count() == 12
        assert pg.locator("#stamp-grid .sdot.on").count() == 3
        assert pg.locator("#streak-list .streak-row").count() == 2
        assert pg.locator("#streak-list .streak-row").first.locator(".sday").count() == 7
        assert pg.locator("#streak-list .streak-row").first.locator(".sday.on").count() == 4
        pg.wait_for_function("document.querySelectorAll('#chart-daily .apexcharts-canvas, #chart-balance .apexcharts-canvas').length === 2",
                             timeout=10000)
        assert pg.evaluate("document.documentElement.dataset.bsTheme") == "light"
        pg.click(".theme-switch button[data-theme=dark]")
        assert pg.evaluate("document.documentElement.dataset.bsTheme") == "dark"
        # icon task là PNG trong vendor/fluent-emoji (không lấy ảnh Bing), tải được và đúng loại
        icons = pg.evaluate("Array.from(document.querySelectorAll('#task-groups .task .tico'),"
                            " (i) => [i.getAttribute('src'), i.complete && i.naturalWidth > 0])")
        assert icons and all(src.startswith("vendor/fluent-emoji/") and ok for src, ok in icons), icons
        srcs = [src for src, _ in icons]
        assert srcs[:2] == ["vendor/fluent-emoji/pc.png", "vendor/fluent-emoji/mobile.png"]  # Search PC, Search Mobile
        assert "vendor/fluent-emoji/camera.png" in srcs  # Visual Search
        pg.click(".theme-switch button[data-theme=cyberpunk]")  # giao diện Cyberpunk: nền tối + lớp riêng
        assert pg.evaluate("[document.documentElement.dataset.bsTheme, document.documentElement.dataset.skin]") == ["dark", "cyberpunk"]
        assert pg.evaluate("getComputedStyle(document.body).fontFamily").lstrip('"').startswith("Bahnschrift")
        pg.click(".theme-switch button[data-theme=light]")
        assert pg.evaluate("document.documentElement.dataset.skin") is None
        if SHOT:
            pg.set_viewport_size({"width": 1320, "height": 1100})
            pg.screenshot(path=SHOT, full_page=True)
        for page in ("profiles", "log", "settings", "guide", "dashboard"):
            pg.evaluate(f"go('{page}')")
            pg.wait_for_timeout(200)
        # hộp thoại thêm tài khoản: nền đặc, ô cổng chỉ hiện ở chế độ gắn vào Edge, nút nằm trong khung
        pg.evaluate("go('profiles')"); pg.click("#btn-add")
        assert pg.locator("#profile-dialog").is_visible()
        assert pg.evaluate("getComputedStyle(document.querySelector('#profile-dialog')).backgroundColor") not in ("rgba(0, 0, 0, 0)", "transparent")
        assert not pg.locator("#pd-port").is_visible()
        pg.click("input[name=mode][value=cdp] + .form-selectgroup-label")
        assert pg.locator("#pd-port").is_visible()
        box, save = pg.locator("#profile-dialog").bounding_box(), pg.locator("#pd-save").bounding_box()
        assert save["x"] + save["width"] <= box["x"] + box["width"] and save["y"] + save["height"] <= box["y"] + box["height"]
        if SHOT:
            pg.screenshot(path=SHOT.replace(".png", "_dialog.png"))
        pg.click("#profile-dialog .btn-close")
        assert not pg.locator("#profile-dialog").is_visible()
        pg.evaluate("go('guide')")
        assert pg.locator("#page-guide .accordion-item").count() >= 5
        pg.click("#page-guide [data-bs-target='#g-fix']")
        pg.wait_for_selector("#g-fix.show", timeout=3000)  # accordion của Tabler/Bootstrap hoạt động
        b.close()
    assert errors == []
    assert dialogs == []  # tên/tiêu đề chứa HTML không được chạy
