# Vòng đời của Ingat: các thao tác, sơ đồ trạng thái, quy tắc an toàn bắt buộc, dữ liệu

[English](LIFECYCLE.md) · **Tiếng Việt** (bản dịch; bản tiếng Anh là bản chuẩn)

> **Nói đơn giản.** Tài liệu này nói chính xác Ingat làm gì khi chạy một lệnh: những quy tắc an toàn mà không gì tắt được, ai phải duyệt việc gì, một thao tác đi qua từng bước và phục hồi sau khi bị ngắt ra sao, mọi thao tác theo thứ tự, cách xử lý dữ liệu và bản sao lưu, ý nghĩa của từng mã thoát, và những việc nên chạy theo lịch. Đây là bản đặc tả bắt buộc phải theo. Để dùng hằng ngày, [hướng dẫn vận hành](runbooks/operator-guide.vi.md) ngắn gọn hơn.

**Tìm gì ở đâu**

| Mục | Nói đơn giản |
|---|---|
| [§1 Quy tắc an toàn bắt buộc](#1-quy-tắc-an-toàn-bắt-buộc) | 17 quy tắc (F1-F17) mà mã nguồn bắt buộc thực hiện và không cài đặt nào tắt được |
| [§2 Lớp duyệt và các lệnh](#2-lớp-duyệt-và-các-lệnh) | Lệnh nào không cần duyệt, lệnh nào cần gõ tên bản cài, lệnh nào cần gõ mã thử thách trên một terminal thật; mọi lệnh kèm mốc (milestone) của nó |
| [§3 Mô hình thao tác](#3-mô-hình-thao-tác) | Một lệnh được lập kế hoạch, được duyệt và chạy từng bước ra sao; điều gì xảy ra sau khi bị ngắt hoặc khi không rõ kết quả; các trạng thái mà một ứng dụng có thể ở |
| [§4 Các thao tác](#4-các-thao-tác) | Từng lệnh, từng bước: đăng ký, chuẩn bị, cài đặt, cập nhật, quay về bản cũ, sao lưu, kiểm tra, thử khôi phục, khôi phục, khởi động và dừng, tác vụ, dọn dẹp, gỡ bỏ hoàn toàn, chẩn đoán, tiếp quản |
| [§5 Dữ liệu](#5-dữ-liệu) | Các cách sao lưu, vùng dữ liệu (generation), định dạng và tên bản sao lưu, các mức kiểm tra, quy tắc giữ lại, tác động ra bên ngoài và chốt chặn, dung lượng đĩa, bản sao ở nơi khác |
| [§6 Mã thoát](#6-mã-thoát-mọi-lệnh) | Ý nghĩa của từng số mã thoát |
| [§7 Việc chạy theo lịch](#7-việc-chạy-theo-lịch) | Nên đặt lịch cho việc nào, vào lúc nào, và chúng xử lý ra sao khi có sự cố |

Trạng thái: **Decided** (đã quyết định) trừ khi được gắn **Planned Mx** (đã lên kế hoạch cho mốc Mx) hoặc **Open OD-n** (một quyết định của chủ sở hữu còn mở). Các thao tác của M1 đã có trong mã. CI chạy đạt trên cả ba làn kiểm thử (lane) dùng Docker thật, và bản phát hành `v0.1.0` đã chạy đạt `selftest --host` trên máy đầu tiên; hiện chưa có ứng dụng thật nào chạy dưới Ingat trên một máy ([README](../README.vi.md#tình-trạng)). Các khóa manifest nhắc tới ở đây được định nghĩa trong [MANIFEST_SPEC.md](MANIFEST_SPEC.vi.md); các tiến trình, cách bố trí thư mục và giao ước với Compose nằm trong [ARCHITECTURE.md](ARCHITECTURE.vi.md).

Các ví dụ gọi hai ứng dụng tham chiếu bằng tên thay thế: *ứng dụng PostgreSQL* (the PostgreSQL consumer: PostgreSQL, các dịch vụ backend và web; một bước cập nhật dữ liệu (migrate) chạy riêng; cấp quyền cho các role sau khi khôi phục; một lệnh kiểm tra tính nhất quán của dữ liệu (invariant check)), được mô phỏng bằng ứng dụng thử (fixture) `fx-pg`, và *ứng dụng SQLite* (the SQLite consumer: một container; SQLite trong một thư mục dữ liệu gắn trực tiếp từ máy (bind mount); sao lưu khi ứng dụng vẫn chạy, bằng cách riêng của ứng dụng; một hàng đợi thư gửi đi; cập nhật dữ liệu khi khởi động), được mô phỏng bằng ứng dụng thử `fx-lite`. `fx-web` là ứng dụng thử không lưu dữ liệu ([ARCHITECTURE.md](ARCHITECTURE.vi.md) §10.2).

## 1. Quy tắc an toàn bắt buộc

Các quy tắc an toàn bắt buộc (safety floor) nằm ngay trong mã. Không cờ dòng lệnh, khóa manifest, khóa cấu hình bản cài hay biến môi trường nào tắt được một quy tắc, và không có `--force` hay `--yes`.

| ID | Quy tắc | Được bảo đảm bởi |
|---|---|---|
| F1 | **Một bản cài, nêu rõ.** Mỗi lệnh về bản cài (instance) nêu đúng một bản cài; tên được xác định một lần rồi truyền xuống không đổi; không có bản cài mặc định. Tên bản cài chính là tên dự án Compose. Mã engine (engine ID) của Docker daemon phải khớp với `host.json`. | bảng lệnh của CLI, trình thực thi (executor) |
| F2 | **Lập kế hoạch trước khi tác động; một lời từ chối không để lại dấu vết.** Mọi phép kiểm tra chạy trong một giai đoạn lập kế hoạch thuần túy (không thay đổi gì). Một lệnh bị từ chối, có kế hoạch đã cũ (stale) hoặc bị hủy trước khi tác động sẽ để `instances/` và danh mục đối tượng Docker có nhãn y như cũ (trừ các bộ nhớ đệm nêu trong [ARCHITECTURE.md](ARCHITECTURE.vi.md) §5.3 và các tệp ghi người đang giữ khóa `lock.holder.json` và `host.lock.holder.json`; một lời từ chối bên trong một trình thực thi đã khởi động còn để lại kế hoạch đã duyệt của nó trong `plans/` và tệp ghi lần chạy của nó trong `host/runs/`). | khung lập kế hoạch, bộ kiểm thử không để lại dấu vết (no-trace) |
| F3 | **Việc duyệt gắn với một kế hoạch.** Thao tác lớp C và D chỉ chạy sau khi duyệt một kế hoạch có mã băm (plan hash) bao gồm các đầu vào và dấu vân tay trạng thái (fingerprint) đã quan sát (số thứ tự lần triển khai, ID container và mã băm cấu hình, con trỏ vùng dữ liệu, mã băm bản sao lưu, thao tác đang mở). Trình thực thi quan sát lại và từ chối một kế hoạch đã cũ. | `core/approval.py`, trình thực thi |
| F4 | **Đầu vào cố định.** Một thao tác chỉ chạy đúng commit đã xuất ra, nội dung manifest, ID image, tệp override đã sinh và các tệp biến môi trường đã dựng, như đã ghi trong kế hoạch. | trình thực thi |
| F5 | **Ghi ý định trước khi tác động; quan sát trước khi thử lại.** Mỗi bản cài có nhiều nhất một thao tác đang mở; nó chặn mọi thay đổi khác, trừ `resume`, `abandon`, `cancel` và những tác vụ mà bước đang mở cho phép. Một kết quả `unknown` (không rõ) không bao giờ được thử lại một cách mù quáng. | nhật ký, trình thực thi |
| F6 | **Giữ lại trước khi thay thế.** Một lần triển khai (deploy) đổi image của bất kỳ phần ghi dữ liệu (writer: phần của ứng dụng thay đổi dữ liệu) hay dịch vụ dữ liệu (data service) nào sẽ dừng các phần ghi dữ liệu, chụp một bản sao lưu (bundle) trước thay đổi bằng bản phát hành hiện tại, niêm phong và kiểm tra nó, rồi mới cập nhật dữ liệu (migrate) hoặc khởi động image mới. Nếu việc giữ lại thất bại, không có gì bị thay thế. | bộ lập kế hoạch triển khai |
| F7 | **Không bao giờ ghi đè dữ liệu.** Khôi phục, quay dữ liệu về bản cũ và chuyển sang image dữ liệu mới đều đổ dữ liệu vào một vùng dữ liệu (generation) mới rồi chuyển một con trỏ; vùng dữ liệu trước đó được giữ cho tới khi có một lệnh dọn bớt (prune) lớp D rõ ràng, và lệnh đó không bao giờ xóa vùng hiện tại hay vùng ngay trước đó. | vùng dữ liệu, override |
| F8 | **Xóa theo danh sách đóng, có chứng minh quyền sở hữu.** Ingat chỉ xóa những đối tượng mang nhãn của nó và có trong một kế hoạch xóa đã cố định; mỗi mục được chứng minh lại (ID, thời điểm tạo, nhãn, những gì đang dùng nó) ngay trước khi xóa. Không bao giờ `prune`, không bao giờ `down -v`, không bao giờ xóa một đường dẫn gắn trực tiếp (bind) nào ngoài một vùng dữ liệu do chính Ingat tạo ra và có trong kế hoạch xóa. Trước M3, Ingat không xóa image nào. Một đối tượng không thuộc Ingat (foreign) không bao giờ bị động tới: Ingat không bao giờ dừng, khởi động, chạy lệnh bên trong (exec), gắn (mount), gắn lại nhãn, khôi phục vào hay xóa nó; việc tiếp quản (adoption, M4) bắt đầu từ một phần dữ liệu (payload) mà chủ sở hữu đã tạo bằng lệnh sao lưu riêng của ứng dụng (§4.16). | bước xóa, quy tắc an toàn cho cấu hình Compose (policy) |
| F9 | **Lệnh chẩn đoán không bao giờ ghi.** `status`, `doctor`, `list`, `ps`, `logs`, `bundles`, `history`, `validate`, `plan` không ghi gì, trừ `plans/` đối với `plan`. | bảng lệnh của CLI, bộ kiểm thử no-trace |
| F10 | **Kết quả kiểm tra gắn với bằng chứng.** Chỉ Ingat ghi `verified` (đã kiểm tra) và `restore-tested` (đã thử khôi phục), mỗi cái gắn với mã băm của một bản sao lưu. Gỡ bỏ hoàn toàn (purge) cần một bản sao lưu cuối cùng đã thử khôi phục, trừ khi bản cài được tạo với `disposable` (dùng xong bỏ). | kiểm tra (verify), gỡ bỏ hoàn toàn (purge) |
| F11 | **Nguồn gốc luôn được giữ.** Bản ghi triển khai giữ tag, commit, ID image, mã băm của manifest và của mô hình (model), và schema (cấu trúc dữ liệu); image của lần triển khai hiện tại và lần trước đó, và của các bản sao lưu trước thay đổi đang được ghim, đều được giữ lại. | bản ghi, sổ ghi image (ledger) |
| F12 | **Bí mật (secret) chỉ nằm trong tệp.** Không bao giờ nằm trong argv (đối số dòng lệnh), kế hoạch, bản ghi, bản sao lưu, log hay thông báo lỗi; đầu ra được thu lại đều bị che phần bí mật; đầu ra loại `terminal` không bao giờ được thu lại. | runner, kiểu `Secret` |
| F13 | **Cách ly và chốt chặn.** Các lần chạy cách ly (thử khôi phục (drill), phần dựng tạm khi khôi phục) dùng mạng nội bộ (internal), không mở cổng ra ngoài, dùng dải mạng con lấy từ pool (nhóm dải địa chỉ dành riêng cho việc chạy cách ly) và các chốt chặn (hold) của manifest, và không bao giờ động tới dự án đang chạy thật hay vùng dữ liệu đang dùng thật. Ứng dụng có tác động ra bên ngoài chỉ được khôi phục qua tác vụ khôi phục riêng của nó; mỗi dòng dữ liệu (lineage) chỉ có một bản cài chạy thật (phần kiểm tra điều này: Planned M4). | override, các bộ lập kế hoạch |
| F14 | **Chỉ trên nền tảng đã kiểm thử.** Các bậc cổng phiên bản (gate tier) ([ARCHITECTURE.md](ARCHITECTURE.vi.md) §3.6); không có cách bỏ qua. | `policy/gate.py` |
| F15 | **Container tác vụ là tiến trình do Ingat sở hữu.** Mỗi container tác vụ chạy một lần có một tên xác định trước, riêng cho từng lần thử, và các nhãn của thao tác, được dừng và chờ kết thúc trước khi nhả khóa, và chặn `resume`/`abandon` khi còn chạy; một container đã thoát do sự cố để lại được ghi làm bằng chứng cho bước của nó rồi được xóa ([ARCHITECTURE.md](ARCHITECTURE.vi.md) §4.5). Các bước `exec` có thay đổi chỉ chạy bên trong các dự án cách ly. | trình thực thi, phép kiểm tra hợp lệ (validation) |
| F16 | **Kho dữ liệu chỉ được coi là sẵn sàng khi đã chứng minh.** Mỗi lần khởi động một dịch vụ dữ liệu đều chờ phép kiểm tra sẵn sàng (probe) ổn định của kho dữ liệu (store) của nó trước khi bất kỳ bước tác vụ, khôi phục hay cài đặt nào động tới nó. | bước `Up` |
| F17 | **Không có công tắc làm yếu quy tắc.** Không `--force`, không `--yes`, không tệp policy; cách duy nhất để thoát khỏi một quy tắc an toàn bắt buộc là một thao tác khác, được duyệt rõ ràng. | quy tắc thiết kế |

## 2. Lớp duyệt và các lệnh

| Lớp | Ý nghĩa | Cách duyệt | Chạy không người trông |
|---|---|---|---|
| A | chỉ đọc | không cần | có |
| B | không phá hủy: chỉ ghi các sản phẩm mới (bản sao lưu, bản ghi kiểm tra, bản chờ triển khai (candidate)) hoặc chỉ xóa những gì quy tắc giữ lại (retention) cho phép | không cần | có |
| C | có thay đổi | trên một terminal, gõ tên bản cài; nếu không thì `ingat apply <≥12 hex of plan hash>` cho một kế hoạch do `ingat plan …` tạo ra và được chủ sở hữu giao lại | chỉ qua `apply` |
| D | phá hủy hoặc làm mất dữ liệu | **chỉ trên một terminal thật**: gõ cụm từ cộng với một mã thử thách (challenge) ngẫu nhiên 4 ký tự (ví dụ `PURGE pg-staging k7q2`). `apply` không bao giờ được chấp nhận cho lớp D, kể cả với bản cài `disposable`. | không |

`selftest` và `conformance` tự điều khiển các bản cài dùng một lần của riêng chúng bên trong một lệnh và chỉ xóa những đối tượng do chính lệnh đó tạo; chúng không bao giờ dùng `apply`, và các kế hoạch chúng chạy bên trong lệnh không cần duyệt riêng (không gõ tên, không có mã thử thách lớp D).

| Lệnh | Lớp | Chạy trong | Mốc |
|---|---|---|---|
| `version`, `host check`, `status [<i>] [--json]`, `doctor <i>`, `list`, `ps <i>`, `logs <i> <service> [--since]`, `history <i>`, `validate <repo-dir>`, `attach <i>`, `bundles <i>` | A | CLI | M1 |
| `plan <command…>` | A | CLI | M2 |
| `prepare <i> <ref>` | B | trình thực thi | M1 |
| `prepare <i> --image <svc>=<repo>@sha256:…` | B | trình thực thi | M2 |
| `task <i> <name>` khi tác động (effect) của tác vụ là `read` | B | trình thực thi | M1 |
| `cancel <i>` | B | CLI (chỉ ghi tệp yêu cầu hủy) | M1 |
| `selftest [--host]` | B | trình thực thi của máy (`selftest --offline`: CLI, không cần daemon) | M1 |
| `backup <i> [--class <class>] [--reason TEXT] [--prune]`, `verify <i> <bundle>\|--latest`, `verify … --restore-test`, `prune <i> --bundles [--apply]`, `scheduled backup\|verify\|task <i> …`, `scheduled status` | B | trình thực thi (`scheduled status`: CLI, chỉ ghi `host/attention.json`) | M1 |
| `host init` | C | CLI (khóa của máy; không thay đổi gì trong Docker) | M1 |
| `init <i> --config <file> --ref <ref>` | C | CLI (khóa của máy; không thay đổi gì trong Docker) | M1 |
| `start\|stop\|restart <i> [<service>…]`, `resume <i>`, `abandon <i>` | C | trình thực thi | M1 |
| `apply <hash>` | C | trình thực thi | M2 |
| `deploy <i> <ref>` (cài lần đầu, cập nhật, chỉ đổi cấu hình) | C, hoặc D khi kế hoạch đổi một khóa cần chủ sở hữu duyệt (owner-gated) hoặc image của một dịch vụ dữ liệu | trình thực thi | M1 cho ứng dụng không lưu dữ liệu và ứng dụng có kho dữ liệu dạng thư mục gắn trực tiếp (bind) (thay đổi cần chủ sở hữu duyệt bị từ chối cho tới M2), M2 cho kho dữ liệu dạng volume, dịch vụ dữ liệu và nguồn là image, đổi image dữ liệu ở M3 |
| `task <i> <name>` với tác động `app-write` hoặc `data` | C | trình thực thi, hoặc CLI đối với tác vụ terminal | M1 |
| `secret set <i> <KEY>` (giá trị lấy từ stdin) | C | CLI (khóa của bản cài; không thay đổi gì trong Docker) | M2 |
| `restore <i> --bundle <id> --reason TEXT` vào một bản cài chưa từng được triển khai | C | trình thực thi | M2 |
| `restore <i> --bundle <id> --reason TEXT` vào một bản cài đã có dữ liệu; `start <i> --unfreeze` | D | trình thực thi | M2 |
| `rollback <i> [--to <seq>] [--accept-schema <rev>]` | C khi chỉ quay mã; D khi nó khôi phục dữ liệu, khi việc ghi đã được mở lại kể từ lần triển khai đích, hoặc khi có `--accept-schema` | trình thực thi | M3 |
| `restore <i> --generation <store>=g<N>`, `prune <i> --generations\|--images [--apply]`, `purge <i>`, `resolve <i> --step N --as done\|not-done --reason TEXT` | D | trình thực thi | M3 |
| `check [<i>]`, `schedule render <i> --systemd\|--cron\|--dsm`, `conformance --repo <dir> [--from <ref>]` | A/B | CLI/trình thực thi | M3 |
| `import <dir> --into <i>`, `export-config <i> --to <dir>`, `host rebind` (D) | B/C/D | trình thực thi | M4 |
| `import --payload <dir> --into <i> --release <ref> --from <name> [--id <bundle-id>] --reason TEXT` (tiếp quản, §4.16) | B | trình thực thi | M4 |
| `ui [--port N] [--idle MIN]` | A | CLI (một cổng nghe chỉ trong máy (loopback) cho phiên làm việc, trong một container không có socket Docker) | Planned (ADR-0032, sau phần việc (slice) giao kế hoạch của M2) |
| `report preview`, `support-bundle <i>` | A | CLI | Planned (ADR-0033) |
| `report enroll`, `report disable` | C | CLI (khóa của máy; không thay đổi gì trong Docker) | Planned (ADR-0033) |
| `scheduled report` | B | CLI (chỉ ghi `host/report.json` và con trỏ đọc của nó) | Planned (ADR-0033) |
| `self-upgrade <version>`, `self-rollback`, `state migrate` | C | trình thực thi của máy | M5 |

Agent vận hành (trợ lý AI) được chạy tự do lớp A và B, chỉ chạy lớp C với một mã băm kế hoạch do chủ sở hữu đưa cho, và không bao giờ chạy lớp D. CLI không phân biệt được một agent với chủ sở hữu: một agent tự mở được một pty (terminal giả) thì gõ được mã thử thách. Vì vậy quy tắc này chỉ đứng vững với những agent tuân theo nó; chính các quy tắc chặn (deny rules) trong công cụ của agent buộc nó tuân theo (quyết định của chủ sở hữu OD-10).

## 3. Mô hình thao tác

### 3.1 Lập kế hoạch, duyệt, thực thi

```
parse ─► plan (pure: validate manifest/instance, observe read-only, gate tier, capacity, policy on every model it will run,
         ordered step list, fingerprint, canonical hash)
           │ refusal ─► exit 1 (or 2), nothing written                                             (F2)
           ▼
       approve (class rules) ─► plans/<hash>.json written once
           ▼
       executor: flock ─► open op? ─► orphan check ─► re-observe fingerprint ─► stale ─► refused-stale, exit 1
           ▼
       ops/<seq>-<kind>/ created ─► for each step: intent (fsync) ─► effect (EffectToken) ─► observe ─► done | failed | unknown
           ▼
       close decision journaled (step 0) ─► unwind (failure or abandon) ─► record.json ─► result.json (write-once)
           ─► lock released ─► run file host/runs/<run-id>.json ─► CLI prints outcome and `next`
```

`result.json` chỉ có với một thao tác đã đóng, nên nó được ghi sau cùng: nếu sự cố xảy ra ở bất kỳ đâu trong lúc đóng, thao tác vẫn đang mở, và lệnh `resume` hoặc `abandon` kế tiếp sẽ hoàn tất việc đóng mà bước 0 đã ghi, chứ không bao giờ đi tiếp vượt qua những gì việc tháo lui (unwind) đã hoàn tác. Mỗi lần trình thực thi chạy, kể cả lần bị từ chối, đều để lại một tệp ghi lần chạy (mã thoát, mã kết quả, thông báo, `next` và các cảnh báo); các cảnh báo của kế hoạch (cảnh báo bậc cổng 1, việc bỏ qua quy tắc giữ lại) được chép vào `result.json` và tệp ghi lần chạy. Một kế hoạch hết hạn 24 giờ sau khi được tạo: trình thực thi từ chối kế hoạch đã hết hạn (mã thoát 2), và M1 không xóa kế hoạch nào, trừ kế hoạch của các bản cài riêng của một lần chạy selftest, lúc lần chạy đó dọn dẹp.

### 3.2 Trạng thái của thao tác

```
            ┌──────────── refused-stale (exit 1; nothing written under instances/)
planned ─approve─► running ──────────────► completed (exit 0)
                    │  failure before the forward point: undo reversible steps ─► failed-unchanged (exit 3)
                    │     … an undo or teardown that did not complete ─────────────► needs-review   (exit 4)
                    │  failure at/after the forward point: stop writers ──────────► failed-frozen  (exit 3)
                    │  cancel before any effect ────────────────────────────────────► abandoned      (exit 130)
                    │  install pause ──────────────────────────────────────────────► paused         (exit 4) ─resume─► running
                    │  unknown outcome / executor killed / host reboot ─────────────► interrupted    (exit 4)
                    ▼
            interrupted ─resume─► running (rules in §3.4)
            interrupted ─abandon─► abandoned (undo reversible; tear down scratch; writers stay stopped past the forward point)
                                   … an undo or teardown that did not complete ─► needs-review (exit 4)
            interrupted prepare / backup / verify / drill ─next command─► abandoned-auto (recorded undo and teardown), then the new command runs
                                   … an undo or teardown that did not complete ─► needs-review, and the new command is refused (exit 2)
```

**Điểm không quay lại (forward point)** của một thao tác là bước đầu tiên mà sau nó không thể đưa về trạng thái trước bằng cách hoàn tác (undo): một tác vụ có tác động lên dữ liệu trên vùng dữ liệu đang dùng thật (cập nhật dữ liệu, migrate), hoặc bước kích hoạt được đánh dấu `reopens_writes` (mở lại việc ghi). Trong một lần cập nhật có thay đổi dữ liệu, mọi nhóm kích hoạt đều thuộc loại không quay lại, vì lần khởi động đầu tiên của một phần ghi dữ liệu thuộc bản chờ triển khai có thể đã thay đổi dữ liệu. Một bước `Delete` không bao giờ được tính là điểm không quay lại (một lần xóa thất bại không bao giờ dừng các phần ghi dữ liệu hay gây tạm khóa), bước của một tác vụ `app-write` chỉ có một bước cũng không (§3.5), và một lần migrate mà ngay lần thử đầu tiên ứng dụng đã từ chối (`refused`) cũng không (không có gì thay đổi, §4.4). Một yêu cầu hủy sau khi đã có tác động tuân theo cùng các quy tắc thất bại, với mã `cancelled`: `failed-unchanged` nếu trước điểm không quay lại, `failed-frozen` nếu sau nó. Mỗi trạng thái kết thúc đều in ra đúng lệnh tiếp theo; một bài kiểm thử khẳng định rằng lệnh được in ra có tồn tại và chạy thành công từ trạng thái đó, kể cả một lần khôi phục vào một bản cài chưa từng được triển khai (bước chuyển sang (cut-over) của một lần tiếp quản) kết thúc ở `failed-frozen` (§4.10) (một công cụ triển khai nội bộ trước đây từng có những trạng thái kết thúc không có cách nào đi tiếp được).

### 3.3 Các loại bước (danh sách đóng; thêm loại mới cần một ADR)

| Bước | Lớp bước | Ngắt được | `observe` | Hoàn tác |
|---|---|---|---|---|
| `Obtain(services)` (kéo image về, ghi lại ID; Ingat không bao giờ tự build: [ADR-0026](adr/0026-app-images-built-in-app-ci.vi.md)) | nháp (scratch) | có | mục trong sổ ghi image có ID và nhãn khớp | không có (chỉ là bộ nhớ đệm) |
| `RunTask` với tác động `read` | nháp | có | có bản ghi kết quả | không có |
| `SnapshotLogs(services)` (`docker logs --tail` có giới hạn, đã che bí mật, quyền 0600) | nháp | có | có tệp kết quả | không có |
| `Stop(services)` | đảo ngược được (reversible) | không (thời gian giới hạn bởi `stop_grace_period`) | các container đã dừng | khởi động lại chúng theo lần triển khai đã ghi |
| `CreateGeneration(store)` | nháp cho tới khi được chuyển sang dùng | không | volume hoặc thư mục có nhãn, kèm tệp đánh dấu | xóa nó, chỉ khi chính thao tác này đã tạo nó và chưa bao giờ đưa nó lên dùng thật |
| `Up(project, services, wait)` | chạy thật: đảo ngược được trước điểm không quay lại; cách ly: nháp | phần chờ probe: có | đang chạy với đúng ID image mong đợi và các probe ổn định | dừng, rồi khởi động lại lần triển khai đã ghi |
| `RunTask` với tác động `app-write` hoặc `data` | chạy thật: không quay lại (forward) (phải `idempotent` hoặc khai báo `observe`, theo quy tắc kiểm tra hợp lệ); cách ly: nháp; một tác vụ thuộc `backup.steps` hoặc `backup.verify`: nháp, bất kể tác động của nó (xem bên dưới) | không (nguyên khối) | theo `observe` | không có |
| `CaptureBundle(class)` | nháp cho tới khi niêm phong; bản sao lưu đã niêm phong được giữ | có, cho tới lúc niêm phong | mục trong danh mục (catalog) có mã băm bản sao lưu | bỏ vùng chuẩn bị (stage) đang dở |
| `VerifyBundle` | nháp | có | bản ghi kiểm tra cho mã băm đó | không có |
| `SwitchGeneration(store, from, to)` | đảo ngược được cho tới khi một phần ghi dữ liệu khởi động trên `to` | không | con trỏ trong `record.json` | chuyển về lại |
| `Teardown(isolated project)` | dọn dẹp phần nháp | không | các container và mạng mang nhãn của chính nó đã biến mất; nó chỉ tác động lên `<i>--t<seq>` hoặc `<i>--r<seq>` của chính thao tác này (nếu không thì báo `not-isolated`), và ngay trước `down`, mọi container và mạng của dự án phải mang nhãn của bản cài và của thao tác (nếu không thì báo `foreign`) | không có |
| `Delete(plan item)`: một bản sao lưu, một container do Ingat sở hữu ([ARCHITECTURE.md](ARCHITECTURE.vi.md) §7.5) hoặc một vùng dữ liệu của selftest (xem bên dưới) | không quay lại, nhưng không bao giờ là điểm không quay lại (§3.2) | không | mục đã biến mất; tiến độ được lưu | không có |
| `Record(kind)` | chạy lại an toàn (idempotent) | không | bản ghi đã được ghi | không có |
| `Pause(text, allow_tasks)` | người vận hành | không áp dụng | đã gọi `resume` | không có |

**Tác vụ sao lưu là bước nháp.** Mọi tác vụ có trong `backup.steps` hoặc `backup.verify` đều thuộc lớp nháp (scratch), bất kể tác động đã khai báo của nó. Nó chỉ được ghi vào vùng chuẩn bị (stage) và vào sổ theo dõi các bản sao lưu của chính ứng dụng (ứng dụng SQLite ghi kết quả của mỗi lần sao lưu vào cơ sở dữ liệu của chính nó), và phép kiểm tra hợp lệ đòi `idempotent = true` cho mọi tác vụ như vậy mà không phải `read`. Vì vậy một thao tác sao lưu không có điểm không quay lại: bỏ dở nó không bao giờ dừng hay tạm khóa các phần ghi dữ liệu, và việc xóa theo quy tắc giữ lại của một lần sao lưu theo lịch cũng không bao giờ gây tạm khóa.

**Bản cài của selftest.** Có hai dạng bước chỉ tác động lên một bản cài `ingat-selftest-*` mà tệp đánh dấu `instances/<i>/selftest.json` của nó (được ghi khi selftest tạo bản cài) ghi tên một lần chạy selftest: một bước `Teardown` của dự án chạy thật của nó, được chứng minh lại giống như với dự án cách ly (mọi container và mạng đều mang nhãn của bản cài), và một mục `Delete` thuộc loại `generation`, xóa một vùng dữ liệu (kể cả vùng hiện tại) chỉ khi tệp đánh dấu riêng của vùng đó ghi đúng bản cài, kho dữ liệu và vùng dữ liệu này và không container nào đang gắn (mount) nó. Selftest chạy chúng trong một thao tác khép kín thuộc loại `teardown` (lớp B, được lập kế hoạch không có phần ghi dữ liệu nào, nên một lần dọn dẹp thất bại không dừng gì cả).

### 3.4 Tiếp tục, bỏ dở, tự động bỏ dở

`resume <i>`: trước tiên kiểm tra container mồ côi (F15; các container tác vụ đã thoát trở thành bằng chứng và được xóa, [ARCHITECTURE.md](ARCHITECTURE.vi.md) §4.5). Một việc đóng đã được quyết định (bước 0, §3.1) được hoàn tất đúng như đã quyết định. Nếu không, lấy bước đầu tiên chưa có `done`:

- **nháp (scratch)** → bỏ các kết quả dở dang của nó (vùng chuẩn bị, các container cách ly của nó, một vùng dữ liệu chưa được đưa lên dùng mà nó đã tạo) và làm lại từ bước đầu tiên trong nhóm của nó; khi dự án cách ly của thao tác này vẫn còn container, dự án đó được gỡ xuống trước (`compose down`, không bao giờ kèm `-v`, được chứng minh lại như với `Teardown`) và việc làm lại bắt đầu từ bước đầu tiên đã tác động lên dự án đó hoặc đã tạo một vùng dữ liệu. Một bước niêm phong của `CaptureBundle` còn dừng ở `intent` mà bản sao lưu của nó đã có trong danh mục với mã băm của tệp `SHA256SUMS` đã công bố thì thay vào đó được coi là đã xong (§3.3), nên một lần tiếp tục không bao giờ niêm phong một bản sao lưu thứ hai;
- **đảo ngược được (reversible)** → quan sát; nếu `done` → ghi là đã xong; nếu không thì làm lại;
- **không quay lại (forward) và `idempotent`** → chạy lại;
- **không quay lại với `observe = "schema"`** → chạy phép quan sát schema: đã đạt schema đích → xong; còn ở schema nguồn → chưa bắt đầu, làm lại; trường hợp khác → giữ `unknown`, mã thoát 4 (Planned M3: `resolve`, lớp D, ghi lại quyết định của chủ sở hữu). Trình thực thi của M1 chưa chạy phép quan sát này: nó không bao giờ lặp lại một bước như vậy, lần tiếp tục (resume) dừng với mã thoát 4, và `status` gợi ý `abandon`;
- một bước đã được ghi nhật ký là `failed` hoặc `cancelled` (thấy trước khi có sự cố, hoặc được quyết định dựa trên bằng chứng từ container mồ côi) → áp dụng các quy tắc thất bại, như thể vừa thấy lúc này.

Thao tác của một tác vụ terminal được tiếp tục trong CLI, trên chính terminal chạy `resume`, không bao giờ trong trình thực thi chạy tách rời ([ARCHITECTURE.md](ARCHITECTURE.vi.md) §4.3).

`abandon <i>`: hoàn tác các bước đảo ngược được đã xong, theo thứ tự ngược lại, dọn các phần nháp (các dự án cách ly; các vùng dữ liệu do thao tác này tạo và chưa bao giờ đưa lên dùng, bằng một lần xóa theo danh sách đóng các đối tượng mang nhãn của thao tác), rồi đóng với `abandoned`. Nếu một bước không quay lại đã hoàn tất hoặc đang `unknown`, các phần ghi dữ liệu vẫn bị dừng và bản cài chuyển sang `frozen` (tạm khóa). Một lần hoàn tác hay dọn dẹp không hoàn tất (ví dụ các phần ghi dữ liệu không khởi động lại được) sẽ đóng với `needs-review` (mã thoát 4) thay vì `abandoned`, kèm các cảnh báo trong kết quả (§3.5).

**Tự động bỏ dở (auto-abandon)** (thao tác không có bước không quay lại): theo thiết kế, `prepare`, `backup`, `verify` và lần thử khôi phục chỉ gồm các bước nháp và bước đảo ngược được (tác vụ sao lưu là bước nháp, §3.3). Khi một lệnh thấy một thao tác như vậy đang mở và không còn container tác vụ nào của nó đang chạy, lệnh đó bỏ dở thao tác: hoàn tác các bước đảo ngược được đã xong (các phần ghi dữ liệu đã bị một lần sao lưu ngoại tuyến (offline) dừng lại sẽ được khởi động lại theo lần triển khai đã ghi), dọn các phần nháp bằng một lần dọn dẹp có ghi lại, rồi chạy tiếp. Vì vậy một lần sao lưu ban đêm bị sự cố không bao giờ chặn lần kế tiếp. Khi việc hoàn tác hay dọn dẹp đó không hoàn tất, thao tác đóng với `needs-review` (mã thoát 4) và lệnh đã phát hiện ra nó bị từ chối (`needs-review`, mã thoát 2; `next` là `status <i>`) thay vì chạy tiếp, chẳng hạn khi các phần ghi dữ liệu đang dừng mà bản ghi lại nói là đang chạy. `status` vẫn hiện thao tác đã bị bỏ dở, và `scheduled` báo nó trong dòng kết quả của mình.

### 3.5 Kết quả không rõ

| Ở đâu | Quy tắc |
|---|---|
| Một mã thoát khác 0 không được khai báo của một tác vụ có tác động `read` | `failed` |
| Một mã thoát khác 0 không được khai báo của một tác vụ có tác động `app-write` hoặc `data` | `unknown`, không bao giờ là `failed` |
| Một kết quả `unknown` đã khai báo (ví dụ mã thoát 2 của các tác vụ migrate, tạo role và cấp quyền của ứng dụng PostgreSQL) | được giải quyết bằng `observe = "schema"` hoặc một lần chạy lại an toàn (idempotent) |
| Một bước trong một dự án cách ly hoặc trên một vùng dữ liệu chưa được đưa lên dùng | nháp: bỏ đi và làm lại khi tiếp tục; một trình thực thi đang chạy coi `unknown` của một bước nháp là `failed` |
| Một thất bại trước điểm không quay lại, một lần `abandon` hoặc một lần tự động bỏ dở mà việc hoàn tác hay dọn dẹp không hoàn tất (ví dụ các phần ghi dữ liệu không khởi động lại được) | `needs-review` (mã thoát 4) thay vì `failed-unchanged` hoặc `abandoned`; kết quả liệt kê các cảnh báo; lệnh đã tự động bỏ dở nó bị từ chối (`needs-review`, mã thoát 2) |
| Một container tác vụ không chứng minh được là đã dừng sau khi hết thời gian chờ hoặc sau một lần hủy | bước giữ `unknown` với mã `task-running` và thao tác vẫn mở (mã thoát 4); `next` là đúng lệnh `docker stop` cần chạy (F15) |
| Một tác vụ `app-write` chỉ có một bước (ví dụ mã thoát 2 được khai báo là `unknown` của một tác vụ đặt lại mật khẩu, hoặc một lần thoát `ok` mà stdout không đạt `expect` của tác vụ) | thao tác đóng với `needs-review` (mã thoát 4); nó không tạm khóa bản cài và không chặn các thao tác khác; `status` hiện nó |

### 3.6 Trạng thái của bản cài

```
(none) ─init─► registered ─deploy (first install)─► running ⇄ stopped        (start / stop / restart)
registered ─restore (class C; an adoption imports its payload first, §4.16)─► running [+ adopted_from]
           | registered (failed-unchanged; g1 torn down) | frozen (restore deployment recorded before its start, §4.10)
running | stopped ─deploy | rollback | restore─► [operation open] ─► running | previous state (failed-unchanged) | frozen
frozen ─deploy (forward) | restore | rollback (M3) | resume─► running        start is refused; `start --unfreeze` is class D
running ─restore of an app with side_effects.after_restore = "held"─► running + held_since   (cleared by the clear_hold task)
any ─purge (M3)─► purged                                                      records, bundles, secrets and lock are kept
```

**Cách đi tiếp từ trạng thái tạm khóa.** Khi lần triển khai mới nhất của bản cài đã làm nó tạm khóa (kết thúc ở `failed-frozen`, hoặc bị bỏ dở sau điểm không quay lại) sau khi bản sao lưu trước thay đổi của nó đã được niêm phong và ghi là `verified`, lần triển khai đó in chính lệnh của nó làm `next`, và `deploy <i> <ref>` với cùng bản chờ triển khai, trên cùng lần triển khai hiện tại, chỉ lập kế hoạch gồm: `VerifyBundle` của bản sao lưu đó → migrate (điểm không quay lại, với `{freeze_at}` và `{bundle.*}` của lần chụp) → các nhóm kích hoạt → các phép kiểm tra → `Record`, ghép lần triển khai mới với bản sao lưu đó. Một lần đi tiếp mà lại bị tạm khóa, hoặc thất bại mà không có gì thay đổi, có thể được lập kế hoạch lại. Việc đi tiếp bị từ chối (`frozen`; cách quay lại là khôi phục một bản sao lưu trước thay đổi, M2) khi bản sao lưu đã bị dọn bớt hoặc không còn ở trạng thái đã kiểm tra, khi tác vụ migrate không `idempotent` (lần chạy trước của nó có thể đã kết thúc `unknown`, F5), hoặc với bất kỳ bản chờ triển khai nào khác. Trong lúc bản cài bị tạm khóa, quy tắc giữ lại giữ bản sao lưu đó (§5.6); `backup` từ chối (`frozen`, `next` là cách đi tiếp), vì các tác vụ của bản phát hành đã ghi sẽ chụp dữ liệu có thể đã qua điểm không quay lại; `start`, `stop`, `restart` và các tác vụ ghi đều từ chối; các tác vụ đọc, `verify` và các lần thử khôi phục vẫn chạy. Một lần cài lần đầu kết thúc ở trạng thái tạm khóa được triển khai lại trên chính `g1` mà nó đã tạo.

`disposable` được cố định lúc `init` và được ghi trong `record.json`; một lần sửa `instance.toml` về sau mà đổi giá trị này sẽ bị từ chối.

## 4. Các thao tác

### 4.1 `host init` và `init`

- `host init` (một lần cho mỗi máy, giữ khóa của máy, chạy trong CLI, duyệt bằng cách gõ tên máy): ghi lại mã engine, DockerRootDir, các phiên bản, kiến trúc, các khả năng của máy (CPU CFS quota, giới hạn bộ nhớ), các thông tin về runc, storage driver, kho image, logging driver và cgroup ([ARCHITECTURE.md](ARCHITECTURE.vi.md) §11), hai thư mục gốc, các pool (pool dải mạng con dùng cho cách ly `10.250.0.0/20`, chia thành các dải `/24`, [ADR-0030](adr/0030-isolation-pool-outside-docker-default-pools.vi.md); và pool cổng `20000-29999` cho các tham số `port` để Ingat tự cấp; [ARCHITECTURE.md](ARCHITECTURE.vi.md) §7.4), và kiểm tra chủ sở hữu và quyền của hai thư mục gốc (`INGAT_ROOT` `root:root 0700`, `INGAT_BACKUPS` thuộc root và không có quyền ghi cho nhóm hay người khác; nếu không thì báo `roots` và không ghi gì). Nó tạo thư mục client Docker rỗng của công cụ `cache/docker-config/`, cùng `plans/`, `host/` và `inbox/`. Chạy lại trên cùng engine sẽ làm mới các thông tin và giữ các pool đã ghi lần đầu; một mã engine khác làm nó dừng lại (`engine-mismatch`, mã thoát 2; `host rebind` thuộc M4).
- `init <i> --config <file> --ref <ref>` (lớp C, giữ khóa của máy, chạy trong CLI, duyệt bằng cách gõ tên bản cài, không động gì tới Docker; bậc cổng 2): chủ sở hữu viết `instance.toml` trước. Ingat lấy mã nguồn về, xác định ref, đọc manifest ở commit đó và kiểm tra bản cài theo manifest, rồi kiểm tra: cú pháp tên; trên daemon không có dự án Compose nào cùng tên (bất kỳ container, mạng hay volume nào mang nhãn `com.docker.compose.project=<i>` đều dẫn tới từ chối `foreign`, kể cả khi nó có nhãn Ingat, vì không có bản ghi nào của bản cài đó); cổng và dải mạng con không trùng với mọi mục cấp phát, mọi cổng đang mở ra ngoài, cấu hình IPAM của mọi mạng trên daemon và pool cách ly; `exclusive_environments` (§4.3); một ứng dụng mà bản phát hành này chạy được (nếu không thì `not-in-this-release`); ở M1, mọi tham số `subnet` phải được đặt trong `instance.toml` (một dải mạng con để Ingat tự cấp sẽ bị từ chối); không có dữ liệu hay bản ghi của một bản cài trước đó cùng tên (`exists`); các bí mật được sinh ra như đã khai báo (đôi một khác nhau). Nó ghi `record.json` (trạng thái `registered`, một mã dòng dữ liệu (lineage id) mới, `disposable`) sau cùng, sau các mục cấp phát, các bí mật và thư mục giữ chỗ, nên chạy lại với cùng cấu hình sẽ hoàn tất một lần `init` bị ngắt và giữ các bí mật nó đã ghi.

### 4.2 `prepare <i> <ref>` (lớp B)

Lấy mã nguồn về bản clone trần (bare clone), xác định ref một lần thành một SHA 40 ký tự hex, kiểm tra mẫu `tag_pattern` của manifest và mẫu `accept` của bản cài, xuất mã bằng `git archive` vào `cache/src/<sha>/`, đọc và kiểm tra manifest ở commit đó (nội dung manifest đã xuất phải giống hệt nội dung đã kiểm tra, để `.gitattributes` không thể thay đổi nó: `unsupported-source`), áp các quy tắc trên văn bản thô cho các tệp Compose của nó trước khi bất kỳ lệnh Compose nào đọc chúng ([ARCHITECTURE.md](ARCHITECTURE.vi.md) §9.5), rồi:

- kéo (pull) mỗi image của bản chờ triển khai một lần, theo tham chiếu mà dịch vụ Compose của nó ghi, được điền bằng các tham số của bản cài (quyết định của chủ sở hữu OD-11, [ADR-0026](adr/0026-app-images-built-in-app-ci.vi.md): image của ứng dụng được build trong CI của ứng dụng; Ingat không bao giờ build). Một tham chiếu theo digest đã có sẵn thì không kéo lại. Image của `build_services` phải khớp `expect_labels`, vốn gắn với commit; một tag có nguồn gốc khác bị từ chối;
- ghi lại ID và digest trong kho image (repository digest) của mỗi image (ví dụ image `postgres` được ghim của ứng dụng PostgreSQL cũng như các image riêng của nó);
- với nguồn là image: kéo `repo@sha256:…` và kiểm tra `RepoDigests`;
- ghi `candidates/<sha>-<refs>.json`, đặt khóa theo commit và một mã băm của các tham chiếu image đã điền (một tham số làm đổi tham chiếu sẽ có một bản chờ triển khai mới, không bao giờ dùng một bản đã cũ), và các mục sổ ghi image chỉ ghi một lần (`host/images/<id>/<instance>-<seq>.json`), không cần khóa của máy. Một bản chờ triển khai đã ghi mà image của nó đã mất (ví dụ sau khi ai đó tự tay dọn bớt image) sẽ được kéo lại theo các digest đã ghi.

`deploy` chạy `prepare` trước tiên khi chưa có bản chờ triển khai nào cho commit đó; khi không có terminal, nó từ chối trước khi chuẩn bị bất cứ thứ gì (việc duyệt của chính nó cần một terminal).

### 4.3 `deploy` — cài lần đầu (trạng thái `registered`)

Kế hoạch: bản chờ triển khai đã được chuẩn bị; không có đối tượng nào trong dự án Compose của bản cài mà không thuộc về nó (`foreign`, F8; mọi lần triển khai, `start`, `stop`, `restart` và một lần sao lưu có dừng các phần ghi dữ liệu đều kiểm tra điều này, vì Compose tác động lên mọi thứ mà dự án của nó chứa); dung lượng (tối thiểu 2 GiB trống trên thư mục gốc của Docker); mọi mô hình đều đạt policy, kể cả các phép kiểm tra khả năng của máy ([ARCHITECTURE.md](ARCHITECTURE.vi.md) §9.5); `exclusive_environments`: một bản cài có môi trường nằm trong danh sách sẽ từ chối triển khai hay khởi động khi có bất kỳ bản cài nào khác của cùng ứng dụng đã được đăng ký trên máy, và các bản cài khác của ứng dụng đó từ chối `init` khi đang có một bản cài trong danh sách (dành cho ứng dụng có quy tắc triển khai riêng cấm mọi bản cài khác của nó trên một daemon đang chạy bản cài production của nó; quyết định của chủ sở hữu OD-5).

Các bước: `CreateGeneration g1` cho mỗi kho dữ liệu (volume có nhãn; thư mục gắn trực tiếp với chủ sở hữu và quyền theo manifest) → các bước `[[install]]` của manifest theo thứ tự (`start` = `Up` với các giá trị ghi đè tham số và các lần chờ tùy chọn; `task`; `pause`, để thao tác ở trạng thái `paused` và chỉ cho phép các tác vụ được liệt kê cho tới khi `resume`) → kiểm tra nhanh sau khi chạy (smoke) → kiểm tra danh tính image → `Record` lần triển khai 1 (`writes_reopened_at` ở bước `reopens_writes`; với một `[schema]` dựa trên probe, giá trị mà probe báo lúc kích hoạt, kèm thời điểm). Một tác vụ được bước tạm dừng cho phép sẽ được ghi nhật ký như một bước của thao tác này ([ARCHITECTURE.md](ARCHITECTURE.vi.md) §4.3). Việc cài đặt không bao giờ thu log của một dịch vụ trong một khoảng được đánh dấu `log_snapshot = false` (một ứng dụng có thể in ra log một bí mật chỉ dùng một lần ở lần chạy đầu).

### 4.4 `deploy` — cập nhật có thay đổi dữ liệu

Một lần triển khai được coi là có thay đổi dữ liệu khi image của bất kỳ phần ghi dữ liệu hay dịch vụ dữ liệu nào khác với lần triển khai hiện tại, hoặc khi ứng dụng khai báo `migrates_on_start` và có bất kỳ image nào thay đổi (ứng dụng SQLite cập nhật dữ liệu khi khởi động). Quy tắc này không cần thăm dò bản chờ triển khai lúc lập kế hoạch (ADR-0017; quyết định của chủ sở hữu OD-4).

Cổng kiểm tra schema lúc lập kế hoạch: khi commit đích đã từng được triển khai trên bản cài này và schema mong đợi đã ghi của nó cũ hơn schema thực tế hiện tại, kế hoạch từ chối với lý do "code-only rollback impossible" (không thể chỉ quay mã về bản cũ) và in lệnh khôi phục cho bản sao lưu trước thay đổi đi kèm. Với đích chưa biết, chính các ứng dụng tự bảo vệ: migrate của ứng dụng PostgreSQL từ chối một phiên bản (revision) nó không biết với mã thoát 1, và ứng dụng SQLite từ chối một schema mới hơn những gì nó biết.

| # | Bước | Lớp bước | Khi thất bại |
|---|---|---|---|
| 1 | `RunTask` các tác vụ lấy mốc (baseline) trên các image hiện tại (được ghi lại, cho phép có phát hiện; **Planned M3**, đầu vào của một phép kiểm tra sau có so sánh, quyết định của chủ sở hữu OD-7) | nháp | failed-unchanged |
| 2 | `RunTask` các phép kiểm tra trước (precheck), mỗi phép chạy trên bộ image mà tác vụ của nó khai báo (`current` hoặc `candidate`); mỗi phép phải là `ok` | nháp | failed-unchanged |
| 3 | `SnapshotLogs` của các dịch vụ `log_snapshot` | nháp | chạy tiếp |
| 4 | `Stop` các phần ghi dữ liệu; ghi `freeze_at` (giờ UTC, `YYYY-MM-DDTHH:MM:SSZ`, đúng dạng mà migrate của ứng dụng PostgreSQL chấp nhận) | đảo ngược được | hoàn tác |
| 5 | `Up` các dịch vụ dữ liệu nếu chưa chạy, chờ kho dữ liệu sẵn sàng (F16) | đảo ngược được | hoàn tác |
| 6 | `CaptureBundle(pre-change)` bằng các tác vụ và image của bản phát hành **hiện tại**, đọc schema trước (§4.7) | nháp | hoàn tác → failed-unchanged |
| 7 | `VerifyBundle` (mã băm cộng các tác vụ kiểm tra) | nháp | hoàn tác → failed-unchanged |
| 8 | kiểm tra lại dung lượng | — | hoàn tác → failed-unchanged |
| 9 | `RunTask` migrate bằng image của bản chờ triển khai, gắn với bản sao lưu này và `{freeze_at}` — **điểm không quay lại** | không quay lại, chạy lại an toàn (idempotent), có quan sát | `refused` → hoàn tác → failed-unchanged; `unknown` → interrupted |
| 10 | `RunTask` các phép kiểm tra sau (postcheck) trên bản chờ triển khai (phải là `ok`) | nháp | dừng các phần ghi dữ liệu → failed-frozen |
| 11 | `Up` các nhóm kích hoạt theo thứ tự, với các lần chờ của chúng; nhóm được đánh dấu `reopens_writes` ghi `writes_reopened_at` | không quay lại | dừng các phần ghi dữ liệu → failed-frozen |
| 12 | các probe kiểm tra nhanh (smoke) và kiểm tra danh tính image (ID image đang chạy = ID đã ghi, cho mọi dịch vụ) | nháp | dừng các phần ghi dữ liệu → failed-frozen |
| 13 | `Record` lần triển khai N+1 (đích quay về là N, id bản sao lưu trước thay đổi) | chạy lại an toàn | — |

Cách áp vào ứng dụng PostgreSQL (được mô phỏng bằng `fx-pg`; giống quy trình phát hành riêng của nó, không chấp nhận các phát hiện có từ trước): precheck = phép kiểm tra tính nhất quán đầy đủ của nó trên bản phát hành đang chạy, phải sạch, nên một phát hiện có từ trước sẽ làm bản phát hành bị từ chối trước thời điểm dừng ghi, cộng thêm một phép kiểm tra tính nhất quán hẹp hơn trên bản chờ triển khai; migrate = dịch vụ migrate chạy một lần của nó; postcheck = phép kiểm tra tính nhất quán đầy đủ trên bản chờ triển khai sau migrate, phải sạch; kích hoạt = backend, rồi web (web mở lại việc ghi); web vẫn phục vụ phần khung giao diện trong lúc backend dừng. Việc chấp nhận các phát hiện có từ trước (một baseline cộng một postcheck có so sánh) cần một thay đổi ở ứng dụng đó và sẽ có ở M3 (quyết định của chủ sở hữu OD-7). Cách áp vào ứng dụng SQLite (được mô phỏng bằng `fx-lite`): không có phép kiểm tra nào; migrate là một lệnh chạy một lần rõ ràng trước khi khởi động, nên lúc khởi động không áp dụng gì.

Việc đổi image của một dịch vụ dữ liệu (ví dụ nâng phiên bản PostgreSQL trong một bản phát hành của ứng dụng PostgreSQL) bị từ chối trước M3 với một thông báo rõ ràng. **Planned M3:** lớp D với một lựa chọn rõ ràng, `--data-image in-place` (cùng định dạng trên đĩa) hoặc `--data-image via-restore` (khôi phục bản sao lưu trước thay đổi vào một vùng dữ liệu mới chạy với image mới), cách này cũng áp dụng cho việc nâng phiên bản lớn (major) của PostgreSQL.

### 4.5 `deploy` — chỉ đổi cấu hình

Khi không có image nào của phần ghi dữ liệu hay của dịch vụ dữ liệu thay đổi, Ingat so `compose config --hash` của từng dịch vụ với `com.docker.compose.config-hash` của container đang chạy (nhãn không mang giá trị nào riêng cho từng lần triển khai, nên chỉ một thay đổi cấu hình thật mới làm đổi mã băm: [ARCHITECTURE.md](ARCHITECTURE.vi.md) §6.2), chụp log, chỉ tạo lại những dịch vụ đã thay đổi (`up --no-deps --no-build --pull never <services>`), chờ các probe của chúng, chạy kiểm tra nhanh (smoke) và ghi lại lần triển khai. Một khóa cần chủ sở hữu duyệt (owner-gated) bị đổi (ví dụ công tắc chế độ gửi ra ngoài và công tắc gửi thật của ứng dụng SQLite) làm kế hoạch thành lớp D và hiển thị thay đổi đó thật nổi bật.

### 4.6 Quay về bản cũ (rollback)

- **M1-M2:** `deploy <i> <older-ref>` đi theo §4.4; cổng kiểm tra schema từ chối nó khi bản phát hành cũ hơn không chạy được trên schema hiện tại, và chủ sở hữu khôi phục bản sao lưu trước thay đổi đi kèm bằng `restore` (§4.10, từ M2); lệnh này chạy tác vụ khôi phục trong image của chính bản phát hành của bản sao lưu đó, nên không cần chế độ giữ nguyên schema.
- **Planned M3:** `rollback <i> [--to <seq>]`. *Chỉ quay mã* khi schema mong đợi đã ghi của lần triển khai đích bằng schema thực tế hiện tại: dừng các phần ghi dữ liệu, `Up` các image đã ghi của đích, các probe, kiểm tra nhanh, `Record` (lớp C). *Quay cả dữ liệu* trong trường hợp còn lại: luồng khôi phục (§4.10) với bản sao lưu trước thay đổi đi kèm, bản phát hành đích, và `[rollback] env` của manifest (với ứng dụng SQLite là tắt bộ chạy việc nền của nó, vì một schema từ trước khi có cơ chế tạm dừng gửi ra ngoài không chứa được các việc nền). Lớp D bất cứ khi nào việc ghi đã được mở lại kể từ lần triển khai đích, và kế hoạch nêu rõ khoảng thời gian mà các lần ghi sẽ bị mất (chúng vẫn nằm trong vùng dữ liệu được giữ lại). `--accept-schema <rev>` (lối quay về của ứng dụng PostgreSQL, trong đó một bản phát hành cũ hơn phục vụ một phiên bản schema mà nó không biết) đặt tham số `accept_schema` của manifest trên lần triển khai đích, lớp D.

### 4.7 `backup` (lớp B; chạy không người trông)

Kế hoạch: bị từ chối khi bản cài đang tạm khóa (§3.6); dung lượng (§5.8); bậc cổng 1 chỉ được phép cho sao lưu trực tuyến (online), tức khi ứng dụng vẫn chạy (lớp `scheduled` hoặc `manual` và mọi kho dữ liệu đều `online_backup`). Các phần ghi dữ liệu cần dừng là những dịch vụ ghi dữ liệu được thấy đang chạy, nên `consistency` của bản sao lưu là đúng những gì lần chụp gặp: bản ghi và các container phải khớp nhau (một phần ghi dữ liệu đang chạy trong khi bản ghi nói bản cài không chạy, hoặc không có container trong khi bản ghi nói đang chạy, sẽ dẫn tới từ chối `changed-outside`, §4.15); một phần ghi dữ liệu có container bị dừng trong khi bản ghi nói đang chạy, như `stop <i> <service>` để lại (§4.11), thì không bị dừng và cũng không được khởi động lại. Quy tắc giữ lại cần bậc cổng 2: trên một nền tảng chưa được chứng nhận hoặc chưa được kiểm thử, `backup --prune` từ chối (mã thoát 2), còn `scheduled backup` vẫn sao lưu nhưng không chạy bước dọn bản sao lưu cũ theo quy tắc giữ lại (không xóa bản nào), kèm cảnh báo được ghi lại `retention skipped: …`; cũng vậy khi có một bản sao lưu mang ngày giờ sau đồng hồ của máy (§5.6).

Các bước: [`Stop` các phần ghi dữ liệu đang chạy khi kho dữ liệu không phải `online_backup`, hoặc lớp là `pre-change` hay `final`] → `Up` các dịch vụ dữ liệu và chờ sẵn sàng (F16) → **đọc schema**: với một `[schema]` dựa trên tác vụ, chạy tác vụ schema như một bước đọc nháp (Planned M2: M1 từ chối chụp bản sao lưu cho ứng dụng như vậy, `not-in-this-release`); với một `[schema]` dựa trên probe, lấy giá trị mà bản ghi triển khai lưu từ lúc kích hoạt (schema của một ứng dụng đang chạy chỉ đổi qua một lần triển khai); kết quả được đưa vào `{schema.expected}` và `bundle.json` → một vùng chuẩn bị (stage) trong `ops/<seq>/stage/`, thuộc uid thực tế của tác vụ → các bước `backup.steps` của manifest theo thứ tự (stdout được ghi thẳng vào các tệp trong vùng chuẩn bị với phép kiểm tra `nonempty`, stdin được đọc thẳng từ các tệp trong vùng chuẩn bị, các mount đã khai báo) → quy tắc phần dữ liệu (payload): đúng một mục ở cấp trên cùng, bằng `backup.payload` khi có khai báo; các mục ẩn do Ingat tạo được xóa → `bundle.json`, `SHA256SUMS` và `meta/` → chép vào `<backups>/<i>/.incoming-<id>/`, fsync, đổi tên thành `<id>/` → bản ghi trong danh mục → `VerifyBundle` → [khởi động lại các phần ghi dữ liệu] → [quy tắc giữ lại, với `scheduled backup` hoặc `--prune`] → `Record`.

Một bản sao lưu đã niêm phong mà kiểm tra thất bại vẫn được giữ ở chỗ đã công bố, với một bản ghi `verified` mang `ok: false` (mã thoát 3); quy tắc giữ lại không bao giờ coi nó là bản sao lưu đã kiểm tra mới nhất. Khi khóa đang bận, lệnh thoát với mã 2 và bộ lập lịch gửi thư cho chủ sở hữu.

### 4.8 `verify <i> <bundle>|--latest` (lớp B)

Tính lại mã băm của thư mục đã niêm phong (mọi tệp trong danh sách phải là tệp thường với số liên kết là 1; liên kết, tệp đặc biệt và tệp không có trong danh sách đều bị từ chối), so mã băm của bản sao lưu với bản ghi trong danh mục (phát hiện việc ai đó sửa trộm trong thư mục sao lưu), tạo một bản sao đầu vào riêng, chạy các tác vụ `backup.verify` của bản phát hành đã ghi của bản sao lưu (ảnh chụp manifest, các image và tệp của lần triển khai đó, như lần thử khôi phục vẫn làm: một bản sao lưu của bản phát hành cũ hơn không bao giờ được kiểm tra bằng tác vụ của bản phát hành hiện tại), rồi thêm một bản ghi `verified`. Một lần lệch mã băm hoặc một tác vụ kiểm tra thất bại sẽ thêm bản ghi đó với `ok: false` (F10).

### 4.9 `verify … --restore-test` (thử khôi phục (drill); lớp B; chạy không người trông)

Kế hoạch: dung lượng (§5.8); `[drill] min_free_memory` so với `/proc/meminfo`; bậc cổng 2; một dải mạng con còn trống trong pool (trình thực thi cấp nó lúc bắt đầu: [ARCHITECTURE.md](ARCHITECTURE.vi.md) §7.4); các image của bản phát hành đã ghi của bản sao lưu phải có sẵn (Ingat không xóa image nào trước M3; thiếu một image sẽ bị từ chối `missing-image`, và `prepare` bản phát hành đó sẽ kéo lại image theo digest đã ghi).

Các bước:

1. `CreateGeneration t<seq>` cho mỗi kho dữ liệu (`purpose=drill`).
2. Dự án cách ly `<i>--t<seq>`: override với các kho dữ liệu `t<seq>`, mạng nội bộ (ứng dụng không được dựa vào tuyến mặc định (default route) ở đó: ứng dụng nào cần thì có một chốt chặn, như dịch vụ web của ứng dụng PostgreSQL; việc có tuyến mặc định hay không khác nhau tùy Engine, thử nghiệm sớm (spike) S12), không mở cổng ra ngoài, dải mạng con lấy từ pool, các chốt chặn của manifest, các bí mật **dùng một lần** được sinh ra trong `ops/<seq>/secrets/` (luôn luôn; khi không khai báo bí mật nào, tham số `secrets_dir` vẫn có thư mục, chỉ chứa một tệp rỗng `.keep`; một lần thử khôi phục không bao giờ thấy bí mật của bản cài), và một tệp biến môi trường ứng dụng riêng cho lần chạy cách ly, không có các khóa cần chủ sở hữu duyệt hay khóa bí mật.
3. `Up` các dịch vụ `restore.start`, chờ kho dữ liệu sẵn sàng.
4. `restore.steps` (các tệp của bản sao lưu được đưa vào qua stdin, hoặc gắn một bản sao đầu vào riêng).
5. Các tác vụ `restore.post`; `restore.checks` và `drill.checks` (mỗi cái phải là `ok`); các tác vụ `drill.record` (được ghi lại, cho phép có phát hiện).
6. Khi có `drill.activate`: `Up` các nhóm kích hoạt bên trong dự án cách ly; các probe `exec` và `health` được chạy, các probe `http` được ghi là không áp dụng khi cách ly.
7. Bằng chứng (thời gian, kết quả, phiên bản) → một bản ghi `restore-tested` gắn với mã băm của bản sao lưu; một lần thử khôi phục thất bại thêm bản ghi đó với `ok: false` (F10).
8. `Teardown`: `compose down` dự án cách ly (không bao giờ kèm `-v`, được chứng minh lại: §3.3), rồi xóa theo danh sách đóng các volume và thư mục `t<seq>` của chính nó, mỗi mục được chứng minh lại (`purpose=drill`, `op=<seq>`, không còn ai dùng), rồi xóa mục cấp phát dải mạng con của nó. Việc dọn dẹp chạy cả khi thất bại.

Bản cài đang chạy thật vẫn tiếp tục chạy (quyết định của chủ sở hữu OD-6).

### 4.10 `restore <i> --bundle <id> --reason TEXT`

Lớp D với một bản cài đã có dữ liệu, lớp C với một bản cài chưa từng được triển khai. Kế hoạch in `created_at` và `freeze_at` của bản sao lưu, lần triển khai hiện tại, và việc ghi có được mở lại sau bản sao lưu hay không; những lần ghi đó vẫn nằm trong vùng dữ liệu được giữ lại.

Một lần khôi phục luôn chạy trong chính bản phát hành của bản sao lưu và để bản cài ở bản phát hành đó; sau đó một lần `deploy` bình thường đưa nó đi tiếp. Khôi phục trong bản phát hành hiện tại sẽ cần một bước migrate bên trong lần khôi phục, và ở v1 chưa có ứng dụng nào cần; điều này sẽ quay lại qua một ADR khi có ứng dụng cần.

Các bước:

1. Kiểm tra mã băm của bản sao lưu với danh mục; image đích = bản phát hành đã ghi của bản sao lưu.
2. `CreateGeneration g<N+1>` cho mỗi kho dữ liệu.
3. Dự án cách ly `<i>--r<seq>` với các bí mật **thật** của bản cài (một volume PostgreSQL mới khởi tạo với mật khẩu owner riêng của bản cài; tác vụ tạo role của ứng dụng đặt mật khẩu cho các role của bản cài), các chốt chặn, mạng nội bộ, không cổng, dải mạng con lấy từ pool, các kho dữ liệu gắn với `g<N+1>`.
4. `Up` `restore.start` và chờ sẵn sàng → `restore.steps` → `restore.post` → `restore.checks` → khi có `restore.activate`, khởi động các nhóm kích hoạt trong môi trường cách ly và chờ các probe `exec`/`health` của chúng.
5. `Teardown` dự án cách ly (chỉ container và mạng) và xóa mục cấp phát dải mạng con của nó; `g<N+1>` được giữ lại.
6. `SnapshotLogs`; `Stop` dự án đang chạy thật (các phần ghi dữ liệu trước) — đảo ngược được. Một bản cài chưa từng được triển khai thì không có gì để dừng.
7. `SwitchGeneration gN → g<N+1>` (từ chỗ chưa có gì sang `g1` với một bản cài chưa từng được triển khai) — đảo ngược được cho tới khi một phần ghi dữ liệu khởi động.
8. `Record` lần triển khai khôi phục N+1 **trước khi khởi động nó** (ghi một lần `deployments/<N+1>.json`: id bản sao lưu gốc, bản phát hành và các image của bản sao lưu) và đặt nó làm lần triển khai hiện tại trong `record.json` (kèm `adopted_from` với một phần dữ liệu tiếp quản được nhập vào, §4.16), để bản cài luôn có một lần triển khai đã ghi khớp với vùng dữ liệu hiện tại của nó.
9. `Up` dự án chạy thật với các image của lần triển khai đích (cộng `[rollback] env` khi lần khôi phục là một lần quay về bản cũ), các probe, kiểm tra nhanh.
10. `Record` kết quả trong `record.json`; với ứng dụng có `after_restore = "held"`, đặt `held_since` và in `restore_notice` của manifest.

Một thất bại trước bước 8 sẽ chuyển vùng dữ liệu về lại nếu bước 7 đã chạy, để nguyên vùng dữ liệu cũ và khởi động lại dự án chạy thật, nếu có (failed-unchanged; một bản cài chưa từng được triển khai vẫn ở `registered`). Bước 8 là **điểm không quay lại**: một thất bại ở bước 8 hoặc 9 sẽ dừng các phần ghi dữ liệu (failed-frozen) với con trỏ ở `g<N+1>` và lần triển khai N+1 là hiện tại, để `start <i> --unfreeze` (lớp D), `deploy <i> <ref>` và một lần `restore` lặp lại đều có một lần triển khai để bắt đầu; `next` in ra `ingat restore <i> --bundle <id> --reason …` (lớp D, vì giờ bản cài đã có dữ liệu). **Planned M3:** `restore <i> --generation <store>=g<N>` chuyển về lại. Một phép khẳng định trong CI kiểm tra rằng không phần ghi dữ liệu chạy thật nào gắn một vùng dữ liệu chưa được chuyển sang, và không dự án cách ly nào gắn vùng dữ liệu đang dùng thật.

Một bản sao lưu `imported` (được nhập vào, §5.9, §4.16) chỉ được chấp nhận sau khi nó đã `restore-tested` trên máy này. Với một phần dữ liệu tiếp quản được nhập vào, mà `bundle.json` của nó không ghi schema, lần triển khai khôi phục ghi schema theo cách lần cài đầu tiên làm (§4.3).

Ứng dụng PostgreSQL (được mô phỏng bằng `fx-pg`): `pg_restore --single-transaction --exit-on-error --no-owner --no-privileges` vào cơ sở dữ liệu mới, rồi các tác vụ tạo role và cấp quyền của nó (các bản dump của nó không mang theo quyền), rồi phép đọc phiên bản schema của nó phải báo là mới nhất và các phép kiểm tra tính nhất quán của nó phải đạt. Ứng dụng SQLite (được mô phỏng bằng `fx-lite`): một lệnh khôi phục chạy một lần của ứng dụng, từ đầu vào là bản sao lưu vào vùng dữ liệu trống; ứng dụng kiểm tra mã băm, tính toàn vẹn và schema, rồi bật chế độ tạm dừng gửi ra ngoài của nó.

### 4.11 `start`, `stop`, `restart` (lớp C)

`start` dùng các ID image đã ghim của lần triển khai đã ghi, và từ chối khi đang tạm khóa (`--unfreeze` là lớp D), khi có một thao tác đang mở, khi mã engine không khớp, khi có xung đột `exclusive_environments`, hoặc, với một `[schema]` dựa trên tác vụ, khi tác vụ schema (chạy như một bước nháp) cho thấy có một lần cập nhật dữ liệu đang chờ (Planned M2: M1 từ chối `start` và `restart` của ứng dụng như vậy, `not-in-this-release`). Phép kiểm tra schema không áp dụng cho ứng dụng `migrates_on_start` có schema dựa trên probe: schema của nó không đọc được trước khi khởi động, và `start` chạy đúng các ID image đã ghim từng chạy trên dữ liệu này. `stop` dừng các phần ghi dữ liệu trước, rồi phần còn lại theo thứ tự kích hoạt ngược. `stop` và `restart` cũng từ chối khi đang tạm khóa (một bản cài đã dừng về sau có thể được khởi động mà không qua bước gỡ tạm khóa). Một lệnh dừng một phần `stop <i> <service>…` không ghi thay đổi trạng thái nào. `restart` chụp log trước (Planned M2, cùng với `SnapshotLogs`).

### 4.12 `task <i> <name>`

Chỉ các tác vụ đã khai báo. Tác vụ đọc là lớp B; tác vụ `app-write` và `data` là thao tác một bước lớp C. Một tác vụ có `operator = false`, có `image` khác `current`, hoặc có mount `stage`, `bundle` hay `generation:<store>` (những thứ này chỉ tồn tại bên trong các thao tác dùng chúng) bị từ chối (`not-operator`). Các lệnh kiểu xem trước rồi xác nhận của chính ứng dụng được mô tả thành hai tác vụ: một tác vụ xem trước (không có đối số xác nhận của ứng dụng; `read` khi phần xem trước của ứng dụng không ghi gì, nếu không thì `app-write` và `idempotent`) và một tác vụ `app-write` riêng có đối số xác nhận (các lệnh gửi ra ngoài của ứng dụng SQLite, [MANIFEST_SPEC.md](MANIFEST_SPEC.vi.md) §11). Ingat không gắn hai lần gọi này với nhau; lệnh xác nhận của chính ứng dụng tự kiểm tra lại trạng thái. `expect` của một tác vụ (§4 của [MANIFEST_SPEC.md](MANIFEST_SPEC.vi.md)) quyết định một lần thoát `ok` có thật sự là `ok` hay không. Các loại đầu ra: `terminal` được hiển thị và không bao giờ bị thu lại (tác vụ chạy trong container CLI, [ARCHITECTURE.md](ARCHITECTURE.vi.md) §4.3); `record` được lưu với quyền 0600 trong `reports/` hoặc trong các tệp kết quả của thao tác; `json` được phân tích, giới hạn kích thước và che bí mật.

### 4.13 `prune`

- `--bundles` (lớp B; M1): quy tắc giữ lại (§5.6). Mặc định chỉ chạy thử, không xóa gì (dry-run); `--apply` và `scheduled backup` thì thực sự áp dụng.
- `--generations` (lớp D; Planned M3): liệt kê các vùng dữ liệu không phải hiện tại và cũ hơn khoảng thời gian ghim; không bao giờ là vùng hiện tại hay vùng ngay trước đó.
- `--images` (lớp D, phạm vi cả máy; Planned M3): chỉ các image trong sổ ghi image không còn được tham chiếu bởi một lần triển khai được giữ lại hay một bản sao lưu được ghim.

### 4.14 `purge <i>` (lớp D; Planned M3)

1. `CaptureBundle(final)` khi các phần ghi dữ liệu đã dừng.
2. Thử khôi phục đúng bản sao lưu đó cho tới khi đạt `restore-tested`; bỏ qua với bản cài `disposable`, và màn hình xác nhận nói rõ điều đó.
3. Một kế hoạch xóa theo danh sách đóng: container, mạng, volume của các vùng dữ liệu, các vùng dữ liệu dạng thư mục gắn trực tiếp, phần còn sót của các lần chạy cách ly, các image mang tag Ingat không còn được tham chiếu.
4. Gõ mã thử thách `PURGE <i> <4 chars>`.
5. `Delete` từng mục, có chứng minh lại.
6. Trạng thái `purged`; các bản sao lưu, bản ghi, kết quả kiểm tra, bí mật và khóa đều được giữ lại.

### 4.15 Chẩn đoán

- `status [--json]` đọc các bản ghi trước (lần triển khai, các vùng dữ liệu, thao tác đang mở và bước cuối của nó, `held_since`, bản sao lưu gần nhất và tuổi các lần kiểm tra của nó, tuổi của lần thử khôi phục gần nhất), rồi tới dữ liệu Docker đang chạy, được báo riêng khi không lấy được: trạng thái dịch vụ, tình trạng sức khỏe (health), số lần khởi động lại, độ lệch ID image và mã băm cấu hình, các đối tượng không thuộc Ingat, dung lượng trống trên mọi thư mục gốc và thư mục gốc của Docker, bậc cổng. Mã cần chú ý (attention) `changed-outside` nghĩa là container, mạng hoặc volume vùng dữ liệu của một bản cài đã triển khai bị mất hoặc khác với lần triển khai đã ghi (ví dụ sau khi dùng "Clean" của Container Manager: [ARCHITECTURE.md](ARCHITECTURE.vi.md) §11.2); nó có trong `status` từ M1. Mã cần chú ý `uncertified` nghĩa là không có chứng nhận nào khớp với bản build nền tảng của máy ([ARCHITECTURE.md](ARCHITECTURE.vi.md) §3.6): các lệnh cần bậc cổng 2, kể cả các lần thử khôi phục theo lịch, sẽ từ chối cho tới khi `selftest --host` chứng nhận bản build đó. Mọi câu trả lời JSON đều mang `next`, đúng lệnh cần chạy. Mã thoát 5 khi cần chú ý.
  - Các mã cần chú ý, quan trọng nhất trước (`next` của câu trả lời phục vụ mã đầu tiên có mặt): `daemon-unreachable`, `engine-mismatch`, `invalid-config` (một bản cài mà `instance.toml` hoặc các bản ghi của nó không đọc được; `status` không kèm tên và `scheduled status` vẫn báo các bản cài khác; `next` là `status <i>`, lệnh này nêu tên các lỗi), `open-operation`, `frozen` (`next` là cách đi tiếp khi đi được, §3.6, nếu không thì `history <i>`), `last-op-failed` và `needs-review` (`next` là những gì kết quả của thao tác đó đã in, hoặc `history <i>`), `changed-outside`, `foreign`, `drift`, `held`, `unverified-bundle`, `backup-old`, `restore-test-old`, `uncertified`.
  - Một thao tác đang mở được tính là đang chạy, không phải cần chú ý, khi một trình thực thi của bản cài đang chạy nó (trình thực thi của máy với một bản cài selftest) hoặc, với một tác vụ terminal do CLI chạy, khi container tác vụ của nó đang chạy dở một bước. Một container tác vụ còn sống lâu hơn trình thực thi của nó làm `next` thành đúng lệnh `docker stop` cho nó. `history` hiện một thao tác đang mở là đang chạy, tạm dừng hoặc bị ngắt.
  - Một container bị dừng bởi một lệnh `stop` đã hoàn tất cho dịch vụ của nó (thời điểm kết thúc mà Docker ghi nằm trong thao tác đó) không bị tính là `changed-outside`.
- `doctor <i>` thêm các phép kiểm tra policy và cổng phiên bản (kể cả chứng nhận), hình dạng tệp bí mật, trùng cổng và dải mạng con, chủ sở hữu và quyền của thư mục gốc, địa chỉ proxy thực tế quan sát được so với giá trị trusted-proxy đã cấu hình khi manifest có nêu giá trị đó (như manifest của ứng dụng SQLite; chưa có trong mã M1: chưa có khóa manifest nào nêu giá trị đó), và các khả năng có sẵn hay không (ví dụ "restore: not applicable" với một trang web không lưu dữ liệu).
- `scheduled status` (lớp B, chạy không người trông, M1-M2; được thay bằng `check` ở M3) tính cùng các mã cần chú ý như `status` cho mọi bản cài và so tập mã đó với `host/attention.json`, tệp duy nhất nó ghi. Nó thoát với mã 5 và in các mã mới xuất hiện và các mã đã hết chỉ khi tập mã thay đổi kể từ lần chạy trước; nếu không, nó thoát với mã 0 và không in gì. Nhờ vậy một tình trạng kéo dài (một ứng dụng `held` sau khi khôi phục, một lần thử khôi phục đã cũ) chỉ gửi thư cho chủ sở hữu một lần, không phải mỗi lần chạy.
- **Planned M3:** `check` (bộ giám sát chạy theo lịch, ngang bằng với script giám sát riêng của ứng dụng PostgreSQL): tình trạng sức khỏe container và số lần khởi động lại tăng thêm, điều kiện sẵn sàng kiểm qua cổng mở ra ngoài, hạn chứng chỉ của URL công khai, các ngưỡng đĩa, tuổi bản sao lưu và tuổi lần thử khôi phục, các thao tác đang mở; trạng thái chống báo trùng nằm trong `instances/<i>/monitor.json`, tệp duy nhất mà `check` ghi.

### 4.16 Tiếp quản (adoption) — nhận quản lý một bản triển khai không do Ingat tạo (Planned M4)

Tiếp quản đưa một bản triển khai ứng dụng không do Ingat tạo (khởi động bằng tay, từ Container Manager hoặc bằng một công cụ khác) vào một bản cài Ingat mới, **từ một phần dữ liệu (payload) do lệnh sao lưu riêng của ứng dụng tạo ra**. Ingat không bao giờ động tới một đối tượng không thuộc Ingat: nó không dừng, khởi động, chạy lệnh bên trong (exec), gắn (mount), gắn lại nhãn, khôi phục vào hay xóa đối tượng đó (F8; ADR-0024). Docker không đổi được nhãn của một đối tượng đã có, nên một đối tượng không thuộc Ingat không bao giờ trở thành của Ingat; dữ liệu của nó chuyển vào một bản cài mới qua một bản sao lưu được nhập vào và lần khôi phục ở §4.10. Việc tiếp quản không đọc nhãn, bản ghi hay bản sao lưu nào của công cụ triển khai nội bộ trước đây (ADR-0001).

**Điều kiện trước.** Ứng dụng có một `ingat.toml` ở một bản phát hành mà các tác vụ `restore` của nó đọc được những gì lệnh sao lưu của bản triển khai không thuộc Ingat ghi ra, thường là bản phát hành mà dự án đó đang chạy. Việc tiếp quản không bao giờ tự cập nhật dữ liệu: lần khôi phục chạy trong bản phát hành đã nêu, và lệnh khôi phục cùng các phép kiểm tra của ứng dụng sẽ từ chối một schema mà bản phát hành đó không chạy được (mục 2 của danh sách kiểm tra khi đưa ứng dụng vào, [ARCHITECTURE.md](ARCHITECTURE.vi.md) §11.3). Một ứng dụng không có lệnh sao lưu mà chủ sở hữu chạy được trên bản triển khai không thuộc Ingat thì dùng một nhà cung cấp dữ liệu (provider) ([ADR-0031](adr/0031-data-providers.vi.md), Planned): hướng dẫn thao tác (runbook) in ra dòng lệnh `backup` của provider để chạy bằng tay, tạo ra phần dữ liệu; chỉ một loại cơ sở dữ liệu (engine) chưa có provider nào mới phải chờ cách `cold` đang được hoãn lại (§5.1).

**Hướng dẫn thao tác** (hướng dẫn vận hành, M4). Các bước bên ngoài Ingat dùng công cụ riêng của dự án không thuộc Ingat và là việc của chủ sở hữu; agent vận hành không bao giờ chạy chúng (`docker` nằm trong quy tắc chặn của chúng: quyết định của chủ sở hữu OD-10).

1. **Bản cài mới.** Viết `instance.toml` cho một bản cài mới với tên, cổng và dải mạng con riêng (dự án không thuộc Ingat giữ những thứ của nó cho tới khi chủ sở hữu xóa nó), đặt các bí mật đã khai báo bằng `secret set`, chạy `init <i> --config <file> --ref <release>` và `prepare <i> <release>`. Các tham số đặt tên cho dữ liệu bên trong kho dữ liệu (ví dụ tên cơ sở dữ liệu hay role owner) lấy đúng giá trị của dự án không thuộc Ingat, từ cấu hình riêng của nó. Không lấy gì từ các bí mật của dự án không thuộc Ingat.
2. **Cho dừng ghi và xuất dữ liệu, bên ngoài Ingat.** Bỏ chính sách tự khởi động lại của các container không thuộc Ingat (`docker update --restart no <ids>`), để một lần khởi động lại daemon không thể chạy chúng lại (live restore mặc định tắt, và tắt trong Container Manager 24.0.2-1706); một container có `HostConfig.AutoRemove` sẽ bị xóa ngay khi dừng, cùng với các volume không tên của nó, nên hãy kiểm tra trước khi dừng. Dừng các phần ghi dữ liệu của dự án không thuộc Ingat, chạy lệnh sao lưu riêng của ứng dụng trên dự án đó (các dịch vụ dữ liệu của nó có thể vẫn chạy để làm việc này) và đặt kết quả vào một thư mục mới dưới `INGAT_ROOT/inbox/`, rồi dừng phần còn lại của dự án (`docker compose -p <project> stop`; không bao giờ `down -v`, không bao giờ dùng các thao tác dự án trên giao diện đồ họa của nhà cung cấp như "Clean" hay "Delete" của Container Manager).
3. **Nhập vào.** `ingat import --payload <dir> --into <i> --release <ref> --from <name> [--id <bundle-id>] --reason TEXT` (lớp B, xem bên dưới).
4. **Thử khôi phục.** `ingat verify <i> <bundle> --restore-test`; `restore` từ chối một bản sao lưu được nhập vào mà chưa `restore-tested` (§4.10).
5. **Chuyển sang (cut-over).** `ingat restore <i> --bundle <bundle> --reason TEXT` (lớp C, vì `<i>` chưa từng được triển khai: §4.10); chủ sở hữu trỏ reverse proxy sang cổng của bản cài mới ngay sau khi lệnh hoàn tất. Thời gian ngừng phục vụ kéo dài từ lúc dừng các phần ghi dữ liệu ở bước 2 tới thời điểm này.
6. **Nghiệm thu.** Khi bản cài mới đã chạy và bản sao lưu theo lịch đầu tiên của nó đã được kiểm tra, chủ sở hữu tự tay xóa dự án không thuộc Ingat (chỉ xóa các volume của nó khi chủ sở hữu chọn làm vậy).

**`import --payload`** (lớp B: nó chỉ ghi một bản sao lưu mới). Kế hoạch (thuần túy; một lời từ chối không để lại dấu vết, F2): `<i>` đang `registered` (chưa từng được triển khai) và đã có bản chờ triển khai cho `<ref>`; `<dir>` nằm dưới `INGAT_ROOT/inbox/` và chứa đúng một mục ở cấp trên cùng; id của bản sao lưu là tên mục đó, trừ khi `--id` đưa ra một id, phải khớp quy tắc đặt id (§5.4) và chưa được dùng; khi manifest khai báo `backup.payload`, giá trị của nó khi điền với id đó phải bằng tên mục (quy tắc phần dữ liệu ở §4.7); dung lượng như với một lần sao lưu (§5.8). Các bước: chép `<dir>` vào vùng chuẩn bị bằng cách duyệt không đi theo liên kết (liên kết, tệp đặc biệt và đường dẫn không an toàn bị từ chối) → `bundle.json` với `class = "pre-change"`, `consistency = "external"` (được tạo bên ngoài Ingat; tính nhất quán của nó là lời xác nhận của chủ sở hữu), không có `freeze_at` và không có `schema`, `deployment = {seq: none, release and commit of <ref>, images: the prepared candidate's IDs}` và `origin = {adopted_from: <name>}` (§5.3) → `SHA256SUMS` và `meta/` → niêm phong, công bố và ghi vào danh mục với loại `imported` (§5.9) → `VerifyBundle`, với các tác vụ `backup.verify` chạy trên image của bản chờ triển khai. `--from <name>` là nhãn chủ sở hữu đặt cho dự án không thuộc Ingat; Ingat ghi lại nó và không bao giờ xem xét dự án đó. Trong lần thử khôi phục và lần khôi phục, `{image.<service>}`, `{release}` và `{commit}` được điền theo lần triển khai đã ghi của bản sao lưu, tức bản chờ triển khai ([MANIFEST_SPEC.md](MANIFEST_SPEC.vi.md) §3). Lần triển khai khôi phục ghi bản sao lưu này là bản sao lưu trước thay đổi đi kèm của nó, nên quy tắc giữ lại giữ nó chừng nào lần triển khai đó còn là hiện tại hoặc ngay trước đó (§5.6).

**Quay lại trước khi nghiệm thu.** `ingat stop <i>`; rồi, bằng công cụ riêng của dự án không thuộc Ingat, đặt lại chính sách tự khởi động lại của nó và khởi động nó; trỏ lại reverse proxy. Những lần ghi trong bản cài mới vẫn nằm trong vùng dữ liệu của nó và không được mang về. Chỉ khởi động dự án không thuộc Ingat sau khi các phần ghi dữ liệu của bản cài mới đã dừng: hai bản đang chạy của cùng một ứng dụng nghĩa là có hai hàng đợi gửi ra ngoài, với một ứng dụng có tác động ra bên ngoài. Đi tiếp lên một bản phát hành mới hơn là một lần `deploy` bình thường với bản sao lưu trước thay đổi của riêng nó.

**Các quy tắc an toàn liên quan.** F2 (`import` và kế hoạch của nó không để lại dấu vết khi bị từ chối), F6 và F7 (một bản sao lưu đã niêm phong, đã kiểm tra và đã thử khôi phục có sẵn trước khi chuyển sang; lần khôi phục đổ dữ liệu vào vùng dữ liệu đầu tiên của bản cài mới), F8 (không đối tượng nào không thuộc Ingat bị động tới; bộ kiểm thử tiếp quản trong CI kiểm tra các sự kiện Docker: [ARCHITECTURE.md](ARCHITECTURE.vi.md) §10.3), F13 (lần thử khôi phục và phần dựng tạm khi khôi phục được cách ly như thường lệ).

## 5. Dữ liệu

### 5.1 Các cách sao lưu (strategy)

| Cách | Dùng khi | Trạng thái |
|---|---|---|
| `tasks` | Các bước tác vụ riêng của ứng dụng, chạy bên trong chính image của ứng dụng (cả hai ứng dụng tham chiếu). Ingat lo phần làm dừng ghi, vùng chuẩn bị, tính mã băm, niêm phong, kiểm tra, giữ lại và thử khôi phục. | Decided, M1 (ứng dụng SQLite), M2 (ứng dụng PostgreSQL) |
| `none` | Ứng dụng không lưu dữ liệu; sao lưu, kiểm tra, khôi phục và thử khôi phục đều báo "not applicable" (không áp dụng). Quay về bản cũ nghĩa là dùng digest hoặc commit trước đó. | Decided, M1 |
| `provider` | Ứng dụng khai báo các tập dữ liệu của mình (`[data.<name>]`); các image provider đi kèm công cụ, được ghim theo digest, sao lưu, kiểm tra và khôi phục chúng như những tác vụ bình thường ([ADR-0031](adr/0031-data-providers.vi.md)). | Planned (sau M2, [ROADMAP.md](ROADMAP.vi.md) §5) |
| `cold` | Dừng dự án, chép các kho dữ liệu đã khai báo bằng một container trợ giúp, chỉ khôi phục với cùng ID image dữ liệu. | Deferred (hoãn lại); điều kiện để làm (được ADR-0031 thu hẹp): một loại cơ sở dữ liệu (engine) mà thư mục dữ liệu của chính nó phải được chép nguyên trạng vì chưa có provider nào cho nó và không thể dump ở dạng logic, hoặc một sự cố mà cả các hook của ứng dụng lẫn provider đều không giữ được dữ liệu |

### 5.2 Kho dữ liệu và vùng dữ liệu

- Mỗi kho dữ liệu gắn với vùng dữ liệu `g<N>`: một volume `<i>_<store>_g<N>` do Ingat tạo và gắn nhãn, được khai báo `external: true` trong override, hoặc một thư mục `INGAT_ROOT/data/<i>/<store>/g<N>/` với chủ sở hữu và quyền theo manifest và một tệp đánh dấu `g<N>.json` nằm bên cạnh.
- Các lần thử khôi phục dùng vùng dữ liệu `t<seq>`. Các lần khôi phục, quay dữ liệu về bản cũ và chuyển sang image dữ liệu mới tạo `g<N+1>`. Vùng dữ liệu trước đó được giữ cho tới `prune --generations` (Planned M3).
- Đây là cách làm mà cả hai ứng dụng tham chiếu vốn đã tự làm bằng tay: ứng dụng PostgreSQL khôi phục vào một cơ sở dữ liệu mới; ứng dụng SQLite khôi phục vào một thư mục trống.
- Một lần khôi phục thất bại không làm mất gì, và điều này thay thế cho loại "emergency capture" (chụp khẩn cấp) trước đây.

### 5.3 Định dạng bản sao lưu (thư mục, định dạng 1)

```
<backups>/<instance>/<bundle-id>/
  bundle.json      format, id, class, instance, app, environment, lineage, created_at, freeze_at, consistency
                   (writers-stopped | online-app | external), deployment {seq, release, commit, images {service: id},
                   manifest_sha256, model_sha256}, schema {expected, actual}, stores {name: generation},
                   payload {entry, files [{path, size, sha256}], total_bytes}, meta [...],
                   tool {version, engine, api, cli, compose, arch, os}, host,
                   origin (optional, M4: {adopted_from: <name>} for an imported adoption payload, §4.16)
  SHA256SUMS       bundle.json and every payload and meta file
  payload/<entry>/ what the app's backup tasks produced: exactly one top-level entry
  meta/            ingat.toml and the Compose files of that commit, deployment.json (non-secret)
```

**Mã băm bản sao lưu (bundle hash)** là SHA-256 của `SHA256SUMS`. Nó được ghi trong `instances/<i>/catalog/<id>.json` (chỉ root đọc được), nên một bản sao lưu bị tráo hay bị sửa trong thư mục sao lưu sẽ bị phát hiện mỗi lần dùng. Các bản ghi kiểm tra nằm trong `instances/<i>/verifications/<bundle-id>.json`, mỗi bản sao lưu một tệp JSON Lines chỉ được ghi thêm, nằm ngoài thư mục đã niêm phong, để mã băm không bị vòng lặp (không phải tự chứa chính nó). Một bản sao lưu không bao giờ chứa bí mật, tệp biến môi trường hay mô hình Compose đã giải. Một phần dữ liệu tiếp quản được nhập vào (M4, §4.16) ghi `consistency = "external"`, không có `freeze_at` và không có `schema`, và một `deployment` không có `seq` mà bản phát hành, commit và ID image là của bản chờ triển khai đã chuẩn bị, để `{image.<service>}` điền ID của bản chờ triển khai trong lần thử khôi phục và lần khôi phục của nó.

### 5.4 Id của bản sao lưu

Id lấy từ mẫu `[backup.naming]` của manifest cho lớp sao lưu đó (mặc định `{bundle.stamp}-{class}`; một phần dữ liệu tiếp quản được nhập vào dùng tên mục của nó hoặc `--id`, §4.16), phải khớp `^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`, và không được trùng với một bản sao lưu đã có. Khi id đã bị dùng nhưng mẫu sẽ cho ra một id khác sau một giây (nó dùng `{bundle.stamp}`), lần chụp chờ một lần, chưa tới một giây, cho tới giây đó rồi tạo lại id: mỗi bản cài chỉ chạy một thao tác tại một thời điểm, nên thứ đang giữ id đó là lần chụp trước của bản cài, bắt đầu trong cùng giây. Việc lập kế hoạch chỉ từ chối (`bundle-exists`) khi id của giây kế tiếp cũng đã bị dùng hoặc id không đổi theo thời gian; một bản sao lưu đã có không bao giờ bị thay thế. Các lớp: `scheduled`, `manual`, `pre-change`, `final`. Cách hoạt động không bao giờ phụ thuộc vào chữ trong id; lớp được ghi trong `bundle.json` và danh mục. Một ứng dụng có quy tắc đặt tên bản sao lưu riêng sẽ ánh xạ các lớp vào quy tắc đó trong manifest của nó: quy tắc của ứng dụng PostgreSQL là một mốc thời gian UTC theo sau bởi một hậu tố hằng ngày, thủ công hoặc trước phát hành có nhãn (nhãn là bắt buộc với trước phát hành và bị cấm trong các trường hợp khác), nên lệnh công bố bản sao lưu riêng của nó và phép kiểm tra bản sao lưu trước thay đổi trong migrate của nó chấp nhận bản sao lưu của Ingat mà không cần sửa gì (`fx-pg`: `backup-publish --name {bundle.id}`, `migrate --pre-change-backup {bundle.payload}`, [MANIFEST_SPEC.md](MANIFEST_SPEC.vi.md) §8). Một bài kiểm thử tuân thủ (conformance, M3) kiểm tra phép ánh xạ này và `{freeze_at}` với cơ chế chặn theo thời điểm dừng ghi thật trong migrate của ứng dụng.

### 5.5 Các mức kiểm tra

| Mức | Ý nghĩa | Cần cho |
|---|---|---|
| `verified` | mã băm của bản sao lưu khớp với danh mục và mọi tác vụ `backup.verify` đều trả về `ok` (một ứng dụng không có lệnh kiểm tra chỉ đọc, như ứng dụng SQLite hiện nay, chỉ được kiểm tra bằng mã băm) | một lần triển khai có thay đổi dữ liệu (bản sao lưu trước thay đổi của chính nó) |
| `restore-tested` | lần thử khôi phục (§4.9) đã đạt các bước khôi phục, các tác vụ sau khôi phục, các phép kiểm tra và các probe | gỡ bỏ hoàn toàn một bản cài không phải loại dùng xong bỏ (disposable); `status` đánh dấu một bản cũ hơn `restore_test_max_age_days` |

Chỉ những bản ghi gắn với mã băm bản sao lưu trong danh mục mới được tính, và ở mỗi mức thì bản ghi mới nhất quyết định: một lần kiểm tra hay thử khôi phục thất bại sẽ thêm `ok: false`, nên một bản sao lưu có bản ghi mới nhất ở một mức là thất bại sẽ không còn được tính ở mức đó (`status` hiện `unverified-bundle`).

### 5.6 Quy tắc giữ lại (`prune --bundles`)

Các khung thời gian theo lịch, tính theo UTC: `keep_daily`, `keep_weekly`, `keep_monthly` (dùng từ ngữ của restic). Luôn được giữ: bản sao lưu mới nhất, bản sao lưu đã kiểm tra mới nhất, bản sao lưu đã thử khôi phục mới nhất, các bản sao lưu trước thay đổi chưa quá `pin_pre_change_days`, các bản sao lưu trước thay đổi đi kèm lần triển khai hiện tại hoặc lần trước đó, bản sao lưu trước thay đổi của lần cập nhật đã làm bản cài tạm khóa, chừng nào bản cài còn tạm khóa (cách đi tiếp và việc khôi phục của nó cần bản này, §3.6), và mọi thứ mà một thao tác đang mở tham chiếu tới. Quy tắc giữ lại cần bậc cổng 2 ([ARCHITECTURE.md](ARCHITECTURE.vi.md) §3.6; một `scheduled backup` không chạy bước dọn này (không xóa bản nào) và ghi lại một cảnh báo, §4.7). Một bản sao lưu bị xóa được đổi tên sang một bên, xóa đi và được ghi lại bằng một bản ghi đánh dấu đã xóa (tombstone) `catalog/<id>.pruned.json`. Quy tắc giữ lại chỉ tác động lên các bản sao lưu có trong danh mục; nó từ chối cả lần chạy khi có bất kỳ bản sao lưu nào mang ngày giờ sau đồng hồ của máy (một quy tắc lấy từ hướng dẫn sao lưu riêng của ứng dụng SQLite; khi đó một `scheduled backup` vẫn sao lưu nhưng không chạy bước dọn bản sao lưu cũ (không xóa bản nào), kèm cảnh báo được ghi lại, §4.7); nó không bao giờ xóa một bản sao lưu không kiểm tra được; việc xóa là một kế hoạch đóng gồm các mục trong danh mục. Việc dọn bớt phía ứng dụng (cả hai ứng dụng tham chiếu đều có cách riêng) không bao giờ được dùng khi chạy dưới Ingat.

### 5.7 Tác động ra bên ngoài và chốt chặn

Mỗi lần chạy cách ly (thử khôi phục, dựng tạm khi khôi phục) áp các `[holds.<service>]` của manifest thành các giá trị ghi đè `environment` của Compose, vốn được ưu tiên hơn giá trị trong `env_file`; bỏ các khóa biến môi trường ứng dụng cần chủ sở hữu duyệt và các khóa bí mật khỏi tệp biến môi trường cách ly; biến mọi mạng thành mạng nội bộ; không mở cổng nào ra ngoài. Với ứng dụng SQLite (được mô phỏng bằng `fx-lite`), các chốt chặn đặt chế độ gửi ra ngoài của nó thành chỉ giữ lại (capture) và tắt bộ chạy việc nền; công tắc gửi thật và thông tin đăng nhập SMTP của nó bị bỏ đi, nên dù chốt chặn có lỗi cũng không thể tới được SMTP. Chốt chặn cũng lo những gì cần để khởi động trong môi trường cách ly: dịch vụ web của ứng dụng PostgreSQL (được mô phỏng bằng `fx-pg`) lấy địa chỉ proxy tin cậy từ tuyến mặc định IPv4 và sẽ thoát nếu không có tuyến đó, mà một mạng nội bộ có thể không có (điều này khác nhau tùy Engine: thử nghiệm sớm S12), nên chốt chặn của nó đặt địa chỉ đó thành `127.0.0.1` (địa chỉ IPv4 nào cũng được: trong môi trường cách ly không có lưu lượng proxy nào).

Ứng dụng có `side_effects.kind = "outbound"`:

- chỉ khôi phục qua tác vụ khôi phục riêng của chúng (`restore_via_app = true`): lần khôi phục của ứng dụng SQLite bật chế độ tạm dừng gửi ra ngoài với lý do `restored` và giữ lại các thư đang chờ gửi;
- sau một lần khôi phục chạy thật, bản cài hiện `held_since` cho tới khi tác vụ `clear_hold` (với ứng dụng SQLite là lệnh có xác nhận để gửi ra ngoài trở lại) thành công; `restore_notice` chỉ tới các tác vụ đối soát của ứng dụng;
- dự án đang chạy thật được dừng trước khi chuyển vùng dữ liệu, nên không bao giờ có hai hàng đợi production cùng chạy trên cùng dữ liệu;
- `single_active` (Planned M4, cùng với khôi phục vào một bản cài mới): các phần ghi dữ liệu của hai bản cài không cách ly thuộc cùng một dòng dữ liệu không bao giờ chạy cùng lúc.

### 5.8 Dung lượng

Được kiểm tra trước mọi tác động, **gộp theo hệ thống tệp** (`st_dev` của `INGAT_BACKUPS`, `INGAT_ROOT` và volume `ingat-probe` đại diện cho thư mục gốc của Docker) rồi cộng lại: cả ba thường nằm trên cùng một hệ thống tệp (hệ thống tệp gốc của một máy Linux nhỏ; `/volume1` trên DSM), nên vùng chuẩn bị, bản đã công bố, bản sao đầu vào của một lần thử khôi phục và kho dữ liệu nó khôi phục ra đều cộng dồn trên một hệ thống tệp. Theo từng thao tác:

| Thao tác | Cần (S = kích thước phần dữ liệu dự kiến) |
|---|---|
| sao lưu (backup) | S cho vùng chuẩn bị (`INGAT_ROOT`) + S cho bản đã công bố (`INGAT_BACKUPS`) + tối thiểu 1 GiB trống trên mỗi hệ thống tệp |
| thử khôi phục, khôi phục | S cho bản sao đầu vào (`INGAT_ROOT`) + 2 × S cho kho dữ liệu được khôi phục (nơi đặt vùng dữ liệu: `INGAT_ROOT` với kho dữ liệu dạng thư mục gắn trực tiếp, thư mục gốc của Docker với volume) + tối thiểu 1 GiB trống trên mỗi hệ thống tệp |
| nhập một phần dữ liệu tiếp quản (M4) | như sao lưu, với S đo từ thư mục phần dữ liệu |
| chuẩn bị (kéo image), cài lần đầu | tối thiểu 2 GiB trống trên thư mục gốc của Docker |

Một thư mục gốc hoặc điểm gắn của probe không tồn tại thì không đo được và dẫn tới từ chối (`cannot-measure`, mã thoát 2). S là phần dữ liệu mới nhất trong danh mục của bản cài. Trước bản sao lưu đầu tiên, S được ước tính từ kích thước kho dữ liệu đo được: kích thước của vùng dữ liệu dạng thư mục gắn trực tiếp đo bằng cách duyệt không đi theo liên kết, hoặc kích thước volume lấy từ `docker system df -v` (chỉ đọc). Ingat không bao giờ xóa gì để lấy chỗ trống.

### 5.9 Bản sao ở nơi khác (ngoài máy)

Giao cho công cụ của nền tảng, bên ngoài Ingat. Sau các lần sao lưu ban đêm, một bản sao của `INGAT_BACKUPS` được gửi tới một nơi nhận ngoài máy do chủ sở hữu quản lý, được mã hóa ngay ở phía máy gửi (client-side). Trên máy Linux, đó là restic (với một kho từ xa chỉ cho ghi thêm và một khóa khôi phục cất ngoại tuyến; `forget`/`prune` chạy từ một máy khách (client) tin cậy) hoặc borg, cả hai đều mã hóa ở phía máy gửi, hoặc rsync tới một nơi nhận có mã hóa. Trên DSM, một tác vụ Hyper Backup bảo vệ thư mục chia sẻ `ingat-backups` với mã hóa phía máy gửi, tới một NAS khác hoặc một nơi nhận ở địa điểm khác. Việc phục hồi không bao giờ dựa vào snapshot (trên DSM, Snapshot Replication chỉ có trên volume Btrfs: [ARCHITECTURE.md](ARCHITECTURE.vi.md) §11.2), nên các bản sao lưu đã niêm phong cộng với bản sao này là toàn bộ đường phục hồi. Mọi thứ mang về từ ngoài máy chỉ được đưa vào lại qua `import` (Planned M4): chép, kiểm tra mọi tệp trong danh sách, từ chối liên kết, tệp đặc biệt, tệp không có trong danh sách và đường dẫn không an toàn, ghi vào danh mục với loại `imported`, rồi thử khôi phục trước khi dùng thật.

## 6. Mã thoát (mọi lệnh)

| Mã | Ý nghĩa |
|---|---|
| 0 | hoàn tất |
| 1 | bị từ chối; không có gì thay đổi (đầu vào không hợp lệ, policy, kế hoạch đã cũ, dung lượng, trạng thái không đúng) |
| 2 | không chạy được; không có gì thay đổi (không kết nối được daemon, khóa đang bận, có thao tác đang mở, nền tảng chưa được kiểm thử cho bậc cổng này, lỗi cách dùng như tên bản cài, đối số hay đường dẫn sai, không có terminal để gõ duyệt, kế hoạch đã hết hạn, một thư mục gốc không đo được) |
| 3 | thất bại sau khi đã có tác động, kể cả một lần hủy sau khi đã có tác động (mã `cancelled`); bản cài ở một trạng thái an toàn đã được ghi lại (`failed-unchanged` hoặc `failed-frozen`); `status` hiện `next` |
| 4 | một thao tác cần chú ý (paused: tạm dừng, interrupted: bị ngắt, unknown: không rõ kết quả, needs-review: cần xem xét); hãy chạy `ingat status <i>` |
| 5 | có phát hiện (status, verify hoặc các tác vụ kiểm tra chỉ đọc tìm thấy điều gì đó; không có gì thất bại) |
| 130 | bị hủy trước khi có tác động |

Mỗi kết quả JSON còn mang một chuỗi `code` ổn định dành cho máy đọc và `next`; một lời từ chối hay thất bại còn mang thông báo của nó, kể cả khi trình thực thi là bên quyết định.

## 7. Việc chạy theo lịch

Bộ lập lịch của máy chạy mọi việc bằng tài khoản root, không có terminal, và gửi thư cho chủ sở hữu khi một việc thoát với mã khác 0: systemd timer (mỗi việc một service oneshot, kèm một unit `OnFailure=`), cron làm phương án dự phòng (`MAILTO`), hoặc bộ lập lịch riêng của nền tảng (trên DSM là Task Scheduler với một script do người dùng định nghĩa, người dùng root, "send run details by email only when the script terminates abnormally" (chỉ gửi chi tiết lần chạy qua email khi script kết thúc bất thường)). Mỗi mục gọi script khởi động (wrapper) bằng đường dẫn tuyệt đối. `scheduled` từ chối các kế hoạch lớp C và D và các tác vụ terminal (`unattended`, mã thoát 2), in một dòng khi thành công (nêu tên một thao tác mà nó đã tự động bỏ dở) và một bản tóm tắt đã che bí mật ra stderr khi thất bại. Lịch ví dụ cho một máy có một bản cài thử nghiệm `lite-test` của ứng dụng SQLite và một bản cài staging `pg-staging` của ứng dụng PostgreSQL, dưới thư mục gốc mặc định (trên DSM, script khởi động là `/volume1/ingat/bin/ingat`):

| Khi nào | Lệnh |
|---|---|
| hằng ngày 01:30 | `/srv/ingat/bin/ingat scheduled backup lite-test` (lớp `scheduled`, rồi quy tắc giữ lại) |
| hằng ngày 02:00 | `/srv/ingat/bin/ingat scheduled backup pg-staging` |
| hằng ngày 03:00 | Bản sao ra ngoài máy của `INGAT_BACKUPS` bằng công cụ của nền tảng (restic, borg hoặc rsync trên Linux; một tác vụ Hyper Backup trên DSM), bên ngoài Ingat (§5.9) |
| hằng ngày 04:00 | `/srv/ingat/bin/ingat scheduled task pg-staging check` (chỉ đọc; báo cáo với quyền 0600; mã thoát 5 khi có phát hiện) |
| Chủ nhật 05:00 | `/srv/ingat/bin/ingat scheduled verify lite-test --latest --restore-test` |
| Chủ nhật 06:00 | `/srv/ingat/bin/ingat scheduled verify pg-staging --latest --restore-test` |
| mỗi giờ | `/srv/ingat/bin/ingat scheduled status` (mã thoát 5 và gửi thư chỉ khi tập mã cần chú ý thay đổi, §4.15); được thay bằng `check` ở M3 |
| theo khoảng thời gian mà `report enroll` đã ghi (`interval_minutes`, mặc định 15), chỉ sau khi đăng ký | `/srv/ingat/bin/ingat scheduled report` (Planned, [ADR-0033](adr/0033-commercial-boundary-report-and-hosted-service.vi.md)) |

Giờ chạy các việc phải cách xa nhau: khi khóa đang bận, lệnh thoát với mã 2 và được gửi thư báo, không bao giờ xếp hàng chờ. Sau một lần cập nhật nền tảng (trên máy Linux là mỗi lần khởi động lại vào một kernel mới), lần thử khôi phục thoát với mã 2 và được gửi thư báo cho tới khi `selftest --host` chứng nhận bản build mới, trong khi các lần sao lưu vẫn tiếp tục nhưng không chạy bước dọn bản sao lưu cũ theo quy tắc giữ lại (không xóa bản nào), kèm một cảnh báo được ghi lại ([ARCHITECTURE.md](ARCHITECTURE.vi.md) §3.6). **Planned M3:** `ingat schedule render <i> --systemd` in ra các unit oneshot, các timer (`Persistent=true`) và một unit `OnFailure=`; `--cron` in ra các dòng crontab làm phương án dự phòng; `--dsm` in ra các mục Task Scheduler cần tạo.
