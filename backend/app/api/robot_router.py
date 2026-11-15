from typing import List, Dict, Any, Optional
import time
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from ..auth.models import User, UserRole
from ..auth.dependencies import get_current_user, require_role
from ..adapters.factory import get_robot_adapter

router = APIRouter(prefix="/api/robot", tags=["Robot Operations"])

class NavigateRequest(BaseModel):
    destination_id: str

class VoiceConfirmRequest(BaseModel):
    proposal_id: str
    destination_id: Optional[str] = None

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
    st = adapter.get_status()
    owner_id = getattr(adapter, "get_owner_id", lambda: "")()
    is_admin = (current_user.role == UserRole.ADMIN)
    st["has_active_trip"] = bool(owner_id)
    st["is_owner"] = bool((owner_id and current_user and current_user.id == owner_id) or is_admin)
    return st

@router.get("/map")
async def get_map_metadata(current_user: User = Depends(get_current_user)):
    """
    Lấy thông tin metadata và định danh phiên bản của bản đồ OccupancyGrid.
    Public cho cả Hành khách và Admin.
    """
    adapter = get_robot_adapter()
    meta = adapter.get_map_metadata()
    if not meta:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bản đồ chưa sẵn sàng hoặc chưa nhận được từ ROS."
        )
    return meta

@router.get("/map/image")
async def get_map_image(
    v: str = Query(..., description="Phiên bản bản đồ tương ứng với metadata")
):
    """
    Tải ảnh PNG bản đồ theo phiên bản chỉ định.
    Nếu phiên bản không khớp hoặc đã hết hạn, trả lỗi 404 để client tải lại metadata.
    """
    adapter = get_robot_adapter()
    png_bytes = adapter.get_map_image(v)
    if png_bytes is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy ảnh bản đồ phiên bản '{v}'. Vui lòng tải lại metadata từ /api/robot/map."
        )
    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={
            "Cache-Control": "public, max-age=31536000, immutable"
        }
    )

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

@router.delete("/destinations/{destination_id}")
async def delete_destination(
    destination_id: str,
    current_user: User = Depends(require_role(UserRole.ADMIN))
):
    """Xóa điểm đến theo ID (chỉ dành cho Admin đã đăng nhập)"""
    adapter = get_robot_adapter()
    res = adapter.delete_destination(destination_id)
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

@router.post("/pause")
async def pause_navigation(
    current_user: User = Depends(require_role(UserRole.ADMIN))
):
    """
    Tạm dừng chuyến dẫn đường hiện tại (chỉ dành cho Admin đã đăng nhập).
    """
    adapter = get_robot_adapter()
    res = adapter.pause_navigation()
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("message"))
    return res

@router.post("/resume")
async def resume_navigation(
    current_user: User = Depends(require_role(UserRole.ADMIN))
):
    """
    Tiếp tục chuyến dẫn đường sau khi tạm dừng (chỉ dành cho Admin đã đăng nhập).
    """
    adapter = get_robot_adapter()
    res = adapter.resume_navigation()
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("message"))
    return res

@router.post("/voice/start")
async def start_voice_session(current_user: User = Depends(get_current_user)):
    """
    Kích hoạt microphone trên phần cứng robot thông qua ROS Service Trigger /airport/voice/start.
    Web không tự thu âm, chỉ yêu cầu ROS bắt đầu phiên tương tác gắn với phiên hành khách hiện tại.
    """
    adapter = get_robot_adapter()
    res = adapter.start_voice_session(requester_id=current_user.id)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("message"))
    return res

@router.post("/voice/confirm")
async def confirm_voice_proposal(
    req: VoiceConfirmRequest,
    current_user: User = Depends(get_current_user)
):
    """
    Xác nhận đề xuất điểm đến từ nhận dạng giọng nói và bắt đầu điều hướng.
    Chỉ phiên hành khách đã bấm microphone (hoặc Admin) mới được quyền xác nhận.
    Chặn xác nhận lặp và kiểm tra thời hạn đề xuất.
    """
    adapter = get_robot_adapter()
    if not hasattr(adapter, "get_voice_proposal"):
        raise HTTPException(status_code=400, detail="Adapter không hỗ trợ đề xuất giọng nói.")

    proposal = adapter.get_voice_proposal()
    if not proposal:
        raise HTTPException(status_code=400, detail="Không có đề xuất điểm đến giọng nói nào đang chờ xác nhận hoặc đề xuất đã hết hạn.")

    if proposal.get("proposal_id") != req.proposal_id:
        raise HTTPException(status_code=400, detail="Mã đề xuất không khớp hoặc đã bị thay thế bởi yêu cầu mới.")

    if proposal.get("confirmed", False):
        raise HTTPException(status_code=400, detail="Đề xuất điểm đến này đã được xác nhận trước đó.")

    # Kiểm tra quyền: Chỉ phiên đã yêu cầu (hoặc Admin) mới được xác nhận
    if proposal.get("requester_id") != current_user.id and current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Bạn không có quyền xác nhận đề xuất của hành khách khác.")

    now_ms = int(time.time() * 1000)
    if now_ms > proposal.get("expires_at", 0):
        adapter.clear_voice_proposal()
        raise HTTPException(status_code=400, detail="Đề xuất điểm đến đã hết hạn, vui lòng thực hiện lại.")

    target_dest_id = req.destination_id or proposal.get("destination_id")
    if not target_dest_id:
        raise HTTPException(status_code=400, detail="Không xác định được điểm đến hợp lệ để điều hướng.")

    # Đánh dấu proposal đã xác nhận và dọn dẹp để chặn xác nhận lặp
    proposal["confirmed"] = True
    adapter.clear_voice_proposal()

    # Điều hướng tới điểm đến thông qua luồng Start Navigation chuẩn
    res = adapter.start_navigation(destination_id=target_dest_id, owner_id=current_user.id)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("message"))
    return res

@router.post("/voice/dismiss")
async def dismiss_voice_proposal(current_user: User = Depends(get_current_user)):
    """
    Bỏ qua đề xuất điểm đến từ giọng nói hiện tại.
    """
    adapter = get_robot_adapter()
    if hasattr(adapter, "get_voice_proposal"):
        proposal = adapter.get_voice_proposal()
        if proposal and (proposal.get("requester_id") == current_user.id or current_user.role == UserRole.ADMIN):
            adapter.clear_voice_proposal()
    return {"success": True, "message": "Đã bỏ qua đề xuất điểm đến."}

@router.post("/control/manual")
async def set_manual_control(
    req: ManualControlRequest,
    current_user: User = Depends(require_role(UserRole.ADMIN))
):
    """
    Chuyển đổi giữa chế độ AUTO và MANUAL qua ROS Service SetBool (Admin only).
    """
    adapter = get_robot_adapter()
    res = adapter.set_manual_control(req.enable, operator_id=current_user.id)
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
    res = adapter.send_manual_velocity(req.linear_x, req.angular_z, operator_id=current_user.id)
    if not res.get("success"):
        raise HTTPException(
            status_code=400,
            detail=res.get("message") or "Không thể gửi lệnh: Robot không ở chế độ MANUAL hoặc topic chưa sẵn sàng."
        )
    return {"success": True}

@router.get("/alerts")
async def get_alerts(current_user: User = Depends(require_role(UserRole.ADMIN))):
    """Lấy danh sách cảnh báo chẩn đoán từ /airport/alerts (Admin only)"""
    adapter = get_robot_adapter()
    return adapter.get_alerts()

@router.get("/admin/events")
async def get_operational_events(
    limit: int = Query(100, ge=1, le=100),
    current_user: User = Depends(require_role(UserRole.ADMIN))
):
    """
    Lấy danh sách nhật ký sự kiện vận hành (Admin only).
    Chỉ lưu trong bộ nhớ backend (tối đa 100 sự kiện) kể từ lúc backend khởi động.
    """
    adapter = get_robot_adapter()
    events = adapter.get_operational_events(limit=limit) if hasattr(adapter, "get_operational_events") else []
    started_at = adapter.get_events_started_at() if hasattr(adapter, "get_events_started_at") else 0
    version = adapter.get_events_version() if hasattr(adapter, "get_events_version") else 0
    return {
        "events": events,
        "started_at": started_at,
        "version": version,
        "total": len(events)
    }

@router.get("/path")
async def get_navigation_path(current_user: User = Depends(get_current_user)):
    """Lấy lộ trình di chuyển Nav2 (nếu có)"""
    adapter = get_robot_adapter()
    return adapter.get_path()
