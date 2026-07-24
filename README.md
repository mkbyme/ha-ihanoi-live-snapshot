[![hacs][hacs-badge]][hacs-repo]
[![Project Maintenance][maintenance-badge]][maintenance]

## iHanoi Live Snapshot cho Home Assistant

Integration này lấy **ảnh snapshot** (khung hình đầu tiên/keyframe) từ camera giao thông
live trên **iHanoi** (`cds.hanoi.gov.vn`) để hiển thị trực tiếp trên UI
[Home Assistant](https://www.home-assistant.io) và dùng làm trigger cho automation —
không cần mở app/web iHanoi riêng để xem tình hình giao thông tại một điểm.

### Các tính năng

1. Thiết lập **một bước** — chọn camera cần thêm từ dropdown, danh sách camera đã có sẵn
   kèm theo tích hợp (không cần đăng nhập/gọi API để cài đặt lần đầu).
2. Theo dõi **nhiều camera cùng lúc**, mỗi camera là một Device riêng.
3. Entity **ảnh (`image`)** cho mỗi camera — chỉ cập nhật khi có yêu cầu (bấm nút hoặc
   camera list được làm mới), không polling liên tục tốn băng thông/CPU.
4. Entity **nút cập nhật (`button`)** cho mỗi camera — gọi được qua automation, chụp lại
   ảnh mới ngay lập tức và lưu thời điểm cập nhật.
5. **Ảnh luôn có nhãn thời gian** (`YYYY-MM-DD HH:MM:SS`) đóng ở góc dưới phải, chụp lúc
   nào biết ngay lúc đó — không cần đoán qua timestamp của sensor riêng.
6. Camera lỗi/mất kết nối **không làm mất ảnh cũ** — ảnh gần nhất vẫn giữ nguyên, tình
   trạng lỗi được báo qua entity nhị phân + thuộc tính `last_error` (xem bảng dưới).
7. Entity **nút "Update Camera List"** — làm mới bảng camera/`wss_url` từ API iHanoi
   (phiên `wss_url` có thời hạn sử dụng), đồng thời **tự động chụp lại ảnh cho tất cả
   camera đã chọn** trong cùng một lần bấm, không cần bấm thêm nút riêng từng camera.
8. **Tự động làm mới danh sách camera theo chu kỳ** (mặc định 60 phút, chỉnh được
   15/30/60/120/240 phút hoặc tắt hẳn) — phòng trường hợp `wss_url` hết hạn giữa hai lần
   bấm tay, mỗi lần làm mới cũng tự chụp lại ảnh như nút bấm ở trên.
9. Có thể đổi danh sách camera đồng bộ và chu kỳ tự động làm mới sau khi cài đặt mà
   không cần xóa integration.
10. Tên entity/device lấy từ tên camera trong danh sách iHanoi (rút gọn dưới 100 ký tự),
    ví dụ `"P.V.Đồng - Bến Xe Nam Thăng Long - C192.12-PTZ"`.
11. **Ảnh được nén JPEG thay vì lưu RAW/PNG**, với **tỉ lệ nén (30-100%) chỉnh được riêng
    cho từng camera** — camera nào cần ảnh nét hơn thì tăng %, camera nào chỉ cần xem
    nhanh thì giảm % để tiết kiệm dung lượng/băng thông.
12. Mỗi camera có thêm entity **ảnh preview (`image_preview`)** kích thước nhỏ (640x360 px)
    bên cạnh ảnh gốc — tiện cho dashboard/thông báo không cần độ phân giải đầy đủ. Ảnh
    preview cập nhật/giữ ảnh cũ khi lỗi giống hệt luồng của ảnh chính.
13. Entity **điều khiển tỉ lệ nén (`number`)** cho mỗi camera — chỉnh trực tiếp trên
    dashboard/qua automation mà không cần vào Settings > Configure, giá trị đồng bộ hai
    chiều với bước "Tỉ lệ nén ảnh JPEG" trong config/options flow.

### Entity được tạo (mỗi camera một Device)

| Entity | Loại | Ý nghĩa |
|---|---|---|
| `image.{ten_camera}` | Ảnh | Snapshot mới nhất (JPEG, nén theo tỉ lệ đã cấu hình) chụp được từ live stream của camera, có nhãn thời gian |
| `image.{ten_camera}_preview` | Ảnh | Bản thu nhỏ 640x360 px của snapshot ở trên, cùng thời điểm chụp |
| `number.{ten_camera}_quality` | Số (Config) | Tỉ lệ nén JPEG (30-100%) của camera này, chỉnh trực tiếp không cần vào Configure |
| `button.{ten_camera}_update` | Nút | Chụp lại ảnh ngay lập tức cho camera này (gọi qua automation) |
| `sensor.{ten_camera}_last_update` | Cảm biến (Diagnostic) | Thời điểm chụp ảnh thành công gần nhất; thuộc tính `last_error` báo lỗi lần chụp gần nhất nếu có |
| `binary_sensor.{ten_camera}_online` | Cảm biến nhị phân (Diagnostic, Connectivity) | `on` nếu lần chụp gần nhất thành công, `off` nếu camera lỗi/mất kết nối |
| `button.ihanoi_update_camera_list` | Nút (dùng chung, EntityCategory: Config) | Làm mới bảng camera từ API iHanoi + chụp lại ảnh cho toàn bộ camera đã chọn |

## Yêu cầu trước khi cài đặt

### `ffmpeg` trên PATH của máy chạy Home Assistant

Integration giải mã khung hình HEVC (keyframe) thành JPEG (nén theo tỉ lệ cấu hình cho
từng camera) bằng cách gọi CLI `ffmpeg` như một subprocess — đây là binary hệ thống, **không** cài được qua `pip`/`manifest.json`
`requirements`. Nếu chạy Home Assistant OS/Supervised, `ffmpeg` thường đã có sẵn; nếu chạy
Core/venv tự cài, cần đảm bảo `ffmpeg` có trong `PATH` trước khi dùng nút cập nhật ảnh,
nếu không nút bấm sẽ báo lỗi rõ ràng (`RuntimeError` từ `ffmpeg`) thay vì treo im lặng.

## Cài đặt

### Cách 1: Thêm nhanh qua HACS (khuyến nghị)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=mkbyme&repository=ha-ihanoi-live-snapshot&category=integration)

Sau khi tải xong, **khởi động lại Home Assistant**, rồi tiến hành [Thiết lập](#thiết-lập) phía dưới.

---

Hoặc thêm thủ công:
> HACS > Integrations > ⋮ > Custom repositories > `https://github.com/mkbyme/ha-ihanoi-live-snapshot` > Category: Integration

### Cách 2: Cài đặt thủ công qua Samba / SFTP

1. Tải phiên bản mới nhất từ [GitHub Releases](https://github.com/mkbyme/ha-ihanoi-live-snapshot/releases)
   (hoặc clone/tải trực tiếp thư mục `custom_components/ihanoi_live_snapshot`).
2. Sao chép thư mục `custom_components/ihanoi_live_snapshot` vào thư mục `custom_components`
   của Home Assistant.

    ```
    └── configuration.yaml
    └── custom_components
        └── ihanoi_live_snapshot
            └── __init__.py
            └── image.py
            └── button.py
            └── sensor.py
            └── binary_sensor.py
            └── device.py
            └── api.py
            └── hevc.py
            └── config_flow.py
            └── const.py
            └── manifest.json
            └── ihanoi_camera.json
            └── fonts/
            └── ...
    ```

3. Khởi động lại Home Assistant.

## Thiết lập

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=ihanoi_live_snapshot)

Hoặc tìm thủ công: **Settings > Devices & Services > Add Integration** → tìm `iHanoi Live Snapshot`.

- **Camera**: chọn một hoặc nhiều camera từ dropdown (danh sách lấy từ file mang theo sẵn
  cùng integration, không cần gọi API lúc này).
- **Chu kỳ tự động cập nhật danh sách camera (phút)**: mặc định 60 phút; đặt `0` để tắt
  hẳn, chỉ dùng nút "Update Camera List" khi cần.
- Ở bước tiếp theo: **Tỉ lệ nén ảnh JPEG (30-100%)** cho từng camera vừa chọn (mặc định
  85%) — áp dụng cho cả ảnh snapshot đầy đủ lẫn ảnh preview 640x360.

Sau khi xác nhận, mỗi camera được chọn sẽ xuất hiện như một Device riêng, gồm entity ảnh,
entity ảnh preview và nút cập nhật ở trên. Bấm nút cập nhật (hoặc gọi qua automation) để
có snapshot đầu tiên — ảnh sẽ trống cho tới khi được chụp lần đầu.

### Thay đổi danh sách camera / chu kỳ cập nhật / tỉ lệ nén sau khi cài đặt

Vào **Settings → Devices & Services → iHanoi Live Snapshot → Configure** để chỉnh lại
danh sách camera đồng bộ, chu kỳ tự động làm mới, hoặc tỉ lệ nén JPEG từng camera mà
không cần xóa và cài lại integration.

[hacs]: https://github.com/custom-components/hacs
[hacs-badge]: https://img.shields.io/badge/HACS-custom-0468BF.svg?style=for-the-badge
[hacs-repo]: https://github.com/mkbyme/ha-ihanoi-live-snapshot
[maintenance-badge]: https://img.shields.io/badge/maintainer-%40mkbyme-F2994B?style=for-the-badge
[maintenance]: https://github.com/mkbyme
