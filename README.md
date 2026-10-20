# Microsoft Rewards Bot (giao diện, nhiều profile)

Tự làm Daily Set, More Activities (link, poll, quiz cơ bản), tìm kiếm PC + Mobile, search ảnh trên Bing Images
và browse web trong N phút. Chạy được nhiều tài khoản/cửa sổ **song song**, có dashboard theo dõi điểm và task.

> ⚠️ Microsoft Rewards cấm dùng bot. Tài khoản có thể bị khóa hoặc mất điểm. Bạn tự chịu rủi ro.

## Cài đặt

```bash
pip install -r requirements.txt
```

Mặc định app dùng Microsoft Edge có sẵn trên Windows. Nếu muốn dùng Chromium của Playwright, chạy `python -m playwright install chromium` rồi chọn `chromium` trong tab Cài đặt.

## Sử dụng

Giao diện chạy trong cửa sổ riêng bằng Edge WebView2 (có sẵn trên Windows 10/11). Nếu thiếu `pywebview`, app tự
quay về giao diện tkinter cũ (hoặc chạy `python -m rewards_bot --classic`).

Nhấp đúp `run.bat`, hoặc:
```bash
python -m rewards_bot
```

1. Tab **Profiles**: bấm **+ Thêm** cho mỗi tài khoản.
2. Chọn profile, bấm **Đăng nhập**. Đăng nhập Microsoft trong cửa sổ vừa mở rồi **đóng cửa sổ** đó (chỉ cần làm 1 lần).
3. Bấm **▶ Chạy tất cả** hoặc chọn vài profile (giữ Ctrl) rồi bấm **▶ Chạy đã chọn**. Bấm **■ Dừng** để dừng.
   Ô "Số profile chạy cùng lúc" giới hạn số cửa sổ chạy song song.

### Dashboard
- 4 ô tổng quan: tổng điểm, điểm task hôm nay, số task đã xong, số profile đang chạy.
- Bảng bên trái liệt kê từng profile với điểm, điểm hôm nay, số task xong và giờ cập nhật.
- Chọn một profile để xem bên phải danh sách task theo nhóm (Daily Set, More Activities, Tìm kiếm, Task thêm), mỗi task có điểm hoặc tiến độ và trạng thái ✓/○.
- Tab **Biểu đồ** (bên phải): tiến độ search PC/Mobile hôm nay, cột chồng điểm mỗi ngày (PC / Mobile / Offers,
  14 ngày) và đường số điểm hiện có (30 ngày). Rê chuột để xem số liệu. Lịch sử lưu ở `data/points_history.json`.
- Số liệu PC/Mobile lấy từ hộp **Points breakdown** trên trang Earn của Rewards.
- Nút **↻ Làm mới** chỉ đọc điểm từ Rewards (chạy ẩn), không làm task.
- Dữ liệu lần cuối được lưu ở `data/dashboard.json`, nên mở app lên là thấy ngay.

### Task thêm
- **Search ảnh**: tìm trên Bing Images (mặc định 6 lượt) bằng câu lấy từ bảng search, rồi mở xem một ảnh.
- **Browse**: lướt các trang tin tức/kiến thức trong N phút (mặc định 30), cuộn trang và đi theo link nội bộ. Mặc định **tắt**.
  Task "browse với Edge" thường được tính qua tài khoản đăng nhập trong chính Edge, nên chạy ở chế độ *Gắn vào trình duyệt đang mở* (Edge đã đăng nhập) thì dễ được tính hơn.
- Số lượt và số phút chỉnh trong tab Cài đặt. Bật/tắt ở thanh tùy chọn trong tab Profiles.

### Hai cách chạy nhiều cửa sổ
- **Cửa sổ riêng** (khuyên dùng): mỗi profile có thư mục `data/profiles/<tên>` riêng, mỗi profile mở 1 cửa sổ.
- **Gắn vào trình duyệt đang mở**: tự mở Edge với cổng debug, mỗi cửa sổ một cổng và một thư mục:
  ```bash
  msedge.exe --remote-debugging-port=9222 --user-data-dir="C:\EdgeRewards1"
  ```
  ```bash
  msedge.exe --remote-debugging-port=9223 --user-data-dir="C:\EdgeRewards2"
  ```
  Đăng nhập trong từng cửa sổ, rồi thêm profile chế độ "Gắn vào trình duyệt đang mở" với cổng 9222 hoặc 9223.
  (Edge không cho debug trên profile mặc định, nên phải dùng `--user-data-dir` riêng.)

### Bảng search
Tab **Bảng search** sinh câu truy vấn ngẫu nhiên từ 15 lĩnh vực (công nghệ, lập trình, khoa học, sức khỏe, ẩm thực, du lịch, lịch sử, thể thao, tài chính, giải trí, thiên nhiên, giáo dục, nhà cửa, xe cộ, địa lý), khoảng 2.400 câu.
- Không có câu nào trùng nhau trong bảng, và hai câu liền nhau không cùng lĩnh vực.
- Câu đã dùng được lưu vào `data/search_history.json` và không lặp lại trong N ngày (mặc định 30).
- Các profile lấy câu lần lượt từ bảng, nên hai tài khoản không tìm cùng một câu. Cột "Đã dùng bởi" cho biết profile nào đã dùng câu đó. Hết bảng thì app tự sinh thêm.
- Có thể xuất bảng ra CSV.

## Chạy tự động hằng ngày (không mở giao diện)

```bash
python -m rewards_bot --run-all --headless
```
Đặt lệnh này trong Windows Task Scheduler, với thư mục bắt đầu là thư mục dự án (hoặc dùng `run.bat --run-all --headless`).

## Cấu trúc

```
rewards-bot/
├── rewards_bot/
│   ├── __main__.py       # điểm vào: python -m rewards_bot
│   ├── cli.py            # chế độ chạy không giao diện
│   ├── core/
│   │   ├── bot.py        # bot cho 1 profile: quest, tìm kiếm, giả lập mobile
│   │   ├── runner.py     # chạy nhiều profile song song
│   │   └── config.py     # cài đặt, danh sách profile, đường dẫn dữ liệu
│   ├── search/
│   │   ├── catalog.py    # lĩnh vực, chủ đề, mẫu câu
│   │   └── bank.py       # bảng truy vấn và lịch sử chống trùng
│   └── gui/
│       ├── app.py        # cửa sổ chính (Tkinter)
│       ├── dashboard.py  # tab Dashboard
│       ├── dialogs.py    # hộp thoại thêm/sửa profile
│       └── theme.py      # màu sắc
├── data/                 # tự tạo khi chạy: settings.json, search_history.json, dashboard.json, profiles/
├── run.bat
├── requirements.txt
└── README.md
```
