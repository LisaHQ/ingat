# ADR-0006 Compose chạy trên chính các tệp của ứng dụng cộng một tệp ghi đè được sinh ra

[English](0006-compose-app-files-plus-override.md) · **Tiếng Việt** (bản dịch; bản tiếng Anh là bản chuẩn)

**Trạng thái:** Đã chấp nhận.

**Nói đơn giản:** Ingat chạy Docker Compose trên chính các tệp Compose của ứng dụng, không sửa gì, cộng thêm một tệp do nó tự sinh ra. Tệp đó ghim đúng image và thêm các nhãn không bao giờ đổi giữa các lần triển khai, nên chỉ những service thật sự đổi cấu hình mới bị tạo lại.

## Bối cảnh

Chạy từ một mô hình `compose config` được dựng lại có nguy cơ lệch cách thoát ký tự (escape drift) giữa các phiên bản Compose: healthcheck của ứng dụng PostgreSQL (the PostgreSQL consumer) dùng `$$POSTGRES_USER`, và công cụ cũ đã phải hiệu chỉnh cách thoát ký tự. Biến của shell được ưu tiên hơn `--env-file`.

## Quyết định

Mọi lời gọi đều là `docker compose -p <project> --project-directory <export> -f <app files> -f <override.yaml> --env-file <rendered> <verb> <explicit services>` với một môi trường rỗng; `up` luôn có `--no-build --pull never`; tác vụ (task) là `run --rm --no-deps -T --name … --label …`. Tệp ghi đè (override) được sinh từ dữ liệu (các giá trị đơn được bọc ngoặc kép theo kiểu JSON, cộng `!reset`); nó cũng gán cho mọi service chưa có `logging` riêng trình ghi log (driver) `local` có xoay vòng tệp, và gán cho service của một tác vụ dùng terminal driver `none` ([ADR-0025](0025-host-baseline.vi.md)). Mô hình đã gộp lấy từ `config --format json --no-env-resolution` chỉ được dùng cho phép kiểm tra quy tắc an toàn cho cấu hình Compose (policy) và cho dấu vân tay (fingerprint) ([ARCHITECTURE.md](../ARCHITECTURE.vi.md) §6).

## Các phương án khác

Chạy từ mô hình đã biến đổi (bị loại: sự lệch nói trên; độ trung thực chưa được kiểm chứng). Ngữ pháp tệp ghi đè viết tay (bị loại: ngữ pháp đọc vào rồi ghi ra (round-trip) của công cụ cũ).

## Hệ quả

Các tệp Compose của ứng dụng giữ nguyên, không bị sửa. Những tính năng Compose mà tệp ghi đè dựa vào (`!reset`, tên volume `external`, ghim `image: sha256:`, `--no-env-resolution`) là các mục của thử nghiệm sớm (spike) S4-S5. Vì nhãn đi vào mã băm cấu hình theo từng service của Compose, tệp ghi đè chỉ thêm các nhãn định danh ổn định (`instance`, `role`); số thứ tự triển khai chỉ nằm trong các bản ghi triển khai, và tệp env đã dựng được định danh theo nội dung (content-addressed), nên một service chỉ bị tạo lại khi cấu hình thực tế của nó thay đổi ([ARCHITECTURE.md](../ARCHITECTURE.vi.md) §6.2).
