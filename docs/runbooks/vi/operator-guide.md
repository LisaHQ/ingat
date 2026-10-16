# Hướng dẫn vận hành Ingat (M1)

Trạng thái: bản dịch của [`../operator-guide.md`](../operator-guide.md), bản tiếng Anh là bản chuẩn. Mô tả bộ lệnh M1 như đang có trong mã ([`README.md`](../../../README.md), mục "Commands (M1)"). Restore, duyệt class D, `secret set` và cơ chế `plan`/`apply` cho agent sẽ có ở M2 ([`ROADMAP.md`](../../ROADMAP.md)); hướng dẫn nói rõ ở những chỗ liên quan. Lý do của từng quy tắc nằm trong [`LIFECYCLE.md`](../../LIFECYCLE.md) và [`ARCHITECTURE.md`](../../ARCHITECTURE.md); tài liệu này chỉ nói gõ gì và sẽ thấy gì.

Mọi lệnh chạy bằng root qua wrapper (`/srv/ingat/bin/ingat` với root mặc định; `/volume1/ingat/bin/ingat` theo hồ sơ DSM). Dưới đây `ingat` là đường dẫn đó, và `lite-test` là một instance ví dụ của app fixture `fx-lite`.

## 1. Trước khi bắt đầu

- **Host:** Docker Engine Linux 24.0 trở lên có plugin `docker compose`, truy cập được bằng root qua socket cục bộ; SSH với `sudo -i`; một bộ lập lịch gửi mail khi job lỗi (systemd timer, cron, hoặc DSM Task Scheduler); một công cụ sao chép backup ra ngoài host (restic, borg, rsync, hoặc Hyper Backup trên DSM). Chi tiết: [`ARCHITECTURE.md`](../../ARCHITECTURE.md) §11.4.
- **Hai thư mục:** `INGAT_ROOT` giữ trạng thái của tool và dữ liệu sống của các store kiểu bind (mặc định `/srv/ingat`; phải là `root:root 0700`, trên filesystem cục bộ, không bao giờ là ổ mạng). `INGAT_BACKUPS` giữ các bundle backup đã niêm phong (mặc định `/srv/ingat-backups`, chỉ root ghi, là nguồn cho bản sao ra ngoài host). Trên DSM truyền `--root /volume1/ingat --backups /volume1/ingat-backups` lúc cài; không bao giờ dùng mặc định `/srv` ở đó.
- **Tool chỉ nhìn thấy hai thư mục này.** CLI chạy trong một container chỉ mount `INGAT_ROOT` và `INGAT_BACKUPS`, không mount gì khác của host. Mọi đường dẫn bạn đưa cho nó (`init --config`, `validate <thư-mục-repo>`, `validate --instance`, file `--input` của task) phải là đường dẫn tuyệt đối nằm dưới một trong hai thư mục đó; `INGAT_ROOT/inbox/` là chỗ để các file và checkout như vậy.
- **App của bạn:** cần `ingat.toml` trong repository và image build bởi CI ([`MANIFEST_SPEC.md`](../../MANIFEST_SPEC.md); checklist onboarding trong [`ARCHITECTURE.md`](../../ARCHITECTURE.md) §11.3). `ingat validate <thư-mục-repo>` kiểm tra một checkout offline (ví dụ một checkout dưới `INGAT_ROOT/inbox/`).
- **Dòng Engine đã kiểm thử:** lệnh thay đổi trạng thái chỉ chạy trên dòng Engine mà bản phát hành đã kiểm thử (`tested.json` trong image) và chỉ sau khi host được chứng nhận. Trên dòng Engine khác, `ingat status` báo `not a tested combination of this release`: lệnh chỉ đọc và backup online vẫn chạy. Trên host Linux hãy ghim `docker-ce` (`apt-mark hold`) và chỉ chuyển dòng mới khi có bản phát hành tool kiểm thử dòng đó.

## 2. Cài đặt và chứng nhận host (một lần)

Bằng root, với `install.sh` và `SHA256SUMS` của bản phát hành trong cùng thư mục:

```sh
sudo -i
sh install.sh --version 0.1.0          # root mặc định; thêm --root và --backups cho hồ sơ DSM
ingat host init                        # gắn root với engine này; gõ tên host để duyệt
sh facts.sh > facts.json               # thu thập thông tin host, chỉ đọc; giữ file cùng ghi chú của bạn
ingat selftest --host                  # chứng nhận bản build nền tảng này: in một dòng tóm tắt, rồi không in gì tới khi xong (vài phút)
ingat status                           # "gate tier 2" ở những dòng cuối nghĩa là lệnh thay đổi trạng thái được phép chạy
```

Theo hồ sơ DSM hãy truyền thư mục gốc cho cả `facts.sh`: `sh facts.sh --root /volume1/ingat --backups /volume1/ingat-backups > facts.json`.

Bạn sẽ thấy: `install.sh` in các dòng selftest offline và `installed version …`; `host init` in engine, storage driver và kernel, rồi hoặc `gate tier 2: this platform build is certified` hoặc lý do chưa được; `selftest --host` in một dòng `PASS` cho mỗi kiểm tra và đường dẫn file chứng nhận. Chạy lại `ingat selftest --host` sau mỗi lần cập nhật OS, kernel hay Engine: trước đó `status` báo `uncertified` và drill theo lịch bị từ chối (exit 2) trong khi backup online hằng đêm vẫn chạy.

Cài offline: `sh install.sh --version 0.1.0 --from-tar ingat-0.1.0-amd64.tar` nạp tarball thay vì pull.

## 3. Đăng ký một instance

1. Viết file instance vào inbox, ví dụ `/srv/ingat/inbox/lite-test.toml` (schema và ví dụ đầy đủ: [`MANIFEST_SPEC.md`](../../MANIFEST_SPEC.md) §6 và §12). Tối thiểu cho `fx-lite`:

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
4. `ingat init lite-test --config /srv/ingat/inbox/lite-test.toml --ref v1.2.0`, rồi gõ `lite-test` để duyệt. Lệnh fetch mã nguồn, đọc manifest tại ref đó, cấp port, sinh các secret đã khai báo và in `next: ingat deploy lite-test v1.2.0`.
5. Secret mà manifest khai báo dạng env-file (ví dụ thông tin đăng nhập mail) sẽ được đặt bằng `ingat secret set` từ M2. Ở M1, sau `init` (lệnh này tạo `secrets/env/` với mode 0700) và trước lần deploy đầu, đặt từng giá trị thành một file `INGAT_ROOT/instances/lite-test/secrets/env/<KEY>` (mode 0600, không có xuống dòng ở cuối); chạy lại `init` sau đó vẫn giữ nguyên file đã có.

Tên instance viết thường, tối đa 30 ký tự: bắt đầu bằng chữ, rồi chữ, số và gạch nối đơn, không ở đầu hay cuối. `ingat list` liệt kê các instance của host.

## 4. Deploy lần đầu

```sh
ingat deploy lite-test v1.2.0
```

Nếu chưa có candidate, lệnh tự prepare trước (pull và ghim image: class B, không cần duyệt), rồi in kế hoạch deploy, mỗi bước một dòng có đánh số kèm lớp và điểm không quay lui, và yêu cầu gõ tên instance. Sau đó in hai dòng có thời gian cho mỗi bước (`started`, rồi `done` hoặc pha lỗi) và một dòng `operation <kết cục>` cuối cùng. Các kết cục:

- `completed`, exit 0: instance đang chạy; `next: ingat status lite-test`.
- `paused`, exit 4: điểm dừng cài đặt của app. Thông điệp nói phải làm gì (với `fx-lite`: chép file bootstrap vào `INGAT_ROOT/inbox/`, chạy `ingat task lite-test bootstrap-config --input config=<file>`, hoàn tất thiết lập trên trình duyệt), rồi `ingat resume lite-test` và gõ tên lần nữa.
- `failed-unchanged`, exit 3: một bước lỗi trước khi có thay đổi vĩnh viễn; những gì đã khởi động đều được dừng lại. Đọc thông điệp, sửa nguyên nhân, chạy lại đúng lệnh đó.
- `failed-frozen`, exit 3: một bước sau migrate của app bị lỗi (với `fx-lite`, migrate lúc cài là điểm không quay lui). Instance bị đóng băng với writer đang dừng và `next` chính là lệnh `deploy` này, chạy tiếp trên generation mà lần cài đã tạo (mục 7).
- `needs-review`, exit 4: việc hoàn tác sau một lỗi không hoàn tất. Đọc `ingat history lite-test` và các cảnh báo trong kết quả trước khi làm gì khác.
- exit 130: hủy trước khi có tác động.

`ingat deploy` cần terminal: job không có terminal bị từ chối với exit 2 trước khi prepare bất cứ thứ gì.

## 5. Vận hành hằng ngày

| Việc | Lệnh | Ghi chú |
|---|---|---|
| Xem trạng thái | `ingat status lite-test` | exit 5 nghĩa là cần chú ý; dòng cuối `next:` nêu lệnh cần chạy. `ingat status` không có tên thì xem mọi instance |
| Kiểm tra sâu | `ingat doctor lite-test` | policy, gate, secret, trùng port, thư mục gốc |
| Container, log, lịch sử, backup | `ingat ps lite-test`, `ingat logs lite-test app --since 1h`, `ingat history lite-test`, `ingat bundles lite-test` | chỉ đọc, không ghi gì |
| Backup thủ công | `ingat backup lite-test --reason "trước khi đổi mail"` | class B, không cần duyệt; dừng writer trừ khi mọi store backup được online |
| Verify một bundle | `ingat verify lite-test --latest` | tính lại hash và chạy task verify của app |
| Diễn tập restore | `ingat verify lite-test --latest --restore-test` | restore bundle vào một bản sao cô lập dùng xong bỏ, kiểm tra, dọn; đánh dấu bundle `restore-tested` |
| Dọn theo retention | `ingat prune lite-test --bundles`, rồi thêm `--apply` | chạy thử trước; `scheduled backup` tự áp dụng retention |
| Dừng, chạy, khởi động lại | `ingat stop lite-test`, `ingat start lite-test`, `ingat restart lite-test` | class C: gõ tên mỗi lần |
| Task app đã khai báo | `ingat task lite-test queue-status`, `… --arg job=<id>`, `… --input config=<file>` | class B với task `read`, class C (gõ tên) với task `app-write` hoặc `data`: mọi task `queue-*` và `bootstrap-*` của `fx-lite` đều là class C và từ chối khi instance đang đóng băng. File đầu vào nằm trong `INGAT_ROOT/inbox/`; task in ra terminal thì không bao giờ được ghi lại; task `app-write` thoát với mã không phải `ok` đã khai báo thì đóng `needs-review` (exit 4) |
| Cập nhật | `ingat deploy lite-test v1.3.0` | xem bên dưới |

**Cập nhật.** Deploy chỉ đổi cấu hình thì tạo lại đúng những service thay đổi. Deploy đổi image của một writer, hoặc bất kỳ image nào của app migrate khi khởi động, là deploy thay đổi dữ liệu: kế hoạch hiện `Stop` các writer, một bundle `pre-change`, bước verify nó, task `migrate` được đánh dấu `forward point`, rồi activation. Writer bị dừng từ bước `Stop` cho đến khi activation mở ghi trở lại; hãy tính trước khoảng downtime. Nếu một bước sau điểm không quay lui lỗi, thao tác kết thúc `failed-frozen` (exit 3) và in lại chính lệnh `deploy` đó ở `next`. Chạy lại sẽ tiếp tục từ bundle pre-change đã verify khi task migrate của app được khai báo `idempotent` (như của `fx-lite`) và bundle đó vẫn còn trong catalog và `verified`; nếu không, deploy từ chối `frozen`, và đường lùi là restore bundle đó, sẽ có ở M2 (`ingat status lite-test` khi đó nêu `history`).

## 6. Job theo lịch

Tạo các job này trong bộ lập lịch của host bằng root, theo đường dẫn tuyệt đối của wrapper, gửi mail khi exit khác 0 (DSM Task Scheduler: "send run details by email only when the script terminates abnormally"):

| Khi nào | Lệnh |
|---|---|
| hằng ngày 01:30 | `/srv/ingat/bin/ingat scheduled backup lite-test` |
| hằng ngày 03:00 | sao chép `/srv/ingat-backups` ra ngoài host bằng công cụ của bạn (restic, borg, rsync; Hyper Backup trên DSM) |
| Chủ nhật 05:00 | `/srv/ingat/bin/ingat scheduled verify lite-test --latest --restore-test` |
| mỗi giờ | `/srv/ingat/bin/ingat scheduled status` |

`scheduled backup` in một dòng khi thành công và áp dụng retention; `scheduled status` không in gì và exit 0 trừ khi tập cảnh báo thay đổi so với lần chạy trước, nên một tình trạng kéo dài chỉ gửi mail một lần. Lock đang bận thì exit 2 và được gửi mail: đặt giờ các job cách xa nhau. `scheduled` từ chối mọi thứ cần duyệt bằng cách gõ tên.

## 7. Khi có sự cố

- **Mất SSH giữa chừng.** Với mọi thao tác chạy qua executor (deploy, backup, verify, drill, start, stop, restart, resume, abandon) không có gì dừng lại: nó chạy trong một executor tách rời. Kết nối lại và chạy `ingat attach lite-test` để theo dõi tới cuối. Task terminal (`bootstrap-config`, `bootstrap-new-code`) chạy ngay trong CLI: sau khi mất kết nối, chạy lệnh kế tiếp và nếu nó in `task-running` thì chạy đúng lệnh `docker stop` được nêu, rồi `ingat status lite-test`. Ctrl-C khi đang theo dõi một thao tác sẽ hỏi `[d]etach or [c]ancel?`, và detach không bao giờ dừng thao tác; trong task terminal, Ctrl-C là yêu cầu hủy.
- **`status` hiện `attention: open-operation: operation <n> (<kind>) is interrupted` (hoặc `paused`), exit 5.** `ingat resume lite-test` tiếp tục từ bước chưa xong đầu tiên; `ingat abandon lite-test` hoàn tác những gì có thể và đóng thao tác. `status` nêu lệnh đúng ở `next`. (Follower thấy executor đã biến mất thì exit 4 với cùng mã; khi đó `status` là lệnh kế tiếp.) Một `prepare`, `backup`, `verify` hay drill bị gián đoạn sẽ được tự abandon bởi lệnh kế tiếp mở một thao tác trên instance (backup, deploy, start …); trước đó `status` vẫn hiện nó. Nếu lần tự abandon đó không hoàn tác được hết, lệnh mới từ chối `needs-review`: chạy `ingat status lite-test` và làm theo `next`.
- **`task-running`.** Một container task của thao tác vẫn còn sống. Chạy đúng lệnh `docker stop <container>` mà thông điệp in ra, rồi `resume` hoặc `abandon`.
- **`failed-frozen`.** Instance bị đóng băng với writer đang dừng. Đường tiến là lệnh `deploy` mà kết quả đã in (cùng ref, cùng candidate), theo điều kiện ở mục 5; `backup`, `start`, `stop`, `restart` và task ghi từ chối khi đang đóng băng, còn task đọc, `verify` và drill vẫn chạy.
- **`uncertified`.** OS, kernel hoặc Engine đã đổi từ lần chứng nhận trước: `ingat selftest --host`.
- **`changed-outside` hoặc `foreign`.** Có gì đó ngoài Ingat đã đổi hoặc thêm container, network, volume của project. Không bao giờ dùng thao tác project của GUI hãng (Container Manager "Clean" hay "Delete") lên project của Ingat. Tự gỡ những gì bạn thêm bằng tay; `ingat restart lite-test` đưa deployment đã ghi trở lại. Nếu image đã mất, `ingat prepare lite-test <ref hiện tại>` pull lại theo digest đã ghi.
- **`not a tested combination`.** Xem mục 1: ghim Engine, hoặc chờ bản phát hành tool kiểm thử dòng mới.
- **`… lock is busy: op …` hoặc `container ingat-exec-lite-test is still present`, exit 2.** Một lệnh khác đang giữ instance, hoặc giữ host lock với `init` và `selftest --host`; `ingat attach lite-test` theo dõi một thao tác của instance, còn lại thì chờ bên giữ mà thông điệp nêu tên.

Mã thoát: 0 hoàn tất, 1 bị từ chối (không thay đổi gì), 2 không chạy được (không thay đổi gì), 3 lỗi sau khi đã có tác động (ở trạng thái an toàn đã ghi), 4 cần chú ý (paused, interrupted, unknown, needs review), 5 có phát hiện, 130 hủy trước khi có tác động. Mọi lệnh đều nhận thêm `--json` để trả một đối tượng JSON thay cho các dòng chữ.

## 8. Nâng cấp tool

Chạy lại `sh install.sh --version <mới>` bằng root. Lệnh từ chối khi có thao tác đang mở (exit 2), chạy `ingat selftest --host` với image mới và giữ wrapper hiện tại nếu thất bại (exit 3); nếu đạt, thay wrapper và giữ bản cũ ở `bin/ingat.prev`, là đường quay lại.

## 9. Không bao giờ làm

- `docker compose down -v`, `docker system prune`, `docker volume rm`, hoặc thao tác project của GUI hãng lên project của Ingat: Ingat không ngăn được và chỉ có thể báo thiệt hại.
- Sửa bất cứ thứ gì dưới `INGAT_ROOT` ngoài `instances/<i>/instance.toml`, các file secret bạn đặt ở M1, `inbox/` và `keys/`.
- Đặt `INGAT_ROOT` hay store kiểu bind lên ổ mạng, thư mục đồng bộ, hoặc (trên DSM) shared folder.
- Chạy hai phiên bản tool trên một host, hoặc tự chép thư mục gốc sang host khác (restore liên host sẽ có ở M4).
- Tìm `--force` hay `--yes`: không có. Cách duy nhất để vượt một lời từ chối là lệnh mà thông điệp nêu tên.
