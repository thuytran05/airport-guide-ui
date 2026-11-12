from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field

class UserRole(str, Enum):
    PASSENGER = "passenger"
    ADMIN = "admin"

ROLE_HIERARCHY = {
    UserRole.PASSENGER: 0,
    UserRole.ADMIN: 1,
}

class User(BaseModel):
    id: str
    username: str
    full_name: str
    role: UserRole
    hashed_password: str
    is_active: bool = True

class UserOut(BaseModel):
    id: str
    username: str
    full_name: str
    role: UserRole
    is_active: bool

class LoginRequest(BaseModel):
    username: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut

class TokenPayload(BaseModel):
    sub: str  # user id
    username: str
    role: UserRole
    exp: int
