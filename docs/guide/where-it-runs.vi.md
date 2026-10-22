# Ingat chạy trên máy nào

[English](where-it-runs.md) · **Tiếng Việt** (bản dịch; bản tiếng Anh là bản chuẩn)

Ingat hỗ trợ những máy nào, và một máy cần có gì trước khi bạn cài Ingat.

## Máy cần có gì

- Một máy có **Linux, Docker Engine 24.0 trở lên và Docker Compose v2**: một máy chủ, máy ảo hoặc VPS, một bo mạch nhỏ, hoặc một NAS chạy được Docker. Bộ xử lý: `x86_64`, hoặc `arm64` với Docker 29.9.
- **Một phiên bản Docker đã kiểm thử, để được thay đổi.** Ingat chỉ thay đổi trên một phiên bản Docker mà bản phát hành này đã được kiểm thử cùng: hiện là 24.0 hoặc 29.9 trên `x86_64`, 29.9 trên `arm64`. Trên một phiên bản khác từ 24.0 trở lên, nó chỉ xem được và tạo được những bản sao lưu không cần dừng ứng dụng. Đừng để Docker tự cập nhật ([hướng dẫn vận hành §1](operator-guide.vi.md#1-trước-khi-bắt-đầu)).
- **Quyền root**, thường qua SSH (`sudo -i`).
- Một **bộ lập lịch** cho các việc chạy hằng đêm (systemd timer, cron, hoặc Task Scheduler trên NAS Synology) có gửi email cho bạn khi một việc bị lỗi.
- Một công cụ **chép các bản sao lưu sang nơi khác** (restic, borg, rsync, hoặc Hyper Backup trên NAS Synology).
- **Bộ nhớ:** bản thân Ingat cần rất ít. Hãy tính cho các ứng dụng của bạn, cộng thêm một bản sao các dịch vụ dữ liệu của một ứng dụng trong lúc thử khôi phục. Gợi ý, chưa đo thực tế: ít nhất 4 GB cho một ứng dụng dùng PostgreSQL, 8 GB trở lên cho nhiều ứng dụng có thử khôi phục hằng tuần.

Danh sách đầy đủ: [yêu cầu tối thiểu với máy](../design/ARCHITECTURE.vi.md#114-yêu-cầu-tối-thiểu-cho-máy).

## Các máy được hỗ trợ

Ingat xử lý khác biệt giữa các máy bằng cách kiểm tra mỗi máy làm được gì, không bao giờ dựa vào thương hiệu, hãng hay đời máy.

| | Máy | Cần gì |
|---|---|---|
| **Được hỗ trợ** | Linux mọi bản phân phối (máy chủ, máy ảo, VPS hay bo mạch nhỏ) với Docker Engine bản gốc (upstream) trên một dòng phiên bản mà CI kiểm thử: hiện là 24.0 và 29.9 trên `x86_64`, 29.9 trên `arm64` | `ingat selftest --host` trên máy đó, chạy lại sau mỗi lần cập nhật kernel, hệ thống hoặc Docker |
| **Được hỗ trợ, theo từng bản build đã chứng nhận** | Thiết bị dùng bản Docker do chính hãng build. Đầu tiên: Synology DSM 7.4 trở lên với Container Manager 24.0.2 trở lên. Đã chứng nhận đến nay: DSM 7.4.1 build 90080 với Container Manager 24.0.2-1706 trên `x86_64` | Một chứng nhận được commit cho từng dòng build, cộng với `ingat selftest --host` sau mỗi lần cập nhật |
| **Không được hỗ trợ** | Rootless Docker; Docker Desktop trên Windows hoặc macOS để dùng thật (chỉ để phát triển); Podman; Kubernetes hoặc Swarm; nhiều máy cùng lúc; Docker Engine cũ hơn 24.0, tức là loại bỏ Synology DSM 7.1 trở về trước với gói Docker cũ | Không có kế hoạch bổ sung trong v1 |

Khi bản build hệ thống và Docker của một máy chưa được chứng nhận, Ingat vẫn cho bạn xem mọi thứ và vẫn tiếp tục các bản sao lưu không cần dừng ứng dụng, nhưng từ chối mọi thay đổi. Thêm: [`docs/design/ARCHITECTURE.vi.md`](../design/ARCHITECTURE.vi.md#11-máy-và-bảng-hỗ-trợ) §11.

### Các bậc hỗ trợ và đặc điểm nền tảng, theo lời của bản đặc tả

Tóm tắt [`docs/design/ARCHITECTURE.vi.md`](../design/ARCHITECTURE.vi.md) §11.1-§11.2:

- **Bậc hỗ trợ 1 (support tier 1):** máy Linux chạy Docker Engine bản gốc (docker-ce hoặc gói của bản phân phối) trên một dòng Engine mà CI kiểm thử, trên `x86_64`, hoặc trên `arm64` với những dòng mà làn arm64 đã đạt (chỉ 29.x). Các làn CI bao phủ bậc này từ M1; các lệnh có thay đổi (bậc cổng 2, gate tier 2) cần một chứng nhận `ingat selftest --host` tại máy cho bản build nền tảng của máy đó. Chứng nhận Linux thông thường đầu tiên được commit đã lên kế hoạch (Planned) cho phần việc 12 của M4, khi có một máy như vậy.
- **Bậc hỗ trợ 2 (support tier 2):** các engine do hãng build trên thiết bị, trước hết là Synology DSM 7.4 trở lên với Container Manager 24.0.2 trở lên (bản build Engine 24.0.2 của Synology, API 1.43). Mỗi dòng bản build nền tảng cần một chứng nhận được commit theo đầy đủ danh sách kiểm tra, và mỗi lần cập nhật cần một `ingat selftest --host` tại máy; trong lúc chờ, các bản sao lưu hằng đêm không cần dừng ứng dụng vẫn tiếp tục, còn các lần thử khôi phục theo lịch thì từ chối. DSM 7.4 hết thời gian bảo trì vào khoảng tháng 6 năm 2028, nên việc chuyển sang dòng DSM tiếp theo là một lần chứng nhận lại đã được tính trước.
- **Đặc điểm:** Ingat từ chối giới hạn `cpus` khác 0 ngay lúc lập kế hoạch trên máy không có CPU CFS quota, ghi log qua driver `local` bất kể mặc định của daemon (tác vụ terminal và CLI qua `none`), ghi nhận runc cũ (CVE-2024-21626) hoặc việc thiếu seccomp như một rủi ro của máy, không phụ thuộc vào storage driver hay phiên bản cgroup nào, và dựa việc phục hồi vào các bản sao lưu đã niêm phong cộng với một bản sao mã hóa ở nơi khác làm bằng công cụ của nền tảng, không bao giờ dựa vào snapshot. Dind bản gốc không tái tạo được một Engine của hãng, nên chỉ chứng nhận máy mới bao phủ được nó.

