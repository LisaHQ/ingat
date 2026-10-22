# Quy ước và tên gọi

[English](CONVENTIONS.md) · **Tiếng Việt** (bản dịch; bản tiếng Anh là bản chuẩn)

Các quy ước mà mọi tài liệu của Ingat tuân theo, và các tên gọi Ingat dùng ở mọi nơi.

## Quy ước dùng trong mọi tài liệu

- **Nhãn trạng thái:** **Decided** (Đã quyết định: một phần của thiết kế), **Planned Mx** (Đã lên kế hoạch: đã quyết định, làm trong mốc x), **Open OD-n** (Còn mở: cần một quyết định của chủ sở hữu), **Unverified** (Chưa kiểm chứng: một đặc điểm nền tảng mà thử nghiệm sớm M0 hoặc một thử nghiệm sau phải xác nhận).
- **Một bộ từ phán định duy nhất** cho điều kiện hoàn thành, CI và báo cáo: `PASS`, `FAIL`, `BLOCKED`.
- **Quyết định của chủ sở hữu** được trích dẫn là "owner decision OD-n" (quyết định của chủ sở hữu OD-n). OD-1, OD-2, OD-3 và OD-11 đã được quyết định; các quyết định còn lại vẫn mở và được ghi trong ghi chú riêng của chủ sở hữu, không thuộc kho mã này.
- **Ứng dụng mẫu không nêu tên.** Hai ứng dụng thật định hướng thiết kế. Ở đây chúng chỉ được gọi bằng tên chung:
  - *ứng dụng PostgreSQL* (the PostgreSQL consumer): một ứng dụng web nhiều dịch vụ (PostgreSQL, một backend và một dịch vụ web) có một bước cập nhật dữ liệu riêng, cấp quyền vai trò sau khi khôi phục và một lệnh kiểm tra tính nhất quán; được mô phỏng bởi ứng dụng thử `fx-pg`;
  - *ứng dụng SQLite* (the SQLite consumer): một ứng dụng một container có SQLite trong một thư mục dữ liệu gắn từ máy (bind mount), sao lưu ngay khi ứng dụng đang chạy, bằng cơ chế riêng của ứng dụng, một hàng đợi thư gửi đi, và cập nhật dữ liệu khi khởi động; được mô phỏng bởi ứng dụng thử `fx-lite`;
  - `fx-web`: một ứng dụng thử không có dữ liệu.

  Tên bản cài ví dụ: `pg-staging`, `pg-prod`, `lite-test`, `site`.
- **Công cụ cũ** là "an earlier in-house deployment controller" (một công cụ triển khai nội bộ trước đây). Ingat được viết lại từ đầu và **không tương thích** gì với nó: không dùng chung nhãn, thư mục gốc, bản ghi, bản sao lưu, volume hay image, và không đọc bất kỳ định dạng nào của nó. Bài học từ nó chỉ xuất hiện dưới dạng lý do ngắn gọn, chung chung, không bao giờ là trích dẫn. Tiếp quản một bản triển khai làm ngoài Ingat là một tính năng của sản phẩm (tiếp quản, M4).

## Tên gọi

| Mục | Giá trị |
|---|---|
| Sản phẩm | Ingat |
| CLI | `ingat` |
| Kho mã (repository) | `github.com/LisaHQ/ingat` |
| Tiền tố biến môi trường | `INGAT_` (ví dụ `INGAT_ROOT`, `INGAT_BACKUPS`) |
| Không gian tên nhãn | `io.github.lisahq.ingat.` (ví dụ `io.github.lisahq.ingat.instance`) |
| Image | `ghcr.io/lisahq/ingat` (công khai, đa kiến trúc `linux/amd64` và `linux/arm64`, tải theo digest) |
| Thư mục gốc mặc định | `/srv/ingat` (trạng thái của công cụ: một thư mục POSIX thường, `root:root 0700`) và `/srv/ingat-backups` (các bản sao lưu đã niêm phong, chỉ root ghi); script khởi động `/srv/ingat/bin/ingat`; cả hai đổi được lúc cài (`--root`, `--backups`) |
| Thư mục gốc theo hồ sơ DSM | `/volume1/ingat` (không bao giờ là shared folder) và `/volume1/ingat-backups` (một shared folder của DSM, chỉ đọc với quản trị viên, chỉ root ghi, là nguồn cho Hyper Backup); script khởi động `/volume1/ingat/bin/ingat`; truyền vào lúc cài, không phải mặc định trong mã |
| Tên Docker suy ra | Project Compose `<instance>`, trình thực thi `ingat-exec-<instance>`, các project cách ly `<instance>--r<seq>` (khôi phục) và `<instance>--t<seq>` (thử khôi phục), volume `<instance>_<store>_g<N>` |

Trong mã, các tên này chỉ nằm trong `src/ingat/brand.py` và mẫu script khởi động ([ADR-0003](adr/0003-name-namespaces-and-brand-module.vi.md)); tài liệu dùng chúng nguyên văn.

