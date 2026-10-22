# Tình trạng và lộ trình của Ingat

[English](status.md) · **Tiếng Việt** (bản dịch; bản tiếng Anh là bản chuẩn)

Những gì đã chạy được hôm nay, những gì đã kiểm thử, những gì chưa xong, và những gì sắp tới.

Tính đến ngày 2026-10-22.

**Đã chạy được hôm nay** (phiên bản 0.1.0, mốc M1), với các ứng dụng build từ một kho mã git và lưu dữ liệu trong thư mục thường, hoặc không có dữ liệu:

- cài Ingat, kiểm tra máy (`host init`, `host check`, `selftest`) và nâng cấp Ingat an toàn;
- đăng ký một ứng dụng (`init`), kiểm tra kho mã của một ứng dụng (`validate`), tải và ghim các image của nó (`prepare`);
- cài lần đầu, có các điểm dừng cho bước thiết lập của ứng dụng; cập nhật có thay đổi dữ liệu (sao lưu trước); cập nhật chỉ đổi thiết lập; và đường đi tiếp an toàn khi một lần cập nhật bị dừng giữa chừng;
- chạy, dừng, khởi động lại và các tác vụ riêng của ứng dụng;
- sao lưu (bằng tay và hằng đêm), kiểm tra, thử khôi phục, và xóa bản sao lưu cũ theo quy tắc giữ lại của bạn;
- `status`, `doctor`, `list`, `ps`, `logs`, `history`, `bundles`;
- các thao tác vẫn chạy tiếp khi mất SSH, cùng `attach`, `cancel`, `resume` và `abandon`.

**Đã kiểm thử:**

- Các bài kiểm thử tự động chạy trên Docker thật với mỗi lần đẩy mã lên `main` và mỗi đêm, và đạt trên cả ba làn: Docker Engine 24.0 và 29.9 trên `x86_64`, và 29.9 trên `arm64` ([các lần chạy CI](https://github.com/LisaHQ/ingat/actions/workflows/ci.yml)).
- Máy thật đầu tiên, một NAS Synology chạy DSM 7.4.1 với Container Manager 24.0.2-1706 (`x86_64`), đã đạt `ingat selftest --host` với phiên bản 0.1.0 (22 bước kiểm tra). [Chứng nhận](../../src/ingat/support/hosts/dsm-7.4.1-90080-0-containermanager-24.0.2-1706-4.4.302+-x86_64.json) của nó đã được commit; các mục kiểm tra bằng tay trong danh sách của nó vẫn còn mở.

**Chưa xong:**

- Bản phát hành v0.1.0 là bản nháp, chưa được công bố. Image `ghcr.io/lisahq/ingat:0.1.0` của nó thì đã công khai.
- Chưa có ứng dụng thật nào chạy dưới Ingat. Ứng dụng đầu tiên, `lite-test` (ứng dụng SQLite) trên chiếc NAS đó, sẽ hoàn thành mốc M1; điều kiện hoàn thành M1 chưa đạt. Tiếp theo là M2.
- Việc nâng cấp từ một bản phát hành thật sang bản kế tiếp chưa được kiểm thử: cho tới khi có bản phát hành thứ hai, bài kiểm thử chỉ nâng cấp giữa hai bản build của cùng một phiên bản.
- Chưa có trong phiên bản này: khôi phục; ứng dụng dùng Docker volume hoặc có dịch vụ cơ sở dữ liệu riêng; ứng dụng chỉ triển khai từ image; tác vụ `exec`; `secret set`; giao kế hoạch cho trợ lý AI; các lệnh có thể làm mất dữ liệu (lớp D); một vài tính năng của manifest ứng dụng (truyền tệp qua luồng, chụp lại log, kiểm tra trước và sau khi triển khai, `[schema]` dựa trên tác vụ); và việc `doctor` so địa chỉ proxy nó thấy với địa chỉ đã cấu hình.

**Đã quyết định, chưa làm:**

- **Bộ cung cấp dữ liệu (data provider)** ([ADR-0031](../design/adr/0031-data-providers.vi.md)): một ứng dụng liệt kê các bộ dữ liệu của nó (PostgreSQL, MySQL, MariaDB, SQLite, tệp thường), và các image hỗ trợ được ghim của chính Ingat sẽ sao lưu, kiểm tra và khôi phục chúng, nên ứng dụng không cần lệnh sao lưu riêng. Một danh mục công khai các ứng dụng đã được chứng nhận. Bản mô tả công khai mà các image provider phải tuân theo (contract) và các image đầu tiên làm song song với M2, phần còn lại ngay sau khi M2 đạt điều kiện hoàn thành.
- **`ingat ui`** ([ADR-0032](../design/adr/0032-local-session-bound-web-view.vi.md)): một trang web chỉ để xem cho phiên làm việc của bạn, chỉ mở được ngay trên máy đó, có lời giải thích dễ hiểu và một công cụ viết sẵn lệnh cho bạn. Phiên bản đầu tiên của nó không có quyền truy cập Docker. Nó đến sau phần giao kế hoạch của M2.
- **`ingat report` và `ingat support-bundle`** ([ADR-0033](../design/adr/0033-commercial-boundary-report-and-hosted-service.vi.md)): một bản tóm tắt tình trạng gửi ra ngoài mà bạn tự đăng ký, và một gói thông tin để gửi kèm khi bạn nhờ hỗ trợ. Cùng M2 hoặc M3.

**Miễn phí, và sẽ luôn miễn phí.** Ingat là mã nguồn mở theo giấy phép Apache License 2.0. Mọi thứ dùng để giữ gìn hay khôi phục dữ liệu của bạn sẽ không bao giờ phải trả tiền, không bao giờ bị giới hạn và không bao giờ phụ thuộc vào gói dịch vụ. Một trang tình trạng do bên Ingat vận hành có thể trở thành dịch vụ trả phí sau này ([ADR-0033](../design/adr/0033-commercial-boundary-report-and-hosted-service.vi.md)).

## Lộ trình tóm tắt

| Mốc | Mang lại gì | Tình trạng |
|---|---|---|
| M0 Quyết định và thông tin máy | Tên và không gian tên, thông tin về máy đầu tiên, kiểm tra cách chạy, nơi build image ứng dụng | Đang làm |
| M1 Ứng dụng thật đầu tiên | `lite-test` (ứng dụng SQLite) trên máy đầu tiên, một NAS Synology; CI bao phủ Linux thông thường | Đang làm: mã đã xong, điều kiện hoàn thành còn mở |
| M2 Khôi phục và ứng dụng PostgreSQL | Khôi phục vào một vùng dữ liệu mới cho cả hai ứng dụng; `pg-staging` trên máy đầu tiên; giao kế hoạch cho trợ lý AI; chốt cố định định dạng `ingat.toml` | Tiếp theo |
| M3 Sẵn sàng cho môi trường thật | Quay về phiên bản cũ, gỡ một ứng dụng, dọn dẹp, giám sát, công cụ hỗ trợ lập lịch cho systemd, cron và DSM; `pg-prod` (khi quyết định của chủ sở hữu OD-5 cho phép) | Đã lên kế hoạch |
| M4 Phục hồi sau sự cố và tiếp quản ứng dụng | Khôi phục trên máy khác, nhập bản sao lưu, tiếp quản một ứng dụng đã cài không qua Ingat; chứng nhận một máy chủ Linux thông thường (khi có một máy như vậy) | Đã lên kế hoạch |
| M5 Ingat tự nâng cấp | Lệnh tự nâng cấp và lệnh chuyển đổi bản ghi | Khi cần |

Chi tiết, quy mô và điều kiện hoàn thành: [`docs/design/ROADMAP.vi.md`](../design/ROADMAP.vi.md).
