"""Logic của bot không cần trình duyệt thật: số lượt search, phát hiện đứng điểm, chọn thẻ, nhận diện profile."""
import threading
from pathlib import Path

import pytest

from rewards_bot.core.bot import RewardsBot
from rewards_bot.core.browser import _uses_dir
from rewards_bot.core.rewards_page import empty_state


class FakeMouse:
    def wheel(self, *a):
        pass


class FakePage:
    def __init__(self):
        self.visits = []
        self.mouse = FakeMouse()

    def goto(self, url, **k):
        self.visits.append(url)


class FakeBank:
    def __init__(self):
        self.n = 0

    def take(self, who):
        self.n += 1
        return f"query {self.n}"


def make_bot(**settings):
    s = {"search_delay_min": 0, "search_delay_max": 0, "extra_searches": 0, **settings}
    logs = []
    bot = RewardsBot({"name": "t", "mode": "managed"}, s, FakeBank(), lambda n, m: logs.append(m),
                     lambda n, d: None, threading.Event())
    bot.sleep = lambda *a: None
    return bot, logs


def test_searches_needed():
    bot, _ = make_bot()
    bot.state = empty_state()
    assert bot.searches_needed("pc") is None
    bot.state["pc"] = {"progress": 60, "max": 90}
    assert bot.searches_needed("pc") == 10
    bot.state["pc"] = {"progress": 89, "max": 90}
    assert bot.searches_needed("pc") == 1
    bot.state["pc"] = {"progress": 90, "max": 90}
    assert bot.searches_needed("pc") == 0


def test_search_stops_when_points_stall():
    bot, logs = make_bot()
    bot.state = empty_state()
    bot.state["mobile"] = {"progress": 24, "max": 60}
    bot._recheck = lambda page, kind: {"progress": 24, "max": 60}  # không bao giờ tăng
    page = FakePage()
    bot.do_searches(page, "mobile", "Search Mobile")
    assert "mobile" in bot.stalled
    assert len(page.visits) == bot.STALL_AFTER  # dừng sau đúng số lượt không được cộng
    assert any("không được cộng điểm" in m for m in logs)


def test_mobile_profile_matches_real_version():
    p = RewardsBot.mobile_profile({"chromium": "155.0.8059.85", "edge": "155.0.4283.62"})
    md = p["userAgentMetadata"]
    assert "Chrome/155.0.0.0" in p["userAgent"] and "EdgA/155.0.0.0" in p["userAgent"]
    assert {b["version"] for b in md["brands"] if b["brand"] != "Not(A:Brand"} == {"155"}
    assert md["fullVersion"] == "155.0.4283.62" and md["bitness"] == "" and md["mobile"]


def test_search_continues_while_points_increase():
    bot, logs = make_bot()
    bot.state = empty_state()
    bot.state["pc"] = {"progress": 60, "max": 90}
    seq = iter([69, 78, 87])  # đọc lại ở lượt 3, 6, 9: điểm vẫn tăng
    bot._recheck = lambda page, kind: {"progress": next(seq), "max": 90}
    page = FakePage()
    bot.do_searches(page, "pc", "Search PC")
    assert not bot.stalled
    assert len(page.visits) == 10  # đủ 10 lượt cần thiết


def test_search_stops_early_when_full():
    bot, logs = make_bot(extra_searches=5)
    bot.state = empty_state()
    bot.state["pc"] = {"progress": 81, "max": 90}
    bot._recheck = lambda page, kind: {"progress": 90, "max": 90}
    page = FakePage()
    bot.do_searches(page, "pc", "Search PC")
    assert any("đã đủ điểm" in m for m in logs)
    assert len(page.visits) == bot.CHECK_EVERY  # dừng ngay lần đọc lại đầu tiên


def test_full_already_does_nothing():
    bot, logs = make_bot()
    bot.state = empty_state()
    bot.state["pc"] = {"progress": 90, "max": 90}
    page = FakePage()
    bot.do_searches(page, "pc", "Search PC")
    assert page.visits == []


def test_uses_dir_matches_exact_folder_only(tmp_path):
    d = tmp_path / "namanh"
    assert _uses_dir(f'msedge.exe --user-data-dir="{d}" --remote-debugging-pipe', d)
    assert _uses_dir(f"msedge.exe --user-data-dir={d} about:blank", d)
    assert not _uses_dir(f"msedge.exe --user-data-dir={d}_2 about:blank", d)
    assert not _uses_dir("msedge.exe --no-startup-window", d)


def test_log_drops_playwright_call_log():
    bot, logs = make_bot()
    bot.log('  lỗi browse: Page.goto: net::ERR_CONNECTION_REFUSED at https://x.com/\nCall log:\n  - navigating to "x"')
    assert logs == ["  lỗi browse: Page.goto: net::ERR_CONNECTION_REFUSED at https://x.com/"]


def test_browse_progress_goes_into_edge_minutes_row():
    bot, _ = make_bot()
    sent = {}
    bot._status = lambda n, d: sent.update(d)
    bot.state = empty_state()
    bot.state["activity"] = [{"title": "Edge – Minutes", "key": "edge", "progress": 0, "max": 30, "img": ""}]
    bot.set_local("Browse", 6, 30, "phút")
    rows = sent["tasks"]
    assert not any(r["title"] == "Browse" for r in rows)  # không sinh dòng mới
    edge = next(r for r in rows if r["title"] == "Edge – Minutes")
    assert edge["unit"] == "phút" and edge["progress"] == 0 and edge["bot"] == "bot: 6/30 phút"


def test_local_task_without_matching_activity_gets_own_row():
    bot, _ = make_bot()
    sent = {}
    bot._status = lambda n, d: sent.update(d)
    bot.state = empty_state()
    bot.set_local("Browse", 6, 30, "phút")
    assert any(r["title"] == "Browse" and r["group"] == "Task thêm" for r in sent["tasks"])


def test_browse_stops_when_browser_closed():
    bot, logs = make_bot()

    class ClosedPage:
        url = "about:blank"
        calls = 0

        def goto(self, *a, **k):
            ClosedPage.calls += 1
            raise RuntimeError("Page.goto: Target page, context or browser has been closed")

    import pytest
    with pytest.raises(RuntimeError):
        bot.do_browse(ClosedPage(), 30)
    assert ClosedPage.calls == 1
    assert any("trình duyệt đã bị đóng" in m for m in logs)


def test_free_profile_only_kills_true_orphans(tmp_path, monkeypatch):
    import pytest
    from rewards_bot.core import browser
    d = tmp_path / "acc"
    killed = []
    monkeypatch.setattr(browser.subprocess, "run", lambda args, **k: killed.append(args))
    monkeypatch.setattr(browser, "_browser_processes",
                        lambda: [(11, f'msedge.exe --user-data-dir="{d}" --remote-debugging-port=0', True)])
    with pytest.raises(browser.ProfileInUse):  # bot khác đang chạy -> không đóng
        browser.free_profile(d, lambda m: None)
    assert killed == []
    monkeypatch.setattr(browser, "_browser_processes",
                        lambda: [(12, f'msedge.exe --user-data-dir="{d}" --remote-debugging-port=0', False)])
    browser.free_profile(d, lambda m: None)  # chương trình mở nó đã tắt -> mồ côi -> đóng
    assert killed and "12" in killed[0]


def test_unix_process_listing(monkeypatch):
    from rewards_bot.core import browser

    class R:
        stdout = ("    1     0 /sbin/init\n"
                  "  500     1 /opt/microsoft/msedge/msedge --user-data-dir=/x/a --remote-debugging-port=0\n"
                  "  700   650 /usr/bin/python3 -m rewards_bot\n"
                  "  710   700 /opt/microsoft/msedge/msedge --user-data-dir=/x/b --remote-debugging-port=0\n"
                  "  711   710 /opt/microsoft/msedge/msedge --type=renderer\n"
                  "  800   650 /usr/bin/bash\n")
    monkeypatch.setattr(browser.subprocess, "run", lambda *a, **k: R())
    got = {pid: alive for pid, _, alive in browser._unix_browser_processes()}
    assert got == {500: False, 710: True}  # 500 mồ côi (cha là init), 710 có python còn sống; bỏ renderer và bash
