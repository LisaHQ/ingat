# Ingat

[English](README.md) · **Tiếng Việt** (bản dịch; bản tiếng Anh là bản chuẩn)

[![CI](https://github.com/LisaHQ/ingat/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/LisaHQ/ingat/actions/workflows/ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)

**Ingat cài đặt, cập nhật và sao lưu các ứng dụng bạn chạy bằng Docker Compose trên máy chủ hay NAS của chính bạn, và không bao giờ đem dữ liệu của bạn ra đánh cược.**

Trước mọi thay đổi có thể chạm tới dữ liệu, Ingat tạo một bản sao lưu và kiểm tra nó. Ingat không bao giờ ghi đè lên dữ liệu của bạn. Nó chứng minh một bản sao lưu thật sự dùng được bằng cách khôi phục chính bản đó vào một bản thử riêng của ứng dụng. Và nếu kết nối của bạn bị ngắt giữa lúc cập nhật, không có gì bị bỏ dở: công việc vẫn chạy tiếp, và bạn luôn có thể làm tiếp hoặc hoàn tác.

*Ingat* nghĩa là "hãy nhớ, hãy để ý, hãy cẩn thận" trong tiếng Mã Lai và tiếng Indonesia. Trong tiếng Tagalog, lời chào tạm biệt hằng ngày *Ingat!* nghĩa là "bảo trọng nhé!". Đọc gần giống "in-ngát".

> [!NOTE]
> **Mới ở giai đoạn đầu.** Phiên bản 0.1.0 đã có dưới dạng bản phát hành nháp (draft) và chưa được công bố. Hiện nó xử lý được các ứng dụng đơn giản, vượt qua mọi bài kiểm thử tự động trên Docker thật, và đã vượt qua bài tự kiểm tra trên máy thật đầu tiên, một NAS Synology. Chưa có ứng dụng thật nào chạy dưới Ingat, và tính năng khôi phục sẽ có ở mốc tiếp theo. Chi tiết: [Tình trạng](#tình-trạng).

[Ingat làm gì](#ingat-làm-gì) · [Vì sao dữ liệu của bạn an toàn](#vì-sao-dữ-liệu-của-bạn-an-toàn) · [Bắt đầu](#bắt-đầu) · [Dùng hằng ngày](#dùng-hằng-ngày) · [Tình trạng](#tình-trạng) · [Chạy trên máy nào](#chạy-trên-máy-nào) · [Tìm hiểu thêm](#tìm-hiểu-thêm)

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
- **Nhà phát triển ứng dụng** muốn ứng dụng của mình dễ cài và cập nhật an toàn. Họ thêm một tệp, `ingat.toml`, vào kho mã (repository) của ứng dụng ([cách làm](docs/app-developers/MANIFEST_SPEC.vi.md)).
- **Trợ lý AI chạy máy chủ thay cho chủ sở hữu.** Ingat được làm như một bộ dây an toàn cho các trợ lý này: chúng được tự do xem tình hình và tạo bản sao lưu, nhưng mọi thay đổi cần chủ sở hữu duyệt, và việc gì có thể làm mất dữ liệu thì chỉ một người gõ tại một terminal thật mới duyệt được. Quy tắc này đúng với những trợ lý tuân theo nó; chính thiết lập công cụ của chúng buộc chúng tuân theo. Cách để chủ sở hữu giao một kế hoạch đã duyệt cho trợ lý sẽ có ở M2.

## Vì sao dữ liệu của bạn an toàn

| Cam kết | Ý nghĩa với bạn |
|---|---|
| **Luôn sao lưu trước mọi thay đổi rủi ro** | Trước một lần cập nhật chạm tới dữ liệu, Ingat dừng những phần của ứng dụng thay đổi dữ liệu, tạo một bản sao lưu, niêm phong nó bằng mã kiểm tra và kiểm tra nó. Chỉ sau đó nó mới thay đổi gì đó. Nếu sao lưu thất bại, không có gì bị thay thế. |
| **Không ghi đè lên thứ gì** | Một lần khôi phục đổ dữ liệu vào một vùng dữ liệu mới, tách riêng, rồi mới chuyển ứng dụng sang vùng đó. Dữ liệu trước đó của bạn vẫn giữ nguyên. (Khôi phục sẽ có ở M2; quy tắc này đã là một phần của thiết kế.) |
| **Bản sao lưu được chứng minh, không phải hy vọng** | Một bản sao lưu chỉ được tính là "đã thử khôi phục" sau khi Ingat khôi phục đúng bản đó vào một bản thử riêng của ứng dụng, không chạm được tới dữ liệu đang dùng của bạn, và các bước kiểm tra riêng của ứng dụng đều đạt. |
| **Bị ngắt giữa chừng vẫn an toàn** | Các thay đổi chạy trong một trình trợ giúp riêng trên máy, không nằm trong cửa sổ SSH của bạn, nên mất kết nối không làm dừng gì cả. Ngoại lệ duy nhất là một tác vụ trò chuyện với bạn ngay trong terminal (ví dụ một bước thiết lập của lần cài đầu): nó chạy từ cửa sổ của bạn, nên nếu mất kết nối, hãy chạy lệnh tiếp theo và làm theo hướng dẫn của nó ([hướng dẫn vận hành §8](docs/guide/operator-guide.vi.md#8-khi-có-sự-cố)). Ingat ghi lại từng bước trước khi làm, nên một việc bị ngắt luôn có thể làm tiếp hoặc hoàn tác. |
| **Chỉ xóa những gì của chính nó** | Ingat chỉ xóa những thứ nó đã tạo, chứng minh được là của nó, và đã liệt kê trước trong một kế hoạch. Nó không bao giờ chạy `docker system prune` hay `docker compose down -v`, và không bao giờ đụng tới container, volume hay network mà nó không tạo ra. |
| **Mật khẩu được giữ kín** | Mật khẩu và khóa chỉ nằm trong các tệp mà chỉ root đọc được. Ingat không bao giờ đưa chúng lên dòng lệnh, vào bản ghi, vào bản sao lưu, vào log hay vào thông báo lỗi. |
| **Không có nút "cưỡng ép"** | Không có `--force`, cũng không có `--yes`. Khi Ingat từ chối, chưa có gì thay đổi, và thông báo nêu đúng lệnh an toàn cần chạy thay vào đó. |
| **Chỉ chạy trên máy đã kiểm thử** | Các lệnh có thay đổi chỉ chạy trên những phiên bản Docker mà bản phát hành này đã được kiểm thử cùng, và chỉ sau khi Ingat đã kiểm thử máy của bạn (`ingat selftest --host`). |

Các quy tắc chính xác là 17 quy tắc an toàn bắt buộc trong [`docs/design/LIFECYCLE.vi.md`](docs/design/LIFECYCLE.vi.md#1-quy-tắc-an-toàn-bắt-buộc). Chúng được viết bằng mã, và không có thiết lập nào tắt được chúng.

## Bắt đầu

### Bạn cần gì

- Một máy có **Linux, Docker Engine 24.0 trở lên và Docker Compose v2**: một máy chủ, máy ảo hoặc VPS, một bo mạch nhỏ, hoặc một NAS chạy được Docker. Bộ xử lý: `x86_64`, hoặc `arm64` với Docker 29.9.
- **Một phiên bản Docker đã kiểm thử, để được thay đổi.** Ingat chỉ thay đổi trên một phiên bản Docker mà bản phát hành này đã được kiểm thử cùng: hiện là 24.0 hoặc 29.9 trên `x86_64`, 29.9 trên `arm64`. Trên một phiên bản khác từ 24.0 trở lên, nó chỉ xem được và tạo được những bản sao lưu không cần dừng ứng dụng. Đừng để Docker tự cập nhật ([hướng dẫn vận hành §1](docs/guide/operator-guide.vi.md#1-trước-khi-bắt-đầu)).
- **Quyền root**, thường qua SSH (`sudo -i`).
- Một **bộ lập lịch** cho các việc chạy hằng đêm (systemd timer, cron, hoặc Task Scheduler trên NAS Synology) có gửi email cho bạn khi một việc bị lỗi.
- Một công cụ **chép các bản sao lưu sang nơi khác** (restic, borg, rsync, hoặc Hyper Backup trên NAS Synology).
- **Bộ nhớ:** bản thân Ingat cần rất ít. Hãy tính cho các ứng dụng của bạn, cộng thêm một bản sao các dịch vụ dữ liệu của một ứng dụng trong lúc thử khôi phục. Gợi ý, chưa đo thực tế: ít nhất 4 GB cho một ứng dụng dùng PostgreSQL, 8 GB trở lên cho nhiều ứng dụng có thử khôi phục hằng tuần.

Danh sách đầy đủ: [yêu cầu tối thiểu với máy](docs/design/ARCHITECTURE.vi.md#114-yêu-cầu-tối-thiểu-cho-máy).

> [!IMPORTANT]
> **Bản phát hành đầu tiên chưa được công bố.** Phiên bản 0.1.0 đang là bản nháp trên GitHub. Khi nó được công bố, hãy tải `install.sh`, `facts.sh` và `SHA256SUMS` từ [trang phát hành](https://github.com/LisaHQ/ingat/releases) vào cùng một thư mục (ví dụ bằng `curl -fLO https://github.com/LisaHQ/ingat/releases/download/v0.1.0/install.sh`, và làm tương tự với `facts.sh` và `SHA256SUMS`), rồi làm theo các bước dưới đây.

### Bước 1: cài Ingat

**Trên máy chủ Linux hoặc VPS**, bằng root:

```sh
sudo -i
cd /path/to/downloads   # thư mục bạn đã lưu các tệp phát hành
sh install.sh --version 0.1.0 --link /usr/local/bin/ingat
```

Ingat giữ tệp của chính nó trong `/srv/ingat` và các bản sao lưu trong `/srv/ingat-backups`. `--link` cho phép bạn gõ `ingat` thay vì `/srv/ingat/bin/ingat`.

**Trên NAS Synology** (DSM 7.4 trở lên với Container Manager 24.0.2 trở lên):

1. Trong DSM Control Panel, tạo shared folder `ingat-backups`: chỉ đọc với quản trị viên, không ai khác được truy cập. Thêm nó vào một tác vụ Hyper Backup có mã hóa, để chép nó ra khỏi NAS mỗi đêm sau giờ sao lưu.
2. Bật SSH, đăng nhập, rồi chạy:

   ```sh
   sudo -i
   cd /path/to/downloads   # thư mục bạn đã lưu các tệp phát hành
   sh install.sh --version 0.1.0 --root /volume1/ingat --backups /volume1/ingat-backups
   ```

   Trên NAS, luôn chỉ rõ hai thư mục này. Thư mục mặc định `/srv` sẽ nằm trên phân vùng hệ thống nhỏ, mà một lần cập nhật DSM có thể đặt lại về ban đầu. Ở dưới, `ingat` nghĩa là `/volume1/ingat/bin/ingat`.

Máy không có internet? Thêm `--from-tar ingat-0.1.0-amd64.tar` (hoặc `ingat-0.1.0-arm64.tar` trên máy `aarch64`) để nạp Ingat từ tệp phát hành đó thay vì tải image về. Hãy tải tệp này từ cùng trang phát hành bằng một máy khác rồi chép nó vào cùng thư mục.

<details>
<summary>Mọi tùy chọn cài đặt</summary>

| Tùy chọn | Ý nghĩa |
|---|---|
| `--version X.Y.Z` | Bắt buộc. Phiên bản cần cài. Image được tải về dưới dạng `ghcr.io/lisahq/ingat@sha256:…`, đúng mã digest mà `SHA256SUMS` ghi cho phiên bản đó |
| `--root DIR`, `--backups DIR` | Đường dẫn đầy đủ tới thư mục riêng của Ingat (`INGAT_ROOT`) và thư mục sao lưu (`INGAT_BACKUPS`); chỉ gồm chữ, số và `/ . _ -` |
| `--from-tar FILE` | Nạp tệp phát hành này bằng `docker load` thay vì tải về (mã SHA-256 của nó phải có trong `SHA256SUMS`) |
| `--link PATH` | Tạo thêm một lối tắt tới lệnh `ingat` (việc chạy theo lịch luôn dùng đường dẫn đầy đủ) |

Trình cài đặt tạo `INGAT_ROOT` nếu chưa có, với quyền `root:root 0700` (chỉ root mở được), tạo volume `ingat-probe` (có gắn nhãn của Ingat), tự kiểm tra image mới, rồi ghi lệnh `ingat` vào `<root>/bin/ingat`. Chạy lại với cùng `--root` trên một máy đã có Ingat thì đó là nâng cấp: nó từ chối khi còn thao tác chưa xong (exit 2), chạy `selftest --host` với phiên bản mới, giữ phiên bản hiện tại nếu kiểm tra đó thất bại (exit 3), còn không thì giữ lệnh cũ ở `bin/ingat.prev`. Chi tiết: [`docs/design/ARCHITECTURE.vi.md`](docs/design/ARCHITECTURE.vi.md#34-cài-đặt) §3.4-§3.5.

</details>

### Bước 2: để Ingat kiểm tra máy của bạn

Làm việc này một lần:

```sh
ingat host init           # gắn Ingat với Docker này; gõ đúng tên mà lệnh hostname in ra để xác nhận
sh facts.sh > facts.json  # ghi lại thông tin về máy (không thay đổi gì); giữ lại tệp này
ingat selftest --host     # kiểm thử Ingat ở đây bằng các ứng dụng dùng xong bỏ; mất vài phút
ingat status              # "gate tier 2 (everything)" nghĩa là từ giờ Ingat được phép thay đổi ở máy này
```

Sau mỗi lần cập nhật hệ điều hành, kernel hoặc Docker, hãy chạy lại `ingat selftest --host`.

Trên NAS, đưa cho `facts.sh` cùng hai thư mục đó: `sh facts.sh --root /volume1/ingat --backups /volume1/ingat-backups > facts.json`.

### Bước 3: thêm ứng dụng đầu tiên

Ứng dụng của bạn cần có `ingat.toml` trong kho mã và các image do CI của nó build ([danh sách việc cho nhà phát triển ứng dụng](docs/design/ARCHITECTURE.vi.md#113-quy-tắc-tổng-quát)). Sau đó:

1. **Mô tả bản cài này của ứng dụng** (một *bản cài*, instance) trong một tệp nhỏ ở thư mục nhận tệp (inbox) của Ingat, ví dụ `/srv/ingat/inbox/lite-test.toml` (trên NAS: `/volume1/ingat/inbox/lite-test.toml`): tên, nơi chứa mã nguồn, cổng và địa chỉ, giữ lại bao nhiêu bản sao lưu. [Ví dụ](docs/guide/operator-guide.vi.md#3-thêm-ứng-dụng-của-bạn).
2. **Đăng ký nó:** `ingat init lite-test --config /srv/ingat/inbox/lite-test.toml --ref v1.2.0`, rồi gõ `lite-test` để xác nhận.
3. **Cài nó:** `ingat deploy lite-test v1.2.0`. Ingat hiện kế hoạch từng bước; gõ `lite-test` để duyệt. Nếu ứng dụng có các bước thiết lập, lần cài sẽ dừng giữa chừng (`paused`, exit 4) và nói bạn cần làm gì; làm xong, hãy chạy `ingat resume lite-test`.
4. **Xem nó:** `ingat status lite-test`.
5. **Lên lịch** sao lưu hằng đêm và thử khôi phục hằng tuần ([cách làm](docs/guide/operator-guide.vi.md#7-việc-chạy-hằng-đêm-và-hằng-tuần)).

Ingat chạy bên trong một container chỉ nhìn thấy hai thư mục của chính nó. Hãy đặt mọi tệp bạn đưa cho nó (tệp bản cài, mã nguồn ứng dụng đã tải về, dữ liệu đầu vào cho tác vụ) vào inbox, `INGAT_ROOT/inbox/`.

[Hướng dẫn vận hành](docs/guide/operator-guide.vi.md) đi qua tất cả những bước này chi tiết hơn.

## Dùng hằng ngày

`lite-test` là một tên bản cài ví dụ.

| Tôi muốn… | Lệnh |
|---|---|
| Xem mọi thứ đang thế nào | `ingat status` (hoặc `ingat status lite-test` cho một ứng dụng) |
| Sao lưu ngay bây giờ | `ingat backup lite-test --reason "before the mail change"` |
| Kiểm tra bản sao lưu mới nhất | `ingat verify lite-test --latest` |
| Chứng minh bản đó khôi phục được | `ingat verify lite-test --latest --restore-test` |
| Cập nhật lên phiên bản mới | `ingat deploy lite-test v1.3.0` |
| Dừng, chạy hoặc khởi động lại ứng dụng | `ingat stop lite-test`, `ingat start lite-test`, `ingat restart lite-test` |
| Đọc log của ứng dụng | `ingat logs lite-test app --since 1h` |
| Chạy một tác vụ do ứng dụng cung cấp | `ingat task lite-test <task>` |
| Xóa bản sao lưu cũ theo quy tắc giữ lại của tôi | `ingat prune lite-test --bundles`, rồi chạy lại với `--apply` |
| Làm tiếp hoặc hoàn tác một việc bị ngắt | `ingat resume lite-test` hoặc `ingat abandon lite-test` |
| Theo dõi lại một việc đang chạy | `ingat attach lite-test` |
| Nâng cấp chính Ingat | Tải `install.sh` và `SHA256SUMS` của bản phát hành mới, rồi chạy `sh install.sh --version <new version>` với cùng `--root` và `--backups` bạn đã dùng khi cài |

Khi còn việc cần làm tiếp, dòng cuối `next:` nêu lệnh cần chạy. Xem, sao lưu và kiểm tra không bao giờ cần duyệt. Một thay đổi sẽ yêu cầu bạn gõ tên bản cài (ví dụ `lite-test`); việc chạy theo lịch không bao giờ duyệt được thay đổi, nên nó từ chối. Thêm `--json` vào bất kỳ lệnh nào để nhận kết quả dưới dạng một khối cho máy đọc.

<details>
<summary>Mọi lệnh trong phiên bản 0.1.0 (mốc M1)</summary>

Chạy bằng root. Các lớp duyệt: A chỉ đọc; B chỉ thêm (bản sao lưu, kết quả kiểm tra) hoặc xóa những gì quy tắc giữ lại của bạn cho phép; C thay đổi một thứ gì đó và yêu cầu bạn gõ tên bản cài (với `host init` là đúng tên mà lệnh `hostname` in ra) tại một terminal ([`docs/design/LIFECYCLE.vi.md`](docs/design/LIFECYCLE.vi.md#2-lớp-duyệt-và-các-lệnh) §2). Mã thoát nằm ở [§6](docs/design/LIFECYCLE.vi.md#6-mã-thoát-mọi-lệnh). Đường dẫn mà `init --config` và `validate` nhận phải là đường dẫn đầy đủ nằm trong một trong hai thư mục của Ingat.

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

</details>

## Tình trạng

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
- Máy thật đầu tiên, một NAS Synology chạy DSM 7.4.1 với Container Manager 24.0.2-1706 (`x86_64`), đã đạt `ingat selftest --host` với phiên bản 0.1.0 (22 bước kiểm tra). [Chứng nhận](src/ingat/support/hosts/dsm-7.4.1-90080-0-containermanager-24.0.2-1706-4.4.302+-x86_64.json) của nó đã được commit; các mục kiểm tra bằng tay trong danh sách của nó vẫn còn mở.

**Chưa xong:**

- Bản phát hành v0.1.0 là bản nháp, chưa được công bố. Image `ghcr.io/lisahq/ingat:0.1.0` của nó thì đã công khai.
- Chưa có ứng dụng thật nào chạy dưới Ingat. Ứng dụng đầu tiên, `lite-test` (ứng dụng SQLite) trên chiếc NAS đó, sẽ hoàn thành mốc M1; điều kiện hoàn thành M1 chưa đạt. Tiếp theo là M2.
- Việc nâng cấp từ một bản phát hành thật sang bản kế tiếp chưa được kiểm thử: cho tới khi có bản phát hành thứ hai, bài kiểm thử chỉ nâng cấp giữa hai bản build của cùng một phiên bản.
- Chưa có trong phiên bản này: khôi phục; ứng dụng dùng Docker volume hoặc có dịch vụ cơ sở dữ liệu riêng; ứng dụng chỉ triển khai từ image; tác vụ `exec`; `secret set`; giao kế hoạch cho trợ lý AI; các lệnh có thể làm mất dữ liệu (lớp D); một vài tính năng của manifest ứng dụng (truyền tệp qua luồng, chụp lại log, kiểm tra trước và sau khi triển khai, `[schema]` dựa trên tác vụ); và việc `doctor` so địa chỉ proxy nó thấy với địa chỉ đã cấu hình.

**Đã quyết định, chưa làm:**

- **Bộ cung cấp dữ liệu (data provider)** ([ADR-0031](docs/design/adr/0031-data-providers.vi.md)): một ứng dụng liệt kê các bộ dữ liệu của nó (PostgreSQL, MySQL, MariaDB, SQLite, tệp thường), và các image hỗ trợ được ghim của chính Ingat sẽ sao lưu, kiểm tra và khôi phục chúng, nên ứng dụng không cần lệnh sao lưu riêng. Một danh mục công khai các ứng dụng đã được chứng nhận. Bản mô tả công khai mà các image provider phải tuân theo (contract) và các image đầu tiên làm song song với M2, phần còn lại ngay sau khi M2 đạt điều kiện hoàn thành.
- **`ingat ui`** ([ADR-0032](docs/design/adr/0032-local-session-bound-web-view.vi.md)): một trang web chỉ để xem cho phiên làm việc của bạn, chỉ mở được ngay trên máy đó, có lời giải thích dễ hiểu và một công cụ viết sẵn lệnh cho bạn. Phiên bản đầu tiên của nó không có quyền truy cập Docker. Nó đến sau phần giao kế hoạch của M2.
- **`ingat report` và `ingat support-bundle`** ([ADR-0033](docs/design/adr/0033-commercial-boundary-report-and-hosted-service.vi.md)): một bản tóm tắt tình trạng gửi ra ngoài mà bạn tự đăng ký, và một gói thông tin để gửi kèm khi bạn nhờ hỗ trợ. Cùng M2 hoặc M3.

**Miễn phí, và sẽ luôn miễn phí.** Ingat là mã nguồn mở theo giấy phép Apache License 2.0. Mọi thứ dùng để giữ gìn hay khôi phục dữ liệu của bạn sẽ không bao giờ phải trả tiền, không bao giờ bị giới hạn và không bao giờ phụ thuộc vào gói dịch vụ. Một trang tình trạng do bên Ingat vận hành có thể trở thành dịch vụ trả phí sau này ([ADR-0033](docs/design/adr/0033-commercial-boundary-report-and-hosted-service.vi.md)).

### Lộ trình tóm tắt

| Mốc | Mang lại gì | Tình trạng |
|---|---|---|
| M0 Quyết định và thông tin máy | Tên và không gian tên, thông tin về máy đầu tiên, kiểm tra cách chạy, nơi build image ứng dụng | Đang làm |
| M1 Ứng dụng thật đầu tiên | `lite-test` (ứng dụng SQLite) trên máy đầu tiên, một NAS Synology; CI bao phủ Linux thông thường | Đang làm: mã đã xong, điều kiện hoàn thành còn mở |
| M2 Khôi phục và ứng dụng PostgreSQL | Khôi phục vào một vùng dữ liệu mới cho cả hai ứng dụng; `pg-staging` trên máy đầu tiên; giao kế hoạch cho trợ lý AI; chốt cố định định dạng `ingat.toml` | Tiếp theo |
| M3 Sẵn sàng cho môi trường thật | Quay về phiên bản cũ, gỡ một ứng dụng, dọn dẹp, giám sát, công cụ hỗ trợ lập lịch cho systemd, cron và DSM; `pg-prod` (khi quyết định của chủ sở hữu OD-5 cho phép) | Đã lên kế hoạch |
| M4 Phục hồi sau sự cố và tiếp quản ứng dụng | Khôi phục trên máy khác, nhập bản sao lưu, tiếp quản một ứng dụng đã cài không qua Ingat; chứng nhận một máy chủ Linux thông thường (khi có một máy như vậy) | Đã lên kế hoạch |
| M5 Ingat tự nâng cấp | Lệnh tự nâng cấp và lệnh chuyển đổi bản ghi | Khi cần |

Chi tiết, quy mô và điều kiện hoàn thành: [`docs/design/ROADMAP.vi.md`](docs/design/ROADMAP.vi.md).

## Chạy trên máy nào

Ingat xử lý khác biệt giữa các máy bằng cách kiểm tra mỗi máy làm được gì, không bao giờ dựa vào thương hiệu, hãng hay đời máy.

| | Máy | Cần gì |
|---|---|---|
| **Được hỗ trợ** | Linux mọi bản phân phối (máy chủ, máy ảo, VPS hay bo mạch nhỏ) với Docker Engine bản gốc (upstream) trên một dòng phiên bản mà CI kiểm thử: hiện là 24.0 và 29.9 trên `x86_64`, 29.9 trên `arm64` | `ingat selftest --host` trên máy đó, chạy lại sau mỗi lần cập nhật kernel, hệ thống hoặc Docker |
| **Được hỗ trợ, theo từng bản build đã chứng nhận** | Thiết bị dùng bản Docker do chính hãng build. Đầu tiên: Synology DSM 7.4 trở lên với Container Manager 24.0.2 trở lên. Đã chứng nhận đến nay: DSM 7.4.1 build 90080 với Container Manager 24.0.2-1706 trên `x86_64` | Một chứng nhận được commit cho từng dòng build, cộng với `ingat selftest --host` sau mỗi lần cập nhật |
| **Không được hỗ trợ** | Rootless Docker; Docker Desktop trên Windows hoặc macOS để dùng thật (chỉ để phát triển); Podman; Kubernetes hoặc Swarm; nhiều máy cùng lúc; Docker Engine cũ hơn 24.0, tức là loại bỏ Synology DSM 7.1 trở về trước với gói Docker cũ | Không có kế hoạch bổ sung trong v1 |

Khi bản build hệ thống và Docker của một máy chưa được chứng nhận, Ingat vẫn cho bạn xem mọi thứ và vẫn tiếp tục các bản sao lưu không cần dừng ứng dụng, nhưng từ chối mọi thay đổi. Thêm: [`docs/design/ARCHITECTURE.vi.md`](docs/design/ARCHITECTURE.vi.md#11-máy-và-bảng-hỗ-trợ) §11.

<details>
<summary>Các bậc hỗ trợ và đặc điểm nền tảng, theo lời của bản đặc tả</summary>

Tóm tắt [`docs/design/ARCHITECTURE.vi.md`](docs/design/ARCHITECTURE.vi.md) §11.1-§11.2:

- **Bậc hỗ trợ 1 (support tier 1):** máy Linux chạy Docker Engine bản gốc (docker-ce hoặc gói của bản phân phối) trên một dòng Engine mà CI kiểm thử, trên `x86_64`, hoặc trên `arm64` với những dòng mà làn arm64 đã đạt (chỉ 29.x). Các làn CI bao phủ bậc này từ M1; các lệnh có thay đổi (bậc cổng 2, gate tier 2) cần một chứng nhận `ingat selftest --host` tại máy cho bản build nền tảng của máy đó. Chứng nhận Linux thông thường đầu tiên được commit đã lên kế hoạch (Planned) cho phần việc 12 của M4, khi có một máy như vậy.
- **Bậc hỗ trợ 2 (support tier 2):** các engine do hãng build trên thiết bị, trước hết là Synology DSM 7.4 trở lên với Container Manager 24.0.2 trở lên (bản build Engine 24.0.2 của Synology, API 1.43). Mỗi dòng bản build nền tảng cần một chứng nhận được commit theo đầy đủ danh sách kiểm tra, và mỗi lần cập nhật cần một `ingat selftest --host` tại máy; trong lúc chờ, các bản sao lưu hằng đêm không cần dừng ứng dụng vẫn tiếp tục, còn các lần thử khôi phục theo lịch thì từ chối. DSM 7.4 hết thời gian bảo trì vào khoảng tháng 6 năm 2028, nên việc chuyển sang dòng DSM tiếp theo là một lần chứng nhận lại đã được tính trước.
- **Đặc điểm:** Ingat từ chối giới hạn `cpus` khác 0 ngay lúc lập kế hoạch trên máy không có CPU CFS quota, ghi log qua driver `local` bất kể mặc định của daemon (tác vụ terminal và CLI qua `none`), ghi nhận runc cũ (CVE-2024-21626) hoặc việc thiếu seccomp như một rủi ro của máy, không phụ thuộc vào storage driver hay phiên bản cgroup nào, và dựa việc phục hồi vào các bản sao lưu đã niêm phong cộng với một bản sao mã hóa ở nơi khác làm bằng công cụ của nền tảng, không bao giờ dựa vào snapshot. Dind bản gốc không tái tạo được một Engine của hãng, nên chỉ chứng nhận máy mới bao phủ được nó.

</details>

## Cách hoạt động, nói ngắn gọn

- Ingat là một container image được ghim cố định (`linux/amd64` và `linux/arm64`) có sẵn Python, dòng lệnh Docker, Compose và git bên trong, được khởi động bởi một script 20 dòng mà chỉ root chạy được. Máy chủ, VPS và NAS chạy đúng cùng những byte đó; Python và Compose có sẵn trên máy không bao giờ được dùng.
- Mọi thay đổi chạy trong một container trợ giúp riêng (`ingat-exec-<instance>`), nên một phiên SSH bị ngắt hay một việc chạy theo lịch không bao giờ làm dừng việc cập nhật dữ liệu giữa chừng. Lệnh bạn gõ chỉ lập kế hoạch, hỏi duyệt và theo dõi. Ngoại lệ là các tác vụ trò chuyện với bạn trong terminal, chạy từ chính cửa sổ của bạn, và ba lệnh ngắn chỉ thay đổi bản ghi của chính Ingat (`host init`, `init`, `secret set`).
- Compose luôn chạy trên chính các tệp Compose của ứng dụng cộng với một tệp do Ingat tạo ra; tệp này ghim từng dịch vụ vào đúng image đã ghi nhận và thêm những nhãn không bao giờ đổi giữa các lần triển khai, nên một lần cập nhật chỉ tạo lại những dịch vụ có thiết lập thay đổi.
- Mỗi ứng dụng tự giữ hiểu biết về dữ liệu của nó trong image của chính nó. Tệp `ingat.toml` của nó nằm trong kho mã của ứng dụng, được đọc từ đúng phiên bản đang cài, và khai báo các tác vụ (sao lưu, khôi phục, kiểm tra, cập nhật dữ liệu) cùng ý nghĩa của từng mã thoát.
- Một cơ sở dữ liệu chỉ được coi là sẵn sàng sau khi phép kiểm tra sẵn sàng mà ứng dụng khai báo cho nó đã đạt, chứ không chỉ vì container của nó đã khởi động.
- Mỗi thao tác có một nhật ký các bước: mỗi bước được ghi lại trước khi chạy, và được kiểm tra trước khi thử lại. Mỗi ứng dụng chỉ có tối đa một thao tác đang mở tại một thời điểm.

Toàn bộ thiết kế: [`docs/design/ARCHITECTURE.vi.md`](docs/design/ARCHITECTURE.vi.md) và [`docs/design/LIFECYCLE.vi.md`](docs/design/LIFECYCLE.vi.md).

## Tìm hiểu thêm

| Nếu bạn là… | Hãy đọc |
|---|---|
| Người chạy Ingat trên máy của mình | [Hướng dẫn vận hành](docs/guide/operator-guide.vi.md): cài đặt, kiểm tra máy, thêm ứng dụng, việc hằng ngày, việc chạy theo lịch, phải làm gì khi có sự cố |
| Người làm cho ứng dụng của mình chạy được với Ingat | [`docs/app-developers/MANIFEST_SPEC.vi.md`](docs/app-developers/MANIFEST_SPEC.vi.md): các tệp `ingat.toml` và `instance.toml`, kèm ví dụ đầy đủ; [danh sách việc khi đưa ứng dụng vào](docs/design/ARCHITECTURE.vi.md#113-quy-tắc-tổng-quát) |
| Người tò mò Ingat hoạt động bên trong ra sao | [`docs/design/ARCHITECTURE.vi.md`](docs/design/ARCHITECTURE.vi.md) (thiết kế, bảo mật, kiểm thử, các máy được hỗ trợ) và [`docs/design/LIFECYCLE.vi.md`](docs/design/LIFECYCLE.vi.md) (quy tắc an toàn bắt buộc, duyệt, từng thao tác theo từng bước, mã thoát) |
| Người theo dõi kế hoạch | [`docs/design/ROADMAP.vi.md`](docs/design/ROADMAP.vi.md): các mốc, điều kiện hoàn thành, và những việc chờ một điều kiện kích hoạt |
| Người muốn biết vì sao một lựa chọn được đưa ra | [`docs/design/adr/`](docs/design/adr/README.vi.md): mỗi lựa chọn có một bản ghi quyết định |
| Người đóng góp, hoặc một agent phát triển (trợ lý AI) | [`CLAUDE.md`](CLAUDE.md) trước tiên: các quy tắc cho mọi thay đổi |

Tài liệu được xếp theo người đọc: [`docs/guide/`](docs/guide/) cho người chạy Ingat, [`docs/app-developers/`](docs/app-developers/) cho nhà phát triển ứng dụng, và [`docs/design/`](docs/design/) cho thiết kế, kế hoạch và các bản ghi quyết định.

Mỗi tài liệu, trừ [`CLAUDE.md`](CLAUDE.md), đều có một bản tiếng Việt bên cạnh, tên là `<name>.vi.md`. Bản tiếng Anh là bản chuẩn.

## Các từ dùng trong Ingat

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

## Quy ước dùng trong mọi tài liệu

- **Nhãn trạng thái:** **Decided** (Đã quyết định: một phần của thiết kế), **Planned Mx** (Đã lên kế hoạch: đã quyết định, làm trong mốc x), **Open OD-n** (Còn mở: cần một quyết định của chủ sở hữu), **Unverified** (Chưa kiểm chứng: một đặc điểm nền tảng mà thử nghiệm sớm M0 hoặc một thử nghiệm sau phải xác nhận).
- **Một bộ từ phán định duy nhất** cho điều kiện hoàn thành, CI và báo cáo: `PASS`, `FAIL`, `BLOCKED`.
- **Quyết định của chủ sở hữu** được trích dẫn là "owner decision OD-n" (quyết định của chủ sở hữu OD-n). OD-1, OD-2, OD-3 và OD-11 đã được quyết định; các quyết định còn lại vẫn mở và được ghi trong ghi chú riêng của chủ sở hữu, không thuộc kho mã này.
- **Ứng dụng mẫu không nêu tên.** Hai ứng dụng thật định hướng thiết kế. Ở đây chúng chỉ được gọi bằng tên chung:
  - *ứng dụng PostgreSQL* (the PostgreSQL consumer): một ứng dụng web nhiều dịch vụ (PostgreSQL, một backend và một dịch vụ web) có một bước cập nhật dữ liệu riêng, cấp quyền vai trò sau khi khôi phục và một lệnh kiểm tra tính nhất quán; được mô phỏng bởi ứng dụng thử `fx-pg`;
  - *ứng dụng SQLite* (the SQLite consumer): một ứng dụng một container có SQLite trong một thư mục dữ liệu gắn từ máy (bind mount), sao lưu ngay khi ứng dụng đang chạy, bằng cơ chế riêng của ứng dụng, một hàng đợi thư gửi đi, và cập nhật dữ liệu khi khởi động; được mô phỏng bởi ứng dụng thử `fx-lite`;
  - `fx-web`: một ứng dụng thử không có dữ liệu.

  Tên bản cài ví dụ: `pg-staging`, `pg-prod`, `lite-test`, `site`.
- **Công cụ cũ** là "an earlier in-house deployment controller" (một công cụ triển khai nội bộ trước đây). Ingat được viết lại từ đầu và **không tương thích** gì với nó: không dùng chung nhãn, thư mục gốc, bản ghi, bản sao lưu, volume hay image, và không đọc bất kỳ định dạng nào của nó. Bài học từ nó chỉ xuất hiện dưới dạng lý do ngắn gọn, chung chung, không bao giờ là trích dẫn. Tiếp quản một bản triển khai làm ngoài Ingat là một tính năng của sản phẩm (tiếp quản, M4).

## Tên gọi

| Mục | Giá trị |
|---|---|
| Sản phẩm | Ingat |
| CLI | `ingat` |
| Kho mã (repository) | `github.com/LisaHQ/ingat` |
| Tiền tố biến môi trường | `INGAT_` (ví dụ `INGAT_ROOT`, `INGAT_BACKUPS`) |
| Không gian tên nhãn | `io.github.lisahq.ingat.` (ví dụ `io.github.lisahq.ingat.instance`) |
| Image | `ghcr.io/lisahq/ingat` (công khai, đa kiến trúc `linux/amd64` và `linux/arm64`, tải theo digest) |
| Thư mục gốc mặc định | `/srv/ingat` (trạng thái của công cụ: một thư mục POSIX thường, `root:root 0700`) và `/srv/ingat-backups` (các bản sao lưu đã niêm phong, chỉ root ghi); script khởi động `/srv/ingat/bin/ingat`; cả hai đổi được lúc cài (`--root`, `--backups`) |
| Thư mục gốc theo hồ sơ DSM | `/volume1/ingat` (không bao giờ là shared folder) và `/volume1/ingat-backups` (một shared folder của DSM, chỉ đọc với quản trị viên, chỉ root ghi, là nguồn cho Hyper Backup); script khởi động `/volume1/ingat/bin/ingat`; truyền vào lúc cài, không phải mặc định trong mã |
| Tên Docker suy ra | Project Compose `<instance>`, trình thực thi `ingat-exec-<instance>`, các project cách ly `<instance>--r<seq>` (khôi phục) và `<instance>--t<seq>` (thử khôi phục), volume `<instance>_<store>_g<N>` |

Trong mã, các tên này chỉ nằm trong `src/ingat/brand.py` và mẫu script khởi động ([ADR-0003](docs/design/adr/0003-name-namespaces-and-brand-module.vi.md)); tài liệu dùng chúng nguyên văn.

## Đóng góp và agent AI

Hãy đọc [`CLAUDE.md`](CLAUDE.md) trước khi thay đổi bất cứ thứ gì. Đó là tệp hướng dẫn cho agent phát triển (trợ lý AI) và cũng áp dụng cho người đóng góp: quy tắc nội dung công khai (chỉ nội dung chung, không có giá trị của ứng dụng thật hay của máy), các lớp mã, các quy tắc an toàn bắt buộc, kiểm thử và định dạng mô tả commit. Agent phát triển không bao giờ chạy Ingat, `docker` hay `install.sh` trên một máy thật; chúng chỉ dùng CI và các Docker daemon dùng xong bỏ.

## Giấy phép

Ingat được cấp phép theo [Apache License 2.0](LICENSE).
