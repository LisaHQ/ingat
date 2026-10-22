# ADR-0011 Vùng dữ liệu; khôi phục và thử khôi phục trong các dự án tách biệt

[English](0011-data-generations-and-isolated-restores.md) · **Tiếng Việt** (bản dịch; bản tiếng Anh là bản chuẩn)

**Trạng thái:** Đã chấp nhận.

**Nói đơn giản:** Dữ liệu của một ứng dụng nằm trong các vùng dữ liệu được đánh số (generation). Một lần khôi phục đổ dữ liệu vào một vùng mới trong một dự án riêng, được cách ly, rồi mới chuyển ứng dụng sang đó; dữ liệu cũ vẫn được giữ. Các lần thử khôi phục dùng những dự án dùng xong bỏ.

## Bối cảnh

Cả hai ứng dụng vốn đã khôi phục vào một chỗ mới (theo quy trình khôi phục trong sổ tay vận hành của chính chúng). Khởi động các service kho dữ liệu (store) trên một vùng dữ liệu mới bên trong dự án đang chạy thật sẽ tạo lại cơ sở dữ liệu đang chạy ngay dưới một backend đang hoạt động (lỗi bắt buộc sửa theo góc nhìn A (Lens A)). Cách khôi phục chỉ vào cùng UUID của công cụ cũ khiến việc phục hồi sau thảm họa là không thể.

## Quyết định

Các kho dữ liệu gắn vào các vùng dữ liệu `g<N>` (volume external hoặc thư mục). Một lần khôi phục đổ dữ liệu vào `g<N+1>` trong dự án tách biệt `<instance>--r<seq>` (secret thật của bản cài (instance), chốt chặn (hold), mạng nội bộ, không mở cổng), gỡ dự án đó xuống, dừng dự án đang chạy thật, chuyển con trỏ và khởi động dự án đang chạy thật. Các lần thử khôi phục (drill) dùng `<instance>--t<seq>` với secret dùng xong bỏ và các vùng dữ liệu `t<seq>`, được gỡ bỏ bằng một thao tác xóa chỉ trên danh sách đóng.

## Các phương án khác

Khôi phục tại chỗ (bị loại: quy tắc an toàn bắt buộc (safety floor) F7, không bao giờ ghi đè dữ liệu; [LIFECYCLE.md](../LIFECYCLE.vi.md) §1). Chuẩn bị khôi phục ngay bên trong dự án đang chạy thật (bị loại: lỗi bắt buộc sửa theo góc nhìn A).

## Hệ quả

Các vùng dữ liệu cũ chiếm đĩa cho tới khi có `prune --generations` (M3). Một bài kiểm thử CI khẳng định rằng không có phần ghi dữ liệu nào đang chạy thật gắn vào một vùng dữ liệu chưa được chuyển sang.
