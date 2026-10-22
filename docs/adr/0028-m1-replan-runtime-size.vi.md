# ADR-0028 Lập lại kế hoạch M1: kích thước mã chạy

[English](0028-m1-replan-runtime-size.md) · **Tiếng Việt** (bản dịch; bản tiếng Anh là bản chuẩn)

**Trạng thái:** Đã chấp nhận (chủ sở hữu, 2026-10-15), theo quy tắc dừng 1.5× của [ROADMAP.md](../ROADMAP.vi.md) §3.

**Nói đơn giản:** Mốc (milestone) M1 hóa ra lớn hơn ước tính ban đầu: khoảng 6,600 dòng mã thay vì 3,000, với điểm dừng để xem xét lại ở khoảng 10,000. Những gì M1 mang lại không thay đổi.

## Bối cảnh

M1 được ước tính khoảng 3,000 dòng mã chạy (runtime), với điểm dừng để lập lại kế hoạch ở 4,500 (1.5×). Khi phần nền móng của phần việc (slice) 1 được viết xong (brand, lỗi, bản ghi, mẫu, mô hình manifest và mô hình bản cài đầy đủ của schema 1, định dạng bản sao lưu, cổng phiên bản (gate), quy tắc giữ bản sao lưu (retention), kho lưu (store), runner, override, các bộ chuyển đổi cho git và cho phép kiểm tra HTTP, kế hoạch, nhật ký và duyệt), chúng đo được 2,227 dòng mã chạy (Python, không tính dòng trống và dòng chú thích), riêng mô hình manifest đã chiếm 575 dòng vì schema 1 được đọc đầy đủ ngay từ v0.1 ([MANIFEST_SPEC.md](../MANIFEST_SPEC.vi.md)). Một ước tính từ dưới lên cho các module M1 còn lại (bộ chuyển đổi Docker và Compose, quy tắc an toàn cho cấu hình Compose (policy), trình thực thi (executor) và các bước, các bộ lập kế hoạch cho host, init, status, prepare, deploy, lifecycle, tasks, backup, verify, drill, prune và selftest, CLI kèm phần theo dõi (follower), `install.sh` và `facts.sh`) cho ra khoảng 6,600 dòng mã chạy cho M1, khoảng 2.2× ước tính. Ngân sách dòng của các module trong [ARCHITECTURE.md](../ARCHITECTURE.vi.md) §5.1 đã cộng lại khoảng 9,000 dòng cho M1-M3, và M1 chứa phần lớn bộ máy đó: trình thực thi, tập các bước, nhật ký, lần thử khôi phục (drill) cách ly và lần cập nhật có thay đổi dữ liệu đều nằm ở M1, vì ứng dụng thật đầu tiên cần chúng.

## Quyết định

Ước tính của M1 trở thành khoảng 6,600 dòng mã chạy, và mức dừng của nó là 1.5× con số đó, khoảng 10,000. Phạm vi của M1 không đổi. Mã vẫn nhỏ nhất mà từng quy tắc cho phép: không có tùy chọn làm sẵn cho trường hợp phỏng đoán, không có hàm hỗ trợ không dùng tới, không có lớp trừu tượng nào khi chưa có hai chỗ dùng. Giới hạn 600 dòng mỗi module, quy tắc phải có nhu cầu của ứng dụng và mọi quy tắc an toàn bắt buộc (safety floor) đều không đổi. Các ước tính của M2-M5 chưa được sửa lúc này; mỗi ước tính được kiểm tra lại theo kích thước đo được của M1 khi mốc đó bắt đầu.

## Các phương án khác

Cắt bớt phạm vi M1 cho vừa 4,500 dòng bằng cách dời lần thử khôi phục, thay đổi chỉ về cấu hình và `scheduled status` sang M2 (chủ sở hữu loại: khi đó `lite-test` không thể đạt điều kiện hoàn thành mốc (exit gate) M1, vốn cần một lần thử khôi phục và một lần cập nhật có thay đổi dữ liệu). Dừng ở 4,500 để xem xét (chủ sở hữu loại: sai là ở con số ước tính chứ không phải ở phạm vi, và phép đếm từ dưới lên không cho thấy tính năng nào ngoài danh sách của M1).

## Hệ quả

Tổng số dòng cho MVP và cho lúc hoàn thành trong [ROADMAP.md](../ROADMAP.vi.md) đang thấp hơn thực tế khoảng cùng một hệ số, cho tới khi từng mốc được ước tính lại. Nếu M1 tiếp tục vượt quá khoảng 10,000 dòng thì lại dừng để viết một ADR lập lại kế hoạch.
