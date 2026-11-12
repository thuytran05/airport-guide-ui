from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from ..auth.models import User, UserRole
from ..auth.dependencies import get_current_user, require_role
from ..adapters.factory import get_robot_adapter

router = APIRouter(prefix="/api/robot", tags=["Robot Operations"])

class NavigateRequest(BaseModel):
    destination_id: str

class DestinationUpsertRequest(BaseModel):
    id: str
    name: str
    map_id: str = "map"
    pose: Dict[str, Any]

class ManualControlRequest(BaseModel):
    enable: bool

class VelocityCommandRequest(BaseModel):
    linear_x: float = Field(..., ge=-1.0, le=1.0)
    angular_z: float = Field(..., ge=-2.0, le=2.0)

@router.get("/status")
async def get_robot_status(current_user: User = Depends(get_current_user)):
    """Lấy trạng thái tổng quan của robot (hành khách hoặc admin)"""
    adapter = get_robot_adapter()
    return adapter.get_status()

@router.get("/destinations")
async def get_destinations(current_user: User = Depends(get_current_user)):
    """Lấy danh sách các điểm đến trên bản đồ"""
    adapter = get_robot_adapter()
    return adapter.get_destinations()

@router.post("/destinations")
async def upsert_destination(
    req: DestinationUpsertRequest,
    current_user: User = Depends(require_role(UserRole.ADMIN))
):
    """Thêm hoặc cập nhật điểm đến (chỉ dành cho Admin đã đăng nhập)"""
    adapter = get_robot_adapter()
    res = adapter.upsert_destination(req.model_dump())
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("message"))
    return res

@router.post("/navigate")
async def start_navigation(
    req: NavigateRequest,
    current_user: User = Depends(get_current_user)
):
    """
    Bắt đầu chuyến dẫn đường tới điểm đến.
    Hành khách hoặc Admin đều có quyền bắt đầu chuyến.
    """
    adapter = get_robot_adapter()
    res = adapter.start_navigation(destination_id=req.destination_id, owner_id=current_user.id)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("message"))
    return res

@router.post("/cancel")
async def cancel_navigation(current_user: User = Depends(get_current_user)):
    """
    Hủy chuyến dẫn đường hiện tại thông qua cơ chế Cancel Goal của ROS Action.
    """
    adapter = get_robot_adapter()
    is_admin = (current_user.role == UserRole.ADMIN)
    res = adapter.cancel_navigation(owner_id=current_user.id, is_admin=is_admin)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("message"))
    return res

@router.post("/voice/start")
async def start_voice_session(current_user: User = Depends(get_current_user)):
    """
    Kích hoạt microphone trên phần cứng robot thông qua ROS Service Trigger /airport/voice/start.
    Web không tự thu âm, chỉ yêu cầu ROS bắt đầu phiên tương tác.
    """
    adapter = get_robot_adapter()
    res = adapter.start_voice_session()
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("message"))
    return res

@router.post("/control/manual")
async def set_manual_control(
    req: ManualControlRequest,
    current_user: User = Depends(require_role(UserRole.ADMIN))
):
    """
    Chuyển đổi giữa chế độ AUTO và MANUAL qua ROS Service SetBool (Admin only).
    """
    adapter = get_robot_adapter()
    res = adapter.set_manual_control(req.enable)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("message"))
    return res

@router.post("/control/velocity")
async def send_manual_velocity(
    req: VelocityCommandRequest,
    current_user: User = Depends(require_role(UserRole.ADMIN))
):
    """
    Gửi lệnh vận tốc TwistStamped vào topic /airport/cmd_vel_manual (Admin only).
    """
    adapter = get_robot_adapter()
    success = adapter.send_manual_velocity(req.linear_x, req.angular_z)
    if not success:
        raise HTTPException(
            status_code=400,
            detail="Không thể gửi lệnh: Robot không ở chế độ MANUAL hoặc topic chưa sẵn sàng."
        )
    return {"success": True}

@router.get("/alerts")
async def get_alerts(current_user: User = Depends(require_role(UserRole.ADMIN))):
    """Lấy danh sách cảnh báo chẩn đoán từ /airport/alerts (Admin only)"""
    adapter = get_robot_adapter()
    return adapter.get_alerts()

@router.get("/path")
async def get_navigation_path(current_user: User = Depends(get_current_user)):
    """Lấy lộ trình di chuyển Nav2 (nếu có)"""
    adapter = get_robot_adapter()
    return adapter.get_path()
