# Airport Guide Robot UI — Project Documentation

## 1. Bối cảnh dự án

- **Mục tiêu:** Ứng dụng web điều khiển robot dẫn đường sân bay. Hành khách chọn điểm đến trên giao diện, robot di chuyển phía trước dẫn đường cho hành khách.
- **Robot thực tế:** Đã có khả năng tự di chuyển đến điểm đích thông qua ROS 2.
- **Môi trường:**
  - Máy phát triển giao diện: Windows (Node.js LTS, PowerShell).
  - Máy chạy robot (Host): Ubuntu 22.04 LTS, ROS 2 Jazzy chạy trong Docker container.
- **Nguyên tắc giai đoạn A:**
  - Hoàn toàn dùng dữ liệu mô phỏng (`MockRobotAdapter`) trên frontend (React + TypeScript + Vite).
  - Không cần cài ROS 2 trên Windows; không thay đổi hệ thống ROS 2/Docker trên máy robot.
  - Phân quyền demo ở frontend để xem trước luồng; phân quyền thật và kết nối ROS sẽ làm ở giai đoạn sau.
  - Một robot, phục vụ một chuyến dẫn đường tại một thời điểm.

---

## 2. Bảng phân quyền chi tiết (3 Vai trò kế thừa)

| Chức năng | Hành khách (Viewer) | Vận hành viên (Operator) | Nhà phát triển (Developer) |
|---|:---:|:---:|:---:|
| Chọn điểm đến từ danh sách & xem vị trí | ✅ | ✅ | ✅ |
| Bắt đầu chuyến dẫn đường của mình | ✅ | ✅ | ✅ |
| Tạm dừng / Tiếp tục / Hủy chuyến của mình | ✅ | ✅ | ✅ |
| Xem bản đồ 2D (robot, đích, đường đi, pan/zoom) | ✅ | ✅ | ✅ |
| Xem trạng thái cơ bản & khoảng cách còn lại | ✅ | ✅ | ✅ |
| Tương tác giọng nói mô phỏng | ✅ | ✅ | ✅ |
| Tra cứu thông tin chuyến bay minh họa | ✅ | ✅ | ✅ |
| Xem mức pin và trạng thái kết nối đơn giản | ✅ | ✅ | ✅ |
| Quản lý mọi chuyến đang hoạt động (kể cả của khách) | ❌ | ✅ | ✅ |
| Xem bản đồ vận hành chi tiết (tất cả địa điểm) | ❌ | ✅ | ✅ |
| Điều khiển robot thủ công (pad ảo + W/A/S/D) | ❌ | ✅ | ✅ |
| Cơ chế phân xử thủ công ↔ tự động | ❌ | ✅ | ✅ |
| Quản lý danh sách địa điểm sân bay (CRUD) | ❌ | ✅ | ✅ |
| Theo dõi cảnh báo hệ thống chi tiết | ❌ | ✅ | ✅ |
| Bảng cảm biến thời gian thực (Laser, IMU, Odom...) | ❌ | ❌ | ✅ |
| Trạng thái chi tiết Navigation Stack (Nav2 plugins) | ❌ | ❌ | ✅ |
| Danh sách Topic ROS 2 được phép | ❌ | ❌ | ✅ |
| Nhật ký hệ thống & lọc log lỗi theo cấp độ | ❌ | ❌ | ✅ |

---

## 3. Lộ trình triển khai các giai đoạn

- **Giai đoạn A (Hiện tại):** Giao diện tương tác hoàn chỉnh bằng dữ liệu mô phỏng trên React + TypeScript + Vite. Đầy đủ 3 vai trò, bản đồ có pan/zoom, quản lý chuyến, điều khiển thủ công mô phỏng, bảng cảm biến/nhật ký, mô phỏng giọng nói và tra cứu chuyến bay.
- **Giai đoạn B:** Khảo sát hệ thống ROS 2 Jazzy và Docker trên máy Ubuntu 22; tài liệu hóa topic, action, service, frame tọa độ và cơ chế pause/resume thực tế.
- **Giai đoạn C:** Xây dựng Backend Python FastAPI, xác thực JWT, WebSocket đồng bộ thời gian thực và đọc dữ liệu ROS thật qua `RosRobotAdapter`.
- **Giai đoạn D:** Tích hợp điều khiển chuyển động và quản lý chuyến thực tế trên robot.
- **Giai đoạn E:** Tích hợp STT/TTS tiếng Việt và kết nối API chuyến bay thực tế.
- **Giai đoạn F:** Kiểm thử liên máy trong mạng LAN và tài liệu hóa triển khai.
