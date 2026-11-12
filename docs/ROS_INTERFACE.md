# Khảo sát Giao diện ROS 2 & Cấu hình Tích hợp Web (Giai đoạn B)

> **Trạng thái:** Bản khảo sát đang chờ kết quả thực thi từ máy robot Ubuntu 22.  
> **Nguyên tắc an toàn:** Toàn bộ lệnh khảo sát là **chỉ đọc (read-only)**. Tuyệt đối không gửi goal, không publish vận tốc (`cmd_vel`), không gọi service thay đổi trạng thái, không sửa tham số, không restart container hay nâng cấp hệ thống.

---

## 1. Bảng tổng hợp Giao diện ROS 2 (Hiện trạng & Ứng viên)

*Ghi chú:*
- **[Đã xác minh]:** Đã có bằng chứng thực tế từ đầu ra lệnh ROS 2 trên máy robot.
- **[Ứng viên]:** Các topic/action/service tiêu chuẩn trong hệ sinh thái ROS 2 / Nav2, cần đối chiếu với kết quả khảo sát thực tế.

| Chức năng | Nguồn ROS đã xác minh | Kiểu dữ liệu | Frame / QoS | Quyền Đọc/Ghi | Thông tin còn thiếu / Cần xác minh |
|---|---|---|---|:---:|---|
| **Vị trí & Hướng robot** | *[Chờ khảo sát]* <br>*(Ứng viên: `/amcl_pose`, `/robot_pose`, `/odom`, hoặc TF `map -> base_link`)* | `geometry_msgs/msg/PoseWithCovarianceStamped` hoặc `geometry_msgs/msg/PoseStamped` | Frame: `map` hoặc `odom` <br>QoS: Transient Local / Volatile | Đọc (Sub) | Topic chính xác đang phát vị trí toàn cục của robot trên bản đồ; tần suất và frame ID. |
| **Bản đồ tĩnh sân bay** | *[Chờ khảo sát]* <br>*(Ứng viên: `/map` hoặc file yaml/pgm)* | `nav_msgs/msg/OccupancyGrid` | Frame: `map` <br>QoS: Transient Local, Reliable | Đọc (Sub) | Có topic `/map` phát từ map_server không, hay bản đồ chỉ lưu dạng file ảnh? Tọa độ gốc (`origin`) và độ phân giải (`resolution`). |
| **Cây biến đổi tọa độ (TF)** | *[Chờ khảo sát]* <br>*(Ứng viên: `/tf`, `/tf_static`)* | `tf2_msgs/msg/TFMessage` | Frames: `map`, `odom`, `base_link`, `base_footprint` | Đọc (Sub) | Tên chính xác của frame bản đồ (`map`), frame odometry (`odom`) và frame thân robot (`base_link` hoặc `base_footprint`). |
| **Gửi mục tiêu dẫn đường** | *[Chờ khảo sát]* <br>*(Ứng viên: `navigate_to_pose` [Action])* | `nav2_msgs/action/NavigateToPose` *(nếu Nav2)* hoặc action tự viết | Action Server | Ghi (Action Goal) | Dùng Nav2 chuẩn hay bộ điều hướng tự viết? Tên Action server và kiểu action interface. |
| **Đường đi dự kiến (Path)** | *[Chờ khảo sát]* <br>*(Ứng viên: `/plan`, `/local_plan`)* | `nav_msgs/msg/Path` | Frame: `map` | Đọc (Sub) | Topic phát đường đi toàn cục để hiển thị lên bản đồ web. |
| **Tạm dừng / Tiếp tục** | *[Chờ khảo sát]* <br>*(Ứng viên: Chưa rõ hoặc cần hủy goal/gửi lại)* | Chưa xác định | Service / Action | Ghi | Bộ điều hướng hiện tại có service tạm dừng (pause/resume) hay không? |
| **Hủy chuyến dẫn đường** | *[Chờ khảo sát]* <br>*(Ứng viên: Cancel Action Goal)* | `action_msgs/srv/CancelGoal` | Action Client | Ghi | Cơ chế cancel goal của Action server hiện tại. |
| **Điều khiển thủ công** | *[Chờ khảo sát]* <br>*(Ứng viên: `/cmd_vel` hoặc `/cmd_vel_teleop`)* | `geometry_msgs/msg/Twist` hoặc `geometry_msgs/msg/TwistStamped` | QoS: Volatile, Best Effort / Reliable | Ghi (Pub) | Tên topic nhận lệnh vận tốc thủ công; có node `twist_mux` phân quyền ưu tiên không? |
| **Mức pin & Nguồn điện** | *[Chờ khảo sát]* <br>*(Ứng viên: `/battery_state`, `/battery`, hoặc chưa có)* | `sensor_msgs/msg/BatteryState` | QoS: Volatile | Đọc (Sub) | Robot có topic pin phần cứng không, hay phải hiển thị "Chưa có dữ liệu"? |
| **Cảm biến Laser Scanner** | *[Chờ khảo sát]* <br>*(Ứng viên: `/scan`)* | `sensor_msgs/msg/LaserScan` | Frame: `laser` / `base_laser` | Đọc (Sub) | Tên topic laser và tần suất quét. |
| **Cảm biến IMU** | *[Chờ khảo sát]* <br>*(Ứng viên: `/imu`, `/imu/data`)* | `sensor_msgs/msg/Imu` | Frame: `imu_link` | Đọc (Sub) | Topic IMU nếu có. |
| **Nhật ký & Chẩn đoán** | *[Chờ khảo sát]* <br>*(Ứng viên: `/rosout`, `/diagnostics`)* | `rcl_interfaces/msg/Log`, `diagnostic_msgs/msg/DiagnosticArray` | QoS: Transient Local | Đọc (Sub) | Topic log hệ thống phục vụ tab Chẩn đoán của Developer. |

---

## 2. Đề xuất vị trí chạy Backend & Robot Adapter

Hệ thống hiện tại gồm: **Host Ubuntu 22** và **ROS 2 Jazzy chạy trong Docker**. Có 2 phương án khả thi:

### Phương án 1 (Khuyến nghị): Chạy Backend FastAPI trực tiếp trong cùng mạng với ROS
- **Cách thực hiện:** Tạo một container riêng cho Backend (chạy Python 3.12 / FastAPI) hoặc chạy trực tiếp trong container ROS nếu có môi trường Python phù hợp.
- **Kết nối DDS:** Container Backend sử dụng chế độ mạng `--net=host` (hoặc cùng Docker network) và cùng biến môi trường `ROS_DOMAIN_ID`, `RMW_IMPLEMENTATION`. Backend dùng thư viện `rclpy` kết nối trực tiếp với node ROS 2 như một ROS node chuẩn.
- **Ưu điểm:**
  - Không cần cài thêm bridge trung gian (như rosbridge websocket).
  - Hiệu năng cao nhất, tương thích 100% kiểu dữ liệu Jazzy.
  - Phân tách rõ ràng giữa frontend tĩnh (chạy ở trình duyệt) và backend quản trị.

### Phương án 2: Chạy Backend bên ngoài Host Ubuntu (nếu Host không cài ROS)
- **Cách thực hiện:** Nếu Host Ubuntu 22 không có sẵn ROS 2 Jazzy, Backend sẽ giao tiếp với container ROS thông qua một WebSocket Bridge (như `rosbridge_server`) hoặc Zenoh bridge chạy trong Docker.
- **Ưu điểm:** Nhẹ hơn cho host nếu không muốn mount thư viện ROS ra ngoài.
- **Nhược điểm:** Phải cài thêm package bridge vào container ROS.

> **Quyết định cụ thể:** Sẽ được chốt sau khi khảo sát xong cấu trúc mount và network mode của container hiện tại ở Phần 3.

---

## 3. Nhóm lệnh khảo sát (Chỉ đọc — Không can thiệp)

Bạn hãy sao chép và chạy lần lượt các nhóm lệnh dưới đây trên máy **Ubuntu 22 của robot**, sau đó dán kết quả trả về vào phản hồi để chúng ta cập nhật bảng trên.

### 📍 BƯỚC 1: Chạy trên máy Host Ubuntu 22 (Xác định Container & Network)

Mở terminal trên **Ubuntu 22 (Host)**:

```bash
# 1.1 Kiểm tra danh sách container Docker đang chạy
docker ps --format "table {{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"

# 1.2 Xem địa chỉ IP của máy Host trong mạng LAN
ip -4 addr show | grep -E "inet " | grep -v "127.0.0.1"

# 1.3 Kiểm tra chi tiết cấu hình network và thư mục mount của container ROS
# (Thay <CONTAINER_NAME> bằng tên container thực tế lấy từ lệnh 1.1)
docker inspect <CONTAINER_NAME> --format 'NetworkMode: {{.HostConfig.NetworkMode}}'
docker inspect <CONTAINER_NAME> --format 'Mounts: {{json .Mounts}}'
```

---

### 📍 BƯỚC 2: Chạy BÊN TRONG Container Docker ROS 2 Jazzy

Sau khi biết tên container từ Bước 1, truy cập vào bên trong container bằng lệnh:
```bash
docker exec -it <CONTAINER_NAME> bash
```

Sau khi đã ở trong container (nhớ source môi trường nếu cần, ví dụ: `source /opt/ros/jazzy/setup.bash` hoặc workspace tương ứng):

```bash
# 2.1 Kiểm tra biến môi trường ROS (chỉ in các biến liên quan, không in toàn bộ)
echo "ROS_DISTRO: $ROS_DISTRO"
echo "ROS_DOMAIN_ID: $ROS_DOMAIN_ID"
echo "RMW_IMPLEMENTATION: $RMW_IMPLEMENTATION"
echo "ROS_LOCALHOST_ONLY: $ROS_LOCALHOST_ONLY"

# 2.2 Kiểm tra use_sim_time (xem robot đang chạy thật hay mô phỏng Gazebo)
ros2 param get /controller_server use_sim_time 2>/dev/null || ros2 param get /amcl use_sim_time 2>/dev/null || echo "Không đọc được trực tiếp use_sim_time"

# 2.3 Liệt kê tất cả các Node đang chạy
ros2 node list

# 2.4 Liệt kê tất cả các Topic kèm kiểu message
ros2 topic list -t

# 2.5 Liệt kê tất cả các Action Server kèm kiểu action
ros2 action list -t

# 2.6 Liệt kê tất cả các Service kèm kiểu service
ros2 service list -t

# 2.7 Kiểm tra các Frame tọa độ TF (chạy 3 giây rồi ngắt, không treo máy)
ros2 run tf2_ros tf2_echo map base_link --timeout 3 2>/dev/null || ros2 run tf2_ros tf2_echo map base_footprint --timeout 3 2>/dev/null || echo "Chưa có TF map -> base"

# 2.8 Lấy mẫu 1 tin nhắn vị trí (nếu có topic amcl_pose hoặc robot_pose hoặc odom)
ros2 topic echo /amcl_pose --once 2>/dev/null || ros2 topic echo /robot_pose --once 2>/dev/null || echo "Không có topic /amcl_pose hoặc /robot_pose"

# 2.9 Lấy mẫu 1 tin nhắn pin (nếu có topic battery hoặc battery_state)
ros2 topic echo /battery_state --once 2>/dev/null || ros2 topic echo /battery --once 2>/dev/null || echo "Không có topic pin tiêu chuẩn"
```

---

## 4. Danh sách thông tin cần người dùng gửi lại

Sau khi chạy xong các lệnh trên, bạn vui lòng gửi lại kết quả của:
1. Đầu ra lệnh `docker ps` và `docker inspect` (NetworkMode & Mounts).
2. Đầu ra các lệnh:
   - `ros2 node list`
   - `ros2 topic list -t`
   - `ros2 action list -t`
   - `ros2 service list -t`
   - Giá trị các biến `ROS_DOMAIN_ID`, `RMW_IMPLEMENTATION`.
3. Kết quả echo thử các topic `/amcl_pose`, `/robot_pose`, `/cmd_vel`, `/battery_state` (nếu có).
