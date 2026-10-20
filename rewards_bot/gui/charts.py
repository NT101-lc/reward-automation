"""Biểu đồ vẽ bằng tk.Canvas (không cần thư viện ngoài).

Màu theo bảng categorical đã kiểm tra (validate_palette: PASS all-pairs, light, nền trắng):
PC = xanh dương, Mobile = cam, Offers = xanh ngọc. Xanh ngọc < 3:1 trên nền trắng nên luôn có
nhãn số / tooltip đi kèm, không dùng màu làm kênh duy nhất.
"""

import tkinter as tk
import tkinter.font as tkfont

SERIES = [("pc", "Search PC", "#2a78d6"), ("mobile", "Search Mobile", "#eb6834"), ("offers", "Offers", "#1baf7a")]
SURFACE = "#ffffff"
INK = "#0b0b0b"
INK2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
TRACK = "#efeee9"
FONT = ("Segoe UI", 9)
FONT_B = ("Segoe UI Semibold", 10)


def nice_max(v: float, ticks: int = 4) -> int:
    """Đỉnh trục y sao cho mỗi vạch là số đẹp (10, 20, 25, 50, 100...)."""
    if v <= 0:
        return 10 * ticks
    mag = 1
    while True:
        for m in (1, 1.5, 2, 2.5, 3, 4, 5, 6, 7.5, 8):
            step = m * mag
            if step * ticks >= v and step == int(step):
                return int(step * ticks)
        mag *= 10


class _Base(tk.Canvas):
    def __init__(self, master, height: int, title: str):
        # width=1: không giành chỗ của bảng profile bên trái, canvas tự giãn theo khung
        super().__init__(master, width=1, height=height, bg=SURFACE, highlightthickness=0)
        self.title = title
        self._fonts = {}
        self.bind("<Configure>", lambda _e: self.redraw())
        self.bind("<Motion>", self._on_move)
        self.bind("<Leave>", lambda _e: self.delete("hover"))

    def _font(self, bold: bool) -> tkfont.Font:
        if bold not in self._fonts:
            self._fonts[bold] = tkfont.Font(self, font=FONT_B if bold else FONT)
        return self._fonts[bold]

    def tw(self, text: str, bold: bool = False) -> int:
        """Độ rộng thật của chữ (đúng cả khi Windows phóng to 125%/150%)."""
        return self._font(bold).measure(text)

    def lh(self) -> int:
        return self._font(False).metrics("linespace")

    def label_step(self, labels: list, width: float) -> int:
        """Cứ bao nhiêu nhãn trục x thì hiện 1 cái để không chồng chữ."""
        need = max((self.tw(l) for l in labels), default=0) + 12
        return max(1, -(-int(need * len(labels)) // max(int(width), 1)))

    def _title(self) -> int:
        """Vẽ tiêu đề, trả về y ngay dưới tiêu đề."""
        self.create_text(0, 2, text=self.title, anchor="nw", fill=INK, font=FONT_B)
        return self._font(True).metrics("linespace") + 6

    def _tooltip(self, x, y, lines: list) -> None:
        """Hộp tooltip: dòng đầu đậm, các dòng sau có ô màu nhận diện series."""
        pad, lh = 8, self.lh() + 4
        w = max(self.tw(t, i == 0) + (0 if c is None else 14) for i, (c, t) in enumerate(lines)) + 2 * pad
        h = len(lines) * lh + 2 * pad
        x = min(max(x + 12, 4), self.winfo_width() - w - 4)
        y = max(min(y - h - 8, self.winfo_height() - h - 4), 4)
        self.create_rectangle(x, y, x + w, y + h, fill=SURFACE, outline=AXIS, tags="hover")
        for i, (color, text) in enumerate(lines):
            ty = y + pad + i * lh + lh / 2
            tx = x + pad
            if color:
                self.create_rectangle(tx, ty - 4, tx + 8, ty + 4, fill=color, outline="", tags="hover")
                tx += 14
            self.create_text(tx, ty, text=text, anchor="w", fill=INK, font=FONT_B if i == 0 else FONT, tags="hover")

    def _on_move(self, e) -> None:
        pass

    def redraw(self) -> None:
        pass


class TodayMeters(_Base):
    """Tiến độ search hôm nay: thanh ngang có track, nhãn 'đã/tối đa' bằng chữ."""

    def __init__(self, master):
        super().__init__(master, 96, "Search hôm nay")
        self.stats = {}

    def set(self, stats: dict) -> None:
        self.stats = stats or {}
        self.redraw()

    def redraw(self) -> None:
        self.delete("all")
        w = self.winfo_width()
        y = self._title() + 12
        name_w = max(self.tw(l) for _, l, _ in SERIES[:2]) + 16
        val_w = self.tw("chưa có dữ liệu", True) + 16
        for key, label, color in SERIES[:2]:
            prog, mx = self.stats.get(key), self.stats.get(key + "_max")
            self.create_text(0, y, text=label, anchor="w", fill=INK2, font=FONT)
            val = f"{prog}/{mx} điểm" if mx else "chưa có dữ liệu"
            self.create_text(w, y, text=val, anchor="e", fill=INK if mx else MUTED, font=FONT_B)
            x0, x1 = name_w, w - val_w
            self.create_rectangle(x0, y - 4, x1, y + 4, fill=TRACK, outline="")
            if mx and prog:
                fx = x0 + (x1 - x0) * min(prog / mx, 1)
                self.create_rectangle(x0, y - 4, fx, y + 4, fill=color, outline="")
            y += self.lh() + 14


class DailyStackChart(_Base):
    """Điểm kiếm được mỗi ngày, cột chồng PC / Mobile / Offers, có tooltip."""

    def __init__(self, master, days: int = 14):
        super().__init__(master, 240, f"Điểm mỗi ngày ({days} ngày)")
        self.days = days
        self.data = []  # [(label 'dd/mm', {pc, mobile, offers})]
        self.bars = []

    def set(self, data: list) -> None:
        self.data = data[-self.days:]
        self.redraw()

    def redraw(self) -> None:
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        y0 = self._title()
        # legend: luôn có khi >= 2 series, xuống dòng nếu hết chỗ
        lx, ly = 0, y0 + self.lh() / 2
        for _, label, color in SERIES:
            item_w = self.tw(label) + 26
            if lx and lx + item_w > w:
                lx, ly = 0, ly + self.lh() + 2
            self.create_rectangle(lx, ly - 4, lx + 8, ly + 4, fill=color, outline="")
            self.create_text(lx + 12, ly, text=label, anchor="w", fill=INK2, font=FONT)
            lx += item_w
        self.bars = []
        if not self.data:
            self.create_text(w / 2, h / 2, text="Chưa có lịch sử — chạy hoặc Làm mới để bắt đầu ghi",
                             fill=MUTED, font=FONT, width=w - 20, justify="center")
            return
        left, right = self.tw("0000") + 10, w - 4
        top, bottom = ly + self.lh() + 6, h - self.lh() - 6
        totals = [sum((v.get(k) or 0) for k, _, _ in SERIES) for _, v in self.data]
        ymax = nice_max(max(totals))
        for i in range(5):  # lưới ngang mảnh + nhãn trục
            y = bottom - (bottom - top) * i / 4
            self.create_line(left, y, right, y, fill=GRID if i else AXIS)
            self.create_text(left - 6, y, text=f"{int(ymax * i / 4)}", anchor="e", fill=MUTED, font=FONT)
        n = len(self.data)
        slot = (right - left) / n
        bw = min(28, slot * 0.6)
        step = self.label_step([l for l, _ in self.data], right - left)
        for i, (label, v) in enumerate(self.data):
            cx = left + slot * (i + 0.5)
            x0, x1 = cx - bw / 2, cx + bw / 2
            y = bottom
            for key, _, color in SERIES:
                val = v.get(key) or 0
                if val <= 0:
                    continue
                hgt = (bottom - top) * val / ymax
                self.create_rectangle(x0, y - hgt, x1, y, fill=color, outline="")
                y -= hgt + 2  # khe 2px giữa các đoạn
            if (n - 1 - i) % step == 0:  # luôn giữ nhãn của ngày mới nhất
                lx = min(cx, w - self.tw(label) / 2 - 1)  # không để nhãn cuối bị cắt mép
                self.create_text(lx, bottom + 4, text=label, anchor="n", fill=MUTED, font=FONT)
            self.bars.append((left + slot * i, left + slot * (i + 1), label, v, totals[i]))
        # nhãn trực tiếp chọn lọc: chỉ tổng của ngày mới nhất
        lx0, lx1, *_ = self.bars[-1]
        cx = (lx0 + lx1) / 2
        ty = bottom - (bottom - top) * totals[-1] / ymax - 4
        self.create_text(cx, ty, text=str(totals[-1]), anchor="s", fill=INK, font=FONT_B)

    def _on_move(self, e) -> None:
        self.delete("hover")
        for x0, x1, label, v, total in self.bars:
            if x0 <= e.x < x1:
                lines = [(None, f"{label} · {total} điểm")]
                lines += [(c, f"{name}: {v.get(k) or 0}") for k, name, c in SERIES]
                self._tooltip(e.x, e.y, lines)
                return


class BalanceLineChart(_Base):
    """Số điểm hiện có theo ngày: 1 đường 2px, crosshair + tooltip khi rê chuột."""

    COLOR = "#2a78d6"

    def __init__(self, master, days: int = 30):
        super().__init__(master, 240, f"Điểm hiện có ({days} ngày)")
        self.days = days
        self.data = []  # [(label, value)]
        self.pts = []
        self.box = None

    def set(self, data: list) -> None:
        self.data = [(l, v) for l, v in data if v is not None][-self.days:]
        self.redraw()

    def redraw(self) -> None:
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        y0 = self._title()
        self.pts = []
        if not self.data:
            self.create_text(w / 2, h / 2, text="Chưa có lịch sử", fill=MUTED, font=FONT)
            return
        left, right = self.tw("00,000") + 10, w - 8
        top, bottom = y0 + self.lh() + 10, h - self.lh() - 6
        vals = [v for _, v in self.data]
        lo, hi = min(vals), max(vals)
        pad = max((hi - lo) * 0.15, 10)
        lo, hi = max(0, lo - pad), hi + pad
        self.box = (left, right, top, bottom)
        for i in range(4):
            y = bottom - (bottom - top) * i / 3
            self.create_line(left, y, right, y, fill=GRID if i else AXIS)
            self.create_text(left - 6, y, text=f"{int(lo + (hi - lo) * i / 3):,}", anchor="e", fill=MUTED, font=FONT)
        n = len(self.data)
        for i, (label, v) in enumerate(self.data):
            x = left + (right - left) * (i / (n - 1) if n > 1 else 0.5)
            y = bottom - (bottom - top) * (v - lo) / (hi - lo)
            self.pts.append((x, y, label, v))
        if n > 1:
            self.create_line(*[c for x, y, *_ in self.pts for c in (x, y)], fill=self.COLOR, width=2)
        x, y, _, v = self.pts[-1]  # điểm cuối: chấm + nhãn trực tiếp
        self.create_oval(x - 4, y - 4, x + 4, y + 4, fill=self.COLOR, outline=SURFACE, width=2)
        self.create_text(x - 6, y - 8, text=f"{v:,}", anchor="se", fill=INK, font=FONT_B)
        step = self.label_step([p[2] for p in self.pts], right - left)
        for i, (x, _, label, _) in enumerate(self.pts):
            if (n - 1 - i) % step == 0:
                self.create_text(x, bottom + 4, text=label, anchor="n" if i < n - 1 else "ne",
                                 fill=MUTED, font=FONT)

    def _on_move(self, e) -> None:
        if not self.pts or not self.box:
            return
        _, _, top, bottom = self.box
        x, y, label, v = min(self.pts, key=lambda p: abs(p[0] - e.x))
        self.delete("hover")
        self.create_line(x, top, x, bottom, fill=AXIS, dash=(2, 2), tags="hover")
        self.create_oval(x - 5, y - 5, x + 5, y + 5, fill=self.COLOR, outline=SURFACE, width=2, tags="hover")
        self._tooltip(x, y, [(None, label), (self.COLOR, f"Điểm: {v:,}")])
