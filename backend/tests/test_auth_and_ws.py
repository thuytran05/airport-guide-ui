import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.auth.security import create_access_token
from app.coordinate.transform import MapMetadata, ros_to_canvas_pose, canvas_to_ros_pose

@pytest.mark.anyio
async def test_health_check():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/health")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "healthy"
        assert data["active_profile"] in ("sim", "real")
        assert "spin_thread_alive" in data
        assert "robot_connected" in data

@pytest.mark.anyio
async def test_passenger_and_admin_permissions():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Khách vãng lai (Passenger không cần đăng nhập)
        res = await client.get("/api/robot/status")
        assert res.status_code == 200
        assert "control_mode" in res.json()

        res = await client.get("/api/robot/destinations")
        assert res.status_code == 200
        assert isinstance(res.json(), list)

        # 2. Khách vãng lai gọi Voice Trigger
        res = await client.post("/api/robot/voice/start")
        assert res.status_code == 200
        assert res.json()["success"] is True

        # 3. Khách vãng lai gọi endpoint Admin (POST /api/robot/control/manual) -> Bị từ chối 403 Forbidden
        res = await client.post("/api/robot/control/manual", json={"enable": True})
        assert res.status_code == 403

        # 4. Đăng nhập sai tài khoản admin -> 401
        res = await client.post("/api/auth/login", json={"username": "admin", "password": "wrongpassword"})
        assert res.status_code == 401

        # 5. Đăng nhập đúng tài khoản Admin
        res = await client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        assert res.status_code == 200
        admin_token = res.json()["access_token"]
        assert res.json()["user"]["role"] == "admin"
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        # 6. Admin gọi chuyển manual -> 200 OK
        res = await client.post("/api/robot/control/manual", json={"enable": True}, headers=admin_headers)
        assert res.status_code == 200
        assert res.json()["success"] is True

        # 7. Admin gửi vận tốc cmd_vel_manual -> 200 OK
        res = await client.post(
            "/api/robot/control/velocity",
            json={"linear_x": 0.2, "angular_z": 0.1},
            headers=admin_headers
        )
        assert res.status_code == 200

        # Trả lại AUTO
        await client.post("/api/robot/control/manual", json={"enable": False}, headers=admin_headers)

@pytest.mark.anyio
async def test_session_expiry_and_token_validation():
    expired_token = create_access_token(
        data={"sub": "usr-admin-01", "username": "admin", "role": "admin"},
        expires_delta_seconds=-10
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {expired_token}"})
        assert res.status_code == 401

def test_coordinate_transforms():
    meta = MapMetadata(
        resolution=0.05,
        width=800,
        height=500,
        origin_x=-20.0,
        origin_y=-12.5,
        origin_yaw=0.0
    )
    canvas_pose = ros_to_canvas_pose(0.0, 0.0, 0.0, meta)
    assert canvas_pose["x"] == 400.0
    assert canvas_pose["y"] == 250.0

    ros_pose = canvas_to_ros_pose(400.0, 250.0, 0.0, meta)
    assert abs(ros_pose["x"] - 0.0) < 0.01
    assert abs(ros_pose["y"] - 0.0) < 0.01

def test_sensitive_data_filter_redacts_tokens():
    import logging
    from app.main import SensitiveDataFilter
    f = SensitiveDataFilter()
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg='GET /ws?token=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIn0 HTTP/1.1 101',
        args=(),
        exc_info=None
    )
    res = f.filter(record)
    assert res is True
    assert "token=***REDACTED***" in record.msg
    assert "eyJ" not in record.msg

@pytest.mark.anyio
async def test_expired_token_handling_in_map_endpoint():
    expired_token = create_access_token(
        data={"sub": "usr-admin-01", "username": "admin", "role": "admin"},
        expires_delta_seconds=-10
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Gửi token hết hạn -> 401
        res = await client.get("/api/robot/map", headers={"Authorization": f"Bearer {expired_token}"})
        assert res.status_code == 401

        # Tạo session hành khách hợp lệ -> X-Passenger-Token
        sess_res = await client.post("/api/auth/session")
        assert sess_res.status_code == 200
        p_token = sess_res.json()["session_token"]

        # Với X-Passenger-Token hợp lệ, không bị lỗi 401 (trả về 200 hoặc 404 tùy adapter nạp map)
        res2 = await client.get("/api/robot/map", headers={"X-Passenger-Token": p_token})
        assert res2.status_code in (200, 404)

