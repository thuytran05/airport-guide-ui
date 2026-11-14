# CẨM NANG CÁC CÂU LỆNH CẦN DÙNG (CHEATSHEET)
*Dự án: Airport Guide Robot UI (Giao diện Web Robot Dẫn đường Sân bay)*
*Môi trường mục tiêu: Ubuntu 22.04 LTS — ROS 2 Jazzy (Docker Compose & VS Code Dev Container)*

Tài liệu này tổng hợp toàn bộ các câu lệnh cần thiết để vận hành và kiểm tra hệ thống trên **Ubuntu 22.04 (máy robot / mô phỏng Gazebo)** và **Windows (phát triển giao diện)**.

---

## PHẦN 1: MÔI TRƯỜNG UBUNTU 22.04 (DOCKER COMPOSE & ROS 2 JAZZY)

> [!IMPORTANT]
> **Không cần cài `node`, `npm`, `pip` hay `python-venv` trên máy Ubuntu host.**
> Toàn bộ giao diện (Frontend Nginx) và backend (FastAPI + `rclpy`) đã được đóng gói hoàn chỉnh bằng Docker Compose với `network_mode: host`.
> VS Code Dev Container (`ws`) của robot hoạt động hoàn toàn độc lập và không bị ảnh hưởng.

### 1. Khởi động và quản lý vòng đời hệ thống

Mở terminal trên Ubuntu tại thư mục `~/airport-guide-ui`:

```bash
cd ~/airport-guide-ui

# 1.1 Khởi động toàn bộ dịch vụ chạy nền
docker compose up -d

# 1.2 Kiểm tra trạng thái hai container
docker compose ps

# 1.3 Khởi động lại khi thay đổi cấu hình (ví dụ sửa config/robot_interface.yaml)
docker compose restart backend

# 1.4 Rebuild lại container khi cập nhật Dockerfile hoặc mã nguồn mới
docker compose up -d --build

# 1.5 Dừng toàn bộ hệ thống một cách an toàn
docker compose down
```

---

### 2. Xem nhật ký hoạt động (Logs)

```bash
# Xem log Backend liên tục (FastAPI + ROS Adapter)
docker compose logs -f backend

# Xem log Frontend liên tục (Nginx)
docker compose logs -f frontend

# Xem 100 dòng log gần nhất của backend khi cần gỡ lỗi
docker compose logs --tail=100 backend

# Xem log của cả hệ thống kết hợp timestamp
docker compose logs -f -t
```

---

### 3. Kiểm tra chẩn đoán 3 tầng kết nối (Health Check & DDS)

> [!WARNING]
> **Quy tắc phân biệt:** Backend báo `healthy` **CHƯA ĐỒNG NGHĨA** robot đã kết nối. Cần kiểm tra kỹ trường `"robot_connected"`.

```bash
# Bước 3.1: Kiểm tra API Sẵn sàng của Backend (Tầng Web Gateway)
curl -s http://localhost:8000/api/health | jq .
# Kết quả mong đợi:
# - "status": "healthy"
# - "ros_domain_id": 0
# - "robot_connected": true (nếu AMCL/Gazebo đang phát pose) hoặc false (nếu chưa có pose)

# Bước 3.2: Kiểm tra các ROS nodes đang phát hiện qua DDS (từ trong Backend Docker)
docker compose exec backend bash -c "source /opt/ros/jazzy/setup.bash && ros2 node list"

# Bước 3.3: Kiểm tra danh sách topics hiện có trên mạng DDS
docker compose exec backend bash -c "source /opt/ros/jazzy/setup.bash && ros2 topic list"

# Bước 3.4: Kiểm tra action server của Nav2
docker compose exec backend bash -c "source /opt/ros/jazzy/setup.bash && ros2 action list"
```

---

### 4. Kiểm tra dữ liệu thực tế từ Gazebo / Nav2

Thực hiện từ bên trong container backend để xác nhận dữ liệu có thực sự đến được gateway:

```bash
# 4.1 Kiểm tra topic bản đồ tĩnh từ map_server (phải có dữ liệu)
docker compose exec backend bash -c "source /opt/ros/jazzy/setup.bash && ros2 topic echo /map --once"

# 4.2 Kiểm tra topic vị trí robot từ AMCL (kiểu PoseWithCovarianceStamped)
docker compose exec backend bash -c "source /opt/ros/jazzy/setup.bash && ros2 topic echo /amcl_pose --once"

# 4.3 Đo tần suất phát vị trí của AMCL (khi robot đứng yên hoặc di chuyển)
docker compose exec backend bash -c "source /opt/ros/jazzy/setup.bash && ros2 topic hz /amcl_pose"

# 4.4 Kiểm tra thông tin action điều hướng Nav2
docker compose exec backend bash -c "source /opt/ros/jazzy/setup.bash && ros2 action info /navigate_to_pose"
```

---

### 5. Truy cập giao diện người dùng

- **Trực tiếp trên máy robot / Ubuntu:** `http://localhost:5173`
- **Trên máy tính khác trong cùng mạng LAN:** `http://<IP_UBUNTU>:5173`
- **Tài khoản quản trị viên (Admin):**
  - Tài khoản: `admin`
  - Mật khẩu: `admin123`
- **Hành khách (Passenger):** Dùng trực tiếp trên trang chủ không cần đăng nhập.

---

## PHẦN 2: MÔI TRƯỜNG WINDOWS (PHÁT TRIỂN & KIỂM THỬ GIAO DIỆN MOCK)

> Dùng khi lập trình giao diện hoặc chạy unit tests trên Windows mà không cần ROS 2.

```powershell
# 1. Cài đặt thư viện (chỉ chạy 1 lần khi clone mới)
cd backend
python -m pip install -r requirements.txt
cd ..\frontend
npm install

# 2. Khởi chạy Backend (Terminal 1)
cd backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 3. Khởi chạy Frontend (Terminal 2)
cd frontend
npm run dev

# 4. Kiểm tra cấu hình ROS (CLI)
cd backend
python -m app.ros_config

# 5. Chạy toàn bộ Unit Tests
cd backend
python -m pytest tests -v
```

---

## PHẦN 3: TÙY BIẾN CẤU HÌNH GIAO TIẾP ROS

Toàn bộ thông số giao tiếp được quản lý tập trung tại:
`config/robot_interface.yaml`

- **Đổi Domain ID:** Mục `connection.ros_domain_id` (mặc định đã đồng bộ `0`).
- **Đổi Profile:** Sửa dòng `active_profile: "sim"` (mô phỏng Gazebo) hoặc `active_profile: "real"` (robot thật).
- **Sau khi sửa file config:** Chỉ cần chạy lệnh:
  ```bash
  docker compose restart backend
  ```
