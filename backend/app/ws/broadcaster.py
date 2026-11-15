import asyncio
import time
import logging
from typing import Dict, Any
from ..auth.models import UserRole
from ..adapters.factory import get_robot_adapter
from ..services.event_logger import event_logger
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
    last_sent_path_versions: Dict[Any, int] = {}
    last_sent_event_versions: Dict[Any, int] = {}

    while True:
        try:
            await asyncio.sleep(0.2)  # 5Hz rate limit
            tick_count += 1

            adapter = get_robot_adapter()
            if hasattr(adapter, "ensure_spinning"):
                adapter.ensure_spinning()
            if hasattr(adapter, "check_manual_timeout"):
                adapter.check_manual_timeout()

            if not ws_manager.active_connections:
                last_sent_path_versions.clear()
                last_sent_event_versions.clear()
                continue

            now_ms = int(time.time() * 1000)

            # Thu thập trạng thái từ adapter
            status = adapter.get_status()
            current_path_version = getattr(adapter, "get_path_version", lambda: 0)()
            owner_id = getattr(adapter, "get_owner_id", lambda: "")()

            # Theo dõi trạng thái chuyển đổi kết nối và chế độ điều khiển (chống ghi lặp)
            event_logger.track_connection(status.get("is_connected", False))
            event_logger.track_control_mode(status.get("control_mode", "AUTO"))

            # Mỗi 1 giây (5 ticks) lấy alerts
            alerts = adapter.get_alerts() if (tick_count % 5 == 0) else None
            active_proposal = adapter.get_voice_proposal() if hasattr(adapter, "get_voice_proposal") else None

            async with ws_manager._lock:
                clients_snapshot = list(ws_manager.active_connections.items())

            # Dọn dẹp cache socket đã ngắt kết nối
            active_ws_set = {ws for ws, _ in clients_snapshot}
            last_sent_path_versions = {
                ws: ver for ws, ver in last_sent_path_versions.items()
                if ws in active_ws_set
            }
            last_sent_event_versions = {
                ws: ver for ws, ver in last_sent_event_versions.items()
                if ws in active_ws_set
            }

            for ws, user in clients_snapshot:
                is_owner = bool(
                    (owner_id and user and user.id == owner_id) or
                    (user.role == UserRole.ADMIN)
                )

                user_proposal = None
                if active_proposal and not active_proposal.get("confirmed", False):
                    # Chỉ hiển thị đề xuất cho phiên đã bấm microphone (hoặc Admin)
                    if (user and active_proposal.get("requester_id") == user.id) or (user and user.role == UserRole.ADMIN):
                        user_proposal = {
                            "proposal_id": active_proposal["proposal_id"],
                            "destination_id": active_proposal.get("destination_id"),
                            "destination_name": active_proposal.get("destination_name"),
                            "status": active_proposal["status"],
                            "transcript": active_proposal.get("transcript"),
                            "created_at": active_proposal["created_at"],
                        }

                payload: Dict[str, Any] = {
                    "type": "telemetry",
                    "server_time": now_ms,
                    "backend_connected": True,
                    "robot_status": {
                        "pose": status["pose"],
                        "frame_id": status.get("frame_id"),
                        "stamp": status.get("stamp"),
                        "battery_percent": status["battery_percent"],
                        "is_connected": status["is_connected"],
                        "is_data_stale": status["is_data_stale"],
                        "control_mode": status["control_mode"],
                        "navigation_state": status["navigation_state"],
                        "has_goal": status["has_goal"],
                        "goal_id": status["goal_id"],
                        "trip_id": status.get("trip_id", ""),
                        "destination_id": status["destination_id"],
                        "has_active_trip": bool(owner_id),
                        "is_owner": is_owner,
                        "distance_remaining": status.get("distance_remaining"),
                        "estimated_time_remaining": status.get("estimated_time_remaining"),
                        "voice_state": status["voice_state"],
                        "voice_transcript": status["voice_transcript"],
                        "voice_response": status["voice_response"],
                        "voice_available": status.get("voice_available", False),
                        "voice_proposal": user_proposal,
                        "message": status["message"],
                        "last_updated": status["last_updated"],
                        "sim_clock_stalled": status.get("sim_clock_stalled", False),
                        "map_version": status.get("map_version"),
                        "destinations_version": status.get("destinations_version", 0),
                        "manual_consumer_available": status.get("manual_consumer_available", False),
                        "manual_operator_id": status.get("manual_operator_id"),
                        "readiness": status.get("readiness"),
                    }
                }

                # Chỉ gửi mảng điểm path khi client mới vào hoặc khi đường đi thay đổi
                if ws not in last_sent_path_versions or last_sent_path_versions[ws] != current_path_version:
                    raw_path = adapter.get_path()
                    payload["path"] = raw_path if raw_path is not None else []
                    last_sent_path_versions[ws] = current_path_version

                # Dành riêng cho Admin đã đăng nhập (alerts và nhật ký sự kiện vận hành)
                if user.role == UserRole.ADMIN:
                    admin_payload: Dict[str, Any] = {
                        "alerts": alerts or adapter.get_alerts()
                    }
                    curr_events_ver = getattr(adapter, "get_events_version", lambda: event_logger.version)()
                    if ws not in last_sent_event_versions or last_sent_event_versions[ws] != curr_events_ver:
                        admin_payload["events"] = getattr(adapter, "get_operational_events", lambda limit=100: event_logger.get_events(limit))(100)
                        admin_payload["events_version"] = curr_events_ver
                        admin_payload["events_started_at"] = getattr(adapter, "get_events_started_at", lambda: event_logger.started_at)()
                        last_sent_event_versions[ws] = curr_events_ver

                    payload["admin_data"] = admin_payload

                try:
                    await ws.send_json(payload)
                except Exception:
                    pass

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Lỗi trong vòng lặp Telemetry Broadcaster: {e}")
            await asyncio.sleep(1.0)
