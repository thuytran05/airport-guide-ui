# Hướng dẫn phát triển đa nền tảng (Windows & Ubuntu 22)

Tài liệu này cung cấp quy trình chuẩn để đồng bộ mã nguồn giữa máy phát triển giao diện (Windows) và máy chạy thực tế trên robot (Ubuntu 22.04 LTS).

---

## 1. Phân định vai trò môi trường

- **Máy phát triển giao diện (Windows 10/11):**
  - Dành cho thiết kế UI React, kiểm thử giao diện mô phỏng (`MockRobotAdapter`), viết Unit Tests.
  - Chạy trực tiếp Node LTS (`v22`) và Python 3 (`uvicorn`). Không yêu cầu cài ROS 2.
- **Máy vận hành robot (Ubuntu 22.04 LTS):**
  - Chạy hệ điều hành Robot ROS 2 Jazzy + Gazebo/Nav2 trong VS Code Dev Container (`ws`).
  - Web UI và Gateway Backend chạy độc lập tại `~/airport-guide-ui` thông qua **Docker Compose** (`network_mode: host`).
  - Không cần cài Node.js hay Python trực tiếp lên Ubuntu host vì Docker đã đóng gói toàn bộ.

---

## 2. Quy tắc quan trọng khi chuyển mã nguồn giữa Windows và Ubuntu

1. **Tuyệt đối KHÔNG sao chép thư mục `node_modules/` hoặc `.venv/` từ Windows sang Ubuntu.**
   - Một số gói npm (ví dụ `lightningcss`, `rolldown`, esbuild) chứa các file nhị phân riêng biệt (`win32-x64-msvc` trên Windows vs `linux-x64` trên Linux).
   - Dockerfile của frontend và backend đã tự động build các thư viện sạch cho môi trường Linux.
2. **Tuân thủ phân biệt chữ hoa / chữ thường (Case-sensitivity):**
   - Windows không phân biệt hoa thường trong đường dẫn, nhưng Linux phân biệt nghiêm ngặt (`Home.tsx` khác `home.tsx`).
3. **Tránh đường dẫn tuyệt đối:**
   - Không sử dụng các đường dẫn cố định như `C:\...` hay dấu gạch chéo ngược `\` trong mã nguồn.
   - Luôn sử dụng đường dẫn tương đối hoặc biến môi trường `ROBOT_CONFIG_PATH`.

---

## 3. Hướng dẫn chạy trên Windows (Phát triển giao diện)

Mở **PowerShell**:

```powershell
# Chạy Backend (Terminal 1)
cd backend
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Chạy Frontend (Terminal 2)
cd frontend
npm install
npm run dev
```

Mở trình duyệt: `http://localhost:5173`

---

## 4. Hướng dẫn đồng bộ mã nguồn sang Ubuntu 22 & Khởi chạy (Docker Compose)

### Bước 4.1: Đồng bộ mã nguồn (qua Git hoặc nén tar)

**Cách 1: Qua Git (Khuyến nghị):**
```bash
# Trên máy Ubuntu 22:
cd ~/airport-guide-ui
git pull
```

**Cách 2: Qua file nén tar (loại trừ node_modules và venv):**
```powershell
# Trên Windows PowerShell:
tar --exclude="node_modules" --exclude=".venv" --exclude="dist" -czvf airport-guide-ui.tar.gz airport-guide-ui
```
Sau đó copy file tar sang Ubuntu và giải nén vào `~/airport-guide-ui`.

### Bước 4.2: Khởi chạy bằng Docker Compose trên Ubuntu

```bash
cd ~/airport-guide-ui

# Khởi chạy toàn bộ hệ thống (tự động build Nginx Alpine và ROS Jazzy container)
docker compose up -d --build

# Kiểm tra log khởi động của backend
docker compose logs -f backend
```

---

## 5. Đồng bộ cấu hình mạng & ROS Domain ID

- **Chế độ mạng:** `network_mode: host` cho phép container backend nhìn thấy các node và topics của Dev Container `ws` trực tiếp qua mạng DDS cục bộ (loopback interface).
- **ROS_DOMAIN_ID:** Cả hai môi trường phải cùng chung Domain ID.
  - Dev Container robot: `ROS_DOMAIN_ID=0`.
  - Docker Compose backend: `ROS_DOMAIN_ID=0` (được cấu hình trong `docker-compose.yml` và `config/robot_interface.yaml`).
- **Truy cập qua mạng LAN:**
  - Từ máy robot: `http://localhost:5173`
  - Từ máy tính khác trong mạng nội bộ: `http://<IP_MÁY_UBUNTU>:5173` (Nginx tự động reverse proxy tới backend ở cổng 8000).
