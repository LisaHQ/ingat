# ADR-0009 Manifest ứng dụng nằm trong repository của ứng dụng; TOML; các bộ từ vựng đóng

[English](0009-app-manifest-in-app-repository.md) · **Tiếng Việt** (bản dịch; bản tiếng Anh là bản chuẩn)

**Trạng thái:** Đã chấp nhận.

**Nói đơn giản:** Mỗi ứng dụng tự mô tả mình trong `ingat.toml` ở repository riêng của nó, được đọc từ đúng phiên bản đang được cài. Định dạng là TOML, và mọi danh sách từ được phép dùng trong đó (bước, chế độ tác vụ, kiểu kiểm tra, chỗ điền giá trị) đều cố định: thêm một từ mới cần một ADR và một ứng dụng thật cần đến nó.

## Bối cảnh

Hồ sơ điều khiển (control-plane profile) được cài trên máy của công cụ cũ bị lệch so với các bản phát hành của ứng dụng và không mô tả được một ứng dụng thứ hai. Cả hai ứng dụng đều đã đóng gói sẵn các thao tác vận hành của mình trong image.

## Quyết định

Manifest ứng dụng (`ingat.toml`) nằm ở thư mục gốc của repository ứng dụng, được đọc từ commit được triển khai và được chụp lại một bản cho mỗi lần triển khai; tệp cấu hình bản cài (`instance.toml`) trên máy chỉ chứa giá trị và không bao giờ bị Ingat ghi lại. TOML được phân tích chặt chẽ bằng `tomllib`. Các tập đóng: loại bước, chế độ tác vụ (`run`, `exec`), kiểu phép kiểm tra sẵn sàng (probe) (`health`, `exec`, `http`), biến mẫu. Một dạng mới cần một ADR và một ứng dụng cụ thể có tên cần đến nó ([MANIFEST_SPEC.md](../../app-developers/MANIFEST_SPEC.vi.md)).

## Các phương án khác

YAML (bị loại: tự đoán kiểu dữ liệu một cách ngầm). Manifest lưu trên máy (bị loại: lệch cấu trúc service khi quay về bản cũ). Một ngôn ngữ biểu thức (bị loại: nguy cơ lớn dần thành một ngôn ngữ thu nhỏ).

## Hệ quả

Quay về bản cũ (rollback) tự động dùng đúng cấu trúc service tương ứng. `ingat validate` chạy trong CI của từng ứng dụng từ M1.
