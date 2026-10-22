"""Lưu mật khẩu: mã hóa DPAPI, không còn chữ thường trong file, giao diện chỉ thấy email."""
import sys

import pytest

from rewards_bot.core import credentials as cr

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="DPAPI chỉ có trên Windows")


def test_roundtrip_and_no_plaintext(tmp_path):
    f = tmp_path / "credentials.json"
    cr.save("namanh", "me@example.com", "S3cret pass ✓", path=f)
    raw = f.read_text(encoding="utf-8")
    assert "S3cret" not in raw and "me@example.com" in raw
    assert not f.with_suffix(".json.bak").exists()
    assert cr.load("namanh", path=f) == ("me@example.com", "S3cret pass ✓")
    assert cr.emails(path=f) == {"namanh": "me@example.com"}
    cr.save("namanh", "me@example.com", "new pass", path=f)  # đổi mật khẩu: không để bản cũ trong .bak
    assert not f.with_suffix(".json.bak").exists() and cr.load("namanh", path=f)[1] == "new pass"


def test_rename_remove_and_bad_input(tmp_path):
    f = tmp_path / "credentials.json"
    cr.save("a", "a@example.com", "pw", path=f)
    cr.rename("a", "b", path=f)
    assert cr.load("a", path=f) is None and cr.load("b", path=f) == ("a@example.com", "pw")
    cr.remove("b", path=f)
    assert cr.emails(path=f) == {}
    for email, pw in (("no-at-sign", "pw"), ("x@y.z", ""), ("x@y.z", "p" * 300)):
        with pytest.raises(ValueError):
            cr.save("c", email, pw, path=f)


def test_tampered_token_is_rejected(tmp_path):
    f = tmp_path / "credentials.json"
    f.write_text('{"a": {"email": "a@example.com", "password": "bm90IGRwYXBp"}}', encoding="utf-8")
    assert cr.load("a", path=f) is None
