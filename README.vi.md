# Ingat

[English](README.md) · **Tiếng Việt** (bản dịch; bản tiếng Anh là bản chuẩn)

[![CI](https://github.com/LisaHQ/ingat/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/LisaHQ/ingat/actions/workflows/ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)

**Cài đặt, cập nhật và sao lưu các ứng dụng bạn chạy bằng Docker Compose trên máy chủ hay NAS của chính bạn, mà không bao giờ đem dữ liệu ra đánh cược.**

Ingat là một công cụ dòng lệnh nhỏ cho một máy: máy chủ ở nhà, VPS, bo mạch nhỏ hay NAS chạy Docker. Nó cài các ứng dụng của bạn từ đúng một phiên bản, cập nhật chúng, sao lưu chúng mỗi đêm, và chứng minh từng bản sao lưu bằng cách khôi phục nó vào một bản thử riêng. Mọi thay đổi có thể chạm tới dữ liệu đều bắt đầu bằng một bản sao lưu đã kiểm tra. *Ingat* nghĩa là "hãy nhớ, hãy cẩn thận" trong tiếng Mã Lai và tiếng Indonesia, và "bảo trọng nhé!" trong tiếng Tagalog.

## Điểm nổi bật

- **Luôn sao lưu trước mọi thay đổi rủi ro.** Trước khi một lần cập nhật chạm tới dữ liệu, Ingat dừng các phần của ứng dụng ghi dữ liệu, tạo một bản sao lưu đã niêm phong và kiểm tra nó. Nếu sao lưu thất bại, không có gì bị thay thế.
- **Bản sao lưu đáng tin.** Một bản sao lưu chỉ được tính là đã thử khôi phục sau khi Ingat khôi phục đúng bản đó vào một bản thử riêng của ứng dụng và các bước kiểm tra riêng của ứng dụng đều đạt.
- **Không bao giờ ghi đè dữ liệu.** Một lần khôi phục đổ dữ liệu vào một vùng dữ liệu mới và giữ lại vùng cũ (khôi phục sẽ có ở M2).
- **An toàn khi mất kết nối.** Hầu hết mọi thay đổi chạy trong một trình trợ giúp trên máy, không nằm trong cửa sổ SSH của bạn, và mỗi bước được ghi lại trước, nên một việc bị ngắt có thể làm tiếp hoặc hoàn tác.
- **Chỉ đụng tới những gì của nó.** Không `docker system prune`, không `down -v`, không `--force`: Ingat chỉ xóa những gì nó đã tạo và đã liệt kê trong một kế hoạch.
- **Lời lẽ dễ hiểu.** Mỗi thông báo nói chuyện gì đã xảy ra và lệnh nào cần chạy tiếp. Việc xem và sao lưu chạy không cần người; mọi thay đổi đều chờ bạn gõ duyệt.

## Bắt đầu nhanh

Bạn cần Linux với một phiên bản Docker Engine mà bản phát hành này đã được kiểm thử cùng (24.0 hoặc 29.9 trên `x86_64`, 29.9 trên `arm64`) và quyền root. Tải `install.sh`, `facts.sh` và `SHA256SUMS` từ [trang phát hành](https://github.com/LisaHQ/ingat/releases) vào cùng một thư mục (v0.1.0 vẫn là bản nháp, nên việc này chỉ làm được khi nó đã được công bố), rồi:

```sh
sudo -i
cd /path/to/downloads                                       # thư mục chứa các tệp phát hành
sh install.sh --version 0.1.0 --link /usr/local/bin/ingat   # trên NAS Synology thêm --root /volume1/ingat --backups /volume1/ingat-backups
ingat host init                                             # gõ đúng tên mà lệnh hostname in ra
ingat selftest --host                                       # kiểm thử máy này; mất vài phút
```

Sau đó mô tả ứng dụng của bạn trong một tệp bản cài ở thư mục nhận tệp (inbox) của Ingat (`/srv/ingat/inbox/`, trên NAS là `/volume1/ingat/inbox/`) và cài nó:

```sh
ingat init lite-test --config /srv/ingat/inbox/lite-test.toml --ref v1.2.0
ingat deploy lite-test v1.2.0                               # hiện kế hoạch; gõ lite-test để duyệt
ingat status lite-test
```

[Hướng dẫn vận hành](docs/guide/operator-guide.vi.md) đi qua từng bước, cách chuẩn bị NAS Synology, tệp bản cài và việc sao lưu hằng đêm.

## Tài liệu

- **Chạy Ingat:** [hướng dẫn vận hành](docs/guide/operator-guide.vi.md), [mọi lệnh](docs/guide/commands.vi.md), [chạy trên máy nào](docs/guide/where-it-runs.vi.md), [cách giữ dữ liệu của bạn an toàn](docs/guide/how-it-works.vi.md), [các từ dùng trong Ingat](docs/guide/glossary.vi.md), [tình trạng và lộ trình](docs/guide/status.vi.md).
- **Làm cho ứng dụng của bạn chạy được với Ingat:** [các tệp `ingat.toml` và `instance.toml`](docs/app-developers/MANIFEST_SPEC.vi.md) và [danh sách việc khi đưa ứng dụng vào](docs/design/ARCHITECTURE.vi.md#113-quy-tắc-tổng-quát).
- **Đóng góp, hoặc phát triển Ingat cùng một agent AI:** đọc [`CLAUDE.md`](CLAUDE.md) trước, rồi [kiến trúc](docs/design/ARCHITECTURE.vi.md), [vòng đời và các quy tắc an toàn bắt buộc](docs/design/LIFECYCLE.vi.md), [lộ trình](docs/design/ROADMAP.vi.md), [các bản ghi quyết định](docs/design/adr/README.vi.md) và [quy ước và tên gọi](docs/design/CONVENTIONS.vi.md).

Mỗi tài liệu Markdown, trừ `CLAUDE.md`, đều có một bản tiếng Việt bên cạnh (`<name>.vi.md`); bản tiếng Anh là bản chuẩn.

## Tình trạng

Mới ở giai đoạn đầu. v0.1.0 là bản phát hành thử đầu tiên, vẫn là bản nháp. CI đạt trên Docker thật (Engine 24.0 và 29.9 trên `x86_64`, 29.9 trên `arm64`), và máy thật đầu tiên, một NAS Synology chạy DSM 7.4.1, đã đạt `ingat selftest --host`. Mốc M1 chưa xong cho tới khi ứng dụng thật đầu tiên chạy trên đó; khôi phục sẽ có ở M2. Thêm: [tình trạng và lộ trình](docs/guide/status.vi.md).

## Giấy phép

[Apache License 2.0](LICENSE). Ingat miễn phí và sẽ luôn miễn phí: mọi thứ dùng để giữ gìn hay khôi phục dữ liệu của bạn sẽ không bao giờ phải trả tiền, không bao giờ bị giới hạn và không bao giờ phụ thuộc vào gói dịch vụ.
