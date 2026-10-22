# Các từ dùng trong Ingat

[English](glossary.md) · **Tiếng Việt** (bản dịch; bản tiếng Anh là bản chuẩn)

Những từ bạn gặp trong thông báo và tài liệu của Ingat. Nếu có tên kỹ thuật, tên đó nằm trong ngoặc.

| Từ | Ý nghĩa |
|---|---|
| **bản cài** (instance) | Một bản sao đã cài đặt của một ứng dụng trên máy bạn, có tên riêng (ví dụ `lite-test`). Tên đó cũng là tên project Docker Compose của nó. |
| **manifest ứng dụng** (`ingat.toml`) | Một tệp trong kho mã của ứng dụng, nói cho Ingat biết ứng dụng hoạt động thế nào: các dịch vụ, dữ liệu, tác vụ của nó. Tệp này không chứa giá trị nào của máy bạn. |
| **tệp bản cài** (`instance.toml`) | Thiết lập của bạn cho một bản cài: nguồn, cổng, địa chỉ, quy tắc giữ lại. Tệp này nằm trên máy bạn. |
| **bản sao lưu** (bundle) | Một bản sao lưu đã niêm phong của dữ liệu một bản cài, mỗi tệp có một mã kiểm tra, được giữ trong `INGAT_BACKUPS`. |
| **đã kiểm tra** (verified) | Ingat đã đọc lại mọi tệp của bản sao lưu, thấy chúng không đổi, và các bước kiểm tra riêng của ứng dụng đều đạt, nếu ứng dụng có (nếu không có, chỉ các tệp được kiểm tra). |
| **thử khôi phục** (drill), **đã thử khôi phục** (restore-tested) | Ingat đã khôi phục bản sao lưu vào một bản thử riêng của ứng dụng, không chạm được tới dữ liệu đang dùng của bạn, kiểm tra nó, rồi xóa bản thử đó. |
| **các phần ghi dữ liệu** (writers) | Những phần của ứng dụng thay đổi dữ liệu của bạn. |
| **vùng dữ liệu** (data generation) | Một bộ dữ liệu đầy đủ của một ứng dụng. Một lần khôi phục đổ vào một vùng mới; vùng cũ được giữ lại. |
| **thao tác** (operation) | Một lần chạy của một lệnh có thay đổi, được ghi lại từng bước để có thể làm tiếp hoặc hoàn tác. |
| **điểm không quay lại** (forward point) | Bước của một lần cập nhật mà sau đó Ingat không còn hoàn tác đơn giản được nữa (thường là bước cập nhật dữ liệu của ứng dụng). |
| **tạm khóa** (frozen) | Một lần cập nhật đã dừng sau khi bắt đầu thay đổi dữ liệu, nên các phần ghi dữ liệu được cố ý giữ ở trạng thái dừng cho tới khi bạn đi tiếp theo đường đã chỉ. |
| **lớp duyệt** (approval classes) | A: chỉ đọc. B: chỉ thêm (bản sao lưu, kết quả kiểm tra) hoặc xóa những gì quy tắc giữ lại của bạn cho phép; chạy không cần người. C: thay đổi một thứ gì đó; bạn gõ tên bản cài. D: có thể làm mất dữ liệu; bạn gõ một cụm từ cộng một mã ngẫu nhiên tại một terminal thật (từ M2). |
| **chứng nhận máy** (host certification) | Bản ghi cho biết `ingat selftest --host` đã đạt trên đúng bản build hệ thống và Docker này của máy bạn. |
