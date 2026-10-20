import threading

from rewards_bot.search.bank import QueryBank
from rewards_bot.search.catalog import CATEGORIES, all_queries


def test_catalog_has_no_duplicates():
    qs = [q.lower() for _, q in all_queries()]
    assert len(qs) == len(set(qs))
    assert len(CATEGORIES) >= 10


def test_table_unique_and_varied(tmp_path):
    rows = QueryBank(tmp_path / "h.json").generate(60)
    assert len({r["query"] for r in rows}) == 60
    assert all(a["category"] != b["category"] for a, b in zip(rows, rows[1:]))


def test_parallel_takes_never_repeat(tmp_path):
    bank = QueryBank(tmp_path / "h.json")
    bank.generate(10)
    got, lock = [], threading.Lock()

    def worker(name):
        for _ in range(50):
            q = bank.take(name)
            with lock:
                got.append(q)

    ts = [threading.Thread(target=worker, args=(n,)) for n in "ABC"]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(got) == 150 and len(set(got)) == 150


def test_used_queries_not_reused_after_restart(tmp_path):
    f = tmp_path / "h.json"
    used = {QueryBank(f).take("A") for _ in range(20)}
    fresh = {r["query"] for r in QueryBank(f).generate(300)}
    assert not used & fresh
