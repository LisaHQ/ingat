# Các lệnh của Ingat

[English](commands.md) · **Tiếng Việt** (bản dịch; bản tiếng Anh là bản chuẩn)

Khi còn việc cần làm tiếp, dòng cuối `next:` nêu lệnh cần chạy. Xem, sao lưu và kiểm tra không bao giờ cần duyệt. Một thay đổi sẽ yêu cầu bạn gõ tên bản cài (ví dụ `lite-test`); việc chạy theo lịch không bao giờ duyệt được thay đổi, nên nó từ chối. Thêm `--json` vào bất kỳ lệnh nào để nhận kết quả dưới dạng một khối cho máy đọc. Các việc hằng ngày, có ví dụ, nằm trong [hướng dẫn vận hành](operator-guide.vi.md#5-việc-hằng-ngày).

## Mọi lệnh trong phiên bản 0.1.0 (mốc M1)

Chạy bằng root. Các lớp duyệt: A chỉ đọc; B chỉ thêm (bản sao lưu, kết quả kiểm tra) hoặc xóa những gì quy tắc giữ lại của bạn cho phép; C thay đổi một thứ gì đó và yêu cầu bạn gõ tên bản cài (với `host init` là đúng tên mà lệnh `hostname` in ra) tại một terminal ([`docs/design/LIFECYCLE.vi.md`](../design/LIFECYCLE.vi.md#2-lớp-duyệt-và-các-lệnh) §2). Mã thoát nằm ở [§6](../design/LIFECYCLE.vi.md#6-mã-thoát-mọi-lệnh). Đường dẫn mà `init --config` và `validate` nhận phải là đường dẫn đầy đủ nằm trong một trong hai thư mục của Ingat.

| Lệnh | Việc nó làm |
|---|---|
| `version` | Phiên bản của công cụ, của lệnh `ingat` và của image |
| `host init`, `host check` | Gắn thư mục của Ingat với Docker engine này và ghi lại thông tin của nó (lớp C); ghi lại thông tin và rủi ro thành một lần kiểm tra máy |
| `init <i> --config <file> --ref <ref>` | Đăng ký một bản cài từ tệp `instance.toml` của nó (lớp C) |
| `validate <repo-dir> [--instance <file>]` | Kiểm tra kho mã của một ứng dụng, và nếu muốn cả một tệp bản cài, mà không thay đổi gì |
| `prepare <i> <ref>` | Lấy phiên bản đó, tải các image của nó và ghim chúng lại (lớp B) |
| `deploy <i> <ref>` | Cài lần đầu, cập nhật có thay đổi dữ liệu, cập nhật chỉ đổi thiết lập, hoặc đường đi tiếp sau một lần cập nhật bị dừng (lớp C); nếu cần thì tự chạy bước chuẩn bị trước |
| `start\|stop\|restart <i> [<service>…]` | Chạy, dừng hoặc khởi động lại bản triển khai đã ghi nhận (lớp C) |
| `task <i> <task> [--arg NAME=VALUE]… [--input NAME=FILE]…` | Chạy một tác vụ mà ứng dụng khai báo (lớp B nếu chỉ đọc, còn lại lớp C); `--input` chỉ tới một tệp trong `INGAT_ROOT/inbox/` |
| `backup <i> [--class <class>] [--reason TEXT] [--prune]` | Tạo một bản sao lưu đã niêm phong và đã kiểm tra (lớp B; `--class` mặc định là `manual`) |
| `verify <i> <bundle>\|--latest [--restore-test]` | Kiểm tra lại một bản sao lưu; `--restore-test` thì thử khôi phục nó luôn (lớp B) |
| `prune <i> --bundles [--apply]` | Xóa bản sao lưu cũ theo quy tắc giữ lại: chạy thử, hoặc xóa thật với `--apply` (lớp B) |
| `resume <i>`, `abandon <i>` | Làm tiếp thao tác chưa xong, hoặc hoàn tác những gì hoàn tác được rồi đóng nó lại (lớp C) |
| `attach <i>`, `cancel <i>` | Theo dõi lại thao tác đang chạy; yêu cầu nó dừng ở điểm an toàn kế tiếp |
| `status [<i>]`, `doctor <i>`, `list`, `ps <i>`, `logs <i> <service> [--since T]`, `history <i>`, `bundles <i>` | Xem mà không thay đổi gì (`status` kết thúc với exit 5 khi có điều cần bạn chú ý) |
| `scheduled backup <i>`, `scheduled verify <i> <bundle>\|--latest [--restore-test]`, `scheduled task <i> <task> …`, `scheduled status` | Việc cho bộ lập lịch của máy: chỉ lớp A và B, in một dòng khi thành công (`scheduled status` chỉ in những gì đã thay đổi) |
| `selftest [--host\|--offline]` | Chạy các ứng dụng dùng xong bỏ từ đầu đến cuối; `--host` còn chứng nhận bản build hệ thống và Docker của máy này; `--offline` kiểm tra image mà không cần Docker |
