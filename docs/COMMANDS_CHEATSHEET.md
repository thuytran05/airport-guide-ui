# CẨM NANG CÁC CÂU LỆNH CẦN DÙNG (CHEATSHEET)
*Dự án: Airport Guide Robot UI (Giao diện Web Robot Dẫn đường Sân bay)*
*Cập nhật lần cuối: 11/11/2026*

Tài liệu này tổng hợp toàn bộ các câu lệnh bạn cần chạy trên **Windows** (khi phát triển/kiểm thử giao diện) và **Ubuntu** (khi kết nối ROS 2 / Docker / Gazebo / Robot thật). Bạn chỉ cần mở tệp này để tra cứu mỗi khi cần.

---

## PHẦN 1: MÔI TRƯỜNG WINDOWS (PHÁT TRIỂN & KIỂM THỬ GIAO DIỆN)

> **Lưu ý:** Trên Windows không cần cài đặt ROS 2 hoặc Docker. Hệ thống tự động sử dụng chế độ `MockRobotAdapter` để giả lập robot.

### 1. Cài đặt ban đầu (Chỉ chạy 1 lần)
Mở PowerShell tại thư mục gốc của dự án `airport-guide-ui`:

```powershell
# Cài đặt thư viện Python cho Backend
cd backend
pip install -r requirements.txt

# Cài đặt thư viện Node.js cho Frontend
cd ../frontend
npm install
```

### 2. Khởi chạy hệ thống hàng ngày để sử dụng trên trình duyệt

**Bước 2.1: Chạy Backend (Terminal 1)**
```powershell
cd backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
*Dấu hiệu thành công:* Terminal báo `Uvicorn running on http://0.0.0.0:8000`.

**Bước 2.2: Chạy Frontend (Terminal 2 - mở tab mới)**
```powershell
cd frontend
npm run dev
```
*Dấu hiệu thành công:* Terminal báo `Local: http://localhost:5173/`.

**Bước 2.3: Mở trình duyệt web**
- Truy cập: `http://localhost:5173`
- **Hành khách:** Dùng ngay trên màn hình chính, không cần đăng nhập (chọn điểm đến, bấm "Bắt Đầu Dẫn Đường", bấm microphone để nói).
- **Quản trị viên (Admin):** Nhấn nút "Đăng nhập Admin" góc trên bên phải:
  - Tài khoản mặc định: `admin`
  - Mật khẩu mặc định: `admin123`

### 3. Các lệnh kiểm tra cấu hình & Unit Tests trên Windows

**Kiểm tra bảng cấu hình ROS đang áp dụng (CLI):**
```powershell
cd backend
python -m app.ros_config
```

**Chạy toàn bộ Unit Tests kiểm tra Backend:**
```powershell
cd backend
python -m pytest tests -v
```

**Kiểm tra biên dịch Frontend (TypeScript & Vite build):**
```powershell
cd frontend
npm run build
```

---

## PHẦN 2: MÔI TRƯỜNG UBUNTU 22 (ROBOT THẬT & MÔ PHỎNG ROS 2 JAZZY)

> **CẢNH BÁO QUAN TRỌNG KHI CHUYỂN DỰ ÁN TỪ WINDOWS SANG UBUNTU:**
> **TUYỆT ĐỐI KHÔNG** sao chép thư mục `node_modules` hoặc thư mục môi trường ảo Python (`.venv`) từ Windows sang Ubuntu. Hãy chỉ copy mã nguồn, sau đó chạy lệnh cài đặt lại dưới đây trên Ubuntu.

### 1. Chuẩn bị thư viện sạch trên Ubuntu

```bash
# Di chuyển vào thư mục dự án
cd airport-guide-ui

# 1. Cài đặt thư viện Frontend sạch theo lockfile:
cd frontend
npm ci
npm run build

# 2. Cài đặt thư viện Backend:
cd ../backend
pip install -r requirements.txt
```

### 2. Kiểm tra kết nối với ROS 2 Jazzy trên Ubuntu

**Kiểm tra cấu hình giao tiếp ROS:**
```bash
cd backend
python3 -m app.ros_config
```

**Khởi chạy Backend với Adapter ROS 2 thật (thay vì mock):**
```bash
cd backend
# Đặt biến môi trường sử dụng adapter ROS và chạy uvicorn
export ROBOT_ADAPTER_MODE=ros
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 3. Khởi chạy bằng Docker Compose (Khuyên dùng khi chạy trên máy Host có ROS Jazzy)

Nếu bạn muốn chạy cả Frontend (qua Nginx) và Backend (trong container ROS Jazzy kết nối host network):

```bash
# Khởi động toàn bộ container
docker compose up -d

# Xem log hoạt động của backend
docker compose logs -f backend

# Dừng hệ thống
docker compose down
```
Truy cập qua trình duyệt máy khác trong mạng LAN: `http://<IP_MÁY_UBUNTU>:80` hoặc cổng dev `http://<IP_MÁY_UBUNTU>:5173`.

---

## PHẦN 3: CÁC LỆNH ROS 2 THƯỜNG DÙNG ĐỂ KIỂM TRA TOPIC/SERVICE TRÊN UBUNTU

Chạy bên trong Docker hoặc terminal đã `source /opt/ros/jazzy/setup.bash`:

```bash
# 1. Xem danh sách topic đang chạy
ros2 topic list

# 2. Kiểm tra tần suất topic vị trí robot (yêu cầu khoảng 10Hz)
ros2 topic hz /airport/pose

# 3. Xem dữ liệu trạng thái robot
ros2 topic echo /airport/state

# 4. Kiểm tra service trigger giọng nói
ros2 service call /airport/voice/start std_srvs/srv/Trigger "{}"

# 5. Kiểm tra service chuyển chế độ thủ công
ros2 service call /airport/control/set_manual std_srvs/srv/SetBool "{data: true}"

# 6. Xem danh sách action đang cung cấp
ros2 action list
```

---

## PHẦN 4: THAY ĐỔI CẤU HÌNH (DUY NHẤT 1 FILE)

Mọi thay đổi về tên topic, service, action, profile `sim` (Gazebo) hoặc `real` (Robot thật):
- **Tệp cần mở sửa:** `config/robot_interface.yaml`
- **Cách áp dụng:** Sửa xong file -> Khởi động lại Backend (`uvicorn` hoặc `docker compose restart backend`).
