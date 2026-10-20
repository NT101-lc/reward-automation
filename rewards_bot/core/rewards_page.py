"""Đọc trạng thái từ giao diện Microsoft Rewards mới (rewards.bing.com/dashboard và /earn).

Trang mới không còn API JSON công khai; dữ liệu được lấy từ các thẻ (link/nút) trên trang,
nhóm theo tiêu đề H2 của từng mục: "Daily set", "Your activity", "Keep earning"...
"""

import re

SCRAPE_JS = r"""
() => {
  const out = [];
  let section = '';
  const anchors = Array.from(document.querySelectorAll('a'));
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT);
  let n;
  while ((n = walker.nextNode())) {
    if (n.tagName === 'H2') section = n.innerText.trim();
    if (n.tagName !== 'A' && n.tagName !== 'BUTTON') continue;
    const lines = (n.innerText || '').split('\n').map(s => s.trim()).filter(Boolean);
    if (!lines.length) continue;
    const img = n.querySelector('img');
    out.push({section, tag: n.tagName, href: n.getAttribute('href') || '',
              index: n.tagName === 'A' ? anchors.indexOf(n) : -1, lines,
              img: img ? (img.currentSrc || img.src || '') : ''});
  }
  return out;
}
"""

_NUM = re.compile(r"^\+?[\d,]+$")


def _num(s: str) -> int:
    return int(re.sub(r"[^\d]", "", s) or 0)


def _card(item: dict) -> dict:
    """Thẻ task dạng: [tiêu đề, mô tả, điểm, 'Completed'?]."""
    lines = item["lines"]
    nums = [_num(l) for l in lines if _NUM.match(l)]
    return {"title": lines[0], "points": nums[-1] if nums else 0,
            "done": any(l.lower() == "completed" for l in lines),
            "href": item["href"], "index": item["index"], "img": item.get("img", "")}


def parse_page(items: list, state: dict) -> dict:
    """Gộp dữ liệu từ 1 trang vào state."""
    for it in items:
        sec = it["section"].lower()
        lines = it["lines"]
        text = " ".join(lines)
        href = it["href"]

        if lines[0] == "Available points" and len(lines) > 1:
            state["available"] = _num(lines[1])
        elif lines[0] == "Today's points" and len(lines) > 1:
            state["today"] = _num(lines[1])
        elif sec == "daily set" and it["tag"] == "A":
            state["daily"].append(_card(it))
        elif sec == "keep earning" and it["tag"] == "A" and href.startswith("http"):
            c = _card(it)
            if c["points"]:  # bỏ các thẻ quảng cáo không có điểm
                state["more"].append(c)
        elif sec == "your activity" and it["tag"] == "BUTTON":
            m = re.search(r"(\d+)\s*/\s*(\d+)", text)
            if m:
                label = lines[1].split(":")[0] if len(lines) > 1 else ""
                state["activity"].append({"title": f"{lines[0]} – {label}".strip(" –"), "key": lines[0].lower(),
                                          "progress": int(m.group(1)), "max": int(m.group(2)),
                                          "img": it.get("img", "")})
                if it.get("img"):
                    state["icons"].setdefault(lines[0].lower(), it["img"])
        elif sec == "streaks" and it.get("img"):
            state["icons"].setdefault("streak:" + lines[0].lower(), it["img"])
    # thẻ trùng tiêu đề + link (vd 2 thẻ "Do you know the answer?") -> đánh số để bấm đúng thẻ thứ n
    for key in ("daily", "more"):
        seen = {}
        for c in state[key]:
            k = (c["title"], c["href"])
            c["dup"] = seen.get(k, 0)
            seen[k] = c["dup"] + 1
    # profile button "3,417 D" làm dự phòng cho số điểm
    if state.get("available") is None:
        for it in items:
            if it["tag"] == "BUTTON" and it["lines"] and _NUM.match(it["lines"][0]):
                state["available"] = _num(it["lines"][0])
                break
    return state


def parse_breakdown(text: str, state: dict) -> dict:
    """Hộp 'Points breakdown' ở /earn: điểm search PC/Mobile, Offers, tổng tháng/năm/trọn đời."""
    lines = [l.strip() for l in text.split("\n") if l.strip()]

    def after(label):
        for i, l in enumerate(lines[:-1]):
            if l.lower() == label:
                return lines[i + 1]
        return None

    for key, label in (("pc", "desktop bing search"), ("mobile", "mobile bing search")):
        v = after(label)
        m = re.match(r"([\d,]+)\s*/\s*([\d,]+)", v or "")
        if m:
            state[key] = {"progress": _num(m.group(1)), "max": _num(m.group(2))}
    for key, label in (("offers", "offers"), ("today", "today's points"), ("month", "this month"),
                       ("year", "this year"), ("lifetime", "lifetime")):
        v = after(label)
        if v and _NUM.match(v):
            state[key] = _num(v)
    return state


def stats(state: dict) -> dict:
    """Số liệu gọn để lưu lịch sử và vẽ biểu đồ."""
    pc, mob = state.get("pc") or {}, state.get("mobile") or {}
    return {"available": state.get("available"), "today": state.get("today"),
            "pc": pc.get("progress"), "pc_max": pc.get("max"),
            "mobile": mob.get("progress"), "mobile_max": mob.get("max"),
            "offers": state.get("offers"), "month": state.get("month"), "lifetime": state.get("lifetime")}


def empty_state() -> dict:
    return {"available": None, "today": None, "daily": [], "more": [], "activity": [],
            "pc": None, "mobile": None, "offers": None, "icons": {}}


def icon(state: dict, *keys: str) -> str:
    """Icon đầu tiên tìm thấy theo các khóa (vd 'bing', 'streak:bing app streak')."""
    icons = (state or {}).get("icons") or {}
    return next((icons[k] for k in keys if icons.get(k)), "")


def activity(state: dict, key: str):
    """Tìm dòng 'Your activity' theo tên (vd 'bing', 'visual search')."""
    return next((a for a in state.get("activity", []) if a["key"] == key), None)


def build_task_rows(state: dict) -> list:
    """Chuyển state thành danh sách task để hiển thị trên dashboard."""
    rows = []
    if not state:
        return rows
    search_icons = {"pc": icon(state, "streak:bing search streak", "bing"),
                    "mobile": icon(state, "streak:bing app streak", "mobile app", "bing")}
    for key, title in (("pc", "Search PC"), ("mobile", "Search Mobile")):
        c = state.get(key)
        if c:
            rows.append({"group": "Tìm kiếm", "title": title, "progress": c["progress"], "max": c["max"],
                         "done": c["max"] > 0 and c["progress"] >= c["max"], "img": search_icons[key]})
    for c in state.get("daily", []):
        rows.append({"group": "Daily Set", "title": c["title"], "progress": c["points"] if c["done"] else 0,
                     "max": c["points"], "done": c["done"], "img": c.get("img", "")})
    for c in state.get("more", []):
        rows.append({"group": "Keep earning", "title": c["title"], "progress": c["points"] if c["done"] else 0,
                     "max": c["points"], "done": c["done"], "img": c.get("img", "")})
    for a in state.get("activity", []):
        rows.append({"group": "Hoạt động", "title": a["title"], "progress": a["progress"], "max": a["max"],
                     "unit": "lượt", "done": a["progress"] >= a["max"], "img": a.get("img", "")})
    return rows


def group_icons(state: dict) -> dict:
    """Icon cho từng nhóm task trên dashboard."""
    return {"Tìm kiếm": icon(state, "bing"), "Daily Set": icon(state, "daily set"),
            "Hoạt động": icon(state, "streak:daily set streak", "daily set"),
            "Keep earning": icon(state, "streak:visual search streak"),
            "Visual Search": icon(state, "visual search"), "Mobile": icon(state, "mobile app")}
