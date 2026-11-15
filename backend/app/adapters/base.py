from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional

class BaseRobotAdapter(ABC):
    @abstractmethod
    def get_status(self) -> Dict[str, Any]:
        """
        Trả về trạng thái hiện tại của robot:
        {
            "pose": {"x": float, "y": float, "theta": float} or None,
            "battery_percent": Optional[float],  # None nếu không có dữ liệu pin
            "is_connected": bool,
            "is_data_stale": bool,
            "control_mode": str,  # 'AUTO' | 'MANUAL' | 'TRANSITION' | 'FAULT'
            "navigation_state": str,  # 'IDLE' | 'ACCEPTED' | 'NAVIGATING' | 'CANCELING' | 'SUCCEEDED' | 'CANCELED' | 'FAILED' | 'UNKNOWN'
            "has_goal": bool,
            "goal_id": str,
            "destination_id": str,
            "voice_state": str,  # 'IDLE' | 'LISTENING' | 'PROCESSING' | 'SPEAKING' | 'ERROR'
            "voice_transcript": Optional[str],
            "voice_response": Optional[str],
            "message": str,
            "last_updated": int   # ms timestamp
        }
        """
        pass

    @abstractmethod
    def get_destinations(self) -> List[Dict[str, Any]]:
        """Lấy danh sách điểm đến lưu bền vững"""
        pass

    @abstractmethod
    def upsert_destination(self, destination: Dict[str, Any]) -> Dict[str, Any]:
        """Thêm hoặc sửa điểm đến qua service upsert"""
        pass

    @abstractmethod
    def delete_destination(self, destination_id: str) -> Dict[str, Any]:
        """Xóa điểm đến theo destination_id"""
        pass

    @abstractmethod
    def start_navigation(self, destination_id: str, owner_id: str) -> Dict[str, Any]:
        """Bắt đầu điều hướng tới một destination_id"""
        pass

    @abstractmethod
    def cancel_navigation(self, owner_id: str, is_admin: bool = False) -> Dict[str, Any]:
        """Hủy nhiệm vụ điều hướng hiện tại bằng cơ chế cancel của ROS action"""
        pass

    @abstractmethod
    def pause_navigation(self) -> Dict[str, Any]:
        """Tạm dừng nhiệm vụ dẫn đường hiện tại (Admin)"""
        pass

    @abstractmethod
    def resume_navigation(self) -> Dict[str, Any]:
        """Tiếp tục nhiệm vụ dẫn đường đang tạm dừng (Admin)"""
        pass

    @abstractmethod
    def get_owner_id(self) -> str:
        """Trả về ID người sở hữu chuyến đi hiện tại (rỗng nếu robot đang rảnh)"""
        pass

    @abstractmethod
    def start_voice_session(self, requester_id: str = "") -> Dict[str, Any]:
        """Gọi service Trigger /airport/voice/start trên robot và liên kết phiên hành khách"""
        pass

    @abstractmethod
    def is_voice_available(self) -> bool:
        """Kiểm tra xem node giọng nói (service trigger / topic) có sẵn sàng phục vụ hay không"""
        pass

    @abstractmethod
    def get_voice_proposal(self) -> Optional[Dict[str, Any]]:
        """Lấy đề xuất điểm đến nhận dạng được từ giọng nói hiện tại (nếu có)"""
        pass

    @abstractmethod
    def clear_voice_proposal(self) -> None:
        """Xóa đề xuất điểm đến giọng nói sau khi xác nhận, bỏ qua hoặc hết hạn"""
        pass

    @abstractmethod
    def set_manual_control(self, enable: bool, operator_id: str = "", force: bool = False) -> Dict[str, Any]:
        """Gọi service SetBool /airport/control/set_manual"""
        pass

    @abstractmethod
    def send_manual_velocity(
        self,
        linear_x: float,
        angular_z: float,
        operator_id: str = "",
        seq: int = 0,
        hold_id: str = ""
    ) -> Dict[str, Any]:
        """Gửi lệnh vận tốc TwistStamped vào /airport/cmd_vel_manual"""
        pass

    @abstractmethod
    def get_alerts(self) -> List[Dict[str, Any]]:
        """Lấy danh sách cảnh báo từ /airport/alerts"""
        pass

    @abstractmethod
    def get_path(self) -> Optional[List[Dict[str, float]]]:
        """Lấy danh sách các điểm trên đường đi nav_msgs/Path nếu có"""
        pass

    @abstractmethod
    def get_path_version(self) -> int:
        """Trả về số phiên bản của đường đi (tăng khi có đường đi mới hoặc khi xóa)"""
        pass

    def get_destinations_version(self) -> int:
        """Trả về số phiên bản của danh sách điểm đến (tăng khi thêm hoặc cập nhật điểm đến)"""
        return 0

    @abstractmethod
    def get_map_metadata(self) -> Optional[Dict[str, Any]]:
        """Lấy thông tin metadata của bản đồ OccupancyGrid hiện hành"""
        pass

    @abstractmethod
    def get_map_image(self, version: str) -> Optional[bytes]:
        """Lấy dữ liệu bytes PNG của đúng phiên bản bản đồ được yêu cầu"""
        pass

    def has_valid_pose(self) -> bool:
        """Kiểm tra xem robot đã có tọa độ định vị AMCL hợp lệ trong frame map hay chưa"""
        return True

    def get_readiness(self) -> Dict[str, Any]:
        """Trả về điều kiện và tính sẵn sàng dẫn đường của robot"""
        return {"ready": True, "reasons": [], "reason": "Hệ thống sẵn sàng"}

    def get_operational_events(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Lấy danh sách nhật ký sự kiện vận hành gần nhất (dành riêng cho Admin)"""
        from ..services.event_logger import event_logger
        return event_logger.get_events(limit=limit)

    def get_events_version(self) -> int:
        """Trả về phiên bản của bộ đệm sự kiện vận hành"""
        from ..services.event_logger import event_logger
        return event_logger.version

    def get_events_started_at(self) -> int:
        """Trả về thời điểm bắt đầu ghi nhận sự kiện (ms timestamp)"""
        from ..services.event_logger import event_logger
        return event_logger.started_at

    @abstractmethod
    def dispose(self) -> None:
        """Dọn dẹp tiến trình / kết nối khi dừng ứng dụng"""
        pass
