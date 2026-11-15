import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from ..auth.models import LoginRequest, Token, UserOut, User, PassengerSessionOut, UserRole
from ..auth.security import create_access_token
from ..auth.service import user_service
from ..auth.dependencies import get_current_user
from ..ws.manager import ws_manager
from ..config import settings

router = APIRouter(prefix="/api/auth", tags=["Authentication"])

@router.post("/session", response_model=PassengerSessionOut)
async def create_passenger_session():
    """
    Cấp token phiên JWT được ký mật mã cho Hành khách vãng lai (không cần mật khẩu).
    Token dùng để xác thực quyền hủy chuyến do chính phiên này tạo ra.
    """
    passenger_id = f"passenger-{uuid.uuid4().hex[:12]}"
    session_id = f"sess_p_{uuid.uuid4().hex[:12]}"
    expires_in_seconds = 30 * 86400  # 30 ngày
    session_token = create_access_token(
        data={
            "sub": passenger_id,
            "role": UserRole.PASSENGER.value,
            "sid": session_id
        },
        expires_delta_seconds=expires_in_seconds
    )
    return PassengerSessionOut(
        session_token=session_token,
        user_id=passenger_id,
        role=UserRole.PASSENGER,
        expires_in=expires_in_seconds
    )

@router.post("/login", response_model=Token)
async def login(request: LoginRequest):
    """
    Xác thực tài khoản và mật khẩu đã băm. Trả về JWT token kèm vai trò được quyết định từ server.
    Mỗi lần đăng nhập tạo một định danh phiên session_id duy nhất để phân biệt đa phiên cùng tài khoản.
    """
    user = user_service.authenticate(request.username, request.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Tên đăng nhập hoặc mật khẩu không chính xác",
        )

    session_id = f"sess_{uuid.uuid4().hex[:12]}"
    access_token = create_access_token(
        data={
            "sub": user.id,
            "username": user.username,
            "role": user.role.value,
            "sid": session_id
        }
    )

    return Token(
        access_token=access_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=UserOut(
            id=user.id,
            username=user.username,
            full_name=user.full_name,
            role=user.role,
            is_active=user.is_active
        )
    )

@router.get("/me", response_model=UserOut)
async def get_my_profile(current_user: User = Depends(get_current_user)):
    """
    Lấy thông tin tài khoản và vai trò của phiên làm việc hiện tại.
    """
    return UserOut(
        id=current_user.id,
        username=current_user.username,
        full_name=current_user.full_name,
        role=current_user.role,
        is_active=current_user.is_active
    )

@router.post("/logout")
async def logout(current_user: User = Depends(get_current_user)):
    """
    Đăng xuất: Đóng toàn bộ kết nối WebSocket đang mở của tài khoản này ngay lập tức.
    """
    await ws_manager.disconnect_user(current_user.id, reason="User logged out")
    return {"message": "Đăng xuất thành công"}

@router.get("/config")
async def get_app_config():
    """
    Trả về cấu hình môi trường ứng dụng (development vs production).
    Khi APP_ENV=production, frontend vô hiệu hóa nút chuyển tài khoản demo tự do.
    """
    return {
        "app_env": settings.APP_ENV,
        "is_production": settings.APP_ENV == "production",
        "adapter_mode": settings.ROBOT_ADAPTER_MODE
    }
