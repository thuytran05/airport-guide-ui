---
name: backend-fastapi-ros-adapter
description: >-
  Sử dụng skill này khi cần kiểm tra, phát triển hoặc debug Backend FastAPI,
  RosRobotAdapter, MockRobotAdapter, REST API endpoints, WebSocket Telemetry,
  hoặc chạy kiểm thử tự động pytest trong container backend.
---

# Backend FastAPI & ROS Adapter Runbook

Skill này hướng dẫn quy trình phát triển, kiểm tra và bảo trì tầng Backend của hệ thống Airport Guide Robot.

## 1. Kiến trúc Tầng Adapter
Backend sử dụng mô hình Adapter Pattern để cách ly nghiệp vụ Web khỏi phần cứng và giao thức ROS:
* **`app/adapters/base.py`:** Định nghĩa lớp trừu tượng `BaseRobotAdapter` với các phương thức bắt buộc (`get_status()`, `get_map_metadata()`, `get_map_image()`, `navigate_to()`,...).
* **`app/adapters/ros_adapter.py`:** Triển khai kết nối thực tế với ROS 2 Jazzy qua thư viện `rclpy`.
* **`app/adapters/mock_adapter.py`:** Triển khai dữ liệu mô phỏng, dùng cho môi trường không có ROS 2 hoặc khi chạy unit test.
* **`app/adapters/factory.py`:** Lựa chọn adapter dựa vào biến môi trường `ROBOT_ADAPTER_MODE` (`ros` hoặc `mock`).

## 2. Kiểm thử Tự động (Pytest)

> [!NOTE]
> Khi chạy pytest bên trong container `airport_guide_backend`, cần chỉ định `PYTHONPATH=/app` và gán `ROBOT_ADAPTER_MODE=mock` cho các bài kiểm tra logic thuần túy:

```bash
docker exec airport_guide_backend bash -c "export PYTHONPATH=/app ROBOT_ADAPTER_MODE=mock && pytest -o cache_dir=/tmp/.pytest_cache /app/tests"
```

## 3. Kiểm tra các Endpoint API cốt lõi

### Health Check (`GET /api/health`)
Xác nhận trạng thái adapter, kết nối robot và số lượng client WebSocket:
```bash
curl -s http://localhost:5173/api/health | jq .
```
Kỳ vọng kết quả:
* `status: "healthy"`
* `adapter_mode: "ros"`
* `robot_connected: true` (khi AMCL và /clock đang hoạt động)

### Map Metadata (`GET /api/robot/map`)
Trả về metadata bản đồ OccupancyGrid thực tế từ ROS:
```bash
curl -s http://localhost:5173/api/robot/map | jq .
```
Kỳ vọng kết quả:
* `status: "ready"`
* `frame_id: "map"`
* `metadata`: chứa `width`, `height`, `resolution`, `origin_x`, `origin_y`, `origin_yaw`
* `image_url`: `/api/robot/map/image?v=<version_id>`

### Map Image (`GET /api/robot/map/image?v=<version_id>`)
Kiểm tra phản hồi ảnh PNG và HTTP headers caching:
```bash
curl -s -D - "http://localhost:5173/api/robot/map/image?v=<version_id>" -o /dev/null
```
Kỳ vọng:
* `HTTP/1.1 200 OK`
* `Content-Type: image/png`
* `Cache-Control: public, max-age=31536000, immutable`

## 4. WebSocket Telemetry Broadcaster
Vòng lặp broadcaster (`app/ws/broadcaster.py`) phát telemetry với tần số 5 Hz đến tất cả client kết nối:
* **Payload bao gồm:** `pose` (`{x, y, theta}` tính theo radian), `frame_id`, `stamp`, `is_connected`, `is_data_stale`, `sim_clock_stalled`, `map_version`.
* **Quy tắc an toàn:** Tuyệt đối không gửi lại ảnh bản đồ trong gói tin telemetry; chỉ gửi `map_version` để client chủ động tải ảnh khi có bản đồ mới.
