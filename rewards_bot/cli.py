"""Chạy tất cả profile không mở giao diện (dùng cho Task Scheduler)."""

import threading
import time

from .core import security
from .core.config import DATA_DIR, HISTORY_FILE, load_settings
from .core.runner import Runner
from .search.bank import QueryBank


def run_cli(headless: bool) -> None:
    security.harden_data_dir(DATA_DIR)
    settings = load_settings()
    if headless:
        settings["headless"] = True
    bank = QueryBank(HISTORY_FILE, int(settings.get("history_days", 30)))
    bank.generate(60)
    finished = threading.Event()
    left = {p["name"] for p in settings["profiles"]}

    def done(name):
        left.discard(name)
        if not left:
            finished.set()

    runner = Runner(bank,
                    log=lambda n, m: print(f"[{time.strftime('%H:%M:%S')}] [{n}] {m}", flush=True),
                    status=lambda n, d: None, done=done)
    runner.start(settings["profiles"], settings)
    try:
        while not finished.wait(1):
            pass
    except KeyboardInterrupt:
        runner.stop()
        finished.wait(30)
