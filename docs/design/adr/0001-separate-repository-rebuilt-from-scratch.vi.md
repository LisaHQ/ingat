# ADR-0001 Một repository riêng, viết lại từ đầu

[English](0001-separate-repository-rebuilt-from-scratch.md) · **Tiếng Việt** (bản dịch; bản tiếng Anh là bản chuẩn)

**Trạng thái:** Đã chấp nhận (chỉ đạo của chủ sở hữu, 2026-10-14).

**Nói đơn giản:** Ingat là một dự án mới, riêng biệt, được viết lại từ đầu. Nó không dùng chung gì với công cụ nội bộ cũ mà nó thay thế và không đọc được dữ liệu của công cụ đó; các ứng dụng đang có trên máy hiện nay được cài lại từ đầu, không chuyển dữ liệu cũ sang.

## Bối cảnh

Công cụ cũ, một công cụ triển khai nội bộ trước đây, nằm bên trong repository của ứng dụng PostgreSQL (the PostgreSQL consumer) (khoảng 29k dòng mã chạy thật, phần lớn nằm trong một script). Nó chưa bao giờ chạy trên máy đích, lần đánh giá (review) cuối cùng của nó kết luận là phải sửa, và danh sách cho phép (allowlist) Compose của nó từ chối ứng dụng SQLite (the SQLite consumer) và không diễn đạt được tệp Compose chạy thật (production) của ứng dụng PostgreSQL. Ứng dụng PostgreSQL chưa được đưa vào chạy thật.

## Quyết định

Một repository công khai mới `github.com/LisaHQ/ingat` (quyết định của chủ sở hữu OD-2 và OD-3), với dòng phiên bản riêng. Không tương thích với công cụ cũ: không dùng chung nhãn (label), thư mục gốc, bản ghi, định dạng bản sao lưu (bundle), volume hay image; không đọc và không chuyển đổi các bản cài (instance) của nó. Mã của nó chỉ được dùng lại ở mức ý tưởng (bản phân tích việc dùng lại nằm trong ghi chú của chủ sở hữu). Dữ liệu hiện nay cũng không được chuyển sang: chủ sở hữu xóa các container hiện có trên máy đích và cài lại cả hai ứng dụng từ đầu (chủ sở hữu, 2026-10-14). Việc tiếp quản (adoption) một bản triển khai Compose không thuộc Ingat (foreign), theo cách chung cho mọi ứng dụng ([ADR-0024](0024-adoption-by-payload-import.vi.md)) là một tính năng sản phẩm riêng, không đọc định dạng nào của công cụ cũ.

## Các phương án khác

Tách công cụ cũ ra rồi sửa lại cấu trúc (bị loại: khoảng 85-90% số dòng của nó phục vụ những tác nhân và cách bố trí mà công cụ mới không có; một cuộc đánh giá kết luận rằng tách ra thực chất là viết lại). Giữ nó bên trong repository của ứng dụng PostgreSQL (bị loại: có một ứng dụng thứ hai, ứng dụng SQLite, và còn có các trang web dạng chung).

## Hệ quả

Công cụ cũ và tài liệu của nó có thể được xóa khỏi repository của ứng dụng (được theo dõi trong ghi chú của chủ sở hữu). Mọi tên định danh được lưu lâu dài đều là mới và phải được chốt trước khi tài nguyên thật đầu tiên ra đời ([ADR-0003](0003-name-namespaces-and-brand-module.vi.md)).
