# Kiến trúc Ingat

[English](ARCHITECTURE.md) · **Tiếng Việt** (bản dịch; bản tiếng Anh là bản chuẩn)

> **Nói đơn giản.** Đây là thiết kế kỹ thuật của Ingat: Ingat hứa những gì và sẽ không bao giờ làm gì, nó chạy trên một máy như thế nào, một lệnh trở thành một danh sách các bước an toàn ra sao, nó giữ tệp ở đâu, nó bảo vệ thông tin bí mật (secret) và từ chối các thiết lập ứng dụng không an toàn thế nào, nó được kiểm thử ra sao, và nó hỗ trợ những máy nào. Đây là bản đặc tả bắt buộc cho mọi người xây dựng hoặc xem xét Ingat. Để dùng Ingat, hãy bắt đầu với [README](../README.vi.md) và [hướng dẫn vận hành](runbooks/operator-guide.vi.md).

**Tìm gì ở đâu**

| Mục | Nói đơn giản |
|---|---|
| [§1 Sản phẩm](#1-sản-phẩm) | Ingat hứa gì, ai dùng nó, phạm vi của nó, và những gì nó sẽ không bao giờ làm |
| [§2 Bối cảnh hệ thống](#2-bối-cảnh-hệ-thống) | Một hình vẽ các thành phần: bạn, lệnh `ingat`, container trợ giúp, các ứng dụng của bạn và hai thư mục |
| [§3 Môi trường chạy và phân phối](#3-môi-trường-chạy-và-phân-phối) | Những gì có trong image Ingat, script khởi động nhỏ, cài đặt và nâng cấp, và cổng phiên bản (version gate) quyết định lệnh nào được chạy trên một máy |
| [§4 Mô hình thực thi](#4-mô-hình-thực-thi) | Vì sao các thay đổi chạy trong một container trợ giúp riêng, các tác vụ dùng terminal, việc hủy, và dọn phần còn sót lại sau khi bị sập |
| [§5 Mô-đun và phân lớp](#5-mô-đun-và-phân-lớp) | Mã được chia thành các lớp ra sao, giới hạn kích thước, và các bài kiểm thử giữ đúng sự phân chia đó |
| [§6 Cách gọi Compose](#6-cách-gọi-compose) | Ingat gọi Docker Compose thế nào: luôn trên các tệp riêng của ứng dụng cộng thêm một tệp do Ingat tạo ra |
| [§7 Bố cục trên đĩa, bản ghi và khóa](#7-bố-cục-trên-đĩa-bản-ghi-và-khóa) | Ingat giữ tệp nào ở đâu, quy tắc ghi chúng, và các khóa để mỗi lúc chỉ một lệnh làm việc với một ứng dụng |
| [§8 Mẫu](#8-mẫu) | Bộ chỗ trống cố định mà một manifest ứng dụng được phép dùng |
| [§9 Bảo mật và mô hình tin cậy](#9-bảo-mật-và-mô-hình-tin-cậy) | Ingat tin vào gì, chống lại gì, socket Docker, thông tin bí mật, và các thiết lập ứng dụng mà nó từ chối |
| [§10 Kiểm thử và chứng nhận](#10-kiểm-thử-và-chứng-nhận) | Các mức kiểm thử, các ứng dụng thử, các bộ kiểm thử bắt buộc, và cách một máy được chứng nhận |
| [§11 Máy và bảng hỗ trợ](#11-máy-và-bảng-hỗ-trợ) | Những máy nào được hỗ trợ, khác biệt giữa chúng được xử lý ra sao, danh sách kiểm tra cho một ứng dụng mới, và cấu hình máy tối thiểu |
| [§12 Rủi ro](#12-rủi-ro) | Các rủi ro đã biết và cách giảm từng rủi ro |

Trạng thái: **Decided** trừ khi có nhãn khác. Mã của M1 đã có. CI đạt trên cả ba làn kiểm thử (lane) chạy Docker thật, và bản phát hành `v0.1.0` đã đạt `selftest --host` trên máy đầu tiên; chưa có mốc (milestone) nào đạt điều kiện hoàn thành mốc (exit gate) ([README](../README.vi.md#tình-trạng)). Các nhãn trạng thái: **Decided** (Đã quyết định: một phần của thiết kế), **Planned Mx** (Đã lên kế hoạch: đã quyết định, sẽ được làm ở mốc x), **Open OD-n** (Còn mở: cần chủ sở hữu quyết định), **Unverified** (Chưa kiểm chứng: một sự thật về nền tảng mà thử nghiệm sớm (spike) M0 hoặc một thử nghiệm sớm sau đó phải xác nhận). Các quyết định của chủ sở hữu được ghi là OD-n: OD-1 (tên), OD-2 (không gian tên LisaHQ), OD-3 (repository công khai) và OD-11 (image ứng dụng được build trong CI của từng ứng dụng: ADR-0026) đã được quyết định; các quyết định còn lại vẫn mở và được ghi trong ghi chú của chủ sở hữu. Các thao tác và sơ đồ trạng thái (state machine) của chúng nằm trong [`LIFECYCLE.md`](LIFECYCLE.vi.md); cú pháp manifest nằm trong [`MANIFEST_SPEC.md`](MANIFEST_SPEC.vi.md); các mốc nằm trong [`ROADMAP.md`](ROADMAP.vi.md); lý do của từng lựa chọn nằm trong các ADR (bản ghi quyết định kiến trúc) ([`adr/README.md`](adr/README.vi.md)).

## 1. Sản phẩm

### 1.1 Tuyên bố

Ingat là một công cụ dòng lệnh nhỏ dùng để cài đặt, cập nhật, sao lưu, kiểm tra, khôi phục và cho ngừng hẳn (retire) các ứng dụng Docker Compose trên **một** máy chạy Docker, và tiếp quản (adoption) một bản triển khai mà nó không tạo ra, bắt đầu từ một gói dữ liệu (payload) do chính lệnh sao lưu của ứng dụng tạo ra (M4). Mã chương trình, không phải cấu hình, bảo đảm các cam kết của nó (các quy tắc an toàn bắt buộc (safety floor) F1-F17 trong [`LIFECYCLE.md`](LIFECYCLE.vi.md) §1):

- Không bước nào thay đổi dữ liệu được chạy trước khi đã có một bản sao lưu được niêm phong (mỗi tệp có mã kiểm tra) và đã kiểm tra (verified), được tạo khi các phần ghi dữ liệu (những phần của ứng dụng thay đổi dữ liệu) đã dừng.
- Một lần khôi phục không bao giờ ghi đè dữ liệu: nó điền dữ liệu vào một vùng dữ liệu (generation) mới, kiểm tra vùng đó, rồi chuyển một con trỏ sang. Vùng dữ liệu cũ được giữ lại.
- Một bản sao lưu chỉ được tính là khôi phục được sau khi một lần khôi phục cách ly (isolated) của chính bản sao lưu (bundle) đã niêm phong đó đạt các phép kiểm tra của ứng dụng.
- Một thao tác bị gián đoạn luôn có thể được tiếp tục hoặc bỏ dở dựa trên nhật ký các bước của chính nó; không trạng thái nào là ngõ cụt.
- Không gì bị xóa trừ khi một kế hoạch đã đóng liệt kê nó và từng mục được chứng minh lại là thuộc Ingat ngay trước khi xóa.

Ingat chỉ điều phối. Mỗi ứng dụng giữ các thao tác dữ liệu của nó bên trong image của chính nó và khai báo chúng trong manifest ứng dụng của nó (ví dụ các lệnh dòng lệnh mà ứng dụng PostgreSQL (the PostgreSQL consumer) và ứng dụng SQLite (the SQLite consumer) đóng gói trong image của chính chúng). Phần lõi (core) không chứa hiểu biết nào về ứng dụng hay về bộ máy cơ sở dữ liệu (database engine).

**Máy.** Một máy là bất kỳ máy nào có Docker Engine Linux cục bộ (24.0 trở lên) và Compose v2, trên bất kỳ bản phân phối hay thiết bị nào: một máy chủ vật lý (bare-metal), một máy ảo (VM) hoặc VPS, một NAS có Docker (Synology hoặc bất kỳ hãng nào khác), một bo mạch nhỏ. Khác biệt giữa các nền tảng (CPU CFS quota, phiên bản cgroup, logging driver, storage driver, kernel, kiến trúc, live restore, seccomp) là các khả năng mà Ingat tự phát hiện, và mỗi bản build nền tảng được chứng nhận riêng; không đường mã nào rẽ nhánh theo tên nền tảng, hãng hay mẫu máy (§11). Các bậc hỗ trợ (support tier) và các hồ sơ nền tảng (platform profile) nằm ở §11.1-§11.2.

### 1.2 Người dùng

| Bên gọi | Cách gọi | Được phép (các lớp duyệt trong [`LIFECYCLE.md`](LIFECYCLE.vi.md) §2) |
|---|---|---|
| Chủ sở hữu | SSH, `sudo -i`, script khởi động (wrapper) `<INGAT_ROOT>/bin/ingat` (mặc định là `/srv/ingat/bin/ingat`) | Mọi thứ; là bên gọi duy nhất được dự định để trả lời thử thách (challenge) của lớp duyệt D (class D) |
| Agent vận hành trong phiên làm việc của chủ sở hữu trên máy | Cùng chương trình | Lớp A và B thoải mái; lớp C chỉ khi có mã băm kế hoạch (plan hash) do chủ sở hữu đưa; lớp D không bao giờ. Đây là một điểm chặn để tránh nhầm lẫn, chỉ có tác dụng với agent tuân theo nó, **không phải** một ranh giới bảo mật chống lại root: một agent tự cấp cho mình một pty (ví dụ `script -qc`) có thể gõ được thử thách. Việc ép buộc thật sự là các quy tắc cấm công cụ của chính agent đó (quyết định của chủ sở hữu OD-10). Agent phát triển (trợ lý AI) làm việc trong repository Ingat không bao giờ chạm vào một máy thật ([`CLAUDE.md`](../CLAUDE.md) §6). |
| Bộ lập lịch của máy (systemd timer, cron, hoặc bộ lập lịch của nền tảng như DSM Task Scheduler) | Đường dẫn tuyệt đối tới script khởi động, root, không có terminal | `ingat scheduled …`: chỉ lớp A và B |
| CI của ứng dụng | `docker run <pinned ingat image> validate` (M1), `conformance` (M3) | Kiểm tra hợp lệ ngoại tuyến; kiểm tra tuân thủ (conformance) với Docker thật trong runner riêng của nó, không bao giờ trên một máy thật |

### 1.3 Ứng dụng dùng Ingat và phạm vi

Các ứng dụng dùng Ingat ở v1, chỉ được mô tả theo hình dạng (repository này công khai và chung chung: quyết định của chủ sở hữu OD-3):

- **Ứng dụng PostgreSQL** (the PostgreSQL consumer): một ứng dụng web nhiều dịch vụ (PostgreSQL, backend và web) có một bước cập nhật dữ liệu (migrate) riêng, cấp quyền cho các role sau khi khôi phục, và một lệnh kiểm tra các điều kiện luôn phải đúng (invariant check); hiện có một bản cài (instance) staging (`pg-staging`), sau này có một bản cài production (`pg-prod`). Ứng dụng thử (fixture) `fx-pg` mô phỏng nó (§10.2).
- **Ứng dụng SQLite** (the SQLite consumer): một ứng dụng một container với SQLite trong một thư mục dữ liệu gắn từ máy (bind mount), một cách sao lưu trực tuyến riêng của ứng dụng, một hàng đợi thư gửi đi và bước cập nhật dữ liệu lúc khởi động; hiện có một bản cài thử (`lite-test`), sau này có bản production. Ứng dụng thử `fx-lite` mô phỏng nó.
- **Các trang web chung không lưu trạng thái**, được triển khai theo digest của image (ví dụ `site`). Ứng dụng thử `fx-web` mô phỏng chúng.

Các ứng dụng nội bộ khác đã được lên kế hoạch; chưa biết chúng dùng công nghệ gì. Mỗi khả năng đều nêu tên nhu cầu của ứng dụng mà nó phục vụ (ADR-0021), và một ứng dụng mới phải vừa mà không cần thay đổi phần lõi (quy tắc tổng quát, §11.3).

Trong phạm vi (toàn bộ tính năng chủ sở hữu yêu cầu, 2026-10-14): cài đặt và chứng nhận máy; khởi tạo bản cài và các thông tin bí mật; build từ một commit git chính xác hoặc triển khai (deploy) một digest image; cập nhật có tính đến dữ liệu, gồm: tạm khóa (freeze), bản sao lưu trước thay đổi, cập nhật cấu trúc và dữ liệu (migrate), bật các dịch vụ theo thứ tự, kiểm tra nhanh sau khi chạy (smoke), tạm khóa lại (refreeze); quay về bản cũ (rollback); start/stop/restart; các tác vụ (task) có kiểu của ứng dụng; sao lưu, kiểm tra và thử khôi phục (drill) cách ly; khôi phục vào một vùng dữ liệu mới; giữ lại bản sao lưu theo quy tắc (retention); gỡ bỏ hoàn toàn (purge) (M3); giám sát với mã thoát ổn định (M3); khắc phục thảm họa: nhập (import), khôi phục sang máy khác và khôi phục vào một bản cài mới (M4); tiếp quản một bản triển khai Compose đang chạy mà Ingat không tạo ra (M4, [`LIFECYCLE.md`](LIFECYCLE.vi.md) §4.16); bất kỳ máy Linux chạy Docker nào (bậc hỗ trợ 1, được các làn kiểm thử CI bao phủ từ M1, với chứng nhận Linux chung đầu tiên được commit ở M4) và các thiết bị của hãng được chứng nhận theo từng bản build nền tảng (bậc hỗ trợ 2, Synology DSM trước tiên) (§11.1).

### 1.4 Những gì không bao giờ làm

- Điều phối nhiều máy, Swarm, Kubernetes, cập nhật không gián đoạn (zero-downtime) cho ứng dụng có trạng thái (cả hai ứng dụng có trạng thái đều chỉ có một phần ghi dữ liệu).
- Xử lý TLS hoặc làm reverse proxy (reverse proxy của máy, ví dụ Caddy, nginx hoặc reverse proxy của DSM, vẫn đứng phía trước; các dịch vụ chỉ mở cổng trên `127.0.0.1`).
- Mã hóa, sao chép ra ngoài máy, bộ lập lịch, kênh thông báo (công cụ của nền tảng lo những việc này: restic, borg hoặc rsync trên Linux, Hyper Backup trên DSM, và bộ lập lịch của máy với thư báo lỗi của nó). Được phép có một báo cáo trạng thái gửi ra ngoài, do bộ lập lịch của máy gửi tới một bên nhận mà chủ sở hữu đã đăng ký ([ADR-0033](adr/0033-commercial-boundary-report-and-hosted-service.vi.md), Planned).
- Một dịch vụ web, tiến trình chạy nền (daemon) hay agent trên máy, một hệ thống plugin hoặc các hook chạy lệnh shell của máy. Dạng duy nhất được phép của một giao diện web là chỉ nghe trên loopback, gắn với một phiên, chỉ đọc và được khởi động bởi một lệnh chạy ở tiền cảnh, không có điểm ghi nào ([ADR-0032](adr/0032-local-session-bound-web-view.vi.md), Planned).
- Tự động cập nhật hoặc tự tìm bản phát hành mới; các tham chiếu (ref) phải được ghi rõ và chỉ được phân giải một lần.
- Mã dành cho bộ máy cơ sở dữ liệu trong phần lõi (`src/`). Mã đó nằm trong các image nhà cung cấp (provider) dưới `providers/`, được công cụ ghim phiên bản và chạy như các tác vụ bình thường ([ADR-0031](adr/0031-data-providers.vi.md), Planned).
- Quản lý container, volume hoặc network mà Ingat không tạo ra: một đối tượng không thuộc Ingat (foreign) không bao giờ bị dừng, khởi động, chạy lệnh bên trong (exec), gắn vào (mount), gắn lại nhãn, khôi phục vào hay xóa (việc tiếp quản bắt đầu từ một gói dữ liệu do chủ sở hữu tạo ra: ADR-0024); quản lý ACL (ví dụ ACL của DSM).
- Chuyển thẳng (passthrough) các lệnh có thay đổi cho Compose.
- Bất kỳ hình thức tương thích nào với công cụ cũ, một công cụ triển khai nội bộ trước đây mà Ingat thay thế (ADR-0001).
- Bảo vệ chống lại một người dùng root khác thao tác cùng lúc hoặc các cú nhấp trong giao diện quản lý container của hãng (ví dụ Container Manager trên DSM): những việc này hiện ra như sự lệch trạng thái (`changed-outside`, §11.2), chúng không bị ngăn chặn.

## 2. Bối cảnh hệ thống

```
 owner / agent (SSH, sudo -i)        host scheduler: systemd, cron, DSM (root)
            │                                    │
            ▼                                    ▼
  /srv/ingat/bin/ingat  (root-owned POSIX wrapper, pins one image; default root)
            │  docker run --rm -i [-t] --init --network host  (same-path mounts)
            ▼
  ┌──────────────── CLI container (ephemeral) ────────────────┐
  │ parse → plan (pure) → approve → start executor → follow   │
  └───────────────┬───────────────────────────────────────────┘
                  │ docker run -d --rm --name ingat-exec-<instance>
                  ▼
  ┌──────────── executor container (one per operation) ──────┐
  │ flock instance lock → step log → typed steps             │
  │   docker compose -p <instance> -f <app files> -f override│
  └───────┬───────────────┬───────────────┬──────────────────┘
          ▼               ▼               ▼
   app project      side projects       tool state
   <instance>       <instance>--r<seq>  INGAT_ROOT /srv/ingat (plain POSIX dir, root 0700)
   (live)           <instance>--t<seq>  INGAT_BACKUPS /srv/ingat-backups (root-written)
                                        Docker volumes <instance>_<store>_g<N>
```

## 3. Môi trường chạy và phân phối

### 3.1 Quyết định

Ingat được phát hành dưới dạng một image OCI đa kiến trúc, `linux/amd64` và `linux/arm64` dưới một index digest, được build từ M1 (ADR-0004, ADR-0025), và chạy qua một script khởi động (wrapper) POSIX `sh` thuộc root. Hỗ trợ arm64 chỉ được công bố sau khi làn kiểm thử CI của nó đạt (§10.1); lần triển khai thật đầu tiên là amd64. Bên trong image, nó là một gói Python 3.13 bình thường, ưu tiên thư viện chuẩn; một thư viện bên thứ ba cần một ADR và phải được khóa bằng mã băm.

Lý do, đối chiếu với thực tế của các máy:

- Python trên máy khác nhau theo nền tảng và thường cũ hoặc không có: `python3` hệ thống của DSM là 3.8 (đã hết vòng đời) và gói Python 3.9 của Synology đã hết vòng đời. Một công cụ chạy trực tiếp trên máy sẽ bị giới hạn bởi phiên bản Python cũ nhất trong số đó; việc làm cho Python của máy đủ tin cậy để chạy bằng root chính là điều đã khiến phần khởi động được bảo vệ của công cụ cũ (một công cụ triển khai nội bộ trước đây) phình to tới khoảng 4.9k dòng.
- Engine và Compose của máy khác nhau theo nền tảng. Một máy Linux dùng gói của Docker chạy Engine gốc (upstream) 29.x; Container Manager 24.0.2-1706, bản build mới nhất cho DSM 7.4, đi kèm bản build Engine 24.0.2 của Synology (API 1.43), và một bản build sau có thể thay đổi Engine, điều mà cổng phiên bản và việc chứng nhận lại sẽ xử lý (ADR-0014). Synology không bao giờ công bố phiên bản Compose đi kèm; Container Manager 24.0.2-1706 đi kèm plugin Compose v2.20.1 trên máy, có từ giữa năm 2023. Ingat không bao giờ dùng Compose của máy. Công cụ cũ đã lặng lẽ chuyển qua lại giữa các bản Compose khác nhau.
- Một digest image (một index đa kiến trúc) ghim trình thông dịch, docker CLI, Compose và git cho mọi kiến trúc, và CI kiểm thử đúng sản phẩm đó trên mỗi kiến trúc mà nó công bố hỗ trợ.
- Gắn socket Docker vào đâu thì nơi đó có quyền tương đương root; dù sao thì phương án nào cũng cần quyền truy cập Docker tương đương root.

### 3.2 Nội dung image (ghim trong `image/versions.lock`, mã kiểm tra được xác minh trong Dockerfile)

| Thành phần | Ghim | Ghi chú |
|---|---|---|
| Image nền | `python:3.13-slim-trixie@sha256:…` | Được hỗ trợ bảo mật tới 2029 |
| docker CLI | bản build tĩnh, đúng một phiên bản (hiện là 29.9.0) | 29.x nếu nó tự hạ xuống API 1.43 khi làm việc với Engine 24.0.2, nếu không thì bản 28.x mới nhất làm được việc đó (thử nghiệm sớm S4). `DOCKER_API_VERSION` không bao giờ được đặt. |
| Plugin Compose | đúng một bản v5.x (hiện là v5.6.0) | Phương án dự phòng: bản v2.x cuối cùng đạt làn Engine 24.0.2. Không bao giờ dùng Compose của máy. |
| buildx | không có | Không có trong image: image ứng dụng được build trong CI của từng ứng dụng rồi được kéo về (quyết định của chủ sở hữu OD-11, [ADR-0026](adr/0026-app-images-built-in-app-ci.vi.md)). Việc build trên máy chỉ quay lại cùng buildx thông qua mục bị hoãn trong [`ROADMAP.md`](ROADMAP.vi.md) §4. |
| git, openssh-client, tar | Gói Debian | |
| Gói `ingat` và các ứng dụng thử `fx-lite` và `fx-web` | | Được `selftest` và CI dùng |

Mỗi tệp chương trình tải về có một mã kiểm tra được ghim cho từng kiến trúc (`linux/amd64`, `linux/arm64`) trong `versions.lock`; cả hai biến thể được build từ cùng một tệp khóa thành một index đa kiến trúc. Không có thông tin bí mật nào trong image. Image là công khai (`ghcr.io/lisahq/ingat`; quyết định của chủ sở hữu OD-3), nên các máy và CI của ứng dụng kéo nó về theo digest mà không cần đăng nhập, và Docker tự chọn biến thể đúng với kiến trúc của máy.

### 3.3 Script khởi động trên máy

`install.sh` ghi ra tệp này; không bao giờ sửa nó bằng tay. Các giá trị được điền vào lúc cài đặt.

```sh
#!/bin/sh
# /srv/ingat/bin/ingat — created by install.sh. Do not edit this file by hand: the next upgrade (install.sh with a newer version) replaces it and any edits would be lost.
set -eu
INGAT_VERSION='0.1.0'
INGAT_IMAGE='ghcr.io/lisahq/ingat@sha256:<digest>'         # or sha256:<local image id> after an offline docker load
INGAT_ROOT='/srv/ingat'                                     # default roots; install --root/--backups set others
INGAT_BACKUPS='/srv/ingat-backups'
DOCKER='/usr/bin/docker'                                    # resolved once by install.sh (/usr/local/bin/docker on DSM)
PATH=/usr/bin:/bin; export PATH
[ "$(id -u)" -eq 0 ] || { echo "ingat: run as root: this command must be run by the root user (the top-level account of this machine), not by your normal user or a NAS admin user. Type sudo -i, press Enter, then run the same command again" >&2; exit 2; }
TTY=; if [ -t 0 ] && [ -t 1 ]; then TTY=-t; fi
FACTS=; for f in /etc.defaults/VERSION /etc/os-release; do [ -r "$f" ] && FACTS="$FACTS -v $f:/run/host$f:ro"; done
HOST_NAME=$(hostname); OPERATOR=${SUDO_USER:-root}
exec env -i PATH="$PATH" TERM="${TERM:-dumb}" "$DOCKER" run --rm -i $TTY --init --pull never --network host \
  --label io.github.lisahq.ingat.role=cli --log-driver none \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$INGAT_ROOT:$INGAT_ROOT" -v "$INGAT_BACKUPS:$INGAT_BACKUPS" \
  -v ingat-probe:/run/ingat/docker-root:ro $FACTS \
  -e TERM -e INGAT_ROOT="$INGAT_ROOT" -e INGAT_BACKUPS="$INGAT_BACKUPS" -e INGAT_IMAGE="$INGAT_IMAGE" \
  -e INGAT_WRAPPER_VERSION="$INGAT_VERSION" -e INGAT_HOST="$HOST_NAME" -e INGAT_OPERATOR="$OPERATOR" \
  "$INGAT_IMAGE" "$@"
```

Đặc điểm:

- **Gắn cùng đường dẫn.** Compose phân giải các đường dẫn bind, `env_file` và secret ở phía client, trong khi daemon đọc chúng trên máy, nên `INGAT_ROOT` và `INGAT_BACKUPS` được gắn vào ở đúng cùng đường dẫn. Ingat từ chối mọi nguồn bind của Compose nằm ngoài các đường dẫn mà nó cung cấp (§9.5).
- **`env -i`** bỏ đi `DOCKER_HOST`, `DOCKER_CONTEXT`, `COMPOSE_*` và mọi thứ khác từ shell của người vận hành (Compose cho phép giá trị từ shell ghi đè `--env-file`).
- **`--network host`** cho phép công cụ tới được các dịch vụ mở trên `127.0.0.1:<port>` để kiểm tra HTTP (probe) mà không cần tham gia network của bất kỳ bản cài nào (thử nghiệm sớm S7).
- **Tệp phiên bản nền tảng.** Script khởi động gắn chỉ-đọc dưới `/run/host` từng tệp đọc được trong một danh sách cố định các tệp phiên bản của nền tảng (hiện là `/etc/os-release` và `/etc.defaults/VERSION` của DSM); việc mở rộng danh sách cho một thiết bị mới là một bản phát hành của công cụ, không bao giờ là một nhánh mã theo nền tảng (§11.3).
- **Ghi log.** Logging driver mặc định của daemon khác nhau theo nền tảng (trên DSM là driver `db` của Synology: §11.2), nên Ingat không bao giờ dựa vào nó. Các tác vụ dùng terminal và container CLI ghi log bằng driver `none`, nên một bí mật hiện trên terminal không bao giờ bị bất kỳ logging driver nào ghi lại (F12): đầu ra của CLI là terminal của người vận hành, `progress.log` và `steps.jsonl` là bản ghi, và các tác vụ dùng terminal nhận driver `none` từ tệp override riêng của thao tác (§6.2). Trình thực thi (executor) và các dịch vụ dùng driver `local` có xoay vòng log, nên `ingat logs` và `SnapshotLogs` đọc một driver chuẩn (việc `db` có giữ log của container đã bị xóa hay không vẫn là Unverified).
- **Dung lượng trống của thư mục gốc Docker** được đo bằng `statvfs` trên volume `ingat-probe` thuộc công cụ (được tạo và gắn nhãn lúc cài; nó nằm trên hệ thống tệp của thư mục gốc Docker). Thư mục gốc Docker không bao giờ được bind-mount, nên mọi cách bố trí thư mục gốc Docker (`/var/lib/docker` trên máy Linux, `@docker` trên một volume DSM) đều dùng được mà không cần thay đổi gì.
- Không có cổng nghe, không có container chạy lâu dài. Container CLI thoát khi lệnh kết thúc. Planned ([ADR-0032](adr/0032-local-session-bound-web-view.vi.md)): `ingat ui` là lệnh tiền cảnh duy nhất có nghe kết nối, chỉ trên `127.0.0.1` và chỉ trong phiên của nó, trong một container CLI mà script khởi động chạy mà không có socket Docker.
- Một hook gây sập chỉ dùng cho kiểm thử (`INGAT_CRASH_AT`) chỉ tồn tại trong môi trường của các bản build kiểm thử; `env -i` của script khởi động không bao giờ truyền được nó, và `doctor` sẽ cảnh báo nếu thấy nó.

### 3.4 Cài đặt

Một `install.sh` dùng cho mọi máy. Một hồ sơ nền tảng (§11.2) chỉ thêm phần chuẩn bị riêng của nó và các giá trị nó truyền vào; việc cài đặt không bao giờ rẽ nhánh theo tên nền tảng.

**Máy bất kỳ (chủ sở hữu làm, một lần):**

1. Chuẩn bị `INGAT_BACKUPS` và bản sao của nó ở nơi khác (ngoài máy). Trên máy Linux, đó là một thư mục thuộc root trên một hệ thống tệp cục bộ (`root:root 0700`, mặc định là `/srv/ingat-backups`), được công cụ của nền tảng chép sau các lần sao lưu hằng đêm tới một nơi lưu ngoài máy do chủ sở hữu quản lý: restic hoặc borg (cả hai đều mã hóa ở phía client) hoặc rsync tới một nơi lưu đã mã hóa ([`LIFECYCLE.md`](LIFECYCLE.vi.md) §5.9, §7). Trên DSM, đó là thư mục chia sẻ (shared folder) của hồ sơ bên dưới. Chứng nhận máy (host certification) kiểm tra rằng không tài khoản nào ngoài root ghi được vào đó (§10.4).
2. Bằng root (`sudo -i`), chép `install.sh` và `SHA256SUMS` từ bản phát hành trên GitHub và chạy `sh install.sh --version 0.1.0` (thư mục gốc mặc định là `--root /srv/ingat --backups /srv/ingat-backups`; một hồ sơ nền tảng truyền giá trị riêng của nó, và hồ sơ DSM bắt buộc phải truyền). Lệnh này:
   - kiểm tra `--version` là một phiên bản semantic (nó được ghi vào script khởi động) và kiểm tra mã kiểm tra của bản phát hành, rồi kéo image về theo digest, hoặc `docker load` tệp tarball của bản phát hành cho kiến trúc của máy (`--from-tar`) sau khi kiểm tra SHA-256 của nó;
   - tạo `INGAT_ROOT` (và `INGAT_BACKUPS` khi chưa có) với `root:root 0700`: một thư mục POSIX thường trên một hệ thống tệp cục bộ;
   - tạo volume có nhãn `ingat-probe`;
   - chạy `<image> selftest --offline` với chính các cờ `docker run` của script khởi động (`--init --network host`), để một engine mà script khởi động không chạy được sẽ báo lỗi ngay tại đây, không phải ở lệnh đầu tiên;
   - tìm đường dẫn bằng `command -v docker`, ghi `bin/ingat.new`, fsync nó rồi đổi tên thành `bin/ingat` (giữ lại `bin/ingat.prev`); `--link /usr/local/bin/ingat` thêm một liên kết tượng trưng (symlink) tùy chọn cho tiện.
3. `ingat host init` ghi engine ID, DockerRootDir, các phiên bản, khả năng của máy (các trường có kiểu của `docker info` là `CpuCfsQuota`, `CpuCfsPeriod` và `MemoryLimit`; thử nghiệm sớm S11) và các dải địa chỉ cấp phát vào `host.json`, cùng với phiên bản runc, storage driver, kho image (image store), logging driver mặc định, phiên bản cgroup, kernel, kiến trúc, live restore và các tùy chọn bảo mật để dùng cho việc chứng nhận (§11), và tạo thư mục client Docker rỗng của công cụ `cache/docker-config/` (§6.1). Các lệnh có thay đổi từ chối một nền tảng chưa được kiểm thử hoặc chưa được chứng nhận (§3.6).
4. Chủ sở hữu chạy `facts.sh` (script chỉ đọc chạy trên máy, đi kèm bản phát hành) để lấy những thông tin mà container của công cụ không thấy được: phiên bản nền tảng và bản build gói Engine của nó, loại và cách bố trí hệ thống tệp của từng thư mục gốc, và dấu hiệu ACL ở nơi nền tảng có ACL (§10.4).
5. `ingat selftest --host` chứng nhận bản build nền tảng của máy cho bậc cổng (gate tier) 2 (§3.6, §10.4).

Các mục chạy theo lịch luôn gọi script khởi động bằng đường dẫn tuyệt đối (`<INGAT_ROOT>/bin/ingat`); symlink chỉ để cho tiện.

**Máy Linux dùng Docker Engine gốc (bậc hỗ trợ 1, §11.1):** Docker Engine từ kho của Docker (docker-ce) được ghim theo chuỗi phiên bản và giữ cố định (`apt-mark hold` hoặc cách tương đương của bản phân phối), hoặc một gói của bản phân phối có dòng Engine nằm trong `tested.json` (Debian 12 đi kèm `docker.io` 20.10, thấp hơn mức tối thiểu 24.0 nên không được hỗ trợ; Debian 13 đi kèm 26.1, hiện chưa có làn kiểm thử CI, nên chỉ chạy bậc cổng 0 và 1). Các việc chạy theo lịch được chạy dưới dạng unit systemd oneshot và timer với `OnFailure=` (do `schedule render --systemd` in ra, Planned M3), hoặc dưới dạng mục cron (`schedule render --cron`, Planned M3). Chứng nhận Linux chung đầu tiên được commit là Planned M4, phần việc (slice) 12.

**Hồ sơ nền tảng: Synology DSM 7.4 với Container Manager 24.0.2 (bậc hỗ trợ 2, §11.2):**

1. Trong DSM Control Panel, tạo thư mục chia sẻ `ingat-backups` với quyền **chỉ đọc** cho quản trị viên và không có quyền gì cho người khác (root vẫn ghi được; thử nghiệm sớm S9 xác nhận), rồi thêm nó vào một tác vụ Hyper Backup chạy theo lịch sau các lần sao lưu hằng đêm, có mã hóa phía client, tới một nơi lưu ngoài NAS do chủ sở hữu quản lý ([`LIFECYCLE.md`](LIFECYCLE.vi.md) §5.9, §7). Khi đó không tài khoản DSM nào ghi được vào đó qua SMB, và chứng nhận máy kiểm tra quyền này (§10.4).
2. Qua SSH bằng root, chạy `sh install.sh --version 0.1.0 --root /volume1/ingat --backups /volume1/ingat-backups`. `/volume1/ingat` được tạo qua SSH như một thư mục POSIX thường, **không phải** thư mục chia sẻ, nên nó không mang ACL của Synology và không hiện ra qua SMB. Không bao giờ chấp nhận giá trị mặc định chung trên DSM: `/srv` sẽ nằm trên phân vùng hệ thống của DSM, vốn nhỏ và có thể bị một bản cập nhật DSM đặt lại.
3. `facts.sh` còn ghi các thông tin riêng của DSM: dấu hiệu ACL, bản build Container Manager, loại và cách bố trí hệ thống tệp của volume (ext4 hoặc Btrfs).
4. Các mục Task Scheduler luôn gọi `/volume1/ingat/bin/ingat` bằng đường dẫn tuyệt đối; symlink tùy chọn `/usr/local/bin/ingat` chỉ để cho tiện, vì các bản cập nhật DSM có thể đặt lại phân vùng hệ thống.

### 3.5 Ghim phiên bản và nâng cấp

- Mỗi máy một phiên bản công cụ. Cho tới M5, nâng cấp là "chạy `install.sh` với phiên bản mới": kéo về theo digest, chạy `selftest --host` với image mới trên daemon đang chạy (nó chỉ điều khiển các bản cài `ingat-selftest-*` của chính nó, nên bậc cổng 2 không bao giờ chạy một phiên bản công cụ mà máy chưa thử qua; một kết quả `FAIL` giữ nguyên script khởi động cũ), thay script khởi động trọn vẹn trong một bước (atomic), giữ lại `bin/ingat.prev`. Việc nâng cấp từ chối khi đang có bất kỳ thao tác nào mở. Chạy `bin/ingat.prev` là cách quay lại.
- **Planned M5:** `ingat self-upgrade <version>` / `self-rollback`, cùng các bước đó nhưng gói thành một lệnh; việc dọn bớt (prune) không bao giờ xóa image công cụ hiện tại hoặc trước đó.
- **Tương thích bản ghi (ADR-0023).** Trạng thái được lưu mang `state_schema = 1`. Trong cùng một `state_schema`, các thay đổi chỉ được là thêm vào và tùy chọn: một trường mới có giá trị mặc định tái tạo đúng hành vi cũ, và không trường nào đổi nghĩa hay đổi kiểu. Bên đọc giữ lại các trường lạ thuộc schema của chính nó (khi ghi lại `record.json`, chúng được chép sang nguyên vẹn) và từ chối một schema mới hơn. Mọi thay đổi khác đều tăng `state_schema` và đi kèm một lệnh `ingat state migrate` riêng, có ghi nhật ký, chép trạng thái ra trước (Planned M5). Các bản ghi mà M2-M4 thêm vào (`held_since` ở M2, `monitor.json` ở M3, dòng dõi (lineage) được kế thừa, các mục catalog `imported`, `adopted_from`, `origin` của một bản sao lưu và giá trị nhất quán `external` ở M4) đều là thêm vào và tùy chọn theo schema 1, trong khi các bản cài sống lâu như `pg-staging` và `lite-test` trải qua nhiều lần nâng cấp công cụ. Bộ kiểm thử nâng cấp (§10.3) kiểm tra điều này từ M1.
- Việc nâng phiên bản Compose hoặc docker CLI luôn là một bản phát hành công cụ với bằng chứng CI riêng (Compose v5.5 có thể tạo lại container ở lần `up` đầu tiên sau khi nâng cấp).

### 3.6 Cổng phiên bản (các bậc, không có cách vượt qua)

Mỗi bản phát hành nhúng `tested.json`, do CI tạo ra từ các làn kiểm thử đã đạt: Engine major.minor × kiến trúc, cùng CLI và Compose đi kèm, được thêm vào như lớp cuối cùng của chính image mà các làn đã kiểm thử ([ADR-0029](adr/0029-tested-image-and-tested-json-layer.vi.md)). v0.x bắt đầu với Engine 24.0 (làn CI trên `docker:24.0.2-dind` gốc, mức tối thiểu của Engine và API) và 29.x (dòng gốc hiện tại) trên `amd64`, và chỉ thêm `arm64` cho những tổ hợp mà làn của nó đạt (§10.1). Các làn gốc (upstream) này là bằng chứng cho bậc hỗ trợ 1 (§11.1). Một Engine do hãng build (bậc hỗ trợ 2) có thể khác bản build gốc ở kernel, storage driver, phiên bản cgroup, logging driver và tùy chọn bảo mật (bản build Engine 24.0.2 của Synology khác như vậy: §11.2), nên chỉ bằng chứng dind gốc thôi không bao giờ chứng nhận được nó.

Các bậc cổng dưới đây (0, 1, 2) cho biết lệnh nào được chạy; chúng không phải các bậc hỗ trợ của §11.1.

| Bậc cổng | Lệnh | Nền tảng cần có |
|---|---|---|
| 0 | các lệnh chỉ đọc (`status`, `doctor`, `ps`, `logs`, `bundles`, `validate`, `plan`) | bất kỳ daemon cục bộ nào kết nối được |
| 1 | `backup` và `verify` trực tuyến (tác vụ băm cộng tác vụ kiểm tra) của một bản cài có manifest khai báo `online_backup` | cho phép Engine chưa được kiểm thử khi API ≥ 1.43; một cảnh báo được ghi vào thao tác và `status` hiện cần chú ý (attention) |
| 2 | mọi thứ khác, kể cả thử khôi phục, khôi phục, triển khai, start/stop, `resume` và `abandon` (nên một thao tác bị gián đoạn bởi bản cập nhật nền tảng sẽ chờ chứng nhận mới), dọn bớt, gỡ bỏ hoàn toàn, tác vụ | tổ hợp có trong `tested.json` **và** có một chứng nhận máy cho bản build nền tảng của máy: phiên bản hệ điều hành hoặc thiết bị (kể cả mức cập nhật), bản build Engine như `docker version` báo (phiên bản Engine, Git commit và thời điểm build, phiên bản containerd và runc), kernel, storage driver và kiến trúc, dưới dạng thông tin được phát hiện, không bao giờ là tên nền tảng. Đó là một chứng nhận nền tảng đã được commit và nhúng trong bản phát hành (`support/hosts/`), hoặc một kết quả `selftest --host` `PASS` tại chỗ cho cùng bản build trong `host/certifications/` (bất kỳ `PASS` nào của bản build đó đều được tính; một `FAIL` sau đó không rút lại nó). Việc giữ lại theo quy tắc (retention) thuộc bậc này: một `scheduled backup` trên nền tảng không đạt bậc này vẫn sao lưu nhưng bỏ qua phần retention, kèm một cảnh báo được ghi lại |

Nếu không có chứng nhận khớp, `status` hiện cần chú ý `uncertified` và bậc cổng 2 từ chối; vì vậy mọi bản cập nhật nền tảng (cập nhật hệ điều hành hoặc thiết bị, cập nhật Engine làm thay đổi những gì `docker version` báo, kernel hay storage driver mới; trên máy Linux là mọi lần cập nhật kernel, sau khi máy đã khởi động lại vào kernel đó) sẽ dừng bậc cổng 2 cho tới khi `selftest --host` chứng nhận bản build mới, trong khi bậc cổng 0 và 1 (sao lưu trực tuyến hằng đêm) vẫn tiếp tục. Thử khôi phục thuộc bậc cổng 2, nên một lần thử khôi phục theo lịch sẽ từ chối với mã thoát 2 cho tới lúc đó. Quy tắc này giống nhau trên mọi máy, nên cổng không bao giờ cần phân biệt bản build của hãng với bản build gốc. Bản thân `selftest --host` được phép chạy trên máy chưa được chứng nhận, vì đó là cách tạo ra một chứng nhận và nó chỉ chạm vào các bản cài `ingat-selftest-*` của chính nó: bên trong lệnh này, bậc cổng 2 chỉ miễn yêu cầu chứng nhận, và chỉ cho một bản cài có dấu selftest ghi đúng lần chạy mà tiến trình này điều khiển (lần chạy được đăng ký trong bộ nhớ và bị xóa sau khi dọn dẹp xong); nó vẫn cần một dòng Engine đã được kiểm thử và đầy đủ thông tin về bản build nền tảng. Không có cờ hay tệp nào nới rộng bậc cổng 2: một dấu do một lần chạy bị giết để lại không miễn được gì, và việc hỗ trợ một dòng Engine hay kiến trúc mới là một bản phát hành công cụ có bằng chứng CI (ADR-0014). Mỗi bản ghi thao tác lưu phiên bản Engine, API, CLI và Compose, kiến trúc, phiên bản hệ điều hành hoặc thiết bị và phiên bản công cụ.

## 4. Mô hình thực thi

### 4.1 Các tiến trình

| Tiến trình | Được khởi động bởi | Thời gian sống | Giữ khóa của bản cài |
|---|---|---|---|
| Container CLI (`role=cli`) | script khởi động | một lệnh | chỉ với các tác vụ dùng terminal chạy ở tiền cảnh (§4.3) và ba lệnh ngắn chỉ thay đổi trạng thái của công cụ, không bao giờ đụng tới Docker: `host init` (khóa máy), `init` (khóa máy), `secret set` (khóa bản cài). Planned: `report enroll` và `report disable` (khóa máy, [ADR-0033](adr/0033-commercial-boundary-report-and-hosted-service.vi.md)); `ingat ui` chạy suốt phiên của nó mà không có socket ([ADR-0032](adr/0032-local-session-bound-web-view.vi.md)) |
| Container trình thực thi `ingat-exec-<instance>` (`role=exec`) | CLI, qua socket, `docker run -d --rm --init --network host --stop-timeout 120 --log-driver local` (xoay vòng log như ở §6.2) với cùng các mount, image và danh sách biến môi trường được phép | một thao tác | có, trong suốt thao tác |
| Trình thực thi của máy `ingat-exec--host` | CLI | một thao tác ở phạm vi máy (`selftest`, dọn bớt image, tự nâng cấp) | khóa máy |
| Container tác vụ `<instance>-x<seq>-<step>-a<attempt>` (`role=task`) | trình thực thi, `compose run --rm --no-deps -T --name … --label …` (không có `-T` với `stdin = "terminal"`, §4.3) | một lần thử của một bước | không (trình thực thi giữ khóa) |

Tên bản cài không được chứa `--` ([`MANIFEST_SPEC.md`](MANIFEST_SPEC.vi.md) §6.1), nên `ingat-exec--host`, `<instance>--r<seq>` và `<instance>--t<seq>` không bao giờ trùng với một bản cài.

### 4.2 Các thao tác thay đổi Docker chạy tách rời (ADR-0005)

Mọi thao tác có lấy khóa mà tạo, khởi động, dừng hoặc xóa một đối tượng Docker đều chạy trong một trình thực thi. Ngoại lệ duy nhất là các tác vụ dùng terminal chạy ở tiền cảnh (§4.3). `host init`, `init` và `secret set` lấy khóa của chúng trong CLI vì chúng chỉ thay đổi trạng thái của công cụ, chạy nhanh và ghi trọn vẹn trong một bước (atomic).

1. CLI lập kế hoạch (thuần, §5.3), in kế hoạch ra, lấy sự duyệt, rồi ghi kế hoạch đã duyệt một lần duy nhất (write-once) vào `plans/<plan-hash>.json`.
2. CLI khởi động trình thực thi. Tên container của nó là một khóa loại trừ thứ hai: Docker từ chối tên trùng, nên hai thao tác trên một bản cài không bao giờ cùng khởi động được.
3. Trình thực thi lấy `flock` không chờ trên `instances/<i>/lock`, kiểm tra không có thao tác nào đang mở, quan sát lại dấu vân tay (fingerprint) và so với kế hoạch. Nếu không khớp, thao tác đóng lại với kết quả `refused-stale` và không ghi gì vào bản cài (mã thoát 1). Một thao tác chạy một project cách ly sau đó cấp phát subnet trong dải của nó (§7.4) trước mọi công việc trên bản cài.
4. CLI theo dõi `ops/<seq>-<kind>/progress.log` và `steps.jsonl` và trả về kết quả từ tệp lần chạy `host/runs/<run-id>.json`, tệp mà trình thực thi ghi sau khi đã nhả khóa ở mọi lần chạy, kể cả lần bị từ chối (exit, code, message, `next`, cảnh báo). Nếu trình thực thi ngừng chạy mà không có tệp đó, CLI trả về `result.json` của thao tác, hoặc nếu không có thì trả về 4 (`executor-vanished`) và `status` hiện bước đang mở.
5. Mất SSH, đóng terminal, SIGHUP, bộ lập lịch hết thời gian chờ hoặc giết CLI chỉ dừng phần theo dõi (follower). Thao tác vẫn chạy tới cùng. `ingat attach <i>` theo dõi lại.

### 4.3 Tác vụ một bước chạy ở tiền cảnh

Một tác vụ có `stdin` hoặc `stdout` là `terminal` (ví dụ đặt lại mật khẩu có hỏi mật khẩu mới, hoặc bước khởi tạo lần chạy đầu in ra một mã thiết lập) chạy ngay trong container CLI, vì đầu ra của nó phải tới được terminal này và không bao giờ bị thu lại. Đó là một thao tác một bước: CLI lấy khóa của bản cài, ghi ý định vào nhật ký, chạy container tác vụ với cái tên xác định trước của nó, rồi đóng lại. Nếu CLI chết, kernel nhả khóa và bước kiểm tra container mồ côi (§4.5) của lệnh kế tiếp xử lý container tác vụ; `resume` của một thao tác như vậy lại chạy trong CLI, trên terminal đang chạy lệnh đó.

- `stdin = "terminal"`: `compose run` chạy **không có** `-T`, gắn với TTY của container CLI, để lời nhắc của ứng dụng có thể tắt hiển thị ký tự gõ (echo) (một tác vụ đặt lại mật khẩu đọc mật khẩu ở lời nhắc như vậy). Lệnh từ chối (mã thoát 2) khi CLI không có TTY. Một bài kiểm thử khẳng định lời nhắc chạy với echo đã tắt.
- Chỉ `stdout = "terminal"`: vẫn giữ `-T`; đầu ra được truyền thẳng ra terminal và không bao giờ bị thu lại.
- **Trong lúc cài đặt đang tạm dừng.** Một tác vụ mà lần tạm dừng cho phép (ví dụ bước khởi tạo lần chạy đầu của ứng dụng SQLite) được ghi nhật ký như một bước của thao tác đang tạm dừng, trong `ops/<seq>/steps.jsonl` của nó, dưới cùng khóa bản cài và cùng quy tắc container mồ côi; nó không mở thao tác thứ hai (F5).

### 4.4 Hủy

- Trong phần theo dõi, Ctrl-C hỏi "tách ra hay yêu cầu hủy"; khi không có terminal, SIGINT và SIGTERM có nghĩa là tách ra.
- `ingat cancel <i>` (hoặc phần theo dõi) ghi `ops/<seq>/cancel`. Trình thực thi tôn trọng yêu cầu này ở ranh giới bước kế tiếp và bên trong các vòng chờ. Một yêu cầu hủy trước mọi tác động sẽ đóng thao tác ở trạng thái `abandoned` (mã thoát 130); sau một tác động, nó theo quy tắc lỗi với mã `cancelled` (mã thoát 3: [`LIFECYCLE.md`](LIFECYCLE.vi.md) §3.2). `cancel` từ chối một thao tác đang tạm dừng, vì tệp này cũng sẽ kết thúc các tác vụ mà lần tạm dừng cho phép và cả việc tiếp tục nó: thay vào đó hãy tiếp tục (resume) hoặc bỏ dở (abandon) nó.
- **Các bước có thể ngắt** (kéo image, dump vào vùng chuẩn bị (staging), phép kiểm tra (probe), các bước thử khôi phục) được dừng như sau: trình thực thi chạy `docker stop -t <grace>` trên container tác vụ có tên của bước và chờ nó thoát **trong khi vẫn giữ khóa**, rồi quan sát bước đó. Chỉ giết client `compose run`/`exec` thôi không dừng được tiến trình ở phía server.
- **Các bước nguyên tử** (cập nhật dữ liệu (migrate), khôi phục vào một vùng dữ liệu, chuyển vùng dữ liệu, một mục xóa) chạy cho tới khi tiến trình con của chúng trả về, chỉ bị giới hạn bởi thời gian chờ đã khai báo. Khi hết thời gian chờ, container tác vụ bị dừng và bước trở thành `unknown`.
- **Tín hiệu gửi tới trình thực thi.** Trình thực thi xử lý SIGINT, SIGTERM, SIGHUP và SIGQUIT như nhau: mỗi tín hiệu là một yêu cầu hủy, được tôn trọng như trên. Nó được khởi động với `--stop-timeout 120`, nên `docker stop ingat-exec-<i>` cho nó hai phút để tới một điểm an toàn. Một bước nguyên tử không dừng vì yêu cầu hủy; nếu hết thời gian chờ trước, Docker giết trình thực thi và bước đó được quan sát ở lệnh kế tiếp. Khi máy khởi động lại, thời gian chờ tắt máy của chính daemon rút ngắn khoảng thời gian này; bước bị gián đoạn khi đó cũng được quan sát theo cùng cách. Bộ kiểm thử mất phiên gửi từng tín hiệu thật (§10.3).
- `docker kill ingat-exec-<i>` là biện pháp cuối cùng có trong tài liệu: kernel nhả flock và bước đang mở được quan sát ở lệnh kế tiếp.

### 4.5 Kiểm tra container mồ côi

Trước `resume`, `abandon` hoặc bất kỳ thay đổi mới nào sau khi một trình thực thi đã chết, Ingat liệt kê mọi container tác vụ (`role=task`) của thao tác đang mở, dù đang chạy hay đã thoát, có nhãn `…ingat.op=<seq>` (F15):

- Một container **đang chạy** khiến lệnh bị từ chối (`task-running`, mã thoát 2), kèm theo đúng lệnh `docker stop` cần chạy được in ra, mà `status` nêu là `next`. Ingat không bao giờ quan sát hay chạy lại một bước có container tác vụ còn sống.
- Một container **đã thoát** thuộc lần thử hiện tại của bước, nằm trong một project Compose của chính bản cài, là bằng chứng: mã thoát và thời điểm kết thúc của nó được ghi nhật ký làm bằng chứng `observe` cho bước của nó (bảng mã thoát khi đó quyết định kết quả như thể trình thực thi đã thấy nó). Một container đã được tạo nhưng chưa bao giờ khởi động, hoặc một container của lần thử trước, không chứng minh được gì. Chỉ sau khi có mục nhật ký, mọi container như vậy trong các project của chính bản cài mới bị xóa, sau khi được chứng minh lại (cùng nhãn) ngay trước khi xóa (F8); một container nằm ngoài các project đó không phải bằng chứng và cũng không bị xóa.
- Một container **bị thiếu** (đã bị `--rm` xóa trước khi đọc được mã thoát; thử nghiệm sớm S14) không cho bằng chứng nào; quy tắc `observe` riêng của bước sẽ quyết định (chạy lại an toàn khi lặp (idempotent), `observe = "schema"`, hoặc `unknown`). Không bao giờ giả định một mã thoát. Trên Engine gốc 24.0.2 và 29.9.0, việc xóa được quan sát là do daemon làm (bằng chứng từ dind thử cục bộ; còn Unverified trong CI và trên máy đầu tiên), nên đây là trường hợp thường gặp sau một lần sập.

Một lần làm lại luôn nhận số lần thử kế tiếp, nên tên container của nó không bao giờ trùng với container còn sót lại. Các container của project cách ly của một thao tác bị gián đoạn là đầu ra tạm của nó, không phải container mồ côi: `resume` gỡ project xuống trước khi làm lại một bước tạm, và `abandon` chạy `Teardown` của nó ([`LIFECYCLE.md`](LIFECYCLE.vi.md) §3.4). Các bước `exec` có thay đổi (không có container riêng) chỉ được phép bên trong project cách ly ([`LIFECYCLE.md`](LIFECYCLE.vi.md) F15); việc gỡ project xuống sẽ kết thúc tiến trình của bước như vậy trước mọi lần làm lại.

## 5. Mô-đun và phân lớp

### 5.1 Các lớp

```
cli  ──►  ops  ──►  core (plan, approval, executor, steps, journal)
                      │            │
                      ▼            ▼
              model, policy     adapters (runner, compose, docker, override, git, http_probe)  &  store (fs, locks, state)
              (pure, no I/O)
```

Mũi tên là hướng import duy nhất được phép; một bài kiểm thử dùng `ast` của thư viện chuẩn bắt buộc điều này.

| Mô-đun | Trách nhiệm | Giới hạn (dòng) |
|---|---|---|
| `brand.py` | Tên sản phẩm, tên CLI, không gian tên nhãn, tiền tố biến môi trường, thư mục gốc mặc định. Nơi duy nhất các chuỗi cố định này được phép xuất hiện. | 60 |
| `cli/commands.py`, `cli/render.py`, `cli/follow.py` | Bảng lệnh (lớp duyệt, khóa, cách duyệt, chạy không cần người, tiền cảnh), phân tích tham số, đầu ra cho người đọc và `--json`, mã thoát; khởi động và theo dõi trình thực thi | 600 |
| `model/manifest.py`, `model/instance.py`, `model/toml_read.py` | Phân tích `tomllib` nghiêm ngặt (một bộ đọc có kiểu) và kiểm tra ý nghĩa của `ingat.toml` và `instance.toml` | 600 + 300 |
| `model/templates.py` | Bộ từ vựng mẫu đóng và bộ điền mẫu của nó (chỉ cho phần tử argv và giá trị biến môi trường, không bao giờ qua shell) | 200 |
| `model/records.py`, `model/bundle.py` | Các kiểu bản ghi (máy, bản cài, lần triển khai, thao tác, lần kiểm tra), định dạng `bundle.json`, JSON chuẩn hóa | 400 |
| `policy/compose_policy.py`, `policy/compose_text.py` | Danh sách cấm áp lên mô hình `config --format json` đã gộp, cộng với kiểm tra khả năng của máy; quy tắc trên văn bản thô của các tệp Compose của ứng dụng (§9.5) | 300 |
| `policy/gate.py`, `policy/retention.py` | Các bậc của cổng phiên bản; chọn bản sao lưu giữ lại (retention) | 300 |
| `core/plan.py` | Khung lập kế hoạch thuần: đầu vào cộng dấu vân tay quan sát được cho ra một danh sách bước có thứ tự và một mã băm chuẩn hóa | 300 |
| `core/steps.py`, `core/tasks.py`, `core/probes.py` | Tập đóng các loại bước với `apply`, `observe`, và `undo` hoặc một dấu điểm không quay lại (forward marker) ([`LIFECYCLE.md`](LIFECYCLE.vi.md) §3.3) | 600 |
| `core/executor.py`, `core/opening.py`, `core/journal.py` | Khóa, mở và tham gia một thao tác, nhật ký ghi ý định trước tác động, tiếp tục, bỏ dở, tự động bỏ dở, hủy, kiểm tra container mồ côi | 600 |
| `core/approval.py` | Tệp kế hoạch, xác nhận bằng cách gõ, thử thách lớp D (chỉ với TTY) | 200 |
| `adapters/runner.py` | Nơi duy nhất dùng `subprocess`: chỉ argv, biến môi trường theo danh sách cho phép, thời gian chờ, nhóm tiến trình riêng, luồng tệp stdin/stdout chính xác từng byte, thu lại luồng văn bản có giới hạn và đã che bí mật, có giữ lại phần đuôi | 400 |
| `adapters/compose.py`, `adapters/docker.py` | Bộ chuyển đổi (adapter) có kiểu cho Compose và Docker CLI. Phương thức truy vấn dùng tự do; phương thức có thay đổi cần một `EffectToken` mà chỉ trình thực thi cấp, bên trong một bước đang mở và đã ghi nhật ký. | 600 + 400 |
| `adapters/override.py` | Tạo YAML override từ dữ liệu (§6.2) | 250 |
| `adapters/git.py`, `adapters/http_probe.py` | Clone trần (bare clone), lấy một ref chính xác, xuất bằng `git archive`; client kiểm tra HTTP phía công cụ | 200 + 150 |
| `store/fs.py`, `store/locks.py`, `store/state.py` | Tệp tạm với `O_EXCL` cộng `O_NOFOLLOW`, fsync tệp và thư mục, đổi tên, ghi một lần, duyệt cây không đi theo liên kết; flock; bố cục thư mục trạng thái và ghi bản ghi trọn vẹn trong một bước. Không bao giờ `sync(2)`. | 600 |
| `ops/*.py` | init, prepare, deploy, backup, verify, restore, lifecycle, tasks, retention, status/doctor, host, selftest, validate, và ở M4 là import, kể cả gói dữ liệu tiếp quản (các bộ lập kế hoạch xây trên `core/plan.py`) | khoảng 2,000 (M1-M3) |

Không mô-đun nào vượt quá 600 dòng (ADR-0021). Mã M1 vượt hai giới hạn theo hàng ở trên (tính theo dòng mã chạy): bộ bước, khoảng 830, và `ops/*.py`, khoảng 2,700 chỉ riêng cho M1; mọi mô-đun vẫn nằm trong 600 dòng, và một giới hạn hàng mới cần một ADR.

### 5.2 Các ranh giới được kiểm thử bắt buộc

- Chỉ `adapters/runner.py` import `subprocess`.
- Chỉ `store/` ghi dưới `INGAT_ROOT` hoặc `INGAT_BACKUPS`.
- Hướng import theo §5.1; giới hạn của các mô-đun được giữ đúng.
- **Chuỗi cấm** trong `src/` (ứng dụng thử và bài kiểm thử được dùng tên bộ máy cơ sở dữ liệu): `postgres`, `pg_`, `sqlite`, `alembic`, `backend`, `frontend`, `uvicorn`, `node`, và tên của các ứng dụng đã biết dùng Ingat, vốn không xuất hiện ở đâu trong repository công khai này (quyết định của chủ sở hữu OD-3) và vì thế không được liệt kê ở đây. Bước grep chuỗi cấm của T0 đọc các tên đó từ một bí mật của CI (không bao giờ được commit); một lần chạy không có bí mật đó, ví dụ một bản fork, bỏ qua phần kiểm tra này và báo là đã bỏ qua. Các chuỗi thương hiệu chỉ xuất hiện trong `brand.py`.
- Bài kiểm thử khẳng định hành vi qua CLI và các tác động quan sát được (tệp, danh sách đối tượng Docker, mã thoát, JSON), không bao giờ qua văn bản mã nguồn hay tên nội bộ (các bộ kiểm thử của công cụ cũ đã khẳng định cách bố trí mã nguồn và vì thế làm nó không đổi được nữa).

### 5.3 Lập kế hoạch thuần

Mọi phép kiểm tra chạy trong một giai đoạn lập kế hoạch thuần, trên trạng thái đã ghi cộng với quan sát chỉ đọc: `docker ps/inspect` lọc theo nhãn, `compose config`, đọc tệp, `statvfs`, `/proc/meminfo`. Việc lập kế hoạch không bao giờ tạo container, tag image, volume, network hay tệp dưới `instances/`. Bất cứ việc gì tạo đối tượng Docker đều là một bước. Việc lập kế hoạch chỉ ghi vào các bộ nhớ đệm đặt tên theo nội dung (content-addressed) `cache/git/` và `cache/src/` (một bản xuất được giải nén vào một thư mục tạm cùng cấp dưới một khóa theo từng commit, đặt chỉ-đọc rồi đổi tên vào chỗ), và tạo các đầu vào Compose cần tệp vào tệp tạm dưới `/dev/shm` của container CLI, rồi xóa chúng đi (phép kiểm tra quy tắc an toàn cho cấu hình Compose (policy) của `doctor` cũng vậy). Việc kéo image ứng viên diễn ra trong `prepare` (lớp B, [`LIFECYCLE.md`](LIFECYCLE.vi.md) §4.2), vốn chỉ ghi vào các bộ nhớ đệm đặt tên theo nội dung (`cache/`, `instances/<i>/candidates/`, sổ image) mà quy tắc không để lại dấu vết (no-trace) miễn trừ theo tên.

## 6. Cách gọi Compose

### 6.1 Hợp đồng (ADR-0006)

Mọi lệnh gọi Compose có dạng này và chạy từ trình thực thi với một môi trường rỗng cộng `PATH`, `HOME` và `DOCKER_CONFIG=<INGAT_ROOT>/cache/docker-config` (do `host init` tạo; mọi lệnh trừ `version` đều từ chối với mã thoát 2, mã `docker-config`, khi thư mục này không rỗng, vì một cấu hình client có thể thêm biến proxy vào mọi container hoặc chạy chương trình hỗ trợ đăng nhập (credential helper)):

```
docker compose -p <project> --project-directory <export>
  -f <export>/<app compose file>… -f <op>/override.yaml
  --env-file <op>/compose.env [--profile <p>…] <verb> [explicit service list]
```

- `<project>` là tên bản cài, hoặc `<instance>--r<seq>` / `<instance>--t<seq>` cho các lần chạy cách ly. `-p` ghi đè mọi `name:` cấp cao nhất trong tệp của ứng dụng (tệp production của ứng dụng PostgreSQL khai báo `name:` riêng).
- `<export>` là bản xuất `git archive` chỉ-đọc của commit đã triển khai (`cache/src/<commit>/`), hoặc thư mục `app/` của bản cài với ứng dụng lấy từ image.
- `compose.env` do Ingat tạo ra từ các tham số (param) đã khai báo. Mọi giá trị đều được đặt trong nháy đơn; một giá trị chứa `'`, dấu xuống dòng hoặc NUL sẽ bị từ chối (thử nghiệm sớm S6 xác nhận cách đọc nguyên văn).
- `up` luôn nhận `--no-build --pull never` và một danh sách dịch vụ ghi rõ. Các lần chạy tác vụ là `run --rm --no-deps -T --name <instance>-x<seq>-<step>-a<attempt> --label …ingat.op=<seq> --label …ingat.step=<n> --label …ingat.role=task` (chỉ không có `-T` với `stdin = "terminal"`, §4.3). Các phụ thuộc được khởi động bởi các bước `Up` riêng có chờ sẵn sàng (`compose run --no-deps` bỏ qua `depends_on: service_healthy`).
- Mô hình đã gộp (`config --format json --no-env-resolution`) được tạo với cùng đầu vào và **chỉ** được dùng cho phép kiểm tra policy (§9.5) và mã băm dấu vân tay. `--no-env-resolution` giữ nội dung của `env_file` (ví dụ thông tin đăng nhập SMTP của ứng dụng SQLite) ngoài mô hình, nên mô hình và mã băm của nó không bao giờ chứa bí mật; bản thân mô hình không bao giờ được lưu trong bản sao lưu. Ingat không bao giờ thực thi từ một mô hình được tạo lại, vì việc chuyển qua lại các ký tự thoát `$$` bị lệch giữa các phiên bản Compose (công cụ cũ đã phải hiệu chỉnh riêng cho từng phiên bản vì điều này).

### 6.2 Tệp override được tạo ra

`adapters/override.py` ghi một tập con YAML nhỏ từ dữ liệu: các giá trị đơn được đặt trong nháy kiểu JSON cộng với tag `!reset`. Ví dụ cho một bản triển khai đang chạy của ứng dụng PostgreSQL (bản cài `pg-staging`):

```yaml
# This app declares its own json-file logging on every service, so the override adds none;
# an app that declares none gets driver local.
services:
  db:      {image: "sha256:3f1c…", pull_policy: "never", labels: {"io.github.lisahq.ingat.instance": "pg-staging", "io.github.lisahq.ingat.role": "app"}}
  backend: {image: "sha256:9a0b…", pull_policy: "never", build: !reset null, labels: {…}}
  web:     {image: "sha256:77de…", pull_policy: "never", build: !reset null, labels: {…}}
  migrate: {image: "sha256:9a0b…", pull_policy: "never", build: !reset null, labels: {…}}
volumes:
  postgres_data: {name: "pg-staging_pgdata_g1", external: true}
networks:
  internal: {labels: {"io.github.lisahq.ingat.instance": "pg-staging"}}
  edge:     {labels: {"io.github.lisahq.ingat.instance": "pg-staging"}}
```

Nó luôn: ghim mọi dịch vụ vào image ID đã ghi với `pull_policy: never` và `build: !reset null` (thử nghiệm sớm S5; phương án dự phòng: kiểm tra tag → ID đã ghi ngay trước mỗi lệnh gọi Compose và từ chối nếu không khớp); thêm các nhãn định danh ổn định; cho mọi dịch vụ không khai báo `logging` riêng một khối `logging` rõ ràng (`driver: local`, `max-size: 10m`, `max-file: 3`), vì driver mặc định của daemon khác nhau theo nền tảng (trên DSM là `db` của Synology: §11.2; thử nghiệm sớm S5) — khối này là một hằng số của công cụ, nên nó không bao giờ làm đổi mã băm cấu hình giữa các lần triển khai, và việc thay đổi nó là một bản phát hành công cụ sẽ tạo lại các dịch vụ, giống như nâng phiên bản Compose; với một bước có tác vụ dùng `stdin` hoặc `stdout = "terminal"`, tệp override riêng của thao tác đặt `logging: {driver: "none"}` trên dịch vụ của tác vụ đó bất kể `logging` riêng của nó (một lần chạy riêng lẻ `compose run --no-deps` không tạo lại dịch vụ đang chạy, nên mã băm cấu hình đang chạy không bị ảnh hưởng); gán mỗi kho dữ liệu (store) kiểu volume đã khai báo vào vùng dữ liệu hiện tại của nó dưới dạng volume bên ngoài (external), để Compose không bao giờ xóa được nó. Với các lần chạy cách ly, nó còn đặt mọi network thành `internal: true` và đặt lại tên của nó (`name: !reset null`, để Compose đặt tên là `<project>_<key>` và một lần chạy cách ly không bao giờ tham gia được network đang chạy), xóa các cổng mở ra ngoài bằng `ports: !reset []`, cho các tham số subnet giá trị lấy từ dải, gán các kho dữ liệu vào vùng dữ liệu cách ly, thêm nhãn op (một project cách ly là mới với mỗi thao tác) và thêm môi trường `[holds]` ([`LIFECYCLE.md`](LIFECYCLE.vi.md) §5.7).

**Mã băm cấu hình ổn định.** Nhãn là một phần của mã băm cấu hình theo từng dịch vụ của Compose, nên tệp override chỉ đặt định danh ổn định trên các dịch vụ đang chạy: `instance` và `role`. Volume có thêm `store`, `generation` và `purpose`; container tác vụ nhận `op`, `step` và `role=task` từ `compose run --label`, vốn không bao giờ đi vào mã băm của dịch vụ. Số thứ tự lần triển khai chỉ được ghi trong `deployments/<seq>.json`; một container đang chạy được khớp với một lần triển khai bằng image ID cộng mã băm cấu hình. Mọi đường dẫn mà mô hình đang chạy tham chiếu đều ổn định hoặc đặt tên theo nội dung: tệp env của ứng dụng sau khi tạo được lưu là `instances/<i>/env/<sha256>.env`, nên đường dẫn của nó chỉ thay đổi khi nội dung thay đổi. Vì vậy mã băm của một dịch vụ chỉ thay đổi khi cấu hình thực tế của nó thay đổi: một lần triển khai chỉ đổi mã không bao giờ tạo lại PostgreSQL, và một thay đổi chỉ về cấu hình tạo lại đúng các dịch vụ bị thay đổi (bộ kiểm thử phạm vi tạo lại, §10.3; thử nghiệm sớm S5 ghi lại những đầu vào nào đi vào mã băm).

## 7. Bố cục trên đĩa, bản ghi và khóa

### 7.1 Bố cục

```
/srv/ingat/                             INGAT_ROOT (default; /volume1/ingat in the DSM profile): root:root 0700,
                                        plain POSIX directory on a local filesystem (on DSM never a shared folder)
  bin/ingat, bin/ingat.prev             wrapper
  host.json                             state_schema, engine_id, roots, docker path, DockerRootDir, label namespace,
                                        capabilities (CPU CFS, memory limits), runc, storage-driver, image-store, logging-driver,
                                        cgroup, kernel, architecture, live-restore and security-option facts,
                                        tool image (current, previous), isolation and port pools
  host.lock                             flock: instance creation, host-scope operations (selftest, image prune, self-upgrade) (never unlinked)
  host/images/<image-id>/<instance>-<seq>.json  image ledger, one write-once provenance entry per image and operation:
                                        {refs, digest, commit, release, labels, pulled_by}; references are computed from records
  host/allocations/<kind>-<value>.json  one write-once entry per allocated port or subnet (`port-20090.json`,
                                        `subnet-10.250.0.0_24.json`): {instance, param, purpose, op}; an
                                        isolated run's subnet entry is removed by its teardown
  host/attention.json                   last attention set seen by `scheduled status` (§4.15 of LIFECYCLE.md)
  host/certifications/<stamp>-<kind>.json  host check (`host-check`) and selftest (`selftest`) evidence, write-once
  host/runs/<run-id>.json               the outcome of every executor run, a refused one included (write-once; M1 removes only a selftest run's own)
  plans/<plan-hash>.json                approved or approvable plans (write-once; refused after 24 h; M1 removes only a selftest run's own)
  cache/git/<repo-id>.git               tool-owned bare clones (hooks disabled, fsckObjects, ssh/https, file only for fixtures)
  cache/src/<commit>/                   read-only `git archive` exports (Compose project directory)
  cache/fixtures/<run-id>/              selftest's fixture repositories, the only `file://` sources (ADR-0027)
  cache/docker-config/                  the tool's own Docker client config directory, always empty (§6.1)
  keys/<name>/{id_ed25519,known_hosts}  read-only deploy keys and pinned host keys (0600)
  inbox/                                owner-dropped task input files (0700)
  instances/<name>/
    instance.toml                       owner-edited (0600); Ingat never rewrites it
    lock                                flock file, never unlinked
    record.json                         the only mutable instance file: state, lineage, disposable, current deployment,
                                        generation per store, open op, held_since, next_seq, adopted_from (M4)
    secrets/                            0700: generated or set secret files (mode per manifest); env/<KEY> (0600)
    placeholder/                        empty 0555 directory bound to task_dir params outside their task
    app/                                manifest and compose file for image-sourced apps (owner-provided)
    selftest.json                       selftest instances only: the run that created the instance (LIFECYCLE.md §3.3)
    candidates/<commit>-<refs>.json     prepared candidate (keyed by commit and a hash of its image references):
                                        images, digests, labels check, export path
    env/<sha256>.env                    rendered app env files, content-addressed, write-once (0600)
    deployments/<seq>.json              immutable deployment record (the deployment seq lives only here, never in a label)
    deployments/<seq>/                  snapshot: manifest bytes, compose file hashes, override.yaml, compose.env, app env hash, model.sha256
    ops/<seq>-<kind>/                   plan.json, steps.jsonl, progress.log, result.json, cancel,
                                        artifacts/ (bounded, redacted step outputs and log snapshots, 0600),
                                        stage/ (bundle being built), in/ (private input copies; `in/` and an
                                        empty `stage/` are removed when the operation closes), env/, secrets/ (a
                                        drill's throwaway secrets)
    catalog/<bundle-id>.json            write-once seal record: bundle hash, class, size, created_at;
                                        <bundle-id>.pruned.json is the tombstone retention writes
    verifications/<bundle-id>.json      append-only JSON Lines, one verification record per line (outside the sealed bundle)
    reports/                            recorded read-only task reports, for example an invariant check (0600)
  data/<name>/<store>/g<N>/             bind-store generations (owner/mode from the manifest), marker g<N>.json beside each
/srv/ingat-backups/                     INGAT_BACKUPS (default; /volume1/ingat-backups in the DSM profile): written only
                                        by root, the source of the off-host copy (on DSM a shared folder, read-only for
                                        administrators, the Hyper Backup source)
  <name>/<bundle-id>/                   sealed bundles: bundle.json, SHA256SUMS, payload/<entry>/…, meta/
  <name>/.incoming-<bundle-id>/         a copy in progress (never read as a bundle)
Docker: volumes <name>_<store>_g<N> (live generations), <name>_<store>_t<seq> (drills), ingat-probe;
        labels io.github.lisahq.ingat.{instance,role} on live services, {instance} on networks, {instance,store,
        generation,purpose} on volumes; plus {op} on drill generations and every object of an isolated project,
        and {op,step,role=task} on task containers (§6.2); never a per-deployment value
```

### 7.2 Quy tắc lưu trữ (ADR-0008)

- **Container không bao giờ đọc từ hay ghi vào `INGAT_BACKUPS`.** Mọi việc đọc ghi của tác vụ đều dùng `INGAT_ROOT`: vùng chuẩn bị (stage), bản sao đầu vào riêng, các vùng dữ liệu. Trên DSM, điều này còn giữ các container tác vụ, vốn chạy với uid cố định (ví dụ uid 10001 trong image của cả hai ứng dụng có trạng thái), tránh xa thư mục chia sẻ, nơi ACL ghi đè quyền POSIX.
- **Chỉ root ghi vào `INGAT_BACKUPS`**: trình thực thi chép một kết quả đã niêm phong vào `<name>/.incoming-<id>/`, fsync mọi tệp và thư mục, rồi đổi tên nó thành `<name>/<id>/` bên trong `INGAT_BACKUPS`. Trên bất kỳ máy nào, hai thư mục gốc có thể nằm trên hai hệ thống tệp khác nhau, và trên một volume Btrfs của DSM mỗi thư mục chia sẻ là một subvolume, nên việc đổi tên từ `INGAT_ROOT` vào đó lỗi với `EXDEV`; việc công bố luôn là chép-rồi-đổi-tên bên trong thư mục gốc sao lưu, nên một cách làm dùng được cho mọi cách bố trí.
- **Bản sao đầu vào.** Một tác vụ đọc một bản sao lưu nhận một bản sao riêng trong `ops/<seq>/in/`, được kiểm tra mã băm trong lúc chép, thuộc uid thực tế của tác vụ (từ `user` của manifest hoặc `Config.User` của image), quyền `0550`/`0440`. Mã băm được kiểm tra lại sau mỗi bước đã thấy bản sao đó.
- **SQLite và dữ liệu ứng dụng nằm trên đĩa cục bộ.** Các vùng dữ liệu kiểu bind nằm dưới `INGAT_ROOT/data/` trên một hệ thống tệp cục bộ (ví dụ ext4, XFS hoặc Btrfs), không bao giờ trên ổ chia sẻ qua mạng (SMB/NFS), thư mục chia sẻ của DSM hay thư mục đồng bộ (cơ chế khóa tệp của SQLite không đáng tin ở đó). Bind mount bỏ qua quyền của các thư mục cha trên máy, nên một thư mục cha gốc có quyền `0700` không chặn uid 10001 bên trong container.
- Việc chứng nhận kiểm tra tài khoản sở hữu và quyền truy cập của cả hai thư mục gốc và việc không tài khoản nào ngoài root ghi được vào `INGAT_BACKUPS`, để retention không bao giờ xóa bên trong một cây thư mục mà người dùng khác có thể thay đổi; trên DSM nó còn kiểm tra `INGAT_ROOT` không hiện dấu ACL `+`, `synoacltool -get` trả về rỗng và quản trị viên chỉ có quyền đọc trên thư mục chia sẻ. Bản thân Ingat không bao giờ đọc hay thay đổi ACL. Retention xóa bằng cách duyệt theo descriptor, không đi theo liên kết, và chứng minh lại từng mục (F8).

### 7.3 Bản ghi

- `record.json` được `init` ghi ra và sau đó được thay thế trọn vẹn trong một bước dưới khóa của bản cài, chỉ bởi trình thực thi (hoặc CLI khi chạy một tác vụ dùng terminal) ở những thời điểm xác định rõ: khi nó mở một thao tác, trong các bước `Record` của nó ([`LIFECYCLE.md`](LIFECYCLE.vi.md) §3.3) và khi nó đóng một thao tác, trước `result.json` ([`LIFECYCLE.md`](LIFECYCLE.vi.md) §3.1); các trường lạ của cùng `state_schema` được chép sang nguyên vẹn (§3.5).
- Bản ghi lần triển khai, kế hoạch, mục catalog và kết quả chỉ được ghi một lần (tạo độc quyền, fsync tệp và thư mục).
- `steps.jsonl` chỉ được ghi nối thêm, mỗi dòng một đối tượng JSON, fsync từng dòng: `{seq, step, phase: intent|done|failed|unknown|cancelled, at, evidence}`. Một dòng cuối bị ghi dở được coi như chưa từng được ghi; điều đó an toàn vì một ý định (intent) được fsync trước khi tác động của nó bắt đầu.
- Số thứ tự thao tác tính riêng cho từng bản cài và chỉ tăng, không bao giờ dựa trên giờ đồng hồ.
- Bản ghi mang kiểu rõ ràng; hành vi không bao giờ phụ thuộc vào tiền tố của tên tài nguyên (việc suy ra hành vi từ tiền tố tên đã gây ra một lỗi trong công cụ cũ).
- JSON nghiêm ngặt (từ chối tên trường trùng và NaN) và byte chuẩn hóa (tên trường được sắp xếp, viết gọn, UTF-8) cho mọi tài liệu được băm, trong một mô-đun.

### 7.4 Khóa

- Mỗi bản cài một `flock` không chờ trên một tệp không bao giờ bị xóa, do trình thực thi giữ trong suốt thao tác; khóa đang bận thì lệnh từ chối ngay (mã thoát 2) kèm thao tác, pid, lệnh, người vận hành và thời điểm bắt đầu của bên đang giữ, lấy từ `lock.holder.json` (`host.lock.holder.json` với khóa máy). Việc lấy khóa ghi lại tệp người giữ của nó, nên quy tắc không để lại dấu vết miễn trừ cả hai tệp này theo tên (F2).
- `host.lock` được lấy trước khi cần cả hai (máy, rồi tới bản cài). Thao tác trên một bản cài đã có không bao giờ cần nó: các tệp dùng chung của máy mà chúng ghi (mục sổ image, cấp phát subnet cho lần chạy cách ly) là các tệp riêng cho từng mục, ghi một lần, được tạo với `O_EXCL`, nên không có việc đọc-sửa-ghi một tệp JSON dùng chung. Một trình thực thi cấp phát một subnet cách ly bằng cách tạo độc quyền `host/allocations/subnet-<address>_<prefix>.json` cho `/24` đầu tiên trong dải mà không mục cấp phát nào và không network nào trên daemon (cấu hình IPAM của mọi network) đang dùng; nếu thua trong cuộc tranh chấp thì chuyển sang `/24` kế tiếp, và một dải không còn `/24` trống sẽ từ chối lúc mở thao tác (`capacity`). Dải mặc định là `10.250.0.0/20`, nằm ngoài các dải địa chỉ mặc định có sẵn của Docker ([ADR-0030](adr/0030-isolation-pool-outside-docker-default-pools.vi.md)); một `host.json` được ghi từ trước giữ dải đã ghi của nó.
- Lệnh chỉ đọc không lấy khóa; chúng đọc các tệp được thay thế trọn vẹn trong một bước.
- `flock` trên một tệp được bind-mount có tác dụng loại trừ giữa các container vì chúng dùng chung kernel và inode của máy (thử nghiệm sớm S3).
- Việc chạy theo lịch không bao giờ chờ hay phá một khóa: khóa bận thì thoát với mã 2 và bộ lập lịch gửi thư cho chủ sở hữu.

### 7.5 Đặt tên và định danh

- Tên bản cài: `^[a-z][a-z0-9]*(-[a-z0-9]+)*$`, tối đa 30 ký tự, duy nhất trên mỗi máy. Tên là định danh và là tên project Compose.
- Mỗi bản cài có một mã dòng dõi `lineage` ngẫu nhiên 128-bit, tạo lúc `init` và được chép vào mọi bản sao lưu. Một lần khôi phục vào bản cài mới kế thừa lineage của bản sao lưu (Planned M4, cùng với phép kiểm tra `single_active`).
- Gắn với engine: `host init` ghi engine ID của daemon; nếu không khớp thì mọi thay đổi bị từ chối cho tới khi chạy `ingat host rebind` (lớp D, Planned M4), lệnh này trước hết kiểm tra các tài nguyên không thuộc Ingat.
- Quyền sở hữu: một đối tượng chỉ thuộc Ingat khi nó mang nhãn bản cài của Ingat **và** (với container) nhãn `com.docker.compose.project` khớp. Nhãn project mà không có nhãn Ingat là vật cản `foreign`; một volume hoặc network được bất kỳ container nào không thuộc Ingat dùng là `shared` và không bao giờ xóa được (cùng cách phân loại như của công cụ cũ). Docker không thể thay đổi nhãn của một đối tượng đã có, nên một đối tượng không thuộc Ingat không bao giờ trở thành thuộc Ingat: việc tiếp quản (M4) chuyển dữ liệu của một bản triển khai không thuộc Ingat vào một bản cài mới qua một gói dữ liệu do chủ sở hữu tạo bằng chính lệnh sao lưu của ứng dụng, và Ingat không bao giờ chạm vào project không thuộc Ingat đó ([`LIFECYCLE.md`](LIFECYCLE.vi.md) §4.16).

## 8. Mẫu

Phần tử argv, giá trị biến môi trường và đường dẫn trong manifest dùng một bộ từ vựng mẫu (template) đóng ([`MANIFEST_SPEC.md`](MANIFEST_SPEC.vi.md) §3). Một biến không có trong bộ đó là lỗi kiểm tra hợp lệ; không có biểu thức; giá trị sau khi điền được kiểm tra ký tự NUL và xuống dòng, và không bao giờ được chuyển cho shell.

## 9. Bảo mật và mô hình tin cậy

### 9.1 Điểm neo tin cậy

Image đã ghim (digest, hoặc image ID của một tarball đã kiểm tra mã kiểm tra), script khởi động thuộc root, `INGAT_ROOT` chỉ root truy cập được, các ref git do chủ sở hữu duyệt được phân giải một lần thành SHA 40 ký tự hex, và engine ID được ghi lúc `host init`. Không có phần khởi động tự kiểm tra chính nó; nâng cấp là đổi image.

### 9.2 Ingat phòng chống những gì

Sai sót (nhầm bản cài, kế hoạch đã cũ, xóa ngoài ý muốn, một bước phá hủy chưa được xem xét), sập và gián đoạn, đầu vào không đáng tin (nội dung repository của ứng dụng, bản sao lưu, các đối tượng Docker khác trên daemon), và rò rỉ bí mật. Nó không phòng chống root.

### 9.3 Socket Docker

Chỉ được gắn vào container CLI và container trình thực thi (sống ngắn, không nghe cổng nào). Container tác vụ, container kiểm tra (probe) và container ứng dụng không bao giờ có nó; policy từ chối việc bind socket. Planned ([ADR-0032](adr/0032-local-session-bound-web-view.vi.md)): container CLI của `ingat ui`, lệnh duy nhất có nghe kết nối, được khởi động mà không có socket.

### 9.4 Thông tin bí mật (ADR-0019)

- Được tạo lúc `init` bằng `secrets.token_*` (32 ký tự `[A-Za-z0-9]`, các bí mật trong một bản cài đều khác nhau từng đôi một) hoặc được đặt bằng `ingat secret set <i> <KEY>` đọc từ stdin, không bao giờ từ argv. Không bao giờ được tạo lại khi nâng cấp, khôi phục hay quay về bản cũ.
- Bí mật dạng tệp của Compose nằm trong `instances/<i>/secrets/` (0700) với quyền theo manifest (ví dụ 0444 cho một tệp bí mật mà một uid không phải root đọc qua bind mount). Bí mật dạng tệp env (ví dụ mật khẩu SMTP của ứng dụng SQLite) nằm trong `secrets/env/<KEY>` (0600) và chỉ được điền vào `app.env` của lần triển khai (0600).
- Trước mỗi lệnh gọi Compose, mỗi đường dẫn bí mật phải là một tệp thường, không rỗng; một thư mục ở đường dẫn bí mật bị từ chối, không bao giờ được sửa (Compose lặng lẽ tạo ra một thư mục như vậy). Bộ lập kế hoạch kiểm tra mọi bí mật dạng tệp của Compose mà một mô hình gắn vào; trình thực thi kiểm tra các tệp bí mật của từng biến thể bằng `lstat` không đi theo liên kết (không có liên kết ở bất kỳ thành phần nào của đường dẫn) ngay trước mỗi lệnh gọi tạo container (`Up`, `RunTask`, `up` của một bước hoàn tác), nếu không thì bước đó thất bại với `secret-file` trước mọi tác động.
- Không bao giờ có trong argv, kế hoạch, bản ghi, bản sao lưu, log hay thông báo lỗi; thông báo lỗi chỉ nêu tên mục (key) và vị trí (công cụ cũ đã làm lộ một bí mật theo cách này). Bản ghi chỉ mang mã băm của phần env không bí mật cộng với tên mục của các bí mật.
- Bộ chạy (runner) che mọi giá trị bí mật của bản cài (với bí mật dạng tệp thì che cả dạng không có ký tự xuống dòng cuối) và dạng mã hóa URL của nó, chỉ trong **văn bản được thu lại** (`json`, `record`, stderr, tiến trình, ảnh chụp log), với phần đuôi được giữ lại dài bằng bí mật dài nhất (một kỹ thuật đã được chứng minh trong bộ chạy của công cụ cũ).
- Các luồng `file:` và `bundle:` (stdin và stdout của tác vụ, ví dụ một tệp lưu trữ `pg_dump`) được giữ chính xác từng byte: không bao giờ bị che, cắt bớt hay giới hạn, nên một bản sao lưu không bao giờ bị hỏng. Các byte của gói dữ liệu là dữ liệu của ứng dụng; Ingat không bao giờ ghi bí mật vào đó.
- Đầu ra được phân loại `terminal` (mã thiết lập) không bao giờ bị thu lại hay ghi nhật ký, và không logging driver nào ghi nó (driver `none`: §3.3, §6.2); ảnh chụp log bỏ qua một dịch vụ trong khoảng thời gian cài đặt khi nó in ra một mã (token).

### 9.5 Quy tắc an toàn (policy) cho mô hình Compose (danh sách cấm trên mô hình đã gộp; `policy/compose_policy.py`)

Bị từ chối: `privileged`; mọi `cap_add`; `devices`, `device_cgroup_rules`; `host` cho `network_mode`, `pid`, `ipc`, `uts`, `userns_mode` hoặc `cgroup`, và `container:<x>` cho bất kỳ mục nào trong số đó (nó tham gia vào một container ngoài project: F8), trong khi `service:<x>` phải nêu tên một dịch vụ của cùng mô hình; mọi `network_mode` khác ngoài `none`, `bridge` hoặc `service:<x>`, và trong lần chạy cách ly thì khác ngoài `none` hoặc `service:<x>` (`bridge` sẽ đi vòng qua các network nội bộ: F13); mọi mục `security_opt` trừ `no-new-privileges` (để trống hoặc true) và `apparmor=docker-default` (một `no-new-privileges` bằng false, mọi mục `seccomp`, kể cả `builtin`, và mọi tùy chọn `label` đều thay thế hoặc nới lỏng một cơ chế giới hạn áp dụng cho toàn daemon); `cgroup_parent`; `container_name`; `volumes_from`; `external_links`; `runtime`; `use_api_socket` (Compose sẽ bind socket Docker vào dịch vụ: §9.3); các loại mount khác ngoài `bind`, `volume` và `tmpfs`; volume hoặc network `external` do ứng dụng khai báo; `driver_opts` trên volume và network; network driver khác ngoài `bridge`; nhãn của ứng dụng nằm trong không gian tên của Ingat; mọi bind của `/var/run/docker.sock`, `/run/docker.sock` hoặc `/`; nguồn bind, `env_file`, secret hoặc config nằm ngoài các vùng dữ liệu của kho của bản cài, thư mục tác vụ, thư mục giữ chỗ (placeholder), thư mục bí mật và tệp env đã tạo (bind chỉ-đọc và tệp config bên trong bản xuất thì được phép); một `label_file` ngoài bản xuất (Compose đọc nó vào nhãn ở mỗi lần gọi); cổng mở trên bất kỳ địa chỉ nào khác `127.0.0.1` (không ứng dụng nào dùng Ingat cần điều đó; một cổng không phải loopback cần một ADR); volume có tên mà không phải kho đã khai báo; ngữ cảnh `build` nằm ngoài bản xuất. Cũng bị từ chối, vì mỗi thứ đi vòng qua một trong các quy tắc trên: dịch vụ `provider:` của Compose (thuộc tính Compose sẽ chạy một chương trình do ứng dụng nêu tên, bên trong trình thực thi đang giữ socket Docker: §9.7; các image nhà cung cấp của [ADR-0031](adr/0031-data-providers.vi.md) là các dịch vụ image bình thường và không phải loại này), hook vòng đời `privileged` (`post_start`, `pre_stop`), yêu cầu GPU (`gpus`, `deploy.resources.reservations.devices`), một network có `name:` cố định (Compose tham gia vào network có sẵn mang tên đó, hoạt động giống như `external`), và các biến nội suy có tên `COMPOSE_*` hoặc `DOCKER_*` (Compose đọc các thiết lập riêng của nó, như `COMPOSE_REMOVE_ORPHANS`, từ `--env-file`; bị bước kiểm tra manifest từ chối khi dùng làm tên tham số, và bị adapter Compose từ chối thêm một lần nữa).

**Quy tắc trên văn bản thô** (`policy/compose_text.py`). Mô hình đã gộp không bao giờ cho thấy các tệp `include` và `extends`, và Compose đọc chúng trước khi bất kỳ quy tắc mô hình nào chạy (include OCI và git từ xa được tải về trong lúc `config`) và lại đọc ở mỗi lần gọi, nên nội dung của chúng có thể thay đổi sau khi đã kiểm tra. Trước khi bất kỳ lệnh gọi Compose nào đọc các tệp Compose của một ứng dụng (trong `prepare` và `deploy`, và trong `validate`), văn bản của từng tệp dùng lúc chạy và tệp dùng lúc build phải đạt: chỉ có các mục (key) cấp cao nhất `version`, `name`, `services`, `networks`, `volumes`, `secrets`, `configs` và `x-*` (nên không có `include`); mọi `extends` chỉ nêu tên một dịch vụ của cùng tệp; và những gì các quy tắc theo dòng không đọc chắc chắn được cũng bị từ chối (một tài liệu không bắt đầu ở cột 0, một mapping dạng flow ở cấp cao nhất, tên mục dạng tường minh hoặc dạng bí danh, tên mục trong nháy kép có ký tự thoát, tag `!!` hoặc tag nguyên văn, tab trong thụt lề, ký tự điều khiển và ký tự xuống dòng Unicode). Một lời từ chối có mã `unsupported-source`.

Bị từ chối khi máy thiếu khả năng tương ứng (`host.json`, do `host init` ghi từ các trường có kiểu `CpuCfsQuota` và `CpuCfsPeriod`): một giới hạn `cpus` khác 0 (`deploy.resources.limits.cpus` hoặc `cpus`) khi daemon báo không hỗ trợ CPU CFS quota, vì khi đó daemon từ chối việc tạo container (NanoCPUs), nên việc tạo không bao giờ có thể thất bại giữa chừng một thao tác. Thông báo nêu tên dịch vụ, tên mục và tham số đặt giá trị đó. Docker lặng lẽ bỏ các giới hạn blkio không được hỗ trợ kèm một cảnh báo, nên không có phép kiểm tra blkio; ứng dụng nào cần giới hạn I/O thì bổ sung phép kiểm tra đó qua một ADR. Những máy như vậy có tồn tại: DSM 7.4.1 với Container Manager 24.0.2-1706, hồ sơ nền tảng đầu tiên, báo không hỗ trợ CPU CFS quota (§11.2), và ứng dụng PostgreSQL đặt `cpus` trên mọi dịch vụ qua tham số: các bản cài của nó trên một máy như vậy đặt các tham số đó là `"0"`, và nếu thử nghiệm sớm S11 cho thấy `cpus: "0"` không có nghĩa là "không giới hạn", ứng dụng sẽ bỏ các mục `cpus` trong repository của chính nó.

Được phép (giảm quyền): `read_only`, `cap_drop`, `user`, `tmpfs`, `init`, `security_opt: no-new-privileges` (và `apparmor=docker-default`, mặc định của chính daemon), giới hạn tài nguyên, `shm_size`, `stop_grace_period`, `network_mode: none`, network nội bộ, profile Compose, cú pháp bind dạng dài. Các tệp Compose đã được gia cố của cả hai ứng dụng có trạng thái đều đạt mà không cần sửa; khuôn danh sách cho phép (allow-list) của công cụ cũ đã từ chối cả hai.

### 9.6 Git

Khóa triển khai (deploy key) chỉ đọc cho mỗi repository; `known_hosts` được ghim lúc `init`; một bare clone thuộc công cụ với `core.hooksPath=/dev/null`, `transfer.fsckObjects=true`, `protocol.allow` giới hạn ở ssh và https (cộng thêm `file` chỉ cho các repository ứng dụng thử dưới `INGAT_ROOT/cache/fixtures/`, [ADR-0027](adr/0027-local-fixture-repositories.vi.md)), `gc.auto=0`; ref được phân giải một lần thành SHA đầy đủ; xuất bằng `git archive` vào một thư mục tạm, đặt chỉ-đọc rồi đổi tên. Submodule, LFS và liên kết tượng trưng trong cây được xuất đều bị từ chối (một liên kết sẽ cho phép một bind chỉ-đọc bên trong bản xuất chạm tới bất kỳ đường dẫn nào trên máy), và một bản xuất có manifest khác với các byte đã được kiểm tra qua `git show` cũng bị từ chối (do một `export-subst` hoặc `export-ignore` trong `.gitattributes`). Ingat không build image nào ([ADR-0026](adr/0026-app-images-built-in-app-ci.vi.md)).

### 9.7 Không bao giờ được phép (không có cách vượt qua)

Chuyển thẳng `up/down/run/exec/build/rm` cho Compose (các lời từ chối có tên sẽ in ra lệnh được quản lý tương ứng); `down -v`, `docker system|volume|image|network prune`; xóa một đối tượng chưa được chứng minh là thuộc Ingat và chưa được liệt kê trong một kế hoạch đã đóng; dừng, khởi động, exec vào, gắn (mount), gắn lại nhãn, khôi phục vào hoặc xóa một đối tượng không thuộc Ingat (việc tiếp quản chỉ làm từ một gói dữ liệu do chủ sở hữu tạo: ADR-0024); khôi phục đè lên dữ liệu hiện tại; cập nhật dữ liệu (migrate) khi không có bản sao lưu trước thay đổi đã niêm phong; thực thi bất cứ thứ gì lấy từ một bản sao lưu; chương trình trên máy do manifest nêu tên; khôi phục bí mật hoặc cấu hình từ một bản sao lưu; bất kỳ điểm kết nối Docker nào ngoài socket cục bộ; daemon rootless hoặc từ xa; lặng lẽ chuyển sang một chương trình Compose hay docker khác; đi theo liên kết tượng trưng trong các cây thư mục thuộc công cụ; `sync(2)` toàn cục (nó đã làm treo công cụ cũ); `--force` hoặc `--yes`; tự động cập nhật.

## 10. Kiểm thử và chứng nhận

### 10.1 Các mức

| Mức kiểm thử | Khi chạy | Nội dung | Thời gian cho phép |
|---|---|---|---|
| T0 tĩnh và đơn vị | mỗi lần push | ruff, mypy strict, kiểm tra hướng import và giới hạn mô-đun, grep chuỗi cấm, `subprocess` chỉ có trong runner; kiểm thử thuần cho việc kiểm tra manifest/bản cài, mẫu, policy, băm kế hoạch, retention, phát lại nhật ký, che bí mật | < 2 phút |
| T1 Docker thật (cổng chính) | mỗi lần push | GitHub Actions `ubuntu-24.04` (`amd64`), `docker:24.0.2-dind` chạy privileged (Engine gốc 24.0.2: mức tối thiểu của Engine và API, 1.43, và là dòng Engine của hồ sơ nền tảng đầu tiên; không phải bản build của Synology, thứ chỉ chứng nhận máy mới bao phủ) và `docker:29.Y.Z-dind` (một tag chính xác trong `image/versions.lock`); làn arm64 trên runner arm64 do GitHub cung cấp `ubuntu-24.04-arm` với cùng tag 29.Y.Z (hiện là 29.9.0). Mỗi làn nạp image công cụ mà một job của pipeline đã build một lần, theo biến thể kiến trúc của làn đó ([ADR-0029](adr/0029-tested-image-and-tested-json-layer.vi.md); thử nghiệm sớm S13), chạy bộ kiểm thử đơn vị bên trong image đó và các mô-đun Docker thật trong các tiến trình song song, mỗi tiến trình trên một máy thử riêng, cùng với các trường hợp sập có tên; làn cũng chạy script thử nghiệm sớm M0, mà các mục của nó không bao giờ làm thay đổi kết luận của làn | < 15 phút mỗi làn (mục tiêu; riêng các mô-đun Docker thật đã mất khoảng 15 phút trên daemon thử cục bộ, nên thời gian chờ tối đa của làn CI là 45 phút cho tới khi có số đo thời gian từ CI) |
| T2 hằng đêm | hằng đêm | toàn bộ ma trận sập được tạo ra (mọi điểm sập của mọi kế hoạch M1) trên các làn amd64; khôi phục sang máy khác trên hai daemon dind (M4); bộ kiểm thử tiếp quản (M4). Kiểm thử tuân thủ của ứng dụng chạy trong job hằng đêm của repository từng ứng dụng, không bao giờ trong CI của công cụ | < 2 giờ |

Các làn dind gốc là bằng chứng cho bậc hỗ trợ 1 (Engine gốc trên Linux, §11.1). Làn arm64 chạy từ M1 (runner arm64 do GitHub cung cấp miễn phí cho repository công khai; thử nghiệm sớm S13 xác nhận điều này ở M0). Hỗ trợ arm64 chỉ được công bố sau khi làn đó đạt: tới lúc đó `tested.json` không có mục arm64 và bậc cổng 2 từ chối trên máy arm64. Một máy arm64 dùng Engine 24.0 vẫn ở bậc cổng 0 và 1 cho tới khi một bản phát hành công cụ thêm làn arm64 `docker:24.0.2-dind`.

### 10.2 Ứng dụng thử (không cần repository ứng dụng)

`fx-web` (máy chủ tĩnh không lưu trạng thái), `fx-lite` (image công cụ ở chế độ ứng dụng thử, mô phỏng ứng dụng SQLite: một máy chủ HTTP nhỏ với SQLite WAL, tệp, một hàng đợi gửi ra giả tôn trọng các mục `JOBS` và `DELIVERY_MODE` của nó ([`MANIFEST_SPEC.md`](MANIFEST_SPEC.vi.md) §11) và ghi dấu "đã gửi", và các lệnh migrate/backup/restore riêng của ứng dụng với kiểu khôi phục giữ hàng đợi lại), `fx-pg` (`postgres:16` làm dịch vụ dữ liệu (data service) cộng một ứng dụng shell mô phỏng các hook hai container của ứng dụng PostgreSQL, có tình huống đua về sẵn sàng do máy chủ tạm lúc khởi tạo (init-server), và một dịch vụ web từ chối khởi động khi không có route IPv4 mặc định trừ khi một chốt chặn (hold) đặt địa chỉ proxy tin cậy của nó, giống như dịch vụ web của ứng dụng PostgreSQL).

### 10.3 Bộ kiểm thử bắt buộc (hành vi chỉ qua CLI)

- **Vòng đời**: init → deploy → backup → verify --restore-test → update → restore → backup → update, trên `fx-pg` và `fx-lite`, trên cả hai engine.
- **Không để lại dấu vết**: mọi đường từ chối (kể cả `refused-stale` bên trong một trình thực thi đã khởi động), mọi `--plan` và mọi lệnh chỉ đọc đều để mã băm cây `instances/` và danh sách đối tượng Docker có nhãn y nguyên sau khi thoát, không có sự kiện tạo, hủy, start, stop hay die nào của container/volume/network/image trong khoảng thời gian đó, trừ của chính các container `role=cli` và `role=exec` của lệnh (cả hai đều `--rm` và có nhãn) và các sự kiện `exec` của các phép kiểm tra chỉ đọc đã khai báo.
- **Ma trận sập**, được tạo ra từ danh sách bước của từng thao tác: SIGKILL trình thực thi trước và sau mỗi bản ghi intent và done (qua hook chỉ dùng cho kiểm thử), và ở giữa mỗi bước tác vụ trong khi container tác vụ của nó đang chạy. Sau đó chạy `status --json`, chạy lệnh `next` của nó, và khẳng định hệ thống hội tụ: không mất dữ liệu, vùng dữ liệu trước đó còn nguyên, không có lần xóa nào ngoài danh sách, và lệnh được in ra chạy thành công. Các trường hợp có tên: trình thực thi bị giết trong một tác vụ sao lưu trực tuyến, sau đó `scheduled backup` kế tiếp tự động bỏ dở nó và thành công; trình thực thi bị giết giữa chừng một tác vụ, sau đó `resume` ghi lại mã thoát của container tác vụ đã thoát, xóa nó và thành công (daemon thường tự xóa container như vậy, §4.5, nên bộ kiểm thử tự đặt sẵn một container); một lần cài đặt tạm dừng, một tác vụ được phép chạy và được ghi nhật ký trong thao tác đang tạm dừng, rồi `resume`; một lần khôi phục vào một bản cài chưa bao giờ được triển khai bị giết sau khi chuyển vùng dữ liệu, mà `next` (lại `restore`) hội tụ được từ lần triển khai đã ghi trước khi bắt đầu ([`LIFECYCLE.md`](LIFECYCLE.vi.md) §4.10).
- **Mất phiên**: giết CLI hoặc phần theo dõi (SIGHUP, SIGTERM, kill) không bao giờ dừng trình thực thi; SIGINT, SIGTERM, SIGHUP và SIGQUIT thật gửi tới trình thực thi đều hoạt động như một yêu cầu hủy; một yêu cầu hủy dừng ở ranh giới kế tiếp; một container tác vụ không bao giờ bị bỏ mồ côi sau khi khóa được nhả.
- **Phạm vi tạo lại**: một lần triển khai chỉ đổi mã của `fx-pg` giữ nguyên ID container của dịch vụ dữ liệu; một thay đổi chỉ về cấu hình tạo lại đúng các dịch vụ bị thay đổi.
- **Nâng cấp** (từ M1): cài bản phát hành N-1 (tag trước đó, hoặc commit main trước đó khi chưa có tag đầu tiên), tạo một bản cài và để một thao tác đang mở; việc nâng cấp lên N từ chối; đóng thao tác, nâng cấp, đọc trạng thái N-1 bằng N; rồi chạy `bin/ingat.prev` (N-1) và đọc trạng thái mà N đã ghi.
- **Sẵn sàng**: trên `fx-pg`, không tác vụ nào chạm vào kho dữ liệu trước khi phép kiểm tra TCP ổn định đạt (tình huống đua với máy chủ tạm lúc khởi tạo).
- **An toàn vùng dữ liệu**: không phần ghi dữ liệu đang chạy nào gắn một vùng dữ liệu chưa được chuyển sang, và không project cách ly nào gắn vùng dữ liệu đang chạy.
- **Cách ly**: một lần thử khôi phục và một lần khôi phục `fx-lite` tạo ra không một dấu "đã gửi" nào; một lần khôi phục kết thúc ở `held`; dịch vụ web của `fx-pg` chỉ khởi động được trong môi trường cách ly nhờ chốt chặn của nó (một network nội bộ có thể không có route mặc định: thử nghiệm sớm S12).
- **Tài nguyên không thuộc Ingat**: một container làm bằng tay trong cùng project, một container không thuộc Ingat dùng volume của bản cài, một volume trùng tên được tạo sau khi lập kế hoạch, một network không thuộc Ingat có IPAM dùng một subnet trong dải: mỗi trường hợp đều bị từ chối hoặc được bỏ qua.
- **Tiếp quản** (M4): các project `fx-pg` và `fx-lite` không thuộc Ingat làm bằng tay (khởi động bằng `docker compose` thường) được bài kiểm thử cho ngừng ghi và xuất ra bằng `docker` thường và các lệnh sao lưu riêng của ứng dụng thử, như runbook hướng dẫn ([`LIFECYCLE.md`](LIFECYCLE.vi.md) §4.16), rồi được `import --payload` vào các bản cài mới, thử khôi phục, khôi phục, sao lưu và cập nhật; các sự kiện Docker không cho thấy sự kiện nào trên bất kỳ đối tượng không thuộc Ingat nào do một container Ingat gây ra; mọi lời từ chối (một gói dữ liệu có liên kết, tệp đặc biệt, mục cấp cao nhất không được liệt kê hoặc có nhiều mục cấp cao nhất, một tên gói dữ liệu vi phạm quy tắc gói dữ liệu, một bản cài không ở trạng thái `registered`, một bản phát hành không có ứng viên đã chuẩn bị, một lần khôi phục một bản sao lưu đã nhập mà chưa `restore-tested`) đều không để lại dấu vết.
- **Bí mật mồi (canary)**: các giá trị được gieo sẵn không bao giờ xuất hiện trong bất kỳ đầu ra văn bản, bản ghi, ảnh chụp log, kế hoạch nào hoặc trong các tệp do Ingat ghi của một bản sao lưu (`bundle.json`, `SHA256SUMS`, `meta/`); một tệp gói dữ liệu chứa một giá trị được gieo vẫn giống hệt từng byte trong bản sao lưu; mã (token) được gieo của một tác vụ dùng terminal không xuất hiện trong tệp nào dưới thư mục gốc Docker.
- **Tác vụ dùng terminal**: một tác vụ `stdin = "terminal"` chạy với echo đã tắt và từ chối khi không có TTY.
- **Cổng phiên bản**: một Engine chưa được kiểm thử bị bậc cổng 2 từ chối với mã thoát 2 và được bậc cổng 1 cho phép kèm một cảnh báo được ghi lại.
- **Bảng policy**: các đoạn cấu hình nguy hiểm bị từ chối; các tệp Compose đã gia cố của ứng dụng thử (`read_only`, `cap_drop`, cổng loopback, bí mật dạng tệp, tham số `cpus`) được chấp nhận.

### 10.4 Chứng nhận máy (chủ sở hữu chạy)

Một chứng nhận máy là bằng chứng rằng công cụ chạy được trên một bản build nền tảng: phiên bản hệ điều hành hoặc thiết bị (kể cả mức cập nhật), bản build Engine như `docker version` báo (phiên bản Engine, Git commit và thời điểm build, phiên bản containerd và runc), kernel, storage driver và kiến trúc, dưới dạng thông tin được phát hiện (§3.6). Bản build gói Engine (trên DSM là bản build Container Manager) là một trường của `facts.sh` trong tệp được commit và trong tên tệp của nó, không phải một mục mà cổng dùng để so khớp, vì container của công cụ không thấy được nó. Sau bất kỳ thay đổi nào của bản build đó, `ingat selftest --host` (bước 2-3, vài phút) chứng nhận lại nó cho cổng. Trên máy bậc hỗ trợ 1 thì chỉ cần vậy: CI đã chạy đủ các bộ kiểm thử trên các bản build gốc của dòng Engine đó (§10.1), và `selftest --host` tại chỗ bao phủ bản build riêng của máy, kể cả gói của bản phân phối. Một nền tảng bậc hỗ trợ 2 còn cần đủ danh sách kiểm tra (bước 1-5, khoảng 30 phút) và một tệp `support/hosts` mới được commit cho mỗi dòng phiên bản nền tảng mới hoặc bản build gói của hãng làm thay đổi Engine, containerd hoặc runc (trên DSM: một dòng DSM minor mới, hoặc một bản build Container Manager làm thay đổi chúng), vì không làn CI nào tái tạo được engine của hãng. Máy bậc hỗ trợ 1 đầu tiên cũng chạy đủ danh sách kiểm tra một lần (phần việc 12 của M4), để cách cài đặt Linux chung và các bộ lập lịch có bằng chứng trên máy thật. Một bản phát hành công cụ không cần chứng nhận máy riêng (CI bao phủ công cụ); việc nâng cấp trên mỗi máy chạy `selftest --host` với phiên bản mới trước khi thay script khởi động (§3.5).

1. `facts.sh` (chỉ đọc, chạy phía máy): `/etc/os-release` và, nếu có, tệp phiên bản riêng của nền tảng và các bản build gói (trên DSM là `/etc.defaults/VERSION` với phiên bản, bản build và mức cập nhật, và bản build Container Manager), `docker version` (Engine, containerd, runc), `docker info` (hỗ trợ CPU CFS, giới hạn bộ nhớ và blkio, storage driver, logging driver mặc định, phiên bản cgroup, live restore, tùy chọn bảo mật), `uname -m/-r`, `ldd --version`, `/proc/meminfo`, loại và cách bố trí hệ thống tệp của từng thư mục gốc (các subvolume Btrfs nếu có), dung lượng trống của từng thư mục gốc và thư mục gốc Docker, `ls -ld` của cả hai thư mục gốc, quyền của socket, và các thông tin ACL ở nơi nền tảng có ACL (trên DSM là `synoacltool -get` của cả hai thư mục gốc và quyền của thư mục chia sẻ `ingat-backups`, quản trị viên chỉ đọc).
2. `ingat host check` (nó chỉ ghi chứng nhận của nó) ghi lại cùng các thông tin đó như công cụ nhìn thấy, các rủi ro của máy và các mục thông tin bản build đã thay đổi kể từ `host init` vào `host/certifications/<stamp>-host-check.json`, với kết quả `PASS`, `FAIL` (một thư mục gốc hoặc thư mục client Docker của công cụ bị sai) hoặc `BLOCKED` (thiếu một thông tin về bản build nền tảng); mọi kết quả khác `PASS` đều thoát với mã 5.
3. `ingat selftest --host` chạy vòng đời trên các bản cài dùng một lần `ingat-selftest-*` của `fx-lite` và `fx-web` (từ các repository ứng dụng thử mà nó tạo ra: ADR-0027), rồi gỡ chúng qua đường xóa đóng, và ghi `host/certifications/<stamp>-selftest.json`: `PASS` chỉ khi mọi phép kiểm tra đều đạt và việc gỡ không để lại gì.
4. Danh sách kiểm tra thủ công: một lần chạy theo lịch qua bộ lập lịch của máy có thư báo lỗi (một systemd timer với `OnFailure=`, một mục cron, hoặc DSM Task Scheduler); một lần mất SSH trong lúc sao lưu; bản sao ngoài máy lấy được `INGAT_BACKUPS` (restic, borg hoặc rsync trên Linux; Hyper Backup trên DSM); sau một bản cập nhật nền tảng, script khởi động và trạng thái vẫn còn.
5. Chủ sở hữu commit `support/hosts/<platform release and update>-<engine package build>-<kernel>-<arch>.json` vào repository của công cụ (trên DSM: `<dsm build and update>-<container manager build>-<kernel>-<arch>.json`). Tệp này chỉ nêu phần mềm nền tảng và kiến trúc (phiên bản hệ điều hành hoặc thiết bị và mức cập nhật, bản build gói Engine như bản build Container Manager, phiên bản Engine, Git commit và thời điểm build, phiên bản containerd và runc, kernel, kiến trúc như `x86_64` hoặc `aarch64`), không bao giờ nêu mẫu thiết bị (NAS, máy chủ hay bo mạch), mẫu CPU, tên máy, địa chỉ hay đường dẫn bản cài, hoặc chi tiết của thiết bị như RAM, dung lượng trống hay cách bố trí volume (quyết định của chủ sở hữu OD-3); những thứ đó ở lại trong bằng chứng `host/certifications/` riêng của máy. Tệp liệt kê các rủi ro của máy mà thông tin cho thấy (ví dụ runc cũ hơn 1.1.12, hoặc không có seccomp). Các tuyên bố hỗ trợ chỉ liệt kê các tổ hợp đã được chứng nhận cộng với ma trận CI.

## 11. Máy và bảng hỗ trợ

Ingat chạy trên một máy có Docker Engine Linux cục bộ 24.0 trở lên và Compose v2, trên bất kỳ bản phân phối hay thiết bị nào: máy chủ vật lý, máy ảo hoặc VPS, một NAS có Docker (Synology hoặc bất kỳ hãng nào khác), một bo mạch nhỏ. Khác biệt giữa các nền tảng được xử lý như các khả năng được phát hiện (§11.2) và bằng một chứng nhận cho từng bản build nền tảng (§3.6, §10.4), không bao giờ bằng cách rẽ nhánh theo tên nền tảng, hãng hay mẫu máy (§11.3). Lần triển khai thật đầu tiên là một NAS Synology chạy DSM 7.4.1 với Container Manager 24.0.2-1706; các đặc điểm của nó, được quan sát bằng một phép thăm dò chỉ đọc và qua nghiên cứu nền tảng vào 2026-10-14, tạo thành hồ sơ nền tảng đầu tiên (§11.2). Đó là đặc điểm của bản phát hành DSM và Container Manager đó, không phải của một mẫu thiết bị. Khi chúng mâu thuẫn với một giả định trước đó, kết quả quan sát được ưu tiên. Vào 2026-10-22, bản phát hành `v0.1.0` đã đạt `selftest --host` trên bản build nền tảng đó, và chứng nhận của nó đã được commit trong `support/hosts/` (danh sách kiểm tra thủ công của §10.4 bước 4 còn đang chờ).

### 11.1 Bảng hỗ trợ

Các bậc hỗ trợ cho biết Ingat hỗ trợ những máy nào và mỗi loại cần bằng chứng gì; chúng không phải các bậc cổng của §3.6. Yêu cầu tối thiểu cho mọi máy: §11.4.

| Bậc hỗ trợ | Máy | Bằng chứng cần có | Trạng thái |
|---|---|---|---|
| **Bậc hỗ trợ 1** | Máy Linux trên bất kỳ bản phân phối nào (máy vật lý, máy ảo, VPS hoặc bo mạch) chạy Docker Engine gốc (docker-ce từ kho của Docker, hoặc một gói của bản phân phối) trên một dòng Engine mà CI kiểm thử (hiện là 24.0 và đúng một bản 29.x), trên `x86_64`, hoặc trên `aarch64` cho những dòng mà làn arm64 đạt (chỉ 29.x) | Các làn dind gốc (§10.1) cộng một chứng nhận `selftest --host` tại chỗ cho từng bản build nền tảng (§10.4) | Được các làn CI bao phủ từ M1; chứng nhận Linux chung đầu tiên được commit (VPS hoặc máy chủ) là Planned M4, phần việc 12. Một Engine gốc 24.0 trở lên trên một dòng chưa có làn CI chỉ chạy bậc cổng 0 và 1, cho tới khi một bản phát hành công cụ thêm làn đó |
| **Bậc hỗ trợ 2** | Engine do hãng build trên các thiết bị: Synology Container Manager trước tiên (hồ sơ DSM, §11.2); thiết bị của các hãng khác sau này, mỗi loại qua hồ sơ nền tảng riêng | Một hồ sơ nền tảng: đủ danh sách kiểm tra chứng nhận và một tệp `support/hosts` được commit cho mỗi dòng bản build nền tảng, cộng một `selftest --host` tại chỗ sau mỗi lần cập nhật (§10.4) | Synology DSM 7.4 với Container Manager 24.0.2 trên `x86_64`: lần triển khai thật đầu tiên. Chứng nhận đầu tiên của nó (DSM 7.4.1 build 90080 với Container Manager 24.0.2-1706) đã được commit trong `support/hosts/`; danh sách kiểm tra thủ công của §10.4 bước 4 còn đang chờ (một mục của điều kiện hoàn thành mốc M1) |
| **Không được hỗ trợ ở v1** | Docker rootless; Docker Desktop trên Windows hoặc macOS để chạy thật (chỉ dùng để phát triển); Podman; Kubernetes hoặc Swarm; cấu hình nhiều máy; Docker Engine cũ hơn 24.0 (API dưới 1.43), điều này cũng loại trừ Synology DSM 7.1 trở về trước với gói Docker cũ (Engine 20.10, API 1.41, Compose v1) | — | Sẽ không thêm bậc, làn CI hay chứng nhận nào ở v1. DSM 7.1 cũng đã hết thời gian hỗ trợ kéo dài từ tháng 6 năm 2025, nên không còn bản sửa lỗi nào được chờ đợi |

Các tuyên bố hỗ trợ chỉ nêu các tổ hợp đã được kiểm thử: một dòng Engine và kiến trúc có làn CI đã đạt, cộng một chứng nhận của bản build nền tảng.

**Mất máy.** Việc phục hồi cần một máy thay thế đã được chứng nhận, thuộc bậc hỗ trợ nào cũng được: ví dụ một máy chủ Linux hoặc VPS, hoặc một NAS Synology khác trên một bản build DSM và Container Manager đã được chứng nhận (một máy chạy DSM 7.1 trở về trước không dùng được). Quy trình: cài đặt, chứng nhận, lấy lại các bản sao lưu từ bản sao ngoài máy, `import` chúng, và khôi phục chúng vào các bản cài được khởi tạo từ bản sao ngoại tuyến đã mã hóa của chủ sở hữu, chứa cấu hình bản cài và bí mật (quyết định của chủ sở hữu OD-9; [`LIFECYCLE.md`](LIFECYCLE.vi.md) §5.9; runbook ở phần việc 10 của M4, được diễn tập trên máy đầu tiên ở điều kiện hoàn thành mốc M4).

### 11.2 Đặc điểm nền tảng và những gì chúng thay đổi

Ingat xử lý mọi khác biệt giữa các nền tảng như một thông tin mà `host init` và `host check` ghi lại (§3.4) và được bộ lập kế hoạch, tệp override và cổng sử dụng. Một hồ sơ nền tảng là tài liệu và dữ liệu chứng nhận (giá trị cài đặt, đặc điểm quan sát được, quy tắc cho người vận hành), không bao giờ là một đường mã (§11.3).

| Đặc điểm | Phát hiện từ | Ingat làm gì |
|---|---|---|
| CPU CFS quota/period | `docker info` (`CpuCfsQuota`, `CpuCfsPeriod`) | Nếu không có, daemon từ chối tạo container có giới hạn `cpus` khác 0, nên phép kiểm tra khả năng lúc lập kế hoạch từ chối mọi `cpus` khác 0 (§9.5); một ứng dụng đặt `cpus` thì đưa nó ra thành tham số, và các bản cài của nó trên máy như vậy đặt tham số đó là `"0"` |
| Giới hạn tốc độ blkio | không có gì để phát hiện | Docker lặng lẽ bỏ các giới hạn blkio không được hỗ trợ kèm một cảnh báo và không ứng dụng nào đặt chúng, nên không có phép kiểm tra; ứng dụng nào cần giới hạn I/O thì bổ sung phép kiểm tra qua một ADR. Giới hạn bộ nhớ và `cpu_shares` vẫn dùng được |
| Logging driver mặc định | `docker info` | Không bao giờ dựa vào: các dịch vụ không có `logging` riêng và trình thực thi nhận `local` có xoay vòng, còn CLI và các tác vụ dùng terminal nhận `none`, nên một bí mật hiện trên terminal không bao giờ bị logging driver ghi lại (F12; §3.3, §6.2) |
| Storage driver | `docker info` | Không bao giờ phụ thuộc vào; một thay đổi là một bản build nền tảng mới cần chứng nhận lại, vì nó làm ẩn các image và container hiện có (rủi ro R14). Các làn dind gốc dùng overlay2 |
| Kho image (classic hoặc containerd snapshotter) | `docker info` (`DriverStatus`) | Được `host init` ghi lại. Image ID khác nhau tùy kho (với kho containerd, loại mà daemon dind gốc 29.9.0 cục bộ đã dùng, ID là index digest), nên Ingat chỉ lấy ID từ `image inspect` trên chính daemon của máy và khớp container theo image ID mà nó chạy, không bao giờ theo nhãn Compose |
| Phiên bản cgroup | `docker info` | Được ghi lại cho việc chứng nhận; không tính năng nào của Ingat cần một phiên bản cgroup cụ thể |
| Kernel | `uname -r` | Là một phần của bản build nền tảng; image ứng dụng phải qua một phép thử canary trên kernel của máy trước khi ứng dụng được tuyên bố là được hỗ trợ ở đó (§11.3 mục 6) |
| Kiến trúc | `docker info`, `uname -m` | Docker kéo biến thể phù hợp của image đa kiến trúc; `tested.json` và chứng nhận tính theo từng kiến trúc; image ứng dụng phải có cho kiến trúc đó |
| Live restore | `docker info` | Khi tắt (mặc định của bản gốc), việc khởi động lại daemon dừng mọi container và một thao tác đang mở trở thành `interrupted` (tiếp tục được), nên Engine được cập nhật có chủ ý, không bao giờ tự động |
| Tùy chọn bảo mật (seccomp, AppArmor) | `docker info` | Được ghi lại; chứng nhận liệt kê việc thiếu seccomp là một rủi ro của máy (cách ly yếu hơn), được giảm nhẹ chủ yếu bằng image tin cậy, ghim theo digest |
| Phiên bản runc | `docker version` | Được ghi lại; runc cũ hơn 1.1.12 (CVE-2024-21626) được liệt kê là một rủi ro của máy |
| Phiên bản Engine và API | `docker version` | Các bậc cổng (§3.6); `start_interval` của healthcheck cần Engine 25, nên không ứng dụng nào được phụ thuộc vào nó khi mức tối thiểu còn là 24.0 |
| Giao diện quản lý container của hãng | không phát hiện được | Quy tắc cho người vận hành: không bao giờ dùng các thao tác project của giao diện đó trên một project Ingat; `status` và `doctor` báo `changed-outside` ([`LIFECYCLE.md`](LIFECYCLE.vi.md) §4.15) |

#### Hồ sơ nền tảng đầu tiên: Synology DSM 7.4 với Container Manager 24.0.2 (bậc hỗ trợ 2)

**Đặc điểm quan sát được** (DSM 7.4.1 với Container Manager 24.0.2-1706): bản build Engine 24.0.2 của Synology (API 1.43), containerd 1.7.1, runc 1.1.7; plugin Compose riêng của máy v2.20.1 (Ingat không dùng); kernel của hãng, 4.4.x trên nhiều nền tảng DSM 7.x (một số nền tảng mới hơn chạy 5.10); cgroup v1; AppArmor mà không có seccomp; không có CPU CFS quota/period; không có giới hạn tốc độ blkio (Docker bỏ giới hạn blkio kèm một cảnh báo); logging driver mặc định là `db`; live restore tắt; storage driver phụ thuộc hệ thống tệp của volume (aufs trên volume ext4, btrfs trên volume Btrfs); Snapshot Replication chỉ có trên volume Btrfs; Python của máy 3.8 (hệ thống) và 3.9 (gói), không dùng; chỉ truy cập Docker được bằng root (`sudo -i`); DSM Task Scheduler cho việc chạy theo lịch. **Giá trị cài đặt:** thư mục gốc `/volume1/ingat` và `/volume1/ingat-backups` (một thư mục chia sẻ, nguồn của Hyper Backup), docker ở `/usr/local/bin/docker` (§3.4).

Các quy tắc chung áp dụng cho hồ sơ này như sau:

- **Ghi log.** Driver mặc định của Container Manager là `db` của Synology. Các tác vụ dùng terminal và container CLI ghi log bằng driver `none`, nên một bí mật hiện trên terminal không bao giờ bị bất kỳ logging driver nào ghi lại (F12); trình thực thi và các dịch vụ dùng `local` có xoay vòng (§3.3, §6.2), nên `ingat logs` và `SnapshotLogs` đọc một driver chuẩn và log được xoay vòng. Màn hình xem log của Container Manager có thể hiện ít hơn với các project Ingat.
- **Giới hạn CPU và I/O.** Không hỗ trợ CPU CFS quota/period (quan sát trên DSM 7.4.1 với Container Manager 24.0.2-1706; trước đây là thử nghiệm sớm S11): daemon từ chối tạo container có giới hạn `cpus` khác 0, nên phép kiểm tra khả năng lúc lập kế hoạch từ chối mọi `cpus` khác 0 trên máy mà `host init` đã ghi là không hỗ trợ CPU CFS (§9.5); một ứng dụng đặt `cpus` thì đưa nó ra thành tham số, các bản cài của nó đặt tham số đó là `"0"`, và ứng dụng chỉ bỏ các mục `cpus` nếu S11 cho thấy `"0"` không có nghĩa là "không giới hạn". Không có giới hạn tốc độ blkio: Docker lặng lẽ bỏ các giới hạn blkio không được hỗ trợ kèm một cảnh báo, và không ứng dụng nào đặt chúng, nên không có phép kiểm tra blkio. Giới hạn bộ nhớ và `cpu_shares` vẫn dùng được.
- **Lưu trữ và phục hồi.** Storage driver phụ thuộc hệ thống tệp của volume (aufs trên volume ext4, btrfs trên volume Btrfs), và Ingat không được phụ thuộc vào nó. Snapshot Replication chỉ có trên volume Btrfs, nên việc phục hồi không bao giờ dựa vào snapshot: nó dựa trên các bản sao lưu đã niêm phong của Ingat trong `ingat-backups` cộng với bản sao Hyper Backup của chủ sở hữu ở ngoài NAS ([`LIFECYCLE.md`](LIFECYCLE.vi.md) §5.9). Các vùng dữ liệu kiểu volume nằm bên trong thư mục gốc Docker (`@docker` trên volume cài Container Manager, ví dụ `/volume1/@docker`; không phải thư mục chia sẻ), nơi Hyper Backup không chọn được, nên một kho dữ liệu đang chạy không bao giờ là nguồn phục hồi. Các làn dind gốc dùng overlay2, và dind gốc hoàn toàn không chạy được aufs (Docker gốc đã bỏ driver aufs ở Engine 24.0; nó chỉ còn trong bản build của Synology), nên hành vi storage driver của một máy DSM chỉ được chứng nhận máy bao phủ (rủi ro R14).
- **runc 1.1.7.** Container Manager 24.0.2-1706 đi kèm runc 1.1.7, ra đời trước bản sửa CVE-2024-21626 (runc 1.1.12). `host check` ghi lại phiên bản runc và chứng nhận liệt kê điểm yếu này là một rủi ro của máy. Biện pháp giảm nhẹ chính là chỉ chạy image tin cậy (build từ repository của chủ sở hữu hoặc image chính thức, ghim theo ID và digest); các dịch vụ chỉ mở cổng trên `127.0.0.1` phía sau reverse proxy của DSM. Nên chỉ cho NAS tiếp xúc trong mạng LAN: CVE-2024-21626 bị kích hoạt bởi một image độc hại hoặc thư mục làm việc độc hại của lệnh exec, không phải bởi việc truy cập được qua mạng, nhưng một container mở ra internet mà bị chiếm quyền sẽ gặp lớp cách ly yếu (runc 1.1.7, không có seccomp, kernel cũ của hãng). Một bản build Container Manager có runc đã sửa sẽ loại bỏ rủi ro này (sau khi chứng nhận lại).
- **Giao diện Container Manager.** Nút "Clean" của một project chạy một lệnh Compose down xóa container, network, volume và image của project; "Delete" xóa dữ liệu của project. Việc Container Manager có liệt kê và có thể Clean một project do Ingat tạo hay không, và Clean có xóa volume external hay không, vẫn là Unverified; dù thế nào thì quy tắc cho người vận hành vẫn áp dụng: không bao giờ dùng các thao tác project của Container Manager trên một project Ingat; Ingat không thể ngăn việc đó. `status` và `doctor` báo cần chú ý `changed-outside` khi container, network hoặc volume vùng dữ liệu của một bản cài đã triển khai bị thiếu hoặc khác với lần triển khai đã ghi ([`LIFECYCLE.md`](LIFECYCLE.vi.md) §4.15). Hãy tắt tự động cập nhật của Container Manager (và tự động cài cập nhật của DSM, nếu đang bật) và cập nhật có chủ ý: live restore đang tắt, nên khởi động lại daemon sẽ dừng mọi container và một thao tác đang mở trở thành `interrupted` (tiếp tục được).
- **Cổng phiên bản.** Một bản cập nhật DSM, hoặc một bản cập nhật Container Manager làm thay đổi bản build Engine, sẽ thay đổi bản build đã được chứng nhận: bậc cổng 2 từ chối cho tới khi `selftest --host` chứng nhận bản build mới (§10.4), kể cả các lần thử khôi phục theo lịch, trong khi các bản sao lưu trực tuyến hằng đêm (bậc cổng 1) vẫn tiếp tục (§3.6). Hãy cài bản cập nhật DSM mới nhất trước lần chứng nhận đầu tiên của một máy để chứng nhận bao gồm cả nó. DSM 7.4 hết thời gian bảo trì vào khoảng tháng 6 năm 2028 và không có thời gian hỗ trợ kéo dài, nên việc chuyển sang dòng DSM kế tiếp phải diễn ra trước đó và là một lần chứng nhận lại (rủi ro R13).
- **Kernel.** Nhiều nền tảng DSM 7.x chạy kernel 4.4.x (một số nền tảng mới hơn chạy 5.10). Kernel 4.4 thấp hơn mức tối thiểu Tier-1 của Node.js 24 (4.18), nên thử nghiệm sớm S15 chạy image của các ứng dụng trên kernel DSM 4.4 trước khi chúng được tuyên bố là được hỗ trợ (môi trường chạy của ứng dụng SQLite và giai đoạn build web của ứng dụng PostgreSQL dùng Node 24). Bản phát hành quan sát được chạy cgroup v1 (v2 cần kernel ≥ 4.15).
- **Công cụ của máy, root và lập lịch.** Plugin Compose v2.20.1 của máy và Python 3.8/3.9 của máy không bao giờ được dùng. Docker cần root, đạt được qua SSH với `sudo -i`. DSM Task Scheduler chạy các việc theo lịch ([`LIFECYCLE.md`](LIFECYCLE.vi.md) §7; `schedule render --dsm`, Planned M3).
- **Không bị các đặc điểm này ảnh hưởng.** Engine 24 kéo được các lớp nén zstd (Engine ≥ 23), nên không cần quy tắc buộc dùng gzip (đó chỉ là mối lo của Engine 20.10 trong gói Docker cũ); image riêng của Ingat chạy trên mức cơ bản x86-64, và một image ứng dụng cần mức x86-64 cao hơn sẽ bị phép thử canary của nó phát hiện (§11.4). Việc RAM của một máy có chứa nổi các bản cài đang chạy cộng một lần thử khôi phục hay không vẫn là Unverified cho tới khi `facts.sh` ghi `MemAvailable` trong lúc các bản cài đó đang chạy. Thử khôi phục từ chối dựa trên `[drill] min_free_memory` và không bao giờ dựa vào swap.

### 11.3 Quy tắc tổng quát

Một ứng dụng mới không được cần thay đổi phần lõi. Nó phải vừa với schema manifest, các tập đóng gồm loại bước, chế độ tác vụ và loại phép kiểm tra, và danh sách kiểm tra tiếp nhận dưới đây, nếu không thì chỗ thiếu được ghi lại bằng ADR như một thất bại về tính tổng quát (ADR-0021). Quy tắc này áp dụng cả cho máy: khác biệt giữa các nền tảng là các khả năng mà `host init` và `host check` phát hiện và bộ lập kế hoạch, tệp override và cổng kiểm tra, cộng với một chứng nhận cho từng bản build nền tảng (§3.6, §10.4); không đường mã nào rẽ nhánh theo tên nền tảng, hãng, mẫu máy hay tên ứng dụng. Một hồ sơ nền tảng (§11.2) là tài liệu và dữ liệu chứng nhận, không bao giờ là một đường mã. Một nền tảng có khác biệt không thể diễn tả bằng các khả năng được phát hiện là một thất bại về tính tổng quát, được ghi lại bằng ADR.

**Danh sách kiểm tra tiếp nhận một ứng dụng mới.** Một ứng dụng sẵn sàng cho Ingat khi repository của nó cung cấp:

1. **Tệp Compose** với **tên dịch vụ ổn định** (chúng đặt tên cho tác vụ, vai trò và mã băm cấu hình; đổi tên một dịch vụ là thay đổi cấu trúc); cổng mở ra ngoài chỉ từ tham số `port` trên `127.0.0.1`; volume có tên chỉ cho các kho đã khai báo; không có `container_name`, mạng của máy (host networking), chế độ privileged, thiết bị hay socket Docker (§9.5); giới hạn `cpus` chỉ dưới dạng tham số có mặc định là không giới hạn (máy không có CPU CFS từ chối giá trị khác 0); không phụ thuộc vào tính năng của Engine 25+ như `start_interval` của healthcheck.
2. **Lệnh dữ liệu riêng của ứng dụng trong image của chính nó:** `backup` (vào một thư mục chuẩn bị hoặc ra stdout; nhất quán khi các phần ghi dữ liệu đã dừng, hoặc trực tuyến khi đã khai báo), `restore` (chỉ vào một đích rỗng), `verify` (chỉ đọc; nên có), `migrate` (an toàn khi chạy lặp lại, hoặc quan sát được qua việc đọc schema) và một lệnh đọc schema (một tác vụ đọc in ra JSON, hoặc một phép kiểm tra sẵn sàng báo schema mong đợi và schema thực tế). Lệnh sao lưu cũng phải chạy được bằng tay trên một bản triển khai làm ngoài Ingat, để bản triển khai đó có thể được tiếp quản ([`LIFECYCLE.md`](LIFECYCLE.vi.md) §4.16). Planned ([ADR-0031](adr/0031-data-providers.vi.md)): một ứng dụng không có các lệnh như vậy sẽ khai báo các tập dữ liệu của nó dưới dạng `[data.<name>]` thay vào đó, và một image nhà cung cấp đi kèm công cụ, ghim theo digest, sẽ cung cấp các lệnh đó.
3. **Một hợp đồng mã thoát** cho mọi lệnh, được ghi trong tài liệu của ứng dụng: `0` là thành công, và các mã riêng biệt cho "bị từ chối, không có gì thay đổi", "không rõ kết quả" (lệnh ghi) và "có phát hiện" (lệnh kiểm tra chỉ đọc). Các bảng `exit` của manifest mã hóa hợp đồng này; một mã thoát khác 0 chưa khai báo của một tác vụ ghi được tính là `unknown`.
4. **Phép kiểm tra sức khỏe và sẵn sàng:** một phép kiểm tra sẵn sàng chỉ đạt khi kho dữ liệu dùng được và schema đã mới nhất (lý tưởng là JSON có trường release và schema), và một phép kiểm tra sẵn sàng ở mức TCP cho mỗi kho dữ liệu (trạng thái `healthy` của container là chưa đủ: F16).
5. **Bí mật dạng tệp** (secret của Compose hoặc biến `*_FILE`), không bao giờ đóng sẵn trong image hay truyền qua argv; các công tắc có tác dụng phụ (gửi thư thật, thanh toán, webhook) là các mục cấu hình (key) chỉ chủ sở hữu được bật; các tác dụng phụ ra bên ngoài được khai báo với chốt chặn và một chế độ tạm dừng ở mức ứng dụng sau khi khôi phục.
6. **Image:** CI phát hành image (quyết định của chủ sở hữu OD-11, ADR-0026) cho kiến trúc của mọi máy mà ứng dụng chạy trên đó (`linux/amd64`, và `linux/arm64` cho máy arm64) lên GHCR theo commit với các nhãn OCI `version` và `revision`; image nền khi chạy phải qua một phép thử canary trên kernel và CPU của máy (ví dụ kernel DSM 4.4, như thử nghiệm sớm S15, và mức x86-64 mà image yêu cầu: §11.4).
7. **`ingat.toml`** ở thư mục gốc của repository, chung chung (không có giá trị của máy), với `ingat validate` trong CI của ứng dụng trên một digest công cụ đã ghim ngay từ commit đầu tiên, và `ingat conformance` chạy hằng đêm khi đã có M3.
8. **Giá trị của máy nằm ngoài repository:** cổng, subnet, URL, tên máy và bí mật chỉ nằm trong `instance.toml` và các tệp bí mật trên máy và trong bản sao ngoại tuyến đã mã hóa của chủ sở hữu (quyết định của chủ sở hữu OD-9).

**Khi nào chiến lược `cold` đang bị hoãn được kích hoạt** ([`ROADMAP.md`](ROADMAP.vi.md) §4; được thu hẹp bởi [ADR-0031](adr/0031-data-providers.vi.md)): một bộ máy cơ sở dữ liệu mà thư mục dữ liệu riêng của nó phải được chép thô vì không có nhà cung cấp nào cho nó và không thể dump logic, hoặc một sự cố mà cả hook của ứng dụng lẫn nhà cung cấp đều không giữ được dữ liệu. Khi đó `cold` dừng project, chép các kho dữ liệu đã khai báo bằng một container trợ giúp và chỉ khôi phục với cùng image ID dữ liệu; nó sẽ được thiết kế bằng ADR khi việc đó xảy ra.

### 11.4 Yêu cầu tối thiểu cho máy

Một máy phải đáp ứng những điều này trước khi có thể được chứng nhận. Đáp ứng chúng không làm cho máy được hỗ trợ: mỗi bản build nền tảng vẫn cần chứng nhận máy riêng (§3.6, §10.4), và các tuyên bố hỗ trợ chỉ nêu các tổ hợp đã được kiểm thử.

- **Engine và Compose.** Một Docker Engine Linux cục bộ 24.0 trở lên (API 1.43 trở lên) với Compose v2 trở lên dưới dạng plugin `docker compose`, truy cập được qua socket cục bộ `/var/run/docker.sock` bằng root (bản thân Ingat chạy Compose đi kèm trong image của nó, không bao giờ dùng Compose của máy: §3.2). Trên máy Linux, dùng docker-ce từ kho của Docker được ghim theo phiên bản, hoặc một gói của bản phân phối trên một dòng Engine mà CI kiểm thử (§3.4). Daemon rootless và daemon từ xa và các tổ hợp khác của §11.1 không được hỗ trợ.
- **Truy cập và lập lịch.** SSH (hoặc màn hình điều khiển tại chỗ) với một tài khoản có thể `sudo` lên root (Docker cần root); một bộ lập lịch chạy việc của root mà không cần terminal và báo lỗi: systemd timer, cron, hoặc bộ lập lịch của nền tảng như DSM Task Scheduler ([`LIFECYCLE.md`](LIFECYCLE.vi.md) §7).
- **CPU.** `x86_64` (amd64) hoặc `aarch64` (arm64); arm64 chỉ với các dòng Engine mà làn CI của nó đạt (§10.1). Image riêng của Ingat nhắm tới mức cơ bản của từng kiến trúc (x86-64; mức cơ bản arm64 của Debian, ARMv8-A). Image ứng dụng phải có cho kiến trúc của máy và có thể yêu cầu mức CPU cao hơn (ví dụ image dựa trên RHEL hoặc UBI 9 cần x86-64-v2), điều mà phép thử canary theo từng image kiểm tra (§11.3 mục 6).
- **RAM.** Bản thân Ingat cần ít (Unverified: chưa đo; M0 sẽ ghi lại). Các ứng dụng quyết định phần còn lại, và một lần thử khôi phục khởi động một bản sao thứ hai của các dịch vụ dữ liệu của ứng dụng, nên hãy tính RAM cho các bản cài đang chạy cộng thêm một bản sao thử khôi phục. Khuyến nghị (chưa đo): ít nhất 4 GB cho một ứng dụng dùng PostgreSQL; 8 GB trở lên cho nhiều ứng dụng có trạng thái với thử khôi phục hằng tuần.
- **Đĩa.** Đủ chỗ cho các bản sao lưu được giữ lại, một vùng dữ liệu thêm trong lúc khôi phục, và các image ([`LIFECYCLE.md`](LIFECYCLE.vi.md) §5.8 kiểm tra dung lượng cho từng thao tác).
- **Ghi chú nền tảng: Synology.** DSM 7.4 trở lên với Container Manager 24.0.2 trở lên, có plugin `docker compose`; DSM 7.1 trở về trước với gói Docker cũ không được hỗ trợ (§11.1). Giá trị cài đặt và đặc điểm: §3.4 và §11.2.

## 12. Rủi ro

| ID | Rủi ro | Giảm nhẹ |
|---|---|---|
| R1 | Hồ sơ DSM: hành vi của môi trường chạy container (bind cùng đường dẫn, sống sót khi chạy tách rời, TTY, flock giữa các container trên một volume cục bộ (ext4 hoặc Btrfs), override logging `local`, `cpus: "0"`, route trên network nội bộ, việc xóa bởi `--rm`, image của các ứng dụng trên kernel DSM 4.4) là **Unverified**; việc thiếu CPU CFS quota là một sự thật đã xác nhận của DSM 7.4.1 với Container Manager 24.0.2-1706 | Thử nghiệm sớm M0 S1-S15 trên máy đầu tiên (một máy DSM thật) và trong CI trước khi viết mã tính năng; môi trường chạy dự phòng: cùng gói đó chạy trực tiếp trên máy với một python-build-standalone đã ghim cộng các chương trình tĩnh dưới `INGAT_ROOT/runtime/<version>/` |
| R2 | docker CLI 29 / Compose v5 với Engine 24.0.2 (API 1.43) là **Unverified** trong CI và trên máy đầu tiên (mới chỉ chạy trên dind thử cục bộ) | Làn `docker:24.0.2-dind` bắt buộc; không build trên máy (quyết định của chủ sở hữu OD-11, ADR-0026); dự phòng: một cặp phiên bản cũ hơn đã ghim |
| R3 | Ghim `image: sha256:<id>`, `build: !reset`, volume vùng dữ liệu external trong một override là **Unverified** trên Compose đi kèm | Thử nghiệm sớm S5; dự phòng: kiểm tra tag → ID trước mỗi lệnh gọi Compose |
| R4 | Hồ sơ DSM: `/volume1/ingat` có thể không còn sau một lần cập nhật hoặc sửa chữa DSM | Mục chứng nhận sau lần cập nhật DSM đầu tiên; dự phòng: một thư mục chia sẻ riêng chỉ cho quản trị viên, có các thư mục con được Ingat chmod rõ ràng, có kiểm tra dấu ACL |
| R5 | Bản sao lưu chứa dữ liệu cá nhân (ví dụ tài liệu đã ký và mã băm thông tin đăng nhập) | `INGAT_BACKUPS` chỉ root ghi và được chứng nhận như vậy (trên DSM là thư mục chia sẻ chỉ đọc cho quản trị viên); mã hóa phía client cho bản sao ngoài máy (restic hoặc borg trên Linux, Hyper Backup trên DSM); doctor báo dấu ACL ở nơi nền tảng có ACL |
| R6 | Một lần thử khôi phục hoặc khôi phục ứng dụng PostgreSQL chạy một PostgreSQL thứ hai; build trên máy một frontend Node và một backend Python cần RAM và thời gian bên cạnh các bản cài đang chạy (tính RAM: §11.4) | Từ chối theo `[drill] min_free_memory`; thử khôi phục ngoài giờ và cách xa nhau; build trong CI (quyết định của chủ sở hữu OD-11, ADR-0026) |
| R7 | Luôn tạm khóa khi image của phần ghi dữ liệu thay đổi làm mất vài phút gián đoạn mỗi bản phát hành | Quyết định của chủ sở hữu OD-4; dịch vụ web của ứng dụng PostgreSQL vẫn phục vụ phần vỏ ứng dụng (app shell) trong khi backend dừng |
| R8 | Các thao tác project trong giao diện quản lý container của hãng (trên DSM là Container Manager: "Clean" xóa container, network, volume và image của project và "Delete" xóa dữ liệu của nó) hoặc `docker compose` chạy tay tạo ra sự lệch trạng thái | `status`/`doctor` báo lệch image ID và mã băm cấu hình, đối tượng không thuộc Ingat và `changed-outside` (từ M1); hướng dẫn vận hành cấm các thao tác project của giao diện quản lý container của hãng (của Container Manager trên DSM) trên các project Ingat; phục hồi từ bản sao lưu của Ingat (§11.2). Việc Container Manager có liệt kê và có thể Clean một project do Ingat tạo hay không, và Clean có xóa volume external hay không, vẫn là Unverified; dù thế nào quy tắc vẫn áp dụng |
| R9 | Nâng cấp Engine lên một dòng chưa có làn CI (trên máy Linux) chặn bậc cổng 2 cho tới khi một bản phát hành công cụ thêm làn đó; mọi thay đổi của bản build Engine, kernel, phiên bản hệ điều hành hoặc storage driver (trên Linux là mọi lần cập nhật kernel, sau khi khởi động lại) cần một `selftest --host` trước khi bậc cổng 2, kể cả các lần thử khôi phục theo lịch, chạy lại được | Ghim gói Engine (docker-ce với `apt-mark hold` hoặc cách tương đương của bản phân phối); chỉ chuyển sang dòng mới cùng một bản phát hành công cụ đã kiểm thử nó; chạy `ingat selftest --host` sau mỗi lần khởi động lại vào kernel mới; cần chú ý `uncertified` sẽ gửi thư cho chủ sở hữu |
| R10 | Phạm vi phình to (công cụ cũ đã lớn gấp mười lần mà chưa từng chạy trên máy thật) | Một bộ khung chạy được (walking skeleton) chạy một ứng dụng thật (bản cài `lite-test` của ứng dụng SQLite) trên máy đầu tiên ở M1 trong giới hạn của nó (khoảng 3k dòng, được lập lại kế hoạch thành khoảng 6.6k với ngưỡng dừng ở khoảng 10k: [ADR-0028](adr/0028-m1-replan-runtime-size.vi.md)), giới hạn mô-đun, tính năng có lý do từ ứng dụng thật, quy tắc dừng 1.5× ([`ROADMAP.md`](ROADMAP.vi.md) §3) |
| R11 | Hồ sơ DSM: runc 1.1.7 của Container Manager 24.0.2-1706 bị ảnh hưởng bởi CVE-2024-21626 | Được ghi lại qua chứng nhận máy; image tin cậy ghim theo ID và digest; cổng chỉ trên loopback phía sau reverse proxy của máy; khuyến nghị chỉ cho máy tiếp xúc trong LAN; chứng nhận lại trên một bản build Container Manager có runc đã sửa (§11.2) |
| R12 | Hồ sơ DSM: Node.js 24 (môi trường chạy của ứng dụng SQLite, giai đoạn build web của ứng dụng PostgreSQL) ghi kernel 4.18 là mức tối thiểu Tier-1 của nó; nhiều nền tảng DSM 7.x chạy kernel 4.4.x | Thử nghiệm sớm S15 trước khi ứng dụng nào trong hai ứng dụng được tuyên bố là được hỗ trợ, kèm phương án dự phòng của nó ([`ROADMAP.md`](ROADMAP.vi.md) M0) |
| R13 | Hồ sơ DSM: DSM 7.4 hết thời gian bảo trì vào khoảng tháng 6 năm 2028 và không có thời gian hỗ trợ kéo dài | Chứng nhận lại trên dòng DSM kế tiếp trước thời điểm đó; cổng phiên bản từ chối bậc cổng 2 trên bản build chưa được chứng nhận (§3.6) |
| R14 | Hồ sơ DSM: trên volume ext4, Container Manager dùng aufs, vốn đã bị bỏ ở bản gốc từ Engine 24.0 và chỉ còn trong bản build của Synology; một bản build Container Manager đổi storage driver sẽ làm ẩn các image và container hiện có (volume và vùng dữ liệu kiểu bind vẫn còn) | `host check` so storage driver với `host.json` và coi một thay đổi là bản build mới cần chứng nhận lại; cách phục hồi là `prepare` (kéo lại các digest đã ghi sẽ khôi phục image: ADR-0026) rồi `deploy` |
