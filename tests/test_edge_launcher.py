from rewards_bot.core import edge_launcher as el


def test_args_have_no_automation_flags():
    args = el.build_args(r"C:\Edge\msedge.exe", r"C:\data\profiles\a", headless=False, extra=["--no-proxy-server"])
    joined = " ".join(args)
    for bad in ("--enable-automation", "--disable-background-networking", "--disable-sync", "--disable-extensions",
                "--disable-gpu", "--headless"):
        assert bad not in joined
    assert el.BOT_MARKER in args  # để nhận ra Edge mồ côi của bot
    assert "--remote-debugging-address=127.0.0.1" in args  # cổng debug chỉ nghe trên máy này
    assert "--disable-blink-features=AutomationControlled" in args
    assert "--edge-skip-compat-layer-relaunch" in args
    assert "--no-proxy-server" in args
    assert args[-1] == "about:blank"


def test_headless_hides_window_without_disabling_gpu():
    args = el.build_args("chrome.exe", "d", headless=True)
    assert "--headless=new" in args and "--window-position=-32000,-32000" in args
    assert "--disable-gpu" not in args and "--edge-skip-compat-layer-relaunch" not in args


def test_read_port(tmp_path):
    assert el.read_port(str(tmp_path)) is None
    (tmp_path / "DevToolsActivePort").write_text("51234\n/devtools/browser/abc\n", encoding="utf-8")
    assert el.read_port(str(tmp_path)) == 51234
    (tmp_path / "DevToolsActivePort").write_text("", encoding="utf-8")
    assert el.read_port(str(tmp_path)) is None


def test_headless_uses_normal_user_agent(tmp_path):
    exe = tmp_path / "msedge.exe"
    exe.write_text("")
    (tmp_path / "155.0.4283.62").mkdir()
    (tmp_path / "154.0.1.2").mkdir()
    args = el.build_args(str(exe), "d", headless=True)
    ua = next(a for a in args if a.startswith("--user-agent="))
    assert "Headless" not in ua and "Chrome/155.0.0.0" in ua and ua.endswith("Edg/155.0.0.0")
    assert not any(a.startswith("--user-agent=") for a in el.build_args(str(exe), "d", headless=False))
