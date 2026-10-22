# ADR-0027 Repository cục bộ của ứng dụng thử (fixture) cho selftest và các bài kiểm thử

[English](0027-local-fixture-repositories.md) · **Tiếng Việt** (bản dịch; bản tiếng Anh là bản chuẩn)

**Trạng thái:** Đã chấp nhận (2026-10-15).

**Nói đơn giản:** Phần tự kiểm tra (self-test) và CI dùng các repository git nhỏ, cục bộ, nằm trong thư mục riêng của Ingat (địa chỉ `file://` chỉ được dùng ở đó, không ở đâu khác), nên chúng đi đúng con đường của một ứng dụng thật mà không cần máy chủ git.

## Bối cảnh

`selftest --host` (mục đầu tiên của điều kiện hoàn thành mốc (exit gate) M1) và các bộ kiểm thử CI chạy trọn vòng đời trên các ứng dụng thử `fx-lite` và `fx-web` qua đúng con đường lấy nguồn git mà một ứng dụng thật dùng ([ARCHITECTURE.md](../ARCHITECTURE.vi.md) §10.4). Schema của bản cài chỉ cho phép URL repository `ssh` và `https`, và bộ chuyển đổi git (git adapter) chỉ cho phép các giao thức đó, nên một ứng dụng thử sẽ cần một máy chủ git trên mọi máy chạy `selftest`, với khóa riêng của nó.

## Quyết định

`[source] repo` của một bản cài cũng có thể là một URL `file://` có đường dẫn nằm dưới `<INGAT_ROOT>/cache/fixtures/`. Chỉ `selftest` tạo repository ở đó (từ các cây thư mục ứng dụng thử đi kèm trong image của công cụ), và các bài kiểm thử tạo chúng trong thư mục gốc tạm của mình theo cùng cách. Bộ chuyển đổi git chỉ cho phép giao thức `file` với URL như vậy; mọi URL `file://` khác, và mọi giao thức khác, vẫn bị từ chối. `INGAT_ROOT` là `root:root 0700`, nên chỉ root mới đặt được repository vào đó.

## Các phương án khác

Một container máy chủ git qua SSH cho selftest và CI (bị loại: selftest trên một máy không được phụ thuộc vào một máy chủ, một cặp khóa hay một cổng lắng nghe mạng). Ứng dụng thử lấy nguồn từ image (bị loại: nguồn từ image có ở M2, và selftest phải chạy thử con đường git mà ứng dụng thật đầu tiên dùng).

## Hệ quả

Selftest và các bộ kiểm thử chạy thử việc tải về (fetch), xác định ref, đọc manifest và xuất mã nguồn (export) đúng như với một ứng dụng thật. Giao thức thêm vào không thể vươn ra ngoài thư mục gốc của công cụ.
