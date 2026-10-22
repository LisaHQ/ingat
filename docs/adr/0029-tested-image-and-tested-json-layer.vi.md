# ADR-0029 Mỗi pipeline build image một lần, mọi làn kiểm thử đều kiểm thử bản build đó, và tested.json là lớp cuối cùng của nó

[English](0029-tested-image-and-tested-json-layer.md) · **Tiếng Việt** (bản dịch; bản tiếng Anh là bản chuẩn)

**Trạng thái:** Đã chấp nhận (2026-10-15).

**Nói đơn giản:** Mỗi lần chạy CI build image Ingat một lần, và mọi làn kiểm thử (lane) đều kiểm thử đúng bản build đó. Bản phát hành là chính bản build đó cộng thêm một lớp (layer) cuối chứa `tested.json`, danh sách các phiên bản Docker mà làn kiểm thử của chúng đã qua.

## Bối cảnh

CLAUDE.md (mục Testing and Validation) và [ARCHITECTURE.md](../ARCHITECTURE.vi.md) §10.1 yêu cầu mỗi làn kiểm thử phải kiểm thử "đúng image công cụ được build trong pipeline đó", và §3.6 yêu cầu mọi bản phát hành phải chứa sẵn `tested.json`, do CI tạo ra từ các làn kiểm thử đã qua. Hai yêu cầu này gặp nhau thành một vòng lặp: `tested.json` chỉ biết được sau khi các làn kiểm thử đã chạy, mà đưa nó vào thì image thay đổi. Build image riêng trong mỗi làn kiểm thử, rồi build lại cho bản phát hành, cũng không cho ra đúng tệp kết quả (artifact) đó: các gói Debian cài lúc build có thể khác nhau giữa hai lần build chỉ cách nhau vài phút.

## Quyết định

- Mỗi pipeline có một job build image đa kiến trúc một lần (`linux/amd64`, `linux/arm64`) từ `image/versions.lock` và xuất một tarball `docker save` cho mỗi kiến trúc làm tệp kết quả của pipeline. Mọi làn kiểm thử nạp tarball của đúng kiến trúc mình vào daemon tạm (scratch) của mình và kiểm thử đúng các lớp đó.
- Image kiểm thử của một làn thêm vào đó một lớp cuối: `tested.json` liệt kê dòng Engine, kiến trúc, CLI và Compose của chính làn đó, để các bộ kiểm thử bậc cổng 2 (gate tier 2) chạy được. Image phát hành là chính bản build đó cộng một lớp cuối chứa `tested.json` được tạo từ các làn kiểm thử đã qua. Mọi lớp khác, và vì vậy toàn bộ mã, giống từng byte với những gì các làn kiểm thử đã kiểm thử; ghi chú phát hành nêu cả hai digest (mã băm nhận dạng image).
- `tested.json` chỉ được đọc từ dữ liệu gói bên trong image; vẫn không có tệp hay cờ (flag) nào trên máy có thể nới rộng bậc cổng 2 (ADR-0014).

## Các phương án khác

Build trong từng làn rồi build lại cho bản phát hành (bị loại: không phải đúng tệp kết quả đó). Đưa vào một `tested.json` viết trước khi các làn kiểm thử chạy (bị loại: nó sẽ khẳng định những tổ hợp chưa làn nào kiểm thử qua). Phát hành `tested.json` bên cạnh image, như một tệp của bản phát hành được cài lên máy (bị loại: ADR-0014 cấm một tệp trên máy nới rộng bậc cổng 2).

## Hệ quả

Quy trình CI có thêm một job build mà các làn kiểm thử phụ thuộc vào, và quy trình phát hành dùng lại bản build của pipeline thay vì build lại. Kết luận của một làn kiểm thử bao trùm các lớp đã kiểm thử; lớp `tested.json` cuối cùng là dữ liệu mà cổng phiên bản (gate) đọc, được kiểm thử bằng các bài kiểm thử đơn vị riêng của cổng.
