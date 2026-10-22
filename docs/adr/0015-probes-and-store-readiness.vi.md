# ADR-0015 Phép kiểm tra sẵn sàng: ba kiểu, khoảng ổn định, giá trị dạng "một trong", sự sẵn sàng của kho dữ liệu

[English](0015-probes-and-store-readiness.md) · **Tiếng Việt** (bản dịch; bản tiếng Anh là bản chuẩn)

**Trạng thái:** Đã chấp nhận.

**Nói đơn giản:** Ingat kiểm tra một ứng dụng đã sẵn sàng hay chưa theo ba cách (trạng thái health của Docker, một lệnh chạy bên trong container, một yêu cầu HTTP), và mỗi phép kiểm tra phải giữ kết quả tốt trong một khoảng thời gian định sẵn. Một cơ sở dữ liệu chỉ được coi là sẵn sàng sau khi phép kiểm tra sẵn sàng của chính nó qua, không bao giờ chỉ vì container của nó báo "healthy".

## Bối cảnh

Một container PostgreSQL báo healthy trong khi máy chủ khởi tạo tạm thời của image vẫn đang chạy (một lần chạy trên Docker thật của công cụ cũ đã cho thấy điều đó); một healthcheck Compose dùng `pg_isready` thì đi qua socket, và `run --no-deps` bỏ qua các điều kiện `depends_on`. Đường quay về bản cũ (rollback) chỉ đổi mã của ứng dụng PostgreSQL (the PostgreSQL consumer) báo lược đồ (schema) của nó là `accepted`. Các phép kiểm tra HTTP từ container trợ giúp phá vỡ quy tắc không để lại dấu vết (lỗi bắt buộc sửa theo góc nhìn A (Lens A)).

## Quyết định

Các kiểu phép kiểm tra sẵn sàng (probe): `health`, `exec` (bên trong container đích) và `http` (từ container Ingat qua loopback của máy tới cổng được mở ra ngoài; không áp dụng khi chạy tách biệt). Khoảng ổn định `stable`; các kỳ vọng JSON chấp nhận một giá trị hoặc một danh sách "một trong các giá trị" (một schema `accepted` bên cạnh `current` cho `rollback --accept-schema`, M3); header khớp chính xác (`header_equals`) hoặc theo chuỗi con (`header_contains`); mọi lần khởi động kho dữ liệu (store) đều chờ phép kiểm tra `ready` của kho đó (với một kho PostgreSQL, như trong `fx-pg`: `pg_isready -h 127.0.0.1`, ổn định 15 s). Phần `[[smoke]]` dạng khai báo tái hiện bài kiểm tra smoke bằng shell của ứng dụng PostgreSQL với cùng độ chặt (ví dụ một header `cache-control: no-cache` chính xác; schema chỉ `current`, còn `accepted` chỉ trên đường quay về bản cũ); phép kiểm tra định danh image được tích hợp sẵn.

## Các phương án khác

Container trợ giúp để kiểm tra (bị loại: để lại dấu vết). Tham gia vào mạng của bản cài (bị loại: đó là một thay đổi). Chỉ dùng health của Docker (bị loại: trường hợp máy chủ khởi tạo ở trên).

## Hệ quả

Phần kiểm tra nhanh sau khi chạy (smoke) ngang bằng bài kiểm tra cũ có ở M2, trước khi bài kiểm tra smoke bằng shell của ứng dụng PostgreSQL có thể được bỏ (lỗi bắt buộc sửa theo góc nhìn B (Lens B)).
