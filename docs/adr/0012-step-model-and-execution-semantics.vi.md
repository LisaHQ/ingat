# ADR-0012 Mô hình bước và ý nghĩa của việc thực thi

[English](0012-step-model-and-execution-semantics.md) · **Tiếng Việt** (bản dịch; bản tiếng Anh là bản chuẩn)

**Trạng thái:** Đã chấp nhận.

**Nói đơn giản:** Một trình thực thi duy nhất chạy mọi thao tác dưới dạng một danh sách các bước có kiểu, lấy từ một tập cố định. Mỗi bước được ghi lại trước khi chạy; các container trợ giúp có tên đoán trước được và luôn được dừng trước khi nhả khóa; và một lần sao lưu hay kiểm tra bị gián đoạn được tự động hoàn tác, nên không bao giờ chặn lần sau.

## Bối cảnh

Các bảng loại × giai đoạn, cơ chế thay thế (supersession) và ghép cặp của công cụ cũ đã sinh ra bế tắc và ngõ cụt (do các lần đánh giá và các lần chạy trên Docker thật của nó phát hiện). Giết tiến trình client `compose exec/run` không làm dừng tiến trình phía server (lỗi bắt buộc sửa theo góc nhìn B (Lens B)). Một lần sao lưu đêm bị sập không được chặn lần tiếp theo (lỗi bắt buộc sửa theo góc nhìn B).

## Quyết định

Một trình thực thi (executor) chung chạy trên một tập đóng các bước có kiểu, thuộc các lớp nháp (scratch) / đảo ngược được (reversible) / tiến (forward), nguyên khối (atomic) hoặc ngắt được (interruptible) ([LIFECYCLE.md](../LIFECYCLE.vi.md) §3.3); ý định được ghi chắc xuống đĩa (fsync) trước khi có tác động; mỗi bản cài (instance) chỉ có một thao tác đang mở, còn những tác vụ (task) mà một lần tạm dừng cho phép thì được ghi nhật ký bên trong chính thao tác đang tạm dừng; các container tác vụ có tên xác định, được gắn nhãn, đặt tên theo từng lần thử (`<instance>-x<seq>-<step>-a<attempt>`), được dừng và chờ dừng hẳn trước khi nhả khóa; một phép kiểm tra container mồ côi (orphan check) trước `resume`, `abandon` hay một thay đổi mới, từ chối khi có container mang nhãn thao tác đang chạy, và biến một container đã thoát thành bằng chứng được ghi lại trước khi xóa nó; mã thoát khác 0 không được khai báo của tác vụ ghi là `unknown`; `exec` có thay đổi chỉ chạy bên trong các dự án tách biệt; mọi tác vụ của `backup.steps` và `backup.verify` đều là nháp bất kể tác động của nó (và phải an toàn khi chạy lại nhiều lần (idempotent) trừ khi chỉ đọc); tự động bỏ (auto-abandon) chỉ áp dụng cho các loại thao tác không có bước tiến (prepare, backup, verify, drill), hoàn tác các bước đảo ngược được, được ghi lại và hiện trong `status`.

## Các phương án khác

Máy trạng thái riêng cho từng loại (bị loại: các lỗi của công cụ cũ). Không tự động bỏ (bị loại: chặn các lần sao lưu theo lịch). Tự động bỏ mọi thao tác không phá hủy (bị loại: góc nhìn A (Lens A) xem việc đó là che giấu lỗi; giới hạn nó vào các loại thao tác không thể đi qua điểm không quay lại (forward point), có ghi lại việc hoàn tác và việc gỡ dọn, thì vẫn giữ được bản ghi). Phân loại một tác vụ sao lưu theo tác động của chính nó (bị loại: lần sao lưu của ứng dụng SQLite (the SQLite consumer) ghi kết quả của nó vào trong ứng dụng, điều này sẽ biến một lần sao lưu đêm bị sập thành một bước tiến chặn mọi lần sao lưu sau đó và làm ứng dụng đang chạy bị tạm khóa (frozen) khi bỏ thao tác).

## Hệ quả

Ma trận sự cố (crash matrix) được sinh ra từ các danh sách bước. `resolve` (lớp D) có từ M3; trong M1-M2, mọi bước tiến của cả hai ứng dụng đều an toàn khi chạy lại hoặc quan sát được, nên chưa cần đến nó.
