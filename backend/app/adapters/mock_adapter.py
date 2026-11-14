import time
import math
import uuid
import os
import threading
from pathlib import Path
from typing import Dict, Any, List, Optional
import yaml

from .base import BaseRobotAdapter
from ..ros_config import get_ros_config

class MockRobotAdapter(BaseRobotAdapter):
    def __init__(self):
        self._lock = threading.Lock()
        self._ros_config = get_ros_config()
        self._destinations_file = Path(self._ros_config.destinations_storage_path)
        self._destinations_seed_file = Path(self._ros_config.destinations_seed_path)
        self._destinations_version: int = 0
        self._destinations = self._load_destinations()

        # Tọa độ trong hệ quy chiếu map (mét)
        self._pose = {"x": 5.0, "y": 3.0, "theta": 0.0}
        self._battery = 0.88  # 88% (tỉ lệ 0.0 - 1.0)
        self._is_connected = True
        self._is_data_stale = False
        self._control_mode = "AUTO"  # AUTO | MANUAL | TRANSITION | FAULT
        self._navigation_state = "IDLE"  # IDLE, ACCEPTED, NAVIGATING, CANCELING, SUCCEEDED, CANCELED, FAILED
        self._has_goal = False
        self._goal_id = ""
        self._destination_id = ""
        self._owner_id = ""
        self._path_version: int = 0
        self._distance_remaining: Optional[float] = None
        self._goal_pose: Optional[Dict[str, Any]] = None
        self._message = "Hệ thống sẵn sàng đón khách"
        self._last_updated = int(time.time() * 1000)

        # Trạng thái giọng nói ROS
        self._voice_state = "IDLE"  # IDLE | LISTENING | PROCESSING | SPEAKING | ERROR
        self._voice_transcript: Optional[str] = None
        self._voice_response: Optional[str] = None

        # Alerts chẩn đoán
        self._alerts: List[Dict[str, Any]] = [
            {
                "name": "Navigation System",
                "level": 0,  # OK
                "message": "Bộ điều phối Nav2 hoạt động bình thường",
                "hardware_id": "sim_nav"
            },
            {
                "name": "LiDAR Sensor",
                "level": 0,
                "message": "Cảm biến LiDAR quét 360 độ ổn định",
                "hardware_id": "sim_lidar"
            }
        ]

        self._path: List[Dict[str, float]] = []
        self._running = True
        self._timer_thread = threading.Thread(target=self._background_loop, daemon=True)
        self._timer_thread.start()

    def _load_destinations(self) -> List[Dict[str, Any]]:
        # 1. Thử đọc từ tệp lưu trữ bền vững (nếu tệp đã tồn tại)
        if hasattr(self, "_destinations_file") and self._destinations_file.is_file():
            try:
                with open(self._destinations_file, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                    if isinstance(data, dict):
                        dests = data.get("destinations")
                        if dests is None:
                            dests = []
                        return list(dests)
            except Exception as e:
                print(f"[MockRobotAdapter] Lỗi đọc destinations lưu trữ: {e}")
                return []
            return []

        # 2. Nếu chưa có tệp dữ liệu lưu trữ, nạp từ tệp seed khởi tạo
        if hasattr(self, "_destinations_seed_file") and self._destinations_seed_file.is_file():
            try:
                with open(self._destinations_seed_file, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                    if isinstance(data, dict) and "destinations" in data and data["destinations"] is not None:
                        return list(data["destinations"])
            except Exception as e:
                print(f"[MockRobotAdapter] Lỗi đọc destinations seed: {e}")

        return []

    def _save_destinations(self) -> bool:
        temp_file = None
        try:
            self._destinations_file.parent.mkdir(parents=True, exist_ok=True)
            if self._destinations_file.exists() and not os.access(self._destinations_file, os.W_OK):
                raise PermissionError(f"Tệp {self._destinations_file} ở chế độ chỉ đọc")
            if not os.access(self._destinations_file.parent, os.W_OK):
                raise PermissionError(f"Thư mục {self._destinations_file.parent} ở chế độ chỉ đọc")
            temp_file = self._destinations_file.with_name(f"{self._destinations_file.name}.tmp.{time.time()}")
            with open(temp_file, "w", encoding="utf-8") as f:
                yaml.dump({
                    "map_id": "airport_floor_1",
                    "destinations": self._destinations
                }, f, allow_unicode=True, sort_keys=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_file, self._destinations_file)
            return True
        except Exception as e:
            if temp_file and temp_file.exists():
                try:
                    temp_file.unlink()
                except Exception:
                    pass
            print(f"[MockRobotAdapter] Lỗi lưu destinations: {e}")
            return False

    def _background_loop(self):
        while self._running:
            time.sleep(0.1)
            with self._lock:
                now_ms = int(time.time() * 1000)
                self._last_updated = now_ms

                # Nếu đang NAVIGATING, mô phỏng robot di chuyển tới goal_pose
                if self._navigation_state == "NAVIGATING" and self._goal_pose:
                    target_x = self._goal_pose.get("x", self._pose["x"])
                    target_y = self._goal_pose.get("y", self._pose["y"])
                    dx = target_x - self._pose["x"]
                    dy = target_y - self._pose["y"]
                    dist = math.sqrt(dx * dx + dy * dy)

                    if dist < 0.2:
                        # Đã đến đích thành công
                        self._navigation_state = "SUCCEEDED"
                        self._message = "Đã dẫn đường đến đích thành công"
                        self._has_goal = False
                        self._path = []
                        self._path_version += 1
                        self._owner_id = ""
                    else:
                        speed = 0.05  # m / tick (0.5 m/s)
                        nx = dx / dist
                        ny = dy / dist
                        self._pose["x"] += nx * speed
                        self._pose["y"] += ny * speed
                        self._pose["theta"] = math.atan2(ny, nx)

                        # Tạo path giả lập
                        steps = 5
                        self._path = [
                            {"x": self._pose["x"] + (dx * i / steps), "y": self._pose["y"] + (dy * i / steps)}
                            for i in range(steps + 1)
                        ]
                        self._path_version += 1

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "pose": dict(self._pose),
                "battery_percent": self._battery,
                "is_connected": self._is_connected,
                "is_data_stale": self._is_data_stale,
                "control_mode": self._control_mode,
                "navigation_state": self._navigation_state,
                "has_goal": self._has_goal,
                "goal_id": self._goal_id,
                "destination_id": self._destination_id,
                "distance_remaining": self._distance_remaining,
                "voice_state": self._voice_state,
                "voice_transcript": self._voice_transcript,
                "voice_response": self._voice_response,
                "message": self._message,
                "destinations_version": self._destinations_version,
                "last_updated": self._last_updated
            }

    def get_owner_id(self) -> str:
        with self._lock:
            return self._owner_id

    def get_path_version(self) -> int:
        with self._lock:
            return self._path_version

    def get_destinations(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._destinations)

    def get_destinations_version(self) -> int:
        with self._lock:
            return self._destinations_version

    def upsert_destination(self, destination: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            dest_id = destination.get("id")
            if not dest_id:
                return {"success": False, "message": "Destination ID không được để trống"}
            
            # Kiểm tra xem đang dẫn đường tới điểm này không
            if self._navigation_state in ("PENDING", "ACCEPTED", "NAVIGATING", "CANCELING") and self._destination_id == dest_id:
                return {"success": False, "message": "Không thể cập nhật điểm đến đang có chuyến dẫn đường đang hoạt động"}

            old_destinations = list(self._destinations)
            found = False
            for idx, d in enumerate(self._destinations):
                if d.get("id") == dest_id:
                    self._destinations[idx] = destination
                    found = True
                    break
            if not found:
                self._destinations.append(destination)

            saved = self._save_destinations()
            if not saved:
                self._destinations = old_destinations
                return {"success": False, "message": "Không thể lưu điểm đến"}

            self._destinations_version += 1
            return {"success": True, "message": f"Đã lưu điểm đến '{destination.get('name')}' thành công"}

    def delete_destination(self, destination_id: str) -> Dict[str, Any]:
        with self._lock:
            dest_id = str(destination_id).strip()
            if not dest_id:
                return {"success": False, "message": "Destination ID không được để trống"}

            # Chặn xóa điểm đang có chuyến dẫn đường chưa kết thúc
            if self._navigation_state in ("PENDING", "ACCEPTED", "NAVIGATING", "CANCELING") and self._destination_id == dest_id:
                return {"success": False, "message": f"Không thể xóa điểm đến '{dest_id}' vì đang có chuyến dẫn đường chưa kết thúc tới điểm này (trạng thái: {self._navigation_state})"}

            existing_idx = next((i for i, d in enumerate(self._destinations) if d.get("id") == dest_id), None)
            if existing_idx is None:
                return {"success": False, "message": f"Không tìm thấy điểm đến có ID '{dest_id}'"}

            old_destinations = list(self._destinations)
            deleted_dest = self._destinations.pop(existing_idx)

            saved = self._save_destinations()
            if not saved:
                self._destinations = old_destinations
                return {"success": False, "message": "Không thể lưu điểm đến sau khi xóa"}

            self._destinations_version += 1
            deleted_name = deleted_dest.get("name") or dest_id
            return {"success": True, "message": f"Đã xóa thành công điểm đến '{deleted_name}'", "destinations_version": self._destinations_version}

    def start_navigation(self, destination_id: str, owner_id: str) -> Dict[str, Any]:
        with self._lock:
            if self._control_mode == "MANUAL":
                return {"success": False, "message": "Robot đang ở chế độ điều khiển thủ công (MANUAL). Hãy chuyển sang AUTO trước."}
            if self._navigation_state in ("PENDING", "ACCEPTED", "NAVIGATING", "CANCELING"):
                return {"success": False, "message": f"Robot đang bận thực hiện một nhiệm vụ khác (trạng thái: {self._navigation_state})."}

            dest = next((d for d in self._destinations if d.get("id") == destination_id), None)
            if not dest:
                return {"success": False, "message": "Không tìm thấy điểm đến yêu cầu."}

            pose = dest.get("pose", {}).get("position", {})
            self._owner_id = owner_id
            self._destination_id = destination_id
            self._goal_id = uuid.uuid4().hex
            self._goal_pose = {"x": pose.get("x", 0.0), "y": pose.get("y", 0.0)}
            self._has_goal = True
            self._navigation_state = "NAVIGATING"
            self._message = f"Đang dẫn đường tới: {dest.get('name')}"
            return {"success": True, "goal_id": self._goal_id, "message": self._message}

    def cancel_navigation(self, owner_id: str, is_admin: bool = False) -> Dict[str, Any]:
        with self._lock:
            # 1. Kiểm tra quyền sở hữu
            if not is_admin and self._owner_id and owner_id != self._owner_id:
                return {"success": False, "message": "Bạn không có quyền hủy chuyến dẫn đường của người dùng khác."}

            if self._navigation_state not in ("PENDING", "ACCEPTED", "NAVIGATING"):
                return {"success": False, "message": f"Không có chuyến dẫn đường nào đang chạy để hủy (trạng thái: {self._navigation_state})."}

            if self._navigation_state == "CANCELING":
                return {"success": True, "message": "Yêu cầu hủy chuyến đã được tiếp nhận trước đó, đang chờ Nav2 dừng robot..."}

            self._navigation_state = "CANCELING"
            self._message = "Đang dừng robot và hủy chuyến..."

            def _finish_cancel():
                time.sleep(0.2)
                with self._lock:
                    self._navigation_state = "CANCELED"
                    self._has_goal = False
                    self._path = []
                    self._path_version += 1
                    self._owner_id = ""
                    self._message = "Chuyến dẫn đường đã bị hủy"

            threading.Thread(target=_finish_cancel, daemon=True).start()
            return {"success": True, "message": "Yêu cầu hủy chuyến đã được tiếp nhận"}

    def start_voice_session(self) -> Dict[str, Any]:
        with self._lock:
            if self._voice_state in ("LISTENING", "PROCESSING", "SPEAKING"):
                return {"success": False, "message": "Hệ thống giọng nói đang bận xử lý lượt trước."}

            self._voice_state = "LISTENING"
            self._voice_transcript = None
            self._voice_response = None

            def _voice_flow():
                # Thu âm trong 2.5s
                time.sleep(2.5)
                with self._lock:
                    self._voice_state = "PROCESSING"
                    self._voice_transcript = "Hãy dẫn tôi đến Cổng số 1"
                
                # Xử lý 1.5s
                time.sleep(1.5)
                with self._lock:
                    self._voice_state = "SPEAKING"
                    self._voice_response = "Vâng, xin mời bạn đi theo tôi tới Cổng khởi hành số 1."
                
                # Nói trong 2.5s
                time.sleep(2.5)
                with self._lock:
                    self._voice_state = "IDLE"

            threading.Thread(target=_voice_flow, daemon=True).start()
            return {"success": True, "message": "Đã kích hoạt microphone robot thành công"}

    def set_manual_control(self, enable: bool) -> Dict[str, Any]:
        with self._lock:
            if enable:
                if self._navigation_state == "NAVIGATING":
                    self._navigation_state = "CANCELED"
                    self._has_goal = False
                    self._path = []
                self._control_mode = "MANUAL"
                self._message = "Chế độ điều khiển thủ công (MANUAL) được kích hoạt"
                return {"success": True, "message": "Đã chuyển sang MANUAL"}
            else:
                self._control_mode = "AUTO"
                self._message = "Chế độ tự động (AUTO) sẵn sàng"
                return {"success": True, "message": "Đã chuyển sang AUTO"}

    def send_manual_velocity(self, linear_x: float, angular_z: float) -> bool:
        with self._lock:
            if self._control_mode != "MANUAL":
                return False
            
            limits = self._ros_config.velocity_limits
            lin_max = limits.get("linear_max", 0.3)
            ang_max = limits.get("angular_max", 0.5)

            # Clamp vận tốc
            linear_x = max(-lin_max, min(lin_max, linear_x))
            angular_z = max(-ang_max, min(ang_max, angular_z))

            dt = 0.1
            self._pose["theta"] += angular_z * dt
            self._pose["x"] += linear_x * math.cos(self._pose["theta"]) * dt
            self._pose["y"] += linear_x * math.sin(self._pose["theta"]) * dt
            return True

    def get_alerts(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._alerts)

    def get_path(self) -> Optional[List[Dict[str, float]]]:
        with self._lock:
            return list(self._path) if self._path else None

    def get_map_metadata(self) -> Optional[Dict[str, Any]]:
        return {
            "status": "ready",
            "map_version": "mock-v1",
            "frame_id": "map",
            "stamp": {"sec": int(time.time()), "nanosec": 0},
            "metadata": {
                "width": 800,
                "height": 500,
                "resolution": 0.05,
                "origin_x": -20.0,
                "origin_y": -12.5,
                "origin_yaw": 0.0
            },
            "image_url": "/api/robot/map/image?v=mock-v1"
        }

    def get_map_image(self, version: str) -> Optional[bytes]:
        if version != "mock-v1":
            return None
        # Tạo 1 ảnh PNG mẫu nhỏ 800x500
        try:
            from PIL import Image
            import io
            img = Image.new("L", (800, 500), color=254)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue()
        except Exception:
            return None

    def dispose(self) -> None:
        self._running = False
