# ADR-0021 Kiểm thử, bằng chứng và rào chắn phạm vi

[English](0021-testing-evidence-and-scope-guardrails.md) · **Tiếng Việt** (bản dịch; bản tiếng Anh là bản chuẩn)

**Trạng thái:** Đã chấp nhận; sửa đổi ngày 2026-10-14, trước khi viết bất kỳ mã nào, để hỗ trợ máy mà không phụ thuộc vào nền tảng ([ADR-0025](0025-host-baseline.vi.md)): một làn kiểm thử (lane) arm64 được thêm vào cổng kiểm thử trên Docker thật.

**Nói đơn giản:** Mọi thay đổi đều được kiểm thử trên Docker thật: Engine 24.0 và đúng một bản 29.x trên `x86_64`, và 29.x trên `arm64`. Chỉ các lần chạy CI và các chứng nhận máy đã commit mới được tính là bằng chứng, với kết luận `PASS`, `FAIL` hoặc `BLOCKED`. Giới hạn kích thước và quy tắc "một ứng dụng thật trên một máy thật ngay ở mốc đầu tiên" giữ cho dự án không phình to quá mức.

## Bối cảnh

Khoảng 1,100 bài kiểm thử offline của công cụ cũ, xoay quanh một Docker giả dài khoảng 1k dòng, đã bỏ sót sáu lỗi mà Docker thật tìm ra. Bộ kiểm thử trên Docker thật của nó chỉ chạy trên máy trạm của chủ sở hữu và bị bỏ không. Phần mã chạy (runtime) của nó tăng khoảng mười lần, lên khoảng 29k dòng, mà chưa từng chạy trên máy thật.

## Quyết định

Docker thật ở mỗi lần push (`docker:24.0.2-dind` và đúng một `docker:29.Y.Z-dind` trên `amd64`, cộng một làn kiểm thử arm64 với cùng thẻ 29.Y.Z trên máy chạy CI (runner) arm64 do GitHub cung cấp), các bộ kiểm thử của [ARCHITECTURE.md](../ARCHITECTURE.vi.md) §10.3, bằng chứng chỉ đến từ các lần chạy CI và các chứng nhận máy (host certification) đã commit, một bộ từ kết luận duy nhất (`PASS`, `FAIL`, `BLOCKED`). Quy tắc phạm vi: mỗi tính năng phải nêu một nhu cầu của một ứng dụng dùng Ingat (consumer); mốc (milestone) đầu tiên kết thúc với một ứng dụng thật (bản cài thử của ứng dụng SQLite, `lite-test`) trên máy thật đầu tiên trong khoảng 3k dòng; mỗi module ≤ 600 dòng; một mốc vượt quá 1.5 × số dòng ước tính thì dừng lại để viết một ADR lập lại kế hoạch (re-plan); một thay đổi phần lõi mà bất kỳ ứng dụng nào buộc phải có, kể cả một ứng dụng mới như các ứng dụng chủ sở hữu định làm sau này, sau khi chốt schema (schema freeze, cuối M2) được ghi lại là một lỗi về tính tổng quát (generality failure).

## Các phương án khác

Kiểm thử xoay quanh Docker giả (bị loại). Làn kiểm thử tích hợp trên máy của chủ sở hữu (bị loại). Một ứng dụng thử (fixture) không lưu dữ liệu làm bộ khung chạy được đầu tiên (walking skeleton) của M1 (bị loại: bài học từ công cụ cũ là phải có một ứng dụng thật trên một máy thật ngay ở mốc đầu tiên; `fx-web` vẫn chỉ là ứng dụng thử của CI).

## Hệ quả

Mỗi lần push tốn khoảng 45 phút CI (ba làn kiểm thử, mỗi làn dưới 15 phút), miễn phí trên runner do GitHub cung cấp, kể cả runner arm64, vì repository là công khai (quyết định của chủ sở hữu OD-3; thử nghiệm sớm (spike) S13 xác nhận runner arm64 ở M0). Chỉ công bố hỗ trợ arm64 cho những tổ hợp mà làn kiểm thử arm64 đã qua ([ADR-0025](0025-host-baseline.vi.md)).
