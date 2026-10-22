# ADR-0007 Định danh image: ghim theo ID, sổ ghi chép, không xóa image trước M3

[English](0007-image-identity-pinned-by-id.md) · **Tiếng Việt** (bản dịch; bản tiếng Anh là bản chuẩn)

**Trạng thái:** Đã chấp nhận.

**Nói đơn giản:** Mỗi service chạy đúng image mà Ingat đã ghi lại, theo ID của nó, không bao giờ theo một tag có thể bị dời sang image khác. Một bản ghi chỉ ghi một lần lưu nguồn gốc của từng image, và Ingat không xóa image nào trước M3.

## Bối cảnh

Khởi động một image đã bị gắn tag lại hoặc build lại sẽ âm thầm làm mất dấu nguồn gốc và khả năng quay về bản cũ (rollback) (lỗi bắt buộc sửa theo góc nhìn B (Lens B); một nhu cầu của ứng dụng). Script phát hành của ứng dụng PostgreSQL (the PostgreSQL consumer) từ chối một bản phát hành khi thiếu các image trước đó; sổ tay vận hành (runbook) của ứng dụng SQLite (the SQLite consumer) không bao giờ build lại một tag cũ.

## Quyết định

`prepare` ghi mọi ID image thành một mục sổ ghi chép (ledger) chỉ ghi một lần `host/images/<id>/<op>.json` cùng các tag, commit và nguồn gốc của nó; các tham chiếu được tính từ các bản ghi triển khai và danh mục (catalog), nên không có tệp sổ ghi chép dùng chung nào bị ghi lại. Tệp ghi đè (override) ghim mỗi service vào ID đã ghi của nó với `pull_policy: never` và `build: !reset null`. Một tag chỉ được dùng lại khi nhãn của nó hoặc sổ ghi chép chứng minh được nguồn gốc. Trước M3, Ingat không xóa image nào; từ M3, `prune --images` (lớp D) chỉ xóa các image trong sổ ghi chép không còn được tham chiếu. Phương án dự phòng nếu thử nghiệm sớm (spike) S5 thất bại: ngay trước mỗi lời gọi Compose, kiểm tra tag → ID đã ghi, và từ chối nếu không khớp.

## Các phương án khác

Tin vào tag (bị loại). Chỉ dùng digest của registry (bị loại làm mặc định khi cả hai ứng dụng còn build trên máy; được dùng cho cả hai ứng dụng nếu chủ sở hữu chọn build bằng CI, là khuyến nghị cho quyết định của chủ sở hữu OD-11).

## Hệ quả

Dung lượng đĩa tăng dần cho tới M3; `status` hiển thị dung lượng đĩa mà image dùng. ID image chỉ có nghĩa trên từng máy (kho image kiểu classic và kiểu containerd khác nhau), nên việc nhận diện giữa các máy dùng commit cộng nhãn (M4).
