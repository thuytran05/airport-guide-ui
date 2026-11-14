# CẨM NANG CÁC CÂU LỆNH CẦN DÙNG (COMMANDS CHEATSHEET)

> 📍 Tài liệu chi tiết và cập nhật đầy đủ nhất được lưu tại: [`docs/COMMANDS_CHEATSHEET.md`](docs/COMMANDS_CHEATSHEET.md)

---

## 🚀 TÓM TẮT LỆNH NHANH

### 🐧 Trên máy Ubuntu 22.04 (Môi trường Robot / Docker Compose)

> Không cần cài `npm` hay `pip` trên host. Hệ thống chạy bằng Docker Compose với `network_mode: host`.

```bash
# 1. Di chuyển vào thư mục dự án
cd ~/airport-guide-ui

# 2. Khởi động toàn bộ dịch vụ (chạy nền)
docker compose up -d

# 3. Kiểm tra trạng thái container và kiểm tra kết nối API
docker compose ps
curl -s http://localhost:8000/api/health | jq .

# 4. Xem nhật ký hoạt động (Logs)
docker compose logs -f backend
# hoặc xem log frontend
docker compose logs -f frontend
# hoặc xem 100 dòng gần nhất khi gặp lỗi
docker compose logs --tail=100 backend

# 5. Khởi động lại dịch vụ (sau khi đổi file config/robot_interface.yaml)
docker compose restart backend

# 6. Rebuild container sau khi cập nhật mã nguồn hoặc Dockerfile
docker compose up -d --build

# 7. Dừng toàn bộ hệ thống an toàn
docker compose down

# 8. Kiểm tra DDS topics từ trong container backend
docker compose exec backend bash -c "source /opt/ros/jazzy/setup.bash && ros2 topic list"
```

- **Mở giao diện Web:** `http://localhost:5173`
- **Truy cập qua mạng LAN:** `http://<IP_MÁY_UBUNTU>:5173`
- **Tài khoản Admin:** `admin` / `admin123` (Hành khách không cần đăng nhập)

---

### 🖥️ Trên máy Windows (Phát triển giao diện, Chế độ Mock)

```powershell
# 1. Chạy Backend (Terminal 1)
cd .\backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 2. Chạy Frontend (Terminal 2)
cd .\frontend
npm run dev

# 3. Kiểm tra cấu hình ROS đang áp dụng (CLI)
cd .\backend
python -m app.ros_config

# 4. Chạy toàn bộ Unit Tests Backend
cd .\backend
python -m pytest tests -v

# 5. Build kiểm tra Frontend
cd .\frontend
npm run build
```
