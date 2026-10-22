# ADR-0023 Bản ghi tương thích với nhau trong cùng một phiên bản lược đồ trạng thái (state schema)

[English](0023-record-compatibility-within-state-schema.md) · **Tiếng Việt** (bản dịch; bản tiếng Anh là bản chuẩn)

**Trạng thái:** Đã chấp nhận.

**Nói đơn giản:** Trong cùng một phiên bản bản ghi, các bản ghi Ingat lưu lại chỉ được thêm trường mới không bắt buộc, có giá trị mặc định giữ nguyên cách hoạt động cũ, để cả Ingat mới hơn lẫn Ingat bản trước đó đều đọc được. Mọi thay đổi khác cần một phiên bản bản ghi mới và một lệnh chuyển đổi (migration).

## Bối cảnh

Các bản cài thật (`lite-test` từ M1, `pg-staging` từ M2) sẽ trải qua nhiều lần nâng cấp công cụ bằng `install.sh` trước M5, trong khi M2-M4 thêm các trường bản ghi (`held_since`, `monitor.json`, nguồn gốc được thừa kế (lineage), các mục danh mục `imported`, `adopted_from` và `origin` của một bản sao lưu). Các tài liệu được tính mã băm dùng JSON nghiêm ngặt ([ARCHITECTURE.md](../ARCHITECTURE.vi.md) §7.3). Công cụ cũ không có đường nâng cấp, và việc nâng cấp và cài lại phải là một tính năng đã được kiểm thử ngay từ bản phát hành đầu tiên.

## Quyết định

Trong cùng một `state_schema`, thay đổi chỉ được là thêm vào và không bắt buộc: một trường mới có giá trị mặc định cho ra đúng cách hoạt động cũ, và không trường nào đổi ý nghĩa hay kiểu. Phần đọc giữ lại các trường lạ thuộc schema của chính nó (khi ghi lại thì mang chúng theo) và từ chối một schema mới hơn. Mọi thay đổi khác phải tăng `state_schema` và đi kèm một lệnh `ingat state migrate` có ghi nhật ký, lệnh này sao chép trạng thái trước tiên (M5). Bộ kiểm thử nâng cấp chạy từ M1: bản phát hành N-1 đang có một thao tác mở thì từ chối nâng cấp; sau khi thao tác đó đóng, N đọc được trạng thái của N-1, và `bin/ingat.prev` (N-1) đọc được trạng thái do N ghi ([ARCHITECTURE.md](../ARCHITECTURE.vi.md) §3.5, §10.3).

## Các phương án khác

Dời mọi quy tắc tương thích sang bộ khung chuyển đổi (migration framework) của M5 (bị loại: trạng thái thật đã có từ M1). Đánh phiên bản riêng cho từng loại bản ghi (bị loại: một số schema cho mỗi máy là đủ cho một chủ sở hữu).

## Hệ quả

Một trường không thể thêm theo kiểu bổ sung sẽ buộc phải tăng schema và có `state migrate` sớm hơn M5; đó là lý do để lập lại kế hoạch (re-plan), không phải một thay đổi lặng lẽ.
