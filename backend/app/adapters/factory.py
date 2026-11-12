import logging
from typing import Optional
from ..config import settings
from .base import BaseRobotAdapter
from .mock_adapter import MockRobotAdapter

logger = logging.getLogger("adapter_factory")

_adapter_instance: Optional[BaseRobotAdapter] = None

def get_robot_adapter() -> BaseRobotAdapter:
    global _adapter_instance
    if _adapter_instance is not None:
        return _adapter_instance

    mode = settings.ROBOT_ADAPTER_MODE.strip().lower()
    if mode == "ros":
        try:
            from .ros_adapter import RosRobotAdapter
            _adapter_instance = RosRobotAdapter(node_name=settings.ROS_NODE_NAME)
            logger.info("Đã khởi tạo RosRobotAdapter thành công với ROS 2 Jazzy.")
        except Exception as e:
            logger.error(f"Không thể khởi tạo RosRobotAdapter: {e}")
            if settings.APP_ENV == "production":
                raise
            logger.warning("Đang chuyển sang dùng MockRobotAdapter làm fallback trong môi trường dev.")
            _adapter_instance = MockRobotAdapter()
    else:
        _adapter_instance = MockRobotAdapter()
        logger.info("Đang sử dụng MockRobotAdapter (Dữ liệu mô phỏng phía Backend).")

    return _adapter_instance
