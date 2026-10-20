import pytest

pytest.importorskip("webview")

from rewards_bot.core import config  # noqa: E402
from rewards_bot.ui import webapp as W  # noqa: E402


class FakeRunner:
    running = {}

    def is_running(self, name):
        return False

    def start(self, *a, **k):
        pass


@pytest.fixture
def api(data_dir, monkeypatch):
    monkeypatch.setattr(W, "POINTS_HISTORY_FILE", data_dir / "ph.json")
    monkeypatch.setattr(W, "save_settings", lambda s: None)
    a = W.Api.__new__(W.Api)
    a._settings = {"profiles": []}
    a._pstate, a._history = {}, {}
    a._runner = FakeRunner()
    import threading
    a._lock = threading.Lock()
    return a


@pytest.mark.parametrize("key,value,ok", [
    ("max_parallel", 3, True), ("max_parallel", 99, False), ("headless", "yes", False),
    ("browser_channel", "evil", False), ("search_delay_min", True, False), ("bypass_proxy", False, True),
])
def test_setting_validation(key, value, ok):
    if ok:
        assert W._clean_setting(key, value) == value
    else:
        with pytest.raises(ValueError):
            W._clean_setting(key, value)


@pytest.mark.parametrize("profile", [
    {"name": "..\\..\\Windows"}, {"name": "x" * 50}, {"name": "ok", "mode": "evil"},
    {"name": "ok", "mode": "cdp", "cdp_port": 22}, {"name": ""},
])
def test_bad_profiles_rejected(api, profile):
    assert api.save_profile(None, profile)["ok"] is False


def test_new_profile_gets_dir_and_rename_keeps_it(api):
    assert api.save_profile(None, {"name": "nam anh"})["ok"]
    p = api._settings["profiles"][0]
    assert p["dir"] == "nam anh"
    api._history["nam anh"] = {"2026-10-20": {"available": 1}}
    api._pstate["nam anh"] = {"points": 1}
    assert api.save_profile("nam anh", {"name": "Nam Anh chính"})["ok"]
    assert p["name"] == "Nam Anh chính" and p["dir"] == "nam anh"
    assert "Nam Anh chính" in api._history and "nam anh" not in api._history
    assert "Nam Anh chính" in api._pstate


def test_unknown_action_rejected(api):
    assert W.Api.start(api, None, "rm -rf")["ok"] is False
    assert "check" in W.ACTIONS
