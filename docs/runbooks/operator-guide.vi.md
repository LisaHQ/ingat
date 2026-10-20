# Hướng dẫn vận hành Ingat (M1)

Trạng thái: bản dịch của [`operator-guide.md`](operator-guide.md), bản tiếng Anh là bản chuẩn. Mô tả bộ lệnh M1 như đang có trong mã ([`README.md`](../../README.md), mục "Commands (M1)"). Restore, duyệt class D, `secret set` và cơ chế `plan`/`apply` cho agent sẽ có ở M2 ([`ROADMAP.md`](../ROADMAP.md)); hướng dẫn nói rõ ở những chỗ liên quan. Lý do của từng quy tắc nằm trong [`LIFECYCLE.md`](../LIFECYCLE.md) và [`ARCHITECTURE.md`](../ARCHITECTURE.md); tài liệu này chỉ nói gõ gì và sẽ thấy gì.

Mọi lệnh chạy bằng tài khoản quản trị của máy (root) qua một script khởi động nhỏ (`/srv/ingat/bin/ingat` với các thư mục mặc định; `/volume1/ingat/bin/ingat` theo hồ sơ DSM, dùng trên NAS Synology). Dưới đây `ingat` là đường dẫn đó, và `lite-test` là một instance ví dụ (một bản cài của một app) của app mẫu `fx-lite`.

## 1. Trước khi bắt đầu

- **Host:** Docker Engine Linux 24.0 trở lên có plugin `docker compose`, truy cập được bằng root qua socket cục bộ; SSH với `sudo -i`; một bộ lập lịch gửi mail khi job lỗi (systemd timer, cron, hoặc DSM Task Scheduler); một công cụ sao chép backup ra ngoài host (restic, borg, rsync, hoặc Hyper Backup trên DSM). Chi tiết: [`ARCHITECTURE.md`](../ARCHITECTURE.md) §11.4.
- **Hai thư mục:** `INGAT_ROOT` giữ các bản ghi của tool và dữ liệu thật của những app lưu dữ liệu trong thư mục thường (mặc định `/srv/ingat`; phải thuộc root với quyền `0700`, tức chỉ root mở được, và nằm trên ổ đĩa trong máy này, không bao giờ là ổ mạng). `INGAT_BACKUPS` giữ các bản backup đã hoàn tất, mỗi bản được niêm phong bằng mã kiểm tra để mọi thay đổi về sau đều bị phát hiện (mặc định `/srv/ingat-backups`; chỉ root ghi vào đó, và đây là thư mục để bạn chép ra nơi khác). Trên DSM truyền `--root /volume1/ingat --backups /volume1/ingat-backups` lúc cài; không bao giờ dùng mặc định `/srv` ở đó.
- **Tool chỉ nhìn thấy hai thư mục này.** Nó chạy trong một hộp riêng (container) chỉ được cho thấy `INGAT_ROOT` và `INGAT_BACKUPS`, không thấy gì khác trên máy. Vì vậy mọi đường dẫn tệp bạn đưa cho nó (`init --config`, `validate <thư-mục-repo>`, `validate --instance`, file `--input` của task) phải là đường dẫn đầy đủ bắt đầu từ một trong hai thư mục đó, nếu không tool sẽ không tìm thấy tệp; `INGAT_ROOT/inbox/` là chỗ để các tệp và mã nguồn như vậy.
- **App của bạn:** cần `ingat.toml` trong repository và image build bởi CI ([`MANIFEST_SPEC.md`](../MANIFEST_SPEC.md); checklist onboarding trong [`ARCHITECTURE.md`](../ARCHITECTURE.md) §11.3). `ingat validate <thư-mục-repo>` kiểm tra một checkout offline (ví dụ một checkout dưới `INGAT_ROOT/inbox/`).
- **Phiên bản Docker đã kiểm thử:** lệnh có thay đổi chỉ chạy trên dòng phiên bản Docker Engine mà bản phát hành này của tool đã được kiểm thử cùng (danh sách nằm sẵn trong tool, tệp `tested.json`), và chỉ sau lần kiểm tra máy ở mục 2 (chạy lại sau mỗi lần cập nhật máy). Trên phiên bản Docker khác, `ingat status` báo `not a tested combination of this release`: bạn vẫn xem được trạng thái và vẫn backup được theo cách không dừng app, nhưng mọi lệnh có thay đổi app hay dữ liệu đều từ chối. Vì vậy đừng để Docker tự cập nhật: trên host Linux hãy ghim `docker-ce` (`apt-mark hold`), và chỉ lên Docker mới cùng với một bản phát hành tool đã được kiểm thử với nó.

## 2. Cài đặt và chứng nhận host (một lần)

Bằng root, với `install.sh` và `SHA256SUMS` của bản phát hành trong cùng thư mục:

```sh
sudo -i
sh install.sh --version 0.1.0          # root mặc định; thêm --root và --backups cho hồ sơ DSM
ingat host init                        # gắn root với engine này; gõ tên host để duyệt
sh facts.sh > facts.json               # thu thập thông tin host, chỉ đọc; giữ file cùng ghi chú của bạn
ingat selftest --host                  # chứng nhận bản build nền tảng này: in một dòng tóm tắt, rồi không in gì tới khi xong (vài phút)
ingat status                           # "gate tier 2" ở những dòng cuối nghĩa là máy này đã được duyệt cho các lệnh có thay đổi
```

Theo hồ sơ DSM hãy truyền thư mục gốc cho cả `facts.sh`: `sh facts.sh --root /volume1/ingat --backups /volume1/ingat-backups > facts.json`.

Bạn sẽ thấy: `install.sh` in các dòng tự kiểm tra offline và `installed version …`; `host init` in phiên bản Docker, storage driver và kernel, rồi hoặc `gate tier 2: this platform build is certified` (phần mềm của máy này đã được duyệt cho các lệnh có thay đổi) hoặc lý do chưa được; `selftest --host` in một dòng `PASS` cho mỗi kiểm tra và đường dẫn tệp chứng nhận nó đã ghi. Chạy lại `ingat selftest --host` sau mỗi lần cập nhật hệ điều hành, kernel hay Docker: chừng nào chưa chạy, `status` báo `uncertified` dưới `attention:` và thử restore theo lịch từ chối chạy (exit 2), còn backup hằng đêm vẫn chạy chừng nào app backup được mà không cần dừng (như `fx-lite`).

Cài offline: `sh install.sh --version 0.1.0 --from-tar ingat-0.1.0-amd64.tar` nạp tarball thay vì pull.

## 3. Đăng ký một instance

1. Viết file instance vào inbox, ví dụ `/srv/ingat/inbox/lite-test.toml` (schema và ví dụ đầy đủ: [`MANIFEST_SPEC.md`](../MANIFEST_SPEC.md) §6 và §12). Tối thiểu cho `fx-lite`:

   ```toml
   instance = 1
   name = "lite-test"
   app = "fx-lite"
   environment = "test"
   disposable = false

   [source]
   repo = "ssh://git@github.com/<owner>/<app>.git"
   key = "fx-lite"                      # /srv/ingat/keys/fx-lite/{id_ed25519,known_hosts}, mode 0600

   [params]
   FXLITE_IMAGE = "ghcr.io/<owner>/fx-lite@sha256:<digest>"   # image do CI build của bản phát hành; fx-lite bắt buộc có
   FXLITE_PORT = "20090"                # không khai báo khóa này thì port được cấp trong dải 20000-29999

   [app_env]
   ALLOWED_ORIGINS = "https://lite-test.example.internal"
   BASE_URL = "https://lite-test.example.internal"
   MAIL_SENDER = "lite-test@example.invalid"
   PROXY_ADDRESS = "127.0.0.1"

   [backups]
   keep_daily = 7
   keep_weekly = 4
   ```

2. Với repository `ssh://`, đặt deploy key chỉ đọc và `known_hosts` đã ghim dưới `INGAT_ROOT/keys/<key>/`.
3. Tùy chọn: `ingat validate /srv/ingat/inbox/<checkout> --instance /srv/ingat/inbox/lite-test.toml`.
4. `ingat init lite-test --config /srv/ingat/inbox/lite-test.toml --ref v1.2.0`, rồi gõ `lite-test` để duyệt. Lệnh tải mã nguồn của app ở phiên bản `v1.2.0`, đọc tệp `ingat.toml` của app trong đó, chọn cổng mạng nào bạn chưa khai báo, tự tạo các mật khẩu mà app cho phép tự sinh (bạn không bao giờ thấy hay gõ chúng; những mật khẩu bạn phải tự cung cấp nằm ở bước 5), và in `next: ingat deploy lite-test v1.2.0`.
5. Secret mà manifest khai báo dạng env-file (ví dụ thông tin đăng nhập mail) sẽ được đặt bằng `ingat secret set` từ M2. Ở M1, sau `init` (lệnh này tạo `secrets/env/` với mode 0700) và trước lần deploy đầu, đặt từng giá trị thành một file `INGAT_ROOT/instances/lite-test/secrets/env/<KEY>` (mode 0600, không có xuống dòng ở cuối); chạy lại `init` sau đó vẫn giữ nguyên file đã có.

Tên instance viết thường, tối đa 30 ký tự: bắt đầu bằng chữ, rồi chữ, số và gạch nối đơn, không ở đầu hay cuối. `ingat list` liệt kê các instance của host.

## 4. Deploy lần đầu

```sh
ingat deploy lite-test v1.2.0
```

Nếu phiên bản này chưa được chuẩn bị, lệnh sẽ chuẩn bị trước: tải image của app (các tệp chương trình đã đóng gói) và ghi lại chính xác bản đã tải. Phần này không thay đổi gì ở app đang chạy nên không cần duyệt. Sau đó lệnh in kế hoạch: mỗi bước một dòng có đánh số, kèm mức rủi ro của bước (lớp) và bước được đánh dấu `forward point`, tức là điểm mà sau đó tool không còn hoàn tác đơn giản được nữa. Lệnh yêu cầu bạn gõ tên instance (`lite-test`) để duyệt. Khi chạy, mỗi bước in hai dòng có giờ (`started`, rồi `done`, hoặc giai đoạn bị lỗi), và dòng cuối là `operation <kết cục>`. Ý nghĩa từng kết cục:

- `completed`, exit 0: instance đang chạy; `next: ingat status lite-test`.
- `paused`, exit 4: điểm dừng cài đặt của app. Thông điệp nói phải làm gì (với `fx-lite`: chép file bootstrap vào `INGAT_ROOT/inbox/`, chạy `ingat task lite-test bootstrap-config --input config=<file>`, hoàn tất thiết lập trên trình duyệt), rồi `ingat resume lite-test` và gõ tên lần nữa.
- `failed-unchanged`, exit 3: một bước bị lỗi nhưng chưa có gì thay đổi vĩnh viễn: tool đã dừng lại mọi thứ nó khởi động, app và dữ liệu của bạn vẫn như trước. Đọc thông điệp, sửa nguyên nhân được nêu, rồi chạy lại đúng lệnh đó.
- `failed-frozen`, exit 3: một bước bị lỗi sau khi app đã cập nhật dữ liệu (với `fx-lite`, lần cập nhật dữ liệu lúc cài chính là `forward point`). Tool giữ instance ở trạng thái tạm khóa ("đóng băng"): các writer, tức những phần của app có ghi vào dữ liệu, vẫn dừng để không gì bị hỏng. Dòng `next:` hiện lại chính lệnh `deploy` này; chạy lại sẽ tiếp tục từ dữ liệu mà lần cài đã tạo (mục 7).
- `needs-review`, exit 4: có bước bị lỗi và tool không tự hoàn tác hết được, nên cần bạn xem xét. Trước khi chạy gì khác, hãy đọc các cảnh báo trong kết quả và `ingat history lite-test`, lệnh liệt kê mọi thao tác đã qua và kết cục của từng thao tác.
- exit 130: hủy trước khi có tác động.

`ingat deploy` phải do người gõ trong cửa sổ terminal, vì lệnh sẽ hỏi bạn gõ tên instance. Nếu một job theo lịch hoặc một script chạy nó, tool từ chối (exit 2) trước khi thay đổi hay tải bất cứ thứ gì.

## 5. Vận hành hằng ngày

| Việc | Lệnh | Ghi chú |
|---|---|---|
| Xem trạng thái | `ingat status lite-test` | Mỗi dòng bắt đầu bằng `attention:` là một việc cần bạn xem; khi đó lệnh kết thúc với mã thoát 5. Dòng cuối `next:` là lệnh cần chạy. `ingat status` không có tên thì hiện mọi instance trên máy này |
| Kiểm tra sâu | `ingat doctor lite-test` | policy, gate, secret, trùng port, thư mục gốc |
| Container, log, lịch sử, backup | `ingat ps lite-test`, `ingat logs lite-test app --since 1h`, `ingat history lite-test`, `ingat bundles lite-test` | chỉ đọc, không ghi gì |
| Backup thủ công | `ingat backup lite-test --reason "trước khi đổi mail"` | Không cần duyệt. Trong lúc chạy, những phần của app có ghi dữ liệu sẽ dừng lại, trừ khi app backup được mọi kho dữ liệu ngay khi đang chạy (như `fx-lite`) |
| Kiểm tra một bản backup | `ingat verify lite-test --latest` | Kiểm tra bản backup vẫn nguyên vẹn như lúc ghi (không thiếu, không hỏng tệp nào) và chạy các bước kiểm tra riêng của app trên bản đó |
| Thử restore | `ingat verify lite-test --latest --restore-test` | Chứng minh bản backup thật sự khôi phục được: restore vào một bản sao tạm, tách riêng, không chạm được dữ liệu thật, kiểm tra rồi xóa bản sao đó. App đang chạy không bị ảnh hưởng. Bản backup sau đó được đánh dấu `restore-tested` |
| Dọn bản backup cũ | `ingat prune lite-test --bundles`, rồi thêm `--apply` | Lệnh đầu chỉ liệt kê những bản cũ sẽ bị xóa theo các thiết lập giữ lại trong file instance (`keep_daily`, `keep_weekly`, `keep_monthly`); chưa xóa gì cho tới khi bạn thêm `--apply`. `scheduled backup` hằng đêm tự làm việc dọn này |
| Dừng, chạy, khởi động lại | `ingat stop lite-test`, `ingat start lite-test`, `ingat restart lite-test` | class C: gõ tên mỗi lần |
| Chạy một task do app cung cấp | `ingat task lite-test queue-status`, `… --arg job=<id>`, `… --input config=<file>` | Task chỉ đọc thì chạy không cần duyệt. Task có thay đổi app hoặc dữ liệu thì yêu cầu bạn gõ tên instance; mọi task `queue-*` và `bootstrap-*` của `fx-lite` đều thuộc loại này và từ chối chạy khi instance đang tạm khóa (đóng băng). Đặt tệp đầu vào trong `INGAT_ROOT/inbox/`. Task tương tác với bạn trong terminal thì chỉ hiện kết quả cho bạn, không lưu lại gì. Nếu một task có thay đổi app kết thúc theo cách app chưa khai báo (không phải mã `ok`, cũng không phải một lỗi đã khai báo), tool không biết task đã làm gì và báo `needs-review` (exit 4): hãy xem kết quả trước khi chạy gì khác |
| Cập nhật | `ingat deploy lite-test v1.3.0` | xem bên dưới |

**Cập nhật.** Nếu phiên bản mới chỉ đổi thiết lập, tool chỉ thay mới những phần của app có thiết lập thay đổi và khởi động chúng với thiết lập mới. Nếu nó đổi chương trình của một phần có ghi dữ liệu, hoặc bất kỳ phần nào của một app tự cập nhật dữ liệu mỗi lần khởi động, thì lần cập nhật này chạm vào dữ liệu, và kế hoạch hiện các bước an toàn: `Stop` các writer (những phần của app có ghi dữ liệu), tạo bản backup `pre-change`, kiểm tra bản đó, chạy bước cập nhật dữ liệu của app (`migrate`, đánh dấu `forward point`: sau bước này tool không còn quay lại đơn giản được), rồi chuyển app sang phiên bản mới. Từ bước `Stop` tới lúc chuyển xong, app không nhận thay đổi, nên hãy chọn giờ vắng để cập nhật. Nếu một bước sau `forward point` bị lỗi, thao tác kết thúc `failed-frozen` (exit 3): app bị tạm khóa với các writer đang dừng, và dòng `next:` hiện lại chính lệnh `deploy` đó. Chạy lại sẽ tiếp tục từ bản backup `pre-change` đã kiểm tra, với điều kiện bước cập nhật dữ liệu của app chạy hai lần vẫn an toàn (manifest khai báo `idempotent`, như của `fx-lite`) và bản backup đó vẫn còn trong danh sách và được đánh dấu `verified`. Nếu không, deploy từ chối với `frozen`; đường lùi khi đó là restore bản backup đó, việc tool này chưa làm được cho tới M2 (trong lúc chờ, `ingat status lite-test` chỉ bạn tới `history`).

## 6. Job theo lịch

Tạo các job này trong bộ lập lịch của host bằng root, theo đường dẫn tuyệt đối của wrapper, gửi mail khi exit khác 0 (DSM Task Scheduler: "send run details by email only when the script terminates abnormally"):

| Khi nào | Lệnh |
|---|---|
| hằng ngày 01:30 | `/srv/ingat/bin/ingat scheduled backup lite-test` |
| hằng ngày 03:00 | sao chép `/srv/ingat-backups` ra ngoài host bằng công cụ của bạn (restic, borg, rsync; Hyper Backup trên DSM) |
| Chủ nhật 05:00 | `/srv/ingat/bin/ingat scheduled verify lite-test --latest --restore-test` |
| mỗi giờ | `/srv/ingat/bin/ingat scheduled status` |

`scheduled backup` in một dòng khi thành công và dọn các bản backup cũ theo các thiết lập giữ lại trong file instance (`keep_daily`, `keep_weekly`, `keep_monthly`). `scheduled status` im lặng (exit 0) chừng nào không có gì mới cần bạn chú ý; nó chỉ in và gửi mail khi một vấn đề xuất hiện hoặc hết, nên một vấn đề kéo dài nhiều ngày chỉ gửi mail một lần chứ không phải mỗi giờ. Nếu một job bắt đầu khi job khác còn đang chạy trên cùng instance, job thứ hai dừng với exit 2 và bạn nhận được mail: hãy đặt các job cách nhau đủ xa. Job theo lịch không bao giờ làm được việc cần bạn gõ duyệt; nó sẽ từ chối.

## 7. Khi có sự cố

- **Mất kết nối SSH giữa chừng.** Không có gì dừng lại. Mọi thao tác (deploy, backup, verify, thử restore, start, stop, restart, resume, abandon) chạy trong một bộ phận phụ riêng trên máy (một container riêng), không nằm trong cửa sổ SSH của bạn, nên vẫn chạy tiếp khi bạn mất kết nối. Kết nối lại và chạy `ingat attach lite-test` để theo dõi tới cuối. Ngoại lệ là task tương tác với bạn trong terminal (`bootstrap-config`, `bootstrap-new-code`): nó chạy từ cửa sổ của bạn, nên mất cửa sổ có thể để nó dang dở trong khi container của nó vẫn chạy. Sau khi mất kết nối, chạy lệnh kế tiếp; nếu lệnh trả lời `task-running`, chạy đúng lệnh `docker stop` nó in ra, rồi `ingat status lite-test`. Khi đang theo dõi một thao tác, Ctrl-C hỏi `[d]etach or [c]ancel?`: detach chỉ ngừng theo dõi, không bao giờ dừng thao tác; trong task terminal, Ctrl-C là yêu cầu dừng task.
- **`status` hiện `attention: open-operation: operation <n> (<kind>) is interrupted` (hoặc `paused`), exit 5.** Một thao tác đã bắt đầu mà chưa xong: nó bị cắt ngang (interrupted) hoặc đang chờ bạn (paused). Bạn có hai lựa chọn, và dòng `next:` của `status` nêu lựa chọn đúng: `ingat resume lite-test` tiếp tục từ bước đầu tiên chưa xong; `ingat abandon lite-test` hoàn tác những gì có thể và đóng thao tác. (Nếu `ingat attach` thấy bộ phận phụ đã biến mất, nó kết thúc với exit 4 và cùng mã `open-operation`; khi đó `status` là lệnh cần chạy.) Một lần chuẩn bị, backup, kiểm tra hay thử restore bị cắt ngang sẽ được lệnh kế tiếp mở thao tác trên instance này (backup, deploy, start …) tự hoàn tác rồi đóng lại; trước đó `status` vẫn hiện nó. Nếu lần tự dọn đó không hoàn tác được hết, lệnh mới từ chối với `needs-review`: chạy `ingat status lite-test` và làm theo `next:`.
- **`task-running`.** Một chương trình phụ (container task) do thao tác khởi động vẫn đang chạy, và tool sẽ không đi tiếp cho tới khi nó dừng. Chép và chạy đúng lệnh `docker stop <container>` mà thông điệp in ra, rồi `ingat resume lite-test` hoặc `ingat abandon lite-test` (`ingat status lite-test` nêu lệnh đúng).
- **`failed-frozen`.** Instance đang tạm khóa: những phần của app có ghi dữ liệu đã dừng để không gì bị hỏng. Đường tiến là lệnh `deploy` mà kết quả đã in (cùng phiên bản, cùng bộ image đã chuẩn bị), theo điều kiện ở mục 5. Khi đang tạm khóa, `backup`, `start`, `stop`, `restart` và các task có thay đổi app hoặc dữ liệu từ chối chạy; task chỉ đọc, `verify` và thử restore vẫn chạy được.
- **`uncertified`.** OS, kernel hoặc Engine đã đổi từ lần chứng nhận trước: `ingat selftest --host`.
- **`changed-outside` hoặc `foreign`.** Có gì đó không phải Ingat (một người, một công cụ khác, hoặc các nút bấm của ứng dụng Docker) đã đổi, xóa hoặc thêm container, network, volume thuộc instance này. Không bao giờ dùng các nút thao tác project của ứng dụng hãng (ví dụ "Clean" hay "Delete" của Container Manager) lên project của Ingat. Tự gỡ bằng tay những gì bạn đã thêm; `ingat restart lite-test` đưa app về đúng như tool đã ghi nhận. Nếu image (tệp chương trình) của app đã mất, `ingat prepare lite-test <ref hiện tại>` tải lại đúng những bản đó.
- **`not a tested combination`.** Xem mục 1: ghim Engine, hoặc chờ bản phát hành tool kiểm thử dòng mới.
- **`… lock is busy: op …` hoặc `container ingat-exec-lite-test is still present`, exit 2.** Một lệnh khác vẫn đang làm việc trên instance này (hoặc, với `init` và `selftest --host`, trên máy này), và mỗi lúc chỉ một lệnh được làm. Chưa có gì thay đổi. `ingat attach lite-test` cho bạn theo dõi thao tác đang chạy; nếu không, chờ lệnh mà thông điệp nêu tên chạy xong rồi thử lại.

Mỗi lệnh kết thúc bằng một con số gọi là mã thoát; bộ lập lịch và kết quả `--json` đều báo số này, và nó cho bạn biết ngay lệnh đã kết thúc thế nào. 0: xong. 1: tool từ chối và không thay đổi gì (ví dụ giá trị sai hoặc vướng một quy tắc an toàn); thông điệp nói lý do. 2: tool không chạy được và không thay đổi gì (ví dụ không kết nối được Docker, một lệnh khác còn đang bận, hoặc không có cửa sổ terminal để gõ duyệt). 3: lệnh dừng giữa chừng sau khi đã thay đổi một phần, nhưng app vẫn ở một trạng thái an toàn đã biết; `ingat status lite-test` cho biết việc cần làm tiếp. 4: thao tác cần bạn xem xét (đang tạm dừng, bị gián đoạn, tool không xác định được một bước đã kết thúc thế nào, hoặc việc dọn dẹp chưa xong); chạy `ingat status lite-test`. 5: một lần kiểm tra phát hiện điều đáng xem; không có gì lỗi. 130: bạn đã hủy trước khi có gì thay đổi. Thêm `--json` vào bất kỳ lệnh nào để nhận cùng câu trả lời dưới dạng một khối JSON cho máy đọc (hữu ích cho script).

## 8. Nâng cấp tool

Chạy lại `sh install.sh --version <mới>` bằng root. Lệnh tải phiên bản mới trước. Nếu còn thao tác nào chưa xong, lệnh dừng lại và giữ nguyên phiên bản bạn đang dùng (exit 2). Nếu không, nó chạy `ingat selftest --host` với phiên bản mới; nếu kiểm tra này thất bại, bạn vẫn giữ phiên bản đang dùng (exit 3). Nếu đạt, phiên bản mới trở thành lệnh `ingat` và script khởi động cũ được giữ ở `bin/ingat.prev`, là đường quay lại nếu phiên bản mới gặp trục trặc.

## 9. Không bao giờ làm

- `docker compose down -v`, `docker system prune`, `docker volume rm`, hoặc các nút thao tác project của ứng dụng hãng (như "Clean" hay "Delete") lên project của Ingat: những thứ này có thể phá hủy container, image hay dữ liệu vĩnh viễn, không gì lấy lại được. Ingat không ngăn được; sau đó nó chỉ có thể báo là có thứ đã mất hoặc đã bị đổi.
- Sửa bất cứ thứ gì dưới `INGAT_ROOT` ngoài `instances/<i>/instance.toml`, các file secret bạn đặt ở M1, `inbox/` và `keys/`.
- Đặt `INGAT_ROOT` hay store kiểu bind lên ổ mạng, thư mục đồng bộ, hoặc (trên DSM) shared folder.
- Chạy hai phiên bản tool trên một host, hoặc tự chép thư mục gốc sang host khác (restore liên host sẽ có ở M4).
- Tìm `--force` hay `--yes`: không có. Cách duy nhất để vượt một lời từ chối là lệnh mà thông điệp nêu tên.
