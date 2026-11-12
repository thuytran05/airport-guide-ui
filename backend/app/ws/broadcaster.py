import asyncio
import time
import logging
from typing import Dict, Any
from ..auth.models import UserRole
from ..adapters.factory import get_robot_adapter
from .manager import ws_manager

logger = logging.getLogger("telemetry_broadcaster")

async def telemetry_broadcaster_loop():
    """
    Vòng lặp gửi dữ liệu telemetry thời gian thực qua WebSocket (5Hz = 200ms).
    Lọc dữ liệu theo 2 vai trò:
    - Passenger: Chỉ nhận dữ liệu cần thiết phục vụ hành khách.
    - Admin: Nhận thêm cảnh báo hệ thống (alerts) và dữ liệu quản trị.
    """
    logger.info("Khởi động vòng lặp Telemetry Broadcaster (5Hz)...")
    tick_count = 0

    while True:
        try:
            await asyncio.sleep(0.2)  # 5Hz rate limit
            tick_count += 1

            if not ws_manager.active_connections:
                continue

            adapter = get_robot_adapter()
            now_ms = int(time.time() * 1000)

            # Thu thập trạng thái từ adapter
            status = adapter.get_status()
            path = adapter.get_path()

            # Mỗi 1 giây (5 ticks) lấy alerts
            alerts = adapter.get_alerts() if (tick_count % 5 == 0) else None

            async with ws_manager._lock:
                clients_snapshot = list(ws_manager.active_connections.items())

            for ws, user in clients_snapshot:
                payload: Dict[str, Any] = {
                    "type": "telemetry",
                    "server_time": now_ms,
                    "backend_connected": True,
                    "robot_status": {
                        "pose": status["pose"],
                        "battery_percent": status["battery_percent"],
                        "is_connected": status["is_connected"],
                        "is_data_stale": status["is_data_stale"],
                        "control_mode": status["control_mode"],
                        "navigation_state": status["navigation_state"],
                        "has_goal": status["has_goal"],
                        "goal_id": status["goal_id"],
                        "destination_id": status["destination_id"],
                        "voice_state": status["voice_state"],
                        "voice_transcript": status["voice_transcript"],
                        "voice_response": status["voice_response"],
                        "message": status["message"],
                        "last_updated": status["last_updated"]
                    },
                    "path": path
                }

                # Dành riêng cho Admin đã đăng nhập
                if user.role == UserRole.ADMIN:
                    payload["admin_data"] = {
                        "alerts": alerts or adapter.get_alerts()
                    }

                try:
                    await ws.send_json(payload)
                except Exception:
                    pass

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Lỗi trong vòng lặp Telemetry Broadcaster: {e}")
            await asyncio.sleep(1.0)
