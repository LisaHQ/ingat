# ADR-0002 Nền tảng tổng hợp: cấu trúc gọn, các quy tắc an toàn bắt buộc, cách chạy hợp với DSM

[English](0002-synthesis-basis.md) · **Tiếng Việt** (bản dịch; bản tiếng Anh là bản chuẩn)

**Trạng thái:** Đã chấp nhận.

**Nói đơn giản:** Ba bản thiết kế nháp đã được so sánh. Ingat lấy bản nhỏ nhất làm nền, rồi thêm các quy tắc an toàn mạnh nhất của bản thứ hai và cách bản thứ ba chạy trên NAS.

## Bối cảnh

Ba đề xuất được chấm điểm theo hai góc nhìn. Góc nhìn A (Lens A: an toàn, tính đúng, thực tế của máy) chọn `safety` (43) hơn `container` (43, hòa điểm) và `lean` (41). Góc nhìn B (Lens B: một chủ sở hữu làm việc cùng các agent AI, thời gian tới lần dùng đầu tiên) chọn `lean` (49) hơn `safety` (44) và `container` (43). Cộng lại: lean 90, safety 87, container 86. Mỗi bên chấm liệt kê các lỗi bắt buộc phải sửa (must-fix) của phương án mình chọn thắng, và những phần nên ghép vào từ các phương án kia.

## Quyết định

Dùng **lean** làm nền cấu trúc (phạm vi nhỏ nhất: một chiến lược dữ liệu, một tập đóng các loại bước, mô-đun tối đa 600 dòng, các tệp của ứng dụng cộng một tệp ghi đè (override) được sinh ra, dự án khôi phục tách biệt `--r<seq>`, quy tắc đặt tên bản sao lưu riêng của ứng dụng, tiếp xúc thật với máy đích ngay từ M0). Ghép từ **safety** các quy tắc an toàn bắt buộc (safety floor) và mức bao phủ cho các ứng dụng (kiểm tra sẵn sàng qua TCP ổn định cho kho dữ liệu (store), container tác vụ có tên xác định trước, chụp lại log, các biến môi trường cần chủ sở hữu duyệt và các biến môi trường bị cấm, kiểm tra nhanh sau khi chạy (smoke) dạng khai báo tái hiện bài kiểm tra smoke bằng shell của ứng dụng PostgreSQL (the PostgreSQL consumer), mã thử thách gõ trên terminal cho lớp duyệt D (class D), trường dòng gốc (lineage), bảng mã thoát chính xác). Ghép từ **container** cách thực thi và mô hình lưu trữ trên DSM (trình thực thi (executor) chạy tách rời, mọi đọc ghi của tác vụ nằm trong một thư mục gốc POSIX thường và được chép rồi đổi tên vào thư mục chia sẻ, volume thăm dò để đo chỗ trống của thư mục gốc Docker, mã thoát khác 0 không được khai báo của các tác vụ ghi được coi là `unknown`, cổng kiểm tra phiên bản theo bậc, tự động bỏ những thao tác chỉ đụng tới phần nháp, `conformance` trong CI của ứng dụng). Mọi lỗi bắt buộc phải sửa từ cả hai góc nhìn đều đã được giải quyết; bảng đối chiếu từng lỗi nằm trong hồ sơ thiết kế riêng.

## Các phương án khác

Lấy nguyên `safety` (bị loại: khoảng 13 phần việc (slice) trước khi tới bản staging của ứng dụng PostgreSQL, ba chế độ tác vụ, một mô hình được dựng lại có nguy cơ lệch cách thoát ký tự (escape drift)). Lấy nguyên `container` (bị loại: 19 phần việc, một bộ sinh service dẫn xuất viết tay dùng `extends`/`!reset`, một mã định danh bản sao lưu phá vỡ quy tắc đặt tên bản sao lưu của ứng dụng PostgreSQL, `--approve` dùng được cho việc gỡ bỏ hoàn toàn (purge)).

## Hệ quả

Bản MVP khoảng 5.5k dòng mã chạy thật (5.2k Python) trong 7 phần việc ([ROADMAP.md](../ROADMAP.vi.md)), lớn hơn mức 4.8k của lean vì có trình thực thi, phần sẵn sàng, smoke, các biến cần chủ sở hữu duyệt và các bản sửa sau đánh giá. Ứng dụng thật đầu tiên (bản cài thử của ứng dụng SQLite, `lite-test`) chạy trên máy đích vào cuối M1, trong khoảng 3k dòng; bản staging của ứng dụng PostgreSQL (`pg-staging`) theo sau vào cuối M2.
