# ✈️ Airport Guide Robot UI & Backend (ROS 2 Jazzy)

Ứng dụng web điều khiển robot dẫn đường sân bay với kiến trúc Full-stack:
- **Frontend:** React 19 + TypeScript + Vite.
- **Backend:** Python FastAPI (REST API + WebSocket Telemetry Hub).
- **Robot Adapter:** `RosRobotAdapter` (sử dụng `rclpy` trong container Docker ROS 2 Jazzy) và `MockRobotAdapter` (mô phỏng).
- **Môi trường phát triển:** Windows 10/11 (Node LTS, Python 3).
- **Môi trường robot:** Ubuntu 22.04 LTS (Host), ROS 2 Jazzy (Docker).

---

## 🚀 Hướng dẫn khởi chạy theo từng môi trường

### 1. Trên máy Windows (Chế độ Mock / Phát triển giao diện)

#### Khởi chạy Backend (FastAPI):
Mở terminal PowerShell thứ nhất:
```powershell
cd backend
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
API docs sẽ sẵn sàng tại: `http://localhost:8000/docs`

#### Khởi chạy Frontend (Vite):
Mở terminal PowerShell thứ hai:
```powershell
cd frontend
npm install
npm run dev
```
Giao diện mở tại: `http://localhost:5173/` (Vite dev proxy sẽ tự động chuyển tiếp `/api` và `/ws` sang `http://127.0.0.1:8000`).

---

### 2. Trên máy Ubuntu 22 (Máy Robot — Chế độ Live ROS 2 Jazzy)

Không cần cài ROS 2 Jazzy trực tiếp lên host Ubuntu 22; toàn bộ Backend và Frontend được điều phối qua Docker Compose cùng mạng với container robot:

```bash
# 1. Clone hoặc giải nén mã nguồn vào máy robot
cd airport-guide-ui

# 2. Khởi chạy toàn bộ hệ thống bằng Docker Compose
docker compose up -d --build

# 3. Xem nhật ký hoạt động
docker compose logs -f backend
```

---

## 🌐 Hướng dẫn truy cập từ hai máy trong mạng LAN

Nhờ cấu hình **Dev Proxy / Nginx Reverse Proxy**, toàn bộ endpoint API và WebSocket đều dùng đường dẫn tương đối (`/api`, `/ws`), tuyệt đối **không hard-code localhost**:

1. **Trên laptop gắn trực tiếp trên robot:**
   - Mở trình duyệt: `http://localhost:5173/`
2. **Trên máy tính của nhân viên / hành khách bên ngoài mạng LAN:**
   - Xác định địa chỉ IP máy robot (ví dụ: `192.168.0.102` bằng lệnh `ip -4 addr`).
   - Mở trình duyệt: `http://192.168.0.102:5173/`
   - Cả hai máy đều nhận đồng bộ dữ liệu thời gian thực từ robot thông qua WebSocket.

---

## 🔐 Tài khoản xác thực mặc định (Backend JWT Authentication)

Backend tự động băm mật khẩu bằng PBKDF2-SHA256 và ký JWT Token theo vai trò:

| Tài khoản | Mật khẩu mặc định | Vai trò | Quyền hạn |
|---|---|---|---|
| `viewer` | `viewer123` | **Viewer** | Chọn điểm, xem bản đồ, quản lý chuyến của mình |
| `operator` | `operator123` | **Operator** | Quản lý mọi chuyến, điều khiển thủ công, CRUD địa điểm |
| `developer` | `developer123` | **Developer** | Xem cảm biến, nhật ký log lỗi, trạng thái Nav2 |

> *Lưu ý:* Khi `APP_ENV=production`, giao diện tự động khóa các nút chọn tài khoản demo, bắt buộc nhập đúng thông tin đăng nhập.

---

## 📊 Hiện trạng dữ liệu kết nối (Giai đoạn C)

| Thành phần | Trạng thái | Ghi chú |
|---|:---:|---|
| **Xác thực JWT & Phân quyền** | **ĐÃ HOÀN TẤT (Thật 100%)** | Mật khẩu băm an toàn, server quyết định quyền trên REST & WS, hết hạn phiên ngắt WS. |
| **WebSocket Telemetry** | **ĐÃ HOÀN TẤT (Thật 100%)** | Gửi tin 5Hz, tự động reconnect exponential backoff, lọc payload theo role. |
| **Phép biến đổi tọa độ ROS ↔ Canvas** | **ĐÃ HOÀN TẤT (Thật 100%)** | Chuyển đổi chuẩn xác từ frame `map` (mét, Y hướng lên) sang Canvas (px, Y hướng xuống). |
| **Dữ liệu Telemetry Robot (Pose, Pin)** | **Đang chạy qua Mock / Chờ output khảo sát** | `RosRobotAdapter` đã code sẵn subscriber `/amcl_pose`, `/battery_state`, `/map`. Khi chạy với ROS Jazzy sẽ tự kết nối. |
| **Điều khiển chuyển động thực tế** | **Vô hiệu hóa an toàn** | Chưa gửi lệnh `cmd_vel` hay goal thật ở Giai đoạn C để đảm bảo an toàn tuyệt đối. |
