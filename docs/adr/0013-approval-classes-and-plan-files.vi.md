# ADR-0013 Các lớp duyệt A-D và tệp kế hoạch

[English](0013-approval-classes-and-plan-files.md) · **Tiếng Việt** (bản dịch; bản tiếng Anh là bản chuẩn)

**Trạng thái:** Đã chấp nhận, chờ quyết định của chủ sở hữu OD-10 (xác nhận ranh giới cho agent).

**Nói đơn giản:** Mỗi lệnh có một lớp duyệt (approval class). A chỉ đọc. B chỉ thêm vào, như các bản sao lưu, hoặc xóa những bản sao lưu cũ mà quy tắc giữ lại của bạn cho phép, và có thể chạy không cần người trông. C thay đổi một thứ gì đó và cần gõ tên bản cài (instance), hoặc một kế hoạch mà chủ sở hữu đã duyệt. D có thể làm mất dữ liệu và cần gõ một mã thử thách trên một terminal thật, không bao giờ dùng một kế hoạch đã lưu. Lớp D chỉ dành cho chủ sở hữu: Ingat không phân biệt được trợ lý AI với con người, nên chỉ các quy tắc chặn trong công cụ của chính trợ lý mới giữ chúng tránh xa lớp D (quyết định của chủ sở hữu OD-10).

## Bối cảnh

Mô hình duyệt của công cụ cũ chỉ chạy kiểu hỏi đáp trực tiếp và chặn các lần sao lưu theo lịch với mã thoát 20. Một mã băm duyệt mà cũng mở khóa được việc gỡ bỏ hoàn toàn (purge) sẽ cho phép một agent hủy dữ liệu (góc nhìn A (Lens A) về `container`).

## Quyết định

A chỉ đọc, B không phá hủy (chạy không cần người trông), C có thay đổi (gõ tên bản cài trên terminal, hoặc `ingat apply <hash>` của một kế hoạch đã lưu), D phá hủy (chỉ trên terminal, một cụm từ cộng một mã thử thách ngẫu nhiên; `apply` không bao giờ được chấp nhận cho lớp D, kể cả với các bản cài `disposable`). `start`, `stop`, `restart` là lớp C (lỗi bắt buộc sửa theo góc nhìn A). Thay đổi biến môi trường cần chủ sở hữu duyệt, thay image của dịch vụ dữ liệu (data service), khôi phục vào một bản cài đã có dữ liệu, quay dữ liệu về bản cũ (rollback), dọn bớt (prune) vùng dữ liệu (generation) và image, gỡ bỏ hoàn toàn và `resolve` là lớp D ([LIFECYCLE.md](../LIFECYCLE.vi.md) §2). Tiếp quản (adoption) không có bước lớp D nào, vì Ingat không bao giờ dừng dự án không thuộc Ingat (foreign): bước nhập (import) của nó là lớp B, và bước khôi phục vào một bản cài chưa từng được triển khai là lớp C ([ADR-0024](0024-adoption-by-payload-import.vi.md)). `disposable` chỉ cho phép việc gỡ bỏ hoàn toàn bỏ qua bước thử khôi phục (restore-test) của nó.

## Các phương án khác

Một tệp quy tắc cấp quyền (policy file of grants) (bị loại: từng là một điểm chặn ở công cụ cũ). `--approve` cho mọi lớp (bị loại: agent có thể gỡ bỏ hoàn toàn). `apply` cho lớp D trên các bản cài disposable (bị loại: các bản cài staging như `pg-staging` và các site không lưu dữ liệu đều là disposable, nên một agent cầm mã băm có thể gỡ bỏ hoàn toàn chúng hoặc khôi phục đè lên chúng).

## Hệ quả

Agent vận hành (trợ lý AI) có thể chuẩn bị mọi thứ và áp dụng lớp C với mã băm của chủ sở hữu; lớp D chỉ dành cho riêng chủ sở hữu. CLI không phân biệt được agent với chủ sở hữu (một agent có pty có thể gõ mã thử thách), nên ranh giới này chỉ đứng vững với những agent tuân theo nó; các quy tắc chặn công cụ (tool deny rules) của chính các agent bảo đảm điều đó (quyết định của chủ sở hữu OD-10). Agent phát triển trong repository Ingat không bao giờ đụng tới máy thật ([CLAUDE.md](../../CLAUDE.md) §6).
