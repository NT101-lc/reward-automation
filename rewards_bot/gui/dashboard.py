"""Tab Dashboard: tổng quan điểm và trạng thái từng task của mỗi profile."""

import tkinter as tk
from tkinter import ttk

from .charts import BalanceLineChart, DailyStackChart, TodayMeters
from .theme import ACCENT, CARD, MUTED, OK, WARN

GROUP_ORDER = ["Tìm kiếm", "Daily Set", "Keep earning", "Hoạt động", "Task thêm"]


def task_points(tasks: list) -> tuple:
    """(điểm đã nhận, điểm tối đa) hôm nay, chỉ tính task của Rewards (không tính task đếm lượt/phút)."""
    rows = [t for t in tasks or [] if not t.get("unit")]
    return sum(t["progress"] for t in rows), sum(t["max"] for t in rows)


def fmt_amount(t: dict) -> str:
    unit = t.get("unit") or "điểm"
    return f"{t['progress']}/{t['max']} {unit}"


class KpiCard(ttk.Frame):
    def __init__(self, master, title: str, color: str = ACCENT):
        super().__init__(master, style="Card.TFrame", padding=(16, 12))
        ttk.Label(self, text=title, style="Muted.TLabel").pack(anchor="w")
        self.value = tk.Label(self, text="—", bg=CARD, fg=color, font=("Segoe UI Semibold", 20))
        self.value.pack(anchor="w")
        self.sub = ttk.Label(self, text="", style="Muted.TLabel")
        self.sub.pack(anchor="w")

    def set(self, value, sub: str = "") -> None:
        self.value.configure(text=value)
        self.sub.configure(text=sub)


class DashboardTab(ttk.Frame):
    def __init__(self, master, on_refresh):
        super().__init__(master, padding=10)
        self.on_refresh = on_refresh  # callback(list tên profile hoặc None = tất cả)
        self.pstate: dict = {}
        self.history: dict = {}  # name -> {"YYYY-MM-DD": stats}
        self.selected = None

        kpis = ttk.Frame(self)
        kpis.pack(fill="x")
        self.k_total = KpiCard(kpis, "Tổng điểm hiện có")
        self.k_today = KpiCard(kpis, "Điểm hôm nay", OK)
        self.k_tasks = KpiCard(kpis, "Task hoàn thành", OK)
        self.k_running = KpiCard(kpis, "Profile đang chạy", WARN)
        for i, k in enumerate((self.k_total, self.k_today, self.k_tasks, self.k_running)):
            k.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 8, 0))
            kpis.columnconfigure(i, weight=1)

        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(10, 6))
        ttk.Label(bar, text="Chọn 1 profile để xem chi tiết task. "
                            "Làm mới chỉ đọc điểm, không làm task.", foreground=MUTED).pack(side="left")
        ttk.Button(bar, text="↻ Làm mới tất cả", command=lambda: self.on_refresh(None)).pack(side="right")
        ttk.Button(bar, text="↻ Làm mới đã chọn",
                   command=lambda: self.selected and self.on_refresh([self.selected])).pack(side="right", padx=4)

        panes = ttk.PanedWindow(self, orient="horizontal")
        panes.pack(fill="both", expand=True)

        # --- trái: tổng quan từng profile
        left = ttk.Frame(panes)
        cols = ("points", "today", "done", "updated")
        self.sum_tree = ttk.Treeview(left, columns=cols, show="tree headings", selectmode="browse")
        self.sum_tree.heading("#0", text="Profile")
        self.sum_tree.column("#0", width=130)
        for c, t, w in [("points", "Điểm", 80), ("today", "Hôm nay", 90), ("done", "Task", 60),
                        ("updated", "Cập nhật", 90)]:
            self.sum_tree.heading(c, text=t)
            self.sum_tree.column(c, width=w, anchor="center")
        self.sum_tree.tag_configure("complete", foreground=OK)
        self.sum_tree.pack(fill="both", expand=True)
        self.sum_tree.bind("<<TreeviewSelect>>", self._on_select)
        panes.add(left, weight=2)

        # --- phải: task của profile đang chọn
        right = ttk.Frame(panes, padding=(10, 0, 0, 0))
        head = ttk.Frame(right)
        head.pack(fill="x")
        self.detail_title = ttk.Label(head, text="Chưa chọn profile", font=("Segoe UI Semibold", 12))
        self.detail_title.pack(side="left")
        self.detail_sub = ttk.Label(head, text="", foreground=MUTED)
        self.detail_sub.pack(side="right")
        self.progress = ttk.Progressbar(right, mode="determinate", style="Ok.Horizontal.TProgressbar")
        self.progress.pack(fill="x", pady=6)

        views = ttk.Notebook(right)
        views.pack(fill="both", expand=True)
        task_tab = ttk.Frame(views)
        chart_tab = tk.Frame(views, bg=CARD, padx=12, pady=10)
        views.add(task_tab, text="  Task  ")
        views.add(chart_tab, text="  Biểu đồ  ")

        self.meters = TodayMeters(chart_tab)
        self.meters.pack(fill="x")
        row = tk.Frame(chart_tab, bg=CARD)
        row.pack(fill="both", expand=True, pady=(8, 0))
        row.columnconfigure(0, weight=3, uniform="c")
        row.columnconfigure(1, weight=2, uniform="c")
        row.rowconfigure(0, weight=1)
        self.stack = DailyStackChart(row, days=14)
        self.stack.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
        self.line = BalanceLineChart(row, days=30)
        self.line.grid(row=0, column=1, sticky="nsew")

        cols = ("amount", "status")
        self.task_tree = ttk.Treeview(task_tab, columns=cols, show="tree headings")
        self.task_tree.heading("#0", text="Task")
        self.task_tree.column("#0", width=320)
        self.task_tree.heading("amount", text="Điểm / tiến độ")
        self.task_tree.column("amount", width=130, anchor="center")
        self.task_tree.heading("status", text="Trạng thái")
        self.task_tree.column("status", width=110, anchor="center")
        self.task_tree.tag_configure("done", foreground=OK)
        self.task_tree.tag_configure("todo", foreground="#8a6d00")
        self.task_tree.tag_configure("group", font=("Segoe UI Semibold", 10))
        sb = ttk.Scrollbar(task_tab, orient="vertical", command=self.task_tree.yview)
        self.task_tree.configure(yscrollcommand=sb.set)
        self.task_tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        panes.add(right, weight=3)

    # ------------------------------------------------------------ data
    def update_data(self, pstate: dict, profiles: list, running: int, history: dict = None) -> None:
        self.pstate = pstate
        if history is not None:
            self.history = history
        names = [p["name"] for p in profiles]

        total_pts = today = done = count = 0
        have_today = False
        existing = set(self.sum_tree.get_children())
        for name in names:
            st = pstate.get(name, {})
            tasks = st.get("tasks") or []
            # điểm hôm nay: lấy số "Today's points" của Rewards, không có thì cộng từ task
            t_pts = st.get("today")
            if t_pts is None and tasks:
                t_pts = task_points(tasks)[0]
            d = sum(1 for t in tasks if t["done"])
            pts = st.get("points", "")
            if str(pts).isdigit():
                total_pts += int(pts)
            if t_pts is not None:
                today, have_today = today + int(t_pts), True
            done, count = done + d, count + len(tasks)
            values = (f"{int(pts):,}" if str(pts).isdigit() else "—", f"+{t_pts}" if t_pts is not None else "—",
                      f"{d}/{len(tasks)}" if tasks else "—", st.get("updated", "—"))
            tags = ("complete",) if tasks and d == len(tasks) else ()
            if self.sum_tree.exists(name):
                self.sum_tree.item(name, values=values, tags=tags)
            else:
                self.sum_tree.insert("", "end", iid=name, text=name, values=values, tags=tags)
            existing.discard(name)
        for gone in existing:
            self.sum_tree.delete(gone)

        self.k_total.set(f"{total_pts:,}" if total_pts else "—", f"{len(names)} profile")
        self.k_today.set(f"+{today:,}" if have_today else "—", "theo Rewards" if have_today else "chưa có dữ liệu")
        self.k_tasks.set(f"{done}/{count}" if count else "—", "tất cả profile")
        self.k_running.set(str(running), "")

        if self.selected not in names:
            self.selected = names[0] if names else None
            if self.selected:
                self.sum_tree.selection_set(self.selected)
        self._render_tasks()

    def _on_select(self, _e=None) -> None:
        sel = self.sum_tree.selection()
        if sel:
            self.selected = sel[0]
            self._render_tasks()

    def _render_charts(self, st: dict) -> None:
        hist = self.history.get(self.selected, {})
        days = sorted(hist)
        label = lambda d: f"{d[8:10]}/{d[5:7]}"
        self.meters.set(st.get("stats") or (hist[days[-1]] if days else {}))
        self.stack.set([(label(d), hist[d]) for d in days])
        self.line.set([(label(d), hist[d].get("available")) for d in days])

    def _render_tasks(self) -> None:
        open_groups = {self.task_tree.item(i, "text").split("  ")[0]: self.task_tree.item(i, "open")
                       for i in self.task_tree.get_children()}
        self.task_tree.delete(*self.task_tree.get_children())
        if not self.selected:
            return
        st = self.pstate.get(self.selected, {})
        tasks = st.get("tasks") or []
        got, mx = task_points(tasks)
        self.detail_title.configure(text=self.selected)
        self.detail_sub.configure(text=f"{st.get('state', '')} · cập nhật {st.get('updated', '—')}")
        self.progress.configure(maximum=max(mx, 1), value=got)
        self._render_charts(st)
        if not tasks:
            self.task_tree.insert("", "end", text="Chưa có dữ liệu — bấm Làm mới hoặc chạy profile")
            return

        groups = {}
        for t in tasks:
            groups.setdefault(t["group"], []).append(t)
        for g in sorted(groups, key=lambda x: GROUP_ORDER.index(x) if x in GROUP_ORDER else 99):
            items = groups[g]
            d = sum(1 for t in items if t["done"])
            gid = self.task_tree.insert("", "end", text=f"{g}  ({d}/{len(items)})", tags=("group",),
                                        open=open_groups.get(g, True),
                                        values=("", "✓ Xong" if d == len(items) else ""))
            for t in items:
                self.task_tree.insert(gid, "end", text=t["title"], values=(fmt_amount(t),
                                      "✓ Xong" if t["done"] else "○ Chưa xong"),
                                      tags=("done" if t["done"] else "todo",))
