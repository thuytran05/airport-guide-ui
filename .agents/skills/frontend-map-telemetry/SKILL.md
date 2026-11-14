---
name: frontend-map-telemetry
description: >-
  Sử dụng skill này khi cần kiểm tra, phát triển hoặc debug giao diện Frontend React/TypeScript,
  thành phần MapView hiển thị OccupancyGrid thực tế, marker robot có hướng,
  phép chiếu tọa độ ROS sang pixel, và luồng WebSocket trong RobotContext.
---

# Frontend MapView & Telemetry Runbook

Skill này hướng dẫn quy trình phát triển và kiểm tra giao diện người dùng hiển thị bản đồ OccupancyGrid thực tế và tọa độ robot.

## 1. Kiến trúc Tầng Frontend
* **Framework:** React 19, Vite, TypeScript.
* **Server phục vụ:** Nginx trên Alpine (`frontend/nginx.conf`), phục vụ trên cổng `5173`.
* **State Management:** `src/contexts/RobotContext.tsx` quản lý kết nối WebSocket (`/ws`) và tải bản đồ (`/api/robot/map`).
* **Hiển thị Bản đồ:** `src/components/MapView/MapView.tsx` dựng hình bản đồ SVG kết hợp thẻ `<image>` chứa ảnh PNG thực tế từ ROS.

## 2. Công thức Phép chiếu Tọa độ và Góc Xoay

### Phép chiếu Tọa độ ROS sang Pixel Bản đồ (`projectRosToMapPixel`):
Hệ tọa độ ảnh SVG có gốc `(0, 0)` tại góc trên bên trái, trục Y hướng xuống dưới; trong khi ROS OccupancyGrid có gốc tại góc dưới bên trái:
```typescript
const dx = rosX - originX;
const dy = rosY - originY;
const a = originYaw; // Radian
const px = (Math.cos(a) * dx + Math.sin(a) * dy) / resolution;
const py = height - (-Math.sin(a) * dx + Math.cos(a) * dy) / resolution;
```

### Tính Góc Hướng Robot (`calculateHeadingDeg`):
Marker robot mặc định hướng sang phải (trục `+X` trong SVG, tương ứng 0 radian). Khi xoay theo hệ tọa độ SVG (trục Y hướng xuống):
```typescript
const headingDeg = -((theta - originYaw) * 180) / Math.PI;
```

## 3. Quy tắc Quản lý Tải Bản đồ và WebSocket
1. **Khử trùng lặp tải ảnh:** `RobotContext` chỉ tải ảnh PNG khi `map_version` thay đổi hoặc khi khởi động ứng dụng. Tuyệt đối không gọi tải ảnh lặp lại theo nhịp 5 Hz của WebSocket.
2. **Nguyên tắc Cặp Dữ liệu:** Metadata và ảnh PNG phải đi liền một cặp. Chỉ kích hoạt hiển thị cặp mới khi ảnh PNG đã được tải hoàn tất (`new Image()`).
3. **Xử lý Dữ liệu Cũ (Stale) hoặc Mất kết nối:**
   * Lưu trữ `lastKnownPoseRef` khi dữ liệu hợp lệ.
   * Nếu mất kết nối, sim clock bị dừng hoặc dữ liệu stale: chuyển màu marker sang xám trung tính (`#64748B`), giảm opacity của vòng hào quang và hiển thị badge cảnh báo.
   * Không đưa thuật ngữ ROS/Docker vào giao diện hành khách (Viewer).

## 4. Quy trình Biên dịch và Triển khai
```bash
# 1. Build lại image frontend
docker compose build frontend

# 2. Khởi động lại container frontend
docker compose up -d frontend

# 3. Kiểm tra log Nginx để xác nhận không bị spam request ảnh
docker compose logs --tail=30 frontend | grep "map/image"
```
Kỳ vọng: Endpoint `map/image` chỉ xuất hiện 1 lần cho mỗi lượt tải trang của client.
