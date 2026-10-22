# ADR-0005 Các thao tác thay đổi Docker chạy trong một container trình thực thi tách rời

[English](0005-detached-executor-container.md) · **Tiếng Việt** (bản dịch; bản tiếng Anh là bản chuẩn)

**Trạng thái:** Đã chấp nhận.

**Nói đơn giản:** Hầu hết mọi thay đổi với Docker chạy trong một container trợ giúp riêng, tự chạy tiếp một mình; terminal của bạn chỉ theo dõi. Vì vậy một kết nối SSH bị ngắt hay một cửa sổ bị đóng không thể làm dừng giữa chừng một lần sao lưu, một lần cập nhật hay một lần cập nhật dữ liệu. Ngoại lệ là tác vụ trò chuyện với bạn trong terminal: nó chạy từ chính cửa sổ của bạn.

## Bối cảnh

Phần chạy lệnh của công cụ cũ chỉ xử lý SIGTERM; SIGHUP giết bộ điều khiển trong khi một tiến trình con đang thay đổi vẫn chạy tiếp sau khi khóa đã được nhả (các lỗi chặn (blocking) trong lần đánh giá cuối của nó). Việc `docker run -i -t` qua SSH có chuyển tiếp tín hiệu và có sống sót khi phiên làm việc bị rớt hay không vẫn chưa được kiểm chứng (cả góc nhìn A lẫn góc nhìn B (Lens A, Lens B) đều nêu điểm này). Góc nhìn B chỉ muốn có trình thực thi tách rời làm phương án dự phòng; góc nhìn A yêu cầu dùng nó mặc định.

## Quyết định

Mọi thao tác cần giữ khóa (lock) mà thay đổi Docker đều chạy trong `ingat-exec-<instance>` (`docker run -d --rm --stop-timeout 120`), hoặc `ingat-exec--host` cho phạm vi toàn máy, do CLI khởi động sau khi lập kế hoạch và duyệt; CLI chỉ theo dõi. Tên container là một khóa loại trừ (mutex) thứ hai. Lệnh hủy là một tệp, được tôn trọng ở ranh giới giữa các bước và trong các vòng chờ; SIGINT, SIGTERM, SIGHUP và SIGQUIT gửi tới trình thực thi (executor) đều được coi là yêu cầu hủy. Trong CLI chỉ chạy các tác vụ (task) một bước ở tiền cảnh có đọc ghi qua terminal, và ba lệnh ngắn thay đổi trạng thái của công cụ nhưng không đụng tới đối tượng Docker nào: `host init`, `init`, `secret set` ([ARCHITECTURE.md](../ARCHITECTURE.vi.md) §4).

## Các phương án khác

Container công cụ gắn với terminal và bỏ qua SIGHUP (bị loại làm mặc định: khi đó tính đúng đắn phụ thuộc vào hành vi chưa kiểm chứng của docker client trên DSM, ở mức độ tin cậy trong thứ tự ưu tiên). Một tiến trình nền thường trú trên máy (host daemon) (bị loại: cần một cổng lắng nghe và các trạng thái vòng đời).

## Hệ quả

Thêm khoảng 250 dòng (phần theo dõi, hủy, gắn vào, phát hiện trình thực thi biến mất). Mất phiên làm việc không bao giờ làm dừng một lần cập nhật dữ liệu (migrate) giữa chừng. `docker kill` trình thực thi là biện pháp cuối cùng có ghi trong tài liệu, được phép kiểm tra container mồ côi (orphan check) xử lý ([ADR-0012](0012-step-model-and-execution-semantics.vi.md)).
