# Ingat hoạt động thế nào

[English](how-it-works.md) · **Tiếng Việt** (bản dịch; bản tiếng Anh là bản chuẩn)

Ingat làm gì, dành cho ai, và giữ dữ liệu của bạn an toàn ra sao, bằng lời dễ hiểu.

## Ingat làm gì

Bạn có vài ứng dụng chạy trên một máy (một trang web, một cửa hàng, một công cụ nhỏ cho nhóm của bạn) bằng Docker Compose. Ingat là người trợ giúp cẩn thận cho chiếc máy đó. Mỗi việc chỉ cần một lệnh, Ingat:

- **cài đặt** một ứng dụng từ đúng một phiên bản mã nguồn của nó;
- **cập nhật** ứng dụng lên phiên bản mới và đưa dữ liệu của nó theo một cách an toàn;
- **sao lưu** ứng dụng, mỗi đêm hoặc bất cứ khi nào bạn muốn, và xóa các bản sao lưu cũ theo quy tắc giữ lại do bạn đặt;
- **kiểm tra** từng bản sao lưu, và **thử khôi phục** bản đó vào một bản thử riêng của ứng dụng để chứng minh nó dùng được;
- **chạy, dừng và khởi động lại** ứng dụng, và chạy các tác vụ bảo trì mà ứng dụng cung cấp;
- nói với bạn bằng lời dễ hiểu điều gì cần bạn chú ý, và lệnh nào cần chạy tiếp.

Dự kiến cho các mốc sau: khôi phục (M2), quay về phiên bản cũ và gỡ một ứng dụng sạch sẽ (M3), chuyển sang máy mới và tiếp quản một ứng dụng đã được cài mà không qua Ingat (M4).

Ingat làm việc trên từng máy một, bằng dòng lệnh, thường là qua SSH. Nó không phải trình quản lý cụm máy, không phải bảng điều khiển hosting hay dịch vụ đám mây, và nó không tự chép bản sao lưu của bạn sang nơi khác: công cụ sao lưu của chính bạn làm việc đó (restic, borg, rsync, hoặc Hyper Backup trên NAS Synology).

## Ingat dành cho ai

- **Những người tự chạy ứng dụng của mình** trên NAS, VPS hay máy chủ ở nhà, và muốn những phần khó và rủi ro được làm hộ một cách an toàn.
- **Nhà phát triển ứng dụng** muốn ứng dụng của mình dễ cài và cập nhật an toàn. Họ thêm một tệp, `ingat.toml`, vào kho mã (repository) của ứng dụng ([cách làm](../app-developers/MANIFEST_SPEC.vi.md)).
- **Trợ lý AI chạy máy chủ thay cho chủ sở hữu.** Ingat được làm như một bộ dây an toàn cho các trợ lý này: chúng được tự do xem tình hình và tạo bản sao lưu, nhưng mọi thay đổi cần chủ sở hữu duyệt, và việc gì có thể làm mất dữ liệu thì chỉ một người gõ tại một terminal thật mới duyệt được. Quy tắc này đúng với những trợ lý tuân theo nó; chính thiết lập công cụ của chúng buộc chúng tuân theo. Cách để chủ sở hữu giao một kế hoạch đã duyệt cho trợ lý sẽ có ở M2.

## Vì sao dữ liệu của bạn an toàn

| Cam kết | Ý nghĩa với bạn |
|---|---|
| **Luôn sao lưu trước mọi thay đổi rủi ro** | Trước một lần cập nhật chạm tới dữ liệu, Ingat dừng những phần của ứng dụng thay đổi dữ liệu, tạo một bản sao lưu, niêm phong nó bằng mã kiểm tra và kiểm tra nó. Chỉ sau đó nó mới thay đổi gì đó. Nếu sao lưu thất bại, không có gì bị thay thế. |
| **Không ghi đè lên thứ gì** | Một lần khôi phục đổ dữ liệu vào một vùng dữ liệu mới, tách riêng, rồi mới chuyển ứng dụng sang vùng đó. Dữ liệu trước đó của bạn vẫn giữ nguyên. (Khôi phục sẽ có ở M2; quy tắc này đã là một phần của thiết kế.) |
| **Bản sao lưu được chứng minh, không phải hy vọng** | Một bản sao lưu chỉ được tính là "đã thử khôi phục" sau khi Ingat khôi phục đúng bản đó vào một bản thử riêng của ứng dụng, không chạm được tới dữ liệu đang dùng của bạn, và các bước kiểm tra riêng của ứng dụng đều đạt. |
| **Bị ngắt giữa chừng vẫn an toàn** | Các thay đổi chạy trong một trình trợ giúp riêng trên máy, không nằm trong cửa sổ SSH của bạn, nên mất kết nối không làm dừng gì cả. Ngoại lệ duy nhất là một tác vụ trò chuyện với bạn ngay trong terminal (ví dụ một bước thiết lập của lần cài đầu): nó chạy từ cửa sổ của bạn, nên nếu mất kết nối, hãy chạy lệnh tiếp theo và làm theo hướng dẫn của nó ([hướng dẫn vận hành §8](operator-guide.vi.md#8-khi-có-sự-cố)). Ingat ghi lại từng bước trước khi làm, nên một việc bị ngắt luôn có thể làm tiếp hoặc hoàn tác. |
| **Chỉ xóa những gì của chính nó** | Ingat chỉ xóa những thứ nó đã tạo, chứng minh được là của nó, và đã liệt kê trước trong một kế hoạch. Nó không bao giờ chạy `docker system prune` hay `docker compose down -v`, và không bao giờ đụng tới container, volume hay network mà nó không tạo ra. |
| **Mật khẩu được giữ kín** | Mật khẩu và khóa chỉ nằm trong các tệp mà chỉ root đọc được. Ingat không bao giờ đưa chúng lên dòng lệnh, vào bản ghi, vào bản sao lưu, vào log hay vào thông báo lỗi. |
| **Không có nút "cưỡng ép"** | Không có `--force`, cũng không có `--yes`. Khi Ingat từ chối, chưa có gì thay đổi, và thông báo nêu đúng lệnh an toàn cần chạy thay vào đó. |
| **Chỉ chạy trên máy đã kiểm thử** | Các lệnh có thay đổi chỉ chạy trên những phiên bản Docker mà bản phát hành này đã được kiểm thử cùng, và chỉ sau khi Ingat đã kiểm thử máy của bạn (`ingat selftest --host`). |

Các quy tắc chính xác là 17 quy tắc an toàn bắt buộc trong [`docs/design/LIFECYCLE.vi.md`](../design/LIFECYCLE.vi.md#1-quy-tắc-an-toàn-bắt-buộc). Chúng được viết bằng mã, và không có thiết lập nào tắt được chúng.

## Cách hoạt động, nói ngắn gọn

- Ingat là một container image được ghim cố định (`linux/amd64` và `linux/arm64`) có sẵn Python, dòng lệnh Docker, Compose và git bên trong, được khởi động bởi một script 20 dòng mà chỉ root chạy được. Máy chủ, VPS và NAS chạy đúng cùng những byte đó; Python và Compose có sẵn trên máy không bao giờ được dùng.
- Mọi thay đổi chạy trong một container trợ giúp riêng (`ingat-exec-<instance>`), nên một phiên SSH bị ngắt hay một việc chạy theo lịch không bao giờ làm dừng việc cập nhật dữ liệu giữa chừng. Lệnh bạn gõ chỉ lập kế hoạch, hỏi duyệt và theo dõi. Ngoại lệ là các tác vụ trò chuyện với bạn trong terminal, chạy từ chính cửa sổ của bạn, và ba lệnh ngắn chỉ thay đổi bản ghi của chính Ingat (`host init`, `init`, `secret set`).
- Compose luôn chạy trên chính các tệp Compose của ứng dụng cộng với một tệp do Ingat tạo ra; tệp này ghim từng dịch vụ vào đúng image đã ghi nhận và thêm những nhãn không bao giờ đổi giữa các lần triển khai, nên một lần cập nhật chỉ tạo lại những dịch vụ có thiết lập thay đổi.
- Mỗi ứng dụng tự giữ hiểu biết về dữ liệu của nó trong image của chính nó. Tệp `ingat.toml` của nó nằm trong kho mã của ứng dụng, được đọc từ đúng phiên bản đang cài, và khai báo các tác vụ (sao lưu, khôi phục, kiểm tra, cập nhật dữ liệu) cùng ý nghĩa của từng mã thoát.
- Một cơ sở dữ liệu chỉ được coi là sẵn sàng sau khi phép kiểm tra sẵn sàng mà ứng dụng khai báo cho nó đã đạt, chứ không chỉ vì container của nó đã khởi động.
- Mỗi thao tác có một nhật ký các bước: mỗi bước được ghi lại trước khi chạy, và được kiểm tra trước khi thử lại. Mỗi ứng dụng chỉ có tối đa một thao tác đang mở tại một thời điểm.

Toàn bộ thiết kế: [`docs/design/ARCHITECTURE.vi.md`](../design/ARCHITECTURE.vi.md) và [`docs/design/LIFECYCLE.vi.md`](../design/LIFECYCLE.vi.md).

