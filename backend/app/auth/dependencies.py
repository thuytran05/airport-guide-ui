from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from .models import User, UserRole, ROLE_HIERARCHY
from .security import decode_access_token
from .service import user_service

bearer_scheme = HTTPBearer(auto_error=False)

GUEST_PASSENGER = User(
    id="guest-passenger",
    username="passenger",
    full_name="Hành khách",
    role=UserRole.PASSENGER,
    hashed_password="",
    is_active=True
)

async def get_current_user(credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme)) -> User:
    """
    Xác thực token JWT từ HTTP Authorization Header.
    Nếu không có token, mặc định xem là hành khách (PASSENGER).
    """
    if not credentials:
        return GUEST_PASSENGER
    
    payload = decode_access_token(credentials.credentials)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token không hợp lệ hoặc đã hết hạn",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    username = payload.get("username")
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Payload token thiếu thông tin người dùng",
        )
    
    user = user_service.get_by_username(username)
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Tài khoản không tồn tại hoặc đã bị khóa",
        )
    
    return user

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
    - Nếu không có token hoặc token rỗng: gán quyền Hành khách (PASSENGER).
    - Nếu có token: giải mã, nếu đúng là admin thì gán quyền ADMIN.
    """
    if not token or token in ("null", "undefined", ""):
        return GUEST_PASSENGER
    
    payload = decode_access_token(token)
    if not payload:
        return GUEST_PASSENGER
    
    username = payload.get("username")
    if not username:
        return GUEST_PASSENGER
    
    user = user_service.get_by_username(username)
    return user if user else GUEST_PASSENGER
