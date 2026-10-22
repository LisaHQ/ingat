# ADR-0022 Những việc giao cho công cụ khác

[English](0022-delegated-concerns.md) · **Tiếng Việt** (bản dịch; bản tiếng Anh là bản chuẩn)

**Trạng thái:** Đã chấp nhận; sửa đổi ngày 2026-10-14, trước khi viết bất kỳ mã nào, để hỗ trợ máy mà không phụ thuộc vào nền tảng ([ADR-0025](0025-host-baseline.vi.md)): các công cụ được giao việc là công cụ sẵn có của nền tảng, và `schedule render` chỉ thuộc M3. Hai mục Bối cảnh và Các phương án khác được thêm vào cùng ngày. Được thay thế một phần (2026-10-19) bởi [ADR-0032](0032-local-session-bound-web-view.vi.md) (hệ quả "không có cổng lắng nghe mạng", thu hẹp lại còn một ngoại lệ được nêu tên) và bởi [ADR-0033](0033-commercial-boundary-report-and-hosted-service.vi.md) (câu về thông báo trong mục Quyết định); phần còn lại giữ nguyên.

**Nói đơn giản:** HTTPS và định tuyến, bản sao ở nơi khác có mã hóa, lập lịch và email báo lỗi đều do công cụ sẵn có của máy đảm nhận (một reverse proxy, restic, borg, rsync hoặc Hyper Backup, systemd, cron hoặc Task Scheduler). Ingat cung cấp cho chúng mã thoát ổn định và các công cụ hỗ trợ. Về sau ADR-0032 (một trang xem web cục bộ) và ADR-0033 (một báo cáo trạng thái gửi ra ngoài) đã thu hẹp hai phần.

## Bối cảnh

Mọi máy mà Ingat nhắm tới đều đã có sẵn một reverse proxy (bộ chuyển tiếp yêu cầu web), công cụ sao lưu và một bộ lập lịch: Caddy hoặc nginx, restic, borg hoặc rsync, và systemd timer hoặc cron trên máy Linux; reverse proxy của DSM, Hyper Backup và Task Scheduler trên DSM. restic, borg và Hyper Backup mã hóa ngay ở phía máy gửi, còn rsync có thể chép tới một nơi nhận đã được mã hóa. Ingat là một công cụ dòng lệnh chạy xong là thoát, không có tiến trình chạy nền (daemon) hay cổng lắng nghe mạng (listener) ([ARCHITECTURE.md](../ARCHITECTURE.vi.md) §1.4).

## Quyết định

TLS và định tuyến (reverse proxy của máy: Caddy, nginx hoặc reverse proxy của DSM), bản sao ở nơi khác (ngoài máy) và mã hóa (công cụ của nền tảng, chép tới một nơi ngoài máy do chủ sở hữu quản lý: restic, borg hoặc rsync trên máy Linux; Hyper Backup trên DSM tới một NAS khác hoặc một nơi ở bên ngoài), lập lịch và thông báo (systemd timer với `OnFailure=`, cron với `MAILTO`, DSM Task Scheduler; mã thoát) đều nằm ngoài Ingat. Việc khôi phục không bao giờ dựa vào snapshot (ảnh chụp ổ đĩa) (trên DSM, Snapshot Replication chỉ có trên volume Btrfs): các bản sao lưu (bundle) cộng với bản sao ở ngoài máy là toàn bộ con đường khôi phục. Ingat cung cấp mã thoát ổn định, `status --json`, `schedule render` cho systemd, cron và DSM Task Scheduler (M3), và một cách sắp xếp bản sao lưu có tài liệu mô tả cùng với lệnh `import` (M4).

## Các phương án khác

Tự làm trong Ingat việc mã hóa, việc sao chép ra ngoài máy, một tiến trình lập lịch chạy nền hoặc một bộ gửi thông báo (bị loại: đây là những việc Ingat không nhắm tới, theo [ARCHITECTURE.md](../ARCHITECTURE.vi.md) §1.4; mỗi thứ sẽ làm lại một công cụ đã hoàn thiện của nền tảng, và thêm việc quản lý khóa mã hóa, một tiến trình chạy nền hoặc một cổng lắng nghe vào một công cụ vốn không có những thứ đó).

## Hệ quả

Ingat không có tiến trình chạy nền, không có bộ gửi thông báo, không có cổng lắng nghe mạng.
