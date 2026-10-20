"""Chỉ cho 1 cửa sổ app (hoặc 1 lần chạy --run-all) hoạt động cùng lúc, tránh 2 nơi tranh nhau 1 profile."""

import contextlib
import os

from .config import LOCK_FILE


class AlreadyRunning(Exception):
    pass


@contextlib.contextmanager
def single_instance():
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    f = open(LOCK_FILE, "a+")
    try:
        if os.name == "nt":
            import msvcrt
            try:
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise AlreadyRunning()
        else:
            import fcntl
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise AlreadyRunning()
        yield
    finally:
        f.close()  # đóng file là nhả khóa (kể cả khi app bị tắt đột ngột)
