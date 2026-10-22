# ADR-0030 Dải mạng con dành cho môi trường cách ly nằm ngoài các dải địa chỉ mặc định của Docker

[English](0030-isolation-pool-outside-docker-default-pools.md) · **Tiếng Việt** (bản dịch; bản tiếng Anh là bản chuẩn)

**Trạng thái:** Đã chấp nhận (2026-10-16).

**Nói đơn giản:** Các bản sao để thử lấy mạng riêng của chúng từ `10.250.0.0/20`, một dải mà Docker không dùng theo mặc định, nên một máy bận rộn không thể hết địa chỉ cho các lần thử khôi phục.

## Bối cảnh

`host init` ghi lại một dải cách ly (isolation pool), từ đó trình thực thi (executor) cấp một `/24` còn trống cho mỗi project cách ly (các lần thử khôi phục (drill); vùng chuẩn bị khôi phục (restore staging) từ M2). Mặc định trong thiết kế là `172.30.192.0/20` ([LIFECYCLE.md](../LIFECYCLE.vi.md) §4.1, [ARCHITECTURE.md](../ARCHITECTURE.vi.md) §7.4). Các dải địa chỉ mặc định có sẵn của Docker, dùng khi chưa cấu hình `DefaultAddressPools`, cấp phát từ `172.17.0.0/16` đến `172.31.0.0/16` và `192.168.0.0/16` theo từng khối `/20`. Một khi daemon đã cấp `172.30.0.0/16` cho một mạng, không còn `/24` nào của dải cách ly trống, và mọi lần thử khôi phục đều bị từ chối. Các lần chạy kiểm thử tích hợp cục bộ trên daemon tạm (upstream Engine 24.0.2 và 29.9.0) đã dùng hết các dải mặc định của Docker, cho thấy một máy bận rộn có thể chạm tới dải đó.

## Quyết định

Dải cách ly mặc định trở thành `10.250.0.0/20` (mười sáu khối `/24`), nằm ngoài mọi dải mặc định của Docker. Quy tắc cấp phát không đổi: lấy `/24` đầu tiên mà không mục cấp phát nào và không mạng nào trên daemon đang dùng. Một máy có mạng riêng dùng dải đó vẫn nhận được một `/24` còn trống hoặc một lời từ chối rõ ràng.

## Các phương án khác

Giữ `172.30.192.0/20` (bị loại: nó đụng với mặc định của chính Docker trên bất kỳ máy nào có đủ nhiều mạng). Suy ra dải từ `DefaultAddressPools` của daemon lúc `host init` (bị loại: trường này không có khi dùng mặc định, và một dải suy ra vẫn có thể bị chiếm về sau). Một dải do từng máy tự cấu hình (tạm thời bị loại: một tùy chọn cài đặt mới mà chưa có ứng dụng nào cần).

## Hệ quả

`host.json` đã ghi trước thay đổi này giữ nguyên dải đã ghi; `host init` trên một máy mới ghi lại mặc định mới. Mạng cách ly là mạng nội bộ và không có đường đi ra ngoài (route), nên dải này không cần cấu hình định tuyến trên máy.
