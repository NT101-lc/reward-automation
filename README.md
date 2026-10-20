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

Giao diện chạy trong cửa sổ riêng bằng Edge WebView2 (có sẵn trên Windows 10/11). Chỉ mở được 1 cửa sổ app cùng lúc.

Nhấp đúp `run.bat`, hoặc:
```bash
python -m rewards_bot
```

1. Trang **Tài khoản**: bấm **Thêm tài khoản** cho mỗi tài khoản Microsoft.
2. Bấm **Đăng nhập** ở dòng tài khoản đó. Cửa sổ mở 2 tab: đăng nhập ở tab Rewards, rồi kiểm tra tab **bing.com**
   cũng là **cùng tài khoản** (góc phải). Xong thì **đóng cửa sổ** (chỉ làm 1 lần).
3. Bấm **Kiểm tra**: bot tự chẩn đoán (không search) và báo từng mục ✓/!/✕ kèm cách sửa.
4. Chọn việc bot sẽ làm ở mục "Việc bot sẽ làm khi chạy", rồi bấm **Chạy** (1 tài khoản) hoặc **Chạy tất cả**.
   Ô "Số tài khoản chạy cùng lúc" giới hạn số cửa sổ chạy song song. **Dừng tất cả** để dừng.

### Trang Tổng quan
- Chọn tài khoản ở hàng trên cùng. Khối bên trái là số điểm hiện có, điểm hôm nay, tháng này và trọn đời.
- **Thẻ đóng dấu hôm nay**: mỗi task có điểm (search PC/Mobile, Daily Set, Keep earning) là một con dấu dùng ảnh
  từ trang Rewards; làm xong thì dấu sáng lên. Bên dưới là tiến độ search PC/Mobile.
- Biểu đồ điểm mỗi ngày (PC / Mobile / Offers, 14 ngày) và số điểm hiện có (30 ngày); rê chuột để xem số liệu.
- Danh sách task hôm nay theo nhóm, có icon và trạng thái.
- **Làm mới** chỉ đọc điểm từ Rewards (chạy ẩn), không làm task.
- **Kiểm tra** (tự chẩn đoán, không search): đăng nhập Rewards, Points breakdown, thẻ Daily Set, bing.com có đúng
  tài khoản không (desktop và mobile), profile có bị cửa sổ khác giữ không, proxy. Cũng chạy được bằng
  `python -m rewards_bot --check`.

### Bot tự bảo vệ khi chạy
- Trước khi search, đối chiếu điểm trên bing.com với Rewards; **sai tài khoản thì không search** (để không cộng nhầm).
- Cứ 3 lượt search đọc lại điểm; **6 lượt liên tiếp không được cộng thì dừng** loại search đó và ghi lý do.
- Thẻ Daily Set / Keep earning được bấm đúng vị trí (kể cả 2 thẻ trùng tên); thẻ nào làm xong mà chưa được ghi
  nhận sẽ được liệt kê trong nhật ký.
- Nhật ký lưu ở `data/logs/<ngày>.log` (giữ 14 ngày) – gửi file này khi cần báo lỗi.
- Tài khoản có thư mục phiên đăng nhập cố định: đổi tên không phải đăng nhập lại.
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


## Bảo mật

- **Thư mục `data/`** (phiên đăng nhập, cookie Microsoft) được khóa quyền ngay lần chạy đầu: chỉ tài khoản Windows
  của bạn và SYSTEM đọc được. Thư mục này không bao giờ được commit lên git.
- **Proxy**: trình duyệt của bot chạy với `--no-proxy-server`, bỏ qua proxy hệ thống và file PAC. Nếu máy đang bật
  proxy, nhật ký sẽ ghi lại để bạn biết. Muốn đi qua proxy (mạng công ty), tắt tùy chọn này trong trang Cài đặt.
- **HTTPS** luôn được kiểm tra chứng chỉ, nên proxy chen giữa dùng chứng chỉ giả sẽ bị chặn.
- **Giao diện** có Content-Security-Policy: chỉ chạy script của app, chỉ tải ảnh từ bing.com. Dữ liệu lấy từ trang
  Rewards luôn được escape. Mọi giá trị giao diện gửi xuống Python (cài đặt, tên tài khoản, cổng, lệnh) đều được kiểm tra.
- **Chế độ Gắn vào Edge đang mở**: cổng debug cho phép mọi chương trình trên máy điều khiển Edge. Bot chỉ kết nối qua
  `127.0.0.1` và từ chối chạy nếu cổng bị mở ra mạng LAN. Chỉ bật Edge debug khi cần chạy bot.
- Giới hạn: phần mềm độc hại chạy dưới chính tài khoản Windows của bạn vẫn có thể đọc dữ liệu của bạn. Hãy giữ
  Windows và phần mềm diệt virus cập nhật.

## Chạy tự động hằng ngày (không mở giao diện)

```bash
python -m rewards_bot --run-all --headless
```
Đặt lệnh này trong Windows Task Scheduler, với thư mục bắt đầu là thư mục dự án (hoặc dùng `run.bat --run-all --headless`).

## Cấu trúc

```
rewards-bot/
├── rewards_bot/
│   ├── __main__.py         # điểm vào: python -m rewards_bot [--run-all | --check]
│   ├── cli.py              # chạy không giao diện
│   ├── core/
│   │   ├── bot.py          # bot cho 1 tài khoản: task, search, kiểm tra (diagnose)
│   │   ├── rewards_page.py # đọc trang Rewards (điểm, task, icon, Points breakdown)
│   │   ├── runner.py       # chạy nhiều tài khoản song song + ghi log ra file
│   │   ├── browser.py      # phát hiện trình duyệt đang giữ profile
│   │   ├── security.py     # khóa quyền data/, proxy, cổng debug
│   │   ├── instance.py     # chỉ 1 cửa sổ app chạy cùng lúc
│   │   └── config.py       # cài đặt, tài khoản, đọc/ghi file an toàn
│   ├── search/             # sinh câu search không trùng
│   └── ui/                 # webapp.py (pywebview) + web/ (index.html, style.css, app.js)
├── tests/                  # pytest: logic, dữ liệu, giao diện
├── data/                   # tự tạo khi chạy (không commit)
├── run.bat                 # mở app
├── check.bat               # chạy test
├── requirements.txt
└── requirements-dev.txt
```

## Phát triển

```bash
pip install -r requirements-dev.txt
```
Chạy `check.bat` (hoặc `python -m pytest -q tests`) trước mỗi lần commit.
