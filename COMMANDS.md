# CẨM NANG CÁC CÂU LỆNH CẦN DÙNG (COMMANDS CHEATSHEET)

> 📍 Tài liệu chi tiết và cập nhật đầy đủ nhất được lưu tại: [`docs/COMMANDS_CHEATSHEET.md`](docs/COMMANDS_CHEATSHEET.md)

---

## 🚀 TÓM TẮT LỆNH NHANH

### 🖥️ Trên máy Windows (Phát triển giao diện, không cần ROS)

```powershell
# 1. Chạy Backend (Terminal 1)
cd .\Documents\Antigravity\airport-guide-ui\backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 2. Chạy Frontend (Terminal 2)
cd .\Documents\Antigravity\airport-guide-ui\frontend
npm.cmd run dev

# 3. Kiểm tra cấu hình ROS đang áp dụng (CLI)
cd backend
python -m app.ros_config

# 4. Chạy toàn bộ Unit Tests
cd backend
python -m pytest tests -v
	
# 5. Build kiểm tra Frontend
cd frontend
npm run build
```
- Mở trình duyệt: `http://localhost:5173`
- Tài khoản Admin: `admin` / `admin123`

---

### 🐧 Trên máy Ubuntu (Kết nối ROS 2 Jazzy / Docker / Gazebo / Robot thật)

*(Tuyệt đối KHÔNG copy `node_modules` từ Windows sang Linux)*

```bash
# Cài đặt sạch trên Ubuntu
cd frontend && npm ci && npm run build
cd ../backend && pip install -r requirements.txt

# Chạy bằng Docker Compose (Khuyên dùng)
docker compose up -d

# Hoặc chạy Backend trực tiếp với ROS 2
export ROBOT_ADAPTER_MODE=ros
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```
