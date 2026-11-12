from typing import Optional
from fastapi import APIRouter, Depends
from ..auth.models import User, UserRole
from ..auth.dependencies import require_role
from ..adapters.factory import get_robot_adapter

router = APIRouter(prefix="/api/diagnostics", tags=["Developer Diagnostics"])

# Tất cả endpoint trong router này đều yêu cầu vai trò DEVELOPER
developer_dep = require_role(UserRole.DEVELOPER)

@router.get("/sensors")
async def get_sensors(current_user: User = Depends(developer_dep)):
    """Chỉ Developer mới có quyền xem dữ liệu cảm biến thô"""
    adapter = get_robot_adapter()
    return adapter.get_sensor_readings()

@router.get("/nav-state")
async def get_nav_state(current_user: User = Depends(developer_dep)):
    """Chỉ Developer mới có quyền xem thông số Nav2 Stack"""
    adapter = get_robot_adapter()
    return adapter.get_nav_state()

@router.get("/topics")
async def get_allowed_topics(current_user: User = Depends(developer_dep)):
    """Chỉ Developer mới có quyền xem danh sách topic ROS"""
    adapter = get_robot_adapter()
    return adapter.get_allowed_topics()

@router.get("/logs")
async def get_logs(
    level: Optional[str] = None,
    since: Optional[int] = None,
    current_user: User = Depends(developer_dep)
):
    """Chỉ Developer mới có quyền xem nhật ký lỗi và sự kiện ROS"""
    adapter = get_robot_adapter()
    return adapter.get_logs(level=level, since=since)
