# ✈️ Airport Guide Robot UI & Backend (ROS 2 Jazzy)

Ứng dụng web điều khiển robot dẫn đường sân bay với kiến trúc Full-stack:
- **Frontend:** React 19 + TypeScript + Vite, đóng gói production bằng Docker Nginx Alpine.
- **Backend:** Python FastAPI (REST API + WebSocket Telemetry Hub) kết hợp `rclpy` trong container Docker ROS 2 Jazzy.
- **Robot Adapter:** `RosRobotAdapter` (kết nối trực tiếp ROS 2 Jazzy qua DDS) và `MockRobotAdapter` (chế độ mô phỏng khi không có ROS).
- **Môi trường robot:** Ubuntu 22.04 LTS (Host), ROS 2 Jazzy + Gazebo/Nav2 chạy trong VS Code Dev Container (`ws`).
- **Môi trường web UI:** Nằm độc lập tại `~/airport-guide-ui`, chạy bằng Docker Compose với `network_mode: host`.

---

## 🚀 Hướng dẫn vận hành trên Ubuntu 22.04 (Docker Compose)

> [!IMPORTANT]
> **Không cần cài đặt `npm`, `node`, `pip` hay `python-venv` trực tiếp lên hệ điều hành Ubuntu host.** Toàn bộ phụ thuộc frontend và backend đã được đóng gói khép kín trong Docker containers.
> Workspace `ws` và Dev Container ROS của robot được giữ nguyên vẹn, hai hệ thống giao tiếp với nhau qua ROS 2 DDS trên cùng máy host nhờ chế độ mạng `network_mode: host`.

### 1. Khởi động hệ thống
Mở terminal tại thư mục dự án:
```bash
cd ~/airport-guide-ui

# Khởi chạy toàn bộ hệ thống chạy ngầm
docker compose up -d
```

### 2. Kiểm tra trạng thái hoạt động
```bash
# Xem trạng thái các container
docker compose ps

# Kiểm tra sức khỏe của Backend và cấu hình ROS
curl -s http://localhost:8000/api/health | jq .
```

### 3. Xem nhật ký hoạt động (Logs)
```bash
# Xem log Backend (FastAPI + ROS adapter)
docker compose logs -f backend

# Xem log Frontend (Nginx reverse proxy)
docker compose logs -f frontend

# Xem 100 dòng log gần nhất của cả hệ thống
docker compose logs --tail=100
```

### 4. Khởi động lại (Restart)
```bash
# Khởi động lại toàn bộ dịch vụ
docker compose restart

# Hoặc khởi động lại riêng backend khi đổi file config
docker compose restart backend
```

### 5. Rebuild sau khi cập nhật mã nguồn hoặc Dockerfile
```bash
# Rebuild và khởi động lại toàn bộ
docker compose up -d --build

# Hoặc rebuild riêng backend (ví dụ sau khi thêm dependency ROS)
docker compose up -d --build backend
```

### 6. Dừng hệ thống
```bash
# Dừng các container một cách an toàn (giữ nguyên dữ liệu)
docker compose down
```

---

## 🌐 Hướng dẫn truy cập qua Web & Mạng LAN

Cả hai dịch vụ đều dùng `network_mode: host`:
- **Frontend (Nginx Reverse Proxy):** Lắng nghe tại cổng `5173`.
  - Nginx tự động chuyển tiếp các yêu cầu `/api/` và `/ws` sang Backend nội bộ `http://127.0.0.1:8000`.
- **Backend (FastAPI):** Lắng nghe tại cổng `8000` (API Docs tại `http://localhost:8000/docs`).

| Thiết bị truy cập | Địa chỉ URL | Ghi chú |
|---|---|---|
| **Trực tiếp trên máy robot / Ubuntu** | `http://localhost:5173/` | Màn hình chính dẫn đường |
| **Máy tính / Tablet khác trong mạng LAN** | `http://<IP_MÁY_UBUNTU>:5173/` | Ví dụ: `http://192.168.0.102:5173/` |
| **Kiểm tra API Backend trực tiếp** | `http://<IP_MÁY_UBUNTU>:8000/api/health` | Kiểm tra trạng thái DDS và kết nối |

> *Mẹo xác định IP máy robot:* Chạy lệnh `ip -4 addr show` hoặc `hostname -I` trên Ubuntu.

---

## 🔐 Phân quyền & Tài khoản xác thực mặc định

Hệ thống phân cấp bảo mật 2 tầng dựa trên JSON Web Token (JWT):

| Vai trò (Role) | Tài khoản | Mật khẩu mặc định | Quyền hạn sử dụng |
|---|---|---|---|
| **Hành khách (Passenger)** | *Không cần đăng nhập* | *Không áp dụng* | Xem bản đồ, chọn điểm đến, bấm microphone tương tác, hủy chuyến của mình |
| **Quản trị viên (Admin)** | `admin` | `admin123` | Theo dõi chẩn đoán lỗi, điều khiển vận tốc thủ công, thêm/sửa danh sách điểm đến |

> *Ghi chú bảo mật:* Mật khẩu admin có thể thay đổi bằng biến môi trường `DEFAULT_ADMIN_PASSWORD` trong file `.env`. Khóa ký JWT được quản lý qua `SECRET_KEY`.

---

## 📊 Hiện trạng kết nối thực tế & Phân biệt các tầng trạng thái

> [!WARNING]
> **Phân biệt rõ việc Backend khởi động thành công và việc thực sự kết nối với robot:**
> - Khi container backend và frontend báo `Up` và `GET /api/health` trả về `healthy`, điều đó **CHỈ CHỨNG MINH** Web Gateway đã sẵn sàng hoạt động trên DDS bus.
> - **Chỉ khi trường `"robot_connected": true`**, hệ thống mới thực sự nhận được dữ liệu vị trí robot từ ROS.

### Bảng kết quả kiểm tra thực tế (Môi trường Dev Container `ws` + Gazebo/Nav2)

| Thành phần | Trạng thái thực tế | Đánh giá kỹ thuật |
|---|:---:|---|
| **Môi trường DDS Domain** | `ROS_DOMAIN_ID=0` | Đã đồng bộ giữa Dev Container và Docker Compose backend. |
| **Phát hiện ROS Nodes / Topics** | **ĐÃ PHÁT HIỆN** | Backend đã nhìn thấy các nodes và topics của Gazebo/Nav2 thông qua DDS. |
| **Bản đồ tĩnh (`/map`)** | Đang có trên DDS | Node `map_server` phát topic `/map` (`nav_msgs/msg/OccupancyGrid`). Cần ánh xạ topic name trong cấu hình backend. |
| **Vị trí robot (`/amcl_pose`)** | Đang có trên DDS | Node `amcl` phát topic `/amcl_pose` (`geometry_msgs/msg/PoseWithCovarianceStamped`). Cần chuyển đổi kiểu dữ liệu trong backend adapter. |
| **Nhận dữ liệu vị trí vào Web** | **CHƯA XÁC NHẬN** | Backend chưa xác nhận nhận được pose do lệch kiểu (`PoseStamped` vs `PoseWithCovarianceStamped`) và tên topic (`/airport/pose` vs `/amcl_pose`). Giao diện hiển thị đúng nhãn *"Chưa có dữ liệu vị trí robot"*. |
| **Điều hướng Nav2 (`/navigate_to_pose`)** | Action server đang chạy | Nav2 action server đang có sẵn `/navigate_to_pose`. Đã bổ sung `ros-jazzy-nav2-msgs` vào Dockerfile. |
| **Package tùy chỉnh `airport_robot_interfaces`** | **CHƯA CÓ** | Chưa có trên host/container/ws. Backend đang dùng cơ chế fallback an toàn (bỏ qua subscribe `RobotState` để không bị crash). |
| **Điều khiển chuyển động thực tế** | **VÔ HIỆU HÓA AN TOÀN** | Chưa gửi lệnh `cmd_vel` hay goal tự động khi chưa hoàn tất kiểm thử từng bước. |
