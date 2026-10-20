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
    bot, logs = make_bot(slow_minutes=0)
    bot.state = empty_state()
    bot.state["mobile"] = {"progress": 24, "max": 60}
    bot._recheck = lambda page, kind: {"progress": 24, "max": 60}  # không bao giờ tăng
    page = FakePage()
    bot.do_searches(page, "mobile", "Search Mobile")
    assert "mobile" in bot.stalled
    assert len(page.visits) == bot.STALL_AFTER  # dừng sau đúng số lượt không được cộng
    assert any("không được cộng điểm" in m for m in logs)


def test_slow_mode_after_stall_until_full():
    bot, logs = make_bot(slow_minutes=15)
    bot.state = empty_state()
    bot.state["mobile"] = {"progress": 36, "max": 60}
    seq = iter([36, 36, 39, 39, 42, 45, 48, 51, 54, 57, 60])  # search nhanh: đứng yên; chế độ chậm: lúc tăng lúc không
    bot._recheck = lambda page, kind: {"progress": next(seq), "max": 60}
    page = FakePage()
    bot.do_searches(page, "mobile", "Search Mobile")
    assert not bot.stalled
    assert any("chế độ chậm" in m for m in logs)
    assert len(page.visits) == bot.STALL_AFTER + 9


def test_slow_mode_when_few_searches_left_get_nothing():
    bot, logs = make_bot(slow_minutes=15)
    bot.state = empty_state()
    bot.state["mobile"] = {"progress": 48, "max": 60}  # chỉ 4 lượt: không kịp chạm STALL_AFTER
    seq = iter([48, 48, 51, 54, 57, 60])
    bot._recheck = lambda page, kind: {"progress": next(seq), "max": 60}
    page = FakePage()
    bot.do_searches(page, "mobile", "Search Mobile")
    assert not bot.stalled
    assert len(page.visits) == 4 + 4


def test_slow_mode_gives_up():
    bot, logs = make_bot(slow_minutes=15)
    bot.state = empty_state()
    bot.state["mobile"] = {"progress": 36, "max": 60}
    bot._recheck = lambda page, kind: {"progress": 36, "max": 60}
    page = FakePage()
    bot.do_searches(page, "mobile", "Search Mobile")
    assert "mobile" in bot.stalled
    assert len(page.visits) == bot.STALL_AFTER + bot.SLOW_GIVE_UP


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
