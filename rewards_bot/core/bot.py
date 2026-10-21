"""Bot Microsoft Rewards cho MỘT profile. Mỗi profile chạy trong thread riêng với sync_playwright riêng."""

import json
import random
import re
import threading
import time
from urllib.parse import quote_plus, urljoin, urlparse

from playwright.sync_api import sync_playwright, BrowserContext, Page, TimeoutError as PWTimeout

from . import security
from .browser import ProfileInUse, free_profile
from .config import profile_dir
from .rewards_page import (SCRAPE_JS, activity, build_task_rows, empty_state, group_icons, icon, parse_breakdown,
                           parse_page, stats, streak_info)
from ..search.bank import QueryBank
from ..search.catalog import IMAGE_QUERIES

REWARDS = "https://rewards.bing.com"
DASHBOARD_URL = REWARDS + "/dashboard"
EARN_URL = REWARDS + "/earn"
POINTS_PER_SEARCH = 3

# Dùng khi không đọc được phiên bản trình duyệt thật
FALLBACK_VERSIONS = {"chromium": "141.0.7390.55", "edge": "141.0.3537.57"}

# Trang dùng cho task "browse": tin tức / kiến thức, nhiều link nội bộ để lướt tiếp
BROWSE_SITES = [
    "https://www.msn.com/",
    "https://www.bing.com/news",
    "https://en.wikipedia.org/wiki/Special:Random",
    "https://apnews.com/",
    "https://www.nationalgeographic.com/",
    "https://www.theverge.com/",
    "https://www.reuters.com/",
    "https://www.britannica.com/",
    "https://www.bing.com/weather",
    "https://www.howstuffworks.com/",
]


class StopRequested(Exception):
    pass


class NotLoggedIn(Exception):
    pass


class RewardsBot:
    def __init__(self, profile: dict, settings: dict, bank: QueryBank, log, status, stop: threading.Event):
        self.profile = profile
        self.name = profile["name"]
        self.s = settings
        self.bank = bank
        self._log = log          # log(name, msg)
        self._status = status    # status(name, dict)
        self.stop = stop
        self.state = empty_state()
        self.stalled: set = set()  # loại search bị dừng vì không được cộng điểm
        self.local: dict = {}    # task do app tự làm: title -> {"progress","max","unit"}

    # ------------------------------------------------------------ helpers
    def log(self, msg: str) -> None:
        # lỗi Playwright kèm "Call log:" nhiều dòng -> chỉ giữ dòng lỗi chính cho nhật ký gọn
        self._log(self.name, msg.split("\nCall log:")[0].rstrip())

    def status(self, **kw) -> None:
        self._status(self.name, kw)

    def sleep(self, a: float, b: float = None) -> None:
        if self.stop.wait(random.uniform(a, b if b is not None else a)):
            raise StopRequested()

    def check_stop(self) -> None:
        if self.stop.is_set():
            raise StopRequested()

    # task của app -> dòng "Your activity" trên Rewards mà nó nhắm tới (key = tên dòng viết thường)
    LOCAL_TO_ACTIVITY = {"Browse": "edge", "Search ảnh": "visual search"}

    def report(self) -> None:
        """Gửi danh sách task (từ Rewards + task thêm của app) lên giao diện."""
        rows = build_task_rows(self.state)
        local_icons = {"Search ảnh": icon(self.state, "visual search"), "Browse": icon(self.state, "edge", "bing")}
        for title, t in self.local.items():
            bot_note = f"bot: {t['progress']}/{t['max']} {t['unit']}"
            target = activity(self.state, self.LOCAL_TO_ACTIVITY.get(title, ""))
            row = next((r for r in rows if target and r["group"] == "Hoạt động" and r["title"] == target["title"]),
                       None)
            if row:  # cập nhật vào dòng Rewards tương ứng thay vì thêm dòng mới; tiến độ chính vẫn là số của Rewards
                row["bot"] = bot_note
                continue
            rows.append({"group": "Task thêm", "title": title, "progress": t["progress"], "max": t["max"],
                         "unit": t["unit"], "done": t["progress"] >= t["max"], "img": local_icons.get(title, "")})
        self.status(tasks=rows, today=self.state.get("today"), stats=stats(self.state),
                    icons=group_icons(self.state), streak=streak_info(self.state),
                    updated=time.strftime("%H:%M %d/%m"))

    def set_local(self, title: str, progress, total, unit: str) -> None:
        self.local[title] = {"progress": progress, "max": total, "unit": unit}
        self.report()

    # ------------------------------------------------------------ browser
    def _open(self, p, headless: bool) -> BrowserContext:
        if self.profile.get("mode") == "cdp":
            port = security.validate_port(self.profile.get("cdp_port") or 9222)
            if security.cdp_exposed(port):
                raise RuntimeError(f"Cổng debug {port} đang mở ra mạng LAN, máy khác có thể điều khiển trình duyệt. "
                                   "Mở lại Edge chỉ với --remote-debugging-port (không dùng --remote-debugging-address)")
            self.log(f"Gắn vào trình duyệt đang mở ở cổng {port} (chỉ localhost)")
            browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
            return browser.contexts[0] if browser.contexts else browser.new_context()
        d = profile_dir(self.profile)
        d.mkdir(parents=True, exist_ok=True)
        free_profile(d, self.log)  # đóng Edge mồ côi của bot / báo rõ nếu profile đang mở ở cửa sổ khác
        kwargs = dict(user_data_dir=str(d), headless=headless, locale="en-US",
                      viewport={"width": 1280, "height": 800},
                      ignore_https_errors=False,  # luôn kiểm tra chứng chỉ HTTPS, chặn proxy chen giữa giả chứng chỉ
                      args=security.browser_args(self.s))
        if self.s.get("browser_channel"):
            kwargs["channel"] = self.s["browser_channel"]
        if self.s.get("bypass_proxy", True):
            proxy = security.system_proxy()
            if proxy:
                self.log(f"Máy đang bật proxy ({proxy}); trình duyệt của bot bỏ qua proxy này")
        return p.chromium.launch_persistent_context(**kwargs)

    def _close(self, ctx: BrowserContext, own: list) -> None:
        for pg in own:
            try:
                pg.close()
            except Exception:
                pass
        if self.profile.get("mode") != "cdp":
            try:
                ctx.close()
            except Exception:
                pass

    @staticmethod
    def _real_versions(ctx: BrowserContext, cdp) -> dict:
        """Phiên bản Chromium / Edge thật của trình duyệt đang chạy (để giả lập mobile không lệch phiên bản)."""
        for pg in ctx.pages:  # tab desktop đang ở https -> có fullVersionList đầy đủ
            if not pg.url.startswith("https://"):
                continue
            try:
                lst = pg.evaluate("async () => (await navigator.userAgentData.getHighEntropyValues("
                                  "['fullVersionList'])).fullVersionList")
                v = {b["brand"]: b["version"] for b in lst}
                if "Chromium" in v:
                    return {"chromium": v["Chromium"], "edge": v.get("Microsoft Edge")}
            except Exception:
                pass
        try:  # UA rút gọn: chỉ có số phiên bản chính
            ua = cdp.send("Browser.getVersion")["userAgent"]
            v = {"chromium": re.search(r"Chrome/([\d.]+)", ua).group(1)}
            edge = re.search(r"Edg/([\d.]+)", ua)
            v["edge"] = edge.group(1) if edge else None
            return v
        except Exception:
            return dict(FALLBACK_VERSIONS)

    @staticmethod
    def mobile_profile(versions: dict) -> dict:
        """UA + client hints của Edge trên Android, khớp đúng phiên bản trình duyệt thật.

        Bing so sánh User-Agent với Sec-CH-UA-*; nếu lệch (vd UA cũ 129 nhưng full-version-list là 155,
        bitness 64 trên điện thoại) thì search Mobile có thể không được tính cho tài khoản bị soi kỹ.
        """
        chromium, edge = versions["chromium"], versions.get("edge")
        major = chromium.split(".")[0]
        brands = [{"brand": "Chromium", "version": major}, {"brand": "Not(A:Brand", "version": "24"}]
        full = [{"brand": "Chromium", "version": chromium}, {"brand": "Not(A:Brand", "version": "24.0.0.0"}]
        ua = f"Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{major}.0.0.0 Mobile Safari/537.36"
        if edge:
            brands.insert(0, {"brand": "Microsoft Edge", "version": edge.split(".")[0]})
            full.insert(0, {"brand": "Microsoft Edge", "version": edge})
            ua += f" EdgA/{edge.split('.')[0]}.0.0.0"
        else:
            brands.insert(0, {"brand": "Google Chrome", "version": major})
            full.insert(0, {"brand": "Google Chrome", "version": chromium})
        return {
            "userAgent": ua,
            "platform": "Linux armv81",
            "userAgentMetadata": {
                "brands": brands, "fullVersionList": full, "fullVersion": edge or chromium,
                "platform": "Android", "platformVersion": "14.0.0", "architecture": "", "bitness": "",
                "model": "Pixel 8", "mobile": True, "wow64": False,
            },
        }

    @classmethod
    def _emulate_mobile(cls, ctx: BrowserContext, page: Page):
        """Giả lập điện thoại Android cho 1 tab (search Mobile được tính riêng với PC)."""
        cdp = ctx.new_cdp_session(page)
        cdp.send("Emulation.setUserAgentOverride", cls.mobile_profile(cls._real_versions(ctx, cdp)))
        cdp.send("Emulation.setDeviceMetricsOverride",
                 {"width": 412, "height": 915, "deviceScaleFactor": 2.625, "mobile": True})
        cdp.send("Emulation.setTouchEmulationEnabled", {"enabled": True, "maxTouchPoints": 5})
        return cdp

    # ------------------------------------------------------------ đọc trạng thái
    def _load(self, page: Page, url: str, marker: str) -> list:
        """Mở trang Rewards và đợi nội dung chính hiện ra (theo chữ marker hoặc số điểm trong nút hồ sơ)."""
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_function(
                """(m) => document.body && (document.body.innerText.toLowerCase().includes(m.toLowerCase())
                         || !!document.querySelector('button[aria-label="View profile"]'))""",
                arg=marker, timeout=25000)
        except PWTimeout:
            host = urlparse(page.url).netloc
            if "login" in host or "microsoftonline" in host or page.locator("text=Sign in").count():
                raise NotLoggedIn()
            raise RuntimeError(f"Trang {urlparse(url).path} không có mục '{marker}' sau 25 giây "
                               "(mạng chậm hoặc Rewards đã đổi giao diện)")
        self.sleep(1.5, 2.5)
        return page.evaluate(SCRAPE_JS)

    def read_state(self, page: Page) -> dict:
        """Đọc điểm + trạng thái task từ /dashboard và /earn."""
        st = empty_state()
        parse_page(self._load(page, DASHBOARD_URL, "Available points"), st)
        try:  # trang Earn là phần phụ: lỗi thì vẫn chạy tiếp với dữ liệu từ Dashboard
            parse_page(self._load(page, EARN_URL, "Today's points"), st)
            self._read_breakdown(page, st)
        except (StopRequested, NotLoggedIn):
            raise
        except Exception as e:
            self.log(f"cảnh báo: không đọc được trang Earn ({e}); Keep earning và điểm PC/Mobile có thể thiếu")
        self.state = st
        self.status(points=st["available"] if st["available"] is not None else "")
        self.report()
        return st

    def _read_breakdown(self, page: Page, st: dict) -> None:
        """Mở hộp 'Points breakdown' (đang ở /earn) để lấy điểm search PC/Mobile."""
        try:
            page.get_by_role("button", name=re.compile("Points breakdown")).first.click(timeout=8000)
            dlg = page.locator("[role=dialog]").first
            dlg.get_by_text("Desktop Bing search").first.wait_for(timeout=10000)
            parse_breakdown(dlg.inner_text(), st)
            page.keyboard.press("Escape")
        except Exception as e:
            self.log(f"Không đọc được Points breakdown: {e}")

    # ------------------------------------------------------------ làm 1 thẻ task
    def _poll(self, page: Page) -> None:
        self._click(page, f"#btoption{random.randint(0, 1)}", 8000)
        self.sleep(3, 5)

    @staticmethod
    def _click(page: Page, selector: str, timeout: int = 3000) -> bool:
        try:
            page.locator(selector).first.click(timeout=timeout)
            return True
        except Exception:
            return False

    def _quiz(self, page: Page) -> None:
        self._click(page, "#rqStartQuiz", 8000)
        self.sleep(2, 4)
        for _ in range(30):
            self.check_stop()
            if page.locator("#quizCompleteContainer").count():
                break
            options = page.locator("[id^='rqAnswerOption']")
            n = options.count()
            if n == 0:
                if not self._click(page, "[id^='questionOptionChoice']"):
                    break
                self.sleep(2, 3)
                self._click(page, "[id^='nextQuestionbtn']")
                self.sleep(2, 3)
                continue
            clicked = False
            for i in range(n):
                opt = options.nth(i)
                try:
                    if opt.get_attribute("iscorrectoption") == "True" and opt.is_visible():
                        opt.click(timeout=3000)
                        clicked = True
                        self.sleep(2, 4)
                except Exception:
                    pass
            if not clicked:
                try:
                    options.nth(random.randrange(n)).click(timeout=3000)
                except Exception:
                    pass
                self.sleep(2, 4)

    def _interact(self, tab: Page) -> None:
        """Thao tác trên trang task vừa mở: poll / quiz nếu có, không thì đọc và cuộn trang."""
        self.sleep(4, 7)
        if tab.locator("#btoption0").count():
            self._poll(tab)
        elif tab.locator("#rqStartQuiz, [id^='rqAnswerOption'], [id^='questionOptionChoice']").count():
            self._quiz(tab)
        else:
            for _ in range(random.randint(2, 4)):
                tab.mouse.wheel(0, random.randint(300, 800))
                self.sleep(2, 4)

    @staticmethod
    def _card_locator(page: Page, card: dict):
        """Đúng thẻ cần bấm: ưu tiên theo vị trí (kiểm tra tiêu đề khớp), không thì thẻ thứ n cùng tiêu đề + link."""
        if card.get("index", -1) >= 0:
            loc = page.locator("a").nth(card["index"])
            try:
                if loc.inner_text(timeout=3000).split("\n")[0].strip() == card["title"]:
                    return loc
            except Exception:
                pass
        return page.locator(f"a[href={json.dumps(card['href'])}]", has_text=card["title"]).nth(card.get("dup", 0))

    def _open_card(self, page: Page, card: dict) -> None:
        """Bấm thẻ task trên trang Rewards (mở tab mới), làm task, rồi đóng tab."""
        href = card["href"]
        link = self._card_locator(page, card)
        tab = None
        try:
            with page.context.expect_page(timeout=15000) as info:
                link.click(timeout=10000)
            tab = info.value
            tab.wait_for_load_state("domcontentloaded", timeout=30000)
        except PWTimeout:
            # thẻ không mở tab mới -> mở trực tiếp
            tab = page.context.new_page()
            tab.goto(urljoin(REWARDS, href), wait_until="domcontentloaded", timeout=30000)
        try:
            self._interact(tab)
        finally:
            try:
                tab.close()
            except Exception:
                pass

    # ------------------------------------------------------------ các nhóm task
    def do_cards(self, page: Page) -> None:
        """Daily Set + Keep earning."""
        for group, key, url, marker in (("Daily Set", "daily", DASHBOARD_URL, "Available points"),
                                        ("Keep earning", "more", EARN_URL, "Today's points")):
            todo = [c for c in self.state.get(key, []) if not c["done"]]
            self.log(f"{group}: {len(todo)} task chưa làm")
            for i, c in enumerate(todo, 1):
                self.check_stop()
                self.status(progress=f"{group} {i}/{len(todo)}")
                self.log(f"  {group}: {c['title']} (+{c['points']})")
                try:
                    self._load(page, url, marker)
                    self._open_card(page, c)
                except (StopRequested, NotLoggedIn):
                    raise
                except Exception as e:
                    self.log(f"  lỗi task: {e}")
                self.sleep(2, 4)

    # Điểm Rewards mà bing.com hiển thị ở góc phải header = điểm của tài khoản đang đăng nhập trên bing.com
    BING_POINTS_JS = r"""() => Array.from(document.querySelectorAll('#id_h *, #rewid *, .id_button *'))
        .map(e => e.textContent.trim()).filter(x => /^[\d,]{2,}$/.test(x)).map(x => +x.replace(/,/g, ''))"""

    def bing_account_check(self, page: Page) -> tuple:
        """(level, chi tiết): bing.com có đăng nhập đúng tài khoản Rewards không. level: ok / warn / fail."""
        rewards_pts = self.state.get("available")
        try:
            page.goto("https://www.bing.com/", wait_until="domcontentloaded", timeout=30000)
            self.sleep(4, 6)
            pts = page.evaluate(self.BING_POINTS_JS)
        except (StopRequested, NotLoggedIn):
            raise
        except Exception as e:
            return "warn", f"không mở được bing.com để đối chiếu ({e})"
        if not pts or rewards_pts is None:
            return "warn", "không đọc được điểm trên bing.com để đối chiếu tài khoản"
        if abs(pts[0] - rewards_pts) > 200:
            return "fail", (f"bing.com đang đăng nhập tài khoản khác ({pts[0]:,} điểm, Rewards là {rewards_pts:,}). "
                            "Search sẽ cộng điểm cho tài khoản kia. Bấm Đăng nhập, đăng xuất ở tab bing.com "
                            "rồi đăng nhập lại đúng tài khoản")
        return "ok", f"cùng tài khoản ({pts[0]:,} điểm)"

    def bing_account_ok(self, page: Page) -> bool:
        level, detail = self.bing_account_check(page)
        if level == "fail":
            self.log("Lỗi: " + detail + ". Bot bỏ qua phần search.")
            return False
        self.log(("bing.com " + detail) if level == "ok" else ("cảnh báo: " + detail + ", vẫn tiếp tục"))
        return True

    CHECK_EVERY = 3   # cứ bao nhiêu lượt search thì đọc lại điểm
    STALL_AFTER = 6   # bao nhiêu lượt liên tiếp không được cộng điểm thì dừng

    # số lượt mặc định khi không đọc được Points breakdown (90 điểm PC, 60 điểm Mobile / 3 điểm mỗi lượt)
    FALLBACK_SEARCHES = {"pc": 30, "mobile": 20}

    def searches_needed(self, kind: str):
        """Số lượt search còn thiếu cho 'pc' / 'mobile' theo Points breakdown (3 điểm/lượt); None = không rõ."""
        c = self.state.get(kind)
        if c:
            return max(0, -(-(c["max"] - c["progress"]) // POINTS_PER_SEARCH))
        return None

    def _recheck(self, check_page: Page, kind: str):
        """Đọc lại breakdown trên tab desktop để cập nhật dashboard; trả về dict progress/max hoặc None."""
        try:
            self._load(check_page, EARN_URL, "Today's points")
            self._read_breakdown(check_page, self.state)
            self.report()
            return self.state.get(kind)
        except (StopRequested, NotLoggedIn):
            raise
        except Exception as e:
            self.log(f"  không kiểm tra được điểm: {e}")
            return None

    def do_searches(self, page: Page, kind: str, label: str, check_page: Page = None) -> None:
        check_page = check_page or page
        need = self.searches_needed(kind)
        if need is None:
            self.log(f"{label}: không đọc được Points breakdown, thử lại...")
            self._recheck(check_page, kind)
            need = self.searches_needed(kind)
            if need is None:
                need = self.FALLBACK_SEARCHES[kind]
                self.log(f"{label}: vẫn không đọc được, dùng mặc định {need} lượt")
        if need <= 0:
            self.log(f"{label}: đã đủ điểm search")
            return
        count = need + int(self.s.get("extra_searches", 0))
        cur = self.state.get(kind) or {}
        self.log(f"{label}: {count} lượt search (đang {cur.get('progress', '?')}/{cur.get('max', '?')} điểm)")
        last_progress, last_gain_at = cur.get("progress"), 0
        for i in range(count):
            self.check_stop()
            if i and i % self.CHECK_EVERY == 0:  # đọc lại điểm định kỳ
                c = self._recheck(check_page, kind)
                if c:
                    self.log(f"  {label}: {c['progress']}/{c['max']} điểm")
                    if c["progress"] >= c["max"]:
                        self.log(f"{label}: đã đủ điểm, dừng sớm")
                        return
                    if last_progress is None or c["progress"] > last_progress:
                        last_progress, last_gain_at = c["progress"], i
                    elif i - last_gain_at >= self.STALL_AFTER:
                        self._stall(kind, label, f"sau {i - last_gain_at} lượt liên tiếp", c)
                        return
            self.status(progress=f"{label} {i + 1}/{count}")
            self._search_once(page, f"{label} {i + 1}/{count}")
            self.sleep(self.s["search_delay_min"], self.s["search_delay_max"])

    def _search_once(self, page: Page, tag: str) -> None:
        q = self.bank.take(self.name)
        try:
            page.goto(f"https://www.bing.com/search?q={quote_plus(q)}&form=QBLH",
                      wait_until="domcontentloaded", timeout=30000)
            page.mouse.wheel(0, random.randint(200, 1200))
        except Exception as e:
            self.log(f"  lỗi khi tìm '{q}': {e}")
        self.log(f"  [{tag}] {q}")

    def _stall(self, kind: str, label: str, why: str, c: dict) -> None:
        self.log(f"Lỗi: {label} không được cộng điểm {why} (đứng ở {c['progress']}/{c['max']}), dừng {label}. "
                 "Nguyên nhân thường gặp: bing.com đăng nhập sai tài khoản (bấm Kiểm tra), hoặc Microsoft tạm "
                 "không tính search cho tài khoản này.")
        self.stalled.add(kind)

    @staticmethod
    def new_bing_session(ctx: BrowserContext) -> None:
        """Xóa cookie phiên search của Bing (không đụng cookie đăng nhập).

        Bing gắn loại thiết bị theo phiên: search Mobile trong phiên đã search PC bị tính là PC (+0 khi PC đã đủ).
        """
        ctx.clear_cookies(name=re.compile(r"^(_SS|_EDGE_S|_Rwho)$"), domain=re.compile(r"bing\.com$"))

    def do_image_searches(self, page: Page, count: int) -> None:
        row = activity(self.state, "visual search")
        if row and row["progress"] >= row["max"]:
            self.log("Visual Search: đã đủ")
            return
        title = "Search ảnh"
        self.log(f"{title}: {count} lượt trên Bing Images")
        self.set_local(title, 0, count, "lượt")
        for i in range(count):
            self.check_stop()
            q = random.choice(IMAGE_QUERIES)  # câu có hình để xem, không lấy bộ câu kiến thức của search chữ
            self.status(progress=f"Ảnh {i + 1}/{count}")
            try:
                page.goto(f"https://www.bing.com/images/search?q={quote_plus(q)}&form=HDRSC2&first=1",
                          wait_until="domcontentloaded", timeout=30000)
                self.sleep(2, 4)
                page.mouse.wheel(0, random.randint(400, 1500))
                thumbs = page.locator("a.iusc")
                if thumbs.count():
                    thumbs.nth(random.randrange(min(thumbs.count(), 10))).click(timeout=5000)
                    self.sleep(3, 6)
                    page.keyboard.press("Escape")
            except StopRequested:
                raise
            except Exception as e:
                self.log(f"  lỗi khi tìm ảnh '{q}': {e}")
            self.log(f"  [Ảnh {i + 1}/{count}] {q}")
            self.set_local(title, i + 1, count, "lượt")
            self.sleep(self.s["search_delay_min"], self.s["search_delay_max"])

    def do_browse(self, page: Page, minutes: int) -> None:
        title = "Browse"
        total = minutes * 60
        start = time.time()
        self.log(f"{title}: lướt web trong {minutes} phút")
        self.set_local(title, 0, minutes, "phút")
        blocked: set = set()  # trang không kết nối được (vd mạng chặn bằng DNS) -> bỏ qua trong lượt này

        def pick_site() -> str:
            ok = [u for u in BROWSE_SITES if urlparse(u).netloc not in blocked]
            return random.choice(ok or BROWSE_SITES)

        url = pick_site()
        while (elapsed := time.time() - start) < total:
            self.check_stop()
            self.status(progress=f"Browse {int(elapsed // 60)}/{minutes} phút")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                for _ in range(random.randint(3, 6)):
                    page.mouse.wheel(0, random.randint(250, 700))
                    self.sleep(4, 12)
                    if time.time() - start >= total:
                        break
                links = page.evaluate(
                    "() => Array.from(document.querySelectorAll('a[href]')).map(a => a.href)"
                    ".filter(h => h.startsWith('http')).slice(0, 200)")
                host = urlparse(page.url).netloc
                same = [h for h in links if urlparse(h).netloc == host and h.split('#')[0] != page.url]
                url = random.choice(same) if same and random.random() < 0.7 else pick_site()
            except StopRequested:
                raise
            except Exception as e:
                if "has been closed" in str(e):  # trình duyệt / tab bị đóng giữa chừng: dừng hẳn, không lặp lỗi
                    self.log(f"Lỗi: trình duyệt đã bị đóng, dừng {title}")
                    raise
                host = urlparse(url).netloc
                if "net::ERR_" in str(e) and host not in blocked:
                    blocked.add(host)
                    self.log(f"  không vào được {host} (mạng chặn hoặc trang lỗi), bỏ qua trang này")
                else:
                    self.log(f"  lỗi browse: {e}")
                url = pick_site()
                self.sleep(2, 4)
            self.set_local(title, min(minutes, int((time.time() - start) // 60)), minutes, "phút")
        self.set_local(title, minutes, minutes, "phút")
        self.log(f"{title}: xong {minutes} phút")

    # ------------------------------------------------------------ entry points
    def _session(self, work, headless: bool, label: str) -> None:
        """Mở trình duyệt, chạy work(ctx, page, own), xử lý lỗi chung."""
        own = []
        try:
            with sync_playwright() as p:
                ctx = self._open(p, headless)
                try:
                    if self.profile.get("mode") != "cdp" and ctx.pages:
                        page = ctx.pages[0]
                    else:
                        page = ctx.new_page()
                        own.append(page)
                    work(ctx, page, own)
                finally:
                    self._close(ctx, own)
        except StopRequested:
            self.status(state="Đã dừng", progress="")
            self.log(f"{label}: đã dừng theo yêu cầu")
        except NotLoggedIn:
            self.status(state="Chưa đăng nhập", progress="Bấm Đăng nhập")
            self.log("Chưa đăng nhập Microsoft Rewards cho profile này")
        except ProfileInUse as e:
            self.status(state="Lỗi", progress="Profile đang mở ở cửa sổ khác")
            self.log(f"Lỗi: {e}")
        except Exception as e:
            self.status(state="Lỗi", progress=str(e)[:60])
            self.log(f"Lỗi: {e}")

    def login(self) -> None:
        if self.profile.get("mode") == "cdp":
            self.log("Profile CDP: hãy đăng nhập trực tiếp trên trình duyệt đang mở của bạn")
            return
        self.status(state="Đang đăng nhập", progress="Đóng cửa sổ khi xong")
        with sync_playwright() as p:
            ctx = self._open(p, headless=False)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(DASHBOARD_URL)
            bing = ctx.new_page()
            bing.goto("https://www.bing.com/")
            page.bring_to_front()
            self.log("Đăng nhập tài khoản Microsoft ở tab Rewards, rồi sang tab bing.com kiểm tra góc phải: "
                     "phải là CÙNG tài khoản (nếu khác thì đăng xuất và đăng nhập lại). Xong thì đóng cửa sổ.")
            while not self.stop.is_set() and ctx.pages:
                try:
                    ctx.pages[0].wait_for_timeout(1000)
                except Exception:
                    if not ctx.pages:
                        break
            try:
                ctx.close()
            except Exception:
                pass
        self.status(state="Sẵn sàng", progress="")
        self.log("Đã lưu phiên đăng nhập")

    def diagnose(self) -> list:
        """Nút Kiểm tra: chạy các bước kiểm tra, KHÔNG search. Trả về [{level, title, detail}]."""
        results = []

        def add(level, title, detail):
            results.append({"level": level, "title": title, "detail": detail})
            self.log(f"[Kiểm tra] {'OK' if level == 'ok' else level.upper()} – {title}: {detail}")

        proxy = security.system_proxy()
        if proxy:
            add("ok" if self.s.get("bypass_proxy", True) else "warn", "Proxy hệ thống",
                f"đang bật ({proxy}); " + ("bot bỏ qua proxy này" if self.s.get("bypass_proxy", True)
                                         else "bot ĐANG đi qua proxy này (bật lại tùy chọn trong Cài đặt)"))
        else:
            add("ok", "Proxy hệ thống", "không có")

        def work(ctx, page, own):
            add("ok", "Mở trình duyệt", "profile không bị chương trình khác giữ")
            try:
                st = self.read_state(page)
            except NotLoggedIn:
                add("fail", "Đăng nhập rewards.bing.com", "chưa đăng nhập. Bấm Đăng nhập")
                return
            add("ok", "Đăng nhập rewards.bing.com", f"{st['available']:,} điểm, hôm nay +{st.get('today') or 0}")
            pc, mob = st.get("pc"), st.get("mobile")
            if pc and mob:
                add("ok", "Points breakdown", f"PC {pc['progress']}/{pc['max']}, Mobile {mob['progress']}/{mob['max']}")
            else:
                add("warn", "Points breakdown", "không đọc được; bot sẽ dùng số lượt search mặc định")
            n_daily, n_more = len(st["daily"]), len(st["more"])
            add("ok" if n_daily else "warn", "Daily Set / Keep earning",
                f"{n_daily} thẻ Daily Set, {n_more} thẻ Keep earning" if n_daily
                else "không thấy thẻ Daily Set nào (có thể Rewards đổi giao diện)")
            level, detail = self.bing_account_check(page)
            add(level, "Tài khoản trên bing.com", detail)
            m = ctx.new_page()
            own.append(m)
            self._emulate_mobile(ctx, m)
            m.goto("https://www.bing.com/", wait_until="domcontentloaded", timeout=30000)
            self.sleep(3, 4)
            signed = any(c["name"] == "_U" for c in ctx.cookies("https://www.bing.com"))
            prompt = m.locator("a[href*='login.live.com'], #mb_signin").count() > 0
            add("ok" if signed and not prompt else "fail", "bing.com trên giao diện Mobile",
                "đã đăng nhập" if signed and not prompt else "chưa đăng nhập: search Mobile sẽ không được tính")

        self.status(state="Đang kiểm tra", progress="")
        self._session(work, headless=True, label="Kiểm tra")
        if self.profile.get("mode") == "cdp":
            add("ok", "Cổng debug", f"chỉ localhost (cổng {self.profile.get('cdp_port')})")
        if not any(r["title"] == "Mở trình duyệt" for r in results):
            add("fail", "Mở trình duyệt", "không mở được profile (xem dòng lỗi phía trên trong nhật ký)")
        worst = "fail" if any(r["level"] == "fail" for r in results) else                 "warn" if any(r["level"] == "warn" for r in results) else "ok"
        self.status(check=results, check_time=time.strftime("%H:%M %d/%m"),
                    state={"ok": "Sẵn sàng", "warn": "Sẵn sàng", "fail": "Lỗi"}[worst],
                    progress={"ok": "Kiểm tra: tất cả OK", "warn": "Kiểm tra: có cảnh báo",
                              "fail": "Kiểm tra: có lỗi"}[worst])
        return results

    def refresh(self) -> None:
        """Chỉ đọc điểm và trạng thái task, không làm gì."""
        def work(ctx, page, own):
            self.status(state="Đang làm mới", progress="")
            st = self.read_state(page)
            self.status(state="Sẵn sàng", progress="")
            self.log(f"Đã cập nhật: {st['available']} điểm, hôm nay {st['today']}")
        self._session(work, headless=True, label="Làm mới")

    def run(self) -> None:
        def work(ctx, page, own):
            self.status(state="Đang chạy", progress="Khởi động")
            start = self.read_state(page)["available"] or 0
            self.status(start=start)
            self.log(f"Điểm hiện tại: {start}")

            if self.s.get("do_quests", True):  # Daily Set + Keep earning
                self.do_cards(page)
                st = self.read_state(page)
                missed = [c["title"] for c in st["daily"] + st["more"] if not c["done"]]
                if missed:
                    self.log("cảnh báo: các thẻ chưa được Rewards ghi nhận sau khi làm: " + "; ".join(missed))
            wants_search = any(self.s.get(k, d) for k, d in (("do_pc", True), ("do_mobile", True), ("do_images", True)))
            account_ok = self.bing_account_ok(page) if wants_search else True
            if account_ok:
                if self.s.get("do_pc", True):
                    self.do_searches(page, "pc", "Search PC")
                if self.s.get("do_mobile", True):
                    self.new_bing_session(ctx)
                    mpage = ctx.new_page()
                    own.append(mpage)
                    self._emulate_mobile(ctx, mpage)
                    self.do_searches(mpage, "mobile", "Search Mobile", check_page=page)
                    mpage.close()
                    own.remove(mpage)
                    self.new_bing_session(ctx)  # search ảnh / browse sau đó lại là PC
                if self.s.get("do_pc", True) or self.s.get("do_mobile", True):
                    self.read_state(page)
                if self.s.get("do_images", True):
                    self.do_image_searches(page, int(self.s.get("image_searches", 6)))
            if self.s.get("do_browse", False):
                self.do_browse(page, int(self.s.get("browse_minutes", 30)))

            end = self.read_state(page)["available"] or start
            self.log(f"Xong! {start} -> {end} (+{end - start})")
            if not account_ok:
                self.status(state="Lỗi", progress="bing.com đăng nhập sai tài khoản")
            elif self.stalled:
                names = ", ".join({"pc": "PC", "mobile": "Mobile"}[k] for k in sorted(self.stalled))
                self.status(state="Lỗi", progress=f"+{end - start} · Search {names} không được cộng điểm")
            else:
                self.status(state="Hoàn thành", progress=f"+{end - start}")
        self._session(work, bool(self.s.get("headless")), label="Chạy")
