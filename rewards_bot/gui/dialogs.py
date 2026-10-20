import tkinter as tk
from tkinter import ttk, messagebox

from .theme import BG


class ProfileDialog(tk.Toplevel):
    def __init__(self, master, profile=None):
        super().__init__(master)
        self.title("Profile")
        self.configure(bg=BG, padx=16, pady=16)
        self.resizable(False, False)
        self.transient(master)
        self.result = None
        p = profile or {"name": "", "mode": "managed", "cdp_port": 9222}

        ttk.Label(self, text="Tên profile").grid(row=0, column=0, sticky="w")
        self.name = tk.StringVar(value=p["name"])
        e = ttk.Entry(self, textvariable=self.name, width=32)
        e.grid(row=1, column=0, columnspan=2, sticky="we", pady=(2, 10))

        self.mode = tk.StringVar(value=p.get("mode", "managed"))
        ttk.Radiobutton(self, text="Cửa sổ riêng do app mở (khuyên dùng)", value="managed",
                        variable=self.mode, command=self._toggle).grid(row=2, column=0, columnspan=2, sticky="w")
        ttk.Radiobutton(self, text="Gắn vào trình duyệt đang mở (cổng debug)", value="cdp",
                        variable=self.mode, command=self._toggle).grid(row=3, column=0, columnspan=2, sticky="w")

        ttk.Label(self, text="Cổng CDP").grid(row=4, column=0, sticky="w", pady=(10, 0))
        self.port = tk.StringVar(value=str(p.get("cdp_port", 9222)))
        self.port_entry = ttk.Entry(self, textvariable=self.port, width=10)
        self.port_entry.grid(row=4, column=1, sticky="w", pady=(10, 0))

        bf = ttk.Frame(self)
        bf.grid(row=5, column=0, columnspan=2, sticky="e", pady=(16, 0))
        ttk.Button(bf, text="Hủy", command=self.destroy).pack(side="right")
        ttk.Button(bf, text="Lưu", style="Accent.TButton", command=self._ok).pack(side="right", padx=6)

        self._toggle()
        e.focus_set()
        self.bind("<Return>", lambda _e: self._ok())
        self.grab_set()
        self.wait_window()

    def _toggle(self):
        self.port_entry.configure(state="normal" if self.mode.get() == "cdp" else "disabled")

    def _ok(self):
        name = self.name.get().strip()
        if not name:
            messagebox.showwarning("Thiếu tên", "Hãy nhập tên profile.", parent=self)
            return
        try:
            port = int(self.port.get())
        except ValueError:
            port = 9222
        self.result = {"name": name, "mode": self.mode.get(), "cdp_port": port}
        self.destroy()

