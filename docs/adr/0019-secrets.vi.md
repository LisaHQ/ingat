# ADR-0019 Bí mật (secrets)

[English](0019-secrets.md) · **Tiếng Việt** (bản dịch; bản tiếng Anh là bản chuẩn)

**Trạng thái:** Đã chấp nhận.

**Nói đơn giản:** Mật khẩu và khóa chỉ tồn tại dưới dạng tệp, được kiểm tra trước mỗi lần dùng. Chúng bị che trong mọi nội dung in ra, thông báo lỗi chỉ nêu tên khóa của chúng, và chúng không bao giờ được đưa vào bản sao lưu.

## Bối cảnh

Công cụ cũ đã làm lộ mã băm của một tệp `.env` ra stderr và vào nhật ký, và làm lộ một ký tự của mật khẩu trong một lỗi đọc cú pháp (parser error). Compose thay một tệp bí mật bị thiếu bằng một thư mục rỗng.

## Quyết định

Bí mật chỉ ở dạng tệp ([ARCHITECTURE.md](../ARCHITECTURE.vi.md) §9.4): được tạo một lần hoặc đặt từ stdin; trước mỗi lần gọi Compose đều kiểm tra đó là một tệp thường và không rỗng, còn nếu là thư mục thì từ chối; kiểu `Secret` tự che giá trị; lỗi chỉ nêu tên khóa; CI quét tìm bí mật mồi (canary); không bao giờ nằm trong bản sao lưu (bundle); chủ sở hữu tự giữ bí mật để khôi phục sau sự cố lớn (quyết định của chủ sở hữu OD-9; `export-config` ở M4).

## Các phương án khác

Bí mật dưới dạng biến thay thế (interpolation variable) của Compose (bị loại: chúng sẽ đi vào mô hình cấu hình (model) của Compose).

## Hệ quả

Mật khẩu thư của ứng dụng SQLite (the SQLite consumer) chỉ đến được container qua tệp env 0600 do Ingat tạo ra, cho tới khi ứng dụng đó đọc được mật khẩu từ một tệp.
