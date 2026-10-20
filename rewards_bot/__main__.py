"""
Microsoft Rewards Bot

    python -m rewards_bot                        # mở giao diện
    python -m rewards_bot --run-all [--headless] # chạy tất cả profile không cần giao diện
"""

import argparse


def main() -> None:
    ap = argparse.ArgumentParser(prog="rewards_bot")
    ap.add_argument("--run-all", action="store_true", help="chạy tất cả profile không mở giao diện")
    ap.add_argument("--headless", action="store_true", help="chạy ẩn trình duyệt")
    ap.add_argument("--classic", action="store_true", help="dùng giao diện tkinter cũ")
    args = ap.parse_args()
    if args.run_all:
        from .cli import run_cli
        run_cli(args.headless)
        return
    if not args.classic:
        try:
            from .ui.webapp import main as web_main
        except ImportError as e:  # chưa cài pywebview
            print(f"Không mở được giao diện web ({e}), dùng giao diện cũ. Cài: pip install pywebview")
        else:
            web_main()
            return
    from .gui.app import App
    App().mainloop()


if __name__ == "__main__":
    main()
