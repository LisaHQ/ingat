# ADR-0018 Kiểm soát biến môi trường của ứng dụng và các chốt chặn (holds)

[English](0018-app-environment-control-and-holds.md) · **Tiếng Việt** (bản dịch; bản tiếng Anh là bản chuẩn)

**Trạng thái:** Đã chấp nhận.

**Nói đơn giản:** Một ứng dụng khai báo mọi thiết lập mà nó nhận. Có thiết lập chỉ được đổi khi có mức duyệt cao nhất, có thiết lập bị cấm, và có thiết lập do Ingat tự điền. Các bản sao để thử được gắn chốt chặn (holds): những thiết lập ngăn chúng gửi thư thật hoặc kết nối ra bên ngoài.

## Bối cảnh

Ứng dụng SQLite (the SQLite consumer) chỉ gửi thư thật ra ngoài khi có một biến bật tính năng mà chỉ chủ sở hữu được đặt; image của nó cố định đường dẫn tới cơ sở dữ liệu và thư mục dữ liệu; khôi phục dữ liệu cũ hơn vào một hệ thống đang chạy thật (live topology) có thể làm thư bị gửi ra ngoài thêm lần nữa.

## Quyết định

Các khóa `[app_env]` khai báo `required`, `allowed`, `pattern`, `secret`, `owner_gated`, `tool_managed`, và manifest liệt kê các khóa `forbidden`. Thay đổi cần chủ sở hữu cho phép (owner-gated) thuộc lớp duyệt D (class D). Các lần chạy cách ly (isolated run) áp dụng `[holds]`, bỏ các khóa owner-gated và các khóa bí mật, và dùng mạng nội bộ. Chốt chặn cũng mang những giá trị mà một dịch vụ cần để khởi động khi không có đường mạng mặc định (default route) (dịch vụ web của ứng dụng PostgreSQL cần được đặt địa chỉ proxy tin cậy (trusted proxy); `fx-pg` làm giống như vậy). Ứng dụng có tác động ra bên ngoài chỉ khôi phục qua tác vụ (task) khôi phục của chính nó và kết thúc ở trạng thái `held`.

## Các phương án khác

Tệp biến môi trường (env) viết tự do (bị loại: không có kiểm soát duyệt, và dữ liệu có thể bị chuyển hướng sang nơi khác).

## Hệ quả

Tệp env của ứng dụng SQLite trở thành một tệp do Ingat tạo ra; chủ sở hữu sửa các giá trị trong `instance.toml` và đặt bí mật bằng `ingat secret set`.
