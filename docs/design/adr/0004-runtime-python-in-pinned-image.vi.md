# ADR-0004 Môi trường chạy: Python 3.13 trong một image được ghim, khởi động bằng một script POSIX

[English](0004-runtime-python-in-pinned-image.md) · **Tiếng Việt** (bản dịch; bản tiếng Anh là bản chuẩn)

**Trạng thái:** Đã chấp nhận (thử nghiệm sớm (spike) ở M0 có thể kích hoạt phương án dự phòng); sửa đổi ngày 2026-10-14, trước khi viết bất kỳ dòng mã nào, để hỗ trợ máy mà không phụ thuộc nền tảng: image là đa kiến trúc (multi-arch) ([ADR-0025](0025-host-baseline.vi.md)).

**Nói đơn giản:** Ingat được phát hành dưới dạng một container image, cho `x86_64` và `arm64`, bên trong có sẵn một bản Python, dòng lệnh Docker, Compose và git cố định. Một script shell nhỏ trên máy khởi động nó, nên máy nào cũng chạy đúng những tệp đã được kiểm thử, bất kể bản thân máy có Python hay Compose nào.

## Bối cảnh

Ingat chạy trên mọi máy Linux có Docker, và Python cũng như Compose cài sẵn trên máy thì khác nhau tùy nền tảng. Python của DSM đã hết hạn hỗ trợ (3.8 của hệ thống, 3.9 dạng gói). Container Manager 24.0.2-1706, bản build mới nhất (cần DSM 7.4), đi kèm bản build Engine 24.0.2 của Synology (API 1.43); một bản build sau có thể đổi Engine, và việc đó do cổng kiểm tra phiên bản cùng việc chứng nhận lại xử lý ([ADR-0014](0014-tiered-version-gate.vi.md)). Synology không công bố phiên bản Compose đi kèm. Một máy Linux dùng gói của Docker chạy Engine 29.x. Máy có thể là `amd64` hoặc `arm64`. Bộ máy kiểm soát độ tin cậy của Python trên máy ở công cụ cũ tốn khoảng 4.9k dòng và làm đóng băng việc nâng cấp. Chủ sở hữu đánh giá (review) mã Python.

## Quyết định

Mỗi bản phát hành có một OCI image đa kiến trúc (`linux/amd64` và `linux/arm64` dưới một index digest; arm64 chỉ được công bố là hỗ trợ sau khi làn kiểm thử (lane) CI của nó qua: [ADR-0025](0025-host-baseline.vi.md)), trong đó ghim Python 3.13, docker CLI dạng tĩnh, Compose v5.x, git và, chỉ khi quyết định của chủ sở hữu OD-11 chọn build image trên máy (phương án a), buildx. Một script khởi động (wrapper) `sh` dài 20 dòng, thuộc root, ghim digest của image và chạy nó với socket, các thư mục gốc cùng đường dẫn, `--init`, `--network host` và `env -i` ([ARCHITECTURE.md](../ARCHITECTURE.vi.md) §3.3). Ưu tiên thư viện chuẩn trước; một thư viện bên ngoài cần một ADR và một tệp khóa phiên bản theo mã băm (hash lock).

## Các phương án khác

Python zipapp trên trình thông dịch của máy (bị loại: trình thông dịch đã hết hạn hỗ trợ, Compose không được ghim). Tệp chạy Go biên dịch tĩnh (bị loại làm phương án chính: một ngôn ngữ mà chủ sở hữu không đánh giá, Compose vẫn phải đi kèm bên cạnh; Compose Go SDK cần `docker/cli v28.5.2+incompatible`). Node/TypeScript (bị loại: cần môi trường chạy trên máy và các bản build tệp chạy đơn lẻ rất lớn mà không được lợi gì). **Phương án dự phòng** nếu các thử nghiệm sớm S1-S3 thất bại: cùng gói đó chạy trên máy bằng một CPython python-build-standalone được ghim phiên bản, cùng các tệp chạy tĩnh như trên, đặt dưới `INGAT_ROOT/runtime/<version>/`, có kiểm tra checksum; mã không thay đổi.

## Hệ quả

CI kiểm thử đúng sản phẩm mà máy chạy, theo từng kiến trúc. Mọi máy chạy cùng một chuỗi byte cho kiến trúc của nó. Nâng cấp là thay image. Quyền truy cập socket tương đương quyền root, như với mọi phương án.
