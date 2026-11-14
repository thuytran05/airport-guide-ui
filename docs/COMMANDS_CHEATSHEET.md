# CẨM NANG CÁC CÂU LỆNH TRA CỨU TẬP TRUNG (COMMANDS CHEATSHEET)
*Dự án: Airport Guide Robot UI & Web Gateway*  
*Môi trường chính: Ubuntu 22.04 LTS — ROS 2 Jazzy (Docker Compose & VS Code Dev Container)*

Tài liệu này là cẩm nang tra cứu duy nhất tổng hợp toàn bộ các câu lệnh thực tế để cài đặt, vận hành, kiểm tra và xử lý sự cố hệ thống.

---

## 📌 PHẦN 1: NGUYÊN TẮC VẬN HÀNH & MÔI TRƯỜNG THỰC THI

### 1.1. Các môi trường thực thi lệnh (Ghi rõ trước mỗi câu lệnh)
| Ký hiệu | Môi trường thực thi | Cách mở / Chạy |
|---|---|---|
| **[Host]** | Terminal Ubuntu 22.04 của máy host | Mở terminal bình thường tại thư mục `~/airport-guide-ui`. |
| **[Backend-Exec]** | Bên trong container Web Gateway | Chạy từ terminal Host qua lệnh `docker compose exec backend bash -c "..."`. |
| **[Dev-Container]** | Bên trong Dev Container ROS 2 (`thirsty_ishizaka`) | Mở terminal trong VS Code gắn với workspace `ws` hoặc chạy qua `docker exec -it thirsty_ishizaka bash`. |
| **[Windows]** | PowerShell trên máy Windows | Dành riêng cho chế độ Mock (phát triển giao diện không cần ROS). |

> [!IMPORTANT]
> **Không chạy lệnh ROS Humble của Ubuntu host để kiểm tra hệ thống Jazzy!**  
> Máy host Ubuntu 22.04 có thể đang cài đặt ROS 2 Humble. Toàn bộ backend web và mô phỏng Gazebo chạy trên nền **ROS 2 Jazzy** bên trong Docker. Mọi lệnh ROS bắt buộc phải thực thi tại **[Backend-Exec]** hoặc **[Dev-Container]**.

---

### 1.2. Phân biệt `restart`, `rebuild` và `recreate`
Ba khái niệm này thường bị nhầm lẫn nhưng có hành vi và tác động rất khác nhau:

| Thao tác | Câu lệnh mẫu | Cơ chế thực tế | Khi nào nên dùng? | Ảnh hưởng dữ liệu |
|---|---|---|---|---|
| **Restart** | `docker compose restart backend` | Khởi động lại tiến trình Python/Nginx trong container đang chạy. Không biên dịch lại mã nguồn, không đổi file cấu hình Compose. | Sau khi chỉnh sửa file cấu hình [config/robot_interface.yaml](file:///home/thuytran/airport-guide-ui/config/robot_interface.yaml). | Bộ nhớ RAM bị giải phóng; dữ liệu trên đĩa (`data/destinations.yaml`) giữ nguyên vẹn. |
| **Rebuild** | `docker compose build backend`<br>`docker compose up -d backend` | Đóng gói lại Docker image từ Dockerfile và mã nguồn mới nhất trên máy host. | Sau khi chỉnh sửa mã nguồn Python (`backend/app/...`), TypeScript/React (`frontend/src/...`), hoặc đổi `package.json`/`requirements.txt`. | Tạo image mới; container sau đó sẽ được thay thế sạch sẽ bằng mã mới. |
| **Recreate** | `docker compose up -d` | Docker so sánh cấu hình hiện tại và file `docker-compose.yml`/`docker-compose.override.yml`. Nếu có thay đổi (ports, volumes, env, network), container cũ bị xóa và container mới được tạo. | Sau khi thay đổi biến môi trường, sửa mount ổ đĩa, hoặc đổi quyền UID/GID trong file override. | Các volume và thư mục mount (`./data`, `./config`) **không bị mất dữ liệu**. |

---

## 🚀 PHẦN 2: BẢNG TRA CỨU LỆNH THEO TÌNH HUỐNG THỰC TẾ

### Tình huống 1: Chạy lần đầu sau khi clone repo
```bash
# [Host] 1. Di chuyển vào thư mục dự án
cd ~/airport-guide-ui

# [Host] 2. Tạo file biến môi trường .env (nếu chưa có)
echo "SECRET_KEY=secret_key_demo_san_bay_2026_xyz123" > .env

# [Host] 3. Đảm bảo thư mục dữ liệu đã sẵn sàng và đúng quyền
mkdir -p data
[ -f data/destinations.yaml ] || cp config/destinations.yaml data/destinations.yaml

# [Host] 4. Build và khởi chạy toàn bộ dịch vụ chạy ngầm
docker compose up -d --build

# [Host] 5. Kiểm tra hai container đã chạy Up
docker compose ps
```

---

### Tình huống 2: Bật lại sau khi mở máy (Machine Reboot)
Khi máy tính khởi động lại, chỉ cần mở terminal và chạy:
```bash
# [Host] 1. Di chuyển vào thư mục dự án
cd ~/airport-guide-ui

# [Host] 2. Bật lại dịch vụ (dùng lại image đã build sẵn, cực nhanh ~1-2s)
docker compose up -d

# [Host] 3. Kiểm tra sức khỏe API
curl -s http://localhost:8000/api/health | jq .
```

---

### Tình huống 3: Xem trạng thái và chẩn đoán kết nối 3 tầng
```bash
# [Host] 3.1 Xem trạng thái container
docker compose ps

# [Host] 3.2 Kiểm tra API Gateway (Tầng 1: Web Gateway Health)
curl -s http://localhost:8000/api/health | jq .
```
> **Phân tích kết quả `curl /api/health`:**
> - `"status": "healthy"` ➔ Web Gateway Backend đang chạy tốt.
> - `"ros_domain_id": 0` ➔ Đang dùng Domain ID 0.
> - `"robot_connected": true` ➔ Backend đã bắt được topic vị trí robot (`/amcl_pose`). Nếu là `false`, xem mục Xử lý sự cố.
> - `"map_available": true` ➔ Backend đã nhận được bản đồ OccupancyGrid (`/map`).

```bash
# [Host] 3.3 Kiểm tra danh sách điểm đến đang nạp trong RAM backend
curl -s http://localhost:8000/api/robot/destinations | jq .

# [Host] 3.4 Kiểm tra endpoint trả ảnh bản đồ
curl -s -I http://localhost:8000/api/robot/map/image
```

---

### Tình huống 4: Xem nhật ký hoạt động (Logs)
```bash
# [Host] Xem log Backend liên tục theo thời gian thực
docker compose logs -f backend

# [Host] Xem log Frontend (Nginx reverse proxy)
docker compose logs -f frontend

# [Host] Xem 100 dòng log gần nhất của backend khi cần tìm lỗi
docker compose logs --tail=100 backend

# [Host] Xem log của toàn bộ hệ thống kèm timestamp chuẩn ISO
docker compose logs -f -t
```

---

### Tình huống 5: Kiểm tra và chẩn đoán ROS 2 Jazzy qua DDS

Toàn bộ các lệnh dưới đây gọi trực tiếp qua container backend để kiểm tra đúng môi trường Jazzy:

```bash
# [Backend-Exec] 5.1 Liệt kê các node ROS 2 đang hoạt động trong mạng DDS
docker compose exec backend bash -c "source /opt/ros/jazzy/setup.bash && ros2 node list"

# [Backend-Exec] 5.2 Liệt kê toàn bộ các topic
docker compose exec backend bash -c "source /opt/ros/jazzy/setup.bash && ros2 topic list"

# [Backend-Exec] 5.3 Đọc 1 gói tin vị trí robot từ AMCL (kiểm tra tọa độ x, y)
docker compose exec backend bash -c "source /opt/ros/jazzy/setup.bash && ros2 topic echo /amcl_pose --once"

# [Backend-Exec] 5.4 Đo tần suất phát vị trí của AMCL (Hz)
docker compose exec backend bash -c "source /opt/ros/jazzy/setup.bash && ros2 topic hz /amcl_pose"

# [Backend-Exec] 5.5 Kiểm tra dữ liệu bản đồ tĩnh OccupancyGrid
docker compose exec backend bash -c "source /opt/ros/jazzy/setup.bash && ros2 topic echo /map --once | head -n 30"

# [Backend-Exec] 5.6 Kiểm tra Action Server điều hướng Nav2 (/navigate_to_pose)
docker compose exec backend bash -c "source /opt/ros/jazzy/setup.bash && ros2 action list"
docker compose exec backend bash -c "source /opt/ros/jazzy/setup.bash && ros2 action info /navigate_to_pose"
```

---

### Tình huống 6: Khởi chạy mô phỏng Gazebo & Nav2 trong Dev Container
Nếu bạn có workspace robot (`ws`) với container `thirsty_ishizaka`:

```bash
# [Dev-Container] Terminal 1: Khởi động mô phỏng Gazebo (Linorobot2)
ros2 launch linorobot2_gazebo gazebo.launch.py

# [Dev-Container] Terminal 2: Khởi động hệ thống điều hướng Nav2 & AMCL
ros2 launch linorobot2_navigation navigation.launch.py sim:=true

# [Dev-Container] Terminal 3 (Tùy chọn): Khởi động RViz2 giám sát trực quan
ros2 launch linorobot2_viz navigation.launch.py sim:=true
```

---

### Tình huống 7: Rebuild từng service sau khi sửa code

```bash
# [Host] Khi chỉ sửa code Backend (Python, API, ROS adapter, websocket)
docker compose build backend && docker compose up -d backend

# [Host] Khi chỉ sửa code Frontend (React, giao diện bản đồ, CSS, ảnh)
docker compose build frontend && docker compose up -d frontend

# [Host] Chạy toàn bộ 19 bài kiểm thử tự động pytest trong backend
docker compose exec backend bash -c "source /opt/ros/jazzy/setup.bash && export PYTHONPATH=/app ROBOT_ADAPTER_MODE=mock && pytest -v -o cache_dir=/tmp/.pytest_cache /app/tests"
```

---

### Tình huống 8: Sao lưu, khôi phục và đặt lại điểm đến (Destinations)

```bash
# [Host] 8.1 Sao lưu dữ liệu điểm đến hiện tại ra tệp có gắn ngày giờ
cp data/destinations.yaml data/destinations_backup_$(date +%Y%m%d_%H%M%S).yaml

# [Host] 8.2 Xem nội dung tệp lưu trữ đang áp dụng
cat data/destinations.yaml

# [Host] 8.3 Khôi phục từ một bản sao lưu cũ
cp data/destinations_backup_20261114.yaml data/destinations.yaml
docker compose restart backend

# [Host] 8.4 Đặt lại (Reset) toàn bộ danh sách điểm về cấu hình gốc mặc định
cp config/destinations.yaml data/destinations.yaml
docker compose restart backend
```

---

## 🛠️ PHẦN 3: XỬ LÝ SỰ CỐ THƯỜNG GẶP (TROUBLESHOOTING)

Quy tắc chuẩn: **Chẩn đoán trước bằng lệnh ➔ Xác định nguyên nhân ➔ Thực hiện khắc phục theo từng trường hợp.**

---

### Sự cố 1: Lỗi `no configuration file provided: not found` hoặc `service not found`
- **Hiện tượng:** Chạy `docker compose up -d` hoặc `docker compose logs` báo lỗi không tìm thấy service `backend`.
- **Bước 1 — Chẩn đoán:**
  ```bash
  # [Host]
  pwd
  ls -la | grep compose
  ```
- **Bước 2 — Nguyên nhân:** Bạn đang đứng ngoài thư mục dự án (ví dụ đang ở `~` hoặc thư mục `ws`).
- **Bước 3 — Khắc phục:**
  ```bash
  cd ~/airport-guide-ui
  docker compose ps
  ```

---

### Sự cố 2: Trình duyệt báo `502 Bad Gateway` ngay sau khi chạy `docker compose up -d`
- **Hiện tượng:** Truy cập `http://localhost:5173` thấy báo lỗi `502 Bad Gateway` từ Nginx.
- **Bước 1 — Chẩn đoán:**
  ```bash
  # [Host] Xem 20 dòng log backend gần nhất
  docker compose logs --tail=20 backend
  ```
- **Bước 2 — Nguyên nhân:** Container Frontend Nginx khởi động cực nhanh (<0.5 giây), trong khi Backend Python FastAPI + `rclpy` cần khoảng 2–3 giây để nạp cấu hình ROS và khởi tạo FastDDS node.
- **Bước 3 — Khắc phục:** Chờ 3–5 giây rồi bấm F5 tải lại trang. Nếu sau 10 giây vẫn báo 502, kiểm tra log backend xem có gặp lỗi cú pháp cấu hình hoặc thiếu biến `SECRET_KEY` không.

---

### Sự cố 3: Backend báo `"status": "healthy"` nhưng `"robot_connected": false`
- **Hiện tượng:** Truy cập web thấy huy hiệu `Robot: Mất kết nối`, gọi `/api/health` thấy `"robot_connected": false`.
- **Bước 1 — Chẩn đoán:**
  ```bash
  # [Backend-Exec] Kiểm tra xem topic /amcl_pose có đang phát dữ liệu không:
  docker compose exec backend bash -c "source /opt/ros/jazzy/setup.bash && ros2 topic echo /amcl_pose --once"
  
  # [Backend-Exec] Kiểm tra Domain ID hiện tại trong container:
  docker compose exec backend bash -c "echo \$ROS_DOMAIN_ID"
  ```
- **Bước 2 — Nguyên nhân & Khắc phục theo từng kết quả:**
  - *Nếu lệnh `ros2 topic echo` không trả về gì:* Mô phỏng Gazebo hoặc node `amcl` chưa được bật trong Dev Container. Hãy bật lại `navigation.launch.py`.
  - *Nếu trong Dev Container có topic nhưng Backend không thấy:* Do lệch Domain ID. Đảm bảo cả hai bên cùng cấu hình `ROS_DOMAIN_ID=0` và sử dụng `network_mode: host`, `ipc: host`. Khởi động lại backend bằng `docker compose restart backend`.

---

### Sự cố 4: Thiếu bản đồ ROS (`/map` không hiển thị trên MapView)
- **Hiện tượng:** Tab "Bản đồ ROS" báo không có dữ liệu bản đồ hoặc tải vô hạn.
- **Bước 1 — Chẩn đoán:**
  ```bash
  # [Backend-Exec] Kiểm tra topic /map có dữ liệu Transient Local không:
  docker compose exec backend bash -c "source /opt/ros/jazzy/setup.bash && ros2 topic info /map -v"
  docker compose exec backend bash -c "source /opt/ros/jazzy/setup.bash && ros2 topic echo /map --once | head -n 15"
  ```
- **Bước 2 — Nguyên nhân:** Node `map_server` của Nav2 chưa kích hoạt (lifecycle unconfigured) hoặc file map `.yaml` trong gói mô phỏng chưa được nạp.
- **Bước 3 — Khắc phục:** Kiểm tra lại terminal chạy `navigation.launch.py sim:=true` trong Dev Container. Sau khi `map_server` chuyển sang trạng thái Active, backend sẽ tự động bắt được bản đồ qua callback `transient_local`.

---

### Sự cố 5: Ảnh "Sơ đồ hành khách" không hiển thị
- **Hiện tượng:** Chuyển sang tab "Sơ đồ hành khách" thấy khung trắng hoặc biểu tượng ảnh vỡ.
- **Bước 1 — Chẩn đoán:**
  ```bash
  # [Host] Kiểm tra file ảnh có tồn tại trên đĩa không:
  ls -lh frontend/public/maps/passenger_map.png
  
  # [Host] Kiểm tra Nginx có phục vụ được file ảnh không:
  curl -I -s http://localhost:5173/maps/passenger_map.png | head -n 5
  ```
- **Bước 2 — Nguyên nhân:** Tệp ảnh `passenger_map.png` chưa được sao chép vào `frontend/public/maps/` hoặc frontend chưa được rebuild sau khi thêm file ảnh mới.
- **Bước 3 — Khắc phục:**
  ```bash
  # Sao chép ảnh sơ đồ của bạn vào thư mục:
  cp /duong/dan/anh/cua_ban.png frontend/public/maps/passenger_map.png
  
  # Rebuild lại container frontend:
  docker compose build frontend && docker compose up -d frontend
  ```

---

## 🪟 PHẦN 4: MÔI TRƯỜNG WINDOWS (CHẾ ĐỘ MOCK)

Dành cho thành viên phát triển giao diện React trên Windows hoặc máy tính không cài ROS 2.

```powershell
# 1. Cài đặt thư viện phụ thuộc (chỉ cần chạy 1 lần)
cd backend
python -m pip install -r requirements.txt
cd ..\frontend
npm install

# 2. Khởi chạy Backend Mock (Terminal 1)
cd backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 3. Khởi chạy Frontend Vite (Terminal 2)
cd frontend
npm run dev

# 4. Kiểm tra cấu hình ROS mặc định
cd backend
python -m app.ros_config

# 5. Chạy bộ Unit Tests đầy đủ
cd backend
python -m pytest tests -v
```
Mở trình duyệt: `http://localhost:5173` (Hành khách) hoặc `http://localhost:5173/admin` (Admin: `admin` / `admin123`).
