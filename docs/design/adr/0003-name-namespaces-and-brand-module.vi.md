# ADR-0003 Tên, không gian tên và một mô-đun thương hiệu duy nhất

[English](0003-name-namespaces-and-brand-module.md) · **Tiếng Việt** (bản dịch; bản tiếng Anh là bản chuẩn)

**Trạng thái:** Đã chấp nhận; tài khoản, không gian tên và chế độ công khai do chủ sở hữu quyết định ngày 2026-10-14 (quyết định của chủ sở hữu OD-2, OD-3); tên sản phẩm Ingat được chủ sở hữu xác nhận ngày 2026-10-14 (quyết định của chủ sở hữu OD-1); các thư mục gốc mặc định được đổi thành dạng chung (generic) ngay trong ngày đó, trước khi viết bất kỳ dòng mã nào ([ADR-0025](0025-host-baseline.vi.md)).

**Nói đơn giản:** Các tên được chốt một lần: Ingat, lệnh `ingat`, tổ chức LisaHQ, tên nhãn và tên image, và các thư mục mặc định. Trong mã, chúng chỉ nằm trong một tệp tên và mẫu script khởi động, vì nhãn Docker không đổi tên được về sau.

## Bối cảnh

Nhãn (label) Docker trên volume và network không thay đổi được sau khi tạo; công cụ cũ đã ghi các tên định danh trước khi có quyết định về tên. Docker yêu cầu công cụ bên thứ ba đặt trước tên nhãn (label key) một tiền tố reverse-DNS mà họ kiểm soát, và dành riêng `com.docker.*`, `io.docker.*` và `org.dockerproject.*` ([nhãn đối tượng Docker (Docker object labels)](https://docs.docker.com/engine/manage-resources/labels/)). Chủ sở hữu chọn tổ chức GitHub LisaHQ và một repository công khai.

## Quyết định

Sản phẩm Ingat, CLI `ingat`, repository `github.com/LisaHQ/ingat`, tiền tố biến môi trường `INGAT_`, không gian tên nhãn `io.github.lisahq.ingat.` (chữ thường), image `ghcr.io/lisahq/ingat`, thư mục gốc mặc định `/srv/ingat` và `/srv/ingat-backups` (đổi được lúc cài; một hồ sơ nền tảng (platform profile) truyền thư mục riêng của nó, ví dụ `/volume1/ingat` và `/volume1/ingat-backups` trên DSM, dưới dạng giá trị lúc cài chứ không phải giá trị mặc định trong mã: [ADR-0025](0025-host-baseline.vi.md)). Tất cả chỉ nằm trong `src/ingat/brand.py` và mẫu script khởi động (wrapper); một bài kiểm thử lint cấm các chuỗi này xuất hiện ở chỗ khác trong mã. Tài liệu thì ghi chúng nguyên văn.

## Các phương án khác

Lodge, Ghim, Upkip (quyết định của chủ sở hữu OD-1). Kipu, phương án dự phòng của một lần rà soát tên trước đó: lần rà soát không gán cho nó ý nghĩa nào và đề xuất nó là thương hiệu sạch nhất theo các phép kiểm tra trùng tên, cho một chủ sở hữu muốn có một thương hiệu hơn là một cái tên mô tả, và chỉ ghi chú nghĩa "đau" (pain) trong tiếng Phần Lan như một rủi ro bên lề. Không chọn: nó không mang ý nghĩa gì với công cụ này, còn Ingat qua kiểm tra vẫn sạch mà lại có nghĩa "take care" (hãy giữ gìn).

## Hệ quả

Mọi dạng tên đều theo tên chính (`github.com/LisaHQ/ingat`, `io.github.lisahq.ingat.`, `ghcr.io/lisahq/ingat`). Đổi tên trước bản cài (instance) thật đầu tiên của M1 vẫn chỉ là tìm và thay cộng với một tệp hằng số. Sau khi đã có volume thật, đổi tên nghĩa là tạo các bản cài mới rồi khôi phục dữ liệu vào.
