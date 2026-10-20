"""Bảng truy vấn dùng chung: không trùng trong bảng, không lặp lại câu đã dùng gần đây."""

import csv
import json
import random
import threading
from datetime import date, timedelta
from pathlib import Path

from .catalog import all_queries


class QueryBank:
    """Bảng truy vấn dùng chung cho tất cả profile (thread-safe)."""

    def __init__(self, history_path: Path, history_days: int = 30):
        self.history_path = history_path
        self.history_days = history_days
        self.lock = threading.Lock()
        self.rows: list = []  # {"id", "category", "query", "used_by"}
        self.next_id = 1
        self.on_change = None  # callback(kind, payload)
        self.history = self._load_history()

    # ------------------------------------------------------------ history
    def _load_history(self) -> dict:
        try:
            data = json.loads(self.history_path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        cutoff = (date.today() - timedelta(days=self.history_days)).isoformat()
        return {q: d for q, d in data.items() if d >= cutoff}

    def _save_history(self) -> None:
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        self.history_path.write_text(json.dumps(self.history, ensure_ascii=False), encoding="utf-8")

    def clear_history(self) -> None:
        with self.lock:
            self.history = {}
            self._save_history()

    # ------------------------------------------------------------ generation
    def _pick(self, n: int) -> list:
        used = set(self.history) | {r["query"].lower() for r in self.rows}
        pools = {}
        for cat, q in all_queries():
            if q.lower() not in used:
                pools.setdefault(cat, []).append(q)
        if not pools:  # đã dùng hết -> quên lịch sử cũ
            self.history = {}
            return self._pick(n)
        for pool in pools.values():
            random.shuffle(pool)
        out, last_cat = [], None
        while len(out) < n and any(pools.values()):
            cats = [c for c in pools if pools[c]]
            random.shuffle(cats)
            for cat in cats:
                if len(out) >= n:
                    break
                if cat == last_cat and len(cats) > 1:
                    continue
                out.append((cat, pools[cat].pop()))
                last_cat = cat
        return out

    def _make_rows(self, pairs: list) -> list:
        rows = []
        for cat, q in pairs:
            rows.append({"id": self.next_id, "category": cat, "query": q, "used_by": ""})
            self.next_id += 1
        return rows

    def generate(self, n: int) -> list:
        """Tạo bảng mới gồm n câu (thay bảng cũ)."""
        with self.lock:
            self.rows = []
            self.rows = self._make_rows(self._pick(n))
            rows = list(self.rows)
        self._emit("reset", rows)
        return rows

    def take(self, who: str) -> str:
        """Lấy câu chưa dùng tiếp theo cho một profile; tự sinh thêm khi hết."""
        with self.lock:
            row = next((r for r in self.rows if not r["used_by"]), None)
            added = []
            if row is None:
                added = self._make_rows(self._pick(30))
                self.rows.extend(added)
                row = added[0]
            row["used_by"] = who
            self.history[row["query"].lower()] = date.today().isoformat()
            self._save_history()
        for r in added:
            self._emit("add", r)
        self._emit("update", row)
        return row["query"]

    def export_csv(self, path: str) -> None:
        with self.lock, open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["#", "Lĩnh vực", "Truy vấn", "Đã dùng bởi"])
            for r in self.rows:
                w.writerow([r["id"], r["category"], r["query"], r["used_by"]])

    def _emit(self, kind, payload) -> None:
        if self.on_change:
            self.on_change(kind, payload)
