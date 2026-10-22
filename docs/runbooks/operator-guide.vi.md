# Hướng dẫn vận hành Ingat

[English](operator-guide.md) · **Tiếng Việt** (bản dịch; bản tiếng Anh là bản chuẩn)

Hướng dẫn này dành cho người chạy Ingat trên một máy: bạn cài nó, thêm các ứng dụng của mình, và giữ cho chúng luôn được sao lưu và cập nhật. Hướng dẫn nói bạn cần gõ gì và sẽ thấy gì. Lý do đằng sau từng quy tắc nằm trong [`LIFECYCLE.vi.md`](../LIFECYCLE.vi.md) và [`ARCHITECTURE.vi.md`](../ARCHITECTURE.vi.md).

Hướng dẫn áp dụng cho phiên bản 0.1.0 (mốc M1), tức các lệnh đã có trong mã hôm nay ([README](../../README.vi.md#dùng-hằng-ngày)). Khôi phục, việc duyệt các lệnh có thể làm mất dữ liệu (lớp D), `secret set` và việc giao một kế hoạch cho trợ lý AI (`plan`/`apply`) sẽ có ở M2 ([`ROADMAP.vi.md`](../ROADMAP.vi.md)); hướng dẫn nói rõ ở những chỗ liên quan.

**Cách đọc các ví dụ.** Chạy mọi lệnh bằng tài khoản quản trị của máy, root. `ingat` là lệnh `ingat` mà trình cài đặt tạo ra: `/srv/ingat/bin/ingat` với các thư mục mặc định, hoặc `/volume1/ingat/bin/ingat` trên NAS Synology. `lite-test` là một bản cài ví dụ (một bản cài của một ứng dụng, instance) của ứng dụng mẫu `fx-lite`.

**Vài từ bạn sẽ gặp:**

- **bản cài** (instance): một bản cài của một ứng dụng, có tên riêng, ví dụ `lite-test`.
- **các phần ghi dữ liệu** (writers): những phần của ứng dụng thay đổi dữ liệu của bạn.
- **bản sao lưu**: một bản sao lưu đã niêm phong của một bản cài (bản ghi của Ingat gọi nó là *bundle*).
- **`INGAT_ROOT`:** thư mục riêng của Ingat. **`INGAT_BACKUPS`:** thư mục chứa các bản sao lưu.

## 1. Trước khi bắt đầu

- **Máy.** Bạn cần một Docker Engine Linux 24.0 trở lên có plugin `docker compose`, truy cập được bằng root qua socket cục bộ; SSH với `sudo -i`; một bộ lập lịch gửi email cho bạn khi một việc bị lỗi (systemd timer, cron, hoặc Task Scheduler trên NAS Synology); và một công cụ chép các bản sao lưu sang nơi khác (restic, borg, rsync, hoặc Hyper Backup trên NAS Synology). Chi tiết: [`ARCHITECTURE.vi.md`](../ARCHITECTURE.vi.md#114-yêu-cầu-tối-thiểu-cho-máy) §11.4.
- **Hai thư mục.**
  - `INGAT_ROOT` giữ các bản ghi của Ingat và dữ liệu đang dùng của những ứng dụng lưu dữ liệu trong thư mục thường. Mặc định `/srv/ingat`. Nó phải thuộc root với quyền `0700`, tức chỉ root mở được, và phải nằm trên ổ đĩa bên trong máy này, không bao giờ trên ổ mạng.
  - `INGAT_BACKUPS` giữ các bản sao lưu đã hoàn tất. Mỗi bản được niêm phong bằng mã kiểm tra, nên mọi thay đổi về sau trên nó đều bị phát hiện. Mặc định `/srv/ingat-backups`. Chỉ root ghi vào đó, và đây là thư mục mà bản sao ở nơi khác của bạn được chép từ đó ra.
  - Trên NAS Synology, hãy truyền `--root /volume1/ingat --backups /volume1/ingat-backups` khi cài. Ở đó không bao giờ dùng mặc định `/srv`.
- **Ingat chỉ nhìn thấy hai thư mục này.** Nó chạy trong container riêng của nó, chỉ được cho thấy `INGAT_ROOT` và `INGAT_BACKUPS`, không thấy gì khác trên máy. Vì vậy mọi đường dẫn tệp bạn đưa cho nó (`init --config`, `validate <repo-dir>`, `validate --instance`, các tệp `--input` của tác vụ) phải là đường dẫn đầy đủ nằm trong một trong hai thư mục đó, nếu không Ingat sẽ không tìm thấy tệp. Hãy đặt những tệp như vậy, và mã nguồn ứng dụng đã tải về, vào hộp thư đến (inbox): `INGAT_ROOT/inbox/`.
- **Ứng dụng của bạn** cần có `ingat.toml` trong repository và các image do CI của nó build ([`MANIFEST_SPEC.vi.md`](../MANIFEST_SPEC.vi.md); danh sách việc khi đưa ứng dụng vào trong [`ARCHITECTURE.vi.md`](../ARCHITECTURE.vi.md#113-quy-tắc-tổng-quát) §11.3). `ingat validate <repo-dir>` kiểm tra một bản mã nguồn đã tải về mà không thay đổi gì, ví dụ một bản nằm dưới `INGAT_ROOT/inbox/`.
- **Giữ Docker ở một phiên bản đã kiểm thử.** Các lệnh có thay đổi chỉ chạy trên một dòng phiên bản Docker Engine mà bản phát hành Ingat này đã được kiểm thử cùng (danh sách nằm sẵn trong Ingat, tệp `tested.json`), và chỉ sau lần kiểm tra máy ở mục 2, việc bạn làm lại sau mỗi lần cập nhật máy. Trên một phiên bản Docker khác, `ingat status` báo `not a tested combination of this release`: bạn vẫn xem được mọi thứ và vẫn sao lưu được theo cách không dừng ứng dụng, nhưng mọi lệnh thay đổi ứng dụng hay dữ liệu đều từ chối. Vì vậy đừng để Docker tự cập nhật: trên máy Linux hãy ghim `docker-ce` (`apt-mark hold`), và chỉ lên Docker mới cùng với một bản phát hành Ingat đã được kiểm thử với nó.

## 2. Cài Ingat và kiểm tra máy

Làm một lần cho mỗi máy. Bằng root, với `install.sh`, `facts.sh` và `SHA256SUMS` của bản phát hành trong cùng một thư mục:

```sh
sudo -i
sh install.sh --version 0.1.0          # thư mục mặc định; thêm --root và --backups trên NAS Synology
ingat host init                        # gắn Ingat với Docker này; gõ tên máy để duyệt
sh facts.sh > facts.json               # ghi lại thông tin về máy (không thay đổi gì); giữ tệp cùng ghi chú của bạn
ingat selftest --host                  # kiểm thử Ingat trên máy này: in một dòng tóm tắt, rồi im lặng tới khi xong (vài phút)
ingat status                           # "gate tier 2 (everything)" ở những dòng cuối: từ giờ Ingat được phép thay đổi ở máy này
```

Trên NAS Synology, đưa cho `facts.sh` cùng hai thư mục đó: `sh facts.sh --root /volume1/ingat --backups /volume1/ingat-backups > facts.json`.

**Bạn sẽ thấy gì.**

- `install.sh` in các dòng tự kiểm tra offline và `installed version …`.
- `host init` in phiên bản Docker, storage driver và kernel, rồi hoặc `gate tier 2: this platform build is certified` (hệ thống và Docker của máy này đã được duyệt cho các lệnh có thay đổi), hoặc lý do vì sao chưa được.
- `selftest --host` in một dòng `PASS` cho mỗi bước kiểm tra và đường dẫn của tệp chứng nhận nó đã ghi.

**Sau mỗi lần cập nhật hệ điều hành, kernel hoặc Docker**, hãy chạy lại `ingat selftest --host`. Chừng nào bạn chưa chạy, `status` báo `uncertified` dưới `attention:`, và lần thử khôi phục theo lịch từ chối chạy (exit 2). Các bản sao lưu hằng đêm vẫn chạy chừng nào ứng dụng sao lưu được mà không cần dừng (như `fx-lite`).

**Máy không có internet?** `sh install.sh --version 0.1.0 --from-tar ingat-0.1.0-amd64.tar` nạp Ingat từ tệp phát hành thay vì tải về.

## 3. Thêm ứng dụng của bạn

1. **Viết tệp bản cài** vào inbox, ví dụ `/srv/ingat/inbox/lite-test.toml`. Mọi khóa và một ví dụ đầy đủ: [`MANIFEST_SPEC.vi.md`](../MANIFEST_SPEC.vi.md) §6 và §12. Tối thiểu cho `fx-lite`:

   ```toml
   instance = 1
   name = "lite-test"
   app = "fx-lite"
   environment = "test"
   disposable = false

   [source]
   repo = "ssh://git@github.com/<owner>/<app>.git"
   key = "fx-lite"                      # /srv/ingat/keys/fx-lite/{id_ed25519,known_hosts}, quyền 0600

   [params]
   FXLITE_IMAGE = "ghcr.io/<owner>/fx-lite@sha256:<digest>"   # image do CI build cho bản phát hành; fx-lite bắt buộc có
   FXLITE_PORT = "20090"                # bỏ khóa này đi thì một cổng sẽ được chọn trong dải 20000-29999

   [app_env]
   ALLOWED_ORIGINS = "https://lite-test.example.internal"
   BASE_URL = "https://lite-test.example.internal"
   MAIL_SENDER = "lite-test@example.invalid"
   PROXY_ADDRESS = "127.0.0.1"

   [backups]
   keep_daily = 7
   keep_weekly = 4
   ```

2. **Với repository truy cập qua `ssh://`**, đặt deploy key chỉ đọc của nó và một tệp `known_hosts` đã ghim vào `INGAT_ROOT/keys/<key>/`.
3. **Kiểm tra (không bắt buộc):** `ingat validate /srv/ingat/inbox/<checkout> --instance /srv/ingat/inbox/lite-test.toml`.
4. **Đăng ký bản cài:** `ingat init lite-test --config /srv/ingat/inbox/lite-test.toml --ref v1.2.0`, rồi gõ `lite-test` để duyệt. Ingat tải mã nguồn của ứng dụng ở phiên bản `v1.2.0`, đọc tệp `ingat.toml` của ứng dụng trong đó, chọn cổng mạng nào bạn chưa khai báo, và tự tạo những mật khẩu mà ứng dụng cho phép tự sinh (bạn không bao giờ thấy hay gõ chúng; những mật khẩu bạn phải tự cung cấp nằm ở bước 5). Lệnh kết thúc với `next: ingat deploy lite-test v1.2.0`.
5. **Mật khẩu bạn tự cung cấp.** Một số bí mật (secret) mà ứng dụng khai báo, ví dụ thông tin đăng nhập mail, do bạn đưa vào. Từ M2 bạn đặt chúng bằng `ingat secret set`. Ở M1, sau `init` (lệnh này tạo `secrets/env/` với quyền 0700) và trước lần triển khai đầu tiên, hãy đặt mỗi giá trị vào một tệp `INGAT_ROOT/instances/lite-test/secrets/env/<KEY>`, quyền 0600, không có dấu xuống dòng ở cuối. Chạy lại `init` sau đó vẫn giữ nguyên tệp đã có.

**Tên bản cài** viết thường và tối đa 30 ký tự: bắt đầu bằng một chữ cái, sau đó là chữ cái, chữ số và dấu gạch nối đơn, không bao giờ có gạch nối ở đầu hay ở cuối. `ingat list` liệt kê các bản cài trên máy này.

## 4. Cài ứng dụng

```sh
ingat deploy lite-test v1.2.0
```

**Chuyện gì xảy ra.**

1. Nếu phiên bản này chưa được chuẩn bị, Ingat chuẩn bị trước: tải các image của ứng dụng (các tệp chương trình đã đóng gói) và ghi lại chính xác những bản đã tải. Việc này không thay đổi gì ở ứng dụng đang chạy, nên không cần duyệt.
2. Ingat in kế hoạch: mỗi bước một dòng có đánh số, kèm mức rủi ro của bước (lớp của nó). Một bước được đánh dấu `forward point`: sau bước đó, Ingat không còn hoàn tác thay đổi một cách đơn giản được nữa.
3. Bạn gõ tên bản cài (`lite-test`) để duyệt.
4. Trong lúc chạy, mỗi bước in hai dòng có giờ: `started`, rồi `done` (hoặc giai đoạn bị lỗi). Dòng cuối là `operation <outcome>`.

**Nó có thể kết thúc thế nào.**

| Kết cục | Exit | Ý nghĩa và việc cần làm |
|---|---|---|
| `completed` | 0 | Ứng dụng đang chạy. `next: ingat status lite-test`. |
| `paused` | 4 | Điểm dừng cài đặt của ứng dụng. Thông báo nói bạn cần làm gì. Với `fx-lite`: chép tệp bootstrap vào `INGAT_ROOT/inbox/`, chạy `ingat task lite-test bootstrap-config --input config=<file>`, hoàn tất thiết lập trên trình duyệt, rồi chạy `ingat resume lite-test` và gõ tên lần nữa. |
| `failed-unchanged` | 3 | Một bước bị lỗi, nhưng chưa có gì thay đổi lâu dài: Ingat đã dừng mọi thứ nó khởi động, ứng dụng và dữ liệu của bạn vẫn như trước. Đọc thông báo, sửa nguyên nhân được nêu, rồi chạy lại đúng lệnh đó. |
| `failed-frozen` | 3 | Một bước bị lỗi sau khi ứng dụng đã cập nhật dữ liệu (với `fx-lite`, bước cập nhật dữ liệu lúc cài chính là `forward point`). Ingat đặt bản cài vào trạng thái tạm khóa ("frozen"): các phần ghi dữ liệu vẫn dừng để không gì bị hỏng. Dòng `next:` hiện lại chính lệnh `deploy` này; chạy lại sẽ tiếp tục từ dữ liệu mà lần cài đã tạo ra (mục 8). |
| `needs-review` | 4 | Có gì đó bị lỗi và Ingat không tự hoàn tác hết được, nên cần đến bạn. Trước khi chạy gì khác, hãy đọc các cảnh báo in trong kết quả và `ingat history lite-test`, lệnh liệt kê mọi thao tác đã qua và kết cục của từng thao tác. |
| đã hủy | 130 | Bạn đã hủy trước khi có gì thay đổi. |

`ingat deploy` phải do một người gõ trong terminal, vì lệnh sẽ hỏi bạn gõ tên bản cài. Nếu một việc chạy theo lịch hoặc một script chạy nó, Ingat từ chối (exit 2) trước khi thay đổi hay tải bất cứ thứ gì.

## 5. Việc hằng ngày

| Việc | Lệnh | Ghi chú |
|---|---|---|
| Xem trạng thái | `ingat status lite-test` | Mỗi dòng bắt đầu bằng `attention:` là một việc cần đến bạn; khi đó lệnh kết thúc với mã thoát 5. Dòng cuối, `next:`, là lệnh cần chạy. `ingat status` không kèm tên thì hiện mọi bản cài trên máy này. |
| Kiểm tra kỹ hơn | `ingat doctor lite-test` | Kiểm tra thiết lập của ứng dụng theo các quy tắc an toàn, việc máy đã được duyệt cho thay đổi chưa, các tệp bí mật, trùng cổng và các thư mục. |
| Container, log, các thao tác đã qua, các bản sao lưu | `ingat ps lite-test`, `ingat logs lite-test app --since 1h`, `ingat history lite-test`, `ingat bundles lite-test` | Những lệnh này chỉ đọc; chúng không bao giờ ghi gì. |
| Sao lưu ngay | `ingat backup lite-test --reason "before the mail change"` | Không cần duyệt. Trong lúc chạy, các phần ghi dữ liệu sẽ dừng, trừ khi ứng dụng sao lưu được toàn bộ dữ liệu ngay khi đang chạy (như `fx-lite`). |
| Kiểm tra một bản sao lưu | `ingat verify lite-test --latest` | Kiểm tra bản sao lưu vẫn đúng y như lúc được ghi (không thiếu, không hỏng tệp nào) và chạy các bước kiểm tra riêng của ứng dụng trên nó. |
| Thử khôi phục một bản sao lưu | `ingat verify lite-test --latest --restore-test` | Chứng minh bản sao lưu thật sự khôi phục được: Ingat khôi phục nó vào một bản tạm, tách riêng của ứng dụng, không chạm được tới dữ liệu đang dùng của bạn, kiểm tra, rồi xóa bản tạm đó. Ứng dụng đang chạy không bị đụng tới. Sau đó bản sao lưu được đánh dấu `restore-tested`. |
| Xóa bản sao lưu cũ | `ingat prune lite-test --bundles`, rồi chạy lại với `--apply` | Lệnh đầu chỉ liệt kê những bản cũ sẽ bị xóa theo các thiết lập giữ lại trong tệp bản cài của bạn (`keep_daily`, `keep_weekly`, `keep_monthly`); chưa có gì bị xóa cho tới khi bạn thêm `--apply`. `scheduled backup` hằng đêm tự làm việc dọn này. |
| Dừng, chạy, khởi động lại | `ingat stop lite-test`, `ingat start lite-test`, `ingat restart lite-test` | Lớp C: gõ tên mỗi lần. |
| Chạy một tác vụ do ứng dụng cung cấp | `ingat task lite-test queue-status`, `… --arg job=<id>`, `… --input config=<file>` | Xem bên dưới. |
| Cập nhật lên phiên bản mới | `ingat deploy lite-test v1.3.0` | Mục 6. |

**Về các tác vụ của ứng dụng.**

- Tác vụ chỉ đọc thì chạy không cần duyệt. Tác vụ thay đổi ứng dụng hoặc dữ liệu thì yêu cầu bạn gõ tên bản cài. Mọi tác vụ `queue-*` và `bootstrap-*` của `fx-lite` đều thuộc loại này, và chúng từ chối chạy khi bản cài đang tạm khóa (frozen).
- Đặt mọi tệp đầu vào trong `INGAT_ROOT/inbox/`.
- Tác vụ trò chuyện với bạn trong terminal chỉ hiện kết quả cho bạn; không có gì từ nó được lưu lại.
- Nếu một tác vụ thay đổi ứng dụng kết thúc theo cách ứng dụng không khai báo (không phải mã `ok`, cũng không phải một lỗi đã khai báo), Ingat không biết tác vụ đã làm gì. Nó báo `needs-review` (exit 4): hãy xem kết quả trước khi chạy gì khác.

## 6. Cập nhật

Chạy `ingat deploy lite-test v1.3.0`. Chuyện gì xảy ra tùy vào những gì phiên bản mới thay đổi.

- **Chỉ thiết lập thay đổi.** Ingat chỉ thay những phần của ứng dụng có thiết lập thay đổi, và khởi động chúng với thiết lập mới.
- **Dữ liệu bị đụng tới.** Đây là trường hợp phiên bản mới thay đổi chương trình của một phần ghi dữ liệu, hoặc của bất kỳ phần nào của một ứng dụng tự cập nhật dữ liệu mỗi lần khởi động. Khi đó kế hoạch hiện các bước an toàn:
  1. `Stop` (dừng) các phần ghi dữ liệu;
  2. tạo một bản sao lưu `pre-change` (trước thay đổi);
  3. kiểm tra bản đó;
  4. chạy bước cập nhật dữ liệu của ứng dụng (`migrate`, được đánh dấu `forward point`: sau bước này Ingat không còn quay lại đơn giản được nữa);
  5. chuyển ứng dụng sang phiên bản mới.

  Từ bước `Stop` cho tới lúc chuyển xong, ứng dụng không nhận thay đổi, nên hãy chọn lúc vắng người dùng.

**Nếu một bước sau `forward point` bị lỗi**, thao tác kết thúc `failed-frozen` (exit 3). Ứng dụng bị tạm khóa với các phần ghi dữ liệu đang dừng, và dòng `next:` hiện lại chính lệnh `deploy` đó. Chạy lại sẽ tiếp tục từ bản sao lưu `pre-change` đã kiểm tra, với hai điều kiện:

- bước cập nhật dữ liệu của ứng dụng chạy hai lần vẫn an toàn (manifest của nó ghi `idempotent`, như của `fx-lite`), và
- bản sao lưu đó vẫn còn trong danh sách và được đánh dấu `verified`.

Nếu không, lệnh deploy từ chối với `frozen`. Đường lui khi đó là khôi phục bản sao lưu đó, việc mà Ingat chưa làm được cho tới M2; trong lúc chờ, `ingat status lite-test` chỉ bạn tới `history`.

## 7. Việc chạy hằng đêm và hằng tuần

Tạo các việc này trong bộ lập lịch của máy bằng root, với đường dẫn đầy đủ của lệnh `ingat`, và gửi email khi một việc kết thúc với mã thoát khác 0. Trong DSM Task Scheduler, đánh dấu "send run details by email only when the script terminates abnormally".

| Khi nào | Lệnh |
|---|---|
| hằng ngày 01:30 | `/srv/ingat/bin/ingat scheduled backup lite-test` |
| hằng ngày 03:00 | chép `/srv/ingat-backups` sang nơi khác bằng công cụ của bạn (restic, borg, rsync; Hyper Backup trên NAS Synology) |
| Chủ nhật 05:00 | `/srv/ingat/bin/ingat scheduled verify lite-test --latest --restore-test` |
| mỗi giờ | `/srv/ingat/bin/ingat scheduled status` |

Trên NAS Synology, lệnh là `/volume1/ingat/bin/ingat` và thư mục sao lưu là `/volume1/ingat-backups`.

- `scheduled backup` in một dòng khi thành công, và xóa các bản sao lưu cũ theo các thiết lập giữ lại trong tệp bản cài của bạn (`keep_daily`, `keep_weekly`, `keep_monthly`).
- `scheduled status` im lặng (exit 0) chừng nào không có gì mới cần bạn chú ý. Nó chỉ in ra, và vì thế bộ lập lịch mới gửi email cho bạn, khi một vấn đề xuất hiện hoặc hết đi. Một vấn đề kéo dài nhiều ngày chỉ gửi email cho bạn một lần, không phải mỗi giờ.
- Nếu một việc bắt đầu khi việc khác còn đang chạy trên cùng bản cài, việc thứ hai dừng với exit 2 và bạn nhận được email. Hãy để các việc cách nhau đủ xa.
- Một việc chạy theo lịch không bao giờ làm được điều gì cần bạn gõ duyệt; nó từ chối.

## 8. Khi có sự cố

**Phiên SSH bị ngắt giữa một thao tác.** Không có gì dừng lại. Mọi thao tác (deploy, backup, verify, thử khôi phục, start, stop, restart, resume, abandon) chạy trong một bộ phận phụ riêng trên máy (container riêng của nó), không nằm trong cửa sổ SSH của bạn, nên nó chạy tiếp mà không cần bạn. Kết nối lại và chạy `ingat attach lite-test` để theo dõi tới cuối.

- Ngoại lệ là tác vụ trò chuyện với bạn trong terminal (`bootstrap-config`, `bootstrap-new-code`). Nó chạy từ cửa sổ của bạn, nên mất cửa sổ có thể để nó dang dở trong khi container của nó vẫn chạy. Sau khi bị ngắt, hãy chạy lệnh kế tiếp của bạn; nếu nó trả lời `task-running`, chạy đúng lệnh `docker stop` mà nó in ra, rồi `ingat status lite-test`.
- Khi bạn đang theo dõi một thao tác, Ctrl-C hỏi `[d]etach or [c]ancel?`. Detach chỉ ngừng theo dõi, không bao giờ dừng thao tác. Trong một tác vụ terminal, Ctrl-C yêu cầu tác vụ dừng.

**`status` hiện `attention: open-operation: operation <n> (<kind>) is interrupted` (hoặc `paused`), exit 5.** Một thao tác đã bắt đầu mà chưa xong: nó bị cắt ngang (interrupted) hoặc đang chờ bạn (paused). Bạn có hai lựa chọn, và dòng `next:` của `status` nêu lựa chọn đúng:

- `ingat resume lite-test` làm tiếp từ bước đầu tiên chưa xong;
- `ingat abandon lite-test` hoàn tác những gì hoàn tác được và đóng thao tác lại.

Nếu `ingat attach` thấy bộ phận phụ đã biến mất, nó kết thúc với exit 4 và cùng mã `open-operation`; khi đó hãy chạy `status`. Một lần chuẩn bị, sao lưu, kiểm tra hay thử khôi phục bị cắt ngang sẽ được lệnh kế tiếp mở một thao tác trên bản cài này (một lần sao lưu, một lần deploy, một lần start …) tự hoàn tác rồi đóng lại; trước đó `status` vẫn tiếp tục hiện nó. Nếu lần tự dọn đó không hoàn tác được hết, lệnh mới từ chối với `needs-review`: chạy `ingat status lite-test` và làm theo `next:` của nó.

**`task-running`.** Một chương trình phụ (container tác vụ) do thao tác khởi động vẫn đang chạy, và Ingat sẽ không đi tiếp cho tới khi nó dừng. Chép và chạy đúng lệnh `docker stop <container>` mà thông báo in ra, rồi `ingat resume lite-test` hoặc `ingat abandon lite-test` (`ingat status lite-test` nêu lệnh đúng).

**`failed-frozen`.** Bản cài đang tạm khóa: các phần ghi dữ liệu đã dừng để không gì bị hỏng. Đường đi tiếp là lệnh `deploy` mà kết quả đã in ra (cùng phiên bản, cùng các image đã chuẩn bị), theo các điều kiện ở mục 6. Khi đang tạm khóa, `backup`, `start`, `stop`, `restart` và các tác vụ thay đổi ứng dụng hoặc dữ liệu đều từ chối chạy; tác vụ chỉ đọc, `verify` và thử khôi phục vẫn chạy được.

**`uncertified`.** Hệ điều hành, kernel hoặc Docker đã thay đổi kể từ lần kiểm tra máy trước. Chạy `ingat selftest --host`.

**`changed-outside` hoặc `foreign`.** Có gì đó không phải Ingat (một người, một công cụ khác, hoặc các nút bấm của chính ứng dụng Docker) đã đổi, xóa hoặc thêm container, network hay volume trong project của bản cài này. Không bao giờ dùng các nút thao tác project của ứng dụng hãng (ví dụ "Clean" hay "Delete" trong Container Manager) lên một project của Ingat. Tự tay gỡ những gì bạn đã thêm; `ingat restart lite-test` đưa ứng dụng về đúng như Ingat đã ghi nhận. Nếu các image (tệp chương trình) của ứng dụng đã mất, `ingat prepare lite-test <current ref>` tải lại đúng những bản đó.

**`not a tested combination`.** Xem mục 1: ghim Docker ở một phiên bản đã kiểm thử, hoặc chờ một bản phát hành Ingat kiểm thử phiên bản mới.

**`… lock is busy: op …` hoặc `container ingat-exec-lite-test is still present`, exit 2.** Một lệnh khác vẫn đang làm việc trên bản cài này (hoặc, với `init` và `selftest --host`, trên máy này), và mỗi lúc chỉ một lệnh được làm. Chưa có gì thay đổi. `ingat attach lite-test` cho bạn theo dõi thao tác đang chạy; nếu không, chờ lệnh mà thông báo nêu tên chạy xong, rồi thử lại.

## 9. Ý nghĩa các mã thoát

Mỗi lệnh kết thúc bằng một con số, gọi là mã thoát. Bộ lập lịch và kết quả `--json` đều báo con số này, và nó cho bạn biết ngay lệnh đã kết thúc ra sao.

| Exit | Ý nghĩa |
|---|---|
| 0 | Xong. |
| 1 | Ingat từ chối và không thay đổi gì (ví dụ một giá trị sai hoặc vướng một quy tắc an toàn). Thông báo nói lý do. |
| 2 | Ingat không chạy được và không thay đổi gì (ví dụ không kết nối được Docker, một lệnh khác còn đang bận, hoặc không có terminal để gõ duyệt). |
| 3 | Lệnh dừng giữa chừng sau khi đã thay đổi một phần, nhưng để ứng dụng ở một trạng thái an toàn đã biết. `ingat status lite-test` cho biết việc cần làm tiếp. |
| 4 | Thao tác cần bạn chú ý: nó đang tạm dừng, bị cắt ngang, Ingat không biết được một bước đã kết thúc ra sao, hoặc việc dọn dẹp của nó chưa xong. Chạy `ingat status lite-test`. |
| 5 | Một lần kiểm tra phát hiện điều đáng xem; không có gì lỗi. |
| 130 | Bạn đã hủy trước khi có gì thay đổi. |

Thêm `--json` vào bất kỳ lệnh nào để nhận cùng câu trả lời dưới dạng một khối JSON cho máy đọc, tiện cho script.

## 10. Nâng cấp Ingat

Chạy lại `sh install.sh --version <new>` bằng root.

1. Trước hết nó tải phiên bản mới.
2. Nếu còn thao tác nào chưa xong, nó dừng lại và giữ nguyên phiên bản bạn đang có (exit 2).
3. Nếu không, nó chạy `ingat selftest --host` với phiên bản mới. Nếu kiểm tra này thất bại, bạn vẫn giữ phiên bản đang có (exit 3).
4. Nếu đạt, phiên bản mới trở thành lệnh `ingat`, và lệnh cũ được giữ ở `bin/ingat.prev`: đường quay lại của bạn nếu phiên bản mới gặp trục trặc.

## 11. Không bao giờ làm

- Không bao giờ chạy `docker compose down -v`, `docker system prune` hay `docker volume rm`, và không bao giờ dùng các nút thao tác project của ứng dụng hãng (như "Clean" hay "Delete"), lên một project của Ingat. Những thứ này có thể phá hủy container, image hay dữ liệu vĩnh viễn, và không gì lấy lại được. Ingat không ngăn được chúng; sau đó nó chỉ có thể báo rằng có thứ đã mất hoặc đã bị đổi.
- Không bao giờ sửa bất cứ thứ gì dưới `INGAT_ROOT` ngoài `instances/<i>/instance.toml`, các tệp bí mật bạn đặt ở M1, `inbox/` và `keys/`.
- Không bao giờ đặt `INGAT_ROOT` hay thư mục dữ liệu của một ứng dụng lên ổ mạng, thư mục đồng bộ, hoặc (trên NAS Synology) một shared folder.
- Không bao giờ chạy hai phiên bản Ingat trên một máy, hay tự tay chép các thư mục của Ingat sang máy khác (khôi phục trên máy khác sẽ có ở M4).
- Không bao giờ tìm `--force` hay `--yes`: không có. Cách duy nhất để vượt qua một lời từ chối là lệnh mà thông báo nêu tên.
