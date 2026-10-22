# ADR-0010 Một chiến lược dữ liệu trong v1: các tác vụ riêng của ứng dụng

[English](0010-one-data-strategy-app-native-tasks.md) · **Tiếng Việt** (bản dịch; bản tiếng Anh là bản chuẩn)

**Trạng thái:** Được thay thế bởi [ADR-0031](0031-data-providers.vi.md) (2026-10-19): một chiến lược thứ hai, `provider`, được thêm vào bên cạnh `tasks`; lập luận chống lại việc đặt mã riêng cho từng loại cơ sở dữ liệu (engine) trong `src/` vẫn giữ nguyên.

**Nói đơn giản:** Quy tắc dữ liệu đầu tiên: ứng dụng tự sao lưu và khôi phục bằng lệnh của chính nó, còn Ingat làm mọi việc xung quanh (dừng, niêm phong, kiểm tra, lưu giữ). ADR-0031 đã thay thế nó bằng cách thêm một cách thứ hai; lý do của nó để giữ mã cơ sở dữ liệu bên ngoài phần lõi của Ingat vẫn còn nguyên giá trị.

## Bối cảnh

Docker thật đã phát hiện các lỗi về cơ sở dữ liệu bên trong mã PostgreSQL của công cụ cũ (các lần chạy trên Docker thật của nó cho thấy điều đó). Mã chung cho các loại cơ sở dữ liệu không thể mang ý nghĩa riêng của từng ứng dụng, như chốt chặn (hold) thư gửi ra ngoài của ứng dụng SQLite (the SQLite consumer), hay việc cấp quyền theo vai trò và phép kiểm tra bất biến sau khi khôi phục của ứng dụng PostgreSQL (the PostgreSQL consumer).

## Quyết định

Chỉ có các chiến lược `tasks` và `none`. Ingat phụ trách việc cho ứng dụng ngừng ghi (quiescence), vùng chuẩn bị, quy tắc về nội dung sao lưu (payload), tính mã băm, niêm phong, kiểm tra, giữ lại theo chính sách và thử khôi phục (drill); các tác vụ của ứng dụng tạo ra và đọc định dạng sao lưu riêng của nó.

## Các phương án khác

Các chiến lược tích hợp sẵn cho từng loại cơ sở dữ liệu (bị loại). Một bản chép nguội `cold` dạng chung (hoãn lại: điều kiện kích hoạt nằm trong [ROADMAP.md](../ROADMAP.vi.md) §4, trong đó có trường hợp một ứng dụng cần tiếp quản (adopt) mà chủ sở hữu không chạy được lệnh sao lưu của nó trên bản triển khai không thuộc Ingat (foreign) của nó; các vùng dữ liệu (generation) đã loại bỏ nhu cầu về một bản chép khẩn cấp).

## Hệ quả

Không có chuỗi tên cơ sở dữ liệu nào trong phần lõi (lint kiểm tra). Phần kiểm tra bản sao lưu trước khi phát hành của chính ứng dụng PostgreSQL, nằm trong lệnh cập nhật dữ liệu (migrate) của nó, vẫn tiếp tục kiểm tra định dạng sao lưu riêng của nó bên trong bản sao lưu (bundle) của Ingat (nội dung sao lưu chính là định dạng đó), tạo thành một lớp bảo vệ thứ hai, độc lập. Việc thay phần kiểm tra đó bằng một xác nhận của Ingat đã được cân nhắc và bị loại: làm vậy sẽ bỏ đi một lần kiểm tra độc lập chỉ để bớt một lớp mã của ứng dụng, và ứng dụng không cần thay đổi gì để giữ phần kiểm tra đó.
