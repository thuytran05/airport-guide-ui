---
name: ros2-nav2-integration
description: >-
  Sử dụng skill này khi cần kiểm tra, debug hoặc tích hợp ROS 2 Jazzy, Nav2, AMCL,
  Gazebo simulation (Linorobot2), FastDDS discovery, OccupancyGrid map, TF và Odometry
  giữa ROS 2 container và Web Gateway.
---

# ROS 2 & Nav2 Integration Runbook

Skill này hướng dẫn quy trình chuẩn để kiểm tra và khắc phục sự cố giao tiếp ROS 2 trong hệ thống Airport Guide Robot.

## 1. Môi trường Thực thi
* **ROS 2 Distro:** Jazzy Jalisco.
* **Dev Container:** `thirsty_ishizaka` (chạy Gazebo, Nav2, robot_state_publisher, AMCL với UID 1000).
* **Backend Gateway:** `airport_guide_backend` (chạy FastAPI + `rclpy`, UID 1000, `ipc: host`, `network_mode: host`).
* **ROS Domain ID:** `0` (đồng bộ cả 2 container).
* **Discovery Scope:** `ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST`.

> [!IMPORTANT]
> Host Ubuntu có thể đang cài đặt phiên bản ROS khác (ví dụ: ROS 2 Humble). Mọi lệnh kiểm tra ROS 2 Jazzy **phải được thực thi bên trong container** (`thirsty_ishizaka` hoặc `airport_guide_backend`).

## 2. Quy trình Kiểm tra Trạng thái ROS 2

### Bước 1: Kiểm tra Nodes và Topics từ Dev Container
```bash
docker exec thirsty_ishizaka bash -c "source /opt/ros/jazzy/setup.bash && ros2 node list"
docker exec thirsty_ishizaka bash -c "source /opt/ros/jazzy/setup.bash && ros2 topic list"
```

### Bước 2: Kiểm tra Pose thực tế từ AMCL
```bash
# Kiểm tra tần số và dữ liệu pose
docker exec thirsty_ishizaka bash -c "source /opt/ros/jazzy/setup.bash && ros2 topic echo /amcl_pose --once"
```
* **Topic:** `/amcl_pose`
* **Message Class:** `geometry_msgs/msg/PoseWithCovarianceStamped`
* **QoS yêu cầu:** `reliability: reliable`, `durability: transient_local`
* **Cấu trúc dữ liệu:** `msg.pose.pose.position.{x, y}`, `msg.pose.pose.orientation.{x, y, z, w}`

### Bước 3: Kiểm tra Bản đồ OccupancyGrid từ Map Server
```bash
docker exec thirsty_ishizaka bash -c "source /opt/ros/jazzy/setup.bash && ros2 topic info /map"
docker exec thirsty_ishizaka bash -c "source /opt/ros/jazzy/setup.bash && ros2 topic echo /map --once | head -n 30"
```
* **Topic:** `/map`
* **Message Class:** `nav_msgs/msg/OccupancyGrid`
* **QoS yêu cầu:** `reliability: reliable`, `durability: transient_local`

### Bước 4: Kiểm tra Action Server Nav2
```bash
docker exec thirsty_ishizaka bash -c "source /opt/ros/jazzy/setup.bash && ros2 action list"
docker exec thirsty_ishizaka bash -c "source /opt/ros/jazzy/setup.bash && ros2 action info /navigate_to_pose"
```
* **Action:** `/navigate_to_pose`
* **Action Type:** `nav2_msgs/action/NavigateToPose`

### Bước 5: Kiểm tra Khả năng Thấu suốt DDS từ Backend Gateway
```bash
docker exec airport_guide_backend bash -c "source /opt/ros/jazzy/setup.bash && ros2 topic echo /amcl_pose --once"
```
Nếu lệnh này bị treo (hang) trong backend nhưng chạy được ở Dev Container:
* Kiểm tra `ipc: host` và quyền truy cập Shared Memory `/dev/shm` (xem skill `docker-ros-troubleshooting`).

## 3. Ràng buộc Tích hợp
1. **Không tạo ROS Node trung gian:** Ưu tiên subscribe trực tiếp từ `RosRobotAdapter` trong backend.
2. **Không tự đổi tên topic:** Mọi thay đổi topic phải qua file `config/robot_interface.yaml`.
3. **Quản lý Stale Data:** Sử dụng topic `/clock` để phát hiện mô phỏng bị treo mà không ngắt nhầm trạng thái kết nối khi robot đứng yên.
