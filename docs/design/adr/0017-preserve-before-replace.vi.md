# ADR-0017 Giữ lại trước khi thay thế, mỗi lần đổi image của phần ghi dữ liệu hoặc image dữ liệu

[English](0017-preserve-before-replace.md) · **Tiếng Việt** (bản dịch; bản tiếng Anh là bản chuẩn)

**Trạng thái:** Đã chấp nhận, chờ quyết định của chủ sở hữu OD-4.

**Nói đơn giản:** Mọi lần cập nhật đổi image của một phần ghi dữ liệu hay của một dịch vụ dữ liệu (hoặc bất kỳ image nào của một ứng dụng tự cập nhật dữ liệu khi khởi động) đều dừng các phần ghi dữ liệu trước, tạo một bản sao lưu và kiểm tra nó; chỉ sau đó bước cập nhật dữ liệu mới chạy. Vì vậy mỗi bản phát hành như thế làm các phần ghi dữ liệu dừng một lúc (thời gian này chưa được đo), và chủ sở hữu quyết định chi phí đó có chấp nhận được không (OD-4).

## Bối cảnh

Script phát hành của ứng dụng PostgreSQL (the PostgreSQL consumer) chỉ tạo bản sao lưu trong lúc tạm ngừng ghi (in-freeze) khi đang có một lần cập nhật dữ liệu (migration) chờ chạy. Tài liệu vận hành (runbook) của ứng dụng SQLite (the SQLite consumer) tạo cặp bản sao lưu của nó khi ứng dụng vẫn đang chạy, trước khi dừng, nên những gì được ghi vào giữa hai việc đó không có trong cặp bản sao lưu. Muốn biết ngay lúc lập kế hoạch là "có migration đang chờ" thì cần một phép kiểm tra trên bản chuẩn bị triển khai (candidate probe); phép kiểm tra này tạo container, và như vậy phá vỡ nguyên tắc lập kế hoạch không gây tác động (plan purity).

## Quyết định

Mọi lần triển khai (deploy) có đổi image của một phần ghi dữ liệu (writer, phần của ứng dụng thay đổi dữ liệu) hoặc image của một dịch vụ dữ liệu (data service) (hoặc bất kỳ image nào của một ứng dụng `migrates_on_start`) đều dừng các phần ghi dữ liệu, tạo và kiểm tra một bản sao lưu trước thay đổi (pre-change bundle), rồi mới cập nhật dữ liệu (migrate) hoặc khởi động. Bước migrate chạy mọi lần; lệnh migrate của cả hai ứng dụng đều chạy lại nhiều lần vẫn cho cùng kết quả (idempotent).

## Các phương án khác

Chỉ tạm ngừng khi có bằng chứng cần (evidence-based freeze: thêm một bước kiểm tra schema trên bản chuẩn bị, bỏ qua bản sao lưu khi không có gì chờ cập nhật): ít thời gian ngừng hơn với các bản phát hành chỉ đổi mã, nhưng nhiều nhánh xử lý hơn và phải có một phép kiểm tra trước khi duyệt.

## Hệ quả

Mỗi bản phát hành của ứng dụng PostgreSQL dừng phần backend (phần xử lý phía máy chủ) của nó trong suốt thời gian kết xuất dữ liệu (dump) cộng thời gian kiểm tra (rồi tiếp đến migrate và kích hoạt): giao diện web vẫn tải được, nhưng không đọc hay ghi được dữ liệu nào. Thời gian này chưa được đo cho tới khi phần việc (slice) 6 của M2 đo nó trên máy đích. Chủ sở hữu quyết định chi phí đó có chấp nhận được không (quyết định của chủ sở hữu OD-4).
