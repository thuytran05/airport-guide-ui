from typing import List, Dict, Any, Optional
import time
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from ..auth.models import User, UserRole
from ..auth.dependencies import get_current_user, require_role
from ..adapters.factory import get_robot_adapter
from ..adapters.base import BaseRobotAdapter

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
    seq: Optional[int] = None
    hold_id: Optional[str] = None

@router.get("/status")
async def get_robot_status(
    current_user: User = Depends(get_current_user),
    adapter: BaseRobotAdapter = Depends(get_robot_adapter)
):
    """Lấy trạng thái tổng quan của robot (hành khách hoặc admin)"""
    st = adapter.get_status()
    owner_id = getattr(adapter, "get_owner_id", lambda: "")()
    is_admin = (current_user.role == UserRole.ADMIN)
    st["has_active_trip"] = bool(owner_id)
    st["is_owner"] = bool((owner_id and current_user and current_user.id == owner_id) or is_admin)
    return st

@router.get("/map")
async def get_map_metadata(
    current_user: User = Depends(get_current_user),
    adapter: BaseRobotAdapter = Depends(get_robot_adapter)
):
    """
    Lấy thông tin metadata và định danh phiên bản của bản đồ OccupancyGrid.
    Public cho cả Hành khách và Admin.
    """
    meta = adapter.get_map_metadata()
    if not meta:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bản đồ chưa sẵn sàng hoặc chưa nhận được từ ROS."
        )
    return meta

@router.get("/map/image")
async def get_map_image(
    v: str = Query(..., description="Phiên bản bản đồ tương ứng với metadata"),
    adapter: BaseRobotAdapter = Depends(get_robot_adapter)
):
    """
    Tải ảnh PNG bản đồ theo phiên bản chỉ định.
    Nếu phiên bản không khớp hoặc đã hết hạn, trả lỗi 404 để client tải lại metadata.
    """
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
async def get_destinations(
    current_user: User = Depends(get_current_user),
    adapter: BaseRobotAdapter = Depends(get_robot_adapter)
):
    """Lấy danh sách các điểm đến trên bản đồ"""
    return adapter.get_destinations()

@router.post("/destinations")
async def upsert_destination(
    req: DestinationUpsertRequest,
    current_user: User = Depends(require_role(UserRole.ADMIN)),
    adapter: BaseRobotAdapter = Depends(get_robot_adapter)
):
    """Thêm hoặc cập nhật điểm đến (chỉ dành cho Admin đã đăng nhập)"""
    res = adapter.upsert_destination(req.model_dump())
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("message"))
    return res

@router.delete("/destinations/{destination_id}")
async def delete_destination(
    destination_id: str,
    current_user: User = Depends(require_role(UserRole.ADMIN)),
    adapter: BaseRobotAdapter = Depends(get_robot_adapter)
):
    """Xóa điểm đến theo ID (chỉ dành cho Admin đã đăng nhập)"""
    res = adapter.delete_destination(destination_id)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("message"))
    return res

@router.post("/navigate")
async def start_navigation(
    req: NavigateRequest,
    current_user: User = Depends(get_current_user),
    adapter: BaseRobotAdapter = Depends(get_robot_adapter)
):
    """
    Bắt đầu chuyến dẫn đường tới điểm đến.
    Hành khách hoặc Admin đều có quyền bắt đầu chuyến.
    """
    res = adapter.start_navigation(destination_id=req.destination_id, owner_id=current_user.id)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("message"))
    return res

@router.post("/cancel")
async def cancel_navigation(
    current_user: User = Depends(get_current_user),
    adapter: BaseRobotAdapter = Depends(get_robot_adapter)
):
    """
    Hủy chuyến dẫn đường hiện tại thông qua cơ chế Cancel Goal của ROS Action.
    """
    is_admin = (current_user.role == UserRole.ADMIN)
    res = adapter.cancel_navigation(owner_id=current_user.id, is_admin=is_admin)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("message"))
    return res

@router.post("/pause")
async def pause_navigation(
    current_user: User = Depends(require_role(UserRole.ADMIN)),
    adapter: BaseRobotAdapter = Depends(get_robot_adapter)
):
    """
    Tạm dừng chuyến dẫn đường hiện tại (chỉ dành cho Admin đã đăng nhập).
    """
    res = adapter.pause_navigation()
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("message"))
    return res

@router.post("/resume")
async def resume_navigation(
    current_user: User = Depends(require_role(UserRole.ADMIN)),
    adapter: BaseRobotAdapter = Depends(get_robot_adapter)
):
    """
    Tiếp tục chuyến dẫn đường sau khi tạm dừng (chỉ dành cho Admin đã đăng nhập).
    """
    res = adapter.resume_navigation()
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("message"))
    return res

@router.post("/voice/start")
async def start_voice_session(
    current_user: User = Depends(get_current_user),
    adapter: BaseRobotAdapter = Depends(get_robot_adapter)
):
    """
    Kích hoạt microphone trên phần cứng robot thông qua ROS Service Trigger /airport/voice/start.
    Web không tự thu âm, chỉ yêu cầu ROS bắt đầu phiên tương tác gắn với phiên hành khách hiện tại.
    Chạy qua anyio worker thread để không chặn event loop asyncio của FastAPI / WebSocket.
    """
    import anyio
    requester_id = current_user.id
    res = await anyio.to_thread.run_sync(adapter.start_voice_session, requester_id)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("message"))
    return res

@router.post("/voice/confirm")
async def confirm_voice_proposal(
    req: VoiceConfirmRequest,
    current_user: User = Depends(get_current_user),
    adapter: BaseRobotAdapter = Depends(get_robot_adapter)
):
    """
    Xác nhận đề xuất điểm đến từ nhận dạng giọng nói và bắt đầu điều hướng.
    Chỉ phiên hành khách đã bấm microphone (hoặc Admin) mới được quyền xác nhận.
    Chặn xác nhận lặp và kiểm tra thời hạn đề xuất. Điểm đến bắt buộc phải lấy từ đề xuất của backend.
    """
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
    user_id = current_user.id
    user_sid = getattr(current_user, "session_id", None)
    req_id = proposal.get("requester_id")
    if req_id != user_id and req_id != user_sid and current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Bạn không có quyền xác nhận đề xuất của hành khách khác.")

    now_ms = int(time.time() * 1000)
    if now_ms > proposal.get("expires_at", 0):
        adapter.clear_voice_proposal()
        raise HTTPException(status_code=400, detail="Đề xuất điểm đến đã hết hạn, vui lòng thực hiện lại.")

    proposal_dest_id = proposal.get("destination_id")
    if not proposal_dest_id or proposal.get("status") != "MATCHED":
        raise HTTPException(status_code=400, detail="Đề xuất giọng nói không có điểm đến xác định để xác nhận.")

    if req.destination_id and req.destination_id != proposal_dest_id:
        raise HTTPException(status_code=400, detail="Điểm đến xác nhận không khớp với điểm đến trong đề xuất được nhận dạng.")

    target_dest_id = proposal_dest_id

    # Kiểm tra lại điểm đến còn tồn tại trong hệ thống
    dests = adapter.get_destinations()
    if not any(d.get("id") == target_dest_id for d in dests):
        adapter.clear_voice_proposal()
        raise HTTPException(status_code=400, detail=f"Điểm đến '{target_dest_id}' không còn tồn tại trong hệ thống.")

    # Kiểm tra tính sẵn sàng của robot tại thời điểm xác nhận
    readiness = adapter.get_readiness() if hasattr(adapter, "get_readiness") else {"ready": True}
    if not readiness.get("ready", True):
        raise HTTPException(status_code=400, detail=f"Robot chưa sẵn sàng dẫn đường: {readiness.get('reason', 'Hệ thống bận')}")

    # Đánh dấu proposal đã xác nhận và dọn dẹp để chặn xác nhận lặp
    proposal["confirmed"] = True
    adapter.clear_voice_proposal()

    # Điều hướng tới điểm đến thông qua luồng Start Navigation chuẩn
    res = adapter.start_navigation(destination_id=target_dest_id, owner_id=user_id)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("message"))
    return res

@router.post("/voice/dismiss")
async def dismiss_voice_proposal(
    current_user: User = Depends(get_current_user),
    adapter: BaseRobotAdapter = Depends(get_robot_adapter)
):
    """
    Bỏ qua đề xuất điểm đến từ giọng nói hiện tại.
    """
    if hasattr(adapter, "get_voice_proposal"):
        proposal = adapter.get_voice_proposal()
        user_id = current_user.id
        user_sid = getattr(current_user, "session_id", None)
        if proposal:
            req_id = proposal.get("requester_id")
            if req_id == user_id or req_id == user_sid or current_user.role == UserRole.ADMIN:
                adapter.clear_voice_proposal()
    return {"success": True, "message": "Đã bỏ qua đề xuất điểm đến."}

@router.post("/control/manual")
async def set_manual_control(
    req: ManualControlRequest,
    current_user: User = Depends(require_role(UserRole.ADMIN)),
    adapter: BaseRobotAdapter = Depends(get_robot_adapter)
):
    """
    Chuyển đổi giữa chế độ AUTO và MANUAL qua ROS Service SetBool (Admin only).
    Phân biệt phiên đăng nhập bằng session_id.
    """
    op_id = current_user.session_id or current_user.id
    res = adapter.set_manual_control(req.enable, operator_id=op_id)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("message"))
    return res

@router.post("/control/velocity")
async def send_manual_velocity(
    req: VelocityCommandRequest,
    current_user: User = Depends(require_role(UserRole.ADMIN)),
    adapter: BaseRobotAdapter = Depends(get_robot_adapter)
):
    """
    Gửi lệnh vận tốc TwistStamped vào topic /airport/cmd_vel_manual (Admin only).
    Lệnh dừng (0, 0) luôn được chấp nhận từ bất kỳ Admin nào để bảo đảm an toàn.
    """
    op_id = current_user.session_id or current_user.id
    res = adapter.send_manual_velocity(
        req.linear_x,
        req.angular_z,
        operator_id=op_id,
        seq=getattr(req, "seq", 0) or 0,
        hold_id=getattr(req, "hold_id", "") or ""
    )
    if not res.get("success"):
        raise HTTPException(
            status_code=400,
            detail=res.get("message") or "Không thể gửi lệnh: Robot không ở chế độ MANUAL hoặc topic chưa sẵn sàng."
        )
    return {"success": True}

@router.get("/alerts")
async def get_alerts(
    current_user: User = Depends(require_role(UserRole.ADMIN)),
    adapter: BaseRobotAdapter = Depends(get_robot_adapter)
):
    """Lấy danh sách cảnh báo chẩn đoán từ /airport/alerts (Admin only)"""
    return adapter.get_alerts()

@router.get("/admin/events")
async def get_operational_events(
    limit: int = Query(100, ge=1, le=100),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
    adapter: BaseRobotAdapter = Depends(get_robot_adapter)
):
    """
    Lấy danh sách nhật ký sự kiện vận hành (Admin only).
    Chỉ lưu trong bộ nhớ RAM backend (tối đa 100 sự kiện) kể từ lúc backend khởi động.
    """
    from ..services.event_logger import event_logger
    if hasattr(adapter, "get_operational_events"):
        events = adapter.get_operational_events(limit=limit)
        started_at = adapter.get_events_started_at() if hasattr(adapter, "get_events_started_at") else event_logger.started_at
        version = adapter.get_events_version() if hasattr(adapter, "get_events_version") else event_logger.version
    else:
        events = event_logger.get_events(limit=limit)
        started_at = event_logger.started_at
        version = event_logger.version

    return {
        "events": events,
        "started_at": started_at,
        "version": version,
        "total": len(events)
    }

@router.get("/path")
async def get_navigation_path(
    current_user: User = Depends(get_current_user),
    adapter: BaseRobotAdapter = Depends(get_robot_adapter)
):
    """Lấy lộ trình di chuyển Nav2 (nếu có)"""
    return adapter.get_path()
