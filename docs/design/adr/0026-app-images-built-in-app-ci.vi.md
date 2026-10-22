# ADR-0026 Image của ứng dụng được build trong CI của từng ứng dụng rồi kéo về (pull), không bao giờ build trên máy

[English](0026-app-images-built-in-app-ci.md) · **Tiếng Việt** (bản dịch; bản tiếng Anh là bản chuẩn)

**Trạng thái:** Đã chấp nhận (quyết định của chủ sở hữu OD-11, phương án (b), 2026-10-15).

**Nói đơn giản:** Ingat không bao giờ build image của ứng dụng. CI của mỗi ứng dụng build và công bố chúng; Ingat tải chúng về, ghim chúng theo ID và digest, và chỉ nhận một image do chính ứng dụng build khi nhãn của nó ghi đúng commit đang được cài.

## Bối cảnh

Quyết định của chủ sở hữu OD-11 hỏi image của ứng dụng được build ở đâu: (a) trên máy, trong `prepare`, với một buildx đóng gói sẵn trong image của công cụ, hoặc (b) trong CI của từng ứng dụng, công bố lên một registry (kho image) rồi máy kéo về. Repository của cả hai ứng dụng tham chiếu đều công khai, nên image công bố lên GHCR được lưu và kéo về miễn phí mà không cần đăng nhập. Build trên máy làm máy nặng thêm bên cạnh các bản cài đang chạy và các lần thử khôi phục, làm đầy thư mục gốc của Docker bằng bộ nhớ đệm build, build lại cùng một commit thành các image ID khác nhau trên máy khác, và là hạng mục chưa được kiểm chứng lớn nhất của M1-M2 (các phép kiểm tra build của thử nghiệm sớm S4). Bản thiết kế để ADR này quyết định "khóa nêu tên nguồn" ([ROADMAP.md](../ROADMAP.vi.md) M0, [MANIFEST_SPEC.md](../../app-developers/MANIFEST_SPEC.vi.md) §2.1).

## Quyết định

- Ingat không bao giờ build image. Image của công cụ không chứa buildx, và `prepare` không chạy bước build nào.
- Không có khóa manifest mới. Tham chiếu image mà một dịch vụ Compose nêu ra, được điền bằng các tham số (params) của bản cài cho bản chuẩn bị triển khai (candidate) (ví dụ một tham số `template` `"ghcr.io/<owner>/<app>:{commit}"`), chính là nguồn. `prepare` kéo mỗi image của bản chuẩn bị một lần theo tham chiếu đó (một tham chiếu theo digest mà image đã có sẵn thì không kéo lại), rồi ghim nó theo image ID và ghi digest repository của nó vào bản chuẩn bị và vào sổ image (image ledger).
- `[compose] build_services` giữ nguyên ý nghĩa: các dịch vụ có image do chính ứng dụng tạo ra. Với các dịch vụ này, `expect_labels` là bắt buộc và ít nhất một giá trị trong đó phải chứa `{commit}` (thường là `org.opencontainers.image.revision = "{commit}"`), để một image kéo về chỉ được nhận khi nhãn của nó gắn nó với đúng commit đang được triển khai. Nếu không khớp thì từ chối bản chuẩn bị; không bao giờ chỉ tin vào một tag.
- `[compose] build_files` và `build_env` vẫn nằm trong schema 1 nhưng không được dùng cho tới khi việc build trên máy quay lại (hạng mục đã hoãn trong [ROADMAP.md](../ROADMAP.vi.md) §4).
- CI của mỗi ứng dụng công bố image cho kiến trúc của mọi máy mà ứng dụng chạy trên đó, gắn tag theo commit và gắn nhãn OCI `version` và `revision` (một thay đổi ở phía ứng dụng).

## Các phương án khác

(a) Build trên máy bằng buildx qua Bake của Compose (bị loại: máy nặng thêm và có bộ nhớ đệm build ngay bên cạnh production, đây là hạng mục chưa kiểm chứng lớn nhất của thử nghiệm sớm, và image ID khác nhau giữa các máy, khiến việc khôi phục sang máy khác chạy những byte đã được build lại). Một khóa manifest mới nêu tên repository trên registry cho từng dịch vụ (bị loại: tệp Compose đã nêu tên image; một tên thứ hai có thể không khớp với nó). Kéo về theo một digest ghi trong repository của ứng dụng (bị loại: một commit không thể ghi digest của một image được build từ chính nó).

## Hệ quả

Máy không bao giờ build, nên thử nghiệm sớm S4 bỏ các phép kiểm tra build của nó và S15 bỏ giai đoạn build trên máy. Các image được ghi trong một bản sao lưu (bundle) có thể kéo về theo digest trên bất kỳ máy nào, nên một lần khôi phục sang máy khác (M4) chạy đúng những byte đó. Một ứng dụng chưa có CI công bố image phải chờ con đường build trên máy đã hoãn. Các bài kiểm thử dùng một registry cục bộ bên trong Docker daemon tạm (scratch) cho con đường `build_services`.
