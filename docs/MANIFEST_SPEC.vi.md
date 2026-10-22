# Manifest ứng dụng và tệp cấu hình bản cài của Ingat

[English](MANIFEST_SPEC.md) · **Tiếng Việt** (bản dịch; bản tiếng Anh là bản chuẩn)

> **Nói đơn giản.** Một ứng dụng làm việc với Ingat qua hai tệp TOML nhỏ. **Manifest ứng dụng** (app manifest) `ingat.toml` do nhà phát triển ứng dụng viết và nằm trong kho mã (repository) của ứng dụng: tệp này mô tả các dịch vụ, dữ liệu, tác vụ (task) và các phép kiểm tra của ứng dụng, và không chứa giá trị nào của một máy cụ thể. **Tệp bản cài** (instance file) `instance.toml` do người chạy ứng dụng viết và nằm lại trên máy đó: tên, nguồn, cổng, địa chỉ, quy tắc giữ lại bản sao lưu. Tài liệu này định nghĩa mọi khóa (key) của cả hai tệp và kết thúc bằng các ví dụ đầy đủ. Nhà phát triển ứng dụng: hãy bắt đầu với §1, [danh sách việc cần làm khi đưa một ứng dụng vào](ARCHITECTURE.vi.md#113-quy-tắc-tổng-quát) (onboarding checklist), và ví dụ gần nhất với ứng dụng của bạn (§11 cho một container dùng SQLite, §8 cho nhiều dịch vụ dùng PostgreSQL, §13 cho một trang web không lưu dữ liệu).

**Tìm gì ở đâu**

| Phần | Nói đơn giản |
|---|---|
| [§1 Hai tệp, hai người phụ trách](#1-hai-tệp-hai-người-phụ-trách) | Ai viết tệp nào, tệp nằm ở đâu, và khi nào Ingat đọc nó |
| [§2 Cấu trúc manifest ứng dụng, phiên bản 1](#2-cấu-trúc-manifest-ứng-dụng-phiên-bản-1) | Mọi khóa của `ingat.toml` |
| [§3 Bộ biến dùng trong mẫu](#3-bộ-biến-dùng-trong-mẫu-danh-sách-đóng) | Các biến giữ chỗ bạn có thể dùng trong giá trị, ví dụ `{instance}` hoặc `{commit}` |
| [§4 Tác vụ](#4-tác-vụ-tasksname) | Các lệnh riêng của ứng dụng (sao lưu, khôi phục, kiểm tra, cập nhật dữ liệu…) và cách Ingat đọc mã thoát của chúng |
| [§5 Phép kiểm tra sẵn sàng (probe) và kiểm tra nhanh sau khi chạy (smoke)](#5-phép-kiểm-tra-sẵn-sàng-probesname-và-smoke) | Cách Ingat biết ứng dụng đã sẵn sàng và đang chạy đúng |
| [§6 Cấu trúc tệp cấu hình bản cài, phiên bản 1](#6-cấu-trúc-tệp-cấu-hình-bản-cài-phiên-bản-1) | Mọi khóa của `instance.toml`, và cách `ingat validate` kiểm tra cả hai tệp |
| [§7 Các ứng dụng thử đứng sau các ví dụ](#7-các-ứng-dụng-thử-đứng-sau-các-ví-dụ) | Các ứng dụng thử (fixture) mà các ví dụ mô phỏng theo |
| §8-§13 | Ví dụ đầy đủ: [`fx-pg`](#8-ví-dụ-manifest-ứng-dụng-fx-pg-mẫu-của-ứng-dụng-postgresql-một-tệp-dùng-cho-cả-staging-lẫn-production) cùng các bản cài [chạy thử (staging)](#9-ví-dụ-bản-cài-staging-của-fx-pg-ingat_rootinstancespg-staginginstancetoml) và [chạy thật (production)](#10-ví-dụ-bản-cài-production-của-fx-pg-ingat_rootinstancespg-prodinstancetoml), [`fx-lite`](#11-ví-dụ-manifest-ứng-dụng-fx-lite-mẫu-của-ứng-dụng-sqlite) cùng [bản cài thử nghiệm](#12-ví-dụ-bản-cài-thử-nghiệm-của-fx-lite-ingat_rootinstanceslite-testinstancetoml), và một [trang web không lưu dữ liệu](#13-ví-dụ-trang-web-chung-không-lưu-dữ-liệu-mẫu-fx-web-các-tệp-nằm-trong-ingat_rootinstancessiteapp) |

Trạng thái: **Decided**, ở dạng bản nháp của cấu trúc (schema) manifest phiên bản 1 và cấu trúc bản cài (instance) phiên bản 1; được chốt cố định tại điều kiện hoàn thành mốc (exit gate) M2. Bộ đọc tệp (parser), bộ kiểm tra hợp lệ (validator) và lệnh `validate` của M1 đã có trong mã, và các bài kiểm thử của chúng đạt trong CI. Toàn bộ cấu trúc đọc được từ v0.1, nhưng M1 chỉ áp dụng các khóa mà ứng dụng SQLite (the SQLite consumer) và các ứng dụng thử dùng (§11, §12), và phần lập kế hoạch của M1 từ chối những gì M1 chưa chạy được (`not-in-this-release`: nguồn kiểu image, dịch vụ dữ liệu (data service), kho dữ liệu kiểu volume, `log_snapshot`, các kiểm tra trước khi triển khai (prechecks), kiểm tra sau (postchecks) và mức nền (baseline), tác vụ `exec`, luồng `file:` và `bundle:`, một tham số `subnet` để hệ thống tự cấp, và `[schema]` dựa trên tác vụ tại `start`, `restart` và mỗi lần tạo bản sao lưu (bundle)); các khóa mà chỉ ứng dụng PostgreSQL (the PostgreSQL consumer) cần (§8-§10) được áp dụng từ M2 và vẫn có thể thay đổi trong lúc đưa ứng dụng này vào, trước khi chốt (`ROADMAP.md` §3). Các khóa được đánh dấu **Planned Mx** đọc được từ v1 nhưng chỉ được áp dụng từ mốc đó. Các ví dụ ở §8-§13 là dạng ứng dụng thử của các đầu vào nghiệm thu (§7): chúng, và các manifest thật của các ứng dụng mà chúng mô phỏng, phải qua kiểm tra hợp lệ và chạy được mà không cần sửa tại điều kiện hoàn thành mốc M2, và một thay đổi phần lõi (core) mà chúng buộc phải có sau khi chốt cấu trúc sẽ được ghi lại là một thất bại về tính tổng quát (generality failure) (ADR-0021).

## 1. Hai tệp, hai người phụ trách

| Tệp | Nằm ở | Người phụ trách | Chứa | Được đọc |
|---|---|---|---|---|
| **Manifest ứng dụng** `ingat.toml` | Thư mục gốc của kho mã ứng dụng (đường dẫn có thể đặt riêng cho từng bản cài) | Nhà phát triển ứng dụng | Thông tin về cấu trúc của ứng dụng: các tệp Compose, cách nhận diện bản phát hành, vai trò của các dịch vụ, kho dữ liệu (store), tham số (chỉ kiểu), thông tin bí mật (secret, chỉ khai báo), các khóa biến môi trường của ứng dụng (app-env), phép kiểm tra sẵn sàng, kiểm tra nhanh, tác vụ, cách sao lưu/khôi phục, chốt chặn (hold), tác động ra bên ngoài (side effects), các bước cài đặt | Từ đúng commit đang được triển khai (`git show <sha>:ingat.toml`), được lưu một bản chụp cho mỗi lần triển khai. Khi quay về bản cũ (rollback), Ingat tự động dùng đúng manifest tương ứng. |
| **Tệp cấu hình bản cài** `instance.toml` | `INGAT_ROOT/instances/<name>/` (chủ là root, quyền 0600) | Chủ sở hữu | Các giá trị: tên, ứng dụng, môi trường, nguồn, giá trị tham số, giá trị biến môi trường của ứng dụng, quy tắc giữ lại, giám sát | Được lưu một bản chụp cho mỗi thao tác; Ingat không bao giờ ghi đè lên tệp này |

Các ứng dụng lấy nguồn từ image (trang web không lưu dữ liệu, không có kho mã) giữ `ingat.toml` và tệp Compose của chúng trong `INGAT_ROOT/instances/<name>/app/`, và Ingat tính mã băm của chúng cho mỗi lần triển khai.

Manifest ứng dụng nằm trong kho mã riêng của ứng dụng, kho này có thể công khai, nên manifest phải chung chung: tác vụ, dịch vụ, phép kiểm tra sẵn sàng và khai báo tham số, không bao giờ có giá trị của máy. Mọi thứ riêng của máy (cổng, mạng con (subnet), URL, tên máy, thông tin đăng nhập kho mã, secret) chỉ nằm trong `instance.toml`, các tệp secret và khóa triển khai (deploy key) trên máy, cùng với bản sao mã hóa ngoại tuyến của chủ sở hữu (quyết định của chủ sở hữu OD-9).

Cả hai tệp đều là TOML 1.0, được đọc bằng `tomllib`; khóa lạ bị từ chối ở mọi cấp. Từ "manifest" nghĩa là manifest ứng dụng của Ingat (cố ý không gọi là "profile": các ứng dụng dùng `profiles:` của Compose cho những dịch vụ chỉ dùng để chạy tác vụ, như `fx-pg` làm với `profiles: [ops]`); `profiles:` của chính Compose được gọi là "Compose profiles". Manifest sao lưu riêng của một ứng dụng (một tệp mà ứng dụng ghi vào thư mục sao lưu của chính nó, như `backup-publish` của `fx-pg` làm) luôn được gọi đầy đủ như vậy.

## 2. Cấu trúc manifest ứng dụng, phiên bản 1

### 2.1 Cấp trên cùng và `[source]`, `[compose]`

| Khóa | Kiểu | Ý nghĩa |
|---|---|---|
| `manifest` | số nguyên (int) | Phiên bản cấu trúc, `1` |
| `app` | chuỗi (string) | Mã ứng dụng (app id), `^[a-z][a-z0-9-]{1,30}$` |
| `requires_ingat` | chuỗi | Khoảng phiên bản Ingat cần có, ví dụ `">=0.1,<1"` |
| `exclusive_environments` | danh sách (list) | Một bản cài có môi trường nằm trong danh sách này sẽ từ chối triển khai hoặc khởi động khi đã có một bản cài khác của ứng dụng này được đăng ký trên máy, và ngược lại với `init` (`LIFECYCLE.md` §4.3) |
| `[source] kind` | `"git"` \| `"image"` | Dựng (build) từ một commit chính xác, hoặc triển khai theo digest của image |
| `[source] release` | `"tag"` \| `"commit"` | Cái gì dùng để đặt tên một bản phát hành (chỉ với git) |
| `[source] tag_pattern` | regex | Các tag được phép khi `release = "tag"`; như mọi regex trong cả hai tệp, nó phải biên dịch được ngay lúc đọc tệp |
| `[source] images` | bảng (table) dịch vụ → tham số | Chỉ cho nguồn kiểu image: tham số `image` nào cấp image cho dịch vụ nào |
| `[compose] files` | danh sách | Các tệp Compose dùng lúc chạy, theo thứ tự gộp |
| `[compose] build_files` | danh sách | Các tệp chỉ dùng khi dựng image ngay trên máy; không dùng tới khi image của ứng dụng được dựng trong CI của ứng dụng ([ADR-0026](adr/0026-app-images-built-in-app-ci.vi.md)) |
| `[compose] build_services` | danh sách | Các dịch vụ có image do CI riêng của ứng dụng dựng và phát hành (quyết định của chủ sở hữu OD-11, [ADR-0026](adr/0026-app-images-built-in-app-ci.vi.md)). `prepare` kéo (pull) mỗi image một lần theo tham chiếu mà dịch vụ Compose của nó ghi (đã điền tham số, ví dụ một tham số `template` `"ghcr.io/<owner>/<app>:{commit}"`) và ghim image đó theo ID và digest của kho image (repository digest); với các dịch vụ này `expect_labels` là bắt buộc và phải gắn với `{commit}`, và mỗi mục phải là tên một dịch vụ Compose (nếu không, phép kiểm tra nhãn của nó sẽ không bao giờ chạy) |
| `[compose] build_env` | bảng | Các biến chỉ dùng khi dựng trên máy (có điền mẫu); không dùng tới khi image của ứng dụng được dựng trong CI của ứng dụng |
| `[compose] expect_labels` | bảng | Các nhãn image phải bằng đúng các giá trị đã điền mẫu, nếu không image bị từ chối (để chứng minh nguồn gốc của các tag được kéo về); bắt buộc với `build_services`, với ít nhất một giá trị chứa `{commit}` |

### 2.2 `[params]`

Mọi biến Compose không có giá trị mặc định của Compose (`${VAR}`, `${VAR:?…}`, và `${VAR:-}`, có giá trị mặc định rỗng mà Compose báo giống như không có mặc định) đều phải được khai báo; các biến có giá trị mặc định không rỗng của Compose (`${VAR:-x}`) có thể được khai báo để bản cài đặt được giá trị cho chúng, nếu không chúng không bao giờ được đặt. Tên tham số bắt đầu bằng `COMPOSE_` hoặc `DOCKER_` bị từ chối (Compose sẽ đọc chúng như thiết lập của chính nó: `ARCHITECTURE.md` §9.5), cả trong `[params]` lẫn trong `params` của một bước `[[install]]`. Mỗi mục là một bảng:

| `kind` (mặc định `string`) | Giá trị lấy từ | Khóa thêm |
|---|---|---|
| `string` | `[params]` của bản cài, nếu không có thì `default` | `required` (bản cài phải đặt giá trị; bị từ chối nếu đi cùng `default` hoặc `optional`), `default`, `optional` (không đặt thì giữ mặc định của Compose), `pattern` |
| `template` | manifest, được điền cho mỗi lần gọi | `value` (mẫu, §3) |
| `port` | giá trị của bản cài, hoặc được cấp từ dải cổng của máy `20000-29999`; không trùng trên mỗi máy; chỉ mở trên `127.0.0.1` | — |
| `subnet` | giá trị của bản cài, hoặc một dải `/24` được cấp; không trùng trên mỗi máy; các lần chạy cách ly nhận giá trị từ dải dành sẵn | — |
| `secrets_dir` | `INGAT_ROOT/instances/<i>/secrets` | — |
| `env_file` | tệp biến môi trường của ứng dụng đã được tạo ra cho lần triển khai (0600) | — |
| `store` | thư mục vùng dữ liệu (generation) hiện tại của một kho dữ liệu kiểu bind | `store` |
| `task_dir` | thư mục tạm (stage) hoặc bản sao đầu vào riêng của tác vụ gắn nó; nếu không thì là thư mục rỗng `placeholder/` | — |
| `accept_schema` | rỗng, trừ khi `rollback --accept-schema` đặt nó (Planned M3) | — |
| `image` | digest đã ghim từ `deploy --image` (nguồn kiểu image) | `service` |

### 2.3 `[secrets.<name>]` và `[app_env]`

`[secrets.<name>]`: `generate = "alnum32"` (32 ký tự `[A-Za-z0-9]`, được tạo một lần lúc `init`, không có hai secret nào giống nhau trong cùng một bản cài), `mode` (quyền của tệp, mặc định `"0400"`). Tệp là `<secrets_dir>/<name>`; tệp Compose tham chiếu tới nó qua tham số `secrets_dir`.

`[app_env]` mô tả một `env_file` mà Ingat tạo ra từ các giá trị `[app_env]` và secret của bản cài:

| Khóa | Ý nghĩa |
|---|---|
| `param` | Tham số `env_file` mà tệp Compose dùng |
| `forbidden` | Các khóa do image cố định và không bản cài nào được đặt (chúng sẽ chuyển dữ liệu đi nơi khác hoặc thay đổi danh tính của ứng dụng lúc chạy) |
| `[app_env.keys] <KEY>` | `required` (bản cài phải đặt; bị từ chối nếu đi cùng `default` hoặc `tool_managed`), `default`, `allowed` (danh sách), `pattern`, `secret` (giá trị được đặt bằng `ingat secret set`, lưu trong `secrets/env/<KEY>`), `owner_gated` (một thay đổi làm kế hoạch thành lớp duyệt D (class D); bị bỏ khỏi các lần chạy cách ly), `tool_managed` (chỉ được đặt bởi chốt chặn và `[rollback] env`) |

Các khóa không được khai báo trong `[app_env]` của bản cài bị từ chối. Giá trị được ghi trong dấu nháy đơn; giá trị chứa `'`, ký tự xuống dòng hoặc NUL bị từ chối.

### 2.4 `[stores.<name>]` và `[services]`

| Khóa của kho | Ý nghĩa |
|---|---|
| `kind` | `"volume"` (một volume Compose ở cấp trên cùng) hoặc `"bind"` (một thư mục trên máy) |
| `volume` | Khóa volume của Compose (`kind = "volume"`) |
| `param` | Tham số `store` dùng làm nguồn bind (`kind = "bind"`) |
| `service` | Dịch vụ dữ liệu phục vụ kho này (không bắt buộc với kho bind mà các phần ghi dữ liệu (writers: những phần của ứng dụng thay đổi dữ liệu) dùng trực tiếp) |
| `ready` | Phép kiểm tra sẵn sàng chứng minh kho đã sẵn sàng (bắt buộc khi đặt `service`; là phép kiểm tra `exec` hoặc `health`, vì phép kiểm tra `http` không chạy trong các project cách ly) |
| `owner`, `mode` | Chủ (`uid:gid`) và quyền của các vùng dữ liệu bind mới |
| `local_only` | Từ chối đường dẫn vùng dữ liệu không nằm trên hệ thống tệp cục bộ |
| `online_backup` | Các tác vụ sao lưu của ứng dụng vẫn cho kết quả nhất quán khi các phần ghi dữ liệu đang chạy, nên các lần sao lưu theo lịch và thủ công để các phần ghi dữ liệu tiếp tục chạy (bản sao lưu trước thay đổi và bản sao lưu cuối cùng luôn dừng các phần ghi dữ liệu) |

Mọi volume có tên trong mô hình đã gộp phải là một kho dữ liệu. `[services]`: `data` (khởi động trước; không bao giờ bị tạo lại bởi một thay đổi chỉ về mã), `writers` (bị dừng cho mọi bước thay đổi dữ liệu), `stateless`, `log_snapshot` (các dịch vụ có log, giới hạn kích thước, được lưu lại trước khi tạo lại hoặc dừng). Mọi dịch vụ chạy lâu dài nằm ngoài Compose profiles phải có đúng một vai trò; các dịch vụ nằm trong Compose profiles chỉ dùng để chạy tác vụ.

### 2.5 `[schema]`

`task` (một tác vụ đọc in ra JSON) hoặc `probe` (một phép kiểm tra sẵn sàng có JSON chứa các trường này), cùng với `expected` và `actual` (đường dẫn trong JSON, nối bằng dấu chấm), và `migrates_on_start` (bool). Phiên bản cấu trúc dữ liệu (schema) được ghi lại trong mọi lần triển khai và mọi bản sao lưu; nó được dùng bởi cổng kiểm tra khi quay về bản cũ (rollback gate) và bởi `observe = "schema"`. Khi nào nó được đọc: schema dựa trên tác vụ chạy như một bước nháp (scratch) trước mỗi lần tạo bản sao lưu và trước `start`; schema dựa trên phép kiểm tra được ghi lại kèm thời điểm khi phép kiểm tra đạt lúc kích hoạt, và các bản sao lưu dùng giá trị đã ghi đó (schema của một ứng dụng đang chạy chỉ thay đổi qua một lần triển khai). Kiểm tra lúc `start` không áp dụng cho ứng dụng có `migrates_on_start` với schema dựa trên phép kiểm tra (`LIFECYCLE.md` §4.7, §4.11).

### 2.6 Kích hoạt, kiểm tra nhanh, cài đặt, triển khai

- `[[activate]]`: các nhóm theo thứ tự `{services, wait = [probe…], reopens_writes}`. Có đúng một nhóm có `reopens_writes = true` khi có phần ghi dữ liệu; nhóm đó là điểm không quay lại (forward point) thứ hai và ghi lại `writes_reopened_at`.
- `[[smoke]]`: các phép kiểm tra `http` chỉ đọc, chạy sau mỗi lần kích hoạt trên bản cài đang chạy thật (§5).
- `[[install]]`: các bước cài lần đầu, mỗi bước là một trong `{start = [services], wait, params, log_snapshot}`, `{task = "<name>"}`, `{pause = "<text>", allow_tasks = [...]}`.
- `[deploy]`: `prechecks` (các tác vụ đọc chạy trước khi dừng các phần ghi dữ liệu (freeze), mỗi tác vụ chạy trên bộ image mà tác vụ đó khai báo, `current` hoặc `candidate`; mỗi tác vụ phải `ok`), `migrate` (tác vụ), `postchecks` (các tác vụ đọc chạy sau bước cập nhật dữ liệu (migrate), thường trên bản ứng viên (candidate); mỗi tác vụ phải `ok`), `baseline` (**Planned M3**: các tác vụ đọc trên các image hiện tại, được ghi lại và cho phép có phát hiện (finding), là đầu vào của một kiểm tra sau dạng so sánh; không ứng dụng nào ở M2 dùng nó).

### 2.7 Sao lưu, khôi phục, quay về bản cũ, thử khôi phục

| Bảng | Khóa |
|---|---|
| `[backup]` | `strategy = "tasks" \| "none"` (Planned: `"provider"`, [ADR-0031](adr/0031-data-providers.vi.md), được ngầm hiểu từ `[data.<name>]` khi không có `[backup]`, §2.8), `steps` (các tác vụ theo thứ tự), `verify` (các tác vụ), `payload` (tên mục bắt buộc ở cấp trên cùng của phần dữ liệu; có điền mẫu), `[backup.naming]` (theo từng loại bản sao lưu `scheduled`, `manual`, `pre-change`, `final`; mặc định `"{bundle.stamp}-{class}"`) |
| `[restore]` | `start` (các dịch vụ dữ liệu được khởi động trên vùng dữ liệu mới), `steps`, `post`, `checks` (các tác vụ phải `ok`), `activate` (khởi động các nhóm kích hoạt trong môi trường cách ly và chờ các phép kiểm tra `exec`/`health`). Tác vụ khôi phục luôn chạy trong image của chính bản phát hành mà bản sao lưu thuộc về (`LIFECYCLE.md` §4.10). |
| `[rollback]` | `env` (các giá trị ghi đè biến môi trường cho một lần triển khai quay về bản cũ dựa trên khôi phục; bị bỏ ở lần triển khai kế tiếp) |
| `[drill]` | `checks` (phải `ok`), `record` (được ghi lại, cho phép có phát hiện), `activate`, `min_free_memory`. Lần thử khôi phục (drill) luôn dùng secret dùng một lần rồi bỏ. |
| `[holds.<service>]` | các giá trị ghi đè biến môi trường được áp dụng trong mọi lần chạy cách ly: chốt chặn tác động ra bên ngoài, và các giá trị mà một dịch vụ cần để khởi động khi cách ly (mạng nội bộ không có tuyến mặc định) |
| `[side_effects]` | `kind = "none" \| "outbound"`, `restore_via_app`, `after_restore = "held"`, `clear_hold` (tác vụ), `single_active` (Planned M4), `restore_notice` |

### 2.8 `[data.<name>]` (Planned, ADR-0031)

**Planned** ([ADR-0031](adr/0031-data-providers.vi.md), sau điều kiện hoàn thành mốc M2; là phần chỉ thêm mới trong cấu trúc 1 nếu có trước khi chốt, nếu không thì là thay đổi đầu tiên của cấu trúc 2). Một ứng dụng không có lệnh sao lưu, khôi phục và kiểm tra của riêng nó thì khai báo các bộ dữ liệu của mình, và các image nhà cung cấp (provider) của chính công cụ, được ghim theo digest, cung cấp các lệnh đó như những tác vụ bình thường. Khóa cho mỗi bộ dữ liệu: `provider` (một loại mà `image/providers.lock` liệt kê), `major`, `service` (vai trò `data`), `store`, `database`, `user`, `password = { secret = "<name>" }`, `port`, `databases` (sqlite), `exclude` (các tệp), `ready`, `timeout`; và `[stores.<name>] backup = false` cho một kho bộ đệm (cache) không bao giờ được sao lưu và được tạo lại rỗng. Một manifest khai báo `[data.<name>]` mà không có `[backup]` sẽ nhận `strategy = "provider"` và các bảng `[backup]`, `[restore]` và `[drill]` được tạo ra từ tệp lock; một loại nhận những khóa nào là do mục của loại đó trong tệp lock quy định (`keys`). Ngữ pháp chính xác, giá trị mặc định và quy tắc kiểm tra hợp lệ sẽ được viết ở đây khi phần việc (slice) P1 hoàn thành ([`ROADMAP.md`](ROADMAP.vi.md) §5).

## 3. Bộ biến dùng trong mẫu (danh sách đóng)

| Biến | Giá trị | Dùng được ở đâu |
|---|---|---|
| `{instance}`, `{environment}`, `{host}` | tên bản cài, nhãn môi trường, tên máy | mọi nơi |
| `{operator}`, `{reason}`, `{op.seq}` | `SUDO_USER` hoặc `root`, nội dung `--reason` (hoặc `scheduled <class> backup`), số thứ tự thao tác | argv của mọi tác vụ |
| `{release}`, `{commit}` | bản phát hành (tag hoặc commit) và commit dạng 40 ký tự hex của bộ image mà **lần gọi này chạy** | mọi nơi |
| `{target.release}` | bản phát hành mà một lần triển khai, quay về bản cũ hoặc khôi phục chuyển tới | tác vụ cập nhật dữ liệu (migrate) và tác vụ khôi phục, đặt tên bản sao lưu trước thay đổi |
| `{image.<service>}` | ID image (`sha256:…`) của dịch vụ đó trong bộ image mà lần gọi này chạy; với phần dữ liệu tiếp quản (adoption payload) được nhập vào, đó là lần triển khai được ghi trong bản sao lưu, cũng chính là bản ứng viên đã chuẩn bị (`LIFECYCLE.md` §4.16) | argv của tác vụ |
| `{schema.expected}` | lấy từ lần đọc schema của thao tác này (`[schema]` dựa trên tác vụ), hoặc giá trị mà bản ghi triển khai giữ từ lúc kích hoạt (dựa trên phép kiểm tra) (`LIFECYCLE.md` §4.7) | argv của tác vụ sao lưu |
| `{bundle.id}`, `{bundle.payload}` | mã bản sao lưu; mục duy nhất trong phần dữ liệu (payload) của nó | sao lưu, kiểm tra, khôi phục, cập nhật dữ liệu |
| `{bundle.stamp}` | thời điểm tạo bản sao lưu `YYYYMMDDTHHMMSSZ` (UTC) | đặt tên |
| `{class}` | loại bản sao lưu | đặt tên |
| `{freeze_at}` | thời điểm dừng các phần ghi dữ liệu `YYYY-MM-DDTHH:MM:SSZ` (UTC, tính đến giây) | bước cập nhật dữ liệu khi triển khai |
| `{param.<NAME>}` | giá trị của một tham số đã khai báo | mọi nơi |
| `{arg.<name>}` | một đối số có kiểu của tác vụ | chính tác vụ đó |
| `{input.<name>}` | tên tệp của một đầu vào trong `inbox/` | chính tác vụ đó |

Biến lạ, hoặc biến dùng ngoài chỗ được phép của nó, là lỗi kiểm tra hợp lệ. Không có biểu thức tính toán. Giá trị sau khi điền được kiểm tra để không chứa NUL và ký tự xuống dòng, và chỉ được dùng làm phần tử argv hoặc giá trị biến môi trường, không bao giờ làm văn bản lệnh shell.

## 4. Tác vụ `[tasks.<name>]`

| Khóa | Giá trị | Ý nghĩa |
|---|---|---|
| `service` | dịch vụ Compose | Image, người dùng, mạng, biến môi trường và các điểm gắn (mount) của container mà tác vụ thừa hưởng |
| `mode` | `"run"` \| `"exec"` | `run`: `compose run --rm --no-deps -T --name <instance>-x<seq>-<step>-a<attempt>` kèm nhãn thao tác (không có `-T` khi `stdin = "terminal"`); `argv` thay thế lệnh của dịch vụ (entrypoint giữ nguyên). `exec`: chạy bên trong container dịch vụ đang chạy; `argv` là toàn bộ lệnh. |
| `image` | `"current"` (mặc định) \| `"candidate"` \| `"bundle"` | Lần gọi ghim bộ image đã ghi lại nào |
| `argv` | danh sách mẫu | Các đối số |
| `env` | bảng | Biến môi trường thêm (có điền mẫu) |
| `user` | `"uid:gid"` | Ghi đè người dùng của image; cũng là chủ của các thư mục tạm và các bản sao đầu vào |
| `stdin` | `"file:<stage path>"` \| `"bundle:<path in payload>"` \| `"terminal"` | `file:` và `bundle:` được Ingat truyền vào chính xác từng byte; `terminal` gắn TTY của CLI vào (lệnh từ chối nếu không có TTY) để lời nhắc nhập có thể tắt hiện chữ đang gõ (echo) |
| `stdout` | `"json"` \| `"record"` \| `"terminal"` \| `"file:<stage path>"` | `terminal` không bao giờ được thu lại; `record` được lưu với quyền 0600; `json` và `record` là văn bản được thu lại (có giới hạn kích thước, đã che thông tin bí mật); `file:` giữ chính xác từng byte, không bao giờ bị che hay cắt bớt |
| `nonempty` | bool | stdout dạng `file:` không được rỗng |
| `mounts` | bảng đích → nguồn | Đích là một đường dẫn trong container (`compose run -v`) hoặc tên một tham số `task_dir`/`store`. Nguồn: `"stage"` (thư mục tạm ghi được; đường dẫn stdin/stdout `file:` tính tương đối với nó), `"bundle"` (một bản sao riêng, chỉ đọc, của thư mục `payload/` trong bản sao lưu của thao tác, thuộc người dùng của tác vụ; mục payload là phần tử con duy nhất của nó), `"generation:<store>"` (vùng dữ liệu mới; tham số riêng của kho đó được gắn vào `placeholder/` cho lần gọi này), `"input:<name>"` (một thư mục riêng chỉ đọc chứa một tệp được sao chép từ `inbox/`; `{input.<name>}` là tên tệp đó) |
| `effect` | `"read"` \| `"app-write"` \| `"data"` | Tác động lên dữ liệu của bản cài |
| `idempotent` | bool | Chạy lại an toàn sau một kết quả không rõ |
| `observe` | `"schema"` | Cách xác định một kết quả không rõ |
| `exit` | bảng mã → `ok` \| `finding` \| `refused` \| `failed` \| `unknown` | Mã khác 0 không được khai báo: `failed` với `read`, `unknown` với các loại khác |
| `expect` | `{json = {<dotted path> = value or [any-of…]}}` (ngữ pháp phép kiểm tra của §5, chỉ phần JSON) | Phải đúng trên stdout `json` hoặc `record` đã đọc thì một mã thoát `ok` mới được tính là `ok`; nếu không, kết quả là `failed` (đọc) hoặc `unknown` (ghi). Dùng khi một mã thoát mang hai nghĩa (lệnh xem trước việc gửi ra ngoài của ứng dụng SQLite thoát với mã 2 cả khi xem trước lẫn khi gọi lệnh sai cách; §11). |
| `args` | bảng tên → regex | Đối số có kiểu (`--arg name=value`); mỗi regex phải biên dịch được |
| `clears_hold` | bool | Chạy thành công thì xóa `held_since` |
| `operator` | bool (mặc định `true`) | `false`: chỉ các thao tác mới được chạy nó. `ingat task` cũng từ chối một tác vụ có `image` khác `current`, hoặc có điểm gắn `stage`, `bundle` hoặc `generation:<store>`, vì những thứ này chỉ tồn tại bên trong các thao tác dùng chúng (`not-operator`), nên những tác vụ như vậy khai báo `operator = false` |
| `max_input_bytes` | int | Giới hạn kích thước cho các tệp `input:` |
| `timeout` | khoảng thời gian | Giới hạn cứng; container tác vụ bị dừng và bước trở thành `unknown` (tác động dữ liệu) hoặc `failed` (đọc) |

Quy tắc kiểm tra hợp lệ riêng cho tác vụ: một tác vụ có tác động `app-write` hoặc `data` ở chế độ `exec` chỉ được xuất hiện trong `restore.steps` hoặc `restore.post` (chỉ trong các project cách ly: quy tắc an toàn bắt buộc (safety floor) F15, `LIFECYCLE.md` §1); các tác vụ dùng làm `deploy.migrate` hoặc dùng trong `[[install]]` có tác động `app-write` hoặc `data` phải là `idempotent` hoặc khai báo `observe` (một tác vụ ghi trên bản cài đang chạy thật là một bước tiến không quay lại (forward step): `LIFECYCLE.md` §3.3); mọi tác vụ trong `backup.steps` hoặc `backup.verify` thuộc lớp nháp (scratch) dù tác động của nó là gì, chỉ được ghi vào thư mục tạm và sổ sách sao lưu riêng của ứng dụng, và phải có `idempotent = true` trừ khi tác động của nó là `read` (`LIFECYCLE.md` §3.3); một tác vụ có `stdin` hoặc `stdout = "terminal"` chạy ở tiền cảnh (foreground) trong CLI, ngay trên terminal của bạn và không được dùng cho `scheduled`; `expect` đòi hỏi `stdout = "json"` hoặc `"record"`.

## 5. Phép kiểm tra sẵn sàng `[probes.<name>]` và `[[smoke]]`

| Khóa chỉ loại | Chạy thế nào | Được phép trong lần chạy cách ly |
|---|---|---|
| `health = "<service>"` | trạng thái sức khỏe Docker của container phải là `healthy` | có |
| `exec = "<service>"` với `argv` | bên trong container đang chạy; cần mã thoát 0 (hoặc `expect.exit`), stdout có thể được đọc như JSON | có |
| `http = {port_param, path, method = "GET", headers = {}, body}` | từ container Ingat, qua địa chỉ nội bộ (loopback) của máy tới `127.0.0.1:<port>` (script khởi động (wrapper) dùng `--network host`) | không: được ghi là không áp dụng |

Khóa chung: `expect` = `{status, json = {<dotted path> = value or [any-of…]}, body_contains, header_equals = {<header> = exact value}, header_contains = {<header> = substring}, exit}`, `stable` (phép kiểm tra phải đạt liên tục trong khoảng thời gian này; mặc định `0s`), `interval` (mặc định `2s`), `timeout` (mặc định `60s`). Phép kiểm tra không bao giờ tạo container, nên `status` và `check` giữ được quy tắc không để lại dấu vết (sự kiện `exec` của các phép kiểm tra chỉ đọc đã khai báo là sự kiện Docker duy nhất được phép). Mỗi mục `[[smoke]]` là một phép kiểm tra `http` cộng thêm một `name`; phép kiểm tra danh tính image (ID image của mỗi container đang chạy phải bằng đúng ID đã ghi lại) có sẵn và luôn chạy.

## 6. Cấu trúc tệp cấu hình bản cài, phiên bản 1

### 6.1 Các khóa

| Khóa | Ý nghĩa |
|---|---|
| `instance = 1` | Phiên bản cấu trúc |
| `name` | `^[a-z][a-z0-9]*(-[a-z0-9]+)*$`, tối đa 30 ký tự; cũng là tên project Compose; không được có `--` |
| `app`, `environment` | Mã ứng dụng (phải bằng `app` của manifest); nhãn môi trường `^[a-z][a-z0-9-]{0,31}$` |
| `disposable` | Bản cài có thể bỏ đi; cố định lúc `init`; cho phép việc gỡ bỏ hoàn toàn (purge) bỏ qua bước thử khôi phục (restore-test) (màn hình xác nhận có ghi rõ điều này). Nó không bao giờ nới lỏng việc duyệt: lớp D vẫn chỉ làm được từ một terminal thật. |
| `[source]` | git: `repo` (URL ssh hoặc https; URL `file://` chỉ dành cho kho mã của ứng dụng thử nằm dưới `INGAT_ROOT/cache/fixtures/`, [ADR-0027](adr/0027-local-fixture-repositories.vi.md)), `key` (tên một khóa triển khai trong `INGAT_ROOT/keys/`), `manifest` (đường dẫn, mặc định `ingat.toml`), `accept` (regex không bắt buộc, thu hẹp các ref được phép). Ứng dụng dạng image: `kind = "image"`. |
| `[params]` | Giá trị chỉ cho các tham số đã khai báo; `port` và `subnet` có thể được cố định ở đây hoặc để hệ thống tự cấp |
| `[app_env]` | Giá trị cho các khóa biến môi trường ứng dụng đã khai báo và không phải secret |
| `[backups]` | `keep_daily`, `keep_weekly`, `keep_monthly`, `pin_pre_change_days`, `max_age_hours` (quá hạn thì trạng thái báo cần chú ý (attention)), `restore_test_max_age_days` |
| `[monitor]` | **Planned M3:** `public_url`, `cert_warn_days`, `resolve_to`, `ca_file` |

### 6.2 Kiểm tra hợp lệ (`ingat validate <repo-dir> [--instance <file>]`, không cần mạng, cũng chạy trong CI của ứng dụng)

1. Đọc chặt chẽ cả hai tệp; kiểm tra phiên bản cấu trúc; `requires_ingat` được đáp ứng.
2. Các tệp Compose tồn tại và đạt các quy tắc trên văn bản thô (không có `include`; `extends` chỉ trong cùng một tệp: `ARCHITECTURE.md` §9.5); `compose config --variables` cho thấy mọi biến không có mặc định không rỗng đều được khai báo, và mọi tham số đã khai báo đều được dùng.
3. Mô hình chạy đã gộp, mọi mô hình tác vụ và mô hình cách ly đều được điền với giá trị thử và đạt quy tắc an toàn cho cấu hình Compose (policy) (`ARCHITECTURE.md` §9.5); riêng mô hình cách ly theo các quy tắc của lần chạy cách ly.
4. Mọi volume có tên là một kho dữ liệu; tham số của mọi kho bind là một nguồn bind; mọi cổng được mở đều đến từ một tham số `port` trên `127.0.0.1`.
5. Mọi dịch vụ chạy lâu dài có một vai trò; có phần ghi dữ liệu khi có kho dữ liệu; phần kích hoạt bao gồm mọi dịch vụ chạy lâu dài; có đúng một nhóm `reopens_writes` khi có phần ghi dữ liệu.
6. Mọi tác vụ, phép kiểm tra và dịch vụ được tham chiếu đều tồn tại; các bảng mã thoát hợp lệ; các biến mẫu nằm trong danh sách đóng và đúng chỗ được phép; các quy tắc tác vụ của §4 được tuân thủ.
7. Tham số mà `[app_env]` dùng là một tham số `env_file`; không khai báo khóa bị cấm nào; secret trong tệp Compose ánh xạ tới `[secrets.*]` qua tham số `secrets_dir`.
8. `side_effects.kind = "outbound"` đòi hỏi có chốt chặn, một tác vụ khôi phục và `restore_via_app = true`.

## 7. Các ứng dụng thử đứng sau các ví dụ

Các ví dụ được viết giống như manifest trong kho mã riêng của một ứng dụng, nhưng dùng tên của các ứng dụng thử trong CI (`ARCHITECTURE.md` §10.2); mỗi ứng dụng thật giữ `ingat.toml` của nó trong kho mã riêng. Mỗi ứng dụng thử tái hiện hành vi của ứng dụng mà ví dụ tương ứng dựa vào:

- **`fx-pg`** mô phỏng ứng dụng PostgreSQL (§8-§10). Các dịch vụ chạy lâu dài: `db` (`postgres:16`, dịch vụ dữ liệu), `backend` (phần ghi dữ liệu; image của nó không có entrypoint, chạy với uid `10001` và mang các nhãn OCI về phiên bản (version) và bản sửa (revision)) và `web` (không lưu dữ liệu; nó vẫn phục vụ phần khung giao diện (shell) hiện tại trong lúc `backend` bị dừng). Các dịch vụ chỉ dùng để chạy tác vụ, nằm trong Compose profile `ops`: `migrate` (entrypoint của nó là lệnh cập nhật dữ liệu của ứng dụng), `status` (entrypoint của nó là báo cáo trạng thái của ứng dụng), và `db-roles` và `backup-tools` (entrypoint của chúng là CLI của ứng dụng). Secret dạng tệp đến từ một thư mục secret được gắn vào từ máy (bind-mount), một cổng được mở qua lớp biên (edge), mạng biên có subnet cố định, và mọi dịch vụ đều có tham số bộ nhớ và `cpus`. CLI của ứng dụng thoát với mã 0 (ok hoặc sạch), 1 (có phát hiện hoặc bị từ chối) và 2 (không chạy được, hoặc kết quả không rõ với một thao tác ghi). Phép kiểm tra tính nhất quán (invariant check) `fx-pg check` của nó có dạng đầy đủ và các phần con có tên (`--only setup`, `--only compat`). Địa chỉ kiểm tra sẵn sàng chỉ trả 200 khi bản phát hành khớp và schema đã mới nhất; một cổng chặn ghi theo bản phát hành trả 409 cho một yêu cầu ghi không mang header bản phát hành hiện tại; các đường dẫn API lạ trả về 404 dạng JSON. `migrate` kiểm tra một bản sao lưu trước thay đổi được tạo sau khi dừng các phần ghi dữ liệu (`--not-before`), và tên bản sao lưu của ứng dụng dùng dấu thời gian UTC. Bản dump không mang quyền truy cập (grants), nên một lần khôi phục phải cấp lại vai trò và quyền. Máy chủ khởi tạo tạm thời của image postgres chỉ lắng nghe trên socket, nên phép kiểm tra sẵn sàng là một phép kiểm tra TCP phải đạt ổn định. `web` suy ra địa chỉ proxy của nó từ tuyến IPv4 mặc định và từ chối khởi động nếu không có tuyến đó, trừ khi địa chỉ được đặt sẵn; mạng nội bộ không có tuyến mặc định.
- **`fx-lite`** mô phỏng ứng dụng SQLite (§11, §12). Một container (`app`) chứa ứng dụng web, một bộ chạy việc nền chạy trong cùng tiến trình và cơ sở dữ liệu SQLite (WAL) trong một thư mục dữ liệu được gắn vào từ máy (bind-mount), thuộc `10001:10001`. Nó cập nhật dữ liệu khi khởi động và cũng có các lệnh riêng `migrate`, `backup --to` chạy khi ứng dụng đang hoạt động (ghi ra ngoài thư mục dữ liệu), `restore --from … --to` (kiểm tra mã băm, tính toàn vẹn và schema, rồi bật tạm dừng gửi ra ngoài với lý do `restored` và giữ lại các thư đang chờ gửi) và `bootstrap`. Hàng đợi thư gửi đi của nó bị chặn bởi một chế độ gửi do chủ sở hữu điều khiển; các lệnh gửi ra ngoài kiểu xem trước rồi mới xác nhận của nó chạy bước cập nhật dữ liệu của ứng dụng trước, và thoát với mã 2 cả khi xem trước lẫn khi gọi lệnh sai cách. JSON sẵn sàng của nó báo `status`, `data_writable` và `schema.expected`/`schema.actual`.
- **`fx-web`** là trang web không lưu dữ liệu của §13.

## 8. Ví dụ: manifest ứng dụng `fx-pg` (mẫu của ứng dụng PostgreSQL; một tệp dùng cho cả staging lẫn production)

```toml
# ingat.toml — fx-pg app manifest (Ingat manifest schema 1). Ingat reads it from the exact commit it deploys.
manifest = 1
app = "fx-pg"
requires_ingat = ">=0.1,<1"
# The app's own rule: no other instance of it on a daemon that runs production (§10).
exclusive_environments = ["production"]

[source]
kind = "git"
release = "tag"
tag_pattern = '^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-(alpha|beta|rc)\.[1-9][0-9]*)?$'

[compose]
files = ["compose.yaml"]
build_files = ["compose.yaml", "compose.build.yaml"]
build_services = ["backend", "web"]
build_env = { FXPG_RELEASE = "{release}", FXPG_COMMIT = "{commit}" }
expect_labels = { "org.opencontainers.image.version" = "{release}", "org.opencontainers.image.revision" = "{commit}" }

[params]
FXPG_RELEASE         = { kind = "template", value = "{release}" }
FXPG_SECRETS_DIR     = { kind = "secrets_dir" }
FXPG_BACKUP_DIR      = { kind = "task_dir" }
FXPG_ACCEPT_SCHEMA   = { kind = "accept_schema" }
FXPG_HTTP_PORT       = { kind = "port" }
FXPG_EDGE_SUBNET     = { kind = "subnet" }
FXPG_TIMEZONE        = { required = true, pattern = '^[A-Za-z]+(/[A-Za-z0-9_+-]+)+$' }
POSTGRES_USER        = { default = "fx_owner", pattern = '^[a-z_][a-z0-9_]{0,62}$' }
POSTGRES_DB          = { default = "fx", pattern = '^[a-z_][a-z0-9_]{0,62}$' }
FXPG_BACKEND_WORKERS = { default = "2", pattern = '^[1-8]$' }
FXPG_PROXY_ADDRESS   = { default = "", pattern = '^([0-9.]+(/[0-9]{1,2})?)?$' }
FXPG_DB_MEMORY       = { optional = true, pattern = '^[0-9]+[mg]$' }
FXPG_DB_CPUS         = { optional = true, pattern = '^[0-9]+(\.[0-9]+)?$' }
FXPG_BACKEND_MEMORY  = { optional = true, pattern = '^[0-9]+[mg]$' }
FXPG_BACKEND_CPUS    = { optional = true, pattern = '^[0-9]+(\.[0-9]+)?$' }
FXPG_WEB_MEMORY      = { optional = true, pattern = '^[0-9]+[mg]$' }
FXPG_WEB_CPUS        = { optional = true, pattern = '^[0-9]+(\.[0-9]+)?$' }
FXPG_OPS_MEMORY      = { optional = true, pattern = '^[0-9]+[mg]$' }
FXPG_OPS_CPUS        = { optional = true, pattern = '^[0-9]+(\.[0-9]+)?$' }

[secrets.postgres_password]                 # the postgres image reads it only when it initialises a new data volume
generate = "alnum32"
mode = "0444"                               # read by uid 10001 through the bind mount
[secrets.app_password]
generate = "alnum32"
mode = "0444"
[secrets.maintenance_password]
generate = "alnum32"
mode = "0444"

[stores.pgdata]
kind = "volume"
volume = "postgres_data"
service = "db"
ready = "db-ready"
online_backup = true                        # one pg_dump snapshot is consistent while backend writes

[services]
data = ["db"]
writers = ["backend"]
stateless = ["web"]                         # keeps serving the shell while backend is stopped
log_snapshot = ["db", "backend", "web"]

[schema]
task = "revision"
expected = "expected_revision"
actual = "database_revision"
migrates_on_start = false                   # the backend never migrates; migration is the explicit `migrate` task

# ---------------------------------------------------------------- probes
[probes.db-ready]                           # TCP, not the socket: the image's temporary init server listens only on the socket
exec = "db"
argv = ["pg_isready", "-h", "127.0.0.1", "-p", "5432", "-U", "{param.POSTGRES_USER}", "-d", "{param.POSTGRES_DB}"]
stable = "15s"
timeout = "180s"

[probes.backend-ready]                      # readiness, not liveness: 200 only when the schema is current (or accepted after `rollback --accept-schema`, Planned M3)
exec = "backend"
argv = ["wget", "-q", "-O", "-", "-T", "3", "http://127.0.0.1:8000/api/health"]
expect = { json = { status = "ok", release = "{release}", schema = "current" } }   # "accepted" is added only for `rollback --accept-schema` (M3, ADR)
stable = "5s"
timeout = "180s"

[probes.web-healthy]
health = "web"
timeout = "60s"

[probes.edge-ready]
http = { port_param = "FXPG_HTTP_PORT", path = "/api/health" }
expect = { status = 200, json = { status = "ok", release = "{release}" } }
timeout = "60s"

[[activate]]
services = ["db"]
wait = ["db-ready"]
[[activate]]
services = ["backend"]                      # web still serves the previous bundle; its writes get 409 from the release gate
wait = ["backend-ready"]
[[activate]]
services = ["web"]
wait = ["web-healthy", "edge-ready"]
reopens_writes = true

# ---------------------------------------------------------------- smoke (the image identity check is built in)
[[smoke]]
name = "shell-is-release"
http = { port_param = "FXPG_HTTP_PORT", path = "/" }
expect = { status = 200, header_contains = { "content-type" = "text/html" }, header_equals = { "cache-control" = "no-cache" }, body_contains = '<meta name="fx-release" content="{release}">' }
[[smoke]]
name = "spa-fallback"
http = { port_param = "FXPG_HTTP_PORT", path = "/app/deep/link" }
expect = { status = 200, header_contains = { "content-type" = "text/html" } }
[[smoke]]
name = "ready-on-release"
http = { port_param = "FXPG_HTTP_PORT", path = "/api/health" }
expect = { status = 200, json = { release = "{release}", schema = "current" } }   # "accepted" never passes the smoke
[[smoke]]
name = "live-on-release"
http = { port_param = "FXPG_HTTP_PORT", path = "/api/health/live" }
expect = { status = 200, json = { release = "{release}" } }
[[smoke]]
name = "unknown-api-is-json-404"
http = { port_param = "FXPG_HTTP_PORT", path = "/api/fx-smoke-missing" }
expect = { status = 404, header_contains = { "content-type" = "application/json" } }
[[smoke]]
name = "write-gate-refuses-missing-release"
http = { port_param = "FXPG_HTTP_PORT", method = "POST", path = "/api/fx-smoke-gate", headers = { "X-Fx-CSRF" = "1", "Content-Type" = "application/json" }, body = "{}" }
expect = { status = 409, json = { stale_release = true } }
[[smoke]]
name = "write-gate-passes-current-release"
http = { port_param = "FXPG_HTTP_PORT", method = "POST", path = "/api/fx-smoke-gate", headers = { "X-Fx-CSRF" = "1", "Content-Type" = "application/json", "X-Fx-Release" = "{release}" }, body = "{}" }
expect = { status = 404 }

# ---------------------------------------------------------------- first install
[[install]]
start = ["db"]
wait = ["db-ready"]
[[install]]
task = "db-roles"
[[install]]
task = "migrate-first"
[[install]]
start = ["backend"]
params = { FXPG_BACKEND_WORKERS = "1" }     # first-run setup needs one worker
wait = ["backend-ready"]
log_snapshot = false
[[install]]
start = ["web"]
wait = ["web-healthy", "edge-ready"]
[[install]]
pause = "First-run setup: read the one-time setup code with `ingat logs {instance} backend --since 15m` (it is in the backend log, which anyone who can run `ingat logs` can read, so finish setup now), create the first administrator at the instance URL, then run `ingat resume {instance}`."
[[install]]
start = ["backend"]                         # recreated with the configured worker count
wait = ["backend-ready"]
log_snapshot = false                        # the previous backend log holds the setup code
[[install]]
task = "check-setup"

# ---------------------------------------------------------------- update
[deploy]
baseline = []                               # Planned M3 (owner decision OD-7): ["check"], findings allowed, compared after migrate
prechecks = ["check", "check-compat-candidate"]   # the current image must be clean; the candidate's compatibility subset
migrate = "migrate"
postchecks = ["check-candidate"]            # the full check on the candidate after migrate must be clean; with a baseline, a comparison task replaces it

# ---------------------------------------------------------------- backup (the payload is the app's own backup directory)
[backup]
strategy = "tasks"
steps = ["pg-dump", "pg-list", "pg-revision", "backup-publish"]
verify = ["backup-verify"]
payload = "{bundle.id}"

[backup.naming]                             # the app's own backup name grammar
scheduled = "{bundle.stamp}-daily"
manual = "{bundle.stamp}-manual"
final = "{bundle.stamp}-manual"
pre-change = "{bundle.stamp}-pre-release-{target.release}"

# ---------------------------------------------------------------- restore (into a new generation, in an isolated project)
[restore]
start = ["db"]
steps = ["pg-restore"]
post = ["db-roles", "db-grants"]            # dumps carry no grants
checks = ["revision", "restore-check"]
activate = false

[drill]
checks = ["revision", "restore-check"]
record = ["check"]
activate = true                             # start backend and web in isolation; exec and health probes only
min_free_memory = "2g"                      # a second PostgreSQL runs during the drill

[holds.web]                                 # internal networks have no default route; without this web exits at start
FXPG_PROXY_ADDRESS = "127.0.0.1"            # any IPv4 address works: no proxy traffic exists in isolation

[side_effects]
kind = "none"

# ---------------------------------------------------------------- tasks
[tasks.revision]                            # read-only schema probe; 0 current, 1 any other state, 2 could not run
service = "backend"
mode = "run"
argv = ["fx-pg", "revision"]
effect = "read"
stdout = "json"
exit = { 0 = "ok", 1 = "finding", 2 = "failed" }
timeout = "2m"

[tasks.check]                               # full report: deploy precheck (must be clean), drill record, a daily `ingat scheduled task`
service = "backend"
mode = "run"
argv = ["fx-pg", "check", "--max-findings", "10000"]
effect = "read"
stdout = "record"                           # may hold personal data: stored 0600
exit = { 0 = "ok", 1 = "finding", 2 = "failed" }
timeout = "30m"

[tasks.check-setup]                         # after the first install: first-run setup is complete
service = "backend"
mode = "run"
argv = ["fx-pg", "check", "--only", "setup"]
effect = "read"
stdout = "record"
exit = { 0 = "ok", 1 = "finding", 2 = "failed" }
timeout = "10m"

[tasks.check-compat-candidate]              # precheck with the candidate image, before the freeze
service = "backend"
mode = "run"
image = "candidate"
argv = ["fx-pg", "check", "--only", "compat"]
effect = "read"
stdout = "record"
exit = { 0 = "ok", 1 = "finding", 2 = "failed" }
timeout = "10m"

[tasks.check-candidate]                     # post-migrate check: the full report with the candidate image
service = "backend"
mode = "run"
image = "candidate"
argv = ["fx-pg", "check", "--max-findings", "10000"]
effect = "read"
stdout = "record"
exit = { 0 = "ok", 1 = "finding", 2 = "failed" }
timeout = "30m"

[tasks.restore-check]
service = "backend"
mode = "run"
argv = ["fx-pg", "check", "--only", "setup", "--only", "compat"]
effect = "read"
stdout = "record"
exit = { 0 = "ok", 1 = "finding", 2 = "failed" }
timeout = "10m"

[tasks.migrate]                             # the service's entrypoint is the app's migrate command
service = "migrate"
mode = "run"
image = "candidate"
argv = ["--pre-change-backup", "{bundle.payload}", "--not-before", "{freeze_at}", "--backup-dir", "/backups"]
mounts = { FXPG_BACKUP_DIR = "bundle" }     # private read-only copy owned by uid 10001
effect = "data"
idempotent = true                           # an at-head database answers already_current
observe = "schema"
stdout = "record"
exit = { 0 = "ok", 1 = "refused", 2 = "unknown" }
operator = false
timeout = "60m"

[tasks.migrate-first]
service = "migrate"
mode = "run"
image = "candidate"
argv = ["--without-backup", "first install: empty database (ingat op {op.seq})"]
effect = "data"
idempotent = true
observe = "schema"
stdout = "record"
exit = { 0 = "ok", 1 = "refused", 2 = "unknown" }
operator = false
timeout = "30m"

[tasks.db-roles]                            # the service's entrypoint is the app CLI; safe to repeat
service = "db-roles"
mode = "run"
argv = ["roles"]
effect = "data"
idempotent = true
stdout = "record"
exit = { 0 = "ok", 1 = "refused", 2 = "unknown" }
timeout = "5m"

[tasks.db-grants]
service = "db-roles"
mode = "run"
argv = ["grants"]
effect = "data"
idempotent = true
stdout = "record"
exit = { 0 = "ok", 1 = "refused", 2 = "unknown" }
timeout = "5m"

[tasks.pg-dump]
service = "db"
mode = "exec"
env = { TZ = "UTC" }                        # the archive stores local-time fields
argv = ["pg_dump", "-U", "{param.POSTGRES_USER}", "-d", "{param.POSTGRES_DB}", "--format=custom", "--no-owner", "--no-privileges", "--lock-wait-timeout=60s"]
stdout = "file:.partial/{bundle.id}/db.dump"
nonempty = true
effect = "read"
exit = { 0 = "ok" }
timeout = "60m"

[tasks.pg-list]
service = "db"
mode = "exec"
env = { TZ = "UTC" }
argv = ["pg_restore", "--list"]
stdin = "file:.partial/{bundle.id}/db.dump"
stdout = "file:.partial/{bundle.id}/db.dump.list"
nonempty = true
effect = "read"
exit = { 0 = "ok" }
timeout = "10m"

[tasks.pg-revision]
service = "db"
mode = "exec"
env = { TZ = "UTC" }
argv = ["pg_restore", "--data-only", "--table=schema_version", "--file=-"]
stdin = "file:.partial/{bundle.id}/db.dump"
stdout = "file:.partial/{bundle.id}/schema_version.sql"
effect = "read"
exit = { 0 = "ok" }
timeout = "10m"

[tasks.backup-publish]                      # publishes <stage>/{bundle.id}/ with the app's own backup manifest and SHA256SUMS
service = "backup-tools"
mode = "run"
argv = ["backup-publish", "--name", "{bundle.id}", "--operator", "{operator}", "--reason", "{reason}",
        "--release-tag", "{release}", "--release-commit", "{commit}", "--expected-revision", "{schema.expected}",
        "--environment", "{environment}", "--host", "{host}",
        "--image-backend", "{image.backend}", "--image-web", "{image.web}", "--image-db", "{image.db}"]
mounts = { FXPG_BACKUP_DIR = "stage" }
effect = "read"                             # writes only into the stage
stdout = "json"
exit = { 0 = "ok", 1 = "refused", 2 = "failed" }
timeout = "10m"

[tasks.backup-verify]
service = "backup-tools"
mode = "run"
argv = ["verify-backup", "{bundle.payload}", "--database", "{param.POSTGRES_DB}"]
mounts = { FXPG_BACKUP_DIR = "bundle" }
effect = "read"
stdout = "json"
exit = { 0 = "ok", 1 = "failed", 2 = "failed" }
timeout = "20m"

[tasks.pg-restore]                          # exec into the isolated project's db only
service = "db"
mode = "exec"
env = { TZ = "UTC" }
argv = ["pg_restore", "--single-transaction", "--exit-on-error", "--no-owner", "--no-privileges", "-U", "{param.POSTGRES_USER}", "-d", "{param.POSTGRES_DB}"]
stdin = "bundle:{bundle.payload}/db.dump"
effect = "data"
exit = { 0 = "ok" }
operator = false
timeout = "120m"

[tasks.app-status]                          # read-only report; its backup-age field is not authoritative under Ingat
service = "status"
mode = "run"
argv = []
effect = "read"
stdout = "json"
exit = { 0 = "ok", 1 = "finding", 2 = "failed" }
timeout = "2m"

[tasks.reset-password]                      # recovery; the password is typed at the prompt, never an argument
service = "backend"
mode = "run"
argv = ["fx-pg", "reset-password", "--user", "{arg.user}"]
args = { user = '^[A-Za-z0-9._@-]{1,64}$' }
stdin = "terminal"
stdout = "terminal"
effect = "app-write"
exit = { 0 = "ok", 1 = "refused", 2 = "unknown" }
timeout = "5m"

[tasks.recover-admin-role]                  # recovery; a free-text name without control characters
service = "backend"
mode = "run"
argv = ["fx-pg", "recover-admin-role", "--role-name", "{arg.role_name}"]
args = { role_name = '^[^\x00-\x1f]{1,100}$' }
stdout = "terminal"
effect = "app-write"
exit = { 0 = "ok", 1 = "refused", 2 = "unknown" }
timeout = "5m"
```

## 9. Ví dụ: bản cài staging của `fx-pg` (`INGAT_ROOT/instances/pg-staging/instance.toml`)

```toml
instance = 1
name = "pg-staging"
app = "fx-pg"
environment = "staging"
disposable = true                     # synthetic data only; fixed at init; purge may skip its restore-test

[source]
repo = "ssh://git@github.com/<owner>/<app>.git"
key = "fx-pg"                         # INGAT_ROOT/keys/fx-pg/ (read-only deploy key, pinned known_hosts)
accept = '^v[0-9]+\.[0-9]+\.[0-9]+(-(alpha|beta|rc)\.[1-9][0-9]*)?$'

[params]
FXPG_TIMEZONE = "Etc/UTC"             # example value; the same as production
FXPG_HTTP_PORT = "20081"              # fixed: the host's reverse proxy points here
FXPG_EDGE_SUBNET = "10.200.1.0/24"
FXPG_BACKEND_WORKERS = "2"
FXPG_DB_MEMORY = "512m"
# Required on a host without CPU CFS quota (as on DSM 7.4.1 with Container Manager 24.0.2-1706): the capability check refuses any non-zero `cpus`.
FXPG_DB_CPUS = "0"
FXPG_BACKEND_CPUS = "0"
FXPG_WEB_CPUS = "0"
FXPG_OPS_CPUS = "0"

[backups]
keep_daily = 7
keep_weekly = 4
keep_monthly = 0
pin_pre_change_days = 14
max_age_hours = 26
restore_test_max_age_days = 8
```

Staging chạy cùng các tệp Compose lúc chạy như production, không phải một tệp Compose riêng cho việc phát triển, nên nó thử đúng những gì production sẽ chạy; vì vậy, một ứng dụng đặt cookie phiên ở chế độ bảo mật (secure) cũng cần HTTPS đứng trước staging. `disposable` không bao giờ cho phép một agent (trợ lý AI) chạy lớp D trên bản cài này: gỡ bỏ hoàn toàn (purge) và khôi phục đè lên staging vẫn chỉ làm được từ một terminal thật (quyết định của chủ sở hữu OD-10).

## 10. Ví dụ: bản cài production của `fx-pg` (`INGAT_ROOT/instances/pg-prod/instance.toml`)

Chỉ được tạo sau khi quyết định của chủ sở hữu OD-5 đã được chốt (khóa `exclusive_environments` của manifest từ chối bản cài này khi `pg-staging` đang được đăng ký trên cùng máy).

```toml
instance = 1
name = "pg-prod"
app = "fx-pg"
environment = "production"
disposable = false

[source]
repo = "ssh://git@github.com/<owner>/<app>.git"
key = "fx-pg"
accept = '^v[0-9]+\.[0-9]+\.[0-9]+$'          # final tags only

[params]
FXPG_TIMEZONE = "Etc/UTC"
FXPG_HTTP_PORT = "20080"
FXPG_EDGE_SUBNET = "10.200.0.0/24"
FXPG_BACKEND_WORKERS = "2"
# On a host without CPU CFS quota, as in §9; a host with CPU CFS support may set real limits:
FXPG_DB_CPUS = "0"
FXPG_BACKEND_CPUS = "0"
FXPG_WEB_CPUS = "0"
FXPG_OPS_CPUS = "0"

[backups]
keep_daily = 14
keep_weekly = 8
keep_monthly = 12
pin_pre_change_days = 30                      # pre-change bundles stay through the observation window
max_age_hours = 26
restore_test_max_age_days = 8

# [monitor]                                   # Planned M3
# public_url = "https://<public host>/"
# cert_warn_days = 21
# resolve_to = "127.0.0.1"
```

## 11. Ví dụ: manifest ứng dụng `fx-lite` (mẫu của ứng dụng SQLite)

Đây là dạng nghiệm thu của M2: một tệp Compose lúc chạy có mạng nhận một subnet cố định từ một tham số `subnet`; CI của ứng dụng dựng và phát hành image theo commit, và Ingat không dùng tệp build của nó ([ADR-0026](adr/0026-app-images-built-in-app-ci.vi.md)). Dạng M1 mô phỏng ứng dụng SQLite khi nó chưa có tệp chạy đó: một tệp Compose, không có tham số `FXLITE_SUBNET` và không có `log_snapshot` (M1 từ chối khóa này lúc lập kế hoạch); mọi thứ khác giống hệt. Ứng dụng thử `fx-lite` (`ARCHITECTURE.md` §10.2) chính là dạng M1 đó, ngoại trừ hai điểm: bản cài ghi tên image của nó (image của công cụ trong selftest và CI), và phép kiểm tra sẵn sàng của nó gọi lệnh `fx-lite probe` riêng của ứng dụng thử, vì image của công cụ không có `wget` (phần đầu của `fixtures/fx-lite/ingat.toml` liệt kê mọi điểm khác).

```toml
# ingat.toml — fx-lite app manifest (Ingat manifest schema 1).
manifest = 1
app = "fx-lite"
requires_ingat = ">=0.1,<1"

[source]
kind = "git"
release = "commit"                            # one image tag per release commit

[compose]
files = ["compose.yaml"]                      # the service without `build:`; network subnet from FXLITE_SUBNET
build_files = ["compose.yaml", "compose.build.yaml"]
build_services = ["app"]                      # built and published by the app's CI (ADR-0026)
expect_labels = { "org.opencontainers.image.revision" = "{commit}" }

[params]
FXLITE_IMAGE    = { kind = "template", value = "ghcr.io/<owner>/<app>:{commit}" }
FXLITE_ENV_FILE = { kind = "env_file" }
FXLITE_DATA_DIR = { kind = "store", store = "data" }
FXLITE_PORT     = { kind = "port" }
FXLITE_SUBNET   = { kind = "subnet" }         # a stable gateway, so PROXY_ADDRESS survives a network recreate

[app_env]
param = "FXLITE_ENV_FILE"
# Fixed by the image, or used only by a development seed command that never runs in production.
# Any other undeclared key is refused anyway.
forbidden = ["APP_ENV", "HOST", "PORT", "DATA_DIR", "DATABASE_PATH", "SEED_PASSWORD"]

[app_env.keys]
ALLOWED_ORIGINS  = { required = true }
BASE_URL         = { required = true }
MAIL_SENDER      = { required = true }
PROXY_ADDRESS    = { required = true }
SECURE_COOKIES   = { allowed = ["true", "false"] }
SESSION_HOURS    = { pattern = '^[0-9]{1,4}$' }
DELIVERY_MODE    = { default = "capture", allowed = ["capture", "smtp"], owner_gated = true }
DELIVERY_ENABLED = { allowed = ["true"], owner_gated = true }   # real sending needs both owner-gated keys
MAIL_HOST        = { pattern = '^[A-Za-z0-9.-]{1,253}$' }
MAIL_PORT        = { pattern = '^[0-9]{1,5}$' }
MAIL_SECURITY    = { allowed = ["starttls", "tls"] }
MAIL_USER        = { secret = true }
MAIL_PASSWORD    = { secret = true }
JOBS             = { allowed = ["off"], tool_managed = true }

[stores.data]
kind = "bind"
param = "FXLITE_DATA_DIR"
owner = "10001:10001"                         # the image user
mode = "0700"
local_only = true                             # SQLite WAL: never SMB/NFS or a synchronized folder
online_backup = true                          # SQLite online backup

[services]
writers = ["app"]                             # web app, in-process job runner and the SQLite store in one container
log_snapshot = ["app"]                        # honoured from M2; M1 refuses a manifest that sets it

[schema]
probe = "ready"
expected = "schema.expected"
actual = "schema.actual"
migrates_on_start = true                      # every image change is data-changing

[probes.ready]
exec = "app"
argv = ["wget", "-q", "-O", "-", "-T", "4", "http://127.0.0.1:3000/api/ready"]
expect = { json = { status = "ready", data_writable = true } }
stable = "5s"
timeout = "120s"

[probes.edge-live]
http = { port_param = "FXLITE_PORT", path = "/api/health" }
expect = { status = 200, json = { status = "ok" } }
timeout = "30s"

[[activate]]
services = ["app"]
wait = ["ready", "edge-live"]
reopens_writes = true

[[smoke]]
name = "live"
http = { port_param = "FXLITE_PORT", path = "/api/health" }
expect = { status = 200, json = { status = "ok" } }
[[smoke]]
name = "ready"
http = { port_param = "FXLITE_PORT", path = "/api/ready" }
expect = { status = 200, json = { status = "ready", data_writable = true } }

[[install]]
task = "migrate"                              # once and alone: concurrent first opens can fail with SQLITE_BUSY
[[install]]
start = ["app"]
wait = ["ready", "edge-live"]
[[install]]
pause = "Copy the bootstrap file into the Ingat inbox (INGAT_ROOT/inbox/), run `ingat task {instance} bootstrap-config --input config=<file>` (it prints a single-use setup code to the terminal that runs it and never records it), complete setup in the browser, then run `ingat resume {instance}`."
allow_tasks = ["bootstrap-config", "bootstrap-new-code"]

[deploy]
baseline = []
prechecks = []
migrate = "migrate"                           # explicit one-off before the start, so the start applies nothing
postchecks = []

[backup]
strategy = "tasks"
steps = ["backup"]
verify = []                                   # hash-only until the app has a read-only verify command

[restore]
start = []
steps = ["restore"]
post = []
checks = []
activate = true                               # start the app on the new generation in isolation and wait for `ready`

[rollback]
env = { JOBS = "off" }                        # a schema older than the outbound pause cannot hold paused jobs

[drill]                                       # throwaway secrets; mail credentials and owner-gated keys are dropped in isolation
checks = []
record = []
activate = true
min_free_memory = "512m"

[holds.app]
DELIVERY_MODE = "capture"
JOBS = "off"

[side_effects]
kind = "outbound"
restore_via_app = true
after_restore = "held"
clear_hold = "queue-resume"
single_active = true                          # Planned M4: never two queues on one data lineage
restore_notice = "Outbound delivery is paused (reason: restored) and queued sends are held. List them with `ingat task {instance} queue-held`, check the mailbox, then use queue-release-job / queue-release-all / queue-drop-job, check `ingat task {instance} queue-status`, and finally run queue-resume."

# ---------------------------------------------------------------- tasks (all `run`: a second SQLite process is safe under WAL)
[tasks.migrate]
service = "app"
mode = "run"
image = "candidate"
argv = ["fx-lite", "migrate"]
effect = "data"
idempotent = true                             # exclusive lock, one transaction; a re-run applies nothing
exit = { 0 = "ok" }                           # any other exit is unknown (data effect)
operator = false
timeout = "15m"

[tasks.backup]
service = "app"
mode = "run"
argv = ["fx-lite", "backup", "--to", "/out"]
mounts = { "/out" = "stage" }                 # outside the data directory, as the app requires
effect = "app-write"                          # records its outcome in the app's own backup bookkeeping; scratch as a backup step (LIFECYCLE §3.3)
idempotent = true                             # required for a non-read backup task; a redo writes into a fresh stage
stdout = "json"
exit = { 0 = "ok", 1 = "failed", 2 = "refused" }
operator = false                              # it mounts the stage, which exists only inside a backup
timeout = "60m"

[tasks.restore]                               # runs only in the isolated project: internal network, read-only root
service = "app"
mode = "run"
image = "bundle"
argv = ["fx-lite", "restore", "--from", "/in/{bundle.payload}", "--to", "/restore"]
mounts = { "/in" = "bundle", "/restore" = "generation:data" }
effect = "data"
exit = { 0 = "ok", 1 = "failed", 2 = "refused" }
operator = false
timeout = "60m"

[tasks.bootstrap-config]
service = "app"
mode = "run"
argv = ["fx-lite", "bootstrap", "--config", "/in/{input.config}"]
mounts = { "/in" = "input:config" }
max_input_bytes = 262144
stdout = "terminal"                           # prints the single-use setup code; never recorded
effect = "app-write"
exit = { 0 = "ok", 1 = "refused", 2 = "refused" }
timeout = "5m"

[tasks.bootstrap-new-code]
service = "app"
mode = "run"
argv = ["fx-lite", "bootstrap", "--new-code"]
stdout = "terminal"
effect = "app-write"
exit = { 0 = "ok", 1 = "refused", 2 = "refused" }
timeout = "2m"

# Outbound reconciliation: the app's own preview (no --confirm; exit 2 with outcome "preview") and its
# confirm commands (--confirm last) are separate tasks. The preview runs the app's migration first and exits 2 for a
# usage error too, so the preview tasks are app-write and idempotent, and `expect` tells a preview from a usage error.
# A read-only preview in the app would make them read tasks (class B).
[tasks.queue-held]                            # lists held jobs: ids, kinds, attempts, blockers; no personal data
service = "app"
mode = "run"
argv = ["fx-lite", "queue", "release"]
effect = "app-write"
idempotent = true
stdout = "record"
expect = { json = { outcome = "preview" } }
exit = { 2 = "ok" }
timeout = "2m"

[tasks.queue-status]                          # the pause and the counts `queue-resume` would release
service = "app"
mode = "run"
argv = ["fx-lite", "queue", "resume"]
effect = "app-write"
idempotent = true
stdout = "record"
expect = { json = { outcome = "preview" } }
exit = { 2 = "ok" }
timeout = "2m"

[tasks.queue-release-job]
service = "app"
mode = "run"
argv = ["fx-lite", "queue", "release", "--job", "{arg.job}", "--confirm"]
args = { job = '^[A-Za-z0-9-]{1,64}$' }
effect = "app-write"
stdout = "record"
exit = { 0 = "ok", 1 = "refused" }
timeout = "2m"

[tasks.queue-release-all]
service = "app"
mode = "run"
argv = ["fx-lite", "queue", "release", "--all", "--confirm"]
effect = "app-write"
stdout = "record"
exit = { 0 = "ok", 1 = "refused" }
timeout = "2m"

[tasks.queue-drop-job]
service = "app"
mode = "run"
argv = ["fx-lite", "queue", "drop", "--job", "{arg.job}", "--confirm"]
args = { job = '^[A-Za-z0-9-]{1,64}$' }
effect = "app-write"
stdout = "record"
exit = { 0 = "ok", 1 = "refused" }
timeout = "2m"

[tasks.queue-resume]
service = "app"
mode = "run"
argv = ["fx-lite", "queue", "resume", "--confirm"]
clears_hold = true
effect = "app-write"
stdout = "record"
exit = { 0 = "ok", 1 = "refused" }            # 1: an attempt still awaits its decision
timeout = "2m"
```

## 12. Ví dụ: bản cài thử nghiệm của `fx-lite` (`INGAT_ROOT/instances/lite-test/instance.toml`)

```toml
instance = 1
name = "lite-test"
app = "fx-lite"
environment = "test"
disposable = false                            # keep the restore-tested purge gate even for a test instance

[source]
repo = "ssh://git@github.com/<owner>/<app>.git"
key = "fx-lite"

[params]
FXLITE_PORT = "20090"
FXLITE_SUBNET = "10.200.2.0/24"               # M2 form; in the M1 form the default network keeps Docker's own subnet

[app_env]
ALLOWED_ORIGINS = "https://lite-test.<lan-domain>"
BASE_URL = "https://lite-test.<lan-domain>"
MAIL_SENDER = "lite-test@<domain>"
PROXY_ADDRESS = "10.200.2.1"                  # the subnet's gateway; `ingat doctor lite-test` compares it with the observed proxy peer
DELIVERY_MODE = "capture"                     # owner-gated; `smtp` also needs DELIVERY_ENABLED (class D)

[backups]
keep_daily = 7                                # retention defaults pending owner decision OD-8
keep_weekly = 4
keep_monthly = 6
pin_pre_change_days = 30
max_age_hours = 26
restore_test_max_age_days = 8
```

Ở dạng M1 (không có `FXLITE_SUBNET`), `PROXY_ADDRESS` được đặt bằng địa chỉ bên kết nối tới (peer) mà `ingat doctor lite-test` báo sau lần cài đầu tiên (báo cáo đó chưa có trong mã M1: `LIFECYCLE.md` §4.15), sau đó triển khai lại chỉ để đổi cấu hình; địa chỉ đó chỉ còn đúng khi mạng mặc định không bị tạo lại, vì vậy tệp Compose lúc chạy với subnet cố định là bắt buộc trước khi chốt M2.

Một bản cài production sau này của cùng ứng dụng chỉ khác ở `name`, `environment = "production"`, các URL và cổng của nó, và thay đổi lớp D của chủ sở hữu đặt `DELIVERY_MODE = "smtp"` cùng `DELIVERY_ENABLED = "true"` sau khi chạy `ingat secret set <i> MAIL_USER` và `MAIL_PASSWORD`.

## 13. Ví dụ: trang web chung không lưu dữ liệu (mẫu `fx-web`; các tệp nằm trong `INGAT_ROOT/instances/site/app/`)

`ingat.toml`:

```toml
manifest = 1
app = "site"
requires_ingat = ">=0.1,<1"

[source]
kind = "image"
images = { site = "SITE_IMAGE" }

[compose]
files = ["compose.yaml"]

[params]
SITE_IMAGE = { kind = "image", service = "site" }
SITE_PORT  = { kind = "port" }

[services]
stateless = ["site"]

[probes.ready]
http = { port_param = "SITE_PORT", path = "/" }
expect = { status = 200 }
timeout = "60s"

[[activate]]
services = ["site"]
wait = ["ready"]

[backup]
strategy = "none"                             # backup, verify, restore and drill report "not applicable"

[side_effects]
kind = "none"
```

`compose.yaml`:

```yaml
services:
  site:
    image: ${SITE_IMAGE:?}
    ports: ["127.0.0.1:${SITE_PORT:?}:8080"]
    read_only: true
    restart: unless-stopped
    logging: {driver: json-file, options: {max-size: "10m", max-file: "3"}}
```

`instance.toml`: `instance = 1`, `name = "site"`, `app = "site"`, `environment = "production"`, `disposable = true`, `[source] kind = "image"`, `[params] SITE_PORT = "20100"`. Triển khai bằng `ingat deploy site --image site=ghcr.io/<owner>/<image>@sha256:<digest>`; quay về bản cũ nghĩa là dùng lại digest trước đó.
