"""Bot Microsoft Rewards cho MỘT profile. Mỗi profile chạy trong thread riêng với sync_playwright riêng."""

import json
import random
import re
import threading
import time
from urllib.parse import quote_plus, urljoin, urlparse

from playwright.sync_api import sync_playwright, BrowserContext, Page, TimeoutError as PWTimeout

from . import security
from .config import profile_dir
from .rewards_page import (SCRAPE_JS, activity, build_task_rows, empty_state, group_icons, icon, parse_breakdown,
                           parse_page, stats)
from ..search.bank import QueryBank

REWARDS = "https://rewards.bing.com"
DASHBOARD_URL = REWARDS + "/dashboard"
EARN_URL = REWARDS + "/earn"
POINTS_PER_SEARCH = 3

MOBILE_UA = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0.0.0 Mobile Safari/537.36 EdgA/129.0.0.0"
)

# Trang dùng cho task "browse": tin tức / kiến thức, nhiều link nội bộ để lướt tiếp
BROWSE_SITES = [
    "https://www.msn.com/",
    "https://www.bing.com/news",
    "https://en.wikipedia.org/wiki/Special:Random",
    "https://www.bbc.com/news",
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
        self.local: dict = {}    # task do app tự làm: title -> {"progress","max","unit"}

    # ------------------------------------------------------------ helpers
    def log(self, msg: str) -> None:
        self._log(self.name, msg)

    def status(self, **kw) -> None:
        self._status(self.name, kw)

    def sleep(self, a: float, b: float = None) -> None:
        if self.stop.wait(random.uniform(a, b if b is not None else a)):
            raise StopRequested()

    def check_stop(self) -> None:
        if self.stop.is_set():
            raise StopRequested()

    def report(self) -> None:
        """Gửi danh sách task (từ Rewards + task thêm của app) lên giao diện."""
        rows = build_task_rows(self.state)
        local_icons = {"Search ảnh": icon(self.state, "visual search"), "Browse": icon(self.state, "bing")}
        for title, t in self.local.items():
            rows.append({"group": "Task thêm", "title": title, "progress": t["progress"], "max": t["max"],
                         "unit": t["unit"], "done": t["progress"] >= t["max"], "img": local_icons.get(title, "")})
        self.status(tasks=rows, today=self.state.get("today"), stats=stats(self.state),
                    icons=group_icons(self.state), updated=time.strftime("%H:%M %d/%m"))

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
    def _emulate_mobile(ctx: BrowserContext, page: Page):
        """Giả lập điện thoại Android cho 1 tab (search Mobile được tính riêng với PC)."""
        cdp = ctx.new_cdp_session(page)
        cdp.send("Emulation.setUserAgentOverride", {
            "userAgent": MOBILE_UA,
            "platform": "Linux armv8l",
            "userAgentMetadata": {
                "brands": [{"brand": "Chromium", "version": "129"}, {"brand": "Microsoft Edge", "version": "129"}],
                "fullVersion": "129.0.0.0", "platform": "Android", "platformVersion": "14.0.0",
                "architecture": "", "model": "Pixel 8", "mobile": True,
            },
        })
        cdp.send("Emulation.setDeviceMetricsOverride",
                 {"width": 412, "height": 915, "deviceScaleFactor": 2.6, "mobile": True})
        cdp.send("Emulation.setTouchEmulationEnabled", {"enabled": True, "maxTouchPoints": 5})
        return cdp

    # ------------------------------------------------------------ đọc trạng thái
    def _load(self, page: Page, url: str, marker: str) -> list:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        try:
            page.get_by_text(marker, exact=True).first.wait_for(timeout=25000)
        except PWTimeout:
            if "login" in urlparse(page.url).netloc or "Sign in" in page.content():
                raise NotLoggedIn()
            raise RuntimeError(f"Không đọc được trang {url} (Rewards có thể đã đổi giao diện)")
        self.sleep(1.5, 2.5)
        return page.evaluate(SCRAPE_JS)

    def read_state(self, page: Page) -> dict:
        """Đọc điểm + trạng thái task từ /dashboard và /earn."""
        st = empty_state()
        parse_page(self._load(page, DASHBOARD_URL, "Available points"), st)
        parse_page(self._load(page, EARN_URL, "Today's points"), st)
        self._read_breakdown(page, st)
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

    def _open_card(self, page: Page, href: str) -> None:
        """Bấm thẻ task trên trang Rewards (mở tab mới), làm task, rồi đóng tab."""
        link = page.locator(f"a[href={json.dumps(href)}]").first
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
                    self._open_card(page, c["href"])
                except (StopRequested, NotLoggedIn):
                    raise
                except Exception as e:
                    self.log(f"  lỗi task: {e}")
                self.sleep(2, 4)

    # Điểm Rewards mà bing.com hiển thị ở góc phải header = điểm của tài khoản đang đăng nhập trên bing.com
    BING_POINTS_JS = r"""() => Array.from(document.querySelectorAll('#id_h *, #rewid *, .id_button *'))
        .map(e => e.textContent.trim()).filter(x => /^[\d,]{2,}$/.test(x)).map(x => +x.replace(/,/g, ''))"""

    def bing_account_ok(self, page: Page) -> bool:
        """Kiểm tra bing.com có đăng nhập đúng tài khoản Rewards không (nếu sai, search sẽ cộng điểm cho tài khoản khác)."""
        rewards_pts = self.state.get("available")
        try:
            page.goto("https://www.bing.com/", wait_until="domcontentloaded", timeout=30000)
            self.sleep(4, 6)
            pts = page.evaluate(self.BING_POINTS_JS)
        except (StopRequested, NotLoggedIn):
            raise
        except Exception as e:
            self.log(f"Không kiểm tra được tài khoản trên bing.com ({e}), vẫn tiếp tục")
            return True
        if not pts or rewards_pts is None:
            self.log("Không đọc được điểm trên bing.com để đối chiếu tài khoản, vẫn tiếp tục")
            return True
        if abs(pts[0] - rewards_pts) > 200:
            self.log(f"Lỗi: bing.com đang đăng nhập tài khoản khác ({pts[0]:,} điểm) so với Rewards ({rewards_pts:,} điểm). "
                     "Search sẽ cộng điểm cho tài khoản kia nên bot bỏ qua search. Bấm Đăng nhập, đăng xuất bing.com "
                     "rồi đăng nhập lại đúng tài khoản ở tab bing.com.")
            return False
        self.log(f"bing.com đúng tài khoản ({pts[0]:,} điểm)")
        return True

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
        start = (self.state.get(kind) or {}).get("progress")
        self.log(f"{label}: {count} lượt search")
        for i in range(count):
            self.check_stop()
            if i and i % 5 == 0:  # cứ 5 lượt kiểm tra điểm 1 lần
                c = self._recheck(check_page, kind)
                if c:
                    self.log(f"  {label}: {c['progress']}/{c['max']} điểm")
                    if c["progress"] >= c["max"]:
                        self.log(f"{label}: đã đủ điểm, dừng sớm")
                        return
                    if start is not None and i >= 10 and c["progress"] <= start:
                        self.log(f"  cảnh báo: {label} chưa được cộng điểm sau {i} lượt "
                                 "(thử tăng thời gian nghỉ trong Cài đặt)")
            q = self.bank.take(self.name)
            self.status(progress=f"{label} {i + 1}/{count}")
            try:
                page.goto(f"https://www.bing.com/search?q={quote_plus(q)}&form=QBLH",
                          wait_until="domcontentloaded", timeout=30000)
                page.mouse.wheel(0, random.randint(200, 1200))
            except Exception as e:
                self.log(f"  lỗi khi tìm '{q}': {e}")
            self.log(f"  [{label} {i + 1}/{count}] {q}")
            self.sleep(self.s["search_delay_min"], self.s["search_delay_max"])

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
            q = self.bank.take(self.name)
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
        url = random.choice(BROWSE_SITES)
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
                url = random.choice(same) if same and random.random() < 0.7 else random.choice(BROWSE_SITES)
            except StopRequested:
                raise
            except Exception as e:
                self.log(f"  lỗi browse: {e}")
                url = random.choice(BROWSE_SITES)
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
                self.read_state(page)
            wants_search = any(self.s.get(k, d) for k, d in (("do_pc", True), ("do_mobile", True), ("do_images", True)))
            account_ok = self.bing_account_ok(page) if wants_search else True
            if account_ok:
                if self.s.get("do_pc", True):
                    self.do_searches(page, "pc", "Search PC")
                if self.s.get("do_mobile", True):
                    mpage = ctx.new_page()
                    own.append(mpage)
                    self._emulate_mobile(ctx, mpage)
                    self.do_searches(mpage, "mobile", "Search Mobile", check_page=page)
                if self.s.get("do_pc", True) or self.s.get("do_mobile", True):
                    self.read_state(page)
                if self.s.get("do_images", True):
                    self.do_image_searches(page, int(self.s.get("image_searches", 6)))
            if self.s.get("do_browse", False):
                self.do_browse(page, int(self.s.get("browse_minutes", 30)))

            end = self.read_state(page)["available"] or start
            if not account_ok:
                self.status(state="Lỗi", progress="bing.com đăng nhập sai tài khoản")
                return
            self.status(state="Hoàn thành", progress=f"+{end - start}")
            self.log(f"Xong! {start} -> {end} (+{end - start})")
        self._session(work, bool(self.s.get("headless")), label="Chạy")
