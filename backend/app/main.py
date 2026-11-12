import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, status
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .adapters.factory import get_robot_adapter
from .auth.dependencies import authenticate_ws_token
from .ws.manager import ws_manager
from .ws.broadcaster import telemetry_broadcaster_loop
from .api.auth_router import router as auth_router
from .api.robot_router import router as robot_router
from .ros_config import get_ros_config

# Thiết lập logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("backend_main")

@asynccontextmanager
async def lifespan(app: FastAPI):
    ros_cfg = get_ros_config()
    logger.info(
        f"Khởi động Airport Guide Backend (Môi trường: {settings.APP_ENV}, "
        f"Adapter: {settings.ROBOT_ADAPTER_MODE}, Profile: {ros_cfg.active_profile.upper()})..."
    )
    # 1. Khởi tạo Robot Adapter singleton
    adapter = get_robot_adapter()

    # 2. Khởi chạy Telemetry Broadcaster Task chạy nền
    broadcaster_task = asyncio.create_task(telemetry_broadcaster_loop())

    yield

    # Shutdown
    logger.info("Đang tắt Airport Guide Backend...")
    broadcaster_task.cancel()
    try:
        await broadcaster_task
    except asyncio.CancelledError:
        pass
    adapter.dispose()
    logger.info("Hệ thống Backend đã dừng hoàn toàn.")

app = FastAPI(
    title="Airport Guide Robot API",
    description="Backend REST API và WebSocket cho Robot Dẫn đường Sân bay (ROS 2 Jazzy)",
    version="1.0.0",
    lifespan=lifespan
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Đăng ký các router REST
app.include_router(auth_router)
app.include_router(robot_router)

@app.get("/api/health")
async def health_check():
    """Kiểm tra tình trạng sẵn sàng của Backend và cấu hình ROS hiện hành"""
    adapter = get_robot_adapter()
    robot_status = adapter.get_status()
    ros_cfg = get_ros_config()
    return {
        "status": "healthy",
        "app_env": settings.APP_ENV,
        "adapter_mode": settings.ROBOT_ADAPTER_MODE,
        "active_profile": ros_cfg.active_profile,
        "ros_domain_id": ros_cfg.ros_domain_id,
        "use_sim_time": ros_cfg.use_sim_time,
        "robot_connected": robot_status.get("is_connected", False),
        "active_ws_clients": len(ws_manager.active_connections)
    }

# Endpoint WebSocket Telemetry
@app.websocket("/ws")
async def websocket_telemetry_endpoint(
    websocket: WebSocket,
    token: Optional[str] = Query(None)
):
    """
    WebSocket Telemetry Endpoint:
    - Nếu có token Admin: giải mã và cấp quyền Admin để nhận alerts và điều khiển.
    - Nếu không có token: tự động cấp quyền Hành khách (PASSENGER) công khai.
    """
    user = authenticate_ws_token(token)
    await ws_manager.connect(websocket, user)

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")

            # Ping-pong giữ kết nối
            if msg_type == "ping":
                await websocket.send_json({"type": "pong", "time": int(asyncio.get_event_loop().time() * 1000)})
            elif msg_type == "authenticate":
                # Nâng cấp quyền khi người dùng đăng nhập Admin từ giao diện
                new_token = data.get("token")
                new_user = authenticate_ws_token(new_token)
                await ws_manager.connect(websocket, new_user)
    except WebSocketDisconnect:
        await ws_manager.disconnect(websocket)
    except Exception as e:
        logger.warning(f"Lỗi phiên WebSocket: {e}")
        await ws_manager.disconnect(websocket)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.BACKEND_HOST,
        port=settings.BACKEND_PORT,
        workers=1,
        reload=settings.APP_ENV == "development"
    )
