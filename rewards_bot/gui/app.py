"""Cửa sổ chính: dashboard, quản lý profile, bảng search, nhật ký, cài đặt."""

import json
import queue
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from tkinter.scrolledtext import ScrolledText

from ..core.config import DASHBOARD_FILE, HISTORY_FILE, POINTS_HISTORY_FILE, load_settings, save_settings
from ..core.runner import Runner
from ..search.bank import QueryBank
from ..search.catalog import CATEGORIES, all_queries
from .dashboard import DashboardTab
from .dialogs import ProfileDialog
from .theme import ACCENT, BG, CARD, OK, STATE_TAGS


def enable_dpi_awareness() -> None:
    """Chữ nét trên màn hình có phóng to (125%, 150%...) của Windows."""
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


class App(tk.Tk):
    def __init__(self):
        enable_dpi_awareness()
        super().__init__()
        self.title("Microsoft Rewards Bot")
        self.geometry("1240x860")
        self.minsize(900, 560)
        self.configure(bg=BG)

        self.settings = load_settings()
        self.q: queue.Queue = queue.Queue()
        self.bank = QueryBank(HISTORY_FILE, int(self.settings.get("history_days", 30)))
        self.bank.on_change = lambda kind, payload: self.q.put(("bank", kind, payload))
        self.runner = Runner(
            self.bank,
            log=lambda n, m: self.q.put(("log", n, m)),
            status=lambda n, d: self.q.put(("status", n, d)),
            done=lambda n: self.q.put(("done", n, None)),
        )
        self.pstate: dict = self._load_cache()  # name -> {"state","points","start","progress","tasks","updated"}
        self.points_history: dict = self._load_json(POINTS_HISTORY_FILE)  # name -> {"YYYY-MM-DD": stats}

        self._style()
        self._build()
        self._load_profiles_tree()
        self.bank.generate(60)
        self.after(100, self._poll)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------ style
    def _style(self):
        st = ttk.Style(self)
        st.theme_use("clam")
        font = ("Segoe UI", 10)
        st.configure(".", font=font, background=BG)
        st.configure("TFrame", background=BG)
        st.configure("Card.TFrame", background=CARD)
        st.configure("TLabel", background=BG)
        st.configure("Card.TLabel", background=CARD)
        st.configure("Muted.TLabel", background=CARD, foreground="#6b7280")
        st.configure("TCheckbutton", background=CARD)
        st.configure("TRadiobutton", background=BG)
        st.configure("TButton", padding=(10, 5))
        st.configure("Accent.TButton", background=ACCENT, foreground="white")
        st.map("Accent.TButton", background=[("active", "#005a9e"), ("disabled", "#9bbbd6")])
        st.configure("Danger.TButton", background="#c42b1c", foreground="white")
        st.map("Danger.TButton", background=[("active", "#a32315")])
        st.configure("Treeview", rowheight=28, background=CARD, fieldbackground=CARD)
        st.configure("Treeview.Heading", font=("Segoe UI Semibold", 10))
        st.configure("TNotebook", background=BG, borderwidth=0)
        st.configure("TNotebook.Tab", padding=(16, 6))
        st.configure("Ok.Horizontal.TProgressbar", background=OK, troughcolor="#e5e7eb", thickness=10)

    # ------------------------------------------------------------ layout
    def _build(self):
        header = tk.Frame(self, bg=ACCENT, height=64)
        header.pack(fill="x")
        tk.Label(header, text="Microsoft Rewards Bot", bg=ACCENT, fg="white",
                 font=("Segoe UI Semibold", 16)).pack(side="left", padx=18, pady=14)
        self.total_lbl = tk.Label(header, text="Tổng điểm: —", bg=ACCENT, fg="white", font=("Segoe UI", 12))
        self.total_lbl.pack(side="right", padx=18)

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=12, pady=12)
        self.dash = DashboardTab(nb, on_refresh=self.refresh_profiles)
        nb.add(self.dash, text="  Dashboard  ")
        self._build_profiles(nb)
        self._build_queries(nb)
        self._build_log(nb)
        self._build_settings(nb)

    def _build_profiles(self, nb):
        tab = ttk.Frame(nb, padding=10)
        nb.add(tab, text="  Profiles  ")

        bar = ttk.Frame(tab)
        bar.pack(fill="x", pady=(0, 8))
        ttk.Button(bar, text="+ Thêm", command=self.add_profile).pack(side="left")
        ttk.Button(bar, text="Sửa", command=self.edit_profile).pack(side="left", padx=4)
        ttk.Button(bar, text="Xóa", command=self.delete_profile).pack(side="left")
        ttk.Button(bar, text="Đăng nhập", command=self.login_selected).pack(side="left", padx=(16, 4))
        ttk.Button(bar, text="■ Dừng", style="Danger.TButton", command=self.stop_all).pack(side="right")
        ttk.Button(bar, text="▶ Chạy tất cả", style="Accent.TButton",
                   command=self.run_all).pack(side="right", padx=4)
        ttk.Button(bar, text="▶ Chạy đã chọn", command=self.run_selected).pack(side="right")

        cols = ("mode", "state", "points", "gain", "progress")
        self.ptree = ttk.Treeview(tab, columns=cols, show="tree headings", selectmode="extended")
        self.ptree.heading("#0", text="Profile")
        self.ptree.column("#0", width=180)
        for c, t, w in [("mode", "Chế độ", 150), ("state", "Trạng thái", 130), ("points", "Điểm", 90),
                        ("gain", "+ Lần này", 90), ("progress", "Tiến độ", 260)]:
            self.ptree.heading(c, text=t)
            self.ptree.column(c, width=w, anchor="w" if c in ("mode", "progress", "state") else "center")
        self.ptree.tag_configure("running", foreground=ACCENT)
        self.ptree.tag_configure("waiting", foreground="#8a6d00")
        self.ptree.tag_configure("done", foreground="#107c10")
        self.ptree.tag_configure("error", foreground="#c42b1c")
        self.ptree.pack(fill="both", expand=True)
        self.ptree.bind("<Double-1>", lambda _e: self.edit_profile())

        opts = ttk.Frame(tab, style="Card.TFrame", padding=10)
        opts.pack(fill="x", pady=(8, 0))
        self.v_quests = tk.BooleanVar(value=self.settings["do_quests"])
        self.v_pc = tk.BooleanVar(value=self.settings["do_pc"])
        self.v_mobile = tk.BooleanVar(value=self.settings["do_mobile"])
        self.v_images = tk.BooleanVar(value=self.settings["do_images"])
        self.v_browse = tk.BooleanVar(value=self.settings["do_browse"])
        self.v_headless = tk.BooleanVar(value=self.settings["headless"])
        self.v_parallel = tk.IntVar(value=self.settings["max_parallel"])
        for text, var in [("Daily Set + Keep earning + Quests", self.v_quests), ("Search PC", self.v_pc),
                          ("Search Mobile", self.v_mobile), ("Search ảnh", self.v_images),
                          ("Browse", self.v_browse), ("Chạy ẩn", self.v_headless)]:
            ttk.Checkbutton(opts, text=text, variable=var, command=self._save_opts).pack(side="left", padx=(0, 14))
        ttk.Label(opts, text="Số profile chạy cùng lúc:", style="Card.TLabel").pack(side="left", padx=(12, 4))
        ttk.Spinbox(opts, from_=1, to=10, width=4, textvariable=self.v_parallel,
                    command=self._save_opts).pack(side="left")

    def _build_queries(self, nb):
        tab = ttk.Frame(nb, padding=10)
        nb.add(tab, text="  Bảng search  ")

        bar = ttk.Frame(tab)
        bar.pack(fill="x", pady=(0, 8))
        ttk.Label(bar, text="Số câu:").pack(side="left")
        self.v_qcount = tk.IntVar(value=60)
        ttk.Spinbox(bar, from_=10, to=500, increment=10, width=6, textvariable=self.v_qcount).pack(side="left", padx=4)
        ttk.Button(bar, text="⟳ Tạo bảng mới", style="Accent.TButton",
                   command=lambda: self.bank.generate(int(self.v_qcount.get()))).pack(side="left", padx=4)
        ttk.Button(bar, text="Xuất CSV", command=self.export_csv).pack(side="left")
        ttk.Button(bar, text="Xóa lịch sử đã dùng", command=self.clear_history).pack(side="right")

        total = len(all_queries())
        ttk.Label(tab, text=f"{len(CATEGORIES)} lĩnh vực · {total} câu khả dụng · không trùng trong bảng và "
                            f"không lặp lại câu đã dùng trong {self.settings['history_days']} ngày. "
                            "Các profile lấy lần lượt từ bảng, hết bảng sẽ tự sinh thêm.",
                  foreground="#6b7280").pack(anchor="w", pady=(0, 6))

        cols = ("cat", "query", "used")
        self.qtree = ttk.Treeview(tab, columns=cols, show="headings")
        for c, t, w in [("cat", "Lĩnh vực", 150), ("query", "Truy vấn", 480), ("used", "Đã dùng bởi", 160)]:
            self.qtree.heading(c, text=t)
            self.qtree.column(c, width=w)
        self.qtree.tag_configure("used", foreground="#9ca3af")
        sb = ttk.Scrollbar(tab, orient="vertical", command=self.qtree.yview)
        self.qtree.configure(yscrollcommand=sb.set)
        self.qtree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

    def _build_log(self, nb):
        tab = ttk.Frame(nb, padding=10)
        nb.add(tab, text="  Nhật ký  ")
        bar = ttk.Frame(tab)
        bar.pack(fill="x", pady=(0, 6))
        ttk.Label(bar, text="Lọc theo profile:").pack(side="left")
        self.v_logfilter = tk.StringVar(value="Tất cả")
        self.logfilter = ttk.Combobox(bar, textvariable=self.v_logfilter, state="readonly", width=24)
        self.logfilter.pack(side="left", padx=6)
        self.logfilter.bind("<<ComboboxSelected>>", lambda _e: self._render_log())
        ttk.Button(bar, text="Xóa log", command=self._clear_log).pack(side="right")
        self.logs: list = []
        self.logbox = ScrolledText(tab, font=("Consolas", 10), bg="#1e1e1e", fg="#d4d4d4",
                                   insertbackground="white", relief="flat", state="disabled")
        self.logbox.pack(fill="both", expand=True)
        self.logbox.tag_configure("time", foreground="#6a9955")
        self.logbox.tag_configure("name", foreground="#4fc1ff")
        self.logbox.tag_configure("err", foreground="#f48771")

    def _build_settings(self, nb):
        tab = ttk.Frame(nb, padding=16)
        nb.add(tab, text="  Cài đặt  ")
        card = ttk.Frame(tab, style="Card.TFrame", padding=16)
        card.pack(anchor="nw")
        self.v_set = {}
        rows = [("search_delay_min", "Nghỉ tối thiểu giữa 2 lượt tìm (giây)"),
                ("search_delay_max", "Nghỉ tối đa giữa 2 lượt tìm (giây)"),
                ("extra_searches", "Số lượt tìm thêm cho chắc đủ điểm"),
                ("history_days", "Không lặp lại câu đã dùng trong (ngày)"),
                ("image_searches", "Số lượt search ảnh"),
                ("browse_minutes", "Thời gian browse (phút)")]
        for i, (k, label) in enumerate(rows):
            ttk.Label(card, text=label, style="Card.TLabel").grid(row=i, column=0, sticky="w", pady=4)
            v = tk.StringVar(value=str(self.settings[k]))
            ttk.Entry(card, textvariable=v, width=8).grid(row=i, column=1, sticky="w", padx=10)
            self.v_set[k] = v
        r = len(rows)
        ttk.Label(card, text="Trình duyệt (cho profile riêng)", style="Card.TLabel").grid(row=r, column=0, sticky="w", pady=4)
        self.v_channel = tk.StringVar(value=self.settings["browser_channel"] or "chromium")
        ttk.Combobox(card, textvariable=self.v_channel, state="readonly", width=12,
                     values=["msedge", "chrome", "chromium"]).grid(row=r, column=1, sticky="w", padx=10)
        ttk.Button(card, text="Lưu cài đặt", style="Accent.TButton",
                   command=self._save_settings_tab).grid(row=r + 1, column=0, sticky="w", pady=(14, 0))

        help_txt = (
            "Chạy nhiều cửa sổ cùng lúc:\n"
            " • Cách 1 (khuyên dùng): thêm nhiều profile 'Cửa sổ riêng', bấm Đăng nhập cho từng cái 1 lần, "
            "rồi ▶ Chạy tất cả — mỗi profile mở 1 cửa sổ và chạy song song.\n"
            " • Cách 2: gắn vào cửa sổ Edge bạn tự mở. Mở Edge bằng lệnh:\n"
            '     msedge.exe --remote-debugging-port=9222 --user-data-dir="C:\\EdgeRewards1"\n'
            "   (cửa sổ thứ 2 dùng cổng 9223 và thư mục khác), đăng nhập trong đó, rồi thêm profile "
            "chế độ 'Gắn vào trình duyệt đang mở' với cổng tương ứng."
        )
        ttk.Label(tab, text=help_txt, justify="left", foreground="#374151").pack(anchor="nw", pady=(18, 0))

    # ------------------------------------------------------------ profiles
    def _profiles(self) -> list:
        return self.settings["profiles"]

    def _find(self, name):
        return next((p for p in self._profiles() if p["name"] == name), None)

    def _mode_text(self, p):
        return "Cửa sổ riêng" if p.get("mode") != "cdp" else f"Gắn CDP :{p.get('cdp_port')}"

    def _load_profiles_tree(self):
        self.ptree.delete(*self.ptree.get_children())
        for p in self._profiles():
            self._state(p["name"])
            self.ptree.insert("", "end", iid=p["name"], text=p["name"], values=(self._mode_text(p), "", "", "", ""))
            self._refresh_row(p["name"])
        self.logfilter["values"] = ["Tất cả"] + [p["name"] for p in self._profiles()]
        self._refresh_dashboard()

    def _refresh_row(self, name):
        if not self.ptree.exists(name):
            return
        st = self.pstate[name]
        gain = ""
        if st.get("start") is not None and st.get("points") != "":
            gain = f"+{int(st['points']) - int(st['start'])}"
        p = self._find(name)
        pts = f"{int(st['points']):,}" if str(st["points"]).isdigit() else st["points"]
        self.ptree.item(name, values=(self._mode_text(p), st["state"], pts, gain, st["progress"]),
                        tags=(STATE_TAGS.get(st["state"], ""),))
        total = sum(int(s["points"]) for s in self.pstate.values() if str(s.get("points", "")).isdigit())
        self.total_lbl.configure(text=f"Tổng điểm: {total:,}" if total else "Tổng điểm: —")

    def add_profile(self):
        d = ProfileDialog(self, {"name": f"Profile {len(self._profiles()) + 1}", "mode": "managed",
                                 "cdp_port": 9222 + len(self._profiles())})
        if d.result:
            if self._find(d.result["name"]):
                messagebox.showwarning("Trùng tên", "Đã có profile với tên này.")
                return
            self._profiles().append(d.result)
            save_settings(self.settings)
            self._load_profiles_tree()

    def edit_profile(self):
        sel = self.ptree.selection()
        if not sel:
            return
        old = self._find(sel[0])
        if self.runner.is_running(old["name"]):
            messagebox.showinfo("Đang chạy", "Hãy dừng profile trước khi sửa.")
            return
        d = ProfileDialog(self, old)
        if d.result:
            if d.result["name"] != old["name"] and self._find(d.result["name"]):
                messagebox.showwarning("Trùng tên", "Đã có profile với tên này.")
                return
            old.update(d.result)
            save_settings(self.settings)
            self._load_profiles_tree()

    def delete_profile(self):
        sel = [n for n in self.ptree.selection() if not self.runner.is_running(n)]
        if not sel or not messagebox.askyesno("Xóa profile", f"Xóa {', '.join(sel)}?\n"
                                                             "(Dữ liệu đăng nhập trong data/profiles vẫn được giữ.)"):
            return
        self.settings["profiles"] = [p for p in self._profiles() if p["name"] not in sel]
        save_settings(self.settings)
        self._load_profiles_tree()

    def _current_settings(self) -> dict:
        self._save_opts()
        return dict(self.settings)

    def login_selected(self):
        sel = self.ptree.selection()
        if not sel:
            messagebox.showinfo("Chọn profile", "Chọn profile cần đăng nhập.")
            return
        self.runner.start([self._find(n) for n in sel], self._current_settings(), action="login")

    def refresh_profiles(self, names=None):
        profs = self._profiles() if names is None else [p for p in map(self._find, names) if p]
        self.runner.start(profs, self._current_settings(), action="refresh")

    def run_selected(self):
        sel = self.ptree.selection()
        if not sel:
            messagebox.showinfo("Chọn profile", "Chọn ít nhất 1 profile (giữ Ctrl để chọn nhiều).")
            return
        self.runner.start([self._find(n) for n in sel], self._current_settings())

    def run_all(self):
        self.runner.start(list(self._profiles()), self._current_settings())

    def stop_all(self):
        sel = self.ptree.selection()
        self.runner.stop(list(sel) if sel and any(self.runner.is_running(n) for n in sel) else None)

    def _save_opts(self):
        self.settings.update(do_quests=self.v_quests.get(), do_pc=self.v_pc.get(), do_mobile=self.v_mobile.get(),
                             do_images=self.v_images.get(), do_browse=self.v_browse.get(),
                             headless=self.v_headless.get())
        try:
            self.settings["max_parallel"] = max(1, int(self.v_parallel.get()))
        except (ValueError, tk.TclError):
            pass
        save_settings(self.settings)

    def _save_settings_tab(self):
        try:
            for k, v in self.v_set.items():
                self.settings[k] = int(v.get())
        except ValueError:
            messagebox.showwarning("Sai giá trị", "Các ô số phải là số nguyên.")
            return
        if self.settings["search_delay_max"] < self.settings["search_delay_min"]:
            self.settings["search_delay_max"] = self.settings["search_delay_min"]
        ch = self.v_channel.get()
        self.settings["browser_channel"] = "" if ch == "chromium" else ch
        self.bank.history_days = self.settings["history_days"]
        save_settings(self.settings)
        messagebox.showinfo("Đã lưu", "Đã lưu cài đặt.")

    # ------------------------------------------------------------ queries tab
    def export_csv(self):
        path = filedialog.asksaveasfilename(defaultextension=".csv", initialfile="bang_search.csv",
                                            filetypes=[("CSV", "*.csv")])
        if path:
            self.bank.export_csv(path)

    def clear_history(self):
        if messagebox.askyesno("Xóa lịch sử", "Cho phép dùng lại các câu đã tìm trước đây?"):
            self.bank.clear_history()

    def _qrow_values(self, r):
        return r["category"], r["query"], r["used_by"]

    # ------------------------------------------------------------ log
    def _append_log(self, name, msg):
        entry = (time.strftime("%H:%M:%S"), name, msg)
        self.logs.append(entry)
        if len(self.logs) > 5000:
            self.logs = self.logs[-4000:]
        f = self.v_logfilter.get()
        if f in ("Tất cả", name):
            self._write_log(entry)

    def _write_log(self, entry):
        t, name, msg = entry
        self.logbox.configure(state="normal")
        self.logbox.insert("end", f"{t} ", "time")
        self.logbox.insert("end", f"[{name}] ", "name")
        self.logbox.insert("end", msg + "\n", "err" if msg.lower().startswith(("lỗi", "  lỗi")) else "")
        self.logbox.configure(state="disabled")
        self.logbox.see("end")

    def _render_log(self):
        self.logbox.configure(state="normal")
        self.logbox.delete("1.0", "end")
        self.logbox.configure(state="disabled")
        f = self.v_logfilter.get()
        for e in self.logs:
            if f in ("Tất cả", e[1]):
                self._write_log(e)

    def _clear_log(self):
        self.logs = []
        self._render_log()

    # ------------------------------------------------------------ dashboard
    def _state(self, name) -> dict:
        st = self.pstate.setdefault(name, {})
        for k, v in (("state", "Sẵn sàng"), ("points", ""), ("start", None), ("progress", ""),
                     ("tasks", []), ("updated", "—")):
            st.setdefault(k, v)
        return st

    def _refresh_dashboard(self):
        self.dash.update_data(self.pstate, self._profiles(), len(self.runner.running), self.points_history)

    @staticmethod
    def _load_json(path) -> dict:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _record_history(self, name: str, stats: dict) -> None:
        """Lưu số liệu mới nhất trong ngày của profile (mỗi ngày 1 bản ghi, ghi đè trong ngày)."""
        day = time.strftime("%Y-%m-%d")
        self.points_history.setdefault(name, {})[day] = stats
        try:
            POINTS_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
            POINTS_HISTORY_FILE.write_text(json.dumps(self.points_history, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    @staticmethod
    def _load_cache() -> dict:
        try:
            data = json.loads(DASHBOARD_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return {n: {"points": d.get("points", ""), "today": d.get("today"), "tasks": d.get("tasks", []), "updated": d.get("updated", "—")}
                for n, d in data.items()}

    def _save_cache(self):
        data = {n: {"points": s.get("points", ""), "today": s.get("today"), "tasks": s.get("tasks", []), "updated": s.get("updated", "—")}
                for n, s in self.pstate.items()}
        try:
            DASHBOARD_FILE.parent.mkdir(parents=True, exist_ok=True)
            DASHBOARD_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    # ------------------------------------------------------------ event loop
    def _poll(self):
        try:
            while True:
                kind, a, b = self.q.get_nowait()
                if kind == "log":
                    self._append_log(a, b)
                elif kind == "status":
                    self._state(a).update(b)
                    if b.get("stats") and b["stats"].get("available") is not None:
                        self._record_history(a, b["stats"])
                    self._refresh_row(a)
                    self._refresh_dashboard()
                    if "tasks" in b or "points" in b:
                        self._save_cache()
                elif kind == "done":
                    self._refresh_dashboard()
                elif kind == "bank":
                    if a == "reset":
                        self.qtree.delete(*self.qtree.get_children())
                        for r in b:
                            self.qtree.insert("", "end", iid=str(r["id"]), values=self._qrow_values(r))
                    elif a == "add":
                        self.qtree.insert("", "end", iid=str(b["id"]), values=self._qrow_values(b))
                    elif a == "update" and self.qtree.exists(str(b["id"])):
                        self.qtree.item(str(b["id"]), values=self._qrow_values(b), tags=("used",))
        except queue.Empty:
            pass
        self.after(150, self._poll)

    def _on_close(self):
        if self.runner.running and not messagebox.askyesno("Thoát", "Bot đang chạy. Dừng và thoát?"):
            return
        self.runner.stop()
        self.destroy()

