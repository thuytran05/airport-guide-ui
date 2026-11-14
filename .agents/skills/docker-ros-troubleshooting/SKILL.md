---
name: docker-ros-troubleshooting
description: >-
  Sử dụng skill này khi cần kiểm tra, debug, khởi động lại hoặc xử lý sự cố mạng,
  FastDDS Shared Memory, quyền UID/GID và logs của các container Docker
  (airport_guide_backend, airport_guide_frontend, thirsty_ishizaka).
---

# Docker & Container Networking Troubleshooting Runbook

Skill này cung cấp các bước xử lý sự cố môi trường Docker và mạng giao tiếp giữa Backend, Frontend và Dev Container ROS.

## 1. Sơ đồ Kiến trúc Môi trường
* **Dev Container (`thirsty_ishizaka`):** Quản lý bởi VS Code trong workspace `ws`. Chạy mô phỏng Gazebo + Nav2.
* **Backend (`airport_guide_backend`):** FastAPI + ROS 2 Jazzy. Chạy với `network_mode: host`, `ipc: host`, UID `1000:1000`.
* **Frontend (`airport_guide_frontend`):** Nginx trên Alpine phục vụ React SPA và proxy API/WS trên cổng `5173`. Chạy với `network_mode: host`.

## 2. Kiểm tra Trạng thái Container và Cổng Mạng

```bash
# 1. Kiểm tra trạng thái các container
docker compose ps
docker ps --filter "name=thirsty_ishizaka"

# 2. Kiểm tra cổng mạng 5173 (Nginx) và 8000 (FastAPI)
curl -sI http://localhost:5173/ | head -n 5
curl -s http://localhost:5173/api/health | jq .
```

## 3. Khắc phục Sự cố Giao tiếp FastDDS (Shared Memory)

> [!WARNING]
> FastDDS sử dụng Shared Memory (`/dev/shm`) theo mặc định khi các container chạy trên cùng host.
> Nếu một container chạy dưới quyền `root` và container kia chạy dưới quyền user thường (`UID 1000`), các segment SHM sẽ bị từ chối truy cập (permission denied), khiến ROS 2 topic không nhận được dữ liệu dù cùng `ROS_DOMAIN_ID=0`.

### Cấu hình chuẩn trong `docker-compose.override.yml`:
```yaml
services:
  backend:
    user: "1000:1000"
    ipc: host
    environment:
      ROBOT_CONFIG_PATH: /app/config/robot_interface.yaml
      SECRET_KEY: ${SECRET_KEY:?SECRET_KEY is required}
      ROS_AUTOMATIC_DISCOVERY_RANGE: LOCALHOST
    volumes:
      - ./config:/app/config:ro
```

### Xử lý khi Dev Container khởi động lại:
Khi Dev Container `thirsty_ishizaka` khởi động lại, các publisher ROS 2 được tạo mới. Cần khởi động lại backend để đồng bộ kết nối DDS:
```bash
docker compose restart backend
```

## 4. Quản lý Vòng đời Container

### Xem log theo thời gian thực:
```bash
# Log backend (FastAPI + ROS)
docker compose logs --tail=50 -f backend

# Log frontend (Nginx access & error)
docker compose logs --tail=50 -f frontend
```

### Khởi động và Dừng dịch vụ an toàn:
```bash
# Khởi động dịch vụ ở chế độ detached
docker compose up -d

# Dừng dịch vụ (không làm ảnh hưởng đến Dev Container ws)
docker compose stop
```

### Rebuild Frontend khi có thay đổi mã nguồn:
Frontend sử dụng multi-stage Dockerfile (Node 22 build -> Nginx). Khi sửa mã nguồn `frontend/src/`, phải rebuild và khởi động lại container:
```bash
docker compose build frontend
docker compose up -d frontend
```

### Rebuild Backend khi cập nhật dependencies:
```bash
docker compose build backend
docker compose up -d backend
```
