---
trigger: always_on
description: Quy tắc phát triển và phạm vi truy cập tệp cho workspace airport-guide-ui
---

# Quy tắc Phát triển và Kỹ thuật Phần mềm (Development Workflow Rules)

Quy tắc này áp dụng cho toàn bộ workspace `airport-guide-ui` nhằm đảm bảo tính ổn định, an toàn và nhất quán của hệ thống.

## 1. Nguyên tắc Khảo sát và Tác động Tối thiểu
* **Khảo sát trước khi sửa:** Luôn đọc cấu trúc thư mục và mã nguồn liên quan trước khi chỉnh sửa. Không suy đoán logic hoặc API.
* **Tác động tối thiểu:** Ưu tiên giải pháp can thiệp ít nhất có thể để giải quyết vấn đề. Không làm hỏng các tính năng đã hoạt động ổn định.
* **Bảo tồn kiến trúc:** Không tự ý thay đổi kiến trúc hệ thống, công nghệ nền tảng (FastAPI, React, ROS 2 Jazzy, Docker Compose) hoặc nâng cấp phiên bản thư viện cốt lõi trừ khi có yêu cầu rõ ràng.

## 2. Giao tiếp ROS 2 và Robot
* **Không đổi tên giao diện:** Không tự ý đổi tên ROS Topic, Service, Action hoặc REST/WebSocket API đã được cấu hình.
* **Đồng bộ Interface:** Khi sửa đổi bất kỳ logic giao tiếp ROS nào, phải kiểm tra file cấu hình trung tâm (`config/robot_interface.yaml`).
* **Minh bạch dữ liệu:** Luôn phân biệt rạch ròi giữa dữ liệu thật (từ ROS/AMCL/Nav2) và dữ liệu mô phỏng (Mock). Dữ liệu thiếu hoặc mô phỏng phải có nhãn rõ ràng.

## 3. Hạ tầng Docker và Môi trường Chạy
* **Bảo vệ cấu hình Container:** Không tự ý sửa đổi `docker-compose.yml`, `docker-compose.override.yml` hoặc các file `Dockerfile` khi không có yêu cầu cụ thể.
* **Tách biệt môi trường:** Không cài đặt các gói hệ thống, `npm` hoặc `pip` trực tiếp lên host Ubuntu khi chúng thuộc phạm vi container.

## 4. Kiểm thử và Báo cáo Kết quả
* **Kiểm tra hồi quy bắt buộc:** Sau mỗi lần chỉnh sửa, phải kiểm tra cú pháp (syntax/compilation) và chạy các bài kiểm thử thích hợp (API health, pytest, build frontend, kiểm tra log container).
* **Báo cáo minh bạch:** Báo cáo đầy đủ danh sách file đã thay đổi, lệnh đã thực hiện và kết quả kiểm chứng thực tế.
* **Ngôn ngữ:** Giải thích các quyết định kỹ thuật bằng tiếng Việt, giữ nguyên các thuật ngữ kỹ thuật tiếng Anh (ví dụ: *frame_id, OccupancyGrid, transient_local, QoS, telemetry, payload*).

## 5. Phạm vi truy cập tệp (File Access Scope & Permissions)
* **Giới hạn phạm vi ghi file:** Mọi thao tác ghi file của tác vụ chỉ thực hiện trong repo `airport-guide-ui`. Tuyệt đối không tạo, sửa, xóa, di chuyển hoặc ghi đè file trong `ws`, kể cả qua Terminal, script, symlink hoặc Docker exec. Không chạy lệnh build (ví dụ `colcon build`) hay công cụ định dạng nếu chúng ghi dữ liệu vào `ws`.
* **Chính sách đối với Workspace ROS `ws`:**
  - Workspace ROS `ws` chỉ dùng để tham chiếu (Read-Only reference).
  - Được phép: Mở, đọc mã nguồn, đọc file cấu hình, tìm kiếm nội dung, xem `git status` / `git diff` và kiểm tra ROS bằng các lệnh chỉ đọc (read-only inspection qua container backend Jazzy `airport_guide_backend`).
  - Nếu phát hiện cần sửa `ws`: Phải dừng lại và báo cáo chính xác đường dẫn file, lý do cần sửa và nội dung thay đổi đề xuất để người dùng phê duyệt trước. Trong lúc chờ, tiếp tục triển khai các phần việc độc lập trong repo web.
  - Tuyệt đối không chỉnh sửa Dev Container, cấu hình của hệ điều hành Ubuntu host hoặc file của bất kỳ dự án nào khác.
* **Bảo vệ ranh giới an toàn:** Tuyệt đối không tự ý tìm cách mở rộng quyền truy cập, không bật chế độ Turbo / Always Proceed, và không tự ý chạy các lệnh ngoài sandbox nhằm vượt qua các giới hạn bảo mật được thiết lập.
