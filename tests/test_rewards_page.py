import json

import pytest

from rewards_bot.core import rewards_page as rp
from conftest import FIXTURES


@pytest.fixture
def items():
    return json.loads((FIXTURES / "rewards_items.json").read_text(encoding="utf-8"))


@pytest.fixture
def state(items):
    st = rp.empty_state()
    rp.parse_page(items["dashboard"], st)
    rp.parse_page(items["earn"], st)
    rp.parse_breakdown(items["breakdown"], st)
    return st


def test_points(state):
    assert state["available"] == 3417
    assert state["today"] == 98  # breakdown ghi đè số ở trang Earn (mới hơn)


def test_daily_set(state):
    assert [(c["title"], c["points"], c["done"]) for c in state["daily"]] == [
        ("Tokyo Early Autumn Glow", 10, True),
        ("Cairns Reef Springtime Clear", 10, False),
        ("Sapphic Flames?", 10, False),
    ]


def test_keep_earning_skips_cards_without_points(state):
    titles = [c["title"] for c in state["more"]]
    assert "New Wallpaper Every Day" not in titles
    assert titles.count("Do you know the answer?") == 2


def test_duplicate_cards_are_numbered(state):
    dups = [(c["title"], c["dup"]) for c in state["more"] if c["title"] == "Do you know the answer?"]
    assert dups == [("Do you know the answer?", 0), ("Do you know the answer?", 1)]
    assert {c["index"] for c in state["more"]} == {20, 21, 22}


def test_quests_are_ignored(state):
    assert "quests" not in state
    assert all(r["group"] != "Quests" for r in rp.build_task_rows(state))


def test_activity_and_icons(state):
    assert rp.activity(state, "bing") == {"title": "Bing – Search", "key": "bing", "progress": 1, "max": 1,
                                          "img": "https://bing.com/th?id=OMR.MicrosoftProducts.Bing.svg&pid=Rewards"}
    assert rp.activity(state, "mobile app")["progress"] == 0
    assert "streak:bing app streak" in state["icons"]


def test_breakdown(state):
    assert state["pc"] == {"progress": 60, "max": 90}
    assert state["mobile"] == {"progress": 0, "max": 60}
    assert state["offers"] == 38
    s = rp.stats(state)
    assert (s["pc"], s["pc_max"], s["mobile"], s["mobile_max"], s["lifetime"]) == (60, 90, 0, 60, 3418)


def test_breakdown_missing_leaves_none():
    st = rp.empty_state()
    rp.parse_breakdown("Points breakdown\nHow it works", st)
    assert st["pc"] is None and st["mobile"] is None


def test_task_rows(state):
    rows = rp.build_task_rows(state)
    groups = [r["group"] for r in rows]
    assert groups[:2] == ["Tìm kiếm", "Tìm kiếm"]
    pc = rows[0]
    assert (pc["title"], pc["progress"], pc["max"], pc["done"]) == ("Search PC", 60, 90, False)
    assert sum(1 for r in rows if r["group"] == "Daily Set" and r["done"]) == 1


def test_points_fallback_from_profile_button():
    st = rp.empty_state()
    rp.parse_page([{"section": "", "tag": "BUTTON", "href": "", "index": -1, "lines": ["12,345", "A"], "img": ""}], st)
    assert st["available"] == 12345
