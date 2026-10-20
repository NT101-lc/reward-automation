import json

from rewards_bot.core import config


def test_write_json_is_atomic_and_keeps_backup(data_dir):
    f = data_dir / "x.json"
    config.write_json(f, {"v": 1})
    config.write_json(f, {"v": 2})
    assert json.loads(f.read_text(encoding="utf-8")) == {"v": 2}
    assert json.loads((data_dir / "x.json.bak").read_text(encoding="utf-8")) == {"v": 1}
    assert not (data_dir / "x.json.tmp").exists()


def test_read_json_falls_back_to_backup_and_warns(data_dir):
    f = data_dir / "x.json"
    config.write_json(f, {"v": 1})
    config.write_json(f, {"v": 2})
    f.write_text("{corrupt", encoding="utf-8")
    assert config.read_json(f, {}) == {"v": 1}
    assert any("khôi phục" in w for w in config.LOAD_WARNINGS)


def test_read_json_missing_returns_copy_of_default(data_dir):
    default = {"a": []}
    got = config.read_json(data_dir / "none.json", default)
    got["a"].append(1)
    assert default == {"a": []}


def test_old_profiles_get_fixed_dir_on_load(data_dir):
    config.write_json(config.SETTINGS_FILE, {"profiles": [{"name": "nam anh", "mode": "managed", "cdp_port": 9222}]})
    s = config.load_settings()
    assert s["profiles"][0]["dir"] == "nam anh"
    # đã lưu lại migrate
    assert json.loads(config.SETTINGS_FILE.read_text(encoding="utf-8"))["profiles"][0]["dir"] == "nam anh"


def test_profile_dir_uses_fixed_dir_not_name(data_dir):
    p = {"name": "Tên mới", "dir": "namanh"}
    assert config.profile_dir(p) == config.PROFILES_DIR / "namanh"


def test_new_profile_dir_is_unique(data_dir):
    (config.PROFILES_DIR / "acc").mkdir(parents=True)
    assert config.new_profile_dir("acc") == "acc_2"
    assert config.new_profile_dir("acc", taken=["acc_2"]) == "acc_3"
    assert config.new_profile_dir("../../x") == "______x"
