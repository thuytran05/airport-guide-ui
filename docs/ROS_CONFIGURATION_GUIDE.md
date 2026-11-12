# HƯỚNG DẪN CẤU HÌNH VÀ VẬN HÀNH AIRPORT GUIDE ROBOT

Tài liệu hướng dẫn quản trị giao tiếp ROS 2 bằng một file cấu hình duy nhất và kết nối hệ thống giao diện web với mô phỏng Gazebo hoặc Robot thật.

---

## 1. FILE CẤU HÌNH DUY NHẤT: `config/robot_interface.yaml`

Đường dẫn file: `config/robot_interface.yaml`.

Đây là nơi **DUY NHẤT** bạn cần chỉnh sửa bằng tay khi muốn đổi tên topic, service, action, QoS hoặc chuyển đổi giữa Gazebo (`sim`) và Robot thật (`real`).

### Cấu trúc các nhóm trong file:
- `schema_version`: Phiên bản cấu hình (mặc định: `"1.0"`).
- `active_profile`: Chọn profile hoạt động (`"sim"` cho Gazebo hoặc `"real"` cho robot vật lý).
- `connection`: Địa chỉ IP/Port kết nối HTTP/WebSocket và `ros_domain_id`.
- `frames`: Tên các frame tọa độ chuẩn: `map`, `odom`, `base_link`.
- `topics`: Danh sách các topic ROS (Bản đồ `/airport/map`, Vị trí `/airport/pose`, Trạng thái `/airport/state`, Điểm đến `/airport/destinations`, Giọng nói `/airport/voice/state`, Cảnh báo `/airport/alerts`, Lệnh vận tốc thủ công `/airport/cmd_vel_manual`, Đường đi `/airport/path`, Pin `/airport/battery`, v.v.).
- `services`: Các service gọi đến ROS (`/airport/voice/start`, `/airport/control/set_manual`, `/airport/destinations/upsert`).
- `actions`: Action Nav2 Jazzy (`/airport/navigate_to_pose`).
- `velocity_limits`: Giới hạn vận tốc an toàn khi điều khiển thủ công (`linear_max`, `angular_max`, `cmd_timeout_sec`).
- `destinations_storage_path`: Tệp lưu trữ cơ sở dữ liệu điểm đến bền vững (`config/destinations.yaml`).
- `profiles.sim` / `profiles.real`: Chỉ định các thông số ghi đè (overrides) riêng cho từng môi trường (ví dụ `use_sim_time: true` cho Gazebo và `false` cho Robot thật).

---

## 2. VÍ DỤ CHỈNH SỬA CẤU HÌNH

### a. Chuyển đổi giữa Mô phỏng Gazebo và Robot Thật
Mở `config/robot_interface.yaml`, sửa dòng:
```yaml
# Dùng Gazebo:
active_profile: "sim"

# Hoặc chuyển sang Robot thật:
active_profile: "real"
```
*Lưu ý:* Sau khi lưu file, bạn chỉ cần khởi động lại Backend (`uvicorn` hoặc Docker Backend) để áp dụng.

### b. Đổi tên Topic ROS (ví dụ đổi topic bản đồ)
```yaml
topics:
  map:
    name: "/my_robot/custom_map"   # Sửa tên ở đây
    type: "nav_msgs/msg/OccupancyGrid"
    direction: "subscribe"
    enabled: true
    required: true
```

### c. Đổi tên Service bắt đầu giọng nói
```yaml
services:
  voice_start:
    name: "/my_voice_node/trigger_listen"  # Sửa tên ở đây
    type: "std_srvs/srv/Trigger"
    direction: "service_client"
```

---

## 3. LỆNH KIỂM TRA CẤU HÌNH ĐANG ÁP DỤNG (CLI)

Để kiểm tra xem cấu hình nào đang có hiệu lực mà không cần mở code:
```bash
# Chạy trong thư mục backend:
cd backend
python -m app.ros_config
```
Lệnh sẽ in ra bảng chi tiết tất cả các topic, service, action, trạng thái BẬT/TẮT, frame và giới hạn vận tốc.

---

## 4. BẢNG ÁNH XẠ CHỨC NĂNG WEB ↔ GIAO TIẾP ROS ↔ NODE CUNG CẤP

| Chức năng trên Web | Chiều | Giao tiếp ROS | Kiểu dữ liệu (Message/Service/Action) | Node cung cấp đề xuất |
|---|---|---|---|---|
| Hiển thị bản đồ tĩnh | Nhận | `/airport/map` | `nav_msgs/msg/OccupancyGrid` | Node Bản đồ / Nav2 Map Server |
| Hiển thị vị trí Robot | Nhận | `/airport/pose` | `geometry_msgs/msg/PoseStamped` | Node Định vị (AMCL / TF / SLAM) |
| Trạng thái điều hướng & Chế độ | Nhận | `/airport/state` | `airport_robot_interfaces/msg/RobotState` | `/airport/interface_node` |
| Danh sách điểm đến đón/trả | Nhận | `/airport/destinations` | `airport_robot_interfaces/msg/DestinationList` | `/airport/interface_node` |
| Trạng thái tương tác giọng nói | Nhận | `/airport/voice/state` | `std_msgs/msg/String` | `/airport/voice_node` |
| Văn bản nhận dạng giọng nói | Nhận | `/airport/voice/transcript` | `std_msgs/msg/String` | `/airport/voice_node` |
| Câu phản hồi chữ của robot | Nhận | `/airport/voice/response` | `std_msgs/msg/String` | `/airport/voice_node` |
| Cảnh báo phần cứng/phần mềm | Nhận | `/airport/alerts` | `diagnostic_msgs/msg/DiagnosticArray` | Diagnostics aggregator / ROS nodes |
| Mức pin và trạng thái sạc | Nhận | `/airport/battery` | `sensor_msgs/msg/BatteryState` | Driver pin / Battery publisher |
| Lộ trình đường đi dự kiến | Nhận | `/airport/path` | `nav_msgs/msg/Path` | Nav2 Global Planner |
| Bấm microphone để nói | Gửi | `/airport/voice/start` | `std_srvs/srv/Trigger` | `/airport/voice_node` |
| Bật/Tắt chế độ thủ công (Admin) | Gửi | `/airport/control/set_manual` | `std_srvs/srv/SetBool` | `/airport/interface_node` |
| Điều khiển lái robot (Admin) | Gửi | `/airport/cmd_vel_manual` | `geometry_msgs/msg/TwistStamped` | Bộ phân xử vận tốc (Twist Mux) |
| Thêm/Sửa điểm đến (Admin) | Gửi | `/airport/destinations/upsert` | `airport_robot_interfaces/srv/UpsertDestination` | `/airport/interface_node` |
| Bắt đầu chuyến dẫn đường | Gửi | `/airport/navigate_to_pose` | `nav2_msgs/action/NavigateToPose` | Nav2 BT Navigator |
| Hủy chuyến dẫn đường | Gửi | Action Cancel | `action_msgs/srv/CancelGoal` | Nav2 BT Navigator |

---

## 5. DANH SÁCH MÃ NGUỒN ĐÃ ĐƯỢC CHỈNH SỬA

1. `config/robot_interface.yaml`: Tệp cấu hình gốc quản lý toàn bộ giao tiếp ROS.
2. `config/destinations.yaml`: Cơ sở dữ liệu điểm đến lưu bền vững, không bị ghi đè khi sửa cấu hình mạng.
3. `backend/app/ros_config.py`: Module đọc, validate YAML, gộp profile (`sim`/`real`) và cung cấp CLI `python -m app.ros_config`.
4. `backend/app/adapters/ros_adapter.py`: Adapter kết nối ROS 2 thật, nạp toàn bộ topic/service/action từ `ros_config.py`.
5. `backend/app/adapters/mock_adapter.py`: Adapter mô phỏng hoạt động độc lập trên Windows mà không cần ROS 2.
6. `backend/app/auth/models.py` & `backend/app/auth/dependencies.py`: Đơn giản hóa về đúng 2 vai trò: **Passenger** (không cần đăng nhập) và **Admin** (đăng nhập bảo mật).
7. `backend/app/api/robot_router.py`: API chuẩn cho các chức năng Navigate, Cancel, Voice Start, Set Manual, Cmd Vel, Upsert Destination.
8. `frontend/src/types/index.ts`: Khớp đúng 2 role và các interfaces ROS.
9. `frontend/src/contexts/RobotContext.tsx` & `AuthContext.tsx`: Quản lý WebSocket và REST APIs.
10. `frontend/src/pages/passenger/Home.tsx`: Màn hình Hành khách (chọn điểm đến, bắt đầu/hủy chuyến, voice trigger, xem bản đồ).
11. `frontend/src/pages/admin/Dashboard.tsx`: Màn hình Quản trị (điều khiển vận tốc d-pad với watchdog an toàn, thêm/sửa điểm đến, xem cảnh báo).
12. `frontend/src/pages/Login.tsx`: Form đăng nhập Quản trị viên.

---

## 6. HƯỚNG DẪN CHẠY TRÊN WINDOWS VÀ CHUYỂN SANG UBUNTU

### a. Chạy phát triển trên Windows (Không cần cài ROS):
```powershell
# 1. Chạy Backend (chế độ mock độc lập)
cd backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 2. Mở một terminal khác, chạy Frontend
cd frontend
npm run dev
```
Truy cập trình duyệt: `http://localhost:5173`.
- Hành khách vào thẳng không cần đăng nhập.
- Admin bấm "Đăng nhập Admin", tài khoản mặc định: `admin` / `admin123`.

### b. Chuyển sang máy Ubuntu 22 (Chạy nối với ROS 2 / Docker):
> **QUAN TRỌNG:** KHÔNG copy thư mục `node_modules` hoặc môi trường ảo Python từ Windows sang Ubuntu!

1. Sao chép toàn bộ mã nguồn sang Ubuntu (trừ `node_modules` và `.venv`).
2. Tại Ubuntu, cài đặt lại dependencies sạch bằng lockfile:
```bash
# Cài thư viện Frontend bằng package-lock.json chuẩn:
cd frontend
npm ci
npm run build

# Cài thư viện Backend:
cd ../backend
pip install -r requirements.txt
```
3. Chạy qua Docker Compose trong mạng ROS Jazzy:
```bash
docker compose up -d
```

---

## 7. CÁC TÀI NGUYÊN CÒN THIẾU ĐỂ MÔ PHỎNG VỚI GAZEBO HARMONIC

Web UI và Backend Gateway đã sẵn sàng 100%. Để chạy mô phỏng hoàn chỉnh trong Gazebo, bạn cần bổ sung:
1. **Gói interface ROS**: Tạo và build package `airport_robot_interfaces` trên môi trường ROS 2 Jazzy chứa:
   - `msg/RobotState.msg`
   - `msg/DestinationList.msg`
   - `msg/Destination.msg`
   - `srv/UpsertDestination.srv`
2. **Mô hình Robot & Bản đồ**: Tệp URDF/SDF của robot và file bản đồ OccupancyGrid (`map.yaml` và `map.pgm`) của sân bay để Nav2 Map Server nạp.
3. **Bộ chuyển đổi ros_gz_bridge**: Nếu dùng Gazebo Transport để truyền cảm biến, cần cấu hình bridge cho:
   - `/clock` (`rosgraph_msgs/msg/Clock`)
   - `/scan` (`sensor_msgs/msg/LaserScan`)
   - `/odom` (`nav_msgs/msg/Odometry`)
4. **Node điều phối (`/airport/interface_node`)**: Node trung gian quản lý trạng thái máy và chuyển tiếp action `NavigateToPose` tới Nav2.
