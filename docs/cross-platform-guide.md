# Hướng dẫn phát triển đa nền tảng (Windows & Ubuntu 22)

> **Lưu ý quan trọng:** Giao diện đang được phát triển trên Windows và chưa thực sự chạy thử trực tiếp trên máy Ubuntu 22 của robot. Tài liệu này cung cấp quy trình chuẩn để chuyển đổi và cài đặt mà không gặp lỗi không tương thích.

---

## 1. Thông số môi trường phát triển đã xác nhận

- **Hệ điều hành máy phát triển:** Windows 10/11 (PowerShell)
- **Node.js:** `v22.16.0` (LTS)
- **npm:** `10.9.2`
- **Lockfile:** Đã lưu `package-lock.json` đồng nhất các phiên bản phụ thuộc.
- **Hệ điều hành máy robot (Host):** Ubuntu 22.04 LTS (ROS 2 Jazzy trong Docker).

---

## 2. Quy tắc quan trọng khi chuyển từ Windows sang Ubuntu

1. **Tuyệt đối KHÔNG sao chép thư mục `node_modules/` từ Windows sang Ubuntu.**
   - Một số gói (ví dụ `lightningcss`, `rolldown` của Vite) cài đặt các file nhị phân riêng cho từng OS (`win32-x64-msvc` trên Windows vs `linux-x64-gnu` trên Ubuntu).
   - Nếu sao chép `node_modules` từ Windows, Vite trên Ubuntu sẽ báo lỗi thiếu binary.
2. **Tuân thủ chữ hoa / chữ thường (Case-sensitivity):**
   - Windows không phân biệt hoa thường trong đường dẫn, nhưng Ubuntu (Linux) phân biệt rất nghiêm ngặt (`Home.tsx` khác `home.tsx`).
   - Toàn bộ đường dẫn import trong mã nguồn dự án đã được rà soát khớp 100% chữ hoa/thường.
3. **Tránh đường dẫn tuyệt đối:**
   - Không sử dụng các đường dẫn cố định như `C:\...` hay dấu gạch chéo ngược `\` trong mã nguồn.
   - Luôn sử dụng đường dẫn tương đối (`./`, `../`) hoặc alias chuẩn.

---

## 3. Hướng dẫn chạy trên Windows (Máy phát triển hiện tại)

Mở **PowerShell**:

```powershell
# Di chuyển vào thư mục frontend
cd frontend

# Cài đặt thư viện (nếu clone mới)
npm install

# Khởi chạy dev server
npm run dev

# Kiểm tra build TypeScript & Vite
npm run build
```

Mở trình duyệt: `http://localhost:5173`

---

## 4. Hướng dẫn chuyển mã nguồn sang Ubuntu 22 & Chạy

### Cách 1: Sử dụng Git (Khuyến nghị)

Trên Windows:
```powershell
git add .
git commit -m "feat: complete phase A mock UI"
git push
```

Trên Ubuntu 22 (máy robot):
```bash
# 1. Clone repository
git clone <url-repository>
cd airport-guide-ui/frontend

# 2. Cài đặt Node.js 22 LTS trên Ubuntu 22 (nếu chưa có)
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt-get install -y nodejs

# Kiểm tra phiên bản (khuyến nghị Node >= 20, tốt nhất là v22.16.x)
node -v
npm -v

# 3. Cài đặt thư viện sạch từ package-lock.json
npm ci

# 4. Khởi chạy dev server cho phép truy cập qua LAN
npm run dev -- --host 0.0.0.0
```

### Cách 2: Sao chép file trực tiếp (qua SSH / SCP / USB)

Khi nén hoặc copy thư mục dự án, hãy loại trừ `node_modules` và `dist`:

Trên Windows (PowerShell):
```powershell
# Nén dự án bỏ qua node_modules và dist
tar --exclude="node_modules" --exclude="dist" -czvf airport-guide-ui.tar.gz airport-guide-ui
```

Trên Ubuntu 22:
```bash
# Giải nén
tar -xzvf airport-guide-ui.tar.gz
cd airport-guide-ui/frontend

# Cài lại thư viện native cho Linux
npm install

# Khởi chạy
npm run dev -- --host 0.0.0.0
```

---

## 5. Truy cập qua mạng nội bộ (LAN)

Khi chạy với cờ `--host 0.0.0.0` (đã được cấu hình mặc định trong `vite.config.ts`), cả hai máy trên cùng mạng Wi-Fi/LAN đều có thể mở giao diện:
- **Trên máy robot:** `http://localhost:5173`
- **Trên máy tính điều khiển bên ngoài:** `http://<IP_MÁY_ROBOT>:5173` (ví dụ `http://192.168.0.102:5173`)
