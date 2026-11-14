import asyncio
import logging
from typing import Dict, List, Optional, Set
from fastapi import WebSocket
from starlette.websockets import WebSocketState
from ..auth.models import User, UserRole

logger = logging.getLogger("ws_manager")

class ConnectionManager:
    def __init__(self):
        # Lưu trữ mapping: WebSocket -> User
        self.active_connections: Dict[WebSocket, User] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, user: User):
        if websocket.client_state != WebSocketState.CONNECTED:
            await websocket.accept()
        async with self._lock:
            self.active_connections[websocket] = user
        logger.info(f"WebSocket client kết nối: {user.username} ({user.role.value}). Tổng kết nối: {len(self.active_connections)}")

    async def disconnect(self, websocket: WebSocket):
        async with self._lock:
            user = self.active_connections.pop(websocket, None)
        if user:
            logger.info(f"WebSocket client ngắt kết nối: {user.username}. Còn lại: {len(self.active_connections)}")

    async def disconnect_user(self, user_id: str, reason: str = "Session revoked/expired"):
        """
        Đóng toàn bộ kết nối WebSocket của một user khi họ đăng xuất hoặc phiên bị hủy.
        """
        to_close: List[WebSocket] = []
        async with self._lock:
            for ws, user in self.active_connections.items():
                if user.id == user_id:
                    to_close.append(ws)

        for ws in to_close:
            try:
                await ws.close(code=1008, reason=reason)
            except Exception:
                pass
            await self.disconnect(ws)

    async def broadcast_to_role(self, message: dict, min_role: UserRole):
        """
        Gửi dữ liệu đến các client có vai trò lớn hơn hoặc bằng min_role.
        """
        from ..auth.models import ROLE_HIERARCHY
        min_level = ROLE_HIERARCHY.get(min_role, 0)
        
        async with self._lock:
            recipients = [
                ws for ws, user in self.active_connections.items()
                if ROLE_HIERARCHY.get(user.role, 0) >= min_level
            ]

        for ws in recipients:
            try:
                await ws.send_json(message)
            except Exception as e:
                logger.warning(f"Lỗi gửi tin WebSocket: {e}")

ws_manager = ConnectionManager()
