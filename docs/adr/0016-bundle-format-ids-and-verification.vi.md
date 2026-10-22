# ADR-0016 Định dạng bản sao lưu, mã định danh và các mức kiểm tra

[English](0016-bundle-format-ids-and-verification.md) · **Tiếng Việt** (bản dịch; bản tiếng Anh là bản chuẩn)

**Trạng thái:** Đã chấp nhận.

**Nói đơn giản:** Một bản sao lưu (bundle) là một thư mục có một tệp mã kiểm tra liệt kê mọi tệp; định danh của nó là mã băm của tệp mã kiểm tra đó. Tên của nó theo mẫu đặt tên riêng của ứng dụng. Hai mức kiểm tra, "verified" (đã kiểm tra) và "restore-tested" (đã thử khôi phục), được ghi lại bên ngoài bản sao lưu.

## Bối cảnh

Công cụ sao lưu của ứng dụng PostgreSQL (the PostgreSQL consumer) chỉ chấp nhận tên bản sao lưu khớp với `<YYYYMMDDTHHMMSSZ>-daily|manual|pre-release-<label>` và một mốc thời gian "không sớm hơn" dạng `YYYY-MM-DDTHH:MM:SSZ`. Đặt kết quả kiểm tra bên trong bản sao lưu đã được niêm phong sẽ khiến mã băm của nó phụ thuộc vòng vào chính nó.

## Quyết định

Một bản sao lưu là một thư mục (`bundle.json`, `SHA256SUMS`, `payload/<entry>/`, `meta/`); mã băm của nó là SHA-256 của `SHA256SUMS`, được ghi trong một danh mục (catalog) chỉ root truy cập được. Mã định danh lấy từ các mẫu đặt tên theo từng loại trong manifest (một ứng dụng ánh xạ chúng sang quy tắc đặt tên riêng của nó). Hai mức, `verified` và `restore-tested`, được giữ bên ngoài bản sao lưu ([LIFECYCLE.md](../LIFECYCLE.vi.md) §5.3-5.5). `{freeze_at}` được dựng ra đúng theo quy tắc ghi giờ UTC của ứng dụng đó; một bài kiểm thử tuân thủ (conformance) chạy nó với lệnh cập nhật dữ liệu (migrate) thật của ứng dụng (M3).

## Các phương án khác

Bản sao lưu dạng tar (bị loại: không ứng dụng nào cần; cách nhập tar hai lượt của công cụ cũ chỉ quay lại nếu có ứng dụng cần). Một mã định danh do công cụ đặt, không liên quan tới quy tắc đặt tên của ứng dụng (bị loại: làm hỏng các bản sao lưu của ứng dụng PostgreSQL).

## Hệ quả

Các công cụ kiểm tra riêng của cả hai ứng dụng vẫn dùng được trên bản sao lưu của Ingat. Bản sao lưu không bao giờ chứa thông tin bí mật (secret) hay mô hình đã được phân giải.
