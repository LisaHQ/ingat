# ADR-0008 Bố trí thư mục: thư mục gốc POSIX thường, thư mục gốc cho bản sao lưu chỉ root ghi

[English](0008-filesystem-layout.md) · **Tiếng Việt** (bản dịch; bản tiếng Anh là bản chuẩn)

**Trạng thái:** Đã chấp nhận; sửa đổi ngày 2026-10-14, trước khi viết bất kỳ dòng mã nào, để hỗ trợ máy mà không phụ thuộc nền tảng ([ADR-0025](0025-host-baseline.vi.md)): thư mục gốc cho bản sao lưu là dạng chung (generic), và thư mục chia sẻ (shared folder) của DSM là dạng của nó trong hồ sơ DSM. Tiêu đề trước đây là "Filesystem layout: plain POSIX root, root-written backup share" (bố trí thư mục: thư mục gốc POSIX thường, thư mục chia sẻ cho bản sao lưu chỉ root ghi).

**Nói đơn giản:** Thư mục riêng của Ingat là một thư mục thường mà chỉ root mở được. Một bản sao lưu được ghi vào đó trước, rồi được chép sang một thư mục sao lưu riêng mà chỉ root ghi vào được; bản sao ở nơi khác (ngoài máy) của bạn được chép ra từ chính thư mục đó.

## Bối cảnh

Các máy khác nhau ở cách bảo vệ thư mục gốc cho bản sao lưu và cách chép nó ra khỏi máy. Trên DSM, thư mục chia sẻ mang ACL được ưu tiên hơn quyền POSIX; container tác vụ chạy dưới các uid cố định (10001 trong image của cả hai ứng dụng) và có thể bị từ chối quyền. Trên volume Btrfs, đổi tên từ một subvolume sang subvolume khác bị lỗi `EXDEV`, và trên bất kỳ máy nào hai thư mục gốc cũng có thể nằm trên hai hệ thống tệp khác nhau (trên một volume ext4, trong cùng một hệ thống tệp thì đổi tên được, nhưng một đường công bố duy nhất phục vụ mọi cách bố trí). Hyper Backup bảo vệ các thư mục chia sẻ, không bảo vệ thư mục gốc Docker (`@docker` trên volume nơi cài Container Manager); trên máy Linux, restic, borg hay rsync chép một thư mục. SQLite WAL cần ổ lưu trữ cục bộ.

## Quyết định

`INGAT_ROOT` là một thư mục thường `root:root 0700` trên hệ thống tệp cục bộ (trên DSM được tạo qua SSH, không bao giờ là thư mục chia sẻ) và chứa toàn bộ trạng thái, các vùng chuẩn bị (stage), bản sao của dữ liệu đầu vào và các vùng dữ liệu (generation) dạng thư mục gắn (bind). `INGAT_BACKUPS` chỉ được root ghi và không tài khoản nào khác ghi vào được, nên việc dọn bản cũ theo chính sách giữ lại (retention) không bao giờ chạy trong một cây thư mục mà người dùng khác có thể thay đổi: trên máy Linux là một thư mục `root:root 0700`, trên DSM là một thư mục chia sẻ mà quản trị viên chỉ đọc được (không tài khoản DSM nào ghi vào được qua SMB). Công bố là chép vào `.incoming-<id>/`, fsync, rồi đổi tên bên trong thư mục gốc cho bản sao lưu. Việc dọn theo chính sách giữ lại xóa bằng cách duyệt cây thư mục không đi theo liên kết (no-follow), tương đối theo descriptor, và chứng minh lại từng mục. Container không bao giờ gắn (mount) thứ gì từ thư mục gốc cho bản sao lưu. Việc chứng nhận kiểm tra người sở hữu tệp, chế độ quyền và quyền ghi của cả hai thư mục gốc, và trên DSM kiểm tra các dấu hiệu ACL và quyền của thư mục chia sẻ ([ARCHITECTURE.md](../ARCHITECTURE.vi.md) §7.2, §10.4).

## Các phương án khác

Chuẩn bị ngay trong thư mục gốc cho bản sao lưu (bị loại: lỗi bắt buộc sửa theo góc nhìn A (Lens A)). Đặt trạng thái trong một thư mục chia sẻ (bị loại: ACL, bị lộ qua SMB). Gắn thư mục gốc Docker vào để kiểm tra chỗ trống (bị loại: lỗi bắt buộc sửa theo góc nhìn B (Lens B); volume thăm dò đo việc đó).

## Hệ quả

Một bản sao lưu (bundle) được ghi hai lần (vùng chuẩn bị, rồi thư mục gốc cho bản sao lưu); các phép kiểm tra dung lượng tính cả hai. Việc `/volume1/ingat` có còn nguyên sau một lần cập nhật DSM hay không là rủi ro R4 ([ARCHITECTURE.md](../ARCHITECTURE.vi.md) §12), sẽ được kiểm tra ở lần cập nhật DSM đầu tiên.
