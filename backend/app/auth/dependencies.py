import uuid
from typing import Optional
from fastapi import Depends, HTTPException, Header, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from .models import User, UserRole, ROLE_HIERARCHY
from .security import decode_access_token
from .service import user_service

bearer_scheme = HTTPBearer(auto_error=False)

GUEST_PASSENGER = User(
    id="passenger-guest",
    username="guest",
    full_name="Hành khách",
    role=UserRole.PASSENGER,
    hashed_password="",
    is_active=True,
    session_id="passenger-guest"
)

async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    x_passenger_token: Optional[str] = Header(None, alias="X-Passenger-Token"),
    x_session_id: Optional[str] = Header(None, alias="X-Session-ID")
) -> User:
    """
    Xác thực token JWT từ HTTP Authorization Header hoặc X-Passenger-Token.
    - Token của Admin/Staff phải có chữ ký hợp lệ và tồn tại trong user_service.
    - Token của Hành khách phải là JWT do server cấp (/api/auth/session) có chữ ký bí mật.
    - Tuyệt đối không chấp nhận định danh tự xưng (chống giả mạo chủ chuyến đi).
    """
    # 1. Bearer Token
    if credentials:
        payload = decode_access_token(credentials.credentials)
        if not payload:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token không hợp lệ hoặc đã hết hạn",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        username = payload.get("username")
        if username:
            user = user_service.get_by_username(username)
            if not user or not user.is_active:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Tài khoản không tồn tại hoặc đã bị khóa",
                )
            sid = payload.get("sid") or payload.get("session_id") or user.id
            return user.model_copy(update={"session_id": sid})
        
        if payload.get("role") == UserRole.PASSENGER.value and payload.get("sub"):
            sid = payload.get("sid") or payload.get("session_id") or payload["sub"]
            return User(
                id=payload["sub"],
                username=payload["sub"],
                full_name="Hành khách",
                role=UserRole.PASSENGER,
                hashed_password="",
                is_active=True,
                session_id=sid
            )

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Payload token không hợp lệ",
        )

    # 2. X-Passenger-Token Header
    if x_passenger_token and x_passenger_token.strip():
        payload = decode_access_token(x_passenger_token.strip())
        if not payload:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token phiên hành khách không hợp lệ hoặc đã bị chỉnh sửa",
            )
        if payload.get("role") == UserRole.PASSENGER.value and payload.get("sub"):
            sid = payload.get("sid") or payload.get("session_id") or payload["sub"]
            return User(
                id=payload["sub"],
                username=payload["sub"],
                full_name="Hành khách",
                role=UserRole.PASSENGER,
                hashed_password="",
                is_active=True,
                session_id=sid
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token phiên hành khách không đúng định dạng quy định",
        )

    # 3. Yêu cầu vãng lai không có token: cấp định danh ngẫu nhiên dùng một lần (ephemeral)
    ephemeral_id = f"passenger-guest-{uuid.uuid4().hex}"
    return User(
        id=ephemeral_id,
        username=ephemeral_id[:20],
        full_name="Hành khách vãng lai",
        role=UserRole.PASSENGER,
        hashed_password="",
        is_active=True,
        session_id=ephemeral_id
    )

def require_role(required_role: UserRole):
    """
    Dependency kiểm tra vai trò tối thiểu: Passenger (0) < Admin (1).
    """
    async def role_checker(current_user: User = Depends(get_current_user)) -> User:
        user_level = ROLE_HIERARCHY.get(current_user.role, 0)
        required_level = ROLE_HIERARCHY.get(required_role, 0)
        
        if user_level < required_level:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Quyền hạn không đủ. Yêu cầu quyền: {required_role.value}",
            )
        return current_user
    return role_checker

def authenticate_ws_token(token: Optional[str]) -> User:
    """
    Xác thực token dùng cho WebSocket:
    - Nếu không có token: gán khách vãng lai.
    - Nếu có token Admin: gán ADMIN từ user_service.
    - Nếu có token Passenger: gán User PASSENGER với ID xác thực của token đó.
    """
    if not token or token in ("null", "undefined", ""):
        return GUEST_PASSENGER
    
    payload = decode_access_token(token)
    if not payload:
        return GUEST_PASSENGER
    
    username = payload.get("username")
    if username:
        user = user_service.get_by_username(username)
        if user:
            sid = payload.get("sid") or payload.get("session_id") or user.id
            return user.model_copy(update={"session_id": sid})
        return GUEST_PASSENGER

    if payload.get("role") == UserRole.PASSENGER.value and payload.get("sub"):
        sid = payload.get("sid") or payload.get("session_id") or payload["sub"]
        return User(
            id=payload["sub"],
            username=payload["sub"],
            full_name="Hành khách",
            role=UserRole.PASSENGER,
            hashed_password="",
            is_active=True,
            session_id=sid
        )
    
    return GUEST_PASSENGER
