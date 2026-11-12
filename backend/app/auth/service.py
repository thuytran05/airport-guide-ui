import os
from typing import Dict, Optional
from .models import User, UserRole, UserOut
from .security import hash_password, verify_password

class UserService:
    def __init__(self):
        self._users: Dict[str, User] = {}
        self._init_default_accounts()

    def _init_default_accounts(self):
        """
        Khởi tạo tài khoản Quản trị viên (Admin) duy nhất.
        Trong production, mật khẩu lấy từ biến môi trường DEFAULT_ADMIN_PASSWORD.
        Hành khách (Passenger) sử dụng phiên khách công khai, không cần đăng nhập.
        """
        admin_pwd = os.getenv("DEFAULT_ADMIN_PASSWORD", "admin123")

        self.create_user(
            user_id="usr-admin-01",
            username="admin",
            full_name="Quản trị viên Hệ thống",
            role=UserRole.ADMIN,
            plain_password=admin_pwd
        )

    def create_user(self, user_id: str, username: str, full_name: str, role: UserRole, plain_password: str) -> User:
        user = User(
            id=user_id,
            username=username.lower(),
            full_name=full_name,
            role=role,
            hashed_password=hash_password(plain_password),
            is_active=True
        )
        self._users[user.username] = user
        return user

    def get_by_username(self, username: str) -> Optional[User]:
        return self._users.get(username.lower())

    def get_by_id(self, user_id: str) -> Optional[User]:
        for u in self._users.values():
            if u.id == user_id:
                return u
        return None

    def authenticate(self, username: str, plain_password: str) -> Optional[User]:
        user = self.get_by_username(username)
        if not user or not user.is_active:
            return None
        if not verify_password(plain_password, user.hashed_password):
            return None
        return user

user_service = UserService()
