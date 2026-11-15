import time
import math
import uuid
import os
import threading
import logging
import collections
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
import yaml

from .base import BaseRobotAdapter
from ..ros_config import get_ros_config
from ..services.voice_matcher import match_destination_from_transcript
from ..services.event_logger import event_logger

logger = logging.getLogger("mock_adapter")

class MockRobotAdapter(BaseRobotAdapter):
    def __init__(self):
        self._lock = threading.RLock()
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
        self._manual_operator_id: Optional[str] = None
        self._current_manual_twist = (0.0, 0.0)
        self._last_manual_cmd_time: float = 0.0
        self._manual_consumer_available: bool = True
        self._active_hold_id: Optional[str] = None
        self._last_manual_seq: int = 0
        self._last_hold_timestamp_ms: int = 0
        self._io_lock = threading.Lock()
        self._nav2_has_active_goal: bool = False
        self._released_hold_ids: collections.OrderedDict = collections.OrderedDict()
        self._navigation_state = "IDLE"  # IDLE, ACCEPTED, NAVIGATING, PAUSING, PAUSED, CANCELING, SUCCEEDED, CANCELED, FAILED
        self._has_goal = False
        self._goal_id = ""
        self._trip_id = ""
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
        self._voice_available: bool = True
        self._voice_start_in_progress: bool = False
        self._voice_proposal: Optional[Dict[str, Any]] = None
        self._voice_requester_id: str = ""
        self._voice_session_id: str = ""
        self._mock_custom_transcript: Optional[str] = None

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
        event_logger.add_event("INFO", "SYSTEM", "Hệ thống Mock Adapter đã khởi tạo")
        event_logger.track_connection(True)

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

    def _write_destinations_file(self, destinations_data: List[Dict[str, Any]]) -> bool:
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
                    "destinations": destinations_data
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

    def _save_destinations(self) -> bool:
        if not hasattr(self, "_io_lock"):
            self._io_lock = threading.Lock()
        with self._lock:
            snapshot = list(self._destinations)
        with self._io_lock:
            return self._write_destinations_file(snapshot)

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
                        dest = next((d for d in self._destinations if d.get("id") == self._destination_id), None)
                        dest_name = dest.get("name", self._destination_id) if dest else self._destination_id
                        self._navigation_state = "SUCCEEDED"
                        self._message = f"Đã dẫn đường đến '{dest_name}' thành công"
                        self._has_goal = False
                        self._path = []
                        self._path_version += 1
                        self._owner_id = ""
                        event_logger.add_event("SUCCESS", "NAVIGATION", f"Robot đã đến điểm đích: {dest_name}")
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
            reasons = []
            if not self._is_connected:
                reasons.append("Chưa kết nối với hệ thống hoặc robot đang offline.")
            elif self._is_data_stale:
                reasons.append("Dữ liệu vị trí robot bị gián đoạn (stale data).")
            if not self._pose:
                reasons.append("Chưa có vị trí định vị của robot.")
            if self._control_mode == "MANUAL":
                reasons.append("Robot đang ở chế độ MANUAL (Cần chuyển sang AUTO).")
            if self._navigation_state in ("PENDING", "ACCEPTED", "NAVIGATING", "PAUSING", "PAUSED", "CANCELING"):
                reasons.append(f"Robot đang có chuyến dẫn đường hoạt động ({self._navigation_state}).")

            readiness = {
                "ready": len(reasons) == 0,
                "reasons": reasons
            }

            return {
                "pose": dict(self._pose),
                "battery_percent": self._battery,
                "is_connected": self._is_connected,
                "is_data_stale": self._is_data_stale,
                "control_mode": self._control_mode,
                "navigation_state": self._navigation_state,
                "has_goal": self._has_goal,
                "goal_id": self._goal_id,
                "trip_id": getattr(self, "_trip_id", ""),
                "destination_id": self._destination_id,
                "distance_remaining": self._distance_remaining,
                "voice_state": self._voice_state,
                "voice_transcript": self._voice_transcript,
                "voice_response": self._voice_response,
                "voice_requester_id": getattr(self, "_voice_requester_id", ""),
                "voice_available": getattr(self, "_voice_available", True),
                "message": self._message,
                "destinations_version": self._destinations_version,
                "manual_consumer_available": getattr(self, "_manual_consumer_available", True),
                "manual_operator_id": getattr(self, "_manual_operator_id", None),
                "external_goal_active": getattr(self, "_nav2_has_active_goal", False),
                "readiness": readiness,
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
        dest_id = destination.get("id")
        if not dest_id:
            return {"success": False, "message": "Destination ID không được để trống"}

        if not hasattr(self, "_io_lock"):
            self._io_lock = threading.Lock()

        with self._io_lock:
            with self._lock:
                # Kiểm tra xem đang dẫn đường tới điểm này không
                if self._navigation_state in ("PENDING", "ACCEPTED", "NAVIGATING", "PAUSING", "PAUSED", "CANCELING") and self._destination_id == dest_id:
                    return {"success": False, "message": f"Không thể cập nhật điểm đến '{dest_id}' khi đang có chuyến dẫn đường tới điểm này (trạng thái: {self._navigation_state})"}

                # Xây dựng danh sách mới mà không làm thay đổi self._destinations trong bộ nhớ trước khi ghi file
                new_destinations = [dict(d) for d in self._destinations]
                found = False
                for idx, d in enumerate(new_destinations):
                    if d.get("id") == dest_id:
                        new_destinations[idx] = destination
                        found = True
                        break
                if not found:
                    new_destinations.append(destination)

                snapshot = list(new_destinations)

            saved = self._write_destinations_file(snapshot)

            with self._lock:
                if not saved:
                    # Ghi file thất bại: Bộ nhớ hoàn toàn không bị ảnh hưởng, không cần rollback
                    return {"success": False, "message": "Không thể lưu điểm đến"}

                self._destinations = new_destinations
                self._destinations_version += 1
                event_logger.add_event("SUCCESS", "DESTINATION", f"Đã lưu điểm đến '{destination.get('name')}' ({dest_id})")
                return {"success": True, "message": f"Đã lưu điểm đến '{destination.get('name')}' thành công"}

    def delete_destination(self, destination_id: str) -> Dict[str, Any]:
        dest_id = str(destination_id).strip()
        if not dest_id:
            return {"success": False, "message": "Destination ID không được để trống"}

        if not hasattr(self, "_io_lock"):
            self._io_lock = threading.Lock()

        with self._io_lock:
            with self._lock:
                # Chặn xóa điểm đang có chuyến dẫn đường chưa kết thúc
                if self._navigation_state in ("PENDING", "ACCEPTED", "NAVIGATING", "PAUSING", "PAUSED", "CANCELING") and self._destination_id == dest_id:
                    return {"success": False, "message": f"Không thể xóa điểm đến '{dest_id}' vì đang có chuyến dẫn đường chưa kết thúc tới điểm này (trạng thái: {self._navigation_state})"}

                existing_idx = next((i for i, d in enumerate(self._destinations) if d.get("id") == dest_id), None)
                if existing_idx is None:
                    return {"success": False, "message": f"Không tìm thấy điểm đến có ID '{dest_id}'"}

                # Xây dựng danh sách mới mà không làm thay đổi self._destinations trong bộ nhớ trước khi ghi file
                new_destinations = [dict(d) for d in self._destinations]
                deleted_dest = new_destinations.pop(existing_idx)
                deleted_name = deleted_dest.get("name") or dest_id
                snapshot = list(new_destinations)

            saved = self._write_destinations_file(snapshot)

            with self._lock:
                if not saved:
                    # Ghi file thất bại: Bộ nhớ không đổi
                    return {"success": False, "message": "Không thể lưu điểm đến sau khi xóa"}

                self._destinations = new_destinations
                self._destinations_version += 1
                event_logger.add_event("INFO", "DESTINATION", f"Đã xóa điểm đến '{deleted_name}' ({dest_id})")
                return {"success": True, "message": f"Đã xóa thành công điểm đến '{deleted_name}'", "destinations_version": self._destinations_version}

    def start_navigation(self, destination_id: str, owner_id: str) -> Dict[str, Any]:
        with self._lock:
            if getattr(self, "_control_mode", "AUTO") == "MANUAL" or getattr(self, "_active_hold_id", None) is not None:
                return {"success": False, "message": "Không thể bắt đầu dẫn đường: Robot đang trong chế độ điều khiển thủ công (MANUAL) hoặc lượt điều khiển tay."}
            if self._navigation_state in ("PENDING", "ACCEPTED", "NAVIGATING", "PAUSING", "PAUSED", "CANCELING"):
                return {"success": False, "message": f"Robot đang có chuyến dẫn đường đang hoạt động hoặc tạm dừng (trạng thái: {self._navigation_state})."}

            dest = next((d for d in self._destinations if d.get("id") == destination_id), None)
            if not dest:
                return {"success": False, "message": "Không tìm thấy điểm đến yêu cầu."}

            pose = dest.get("pose", {}).get("position", {})
            self._owner_id = owner_id
            self._destination_id = destination_id
            self._goal_id = uuid.uuid4().hex
            self._trip_id = uuid.uuid4().hex
            self._goal_pose = {"x": pose.get("x", 0.0), "y": pose.get("y", 0.0)}
            self._has_goal = True
            self._navigation_state = "NAVIGATING"
            self._message = f"Đang dẫn đường tới: {dest.get('name')}"
            dest_name = dest.get('name', destination_id)
            event_logger.add_event("INFO", "NAVIGATION", f"Bắt đầu chuyến dẫn đường tới điểm: {dest_name}")
            return {"success": True, "goal_id": self._goal_id, "trip_id": self._trip_id, "message": self._message}

    def pause_navigation(self) -> Dict[str, Any]:
        with self._lock:
            if self._navigation_state == "PAUSED":
                return {"success": True, "message": "Chuyến dẫn đường hiện đã ở trạng thái tạm dừng."}
            if self._navigation_state == "PAUSING":
                return {"success": True, "message": "Yêu cầu tạm dừng chuyến đi đã được tiếp nhận, đang dừng robot..."}
            if self._navigation_state not in ("PENDING", "ACCEPTED", "NAVIGATING"):
                return {"success": False, "message": f"Không có chuyến dẫn đường nào đang hoạt động để tạm dừng (trạng thái: {self._navigation_state})."}

            dest = next((d for d in self._destinations if d.get("id") == self._destination_id), None)
            dest_name = dest.get("name", "") if dest else self._destination_id
            self._navigation_state = "PAUSED"
            self._has_goal = False
            self._path = []
            self._path_version += 1
            self._message = f"Chuyến dẫn đường tới '{dest_name}' đã tạm dừng. Sẵn sàng tiếp tục khi có lệnh."
            event_logger.add_event("WARN", "NAVIGATION", f"Tạm dừng chuyến dẫn đường tới {dest_name}")
            return {"success": True, "message": "Đã tạm dừng chuyến dẫn đường thành công."}

    def resume_navigation(self) -> Dict[str, Any]:
        with self._lock:
            if getattr(self, "_control_mode", "AUTO") == "MANUAL" or getattr(self, "_active_hold_id", None) is not None:
                return {"success": False, "message": "Không thể tiếp tục dẫn đường: Robot đang trong chế độ điều khiển thủ công (MANUAL) hoặc lượt điều khiển tay."}
            if self._navigation_state in ("NAVIGATING", "ACCEPTED", "PENDING"):
                return {"success": False, "message": "Robot đang trong quá trình dẫn đường, không cần tiếp tục."}
            if self._navigation_state == "PAUSING":
                return {"success": False, "message": "Robot đang trong quá trình dừng tạm thời. Vui lòng chờ tạm dừng hoàn tất trước khi tiếp tục."}
            if self._navigation_state != "PAUSED":
                return {"success": False, "message": f"Không có chuyến dẫn đường nào đang tạm dừng để tiếp tục (trạng thái: {self._navigation_state})."}

            dest = next((d for d in self._destinations if d.get("id") == self._destination_id), None)
            if not dest:
                return {"success": False, "message": f"Không tìm thấy thông tin điểm đến '{self._destination_id}' để tiếp tục."}

            self._navigation_state = "NAVIGATING"
            self._has_goal = True
            self._goal_id = uuid.uuid4().hex
            dest_name = dest.get("name", self._destination_id)
            self._message = f"Đang tiếp tục dẫn đường tới: {dest_name}"
            event_logger.add_event("INFO", "NAVIGATION", f"Tiếp tục chuyến dẫn đường tới điểm: {dest_name}")
            return {"success": True, "message": self._message}

    def cancel_navigation(self, owner_id: str, is_admin: bool = False) -> Dict[str, Any]:
        with self._lock:
            # 1. Kiểm tra quyền sở hữu
            if not is_admin and self._owner_id and owner_id != self._owner_id:
                return {"success": False, "message": "Bạn không có quyền hủy chuyến dẫn đường của người dùng khác."}

            if self._navigation_state == "PAUSED":
                dest = next((d for d in self._destinations if d.get("id") == self._destination_id), None)
                dest_name = dest.get("name", "") if dest else self._destination_id
                self._navigation_state = "CANCELED"
                self._has_goal = False
                self._path = []
                self._path_version += 1
                self._owner_id = ""
                self._trip_id = ""
                self._destination_id = ""
                self._goal_pose = None
                self._message = f"Chuyến dẫn đường tới '{dest_name}' đã được hủy."
                event_logger.add_event("WARN", "NAVIGATION", f"Chuyến dẫn đường tới '{dest_name}' đã bị hủy")
                return {"success": True, "message": f"Chuyến dẫn đường tới '{dest_name}' đã được hủy thành công."}

            if self._navigation_state not in ("PENDING", "ACCEPTED", "NAVIGATING", "PAUSING"):
                return {"success": False, "message": f"Không có chuyến dẫn đường nào đang chạy để hủy (trạng thái: {self._navigation_state})."}

            if self._navigation_state == "CANCELING":
                return {"success": True, "message": "Yêu cầu hủy chuyến đã được tiếp nhận trước đó, đang chờ Nav2 dừng robot..."}

            self._navigation_state = "CANCELING"
            self._message = "Đang dừng robot và hủy chuyến..."
            cancel_id = str(uuid.uuid4())
            self._active_cancel_id = cancel_id
            target_goal_id = self._goal_id

            def _finish_cancel():
                time.sleep(0.2)
                with self._lock:
                    if getattr(self, "_active_cancel_id", None) != cancel_id:
                        return
                    if getattr(self, "_goal_id", "") != target_goal_id and target_goal_id != "":
                        return
                    if self._navigation_state != "CANCELING":
                        return
                    self._navigation_state = "CANCELED"
                    self._has_goal = False
                    self._path = []
                    self._path_version += 1
                    self._owner_id = ""
                    self._trip_id = ""
                    self._destination_id = ""
                    self._goal_pose = None
                    event_logger.add_event("WARN", "NAVIGATION", "Chuyến dẫn đường đã bị hủy")
                    self._message = "Chuyến dẫn đường đã bị hủy"

            threading.Thread(target=_finish_cancel, daemon=True).start()
            return {"success": True, "message": "Yêu cầu hủy chuyến đã được tiếp nhận"}

    def is_voice_available(self) -> bool:
        return getattr(self, "_voice_available", True)

    def set_voice_available(self, available: bool) -> None:
        """Hỗ trợ kiểm thử trạng thái sẵn sàng của giọng nói"""
        with self._lock:
            self._voice_available = bool(available)

    def set_mock_transcript(self, transcript: Optional[str]) -> None:
        """Hỗ trợ kiểm thử các tình huống nhận dạng giọng nói khác nhau (khớp, không khớp, mập mờ)"""
        with self._lock:
            self._mock_custom_transcript = transcript

    def get_voice_proposal(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            if not self._voice_proposal:
                return None
            now_ms = int(time.time() * 1000)
            if now_ms > self._voice_proposal.get("expires_at", 0):
                self._voice_proposal = None
                return None
            return dict(self._voice_proposal)

    def clear_voice_proposal(self) -> None:
        with self._lock:
            self._voice_proposal = None
            self._voice_transcript = None
            self._voice_response = None
            self._voice_requester_id = ""

    def start_voice_session(self, requester_id: str = "") -> Dict[str, Any]:
        with self._lock:
            if not getattr(self, "_voice_available", True):
                return {
                    "success": False,
                    "message": "ROS Service /airport/voice/start chưa sẵn sàng (node giọng nói chưa khởi chạy)."
                }
            if getattr(self, "_voice_start_in_progress", False):
                return {
                    "success": False,
                    "message": "Yêu cầu kích hoạt microphone đang được xử lý, vui lòng chờ."
                }
            if self._voice_state in ("LISTENING", "PROCESSING", "SPEAKING"):
                return {
                    "success": False,
                    "message": "Hệ thống giọng nói đang bận xử lý lượt trước."
                }

            self._voice_start_in_progress = True
            self._voice_state = "LISTENING"
            self._voice_transcript = None
            self._voice_response = None
            self._voice_proposal = None
            self._voice_requester_id = requester_id
            self._voice_session_id = str(uuid.uuid4())

            def _voice_flow():
                try:
                    # Thu âm trong 1.5s
                    time.sleep(1.5)
                    with self._lock:
                        if getattr(self, "_voice_session_id", "") != session_id:
                            return
                        self._voice_state = "PROCESSING"
                        transcript = self._mock_custom_transcript or "Hãy dẫn tôi đến Cổng khởi hành số 1"
                        self._voice_transcript = transcript

                        # Đối chiếu điểm đến từ transcript (lấy trực tiếp danh sách để tránh khóa lồng)
                        dests = list(self._destinations)
                        match_res = match_destination_from_transcript(transcript, dests)
                        now_ms = int(time.time() * 1000)

                        if match_res["status"] == "MATCHED":
                            dest = match_res["destination"]
                            self._voice_proposal = {
                                "proposal_id": str(uuid.uuid4()),
                                "requester_id": self._voice_requester_id,
                                "session_id": self._voice_session_id,
                                "status": "MATCHED",
                                "destination_id": dest["id"],
                                "destination_name": dest["name"],
                                "transcript": transcript,
                                "created_at": now_ms,
                                "expires_at": now_ms + 30000,
                                "confirmed": False,
                            }
                            response_text = f"Tôi đã nhận diện được điểm đến: {dest['name']}. Vui lòng xác nhận trên màn hình để tôi dẫn đường."
                        elif match_res["status"] == "AMBIGUOUS":
                            self._voice_proposal = {
                                "proposal_id": str(uuid.uuid4()),
                                "requester_id": self._voice_requester_id,
                                "session_id": self._voice_session_id,
                                "status": "AMBIGUOUS",
                                "destination_id": None,
                                "destination_name": None,
                                "transcript": transcript,
                                "created_at": now_ms,
                                "expires_at": now_ms + 30000,
                                "confirmed": False,
                            }
                            response_text = "Tôi tìm thấy nhiều điểm đến trùng khớp. Xin vui lòng chọn trực tiếp trên danh sách."
                        else:
                            self._voice_proposal = {
                                "proposal_id": str(uuid.uuid4()),
                                "requester_id": self._voice_requester_id,
                                "session_id": self._voice_session_id,
                                "status": "NO_MATCH",
                                "destination_id": None,
                                "destination_name": None,
                                "transcript": transcript,
                                "created_at": now_ms,
                                "expires_at": now_ms + 30000,
                                "confirmed": False,
                            }
                            response_text = "Xin lỗi, tôi chưa tìm thấy điểm đến này trong sân bay. Vui lòng chọn từ danh sách."

                    # Xử lý 1.0s
                    time.sleep(1.0)
                    with self._lock:
                        if getattr(self, "_voice_session_id", "") != session_id:
                            return
                        self._voice_state = "SPEAKING"
                        self._voice_response = response_text

                    # Nói trong 1.5s
                    time.sleep(1.5)
                    with self._lock:
                        if getattr(self, "_voice_session_id", "") == session_id:
                            self._voice_state = "IDLE"
                finally:
                    with self._lock:
                        self._voice_start_in_progress = False

            session_id = self._voice_session_id

            threading.Thread(target=_voice_flow, daemon=True).start()
            return {"success": True, "message": "Đã kích hoạt microphone robot thành công"}

    def has_valid_pose(self) -> bool:
        with self._lock:
            if not self._pose:
                return False
            return math.isfinite(self._pose.get("x", 0)) and math.isfinite(self._pose.get("y", 0))

    def is_manual_consumer_available(self) -> bool:
        return getattr(self, "_manual_consumer_available", True)

    def _publish_zero_velocity(self) -> None:
        self._current_manual_twist = (0.0, 0.0)

    def _can_manual_control_locked(self, operator_id: str = "", require_consumer: bool = True) -> Tuple[bool, Optional[str]]:
        if not getattr(self, "_is_connected", True):
            return (False, "Robot chưa kết nối.")
        if not self.has_valid_pose():
            return (False, "Chưa có vị trí định vị hợp lệ.")
        if getattr(self, "_clock_stalled", False):
            return (False, "Mô phỏng đang tạm dừng (clock stalled).")
        nav_state = getattr(self, "_navigation_state", "IDLE")
        if nav_state in ("PENDING", "ACCEPTED", "NAVIGATING", "PAUSING", "PAUSED", "CANCELING") or getattr(self, "_has_goal", False):
            return (False, f"Đang có chuyến dẫn đường ({nav_state}).")
        if getattr(self, "_nav2_has_active_goal", False):
            return (False, "Nav2 đang có mục tiêu điều hướng đang chạy từ nguồn ngoài.")
        current_op = getattr(self, "_manual_operator_id", None)
        if getattr(self, "_control_mode", "AUTO") == "MANUAL" and current_op and operator_id and current_op != operator_id:
            op_desc = f" ({current_op})" if current_op and not str(current_op).startswith("sess_") else ""
            return (False, f"Quyền điều khiển thủ công đang thuộc về Admin khác{op_desc}.")
        if require_consumer and not self.is_manual_consumer_available():
            return (False, "Đường lệnh điều khiển tay ROS (/cmd_vel) chưa có consumer tiếp nhận.")
        return (True, None)

    def can_manual_control(self, operator_id: str = "") -> Tuple[bool, Optional[str]]:
        with self._lock:
            return self._can_manual_control_locked(operator_id, require_consumer=True)

    def check_manual_timeout(self) -> None:
        with self._lock:
            if getattr(self, "_control_mode", "AUTO") != "MANUAL":
                return
            timeout_sec = 0.5
            if hasattr(self, "_ros_config") and hasattr(self._ros_config, "velocity_limits"):
                timeout_sec = self._ros_config.velocity_limits.get("cmd_timeout_sec", 0.5)
            now = time.monotonic()
            last_time = getattr(self, "_last_manual_cmd_time", 0.0)
            if (now - last_time) >= timeout_sec:
                op_id = getattr(self, "_manual_operator_id", None) or "Admin"
                logger.warning(
                    f"Watchdog timeout ({timeout_sec}s): Không nhận được lệnh điều khiển tay từ {op_id}. Dừng robot an toàn."
                )
                if getattr(self, "_active_hold_id", None):
                    self._released_hold_ids[self._active_hold_id] = now
                    while len(self._released_hold_ids) > 500:
                        self._released_hold_ids.popitem(last=False)
                    self._active_hold_id = None
                self._publish_zero_velocity()
                self._control_mode = "AUTO"
                self._manual_operator_id = None
                self._last_manual_seq = 0
                self._current_manual_twist = (0.0, 0.0)
                self._message = "Chế độ tự động (AUTO) sẵn sàng"

    def set_manual_control(self, enable: bool, operator_id: str = "", force: bool = False) -> Dict[str, Any]:
        with self._lock:
            if enable:
                can_drive, reason = self._can_manual_control_locked(operator_id, require_consumer=False)
                if not can_drive and not force:
                    return {"success": False, "message": f"Không thể chuyển sang MANUAL: {reason}"}
                current_op = getattr(self, "_manual_operator_id", None)
                if getattr(self, "_control_mode", "AUTO") == "MANUAL" and current_op and operator_id and current_op != operator_id and not force:
                    op_desc = f" ({current_op})" if current_op and not str(current_op).startswith("sess_") else ""
                    return {
                        "success": False,
                        "message": f"Quyền điều khiển thủ công đang thuộc về Admin khác{op_desc}."
                    }
                self._control_mode = "MANUAL"
                self._manual_operator_id = operator_id
                self._last_manual_cmd_time = time.monotonic()
                self._current_manual_twist = (0.0, 0.0)
                self._active_hold_id = None
                self._last_manual_seq = 0
                self._message = f"Chế độ điều khiển thủ công (MANUAL) được kích hoạt bởi {operator_id or 'Admin'}."
                event_logger.track_control_mode("MANUAL")
                return {"success": True, "message": "Đã chuyển sang MANUAL"}
            else:
                if getattr(self, "_active_hold_id", None):
                    self._released_hold_ids[self._active_hold_id] = time.monotonic()
                    while len(self._released_hold_ids) > 500:
                        self._released_hold_ids.popitem(last=False)
                    self._active_hold_id = None
                self._control_mode = "AUTO"
                self._manual_operator_id = None
                self._last_manual_seq = 0
                self._publish_zero_velocity()
                self._current_manual_twist = (0.0, 0.0)
                self._last_manual_cmd_time = 0.0
                self._message = "Chế độ tự động (AUTO) sẵn sàng"
                event_logger.track_control_mode("AUTO")
                return {"success": True, "message": "Đã chuyển sang AUTO"}

    def send_manual_velocity(
        self,
        linear_x: float,
        angular_z: float,
        operator_id: str = "",
        seq: int = 0,
        hold_id: str = ""
    ) -> Dict[str, Any]:
        with self._lock:
            if not hasattr(self, "_released_hold_ids"):
                self._released_hold_ids = collections.OrderedDict()

            now = time.monotonic()

            # Dọn dẹp cache hold đã giải phóng (> 60s và giữ tối đa 500 phần tử)
            stale_keys = [k for k, t in self._released_hold_ids.items() if (now - t) > 60.0]
            for k in stale_keys:
                self._released_hold_ids.pop(k, None)
            while len(self._released_hold_ids) > 500:
                self._released_hold_ids.popitem(last=False)

            is_stop_cmd = (abs(linear_x) < 1e-4 and abs(angular_z) < 1e-4)

            # 1. Xử lý Lệnh Dừng (Stop / Emergency Stop)
            if is_stop_cmd:
                if not hold_id:
                    # Emergency Stop không gắn hold_id:
                    # Bất kỳ Admin nào gọi cũng dừng xe ngay lập tức, hủy mọi active hold và đưa về AUTO.
                    self._publish_zero_velocity()
                    self._current_manual_twist = (0.0, 0.0)
                    self._last_manual_cmd_time = now
                    if getattr(self, "_active_hold_id", None):
                        self._released_hold_ids[self._active_hold_id] = now
                        self._active_hold_id = None
                    was_manual = (getattr(self, "_control_mode", "AUTO") == "MANUAL")
                    self._control_mode = "AUTO"
                    self._manual_operator_id = None
                    self._message = "Chế độ tự động (AUTO) sẵn sàng"
                    if was_manual:
                        event_logger.track_control_mode("AUTO")
                    return {"success": True, "message": "Đã gửi lệnh dừng khẩn cấp (Emergency Stop) thành công."}

                # Lệnh Dừng giải phóng hold cụ thể (release specific hold)
                self._released_hold_ids[hold_id] = now
                active_id = getattr(self, "_active_hold_id", None)
                if active_id == hold_id:
                    self._active_hold_id = None
                    self._publish_zero_velocity()
                    self._current_manual_twist = (0.0, 0.0)
                    self._last_manual_cmd_time = now
                    if seq > getattr(self, "_last_manual_seq", 0):
                        self._last_manual_seq = seq
                    was_manual = (getattr(self, "_control_mode", "AUTO") == "MANUAL")
                    self._control_mode = "AUTO"
                    self._manual_operator_id = None
                    self._message = "Chế độ tự động (AUTO) sẵn sàng"
                    if was_manual:
                        event_logger.track_control_mode("AUTO")
                    return {"success": True, "message": "Đã giải phóng hold và dừng robot an toàn."}
                else:
                    # Hold cũ hoặc không khớp active hold -> Không dừng hay làm gián đoạn active hold mới
                    return {"success": True, "ignored": True, "message": f"Hold '{hold_id}' không còn là active hold, bỏ qua dừng."}

            # 2. Xử lý Lệnh Chuyển động (Vận tốc khác 0)
            # BẮT BUỘC có hold_id và seq >= 1 (Loại bỏ hoàn toàn single-shot/legacy branch cho lệnh chuyển động)
            if not hold_id or seq is None or seq < 1:
                return {
                    "success": False,
                    "message": "Yêu cầu hold_id và seq (seq >= 1) hợp lệ cho lệnh vận tốc di chuyển."
                }

            # Kiểm tra hold đã giải phóng
            if hold_id in self._released_hold_ids:
                return {
                    "success": True,
                    "ignored": True,
                    "message": "Bỏ qua lệnh vận tốc của lượt bấm đã kết thúc."
                }

            # Kiểm tra thứ tự và thời gian tạo hold (Tránh hold cũ đến muộn chiếm quyền hold mới)
            hold_timestamp_ms = None
            if hold_id.startswith("hold_"):
                parts = hold_id.split("_")
                if len(parts) >= 2 and parts[1].isdigit():
                    hold_timestamp_ms = int(parts[1])

            if getattr(self, "_active_hold_id", None) == hold_id:
                last_seq = getattr(self, "_last_manual_seq", 0)
                if seq <= last_seq:
                    return {
                        "success": True,
                        "ignored": True,
                        "message": f"Bỏ qua lệnh vận tốc đến trễ hoặc lặp seq (seq {seq} <= {last_seq})."
                    }
                self._last_manual_seq = seq
            else:
                # Hold mới được khởi tạo
                if hold_timestamp_ms is not None:
                    last_hold_ts = getattr(self, "_last_hold_timestamp_ms", 0)
                    if hold_timestamp_ms < last_hold_ts:
                        logger.warning(
                            f"Bỏ qua hold cũ đến trễ: {hold_id} (ts: {hold_timestamp_ms} < {last_hold_ts})"
                        )
                        return {
                            "success": True,
                            "ignored": True,
                            "message": "Bỏ qua hold cũ đến trễ hơn hold đã xử lý."
                        }
                    self._last_hold_timestamp_ms = hold_timestamp_ms

                # Nếu đang có hold hoạt động khác:
                if getattr(self, "_active_hold_id", None) is not None:
                    current_op = getattr(self, "_manual_operator_id", None)
                    if current_op and operator_id and current_op != operator_id:
                        op_desc = f" ({current_op})" if current_op and not str(current_op).startswith("sess_") else ""
                        return {
                            "success": False,
                            "message": f"Quyền điều khiển đang thuộc về phiên khác{op_desc}."
                        }
                    # Đưa hold cũ vào cache giải phóng
                    self._released_hold_ids[self._active_hold_id] = now

                self._active_hold_id = hold_id
                self._last_manual_seq = seq

            # 3. Kiểm tra điều kiện lái tay và quyền Admin TRƯỚC TIÊN
            can_drive, reason = self._can_manual_control_locked(operator_id)
            if not can_drive:
                return {"success": False, "message": reason or "Không đủ điều kiện điều khiển tay."}

            # 4. Kiểm tra dữ liệu đầu vào hữu hạn
            if not (math.isfinite(linear_x) and math.isfinite(angular_z)):
                return {"success": False, "message": "Giá trị vận tốc không hợp lệ (NaN hoặc Inf)."}

            # 5. Kích hoạt MANUAL (không ghi log AUTO/MANUAL trên mỗi nhịp giữ phím tạm thời)
            self._control_mode = "MANUAL"
            self._manual_operator_id = operator_id
            self._message = f"Chế độ điều khiển thủ công (MANUAL) được kích hoạt bởi {operator_id or 'Admin'}."

            limits = self._ros_config.velocity_limits if hasattr(self, "_ros_config") and hasattr(self._ros_config, "velocity_limits") else {}
            lin_max = limits.get("linear_max", 0.3)
            ang_max = limits.get("angular_max", 0.5)

            clamped_x = max(-lin_max, min(lin_max, float(linear_x)))
            clamped_z = max(-ang_max, min(ang_max, float(angular_z)))

            dt = 0.1
            self._pose["theta"] += clamped_z * dt
            self._pose["x"] += clamped_x * math.cos(self._pose["theta"]) * dt
            self._pose["y"] += clamped_x * math.sin(self._pose["theta"]) * dt

            self._last_manual_cmd_time = time.monotonic()
            self._current_manual_twist = (clamped_x, clamped_z)
            return {"success": True, "message": "Đã gửi lệnh vận tốc thành công."}

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
