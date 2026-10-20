# Microsoft Rewards Bot (giao diện, nhiều tài khoản)

Tự làm Daily Set, Keep earning (link, poll, quiz cơ bản), search PC + Mobile, search ảnh trên Bing Images
và browse web trong N phút. Chạy được nhiều tài khoản/cửa sổ **song song**, có dashboard theo dõi điểm và task.

> ⚠️ Microsoft Rewards cấm dùng bot. Tài khoản có thể bị khóa hoặc mất điểm. Bạn tự chịu rủi ro.

## Cài đặt

```bash
pip install -r requirements.txt
```

Mặc định app dùng Microsoft Edge có sẵn trên Windows. Nếu muốn dùng Chromium của Playwright, chạy `python -m playwright install chromium` rồi chọn Chromium trong trang Cài đặt.

## Sử dụng

Giao diện chạy trong cửa sổ riêng bằng Edge WebView2 (có sẵn trên Windows 10/11). Nếu thiếu `pywebview`, app tự
quay về giao diện tkinter cũ (hoặc chạy `python -m rewards_bot --classic`).

Nhấp đúp `run.bat`, hoặc:
```bash
python -m rewards_bot
```

1. Trang **Tài khoản**: bấm **Thêm tài khoản** cho mỗi tài khoản Microsoft.
2. Bấm **Đăng nhập** ở dòng tài khoản đó, đăng nhập trong cửa sổ vừa mở rồi **đóng cửa sổ** (chỉ làm 1 lần).
3. Chọn việc bot sẽ làm ở mục "Việc bot sẽ làm khi chạy", rồi bấm **Chạy** (1 tài khoản) hoặc **Chạy tất cả**.
   Ô "Số tài khoản chạy cùng lúc" giới hạn số cửa sổ chạy song song. **Dừng tất cả** để dừng.

### Trang Tổng quan
- Chọn tài khoản ở hàng trên cùng. Khối bên trái là số điểm hiện có, điểm hôm nay, tháng này và trọn đời.
- **Thẻ đóng dấu hôm nay**: mỗi task có điểm (search PC/Mobile, Daily Set, Keep earning) là một con dấu dùng ảnh
  từ trang Rewards; làm xong thì dấu sáng lên. Bên dưới là tiến độ search PC/Mobile.
- Biểu đồ điểm mỗi ngày (PC / Mobile / Offers, 14 ngày) và số điểm hiện có (30 ngày); rê chuột để xem số liệu.
- Danh sách task hôm nay theo nhóm, có icon và trạng thái.
- **Làm mới** chỉ đọc điểm từ Rewards (chạy ẩn), không làm task.
- Số liệu PC/Mobile lấy từ hộp **Points breakdown** trên trang Earn. Lịch sử lưu ở `data/points_history.json`,
  dữ liệu lần cuối ở `data/dashboard.json`.

### Task thêm
- **Search ảnh**: tìm trên Bing Images (mặc định 6 lượt), rồi mở xem một ảnh.
- **Browse**: lướt các trang tin tức/kiến thức trong N phút (mặc định 30), cuộn trang và đi theo link nội bộ. Mặc định **tắt**.
  Task "browse với Edge" thường được tính qua tài khoản đăng nhập trong chính Edge, nên chạy ở chế độ *Gắn vào Edge đang mở* (Edge đã đăng nhập) thì dễ được tính hơn.
- Số lượt và số phút chỉnh trong trang Cài đặt.

### Câu search
Bot tự sinh câu search từ 15 lĩnh vực (khoảng 2.400 câu): không trùng nhau, hai câu liền nhau không cùng lĩnh vực,
các tài khoản không tìm cùng một câu, và câu đã dùng không lặp lại trong N ngày (lưu ở `data/search_history.json`).

### Hai cách chạy nhiều cửa sổ
- **Cửa sổ riêng** (khuyên dùng): mỗi tài khoản có thư mục `data/profiles/<tên>` riêng, mỗi tài khoản mở 1 cửa sổ.
- **Gắn vào Edge đang mở**: tự mở Edge với cổng debug, mỗi cửa sổ một cổng và một thư mục:
  ```bash
  msedge.exe --remote-debugging-port=9222 --user-data-dir="C:\EdgeRewards1"
  ```
  ```bash
  msedge.exe --remote-debugging-port=9223 --user-data-dir="C:\EdgeRewards2"
  ```
  Đăng nhập trong từng cửa sổ, rồi thêm tài khoản chế độ "Gắn vào Edge đang mở" với cổng 9222 hoặc 9223.
  (Edge không cho debug trên profile mặc định, nên phải dùng `--user-data-dir` riêng.)


## Chạy tự động hằng ngày (không mở giao diện)

```bash
python -m rewards_bot --run-all --headless
```
Đặt lệnh này trong Windows Task Scheduler, với thư mục bắt đầu là thư mục dự án (hoặc dùng `run.bat --run-all --headless`).

## Cấu trúc

```
rewards-bot/
├── rewards_bot/
│   ├── __main__.py         # điểm vào: python -m rewards_bot
│   ├── cli.py              # chế độ chạy không giao diện
│   ├── core/
│   │   ├── bot.py          # bot cho 1 tài khoản: task, search, giả lập mobile
│   │   ├── rewards_page.py # đọc trang Rewards (điểm, task, icon, Points breakdown)
│   │   ├── runner.py       # chạy nhiều tài khoản song song
│   │   └── config.py       # cài đặt, danh sách tài khoản, đường dẫn dữ liệu
│   ├── search/
│   │   ├── catalog.py      # lĩnh vực, chủ đề, mẫu câu
│   │   └── bank.py         # sinh câu search và lịch sử chống trùng
│   ├── ui/
│   │   ├── webapp.py       # cửa sổ pywebview + API cho giao diện
│   │   └── web/            # index.html, style.css, app.js
│   └── gui/                # giao diện tkinter cũ (--classic)
├── data/                   # tự tạo khi chạy: settings, lịch sử, phiên đăng nhập (không commit)
├── run.bat
├── requirements.txt
└── README.md
```
