import time
import threading
from collections import deque
from typing import List, Dict, Any, Optional

class OperationalEventLogger:
    """
    Bộ đệm vòng giới hạn trong bộ nhớ (in-memory circular buffer)
    lưu trữ tối đa 100 sự kiện vận hành gần nhất dành riêng cho Admin.
    
    Quy tắc an toàn và bảo mật:
    - Không lưu trữ trong database hay ghi file đĩa trong giai đoạn này.
    - Không ghi token, cookie hoặc dữ liệu xác thực.
    - Không ghi thông tin định danh cá nhân của hành khách (ID người dùng, tên hành khách).
    - Không ghi nội dung giọng nói (voice transcript).
    - Chống ghi lặp các sự kiện không đổi từ vòng lặp telemetry 5Hz.
    """
    def __init__(self, maxlen: int = 100):
        self._maxlen = maxlen
        self._events: deque = deque(maxlen=maxlen)
        self._lock = threading.Lock()
        self._version: int = 0
        self._started_at: int = int(time.time() * 1000)

        # Trạng thái theo dõi để chống ghi lặp (deduplication)
        self._last_connected: Optional[bool] = None
        self._last_control_mode: str = "AUTO"
        self._last_nav_state: str = "IDLE"

    @property
    def started_at(self) -> int:
        return self._started_at

    @property
    def version(self) -> int:
        with self._lock:
            return self._version

    def add_event(
        self,
        level: str,
        category: str,
        message: str,
        details: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Thêm một sự kiện mới vào bộ đệm.
        level: "INFO" | "WARN" | "ERROR" | "SUCCESS"
        category: "SYSTEM" | "CONNECTION" | "NAVIGATION" | "CONTROL"
        """
        with self._lock:
            now_ms = int(time.time() * 1000)
            self._version += 1
            event_id = f"evt_{now_ms}_{self._version}"
            event = {
                "id": event_id,
                "timestamp": now_ms,
                "level": level.upper(),
                "category": category.upper(),
                "message": message,
                "details": details or {}
            }
            self._events.append(event)
            return dict(event)

    def get_events(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Lấy danh sách các sự kiện gần nhất (tối đa `limit`, mặc định 100)"""
        with self._lock:
            evts = list(self._events)
            if limit < len(evts):
                return evts[-limit:]
            return evts

    def clear(self) -> None:
        """Xóa toàn bộ sự kiện trong bộ đệm (dùng cho test cô lập)"""
        with self._lock:
            self._events.clear()
            self._version += 1
            self._last_connected = None
            self._last_control_mode = "AUTO"
            self._last_nav_state = "IDLE"

    def track_connection(self, is_connected: bool) -> None:
        """
        Theo dõi chuyển đổi trạng thái kết nối ROS.
        Chỉ ghi sự kiện khi có sự thay đổi (True -> False hoặc False -> True),
        chống ghi lặp ở tần số 5Hz.
        """
        with self._lock:
            if self._last_connected is None:
                self._last_connected = is_connected
                if is_connected:
                    self._add_event_unlocked("SUCCESS", "CONNECTION", "Đã kết nối với hệ thống ROS 2")
                else:
                    self._add_event_unlocked("WARN", "CONNECTION", "Chưa kết nối với hệ thống ROS 2")
            elif self._last_connected != is_connected:
                self._last_connected = is_connected
                if is_connected:
                    self._add_event_unlocked("SUCCESS", "CONNECTION", "Đã phục hồi kết nối với hệ thống ROS 2")
                else:
                    self._add_event_unlocked("ERROR", "CONNECTION", "Mất kết nối với hệ thống ROS 2")

    def track_control_mode(self, mode: str) -> None:
        """
        Theo dõi chuyển đổi chế độ điều khiển AUTO / MANUAL.
        Chỉ ghi sự kiện khi chế độ thực tế thay đổi.
        """
        with self._lock:
            if self._last_control_mode != mode:
                self._last_control_mode = mode
                if mode == "MANUAL":
                    self._add_event_unlocked("WARN", "CONTROL", "Đã chuyển sang chế độ điều khiển thủ công (MANUAL)")
                elif mode == "AUTO":
                    self._add_event_unlocked("INFO", "CONTROL", "Đã chuyển sang chế độ điều khiển tự động (AUTO)")

    def track_navigation_state(self, nav_state: str, dest_name: str = "") -> None:
        """
        Theo dõi chuyển đổi trạng thái điều hướng Nav2.
        Chỉ ghi sự kiện khi trạng thái chuyển sang các mốc quan trọng.
        """
        with self._lock:
            if self._last_nav_state != nav_state:
                prev_state = self._last_nav_state
                self._last_nav_state = nav_state
                target_desc = f": {dest_name}" if dest_name else ""

                if nav_state == "NAVIGATING" and prev_state not in ("PAUSING", "PAUSED"):
                    self._add_event_unlocked("INFO", "NAVIGATION", f"Bắt đầu chuyến dẫn đường tới điểm{target_desc}")
                elif nav_state == "PAUSED":
                    self._add_event_unlocked("WARN", "NAVIGATION", f"Tạm dừng chuyến dẫn đường{target_desc}")
                elif nav_state == "NAVIGATING" and prev_state == "PAUSED":
                    self._add_event_unlocked("INFO", "NAVIGATION", f"Tiếp tục chuyến dẫn đường tới điểm{target_desc}")
                elif nav_state == "SUCCEEDED":
                    self._add_event_unlocked("SUCCESS", "NAVIGATION", f"Robot đã đến điểm đích thành công{target_desc}")
                elif nav_state == "CANCELED":
                    self._add_event_unlocked("WARN", "NAVIGATION", f"Chuyến dẫn đường đã bị hủy{target_desc}")
                elif nav_state == "FAILED":
                    self._add_event_unlocked("ERROR", "NAVIGATION", f"Chuyến dẫn đường thất bại{target_desc}")

    def _add_event_unlocked(
        self,
        level: str,
        category: str,
        message: str,
        details: Optional[Dict[str, Any]] = None
    ) -> None:
        now_ms = int(time.time() * 1000)
        self._version += 1
        event_id = f"evt_{now_ms}_{self._version}"
        event = {
            "id": event_id,
            "timestamp": now_ms,
            "level": level.upper(),
            "category": category.upper(),
            "message": message,
            "details": details or {}
        }
        self._events.append(event)

# Khởi tạo singleton dùng chung cho toàn backend
event_logger = OperationalEventLogger(maxlen=100)
