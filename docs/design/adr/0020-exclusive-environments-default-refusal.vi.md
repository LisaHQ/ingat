# ADR-0020 Môi trường độc quyền mặc định là từ chối

[English](0020-exclusive-environments-default-refusal.md) · **Tiếng Việt** (bản dịch; bản tiếng Anh là bản chuẩn)

**Trạng thái:** Đã chấp nhận, chờ quyết định của chủ sở hữu OD-5.

**Nói đơn giản:** Một ứng dụng có thể nói rằng bản chạy thật (production) của nó không được ở chung máy với một bản khác của cùng ứng dụng. Khi đó Ingat mặc định từ chối. Chủ sở hữu có thể nới quy tắc này sau (OD-5).

## Bối cảnh

Quy tắc triển khai riêng của ứng dụng PostgreSQL (the PostgreSQL consumer) cấm đặt một bản cài (instance) staging (bản chạy thử trước khi lên thật) trên Docker daemon đang chạy bản production của nó, và script phát hành của nó từ chối chạy khi còn một project staging. Đề xuất `safety` đã lặng lẽ bỏ quy tắc này (một mục Lens A bắt buộc phải sửa, must-fix). Một máy chạy hai bản cài PostgreSQL cũng cần RAM cho cả hai.

## Quyết định

Khóa manifest `exclusive_environments = ["production"]` giữ quy tắc này: một bản cài production từ chối triển khai hoặc khởi động khi trên máy có một bản cài khác của cùng ứng dụng đã được đăng ký, và ngược lại với `init`. Chủ sở hữu có thể đổi quy tắc trong manifest của ứng dụng sau OD-5; nếu chủ sở hữu nới quy tắc trước khi chốt schema ở M2 (schema freeze), khóa này rời khỏi schema 1 (khi đó không còn ứng dụng nào dùng nó) và quy tắc chỉ còn là thói quen làm việc của chủ sở hữu cộng với phép kiểm tra `[drill] min_free_memory`.

## Các phương án khác

Bỏ quy tắc vì Ingat đã tách riêng project, volume, bí mật và bản sao lưu (quan điểm của `safety`/`container`). Chỉ giữ nó như thói quen làm việc của chủ sở hữu ngay từ đầu (đề xuất của lần rà soát, bị loại làm mặc định: nó sẽ xóa bỏ một mục Lens A bắt buộc phải sửa, tức mặc định từ chối, trước khi chủ sở hữu quyết định OD-5).

## Hệ quả

Với mặc định này, bản cài staging (`pg-staging`) phải được gỡ bỏ hoàn toàn (purge, M3) hoặc chuyển sang máy khác trước khi bản cài production (`pg-prod`) khởi động trên máy của nó.
