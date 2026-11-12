# Ràng buộc cho Agent — Airport Guide Robot UI

## Không được làm

1. **Không tự giả định** topic, action, service, frame, tọa độ hoặc API chuyến bay ROS 2.
2. **Không coi gửi lệnh thành công là robot đã hoàn thành.** Phải chờ trạng thái completed/failed.
3. **Không thay đổi** hệ ROS, container Docker hoặc cấu hình điều hướng hiện có.
4. **Không gọi tùy ý** topic/service ROS từ giọng nói — giọng nói dùng cùng chức năng nghiệp vụ với nút bấm.
5. **Không đưa thuật ngữ** ROS/Docker/topic vào nội dung dành cho hành khách (Viewer).
6. **Không tạo nút bấm không có tác dụng.** Nếu chức năng chưa tích hợp, vô hiệu hóa và giải thích rõ.
7. **Không rải dữ liệu giả** trực tiếp trong component — dùng MockRobotAdapter làm nguồn trung tâm.
8. **Không giả vờ đang thu âm** microphone thật ở giai đoạn A — ghi nhãn "Giọng nói mô phỏng".

## Phải làm

1. **Phân quyền ở backend** (giai đoạn C+). Giai đoạn A: demo chọn vai trò có nhãn rõ.
2. **Viewer chỉ điều khiển chuyến của mình.** Operator/Developer quản lý chuyến đang hoạt động.
3. **Dữ liệu mô phỏng phải có nhãn.** Thiếu dữ liệu thật → hiển thị "Chưa có dữ liệu".
4. **Kiểm tra tạm dừng/tiếp tục** thực tế trước khi tích hợp (giai đoạn B).
5. **Điều khiển thủ công ↔ tự động** phải có cơ chế phân xử, không chạy song song.
6. **Giọng nói cần xác nhận** trước khi tạo chuyến — không tự đoán rồi cho robot đi.
7. **Tách dữ liệu địa điểm** khỏi mã giao diện để thay bằng dữ liệu thật sau.
8. **Thiết kế hợp đồng dữ liệu** (interfaces/types) để nối backend mà không viết lại frontend.
9. **Bổ sung tình huống lỗi** trong demo: robot bận, mất kết nối, pin thấp, không tìm đường, chuyến thất bại.
