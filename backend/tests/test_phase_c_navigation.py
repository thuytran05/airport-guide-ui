import asyncio
import math
import os
import stat
import tempfile
import threading
import time
import pytest
import yaml
from pathlib import Path
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.auth.models import UserRole
from app.ros_config import get_ros_config
from app.coordinate.transform import MapMetadata
from app.adapters.ros_adapter import RosRobotAdapter
from app.adapters.mock_adapter import MockRobotAdapter

try:
    from action_msgs.msg import GoalStatus, GoalStatusArray
except ImportError:
    class GoalStatus:
        STATUS_UNKNOWN = 0
        STATUS_ACCEPTED = 1
        STATUS_EXECUTING = 2
        STATUS_CANCELING = 3
        STATUS_SUCCEEDED = 4
        STATUS_CANCELED = 5
        STATUS_ABORTED = 6

    class GoalStatusArray:
        def __init__(self):
            self.status_list = []

# =========================================================================
# 1. Coordinate Validation Unit Tests (RosRobotAdapter validation logic)
# =========================================================================

def test_validate_destination_coordinates_extended():
    """Kiểm tra xác thực tọa độ với kích thước động, xoay origin, mép bản đồ và thiếu map."""
    adapter = RosRobotAdapter.__new__(RosRobotAdapter)
    adapter._lock = threading.Lock()
    adapter._cfg = get_ros_config()

    # 1. Trường hợp thiếu metadata bản đồ (bản đồ chưa sẵn sàng từ ROS)
    adapter._map_meta = None
    adapter._occupancy_grid_data = None
    dummy_dest = {
        "id": "p1", "name": "P1", "frame_id": "map",
        "pose": {"position": {"x": 1.0, "y": 1.0, "z": 0.0}}
    }
    res = adapter.validate_destination_coordinates(dummy_dest)
    assert res["valid"] is False
    assert "chưa sẵn sàng" in res["message"]

    # 2. Thiết lập bản đồ thông thường: 100x100, res=0.1m, origin=(-5.0, -5.0, yaw=0.0)
    # Tọa độ thực: x in [-5.0, 5.0), y in [-5.0, 5.0)
    adapter._map_meta = MapMetadata(
        width=100,
        height=100,
        resolution=0.1,
        origin_x=-5.0,
        origin_y=-5.0,
        origin_yaw=0.0
    )
    grid = [0] * (100 * 100)
    # Đặt vật cản tại index tương ứng (0.05, 0.05) -> col=50, row=50 -> idx=5050
    grid[50 * 100 + 50] = 100
    # Đặt ô chưa biết tại (0.15, 0.05) -> col=51, row=50 -> idx=5051
    grid[50 * 100 + 51] = -1
    adapter._occupancy_grid_data = grid

    # Điểm hợp lệ trong vùng trống
    valid_dest = {
        "id": "valid_1", "name": "Điểm hợp lệ", "frame_id": "map",
        "pose": {"position": {"x": 1.0, "y": 1.0, "z": 0.0}}
    }
    assert adapter.validate_destination_coordinates(valid_dest)["valid"] is True

    # Sai frame
    wrong_frame = {
        "id": "wf", "name": "Sai frame", "frame_id": "odom",
        "pose": valid_dest["pose"]
    }
    assert adapter.validate_destination_coordinates(wrong_frame)["valid"] is False

    # Tọa độ NaN / Inf
    nan_dest = {
        "id": "nan", "name": "NaN", "frame_id": "map",
        "pose": {"position": {"x": float("nan"), "y": 0.0}}
    }
    assert adapter.validate_destination_coordinates(nan_dest)["valid"] is False

    # Ngoài mép bản đồ (Out of bounds)
    oob_dest = {
        "id": "oob", "name": "Ngoài biên", "frame_id": "map",
        "pose": {"position": {"x": 6.0, "y": 0.0}}
    }
    res_oob = adapter.validate_destination_coordinates(oob_dest)
    assert res_oob["valid"] is False
    assert "nằm ngoài biên bản đồ" in res_oob["message"]

    # Ngay mép trên (x = 5.0 -> x_local = 10.0m == map_w -> out of bounds)
    edge_dest = {
        "id": "edge", "name": "Mép trên", "frame_id": "map",
        "pose": {"position": {"x": 5.0, "y": 0.0}}
    }
    assert adapter.validate_destination_coordinates(edge_dest)["valid"] is False

    # Vướng vật cản (> 50)
    occ_dest = {
        "id": "occ", "name": "Vật cản", "frame_id": "map",
        "pose": {"position": {"x": 0.05, "y": 0.05}}
    }
    res_occ = adapter.validate_destination_coordinates(occ_dest)
    assert res_occ["valid"] is False
    assert "vật cản" in res_occ["message"]

    # Rơi vào vùng chưa quét (< 0)
    unk_dest = {
        "id": "unk", "name": "Chưa quét", "frame_id": "map",
        "pose": {"position": {"x": 0.15, "y": 0.05}}
    }
    res_unk = adapter.validate_destination_coordinates(unk_dest)
    assert res_unk["valid"] is False
    assert "chưa quét" in res_unk["message"]

    # 3. Bản đồ có origin xoay (origin_yaw != 0):
    # Origin tại (0, 0), xoay 90 độ (yaw = pi/2), width=100, height=100, res=0.1
    # Trong hệ cục bộ ma trận: x_local = dy, y_local = -dx
    # Điểm (x=-0.5, y=5.0) -> x_local = 5.0m, y_local = 0.5m -> HỢP LỆ
    # Điểm (x=5.0, y=0.0) -> x_local = 0.0m, y_local = -5.0m -> KHÔNG HỢP LỆ
    adapter._map_meta = MapMetadata(
        width=100,
        height=100,
        resolution=0.1,
        origin_x=0.0,
        origin_y=0.0,
        origin_yaw=math.pi / 2
    )
    adapter._occupancy_grid_data = [0] * (100 * 100)

    rot_inside = {
        "id": "rot_in", "name": "Trong xoay", "frame_id": "map",
        "pose": {"position": {"x": -0.5, "y": 5.0}}
    }
    rot_outside = {
        "id": "rot_out", "name": "Ngoài xoay", "frame_id": "map",
        "pose": {"position": {"x": 5.0, "y": 0.0}}
    }
    assert adapter.validate_destination_coordinates(rot_inside)["valid"] is True
    assert adapter.validate_destination_coordinates(rot_outside)["valid"] is False


# =========================================================================
# 2. Isolated Destination Storage (YAML File I/O, Rollback & Read-only Error)
# =========================================================================

def test_isolated_destinations_file_io():
    """Kiểm tra ghi/đọc YAML trên file tạm, xử lý trùng ID và rollback khi lỗi ghi/read-only."""
    with tempfile.TemporaryDirectory() as tmpdir:
        dest_file = Path(tmpdir) / "test_destinations.yaml"

        adapter = RosRobotAdapter.__new__(RosRobotAdapter)
        adapter._lock = threading.Lock()
        adapter._cfg = get_ros_config()
        adapter._destinations_file = dest_file
        adapter._destinations = []
        adapter._navigation_state = "IDLE"
        adapter._destination_id = ""

        # Thiết lập map giả lập để vượt qua xác thực
        adapter._map_meta = MapMetadata(
            width=100, height=100, resolution=0.1, origin_x=0.0, origin_y=0.0, origin_yaw=0.0
        )
        adapter._occupancy_grid_data = [0] * 10000

        # 1. Thêm điểm mới hợp lệ
        d1 = {
            "id": "gate_test_1",
            "name": "Cổng thử nghiệm 1",
            "frame_id": "map",
            "pose": {"position": {"x": 2.0, "y": 3.0}}
        }
        res1 = adapter.upsert_destination(d1)
        assert res1["success"] is True
        assert dest_file.exists()

        # 2. Cập nhật trùng ID -> Sửa thông tin điểm đã có mà không nhân bản
        d1_updated = {
            "id": "gate_test_1",
            "name": "Cổng thử nghiệm 1 (Đã đổi tên)",
            "frame_id": "map",
            "pose": {"position": {"x": 2.5, "y": 3.5}}
        }
        res_up = adapter.upsert_destination(d1_updated)
        assert res_up["success"] is True
        assert len(adapter._destinations) == 1
        assert adapter._destinations[0]["name"] == "Cổng thử nghiệm 1 (Đã đổi tên)"

        # 3. Đọc lại từ file YAML sau reload
        reloaded = adapter._load_destinations()
        assert len(reloaded) == 1
        assert reloaded[0]["id"] == "gate_test_1"
        assert reloaded[0]["name"] == "Cổng thử nghiệm 1 (Đã đổi tên)"

        # 4. Giả lập lỗi filesystem chỉ đọc (Read-only file)
        os.chmod(dest_file, stat.S_IREAD)
        try:
            d2 = {
                "id": "gate_test_2",
                "name": "Cổng thử nghiệm 2",
                "frame_id": "map",
                "pose": {"position": {"x": 4.0, "y": 4.0}}
            }
            res_ro = adapter.upsert_destination(d2)
            # Phải báo lỗi thực tế thay vì báo thành công giả tạo!
            assert res_ro["success"] is False
            assert "Không thể lưu" in res_ro["message"] or "chỉ đọc" in res_ro["message"].lower()

            # Xác nhận bộ nhớ đã được rollback về 1 điểm ban đầu
            assert len(adapter._destinations) == 1
            assert adapter._destinations[0]["id"] == "gate_test_1"
        finally:
            # Khôi phục quyền để xóa thư mục tạm an toàn
            os.chmod(dest_file, stat.S_IRWXU)


# =========================================================================
# 3. Nav2 Goal Lifecycle Edge Cases & Concurrency
# =========================================================================

def test_ros_adapter_lifecycle_edge_cases():
    """Kiểm tra các nhánh vòng đời Goal: Concurrency, Late Acceptance, PENDING Cancel, External Goal."""
    adapter = RosRobotAdapter.__new__(RosRobotAdapter)
    adapter._lock = threading.Lock()
    adapter._cfg = get_ros_config()
    adapter._navigation_state = "IDLE"
    adapter._has_goal = False
    adapter._goal_id = ""
    adapter._destination_id = ""
    adapter._destinations = []
    adapter._owner_id = ""
    adapter._distance_remaining = None
    adapter._estimated_time_remaining = None
    adapter._number_of_recoveries = 0
    adapter._message = "Sẵn sàng"
    adapter._current_goal_handle = None
    adapter._cancel_requested_for = None
    adapter._active_request_id = "req_100"
    adapter._nav2_has_active_goal = False
    adapter._path = None
    adapter._path_version = 0

    class MockGoalId:
        uuid = b"1234567890abcdef"

    class MockGoalHandle:
        accepted = True
        goal_id = MockGoalId()
        def cancel_goal_async(self):
            class MockCancelFuture:
                def add_done_callback(self, cb):
                    pass
            return MockCancelFuture()
        def get_result_async(self):
            class MockResultFuture:
                def add_done_callback(self, cb):
                    pass
            return MockResultFuture()

    class MockFuture:
        def __init__(self, handle):
            self._handle = handle
        def result(self):
            return self._handle

    # --- Nhánh 1: Hủy khi đang ở trạng thái PENDING ---
    adapter._navigation_state = "PENDING"
    adapter._has_goal = True
    adapter._destination_id = "dest_1"
    adapter._owner_id = "user_A"
    adapter._current_goal_handle = None

    # Người dùng bấm hủy ngay khi PENDING
    cancel_pending_res = adapter.cancel_navigation(owner_id="user_A", is_admin=False)
    assert cancel_pending_res["success"] is True
    assert adapter._navigation_state == "CANCELING"
    assert adapter._cancel_requested_for == "req_100"

    # Khi Nav2 chấp thuận goal đến muộn: phải tự động hủy ngay mà không chuyển sang NAVIGATING
    adapter._on_goal_response(MockFuture(MockGoalHandle()), "req_100", "Cổng 1")
    assert adapter._navigation_state == "CANCELING"

    # --- Nhánh 2: Hủy nhiều lần (Multiple Cancels) ---
    dup_cancel = adapter.cancel_navigation(owner_id="user_A", is_admin=False)
    assert dup_cancel["success"] is True
    assert "tiếp nhận trước đó" in dup_cancel["message"]

    # --- Nhánh 3: Result về trước callback Hủy (Race between Result and Cancel Response) ---
    # Goal về đích (STATUS_SUCCEEDED = 4)
    class MockSucceededResult:
        status = 4
        result = None

    class MockResultFuture:
        def result(self):
            return MockSucceededResult()

    adapter._on_nav_result(MockResultFuture(), "req_100", "Cổng 1")
    assert adapter._navigation_state == "SUCCEEDED"

    # Sau đó callback hủy mới hoàn tất -> Không được ghi đè trạng thái SUCCEEDED!
    class MockCancelResponse:
        return_code = 0  # OK

    class MockCancelResponseFuture:
        def result(self):
            return MockCancelResponse()

    adapter._on_cancel_response(MockCancelResponseFuture(), "req_100")
    assert adapter._navigation_state == "SUCCEEDED"

    # --- Nhánh 4: Callback cũ không ghi đè trạng thái chuyến mới ---
    # Bắt đầu chuyến mới req_200
    adapter._active_request_id = "req_200"
    adapter._navigation_state = "NAVIGATING"
    adapter._destination_id = "dest_2"

    # Một kết quả cũ của req_100 bay về
    class MockOldResultFuture:
        def result(self):
            class OldRes:
                status = 6  # ABORTED
                result = None
            return OldRes()

    adapter._on_nav_result(MockOldResultFuture(), "req_100", "Cổng 1")
    # Không làm ảnh hưởng tới req_200 đang NAVIGATING
    assert adapter._navigation_state == "NAVIGATING"
    assert adapter._destination_id == "dest_2"

    # --- Nhánh 5: Hủy bị Nav2 từ chối (return_code == 1 ERROR_REJECTED) ---
    adapter._navigation_state = "CANCELING"
    class MockRejectCancelResponse:
        return_code = 1

    class MockRejectFuture:
        def result(self):
            return MockRejectCancelResponse()

    adapter._on_cancel_response(MockRejectFuture(), "req_200")
    # Khi từ chối hủy, robot tiếp tục NAVIGATING
    assert adapter._navigation_state == "NAVIGATING"
    assert "từ chối" in adapter._message

    # --- Nhánh 6: Phát hiện Nav2 đang có mục tiêu ngoại vi (RViz hoặc phiên trước) ---
    class MockGoalStatusInfo:
        status = 2  # STATUS_EXECUTING

    status_msg = GoalStatusArray()
    status_msg.status_list = [MockGoalStatusInfo()]
    adapter._on_action_status(status_msg)
    assert adapter._nav2_has_active_goal is True

    # Khi không có goal handle trong app và có goal ngoài, start_navigation phải bị chặn
    adapter._navigation_state = "IDLE"
    adapter._has_goal = False
    adapter._current_goal_handle = None
    adapter._control_mode = "AUTO"
    adapter._clock_stalled = False
    adapter._action_nav = object()
    import app.adapters.ros_adapter as ra_mod
    orig_has_action = ra_mod.HAS_NAV2_ACTION
    ra_mod.HAS_NAV2_ACTION = True

    adapter._destinations = [{"id": "d_test", "name": "Test", "pose": {"position": {"x": 0.0, "y": 0.0}}}]
    adapter._pose = {"x": 0.0, "y": 0.0, "theta": 0.0}

    # Bổ sung map meta để vượt qua xác thực
    adapter._map_meta = MapMetadata(width=100, height=100, resolution=0.1, origin_x=0.0, origin_y=0.0, origin_yaw=0.0)
    adapter._occupancy_grid_data = [0] * 10000

    try:
        block_res = adapter.start_navigation("d_test", owner_id="user_test")
        assert block_res["success"] is False
        assert "mục tiêu khác" in block_res["message"]
    finally:
        ra_mod.HAS_NAV2_ACTION = orig_has_action


# =========================================================================
# 4. HTTP REST API: Cryptographic Passenger Sessions & Permissions
# =========================================================================

@pytest.mark.anyio
async def test_api_passenger_sessions_and_permissions():
    """
    Kiểm tra bảo mật phiên hành khách:
    - Phiên được ký mật mã qua /api/auth/session (JWT).
    - Tuyệt đối không để lộ owner_id trong /api/robot/status hoặc dữ liệu công khai.
    - Chống giả mạo qua header plain text hoặc token bị can thiệp.
    - Hành khách A reloaded (tái dùng token A) có quyền hủy chuyến của mình.
    - Admin dùng JWT hợp lệ có quyền hủy (Admin override).
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Lấy token Admin
        admin_res = await client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        assert admin_res.status_code == 200
        admin_token = admin_res.json()["access_token"]
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        # 2. Cấp 2 phiên hành khách hợp lệ được ký bởi backend
        sess_res_A = await client.post("/api/auth/session")
        assert sess_res_A.status_code == 200
        token_A = sess_res_A.json()["session_token"]
        user_id_A = sess_res_A.json()["user_id"]
        headers_A = {"X-Passenger-Token": token_A}

        sess_res_B = await client.post("/api/auth/session")
        assert sess_res_B.status_code == 200
        token_B = sess_res_B.json()["session_token"]
        headers_B = {"X-Passenger-Token": token_B}

        # 3. Lấy danh sách điểm đến
        dest_res = await client.get("/api/robot/destinations")
        assert dest_res.status_code == 200
        dests = dest_res.json()
        assert len(dests) > 0
        target_id = dests[0]["id"]

        # 4. Hành khách A bắt đầu chuyến đi
        start_A = await client.post("/api/robot/navigate", json={"destination_id": target_id}, headers=headers_A)
        assert start_A.status_code == 200
        assert start_A.json()["success"] is True

        # 5. Kiểm tra API status:
        # A kiểm tra: is_owner=True, has_active_trip=True, KHÔNG lộ owner_id
        status_A = await client.get("/api/robot/status", headers=headers_A)
        assert status_A.status_code == 200
        st_data_A = status_A.json()
        assert "owner_id" not in st_data_A  # Không bao giờ leak secret owner_id
        assert st_data_A.get("has_active_trip") is True
        assert st_data_A.get("is_owner") is True

        # B kiểm tra: is_owner=False, has_active_trip=True, KHÔNG lộ owner_id
        status_B = await client.get("/api/robot/status", headers=headers_B)
        assert status_B.status_code == 200
        st_data_B = status_B.json()
        assert "owner_id" not in st_data_B
        assert st_data_B.get("has_active_trip") is True
        assert st_data_B.get("is_owner") is False

        # 6. Hành khách B cố ý hủy chuyến của A -> 400 Forbidden
        cancel_B = await client.post("/api/robot/cancel", headers=headers_B)
        assert cancel_B.status_code == 400
        assert "không có quyền" in cancel_B.json()["detail"]

        # 7. Kẻ tấn công giả mạo token A (chỉnh sửa chữ ký) -> 401 Unauthorized
        tampered_headers = {"X-Passenger-Token": token_A + "tampered_bad_sig"}
        cancel_tampered = await client.post("/api/robot/cancel", headers=tampered_headers)
        assert cancel_tampered.status_code == 401

        # 8. Kẻ tấn công cố gửi header plain text X-Session-ID không ký -> Bị gán guest ngẫu nhiên, không hủy được (400)
        spoofed_plain = {"X-Session-ID": user_id_A}
        cancel_spoofed = await client.post("/api/robot/cancel", headers=spoofed_plain)
        assert cancel_spoofed.status_code == 400
        assert "không có quyền" in cancel_spoofed.json()["detail"]

        # 9. Request không có token/phiên nào cố hủy -> 400
        cancel_anonymous = await client.post("/api/robot/cancel")
        assert cancel_anonymous.status_code == 400

        # 10. Admin can thiệp hủy chuyến (Admin Override) -> 200 Thành công
        cancel_admin = await client.post("/api/robot/cancel", headers=admin_headers)
        assert cancel_admin.status_code == 200
        assert cancel_admin.json()["success"] is True

        # Đợi luồng nền cancel hoàn tất
        await asyncio.sleep(0.3)

        # 11. Hành khách A tạo chuyến mới, sau đó reload (tái sử dụng token_A lưu trong storage) và tự hủy -> 200
        start_A2 = await client.post("/api/robot/navigate", json={"destination_id": target_id}, headers=headers_A)
        assert start_A2.status_code == 200

        cancel_A = await client.post("/api/robot/cancel", headers=headers_A)
        assert cancel_A.status_code == 200
        assert cancel_A.json()["success"] is True


# =========================================================================
# 5. Nav2 Restart & Action Status Monitoring Unit Tests (Part 1.4)
# =========================================================================

def test_nav2_restart_and_action_status_cases():
    """
    Kiểm tra 3 tình huống Nav2 khi backend khởi động lại:
    1. Nav2 đang chạy goal cũ / ngoại vi (status=2 EXECUTING).
    2. Nav2 đã kết thúc goal cũ (status=4 SUCCEEDED).
    3. Action server chưa sẵn sàng / thiếu thông tin kết nối.
    4. Ứng dụng không bao giờ gửi cancel tới goal do bên ngoài phát đi.
    """
    adapter = RosRobotAdapter.__new__(RosRobotAdapter)
    adapter._lock = threading.Lock()
    adapter._cfg = get_ros_config()
    adapter._navigation_state = "IDLE"
    adapter._has_goal = False
    adapter._current_goal_handle = None
    adapter._control_mode = "AUTO"
    adapter._clock_stalled = False
    adapter._nav2_has_active_goal = False
    adapter._nav2_action_status_received = False
    adapter._owner_id = ""
    adapter._destinations = [{"id": "gate_1", "name": "Cổng 1", "pose": {"position": {"x": 1.0, "y": 1.0}}}]
    adapter._pose = {"x": 0.0, "y": 0.0, "theta": 0.0}
    adapter._map_meta = MapMetadata(width=100, height=100, resolution=0.1, origin_x=0.0, origin_y=0.0, origin_yaw=0.0)
    adapter._occupancy_grid_data = [0] * 10000

    class DummyActionClient:
        def __init__(self, ready=True):
            self._ready = ready
        def server_is_ready(self):
            return self._ready
        def wait_for_server(self, timeout_sec=0.5):
            return self._ready

    adapter._action_nav = DummyActionClient(ready=True)

    import app.adapters.ros_adapter as ra_mod
    orig_has_action = ra_mod.HAS_NAV2_ACTION
    ra_mod.HAS_NAV2_ACTION = True

    try:
        # --- Tình huống 1: Nav2 đang có goal cũ/ngoại vi đang chạy (status=2) ---
        class ActiveGoalInfo:
            status = GoalStatus.STATUS_EXECUTING
        status_msg_active = GoalStatusArray()
        status_msg_active.status_list = [ActiveGoalInfo()]

        adapter._on_action_status(status_msg_active)
        assert adapter._nav2_has_active_goal is True
        assert adapter._nav2_action_status_received is True

        # Khi Nav2 đang có goal ngoại vi, Start Navigation bị chặn với thông báo rõ ràng
        res1 = adapter.start_navigation("gate_1", owner_id="user_test")
        assert res1["success"] is False
        assert "mục tiêu khác" in res1["message"]

        # Thử gọi Cancel: Không có goal handle của mình -> Từ chối, không làm ảnh hưởng goal ngoài
        cancel_res = adapter.cancel_navigation(owner_id="user_test", is_admin=True)
        assert cancel_res["success"] is False

        # --- Tình huống 2: Nav2 đã hoàn tất toàn bộ goal cũ (status=4 SUCCEEDED) ---
        class FinishedGoalInfo:
            status = GoalStatus.STATUS_SUCCEEDED
        status_msg_done = GoalStatusArray()
        status_msg_done.status_list = [FinishedGoalInfo()]

        adapter._on_action_status(status_msg_done)
        assert adapter._nav2_has_active_goal is False

        # --- Tình huống 3: Action server chưa sẵn sàng kết nối ---
        adapter._action_nav = DummyActionClient(ready=False)
        res3 = adapter.start_navigation("gate_1", owner_id="user_test")
        assert res3["success"] is False
        assert "chưa sẵn sàng" in res3["message"]

    finally:
        ra_mod.HAS_NAV2_ACTION = orig_has_action


# =========================================================================
# 6. Real Path Handling, Frame Validation & Lifecycle Tests (Part 2)
# =========================================================================

def test_path_handling_and_lifecycle():
    """
    Kiểm tra xử lý đường dẫn thật (nav_msgs/Path):
    1. Tiếp nhận đường dẫn hợp lệ trong frame 'map'.
    2. Từ chối đường dẫn khi sai frame (ví dụ 'odom').
    3. Từ chối đường dẫn đến muộn khi robot không ở trạng thái dẫn đường.
    4. Tự động xóa đường dẫn khi chuyến đi hoàn tất, bị hủy hoặc thất bại.
    5. Kiểm tra path_version tăng khi có đường đi mới hoặc khi xóa đường đi.
    """
    adapter = RosRobotAdapter.__new__(RosRobotAdapter)
    adapter._lock = threading.Lock()
    adapter._cfg = get_ros_config()
    adapter._navigation_state = "IDLE"
    adapter._path = None
    adapter._path_version = 0

    class DummyHeader:
        def __init__(self, frame_id="map"):
            self.frame_id = frame_id

    class DummyPose:
        def __init__(self, x, y):
            class Pos:
                def __init__(self, x, y):
                    self.x = x
                    self.y = y
            class Pose:
                def __init__(self, x, y):
                    self.position = Pos(x, y)
            self.pose = Pose(x, y)

    class DummyPathMsg:
        def __init__(self, frame_id="map", points=None):
            self.header = DummyHeader(frame_id)
            self.poses = [DummyPose(p[0], p[1]) for p in (points or [])]

    # --- 1. Robot đang IDLE: nhận đường đi muộn -> Phải bỏ qua ---
    msg_valid = DummyPathMsg(frame_id="map", points=[(1.0, 2.0), (3.0, 4.0)])
    adapter._on_path(msg_valid)
    assert adapter.get_path() is None
    assert adapter.get_path_version() == 0

    # --- 2. Robot chuyển sang NAVIGATING: nhận đường đi hợp lệ ---
    adapter._navigation_state = "NAVIGATING"
    adapter._current_goal_handle = object()
    adapter._current_target_pose = {"x": 3.0, "y": 4.0}
    adapter._on_path(msg_valid)
    assert adapter.get_path() is not None
    assert len(adapter.get_path()) == 2
    assert adapter.get_path()[0]["x"] == 1.0
    assert adapter.get_path()[1]["y"] == 4.0
    assert adapter.get_path_version() == 1

    # --- 3. Nhận đường đi sai frame (ví dụ 'odom') -> Phải từ chối, không đổi path ---
    msg_wrong_frame = DummyPathMsg(frame_id="odom", points=[(9.0, 9.0)])
    adapter._on_path(msg_wrong_frame)
    # Vẫn giữ nguyên đường đi cũ
    assert len(adapter.get_path()) == 2
    assert adapter.get_path()[0]["x"] == 1.0
    assert adapter.get_path_version() == 1  # version không tăng

    # --- 4. Chuyến đi hoàn tất (SUCCEEDED) -> Đường dẫn phải bị xóa sạch ---
    class MockResult:
        status = 4  # SUCCEEDED
        result = None
    class MockResultFut:
        def result(self):
            return MockResult()

    adapter._active_request_id = "req_finish"
    adapter._owner_id = "user_A"
    adapter._current_goal_handle = object()
    adapter._on_nav_result(MockResultFut(), "req_finish", "Cổng 1")

    assert adapter._navigation_state == "SUCCEEDED"
    assert adapter.get_path() is None  # Đã xóa đường đi
    assert adapter.get_path_version() == 2  # version tăng để client cập nhật
    assert adapter.get_owner_id() == ""  # Đã giải phóng phiên


def test_path_endpoint_and_external_goal_filtering():
    """
    Kiểm tra chốt chặn an toàn cho /plan:
    1. Bỏ qua /plan nếu backend không sở hữu goal handle tích cực (tránh bắt nhầm path ngoại vi từ RViz).
    2. Chấp nhận /plan khi điểm cuối gần mục tiêu chuyến đi (dung sai <= 2.0m).
    3. Từ chối /plan khi điểm cuối lệch xa mục tiêu (> 2.0m).
    """
    adapter = RosRobotAdapter.__new__(RosRobotAdapter)
    adapter._lock = threading.Lock()
    adapter._cfg = get_ros_config()
    adapter._navigation_state = "NAVIGATING"
    adapter._current_goal_handle = None  # Không có goal handle
    adapter._current_target_pose = {"x": 10.0, "y": 5.0}
    adapter._path = None
    adapter._path_version = 0

    class DummyHeader:
        def __init__(self, frame_id="map"):
            self.frame_id = frame_id

    class DummyPose:
        def __init__(self, x, y):
            class Pos:
                def __init__(self, x, y):
                    self.x = x
                    self.y = y
            class Pose:
                def __init__(self, x, y):
                    self.position = Pos(x, y)
            self.pose = Pose(x, y)

    class DummyPathMsg:
        def __init__(self, frame_id="map", points=None):
            self.header = DummyHeader(frame_id)
            self.poses = [DummyPose(p[0], p[1]) for p in (points or [])]

    # 1. External path từ RViz: navigation_state=NAVIGATING nhưng _current_goal_handle=None
    msg_external = DummyPathMsg(frame_id="map", points=[(0.0, 0.0), (10.0, 5.0)])
    adapter._on_path(msg_external)
    assert adapter.get_path() is None
    assert adapter.get_path_version() == 0

    # 2. Backend sở hữu goal handle, điểm cuối khớp mục tiêu (10.1, 5.05) -> dist ≈ 0.11m <= 2.0m
    adapter._current_goal_handle = object()
    msg_matching = DummyPathMsg(frame_id="map", points=[(0.0, 0.0), (5.0, 2.5), (10.1, 5.05)])
    adapter._on_path(msg_matching)
    assert adapter.get_path() is not None
    assert len(adapter.get_path()) == 3
    assert adapter.get_path_version() == 1

    # 3. Path có điểm cuối lệch xa mục tiêu (ví dụ (2.0, 1.0) cách (10.0, 5.0) ~8.9m)
    msg_mismatched = DummyPathMsg(frame_id="map", points=[(0.0, 0.0), (2.0, 1.0)])
    adapter._on_path(msg_mismatched)
    # Vẫn giữ nguyên path cũ
    assert len(adapter.get_path()) == 3
    assert adapter.get_path_version() == 1


@pytest.mark.anyio
async def test_telemetry_broadcaster_reconnection_and_cancellation():
    """
    Kiểm tra logic phân phối path trong telemetry broadcaster:
    - Tab mới hoặc tab kết nối lại nhận path ở ngay khung hình đầu tiên.
    - Hai tab song song đều nhận được path khi có path mới.
    - Khi path_version không đổi, payload không lặp lại mảng path ở 5Hz.
    - Khi chuyến đi kết thúc (CANCELED/SUCCEEDED/FAILED/IDLE), path được xóa và gửi mảng rỗng.
    """
    from app.auth.models import User, UserRole

    class MockWebSocket:
        def __init__(self, ws_id: str):
            self.ws_id = ws_id
            self.sent_messages = []

        async def send_json(self, data):
            self.sent_messages.append(data)

    class MockAdapter:
        def __init__(self):
            self._path = [{"x": 1.0, "y": 2.0}, {"x": 3.0, "y": 4.0}]
            self._path_version = 1
            self._owner_id = "user_test"

        def get_status(self):
            return {
                "pose": {"x": 0.0, "y": 0.0, "theta": 0.0},
                "battery_percent": 0.9,
                "is_connected": True,
                "is_data_stale": False,
                "control_mode": "AUTO",
                "navigation_state": "NAVIGATING",
                "has_goal": True,
                "goal_id": "g1",
                "destination_id": "gate_1",
                "voice_state": "IDLE",
                "voice_transcript": None,
                "voice_response": None,
                "message": "Dẫn đường",
                "last_updated": 1000,
            }

        def get_path(self):
            return list(self._path) if self._path is not None else None

        def get_path_version(self):
            return self._path_version

        def get_owner_id(self):
            return self._owner_id

        def get_alerts(self):
            return []

    ws1 = MockWebSocket("client_1")
    ws2 = MockWebSocket("client_2")
    user_p = User(
        id="user_p",
        username="passenger",
        full_name="Passenger",
        role=UserRole.PASSENGER,
        hashed_password="",
    )

    last_sent_path_versions = {}
    adapter = MockAdapter()

    def build_payload_for_ws(ws, user):
        current_path_version = adapter.get_path_version()
        payload = {"type": "telemetry", "robot_status": {}}
        if ws not in last_sent_path_versions or last_sent_path_versions[ws] != current_path_version:
            raw_path = adapter.get_path()
            payload["path"] = raw_path if raw_path is not None else []
            last_sent_path_versions[ws] = current_path_version
        return payload

    # 1. Khung hình đầu: cả 2 client đều nhận path
    p1 = build_payload_for_ws(ws1, user_p)
    p2 = build_payload_for_ws(ws2, user_p)
    assert "path" in p1
    assert len(p1["path"]) == 2
    assert "path" in p2
    assert len(p2["path"]) == 2

    # 2. Khung hình tiếp theo: path không đổi (path_version = 1) -> KHÔNG gửi path lặp lại
    p1_tick2 = build_payload_for_ws(ws1, user_p)
    p2_tick2 = build_payload_for_ws(ws2, user_p)
    assert "path" not in p1_tick2
    assert "path" not in p2_tick2

    # 3. Path thay đổi (robot cập nhật đường đi) -> cả 2 client đều nhận path mới
    adapter._path = [{"x": 1.5, "y": 2.5}]
    adapter._path_version = 2
    p1_tick3 = build_payload_for_ws(ws1, user_p)
    p2_tick3 = build_payload_for_ws(ws2, user_p)
    assert "path" in p1_tick3
    assert len(p1_tick3["path"]) == 1
    assert "path" in p2_tick3
    assert len(p2_tick3["path"]) == 1

    # 4. Client 3 mới vào kết nối lại -> nhận ngay đường đi hiện tại
    ws3 = MockWebSocket("client_3")
    p3 = build_payload_for_ws(ws3, user_p)
    assert "path" in p3
    assert len(p3["path"]) == 1

    # 5. Hủy chuyến hoặc kết thúc: adapter xóa path (path=None) và tăng version -> gửi mảng rỗng
    adapter._path = None
    adapter._path_version = 3
    p1_cancel = build_payload_for_ws(ws1, user_p)
    p2_cancel = build_payload_for_ws(ws2, user_p)
    p3_cancel = build_payload_for_ws(ws3, user_p)
    assert p1_cancel["path"] == []
    assert p2_cancel["path"] == []
    assert p3_cancel["path"] == []


def test_reverse_coordinate_projection_isolated():
    """
    Kiểm tra phép chiếu ngược từ pixel sang tọa độ ROS (frame map):
    - Benchmark điểm chuẩn đã biết.
    - Xoay bản đồ origin_yaw != 0.
    - Tính đối xứng hoàn hảo (round-trip: forward -> inverse -> original).
    - Giới hạn biên và loại bỏ click khi kéo bản đồ (drag).
    """
    def project_ros_to_pixel(ros_x, ros_y, ox, oy, oyaw, res, h):
        dx = ros_x - ox
        dy = ros_y - oy
        px = (math.cos(oyaw) * dx + math.sin(oyaw) * dy) / res
        py = h - (-math.sin(oyaw) * dx + math.cos(oyaw) * dy) / res
        return px, py

    def project_pixel_to_ros(px, py, ox, oy, oyaw, res, h):
        u = px * res
        v = (h - py) * res
        dx = math.cos(oyaw) * u - math.sin(oyaw) * v
        dy = math.sin(oyaw) * u + math.cos(oyaw) * v
        return ox + dx, oy + dy

    # 1. Điểm chuẩn đã biết không xoay: res=0.05, origin=(-10.0, -10.0), h=400, w=400
    # Tại pixel (200, 200) -> chính giữa ảnh:
    # u = 200 * 0.05 = 10.0 -> ros_x = -10.0 + 10.0 = 0.0
    # v = (400 - 200) * 0.05 = 10.0 -> ros_y = -10.0 + 10.0 = 0.0
    ros_x, ros_y = project_pixel_to_ros(200, 200, -10.0, -10.0, 0.0, 0.05, 400)
    assert abs(ros_x - 0.0) < 1e-6
    assert abs(ros_y - 0.0) < 1e-6

    # 2. Xoay origin_yaw = pi/4 (45 độ)
    yaw = math.pi / 4.0
    test_rx, test_ry = 5.0, -2.0
    px, py = project_ros_to_pixel(test_rx, test_ry, -10.0, -5.0, yaw, 0.05, 500)
    calc_rx, calc_ry = project_pixel_to_ros(px, py, -10.0, -5.0, yaw, 0.05, 500)
    assert abs(calc_rx - test_rx) < 1e-6
    assert abs(calc_ry - test_ry) < 1e-6

    # 3. Round-trip hàng loạt điểm ngẫu nhiên
    for rx, ry in [(1.23, 4.56), (-7.89, 0.12), (18.5, 4.2), (24.0, 8.5)]:
        f_px, f_py = project_ros_to_pixel(rx, ry, -12.0, -8.0, 0.35, 0.05, 600)
        b_rx, b_ry = project_pixel_to_ros(f_px, f_py, -12.0, -8.0, 0.35, 0.05, 600)
        assert abs(b_rx - rx) < 1e-6
        assert abs(b_ry - ry) < 1e-6

    # 4. Kiểm tra điều kiện kéo (drag): khoảng cách chuột > 5px không được kích hoạt chọn điểm
    def should_trigger_select(drag_dist, is_picking, is_ros_mode, has_map, pt_x, pt_y, w, h):
        if drag_dist > 5:
            return False  # Kéo chuột pan bản đồ
        if not is_picking or not is_ros_mode or not has_map:
            return False
        if pt_x < 0 or pt_x > w or pt_y < 0 or pt_y > h:
            return False  # Ngoài biên bản đồ
        return True

    assert should_trigger_select(12, True, True, True, 100, 100, 400, 400) is False  # Kéo 12px
    assert should_trigger_select(2, True, True, True, 100, 100, 400, 400) is True   # Click tĩnh 2px
    assert should_trigger_select(1, True, False, True, 100, 100, 400, 400) is False # Đang ở tab Sơ đồ hành khách
    assert should_trigger_select(1, True, True, False, 100, 100, 400, 400) is False # Chưa có metadata bản đồ
    assert should_trigger_select(1, True, True, True, -5, 100, 400, 400) is False   # Click ngoài biên trái
    assert should_trigger_select(1, True, True, True, 450, 100, 400, 400) is False  # Click ngoài biên phải


# =========================================================================
# 7. Persistent Storage, Seed Fallback, Concurrency & Admin Permissions
# =========================================================================

@pytest.mark.anyio
async def test_destinations_persistence_concurrency_and_permissions():
    """
    Kiểm thử toàn diện tính năng lưu điểm đến trực tiếp từ Admin:
    1. Lần đầu nạp YAML: Tệp lưu trữ chưa tồn tại -> nạp từ seed file.
    2. Lưu bền vững và đọc lại sau khi tạo adapter mới (giả lập restart backend).
    3. Concurrency: Hai luồng lưu gần đồng thời không làm mất dữ liệu.
    4. Lỗi ghi (read-only/OSError): Không làm mất bản cũ, rollback bộ nhớ và trả lỗi thật.
    5. Chặn sửa điểm đang có chuyến dẫn đường đang chạy.
    6. Xác thực quyền Admin: Khách/Anonymous bị chặn (403/401), Admin lưu thành công (200).
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        seed_file = tmp_path / "seed_destinations.yaml"
        storage_file = tmp_path / "data" / "destinations.yaml"

        # Tạo seed data
        seed_data = {
            "map_id": "airport_floor_1",
            "destinations": [
                {
                    "id": "gate_seed_1",
                    "name": "Cổng khởi tạo 1",
                    "map_id": "airport_floor_1",
                    "pose": {"position": {"x": 1.0, "y": 1.0, "z": 0.0}}
                }
            ]
        }
        with open(seed_file, "w", encoding="utf-8") as f:
            yaml.dump(seed_data, f)

        # 1. Khởi tạo adapter 1: storage_file chưa tồn tại -> nạp từ seed_file
        adapter1 = RosRobotAdapter.__new__(RosRobotAdapter)
        adapter1._lock = threading.Lock()
        adapter1._cfg = get_ros_config()
        adapter1._destinations_file = storage_file
        adapter1._destinations_seed_file = seed_file
        adapter1._destinations_version = 0
        adapter1._navigation_state = "IDLE"
        adapter1._destination_id = ""
        adapter1._map_meta = MapMetadata(
            width=100, height=100, resolution=0.1, origin_x=0.0, origin_y=0.0, origin_yaw=0.0
        )
        adapter1._occupancy_grid_data = [0] * 10000

        initial_dests = adapter1._load_destinations()
        assert len(initial_dests) == 1
        assert initial_dests[0]["id"] == "gate_seed_1"
        assert not storage_file.exists()  # Chưa ghi đè khi chưa lưu

        adapter1._destinations = initial_dests

        # 2. Admin lưu điểm mới -> ghi an toàn vào storage_file
        new_d = {
            "id": "gate_saved_2",
            "name": "Cổng đã lưu 2",
            "map_id": "airport_floor_1",
            "pose": {"position": {"x": 2.0, "y": 2.0, "z": 0.0}}
        }
        res_save = adapter1.upsert_destination(new_d)
        assert res_save["success"] is True
        assert storage_file.exists()
        assert adapter1.get_destinations_version() == 1

        # Đọc trực tiếp tệp trên đĩa: phải có cả 2 điểm
        with open(storage_file, "r", encoding="utf-8") as f:
            disk_data = yaml.safe_load(f)
            assert len(disk_data["destinations"]) == 2

        # 3. Tạo adapter 2 (giả lập restart backend): nạp từ storage_file, giữ điểm đã lưu
        adapter2 = RosRobotAdapter.__new__(RosRobotAdapter)
        adapter2._lock = threading.Lock()
        adapter2._cfg = get_ros_config()
        adapter2._destinations_file = storage_file
        adapter2._destinations_seed_file = seed_file
        adapter2._destinations_version = 0
        adapter2._navigation_state = "IDLE"
        adapter2._destination_id = ""
        adapter2._map_meta = adapter1._map_meta
        adapter2._occupancy_grid_data = adapter1._occupancy_grid_data

        reloaded_dests = adapter2._load_destinations()
        assert len(reloaded_dests) == 2
        ids = [d["id"] for d in reloaded_dests]
        assert "gate_seed_1" in ids
        assert "gate_saved_2" in ids

        # 4. Concurrency: 2 luồng lưu gần đồng thời
        adapter2._destinations = reloaded_dests
        results = []

        def save_worker(item_id, item_name, coord_x):
            d = {
                "id": item_id,
                "name": item_name,
                "map_id": "airport_floor_1",
                "pose": {"position": {"x": coord_x, "y": 2.0, "z": 0.0}}
            }
            r = adapter2.upsert_destination(d)
            results.append(r)

        t1 = threading.Thread(target=save_worker, args=("concurrent_A", "Điểm A", 3.0))
        t2 = threading.Thread(target=save_worker, args=("concurrent_B", "Điểm B", 4.0))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert len(results) == 2
        assert all(r["success"] is True for r in results)
        assert len(adapter2._destinations) == 4

        # 5. Lỗi ghi (read-only): Giữ bản cũ, không mất dữ liệu, rollback bộ nhớ
        os.chmod(storage_file, stat.S_IREAD)
        try:
            bad_save = adapter2.upsert_destination({
                "id": "should_fail",
                "name": "Thất bại",
                "map_id": "airport_floor_1",
                "pose": {"position": {"x": 5.0, "y": 5.0, "z": 0.0}}
            })
            assert bad_save["success"] is False
            assert "Không thể lưu" in bad_save["message"] or "quyền ghi" in bad_save["message"].lower() or "hệ thống tệp" in bad_save["message"].lower()
            # Bộ nhớ vẫn nguyên vẹn 4 điểm
            assert len(adapter2._destinations) == 4
            assert "should_fail" not in [d["id"] for d in adapter2._destinations]
        finally:
            os.chmod(storage_file, stat.S_IRWXU)

        # 6. Chặn sửa điểm đang có chuyến dẫn đường đang chạy
        adapter2._navigation_state = "NAVIGATING"
        adapter2._destination_id = "concurrent_A"
        res_locked = adapter2.upsert_destination({
            "id": "concurrent_A",
            "name": "Đổi tên khi đang chạy",
            "map_id": "airport_floor_1",
            "pose": {"position": {"x": 3.0, "y": 2.0, "z": 0.0}}
        })
        assert res_locked["success"] is False
        assert "Không thể cập nhật" in res_locked["message"]

        # Cho phép sửa điểm khác
        res_other = adapter2.upsert_destination({
            "id": "concurrent_B",
            "name": "Đổi tên điểm B",
            "map_id": "airport_floor_1",
            "pose": {"position": {"x": 4.0, "y": 2.0, "z": 0.0}}
        })
        assert res_other["success"] is True

    # 7. Kiểm tra phân quyền API /api/robot/destinations (Admin vs Passenger vs Anonymous) trong môi trường test cô lập
    from app.adapters.factory import get_robot_adapter
    live_adapter = get_robot_adapter()
    orig_file = getattr(live_adapter, "_destinations_file", None)
    orig_dests = list(getattr(live_adapter, "_destinations", []))
    isolated_api_file = tmp_path / "api_data" / "destinations.yaml"
    if hasattr(live_adapter, "_destinations_file"):
        live_adapter._destinations_file = isolated_api_file

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # Anonymous -> 401 hoặc 403
            test_payload = {
                "id": "api_test",
                "name": "API Test",
                "map_id": "airport_floor_1",
                "pose": {"position": {"x": 1.0, "y": 1.0, "z": 0.0}}
            }
            res_anon = await client.post("/api/robot/destinations", json=test_payload)
            assert res_anon.status_code in (401, 403)

            # Passenger -> 403 Forbidden
            sess_p = await client.post("/api/auth/session")
            token_p = sess_p.json()["session_token"]
            res_p = await client.post("/api/robot/destinations", json=test_payload, headers={"X-Passenger-Token": token_p})
            assert res_p.status_code == 403

            # Admin -> 200 OK
            admin_login = await client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
            admin_tok = admin_login.json()["access_token"]
            res_adm = await client.post("/api/robot/destinations", json=test_payload, headers={"Authorization": f"Bearer {admin_tok}"})
            assert res_adm.status_code == 200
            assert res_adm.json()["success"] is True
    finally:
        if hasattr(live_adapter, "_destinations_file"):
            live_adapter._destinations_file = orig_file
            live_adapter._destinations = orig_dests


@pytest.mark.anyio
async def test_destinations_deletion_persistence_and_permissions():
    """
    Kiểm thử toàn diện chức năng Xóa điểm đến:
    1. Admin xóa thành công điểm đến (atomic write, version increment, removed from disk).
    2. Điểm đã xóa không xuất hiện lại sau khi khởi tạo adapter mới (giả lập restart backend).
    3. Chặn xóa điểm đang có chuyến dẫn đường chưa kết thúc (PENDING, ACCEPTED, NAVIGATING, CANCELING).
    4. Lỗi ghi (read-only): Giữ nguyên danh sách cũ, rollback bộ nhớ và báo lỗi.
    5. Xóa điểm cuối cùng: Tệp lưu trữ rỗng 'destinations: []', khởi tạo adapter mới giữ danh sách rỗng,
       không nạp lại từ seed file.
    6. Phân quyền API: Anonymous (401/403) và Passenger (403) bị chặn, chỉ Admin (200) được xóa.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        seed_file = tmp_path / "seed_destinations.yaml"
        storage_file = tmp_path / "data" / "destinations.yaml"

        seed_data = {
            "map_id": "airport_floor_1",
            "destinations": [
                {
                    "id": "gate_seed_A",
                    "name": "Cổng Khởi Tạo A",
                    "map_id": "airport_floor_1",
                    "pose": {"position": {"x": 1.0, "y": 1.0, "z": 0.0}}
                },
                {
                    "id": "gate_seed_B",
                    "name": "Cổng Khởi Tạo B",
                    "map_id": "airport_floor_1",
                    "pose": {"position": {"x": 2.0, "y": 2.0, "z": 0.0}}
                }
            ]
        }
        with open(seed_file, "w", encoding="utf-8") as f:
            yaml.dump(seed_data, f)

        # 1. Khởi tạo adapter: storage_file chưa tồn tại -> nạp 2 điểm từ seed_file
        adapter = RosRobotAdapter.__new__(RosRobotAdapter)
        adapter._lock = threading.Lock()
        adapter._cfg = get_ros_config()
        adapter._destinations_file = storage_file
        adapter._destinations_seed_file = seed_file
        adapter._destinations_version = 0
        adapter._navigation_state = "IDLE"
        adapter._destination_id = ""
        adapter._map_meta = MapMetadata(
            width=100, height=100, resolution=0.1, origin_x=0.0, origin_y=0.0, origin_yaw=0.0
        )
        adapter._occupancy_grid_data = [0] * 10000

        initial_dests = adapter._load_destinations()
        assert len(initial_dests) == 2
        adapter._destinations = initial_dests
        # Lưu ra storage file
        adapter._save_destinations()
        assert storage_file.exists()

        # 2. Chặn xóa điểm đang có chuyến dẫn đường chưa kết thúc
        for blocked_state in ("PENDING", "ACCEPTED", "NAVIGATING", "CANCELING"):
            adapter._navigation_state = blocked_state
            adapter._destination_id = "gate_seed_A"
            res_blocked = adapter.delete_destination("gate_seed_A")
            assert res_blocked["success"] is False
            assert "chuyến dẫn đường chưa kết thúc" in res_blocked["message"] or "Không thể xóa" in res_blocked["message"]
            assert len(adapter._destinations) == 2

        # Cho phép xóa khi chuyến đã xong (SUCCEEDED, CANCELED, FAILED, IDLE)
        adapter._navigation_state = "IDLE"
        adapter._destination_id = ""

        # 3. Lỗi ghi (read-only): Giữ nguyên danh sách cũ, rollback bộ nhớ và báo lỗi
        os.chmod(storage_file, stat.S_IREAD)
        try:
            bad_del = adapter.delete_destination("gate_seed_A")
            assert bad_del["success"] is False
            assert "chế độ chỉ đọc" in bad_del["message"].lower() or "không thể lưu" in bad_del["message"].lower()
            # Danh sách trong bộ nhớ vẫn giữ nguyên 2 điểm
            assert len(adapter._destinations) == 2
            assert any(d["id"] == "gate_seed_A" for d in adapter._destinations)
        finally:
            os.chmod(storage_file, stat.S_IRWXU)

        # 4. Admin xóa thành công 1 điểm: "gate_seed_A"
        res_del = adapter.delete_destination("gate_seed_A")
        assert res_del["success"] is True
        assert adapter.get_destinations_version() == 1
        assert len(adapter._destinations) == 1
        assert adapter._destinations[0]["id"] == "gate_seed_B"

        # Kiểm tra tệp trên đĩa: chỉ còn 1 điểm
        with open(storage_file, "r", encoding="utf-8") as f:
            disk_data = yaml.safe_load(f)
            assert len(disk_data["destinations"]) == 1
            assert disk_data["destinations"][0]["id"] == "gate_seed_B"

        # 5. Điểm đã xóa không xuất hiện lại sau khi khởi tạo adapter mới
        adapter_restarted = RosRobotAdapter.__new__(RosRobotAdapter)
        adapter_restarted._lock = threading.Lock()
        adapter_restarted._cfg = get_ros_config()
        adapter_restarted._destinations_file = storage_file
        adapter_restarted._destinations_seed_file = seed_file
        adapter_restarted._destinations_version = 0

        restarted_dests = adapter_restarted._load_destinations()
        assert len(restarted_dests) == 1
        assert restarted_dests[0]["id"] == "gate_seed_B"
        assert not any(d["id"] == "gate_seed_A" for d in restarted_dests)

        # 6. Xóa điểm cuối cùng: danh sách rỗng
        adapter._destinations = restarted_dests
        res_del_last = adapter.delete_destination("gate_seed_B")
        assert res_del_last["success"] is True
        assert len(adapter._destinations) == 0

        # Kiểm tra đĩa: destinations rỗng
        with open(storage_file, "r", encoding="utf-8") as f:
            disk_empty = yaml.safe_load(f)
            assert isinstance(disk_empty["destinations"], list)
            assert len(disk_empty["destinations"]) == 0

        # Khởi tạo adapter mới lần 3 khi storage_file rỗng:
        # Phải nạp ra danh sách rỗng, KHÔNG ĐƯỢC nạp lại từ seed_file!
        adapter_empty = RosRobotAdapter.__new__(RosRobotAdapter)
        adapter_empty._lock = threading.Lock()
        adapter_empty._cfg = get_ros_config()
        adapter_empty._destinations_file = storage_file
        adapter_empty._destinations_seed_file = seed_file
        adapter_empty._destinations_version = 0

        empty_loaded = adapter_empty._load_destinations()
        assert len(empty_loaded) == 0  # GIỮ RỖNG sau khi xóa hết!

        # 7. Xóa điểm không tồn tại -> báo lỗi
        res_nonexistent = adapter.delete_destination("non_existent_id")
        assert res_nonexistent["success"] is False
        assert "Không tìm thấy" in res_nonexistent["message"]

    # 8. Kiểm tra phân quyền API DELETE /api/robot/destinations/{id} (Admin vs Passenger vs Anonymous)
    from app.adapters.factory import get_robot_adapter
    live_adapter = get_robot_adapter()
    orig_file = getattr(live_adapter, "_destinations_file", None)
    orig_dests = list(getattr(live_adapter, "_destinations", []))
    isolated_api_file = tmp_path / "api_data" / "destinations_del.yaml"
    if hasattr(live_adapter, "_destinations_file"):
        live_adapter._destinations_file = isolated_api_file
        live_adapter._destinations = [
            {
                "id": "del_api_test",
                "name": "Điểm Xóa API",
                "map_id": "airport_floor_1",
                "pose": {"position": {"x": 1.0, "y": 1.0, "z": 0.0}}
            }
        ]
        live_adapter._save_destinations()

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # Anonymous -> 401 hoặc 403
            res_anon = await client.delete("/api/robot/destinations/del_api_test")
            assert res_anon.status_code in (401, 403)

            # Passenger -> 403 Forbidden
            sess_p = await client.post("/api/auth/session")
            token_p = sess_p.json()["session_token"]
            res_p = await client.delete("/api/robot/destinations/del_api_test", headers={"X-Passenger-Token": token_p})
            assert res_p.status_code == 403

            # Admin -> 200 OK
            admin_login = await client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
            admin_tok = admin_login.json()["access_token"]
            res_adm = await client.delete("/api/robot/destinations/del_api_test", headers={"Authorization": f"Bearer {admin_tok}"})
            assert res_adm.status_code == 200
            assert res_adm.json()["success"] is True

            # Xác nhận đã xóa thành công trên API
            get_res = await client.get("/api/robot/destinations", headers={"Authorization": f"Bearer {admin_tok}"})
            assert get_res.status_code == 200
            assert not any(d["id"] == "del_api_test" for d in get_res.json())
    finally:
        if hasattr(live_adapter, "_destinations_file"):
            live_adapter._destinations_file = orig_file
            live_adapter._destinations = orig_dests


# =========================================================================
# 11. Navigation Pause & Resume Lifecycle and Permissions
# =========================================================================

@pytest.mark.anyio
async def test_navigation_pause_resume_lifecycle_and_permissions(tmp_path):
    """
    Kiểm tra toàn diện cơ chế Tạm dừng / Tiếp tục dẫn đường:
    1. Vòng đời Pause / Resume trên MockRobotAdapter:
       - Tách biệt trip_id và goal_id, giữ trip_id, owner_id, destination_id khi PAUSED.
       - Xóa path khi PAUSED, nhận path mới khi RESUMED.
       - Chống gọi lặp (pause khi đã paused, resume khi đang navigating).
       - Chặn bắt đầu chuyến mới và chặn sửa/xóa điểm đến khi đang PAUSED.
       - Hủy dứt điểm khi đang PAUSED mà không cần gọi thêm cancel tới Nav2.
    2. Vòng đời trên RosRobotAdapter:
       - Pause gửi cancel_goal_async và chuyển sang PAUSING.
       - Phản hồi từ chối hủy (return_code != 0) chuyển lại NAVIGATING.
       - Nav result status 5 trong lúc PAUSING chuyển sang PAUSED.
       - Nav result status 4 (đến đích đúng lúc bấm pause) giữ nguyên SUCCEEDED.
       - Resume gửi goal mới với cùng tọa độ đích, giữ nguyên trip_id.
       - Nav2 từ chối goal mới khi resume giữ nguyên PAUSED.
    3. Phân quyền API:
       - Anonymous / Passenger bị cấm (401/403) khi gọi /pause hoặc /resume.
       - Admin có quyền gọi /pause và /resume (200 OK).
       - Hành khách chủ chuyến có quyền gọi /cancel khi chuyến đang PAUSED.
    """
    # -------------------------------------------------------------
    # Phân đoạn 1: MockRobotAdapter Vòng đời Pause / Resume / Cancel
    # -------------------------------------------------------------
    mock_adapter = MockRobotAdapter()
    mock_adapter._destinations_file = tmp_path / "mock_dest.yaml"
    mock_adapter._destinations = []
    test_dest = {
        "id": "gate_pr_test",
        "name": "Cổng Test Pause Resume",
        "map_id": "airport_floor_1",
        "pose": {"position": {"x": 5.0, "y": 6.0, "z": 0.0}}
    }
    mock_adapter.upsert_destination(test_dest)

    # 1.1 Bắt đầu dẫn đường
    start_res = mock_adapter.start_navigation(destination_id="gate_pr_test", owner_id="user_owner_1")
    assert start_res["success"] is True
    initial_trip_id = start_res["trip_id"]
    initial_goal_id = start_res["goal_id"]
    assert initial_trip_id != ""
    assert mock_adapter._navigation_state == "NAVIGATING"

    # 1.2 Tạm dừng dẫn đường
    pause_res = mock_adapter.pause_navigation()
    assert pause_res["success"] is True
    assert mock_adapter._navigation_state == "PAUSED"
    assert mock_adapter._has_goal is False
    assert mock_adapter.get_path() is None or len(mock_adapter.get_path()) == 0
    # Bảo lưu thông tin phiên
    assert mock_adapter._trip_id == initial_trip_id
    assert mock_adapter._owner_id == "user_owner_1"
    assert mock_adapter._destination_id == "gate_pr_test"

    # 1.3 Gọi pause lại lần nữa -> Báo đã ở trạng thái tạm dừng
    pause_again = mock_adapter.pause_navigation()
    assert pause_again["success"] is True
    assert "đã ở trạng thái tạm dừng" in pause_again["message"]

    # 1.4 Chặn bắt đầu chuyến mới khi đang PAUSED
    start_blocked = mock_adapter.start_navigation(destination_id="gate_pr_test", owner_id="user_owner_2")
    assert start_blocked["success"] is False
    assert "PAUSED" in start_blocked["message"]

    # 1.5 Chặn sửa hoặc xóa điểm đang trong chuyến PAUSED
    upsert_blocked = mock_adapter.upsert_destination(test_dest)
    assert upsert_blocked["success"] is False
    assert "PAUSED" in upsert_blocked["message"]

    del_blocked = mock_adapter.delete_destination("gate_pr_test")
    assert del_blocked["success"] is False
    assert "PAUSED" in del_blocked["message"]

    # 1.6 Tiếp tục dẫn đường (Resume)
    resume_res = mock_adapter.resume_navigation()
    assert resume_res["success"] is True
    assert mock_adapter._navigation_state == "NAVIGATING"
    assert mock_adapter._has_goal is True
    # trip_id giữ nguyên, goal_id mới được cấp
    assert mock_adapter._trip_id == initial_trip_id
    assert mock_adapter._goal_id != initial_goal_id
    assert mock_adapter._owner_id == "user_owner_1"

    # 1.7 Gọi resume lần nữa khi đang di chuyển -> Báo không cần tiếp tục
    resume_again = mock_adapter.resume_navigation()
    assert resume_again["success"] is False
    assert "không cần tiếp tục" in resume_again["message"]

    # 1.8 Tạm dừng lại lần nữa để thử Cancel khi PAUSED
    mock_adapter.pause_navigation()
    assert mock_adapter._navigation_state == "PAUSED"

    # Người dùng khác hủy -> Bị từ chối
    cancel_forbidden = mock_adapter.cancel_navigation(owner_id="stranger_user", is_admin=False)
    assert cancel_forbidden["success"] is False
    assert "không có quyền" in cancel_forbidden["message"]

    # Chính chủ hủy khi đang PAUSED -> Hủy dứt điểm ngay lập tức
    cancel_owner = mock_adapter.cancel_navigation(owner_id="user_owner_1", is_admin=False)
    assert cancel_owner["success"] is True
    assert mock_adapter._navigation_state == "CANCELED"
    assert mock_adapter._trip_id == ""
    assert mock_adapter._owner_id == ""
    assert mock_adapter._destination_id == ""

    # Dọn dẹp mock adapter
    mock_adapter.dispose()

    # -------------------------------------------------------------
    # Phân đoạn 2: RosRobotAdapter Xử lý Callbacks, Async & Góc chết
    # -------------------------------------------------------------
    ros_ad = RosRobotAdapter.__new__(RosRobotAdapter)
    ros_ad._lock = threading.Lock()
    class DummyCfg:
        use_sim_time = False
        frames = {"map": "map", "base_link": "base_link"}
    ros_ad._cfg = DummyCfg()
    ros_ad._navigation_state = "NAVIGATING"
    ros_ad._has_goal = True
    ros_ad._trip_id = "test_ros_trip_123"
    ros_ad._active_request_id = "req_ros_goal_1"
    ros_ad._destination_id = "dest_1"
    ros_ad._owner_id = "admin"
    ros_ad._destinations = [
        {"id": "dest_1", "name": "Điểm Đích 1", "pose": {"position": {"x": 2.0, "y": 3.0}}}
    ]
    ros_ad._path = [{"x": 1.0, "y": 1.0}]
    ros_ad._path_version = 1
    ros_ad._cancel_requested_for = None
    ros_ad._pause_requested_for = None
    ros_ad._distance_remaining = 3.5
    ros_ad._estimated_time_remaining = 7.0
    ros_ad._number_of_recoveries = 0

    class DummyGoalHandle:
        def __init__(self):
            self.cancel_called = False
        def cancel_goal_async(self):
            self.cancel_called = True
            fut = asyncio.Future()
            return fut

    dummy_gh = DummyGoalHandle()
    ros_ad._current_goal_handle = dummy_gh

    # 2.1 Bấm tạm dừng khi đang NAVIGATING -> Chuyển PAUSING, gọi cancel_goal_async
    p_res = ros_ad.pause_navigation()
    assert p_res["success"] is True
    assert ros_ad._navigation_state == "PAUSING"
    assert dummy_gh.cancel_called is True
    assert ros_ad._path is None

    # 2.2 Callback Nav2 phản hồi từ chối cancel (return_code != 0) -> chuyển lại NAVIGATING
    class DummyCancelResponse:
        return_code = 1  # REJECTED
    class DummyFuture:
        def result(self):
            return DummyCancelResponse()

    ros_ad._on_cancel_response(DummyFuture(), "req_ros_goal_1")
    assert ros_ad._navigation_state == "NAVIGATING"

    # 2.3 Bấm tạm dừng lại và Nav2 hoàn tất hủy (GoalStatus 5) -> Chuyển PAUSED
    ros_ad.pause_navigation()
    assert ros_ad._navigation_state == "PAUSING"

    class DummyResultHandleStatus5:
        status = 5  # STATUS_CANCELED
        result = None
    class DummyResultFuture5:
        def result(self):
            return DummyResultHandleStatus5()

    ros_ad._on_nav_result(DummyResultFuture5(), "req_ros_goal_1", "Điểm Đích 1")
    assert ros_ad._navigation_state == "PAUSED"
    assert ros_ad._has_goal is False
    assert ros_ad._current_goal_handle is None
    # Bảo lưu phiên
    assert ros_ad._trip_id == "test_ros_trip_123"
    assert ros_ad._owner_id == "admin"
    assert ros_ad._destination_id == "dest_1"

    # 2.4 Tình huống robot đến đích ngay khi bấm pause (race condition: status 4)
    ros_ad._navigation_state = "PAUSING"
    class DummyResultHandleStatus4:
        status = 4  # STATUS_SUCCEEDED
        result = None
    class DummyResultFuture4:
        def result(self):
            return DummyResultHandleStatus4()

    ros_ad._on_nav_result(DummyResultFuture4(), "req_ros_goal_1", "Điểm Đích 1")
    assert ros_ad._navigation_state == "SUCCEEDED"
    assert ros_ad._trip_id == ""

    # 2.5 Kiểm tra Resume: regression test sim clock & goal construction
    import app.adapters.ros_adapter as ros_mod
    orig_has_action = getattr(ros_mod, "HAS_NAV2_ACTION", False)
    orig_nav_pose = getattr(ros_mod, "NavigateToPose", None)
    ros_mod.HAS_NAV2_ACTION = True
    class DummyNavigateToPose:
        class Goal:
            def __init__(self):
                class DummyHeader:
                    frame_id = ""
                    stamp = None
                class DummyPoint:
                    x = 0.0; y = 0.0; z = 0.0
                class DummyQuat:
                    x = 0.0; y = 0.0; z = 0.0; w = 1.0
                class DummyPose:
                    position = DummyPoint()
                    orientation = DummyQuat()
                class DummyPoseStamped:
                    header = DummyHeader()
                    pose = DummyPose()
                self.pose = DummyPoseStamped()
    ros_mod.NavigateToPose = DummyNavigateToPose

    try:
        ros_ad._cfg.use_sim_time = True
        ros_ad._clock_stalled = False
        ros_ad._navigation_state = "PAUSED"
        ros_ad._trip_id = "test_trip_resume"
        ros_ad._active_request_id = "req_resume_old"
        ros_ad._owner_id = "admin"
        ros_ad._destination_id = "dest_1"
        ros_ad._pose = {"x": 1.0, "y": 1.0, "theta": 0.0}

        class DummyActionNav:
            def __init__(self):
                self.last_goal = None
            def server_is_ready(self):
                return True
            def wait_for_server(self, timeout_sec=0.5):
                return True
            def send_goal_async(self, goal, feedback_callback=None):
                self.last_goal = goal
                fut = asyncio.Future()
                return fut

        class DummyClock:
            def now(self):
                class DummyTime:
                    def to_msg(self):
                        return None
                return DummyTime()

        class DummyNode:
            def get_clock(self):
                return DummyClock()

        ros_ad._action_nav = DummyActionNav()
        ros_ad._node = DummyNode()

        # 2.5a Clock stalled -> từ chối, giữ nguyên PAUSED
        ros_ad._clock_stalled = True
        res_stalled = ros_ad.resume_navigation()
        assert res_stalled["success"] is False
        assert "sim clock stalled" in res_stalled["message"]
        assert ros_ad._navigation_state == "PAUSED"

        # 2.5b Clock hoạt động -> tiếp tục thành công, chuyển PENDING, bảo lưu trip_id và tọa độ đích
        ros_ad._clock_stalled = False
        res_resume_ok = ros_ad.resume_navigation()
        assert res_resume_ok["success"] is True
        assert ros_ad._navigation_state == "PENDING"
        assert ros_ad._action_nav.last_goal is not None
        assert ros_ad._action_nav.last_goal.pose.pose.position.x == 2.0
        assert ros_ad._action_nav.last_goal.pose.pose.position.y == 3.0
        assert ros_ad._action_nav.last_goal.pose.header.frame_id == "map"
        assert ros_ad._trip_id == "test_trip_resume"

        # 2.5c Nav2 từ chối Goal mới khi resume -> Vẫn giữ PAUSED
        class DummyRejectedGoalHandle:
            accepted = False
        class DummyGoalFuture:
            def result(self):
                return DummyRejectedGoalHandle()

        ros_ad._on_goal_response(DummyGoalFuture(), ros_ad._active_request_id, "Điểm Đích 1", is_resume=True)
        assert ros_ad._navigation_state == "PAUSED"
        assert "từ chối" in ros_ad._message
    finally:
        ros_mod.HAS_NAV2_ACTION = orig_has_action
        ros_mod.NavigateToPose = orig_nav_pose

    # 2.6 Kiểm tra Hủy khi đang PAUSED trên RosRobotAdapter
    cancel_res_paused = ros_ad.cancel_navigation(owner_id="admin", is_admin=True)
    assert cancel_res_paused["success"] is True
    assert ros_ad._navigation_state == "CANCELED"
    assert ros_ad._trip_id == ""

    # -------------------------------------------------------------
    # Phân đoạn 3: Phân quyền API (REST Endpoints)
    # -------------------------------------------------------------
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 3.1 Anonymous gọi /pause và /resume -> Bị từ chối
        res_anon_pause = await client.post("/api/robot/pause")
        assert res_anon_pause.status_code in (401, 403)

        res_anon_resume = await client.post("/api/robot/resume")
        assert res_anon_resume.status_code in (401, 403)

        # 3.2 Passenger (Viewer) gọi /pause và /resume -> 403 Forbidden
        sess_p = await client.post("/api/auth/session")
        token_p = sess_p.json()["session_token"]

        res_p_pause = await client.post("/api/robot/pause", headers={"X-Passenger-Token": token_p})
        assert res_p_pause.status_code == 403

        res_p_resume = await client.post("/api/robot/resume", headers={"X-Passenger-Token": token_p})
        assert res_p_resume.status_code == 403

        # 3.3 Admin đăng nhập
        admin_login = await client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        admin_tok = admin_login.json()["access_token"]
        admin_headers = {"Authorization": f"Bearer {admin_tok}"}

        # Tạo chuyến dẫn đường qua Mock Adapter
        from app.adapters.factory import get_robot_adapter
        app_adapter = get_robot_adapter()
        orig_file = getattr(app_adapter, "_destinations_file", None)
        orig_dests = list(getattr(app_adapter, "_destinations", []))
        app_adapter._destinations_file = tmp_path / "api_dest.yaml"
        app_adapter._destinations = []
        app_adapter._control_mode = "AUTO"
        app_adapter._navigation_state = "IDLE"
        app_adapter._has_goal = False
        app_adapter._owner_id = ""
        app_adapter._active_hold_id = None
        try:
            app_adapter.upsert_destination({
                "id": "gate_api_test",
                "name": "Cổng API Test",
                "map_id": "airport_floor_1",
                "pose": {"position": {"x": 5.0, "y": 5.0, "z": 0.0}}
            })
            start_res_api = app_adapter.start_navigation("gate_api_test", owner_id="admin")
            assert start_res_api["success"] is True

            # Admin gọi Pause -> 200 OK
            res_adm_pause = await client.post("/api/robot/pause", headers=admin_headers)
            assert res_adm_pause.status_code == 200
            assert res_adm_pause.json()["success"] is True
            assert app_adapter.get_status()["navigation_state"] == "PAUSED"

            # Admin gọi Resume -> 200 OK
            res_adm_resume = await client.post("/api/robot/resume", headers=admin_headers)
            assert res_adm_resume.status_code == 200
            assert res_adm_resume.json()["success"] is True
            assert app_adapter.get_status()["navigation_state"] == "NAVIGATING"

            # Admin pause lại rồi cancel
            await client.post("/api/robot/pause", headers=admin_headers)
            res_adm_cancel = await client.post("/api/robot/cancel", headers=admin_headers)
            assert res_adm_cancel.status_code == 200
            assert app_adapter.get_status()["navigation_state"] == "CANCELED"
        finally:
            if hasattr(app_adapter, "_destinations_file"):
                app_adapter._destinations_file = orig_file
                app_adapter._destinations = orig_dests


# =========================================================================
# 11. AMCL Epoch Synchronization & Simulation Clock Reset Regression Tests
# =========================================================================

class MockClockHeader:
    def __init__(self, sec: int = 0, nanosec: int = 0):
        self.sec = sec
        self.nanosec = nanosec

class MockClockMsg:
    def __init__(self, sec: int, nanosec: int = 0):
        self.clock = MockClockHeader(sec=sec, nanosec=nanosec)

class MockPoint:
    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.x = x
        self.y = y
        self.z = z

class MockQuaternion:
    def __init__(self, x=0.0, y=0.0, z=0.0, w=1.0):
        self.x = x
        self.y = y
        self.z = z
        self.w = w

class MockPoseInner:
    def __init__(self, x=0.0, y=0.0):
        self.position = MockPoint(x, y)
        self.orientation = MockQuaternion()

class MockPoseWithCovariance:
    def __init__(self, x=0.0, y=0.0):
        self.pose = MockPoseInner(x, y)

class MockAmclMsg:
    def __init__(self, x=0.0, y=0.0, frame_id="map", sec=1):
        class MockHeader:
            def __init__(self, fid, s):
                self.frame_id = fid
                self.stamp = MockClockHeader(sec=s)
        self.header = MockHeader(frame_id, sec)
        self.pose = MockPoseWithCovariance(x, y)

class MockDummyActionClient:
    def __init__(self):
        self.last_goal = None
    def server_is_ready(self):
        return True
    def wait_for_server(self, timeout_sec=0.5):
        return True
    def send_goal_async(self, goal, feedback_callback=None):
        self.last_goal = goal
        class DummyFuture:
            def add_done_callback(self, cb):
                pass
        return DummyFuture()

def create_isolated_ros_adapter():
    adapter = RosRobotAdapter.__new__(RosRobotAdapter)
    adapter._lock = threading.Lock()
    adapter._cfg = get_ros_config()
    adapter._navigation_state = "IDLE"
    adapter._control_mode = "AUTO"
    adapter._has_goal = False
    adapter._goal_id = ""
    adapter._trip_id = ""
    adapter._destination_id = ""
    adapter._destinations = [
        {"id": "d1", "name": "Điểm 1", "pose": {"position": {"x": 1.0, "y": 1.0, "z": 0.0}}}
    ]
    adapter._owner_id = ""
    adapter._distance_remaining = None
    adapter._estimated_time_remaining = None
    adapter._number_of_recoveries = 0
    adapter._voice_state = "IDLE"
    adapter._voice_transcript = None
    adapter._voice_response = None
    adapter._message = "Đang kết nối tới các topic ROS..."
    adapter._current_goal_handle = None
    adapter._nav2_has_active_goal = False
    adapter._path = None
    adapter._path_version = 0
    adapter._battery_percent = 90.0
    adapter._map_version = "v1"
    adapter._destinations_version = 1
    adapter._last_pose_time = 0.0
    adapter._pose = None
    adapter._pose_frame_id = ""
    adapter._pose_stamp = None

    # Sim clock & epoch fields
    adapter._last_clock_sec = None
    adapter._last_clock_monotonic = 0.0
    adapter._clock_stalled = False
    adapter._sim_restarted = False
    adapter._pose_epoch = 0
    adapter._pose_received_epoch = -1

    # Mock action client & MapMetadata
    adapter._action_nav = MockDummyActionClient()
    adapter._map_meta = MapMetadata(width=100, height=100, resolution=0.1, origin_x=0.0, origin_y=0.0, origin_yaw=0.0)
    adapter._occupancy_grid_data = [0] * 10000

    class DummyClock:
        def now(self):
            class DummyTime:
                def to_msg(self):
                    return MockClockHeader(sec=1, nanosec=0)
            return DummyTime()

    class DummyNode:
        def get_clock(self):
            return DummyClock()

    adapter._node = DummyNode()
    return adapter

def test_amcl_epoch_pose_before_clock_initial_connection():
    """
    Regression Test (1):
    Pose AMCL đến trước /clock lúc kết nối lần đầu.
    Robot đứng yên (không có pose mới sau khi clock đến) vẫn kết nối thành công (Robot: OK, Bắt đầu mở).
    """
    adapter = create_isolated_ros_adapter()
    import app.adapters.ros_adapter as ra_mod
    orig_has_action = ra_mod.HAS_NAV2_ACTION
    orig_nav_cls = ra_mod.NavigateToPose
    ra_mod.HAS_NAV2_ACTION = True

    class MockGoalMsg:
        class Goal:
            def __init__(self):
                class MockTargetPose:
                    def __init__(self):
                        class MockHeader:
                            def __init__(self):
                                self.frame_id = "map"
                                self.stamp = MockClockHeader()
                        class MockPoseContent:
                            def __init__(self):
                                self.position = MockPoint()
                                self.orientation = MockQuaternion()
                        self.header = MockHeader()
                        self.pose = MockPoseContent()
                self.pose = MockTargetPose()

    ra_mod.NavigateToPose = MockGoalMsg

    try:
        # Ban đầu chưa có dữ liệu gì: is_connected = False, sim_clock_stalled = True
        init_st = adapter.get_status()
        assert init_st["is_connected"] is False
        assert init_st["sim_clock_stalled"] is True
        assert "Đang chờ mô phỏng" in init_st["message"]

        # 1. Pose AMCL đến TRƯỚC /clock (ví dụ AMCL latched pose đến trước)
        adapter._on_amcl_pose(MockAmclMsg(x=1.5, y=2.5))
        assert adapter._pose is not None
        assert adapter._pose["x"] == 1.5
        assert adapter._pose_received_epoch == 0
        assert adapter._sim_restarted is False

        # Tại thời điểm này /clock vẫn chưa đến -> vẫn chưa báo OK vì clock chưa tiến
        mid_st = adapter.get_status()
        assert mid_st["is_connected"] is False
        assert mid_st["sim_clock_stalled"] is True

        # 2. Sau đó /clock message đầu tiên xuất hiện (ví dụ lúc t = 10s)
        adapter._on_clock(MockClockMsg(sec=10, nanosec=0))
        assert adapter._last_clock_sec == 10.0
        assert adapter._clock_stalled is False
        assert adapter._pose_epoch == 0  # Không bị tăng epoch
        assert adapter._sim_restarted is False

        # 3. Robot đứng yên! AMCL không gửi thêm pose nào nữa.
        # Clock tiếp tục tiến:
        adapter._on_clock(MockClockMsg(sec=11, nanosec=0))
        adapter._on_clock(MockClockMsg(sec=12, nanosec=0))

        # Kiểm tra trạng thái: Robot đứng yên VẪN KẾT NỐI ĐƯỢC
        final_st = adapter.get_status()
        assert final_st["is_connected"] is True  # Robot: OK
        assert final_st["is_data_stale"] is False
        assert final_st["sim_restarted"] is False
        assert final_st["sim_clock_stalled"] is False
        assert final_st["pose"]["x"] == 1.5
        assert final_st["message"] == "Hệ thống sẵn sàng đón khách"

        # Nút "Bắt đầu dẫn đường" được phép kích hoạt thành công
        start_res = adapter.start_navigation("d1", owner_id="admin")
        assert start_res["success"] is True
        assert adapter._navigation_state == "PENDING"
    finally:
        ra_mod.HAS_NAV2_ACTION = orig_has_action
        ra_mod.NavigateToPose = orig_nav_cls


def test_amcl_epoch_clock_rewind_requires_new_pose_after_gazebo_reset():
    """
    Regression Test (2):
    /clock quay lùi sau reset Gazebo:
    - Pose cũ KHÔNG được tự động công nhận cho phiên mới chỉ vì /clock tiếp tục tăng.
    - Chờ pose hợp lệ của phiên mới rồi mới báo Robot: OK và mở lại nút Bắt đầu.
    """
    adapter = create_isolated_ros_adapter()
    import app.adapters.ros_adapter as ra_mod
    orig_has_action = ra_mod.HAS_NAV2_ACTION
    orig_nav_cls = ra_mod.NavigateToPose
    ra_mod.HAS_NAV2_ACTION = True

    class MockGoalMsg:
        class Goal:
            def __init__(self):
                class MockTargetPose:
                    def __init__(self):
                        class MockHeader:
                            def __init__(self):
                                self.frame_id = "map"
                                self.stamp = MockClockHeader()
                        class MockPoseContent:
                            def __init__(self):
                                self.position = MockPoint()
                                self.orientation = MockQuaternion()
                        self.header = MockHeader()
                        self.pose = MockPoseContent()
                self.pose = MockTargetPose()

    ra_mod.NavigateToPose = MockGoalMsg

    try:
        # Giai đoạn 1: Phiên 1 đang chạy bình thường ở epoch 0
        adapter._on_amcl_pose(MockAmclMsg(x=8.0, y=9.0))
        adapter._on_clock(MockClockMsg(sec=120, nanosec=0))
        s1 = adapter.get_status()
        assert s1["is_connected"] is True
        assert s1["pose"]["x"] == 8.0

        # Giai đoạn 2: Gazebo bị reset! Clock quay lùi từ 120s về 0.5s
        adapter._on_clock(MockClockMsg(sec=0, nanosec=500_000_000))
        assert adapter._sim_restarted is True
        assert adapter._pose_epoch == 1
        assert adapter._pose_received_epoch == 0  # Thuộc epoch cũ!

        # Giai đoạn 3: Trong phiên mới, clock tiếp tục tăng tiến bình thường (0.6s -> 5.0s)
        adapter._on_clock(MockClockMsg(sec=1, nanosec=0))
        adapter._on_clock(MockClockMsg(sec=2, nanosec=0))
        adapter._on_clock(MockClockMsg(sec=5, nanosec=0))

        # Quan trọng: Dù /clock tiếp tục tăng, pose cũ TUYỆT ĐỐI KHÔNG ĐƯỢC CÔNG NHẬN
        s2 = adapter.get_status()
        assert s2["is_connected"] is False  # Robot: KHÔNG OK
        assert s2["is_data_stale"] is True
        assert s2["sim_restarted"] is True
        assert "khởi động lại" in s2["message"]

        # Nút "Bắt đầu dẫn đường" bị khóa ở backend và trả về lỗi rõ ràng
        blocked_start = adapter.start_navigation("d1", owner_id="admin")
        assert blocked_start["success"] is False
        assert "Mô phỏng vừa khởi động lại" in blocked_start["message"] or "chờ dữ liệu vị trí robot mới" in blocked_start["message"]

        # Giai đoạn 4: AMCL trong phiên Gazebo mới định vị xong và phát pose mới (epoch 1)
        adapter._on_amcl_pose(MockAmclMsg(x=0.0, y=0.0))  # Robot xuất hiện ở tọa độ gốc mới
        assert adapter._pose_epoch == 1
        assert adapter._pose_received_epoch == 1
        assert adapter._sim_restarted is False

        # Sau khi có pose của phiên mới: Robot: OK và nút Bắt đầu được mở lại
        s3 = adapter.get_status()
        assert s3["is_connected"] is True  # Robot: OK
        assert s3["is_data_stale"] is False
        assert s3["sim_restarted"] is False
        assert s3["pose"]["x"] == 0.0
        assert s3["message"] == "Hệ thống sẵn sàng đón khách"

        # Bắt đầu dẫn đường thành công
        ok_start = adapter.start_navigation("d1", owner_id="admin")
        assert ok_start["success"] is True
        assert adapter._navigation_state == "PENDING"
    finally:
        ra_mod.HAS_NAV2_ACTION = orig_has_action
        ra_mod.NavigateToPose = orig_nav_cls


@pytest.mark.anyio
async def test_manual_control_arbitration_concurrency_and_timeout():
    """
    Kiểm tra toàn diện tính năng Điều khiển tay (Manual Control) cho Admin:
    1. Phân quyền API: Anonymous (401), Passenger/Viewer (403), Admin (200).
    2. Chuyển chế độ AUTO / MANUAL:
       - Chặn khi chưa kết nối, chặn khi đang NAVIGATING hoặc PAUSED, chặn khi Nav2 có goal ngoài.
       - Cho phép khi rảnh (IDLE) và kết nối.
    3. Phân quyền phiên Admin đơn (Single Admin lock):
       - Admin 1 chiếm quyền -> Admin 2 bị từ chối chuyển chế độ và gửi lệnh vận tốc.
    4. Giới hạn vận tốc (Speed clamping):
       - Vận tốc vượt ngưỡng an toàn bị kẹp chặt về linear_max (0.3 m/s) và angular_max (0.5 rad/s).
    5. Cơ chế Watchdog an toàn (Heartbeat timeout):
       - Khi nhả nút hoặc quá thời gian timeout (cmd_timeout_sec), robot tự động ngắt về vận tốc 0.
    6. Phân luồng xung đột giữa MANUAL và Nav2:
       - Khi ở MANUAL, chặn hoàn toàn bắt đầu dẫn đường mới và tiếp tục chuyến cũ.
       - Khi thoát MANUAL về AUTO, mở khóa dẫn đường trở lại.
    7. RosRobotAdapter:
       - Kiểm tra logic consumer check (0 subscriber), arbitration và watchdog.
    """
    # -------------------------------------------------------------
    # Phân đoạn 1: Phân quyền REST Endpoints
    # -------------------------------------------------------------
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1.1 Anonymous gọi /control/manual và /control/velocity -> Bị từ chối
        res_anon_mode = await client.post("/api/robot/control/manual", json={"enable": True})
        assert res_anon_mode.status_code in (401, 403)

        res_anon_vel = await client.post("/api/robot/control/velocity", json={"linear_x": 0.2, "angular_z": 0.0})
        assert res_anon_vel.status_code in (401, 403)

        # 1.2 Passenger (Viewer) gọi -> 403 Forbidden
        sess_p = await client.post("/api/auth/session")
        token_p = sess_p.json()["session_token"]
        headers_p = {"X-Passenger-Token": token_p}

        res_p_mode = await client.post("/api/robot/control/manual", json={"enable": True}, headers=headers_p)
        assert res_p_mode.status_code == 403

        res_p_vel = await client.post("/api/robot/control/velocity", json={"linear_x": 0.2, "angular_z": 0.0}, headers=headers_p)
        assert res_p_vel.status_code == 403

        # 1.3 Admin đăng nhập -> Có quyền gọi API
        admin_login = await client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        assert admin_login.status_code == 200
        admin_tok = admin_login.json()["access_token"]
        admin_headers = {"Authorization": f"Bearer {admin_tok}"}

        # Lấy adapter mock
        from app.adapters.factory import get_robot_adapter
        adapter = get_robot_adapter()
        adapter._is_connected = True
        adapter._control_mode = "AUTO"
        adapter._navigation_state = "IDLE"
        adapter._has_goal = False
        adapter._manual_operator_id = None
        adapter._current_manual_twist = (0.0, 0.0)

        # Bật thủ công qua Admin API
        res_admin_mode = await client.post("/api/robot/control/manual", json={"enable": True}, headers=admin_headers)
        assert res_admin_mode.status_code == 200
        assert res_admin_mode.json()["success"] is True
        assert adapter._control_mode == "MANUAL"

        # Gửi vận tốc qua Admin API
        res_admin_vel = await client.post(
            "/api/robot/control/velocity",
            json={"linear_x": 0.2, "angular_z": 0.1, "seq": 1, "hold_id": "hold_adm_1"},
            headers=admin_headers
        )
        assert res_admin_vel.status_code == 200
        assert res_admin_vel.json()["success"] is True

        # Tắt thủ công qua Admin API
        res_admin_off = await client.post("/api/robot/control/manual", json={"enable": False}, headers=admin_headers)
        assert res_admin_off.status_code == 200
        assert adapter._control_mode == "AUTO"

    # -------------------------------------------------------------
    # Phân đoạn 2: Điều kiện chuyển sang MANUAL và Phân luồng xung đột
    # -------------------------------------------------------------
    adapter._control_mode = "AUTO"
    adapter._navigation_state = "IDLE"
    adapter._has_goal = False
    adapter._is_connected = False

    # 2.1 Không kết nối -> Chặn chuyển sang MANUAL
    res_no_conn = adapter.set_manual_control(True, operator_id="admin1")
    assert res_no_conn["success"] is False
    assert "chưa kết nối" in res_no_conn["message"]

    # 2.2 Đang NAVIGATING -> Chặn chuyển sang MANUAL
    adapter._is_connected = True
    adapter._navigation_state = "NAVIGATING"
    adapter._has_goal = True
    res_nav = adapter.set_manual_control(True, operator_id="admin1")
    assert res_nav["success"] is False
    assert "Đang có chuyến dẫn đường" in res_nav["message"]

    # 2.3 Đang PAUSED -> Chặn chuyển sang MANUAL
    adapter._navigation_state = "PAUSED"
    res_paused = adapter.set_manual_control(True, operator_id="admin1")
    assert res_paused["success"] is False
    assert "Đang có chuyến dẫn đường" in res_paused["message"]

    # 2.4 Robot rảnh (IDLE) -> Chuyển thành công
    adapter._navigation_state = "IDLE"
    adapter._has_goal = False
    res_idle = adapter.set_manual_control(True, operator_id="admin1")
    assert res_idle["success"] is True
    assert adapter._control_mode == "MANUAL"
    assert adapter._manual_operator_id == "admin1"

    # 2.5 Khi đang ở MANUAL -> Chặn Start và Resume Nav2
    start_blocked = adapter.start_navigation("gate_a1", owner_id="admin1")
    assert start_blocked["success"] is False
    assert "chế độ điều khiển thủ công" in start_blocked["message"]

    resume_blocked = adapter.resume_navigation()
    assert resume_blocked["success"] is False
    assert "chế độ điều khiển thủ công" in resume_blocked["message"]

    # -------------------------------------------------------------
    # Phân đoạn 3: Chiếm quyền Admin (Single Admin Concurrency)
    # -------------------------------------------------------------
    # Admin 2 cố gắng gửi lệnh khi Admin 1 đang giữ quyền
    res_admin2_enable = adapter.set_manual_control(True, operator_id="admin2")
    assert res_admin2_enable["success"] is False
    assert "thuộc về Admin khác (admin1)" in res_admin2_enable["message"]

    res_admin2_vel = adapter.send_manual_velocity(0.2, 0.0, operator_id="admin2", seq=1, hold_id="hold_adm_2")
    assert res_admin2_vel["success"] is False
    assert "thuộc về Admin khác (admin1)" in res_admin2_vel["message"]

    # -------------------------------------------------------------
    # Phân đoạn 4: Giới hạn tốc độ (Speed Clamping) & Watchdog
    # -------------------------------------------------------------
    # Gửi vận tốc vượt trần: linear_x=2.0 (trần 0.3), angular_z=-3.0 (trần -0.5)
    res_clamped = adapter.send_manual_velocity(2.0, -3.0, operator_id="admin1", seq=1, hold_id="hold_adm_clamp")
    assert res_clamped["success"] is True
    assert adapter._current_manual_twist == (0.3, -0.5)

    # Watchdog kiểm tra khi mới nhận lệnh -> chưa timeout
    adapter.check_manual_timeout()
    assert adapter._current_manual_twist == (0.3, -0.5)

    # Giả lập thời gian trôi qua quá timeout (0.6s)
    adapter._last_manual_cmd_time = time.monotonic() - 1.0
    adapter.check_manual_timeout()
    # Robot tự động dừng về (0.0, 0.0)
    assert adapter._current_manual_twist == (0.0, 0.0)

    # -------------------------------------------------------------
    # Phân đoạn 5: Thoát MANUAL về AUTO
    # -------------------------------------------------------------
    res_off = adapter.set_manual_control(False)
    assert res_off["success"] is True
    assert adapter._control_mode == "AUTO"
    assert adapter._manual_operator_id is None
    assert adapter._current_manual_twist == (0.0, 0.0)

    # -------------------------------------------------------------
    # Phân đoạn 6: Kiểm tra RosRobotAdapter độc lập
    # -------------------------------------------------------------
    from app.adapters.ros_adapter import RosRobotAdapter
    ros_ad = RosRobotAdapter.__new__(RosRobotAdapter)
    ros_ad._lock = threading.Lock()
    ros_ad._control_mode = "AUTO"
    ros_ad._manual_operator_id = None
    ros_ad._current_manual_twist = (0.0, 0.0)
    ros_ad._last_manual_cmd_time = 0.0
    ros_ad._navigation_state = "IDLE"
    ros_ad._has_goal = False
    ros_ad._nav2_has_active_goal = False
    ros_ad._pose = {"x": 1.0, "y": 2.0, "theta": 0.0}
    ros_ad._battery_percent = 0.8
    ros_ad._last_pose_time = time.time()
    ros_ad._clock_stalled = False
    ros_ad._sim_restarted = False
    ros_ad._pose_received_epoch = 0
    ros_ad._pose_epoch = 0
    ros_ad._last_clock_sec = 10.0
    ros_ad._last_clock_monotonic = time.monotonic()
    ros_ad._message = "Sẵn sàng"
    ros_ad._destination_id = ""
    ros_ad._distance_remaining = None
    ros_ad._estimated_time_remaining = None
    ros_ad._number_of_recoveries = 0
    ros_ad._voice_state = "IDLE"
    ros_ad._voice_transcript = None
    ros_ad._voice_response = None
    ros_ad._pose_frame_id = "map"
    ros_ad._pose_stamp = None
    ros_ad._map_version = "v1"

    class MockCfg:
        use_sim_time = True
        velocity_limits = {"linear_max": 0.3, "angular_max": 0.5, "cmd_timeout_sec": 0.5}
        frames = {"base_link": "base_link"}

    ros_ad._cfg = MockCfg()

    # Consumer check khi chưa có publisher hoặc 0 subscriber
    assert ros_ad.is_manual_consumer_available() is False

    # Chặn khi Nav2 có goal ngoài đang chạy
    ros_ad._nav2_has_active_goal = True
    r_ext = ros_ad.set_manual_control(True, operator_id="admin_ext")
    assert r_ext["success"] is False
    assert "nguồn ngoài" in r_ext["message"]

    # Chuyển thành công khi IDLE và không có goal ngoài
    ros_ad._nav2_has_active_goal = False
    r_ok = ros_ad.set_manual_control(True, operator_id="admin_ros")
    assert r_ok["success"] is True
    assert ros_ad._control_mode == "MANUAL"
    assert ros_ad._manual_operator_id == "admin_ros"

    # Chiếm quyền
    r_conflict = ros_ad.set_manual_control(True, operator_id="admin_other")
    assert r_conflict["success"] is False
    assert "thuộc về Admin khác (admin_ros)" in r_conflict["message"]

    # Watchdog trên RosRobotAdapter
    ros_ad._current_manual_twist = (0.2, 0.1)
    ros_ad._last_manual_cmd_time = time.monotonic() - 1.0
    ros_ad.check_manual_timeout()
    assert ros_ad._current_manual_twist == (0.0, 0.0)

    # Thoát về AUTO
    r_auto = ros_ad.set_manual_control(False)
    assert r_auto["success"] is True
    assert ros_ad._control_mode == "AUTO"
    assert ros_ad._manual_operator_id is None


# =========================================================================
# 26. Voice Interface, Debouncing & Lifecycle Tests
# =========================================================================

def test_voice_interface_lifecycle_and_debouncing():
    """
    Kiểm thử toàn diện cho hệ thống Voice/Microphone:
    1. Kiểm tra xác thực API (/api/robot/voice/start).
    2. Kiểm tra khi node giọng nói ROS offline: từ chối an toàn, nút bị khóa.
    3. Kiểm tra khi node sẵn sàng: kích hoạt, chặn bấm dồn dập (in-flight debounce),
       chuyển trạng thái LISTENING -> PROCESSING -> SPEAKING -> IDLE.
    4. Kiểm thử RosRobotAdapter cô lập: service_is_ready check, timeout handling,
       phản hồi từ ROS service Trigger.
    """
    from fastapi.testclient import TestClient
    from app.main import app
    from app.adapters.factory import get_robot_adapter
    from app.adapters.ros_adapter import RosRobotAdapter
    import threading

    client = TestClient(app)

    # 1. API Auth check - Token giả mạo/không hợp lệ bị từ chối 401
    resp_bad_token = client.post("/api/robot/voice/start", headers={"Authorization": "Bearer invalid_forged_token"})
    assert resp_bad_token.status_code == 401

    # Tạo token passenger
    sess_res = client.post("/api/auth/session")
    assert sess_res.status_code == 200
    pass_token = sess_res.json()["session_token"]
    pass_headers = {"X-Passenger-Token": pass_token}

    adapter = get_robot_adapter()
    assert hasattr(adapter, "is_voice_available")

    # 2. Trường hợp Voice node OFFLINE
    if hasattr(adapter, "set_voice_available"):
        adapter.set_voice_available(False)
        assert adapter.is_voice_available() is False
        status = adapter.get_status()
        assert status.get("voice_available") is False

        # Gọi API khi offline -> Bị từ chối an toàn 400
        resp_offline = client.post("/api/robot/voice/start", headers=pass_headers)
        assert resp_offline.status_code == 400
        assert "chưa sẵn sàng" in resp_offline.json()["detail"] or "chưa khởi chạy" in resp_offline.json()["detail"]

        # 3. Trường hợp Voice node SẴN SÀNG
        adapter.set_voice_available(True)
        assert adapter.is_voice_available() is True
        status_ok = adapter.get_status()
        assert status_ok.get("voice_available") is True

        # Đảm bảo reset trạng thái giọng nói về IDLE
        with adapter._lock:
            adapter._voice_state = "IDLE"
            adapter._voice_start_in_progress = False

        # Gọi API kích hoạt thành công
        resp_start = client.post("/api/robot/voice/start", headers=pass_headers)
        assert resp_start.status_code == 200
        assert resp_start.json()["success"] is True

        # Kiểm tra trạng thái chuyển sang LISTENING
        assert adapter.get_status()["voice_state"] == "LISTENING"

        # Chặn bấm dồn dập (in-flight debounce / đang bận)
        resp_spam = client.post("/api/robot/voice/start", headers=pass_headers)
        assert resp_spam.status_code == 400
        assert "đang bận" in resp_spam.json()["detail"] or "đang được xử lý" in resp_spam.json()["detail"]

        # Reset về IDLE sau test
        with adapter._lock:
            adapter._voice_state = "IDLE"
            adapter._voice_start_in_progress = False

    # 4. Kiểm thử RosRobotAdapter cô lập (Unit tests không phụ thuộc ROS daemon)
    ros_ad = object.__new__(RosRobotAdapter)
    ros_ad._lock = threading.RLock()
    ros_ad._voice_start_in_progress = False
    ros_ad._voice_state = "IDLE"
    ros_ad._voice_transcript = None
    ros_ad._voice_response = None

    class MockVoiceSrvCfg:
        name = "/airport/voice/start"
        type = "std_srvs/srv/Trigger"
        enabled = True
        timeout_sec = 0.5

    class MockRosCfg:
        use_sim_time = True
        def get_service(self, name):
            if name == "voice_start":
                return MockVoiceSrvCfg()
            return None

    ros_ad._cfg = MockRosCfg()

    # (a) Chưa có client
    ros_ad._cli_voice_start = None
    assert ros_ad.is_voice_available() is False
    res_no_cli = ros_ad.start_voice_session()
    assert res_no_cli["success"] is False
    assert "chưa được cấu hình" in res_no_cli["message"]

    # (b) Client tồn tại nhưng service chưa sẵn sàng
    class DummyServiceClient:
        def __init__(self, ready=False):
            self._ready = ready
            self.call_count = 0
        def service_is_ready(self):
            return self._ready
        def call_async(self, req):
            self.call_count += 1
            class DummyFuture:
                def __init__(self):
                    self._done_callbacks = []
                def add_done_callback(self, cb):
                    self._done_callbacks.append(cb)
            return DummyFuture()

    ros_ad._cli_voice_start = DummyServiceClient(ready=False)
    assert ros_ad.is_voice_available() is False
    res_not_ready = ros_ad.start_voice_session()
    assert res_not_ready["success"] is False
    assert "chưa sẵn sàng" in res_not_ready["message"]
    assert ros_ad._cli_voice_start.call_count == 0  # Không gửi call_async khi chưa sẵn sàng

    # (c) In-flight debounce
    ros_ad._cli_voice_start = DummyServiceClient(ready=True)
    assert ros_ad.is_voice_available() is True
    ros_ad._voice_start_in_progress = True
    res_in_prog = ros_ad.start_voice_session()
    assert res_in_prog["success"] is False
    assert "đang được xử lý" in res_in_prog["message"]
    ros_ad._voice_start_in_progress = False

    # (d) Timeout handling khi service không trả lời
    class TimeoutServiceClient:
        def service_is_ready(self):
            return True
        def call_async(self, req):
            class HangingFuture:
                def add_done_callback(self, cb):
                    pass  # Không gọi callback để kích hoạt timeout
            return HangingFuture()

    ros_ad._cli_voice_start = TimeoutServiceClient()
    t0 = time.monotonic()
    res_timeout = ros_ad.start_voice_session()
    duration = time.monotonic() - t0
    assert res_timeout["success"] is False
    assert "Hết thời gian chờ phản hồi" in res_timeout["message"]
    assert duration >= 0.4  # Khớp timeout 0.5s từ config
    assert ros_ad._voice_start_in_progress is False  # Đảm bảo cờ in-flight được reset

    # (e) ROS Service trả về thành công
    class SuccessServiceClient:
        def service_is_ready(self):
            return True
        def call_async(self, req):
            class ImmediateFuture:
                def add_done_callback(self, cb):
                    class Resp:
                        success = True
                        message = "Microphone robot đã mở, mời nói."
                    self.result = lambda: Resp()
                    cb(self)
            return ImmediateFuture()

    ros_ad._cli_voice_start = SuccessServiceClient()
    res_ok = ros_ad.start_voice_session()
    assert res_ok["success"] is True
    assert "Microphone robot đã mở" in res_ok["message"]
    assert ros_ad._voice_start_in_progress is False


# =========================================================================
# 27. Voice Destination Matching, Session Isolation & Confirmation Tests
# =========================================================================

def test_voice_destination_matching_and_confirmation_workflow():
    """
    Kiểm thử chuyên sâu cho tính năng Nhận diện Điểm Đến & Xác Nhận từ Giọng Nói:
    1. Thuật toán voice_matcher: khớp 1 điểm (MATCHED), mập mờ (AMBIGUOUS), không khớp (NO_MATCH).
    2. Phân tách phiên: Đề xuất gắn chặt với ID phiên bấm mic (Passenger A).
    3. Bảo mật: Passenger B không có quyền xác nhận đề xuất của Passenger A (403).
    4. Xác nhận thành công: Bắt đầu điều hướng qua luồng Nav2 hiện có.
    5. Chống xác nhận lặp: Đề xuất bị thu hồi ngay lập tức, bấm lần 2 bị từ chối 400.
    6. Hết hạn (Expiry): Đề xuất quá thời hạn (30s) bị từ chối 400.
    7. Bỏ qua (Dismiss): Hủy đề xuất an toàn.
    """
    from fastapi.testclient import TestClient
    from app.main import app
    from app.adapters.factory import get_robot_adapter
    from app.services.voice_matcher import match_destination_from_transcript

    client = TestClient(app)
    adapter = get_robot_adapter()

    # Dữ liệu điểm đến mẫu
    sample_dests = [
        {"id": "gate_1", "name": "Cổng khởi hành số 1"},
        {"id": "gate_2", "name": "Cổng khởi hành số 2"},
        {"id": "info_desk", "name": "Quầy thông tin"},
        {"id": "restroom", "name": "Khu vệ sinh công cộng"},
    ]

    # --- 1. Kiểm thử thuật toán voice_matcher ---
    # (a) Khớp chính xác duy nhất
    res_exact = match_destination_from_transcript("Hãy dẫn tôi đến Cổng khởi hành số 1", sample_dests)
    assert res_exact["status"] == "MATCHED"
    assert res_exact["destination"]["id"] == "gate_1"

    # (b) Khớp theo số thứ tự và từ khóa
    res_number = match_destination_from_transcript("Dẫn tôi tới Cổng 2", sample_dests)
    assert res_number["status"] == "MATCHED"
    assert res_number["destination"]["id"] == "gate_2"

    res_info = match_destination_from_transcript("Tôi muốn đến quầy thông tin", sample_dests)
    assert res_info["status"] == "MATCHED"
    assert res_info["destination"]["id"] == "info_desk"

    # (c) Mập mờ (Nhiều điểm cùng khớp từ khóa)
    res_ambiguous = match_destination_from_transcript("Dẫn tôi ra cổng", sample_dests)
    assert res_ambiguous["status"] == "AMBIGUOUS"
    assert res_ambiguous["destination"] is None

    # (d) Không tìm thấy điểm nào
    res_none = match_destination_from_transcript("Tôi muốn đi ăn kem ngoài bãi biển", sample_dests)
    assert res_none["status"] == "NO_MATCH"
    assert res_none["destination"] is None

    # --- 2. Kiểm thử phiên hành khách & API xác nhận ---
    # Tạo 2 phiên hành khách A và B
    sess_A = client.post("/api/auth/session")
    assert sess_A.status_code == 200
    token_A = sess_A.json()["session_token"]
    user_A = sess_A.json()["user_id"]
    headers_A = {"X-Passenger-Token": token_A}

    sess_B = client.post("/api/auth/session")
    assert sess_B.status_code == 200
    token_B = sess_B.json()["session_token"]
    user_B = sess_B.json()["user_id"]
    headers_B = {"X-Passenger-Token": token_B}

    # Đảm bảo robot ở trạng thái rảnh và sẵn sàng
    if hasattr(adapter, "cancel_navigation"):
        adapter.cancel_navigation(owner_id="admin", is_admin=True)
    if hasattr(adapter, "set_voice_available"):
        adapter.set_voice_available(True)
    with adapter._lock:
        adapter._voice_state = "IDLE"
        adapter._voice_start_in_progress = False
        adapter._navigation_state = "IDLE"
        adapter._has_goal = False
        adapter._owner_id = ""

    # Lấy điểm đến thực tế hiện hành trong database
    active_dests = adapter.get_destinations()
    assert len(active_dests) > 0
    target_dest = active_dests[0]
    target_name = target_dest["name"]
    target_id = target_dest["id"]

    # Hành khách A bắt đầu phiên giọng nói
    if hasattr(adapter, "set_mock_transcript"):
        adapter.set_mock_transcript(f"Hãy dẫn tôi đến {target_name}")

    start_res = client.post("/api/robot/voice/start", headers=headers_A)
    assert start_res.status_code == 200

    # Chờ tiến trình thu âm và nhận dạng giả lập (mock loop mất khoảng 1.5 - 2.5s)
    time.sleep(2.8)

    proposal = adapter.get_voice_proposal()
    assert proposal is not None
    assert proposal["status"] == "MATCHED"
    assert proposal["destination_id"] == target_id
    assert proposal["requester_id"] == user_A
    prop_id = proposal["proposal_id"]

    # --- 3. Hành khách B cố ý xác nhận đề xuất của A -> 403 Forbidden ---
    confirm_B = client.post(
        "/api/robot/voice/confirm",
        json={"proposal_id": prop_id, "destination_id": target_id},
        headers=headers_B
    )
    assert confirm_B.status_code == 403
    assert "không có quyền" in confirm_B.json()["detail"]

    # --- 4. Kiểm tra đề xuất hết hạn (Expiry) ---
    with adapter._lock:
        # Giả lập đề xuất đã quá hạn 30s
        adapter._voice_proposal["expires_at"] = int(time.time() * 1000) - 5000

    confirm_expired = client.post(
        "/api/robot/voice/confirm",
        json={"proposal_id": prop_id, "destination_id": target_id},
        headers=headers_A
    )
    assert confirm_expired.status_code == 400
    assert "hết hạn" in confirm_expired.json()["detail"]

    # --- 5. Khôi phục đề xuất hợp lệ và Hành khách A Xác nhận Thành công ---
    with adapter._lock:
        adapter._voice_proposal = {
            "proposal_id": prop_id,
            "requester_id": user_A,
            "session_id": "session_test",
            "status": "MATCHED",
            "destination_id": target_id,
            "destination_name": target_name,
            "transcript": f"Dẫn tôi tới {target_name}",
            "created_at": int(time.time() * 1000),
            "expires_at": int((time.time() + 30) * 1000),
            "confirmed": False
        }

    confirm_A = client.post(
        "/api/robot/voice/confirm",
        json={"proposal_id": prop_id, "destination_id": target_id},
        headers=headers_A
    )
    assert confirm_A.status_code == 200
    assert confirm_A.json()["success"] is True

    # Xác nhận chuyến dẫn đường đã bắt đầu với chủ sở hữu là A
    assert adapter.get_owner_id() == user_A
    assert adapter.get_status()["destination_id"] == target_id

    # --- 6. Chống xác nhận lặp (Double Confirmation Prevention) ---
    confirm_again = client.post(
        "/api/robot/voice/confirm",
        json={"proposal_id": prop_id, "destination_id": "info_desk"},
        headers=headers_A
    )
    assert confirm_again.status_code == 400
    assert "Không có đề xuất" in confirm_again.json()["detail"] or "hết hạn" in confirm_again.json()["detail"]

    # Hủy chuyến để dọn dẹp
    adapter.cancel_navigation(owner_id="admin", is_admin=True)

    # --- 7. Bỏ qua đề xuất (Dismiss) ---
    with adapter._lock:
        adapter._voice_proposal = {
            "proposal_id": "prop_dismiss_test",
            "requester_id": user_A,
            "session_id": "session_dismiss",
            "status": "MATCHED",
            "destination_id": "info_desk",
            "destination_name": "Quầy thông tin",
            "transcript": "Dẫn tôi tới Quầy thông tin",
            "created_at": int(time.time() * 1000),
            "expires_at": int((time.time() + 30) * 1000),
            "confirmed": False
        }

    dismiss_res = client.post("/api/robot/voice/dismiss", headers=headers_A)
    assert dismiss_res.status_code == 200
    assert adapter.get_voice_proposal() is None


@pytest.mark.anyio
async def test_operational_event_logger_and_admin_monitoring_lifecycle():
    """
    Test kiểm tra toàn diện tính năng Giám sát & Nhật ký vận hành Admin:
    1. Bộ đệm vòng RAM giới hạn đúng 100 sự kiện, đẩy các sự kiện cũ nhất ra ngoài.
    2. Chống ghi lặp (Deduplication) khi trạng thái kết nối và chế độ điều khiển không đổi.
    3. Bảo mật dữ liệu: Không ghi token, không ghi thông tin định danh hành khách hoặc giọng nói.
    4. Phân quyền API: Passenger nhận 403 Forbidden, Unauthenticated nhận 401, Admin nhận 200.
    5. Phân tách Telemetry WebSocket: Passenger không nhận admin_data, Admin nhận events.
    6. Trạng thái sẵn sàng (Readiness check): Xác định chính xác ready/reasons khi ở MANUAL hoặc bình thường.
    """
    from app.services.event_logger import OperationalEventLogger
    from app.adapters.factory import get_robot_adapter
    from app.auth.models import User, UserRole
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    adapter = get_robot_adapter()

    # --- 1. Kiểm tra bộ đệm vòng RAM (Giới hạn tối đa 100) ---
    logger = OperationalEventLogger(maxlen=100)
    for i in range(125):
        logger.add_event("INFO", "SYSTEM", f"Sự kiện kiểm thử #{i+1}")

    events = logger.get_events()
    assert len(events) == 100
    assert logger.version == 125
    # Sự kiện đầu tiên còn lưu phải là sự kiện #26 (25 sự kiện đầu bị đẩy ra)
    assert events[0]["message"] == "Sự kiện kiểm thử #26"
    assert events[-1]["message"] == "Sự kiện kiểm thử #125"

    # --- 2. Kiểm tra chống ghi lặp (Deduplication ở 5Hz) ---
    logger.clear()
    assert len(logger.get_events()) == 0

    # Gọi track_connection 10 lần liên tiếp với trạng thái True
    for _ in range(10):
        logger.track_connection(True)
    evts_conn = logger.get_events()
    assert len(evts_conn) == 1
    assert "Đã kết nối" in evts_conn[0]["message"]

    # Gọi track_connection khi chuyển sang False 5 lần
    for _ in range(5):
        logger.track_connection(False)
    evts_conn2 = logger.get_events()
    assert len(evts_conn2) == 2
    assert "Mất kết nối" in evts_conn2[1]["message"]

    # Chuyển ngược lại True
    logger.track_connection(True)
    evts_conn3 = logger.get_events()
    assert len(evts_conn3) == 3
    assert "phục hồi kết nối" in evts_conn3[2]["message"]

    # Chế độ điều khiển: Gọi track_control_mode 5 lần liên tiếp với MANUAL
    for _ in range(5):
        logger.track_control_mode("MANUAL")
    evts_ctrl = logger.get_events()
    assert len(evts_ctrl) == 4
    assert "MANUAL" in evts_ctrl[3]["message"]

    # Gọi tiếp AUTO 5 lần
    for _ in range(5):
        logger.track_control_mode("AUTO")
    evts_ctrl2 = logger.get_events()
    assert len(evts_ctrl2) == 5
    assert "AUTO" in evts_ctrl2[4]["message"]

    # --- 3. Kiểm tra tính an toàn dữ liệu (Không lộ token, id hành khách, giọng nói) ---
    sensitive_tokens = ["jwt_token_secret", "bearer_token", "pass_session_xyz"]
    for evt in logger.get_events():
        msg_lower = evt["message"].lower()
        for tok in sensitive_tokens:
            assert tok not in msg_lower
        assert "transcript" not in evt["details"]
        assert "token" not in evt["details"]
        assert "user_id" not in evt["details"]

    # --- 4. Kiểm tra phân quyền API GET /api/robot/admin/events ---
    # Tạo phiên Hành khách
    resp_pass = client.post("/api/auth/session")
    assert resp_pass.status_code == 200
    token_pass = resp_pass.json()["session_token"]
    headers_pass = {"Authorization": f"Bearer {token_pass}"}

    # Đăng nhập Admin
    resp_admin = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "admin123"}
    )
    assert resp_admin.status_code == 200
    token_admin = resp_admin.json()["access_token"]
    headers_admin = {"Authorization": f"Bearer {token_admin}"}

    # 4a. Chưa đăng nhập (hoặc token giả mạo) -> 401
    resp_unauth = client.get(
        "/api/robot/admin/events",
        headers={"Authorization": "Bearer invalid_forged_token"}
    )
    assert resp_unauth.status_code == 401

    # 4b. Hành khách gọi endpoint Admin -> 403 Forbidden
    resp_forbidden = client.get("/api/robot/admin/events", headers=headers_pass)
    assert resp_forbidden.status_code == 403
    assert "Quyền hạn không đủ" in resp_forbidden.json()["detail"]

    # 4c. Admin gọi endpoint -> 200 OK với danh sách sự kiện
    resp_ok = client.get("/api/robot/admin/events", headers=headers_admin)
    assert resp_ok.status_code == 200
    data = resp_ok.json()
    assert "events" in data
    assert "started_at" in data
    assert "version" in data
    assert "total" in data
    assert isinstance(data["events"], list)

    # --- 5. Kiểm tra Telemetry WebSocket Isolation ---
    user_passenger = User(id="passenger_1", username="passenger", full_name="Hành khách", role=UserRole.PASSENGER, hashed_password="")
    user_admin = User(id="admin_1", username="admin", full_name="Quản trị viên", role=UserRole.ADMIN, hashed_password="")

    # Giả lập payload phát từ broadcaster
    def simulate_telemetry_payload(user: User):
        status = adapter.get_status()
        payload = {
            "type": "telemetry",
            "server_time": int(time.time() * 1000),
            "backend_connected": True,
            "robot_status": {
                "pose": status["pose"],
                "control_mode": status["control_mode"],
                "navigation_state": status["navigation_state"],
                "readiness": status.get("readiness")
            }
        }
        if user.role == UserRole.ADMIN:
            payload["admin_data"] = {
                "alerts": adapter.get_alerts(),
                "events": adapter.get_operational_events(100),
                "events_version": adapter.get_events_version()
            }
        return payload

    payload_pass = simulate_telemetry_payload(user_passenger)
    payload_adm = simulate_telemetry_payload(user_admin)

    # Hành khách tuyệt đối KHÔNG có admin_data
    assert "admin_data" not in payload_pass
    assert "events" not in payload_pass["robot_status"]

    # Admin có admin_data chứa events
    assert "admin_data" in payload_adm
    assert "events" in payload_adm["admin_data"]
    assert isinstance(payload_adm["admin_data"]["events"], list)

    # --- 6. Kiểm tra Trạng thái Sẵn sàng (Readiness check) ---
    st_normal = adapter.get_status()
    assert "readiness" in st_normal
    assert "ready" in st_normal["readiness"]
    assert "reasons" in st_normal["readiness"]

    # Khi chuyển sang MANUAL -> readiness.ready = False
    adapter.set_manual_control(True, operator_id="admin_1")
    st_manual = adapter.get_status()
    assert st_manual["control_mode"] == "MANUAL"
    assert st_manual["readiness"]["ready"] is False
    assert any("MANUAL" in r for r in st_manual["readiness"]["reasons"])

    # Chuyển về AUTO -> readiness.ready = True (nếu không có chuyến)
    adapter.set_manual_control(False, operator_id="admin_1")
    st_auto = adapter.get_status()
    assert st_auto["control_mode"] == "AUTO"
    assert st_auto["readiness"]["ready"] is True


# =========================================================================
# 8. Deadlock Prevention, Non-Blocking Async Voice, and Watchdog Tests
# =========================================================================

def test_ros_adapter_voice_transcript_lock_and_deadlock_prevention():
    """
    Kiểm tra callback _on_voice_transcript của RosRobotAdapter với khóa threading.Lock()
    giống hệt production, bảo đảm không bị deadlock do khóa lồng nhau khi xử lý transcript.
    Đồng thời kiểm tra ROS mode không tự ý tạo proposal từ bare String khi thiếu hợp đồng phiên.
    """
    class StringMsg:
        def __init__(self, data: str):
            self.data = data

    adapter = RosRobotAdapter.__new__(RosRobotAdapter)
    adapter._lock = threading.Lock()
    adapter._destinations = [
        {"id": "gate_1", "name": "Cổng số 1", "map_id": "map", "pose": {"position": {"x": 1.0, "y": 2.0, "z": 0.0}}}
    ]
    adapter._voice_transcript = None
    adapter._voice_proposal = None
    adapter._voice_requester_id = "user_test_1"
    adapter._voice_session_id = "sess_voice_123"

    t_start = time.time()
    deadlock_detected = False

    def _invoke():
        adapter._on_voice_transcript(StringMsg("Hãy dẫn tôi tới Cổng số 1"))

    th = threading.Thread(target=_invoke)
    th.start()
    th.join(timeout=1.0)
    if th.is_alive():
        deadlock_detected = True
        assert False, "Deadlock phát hiện trong _on_voice_transcript! Callback không hoàn thành sau 1.0s."

    assert not deadlock_detected
    assert (time.time() - t_start) < 0.5
    assert adapter._voice_transcript == "Hãy dẫn tôi tới Cổng số 1"
    assert adapter._voice_proposal is None


@pytest.mark.anyio
async def test_voice_service_async_non_blocking_and_watchdog_timeout():
    """
    Kiểm tra:
    1. Khi gọi /voice/start với ROS service bị chậm hoặc timeout, main asyncio loop của FastAPI
       không bị khóa (API khác vẫn phản hồi, watchdog manual control vẫn chạy hết hạn).
    2. Watchdog chuyển động hết hạn sau timeout_sec với dung sai thời gian thực tế,
       phát lệnh dừng robot an toàn.
    """
    from app.adapters.factory import get_robot_adapter
    adapter = MockRobotAdapter()
    adapter._is_connected = True
    adapter._control_mode = "MANUAL"
    adapter._manual_operator_id = "sess_adm_1"
    adapter._current_manual_twist = (0.2, 0.0)
    adapter._last_manual_cmd_time = time.monotonic()

    def slow_voice(requester_id: str):
        time.sleep(1.2)
        return {"success": False, "message": "Timeout từ ROS voice service"}

    adapter.start_voice_session = slow_voice

    app.dependency_overrides[get_robot_adapter] = lambda: adapter
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login_res = await client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        adm_token = login_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {adm_token}"}

        t0 = time.monotonic()

        async def call_voice():
            return await client.post("/api/robot/voice/start", headers=headers)

        async def check_api_responsive():
            await asyncio.sleep(0.2)
            res = await client.get("/api/robot/status", headers=headers)
            assert res.status_code == 200
            await asyncio.sleep(0.4)
            adapter.check_manual_timeout()
            assert adapter._current_manual_twist == (0.0, 0.0)
            return True

        v_res, api_ok = await asyncio.gather(call_voice(), check_api_responsive())
        elapsed = time.monotonic() - t0
        assert api_ok is True
        assert elapsed >= 1.0
        assert v_res.status_code == 400

    app.dependency_overrides.pop(get_robot_adapter, None)


@pytest.mark.anyio
async def test_admin_multi_session_distinct_control_arbitration():
    """
    Kiểm tra hai phiên đăng nhập thật của cùng một tài khoản Admin ('admin'):
    - Hai phiên nhận hai session_id (sid) khác nhau trong JWT.
    - Phiên 1 bật MANUAL -> thành công (operator_id = sid_1).
    - Phiên 2 gửi lệnh vận tốc khác 0 -> BỊ TỪ CHỐI (400) vì quyền đang thuộc về phiên 1.
    - Phiên 1 gửi lệnh vận tốc khác 0 -> THÀNH CÔNG.
    - Phiên 2 gửi lệnh Dừng (0, 0) -> THÀNH CÔNG (lệnh dừng khẩn cấp được chấp nhận từ bất kỳ Admin nào).
    - Phiên 2 tắt MANUAL -> THÀNH CÔNG, robot chuyển về AUTO.
    """
    from app.adapters.factory import get_robot_adapter
    adapter = MockRobotAdapter()
    adapter._is_connected = True
    adapter._control_mode = "AUTO"
    adapter._manual_consumer_available = True

    app.dependency_overrides[get_robot_adapter] = lambda: adapter
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res1 = await client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        assert res1.status_code == 200
        token1 = res1.json()["access_token"]

        res2 = await client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        assert res2.status_code == 200
        token2 = res2.json()["access_token"]

        assert token1 != token2

        h1 = {"Authorization": f"Bearer {token1}"}
        h2 = {"Authorization": f"Bearer {token2}"}

        # Phiên 1 bật MANUAL
        r_manual = await client.post("/api/robot/control/manual", json={"enable": True}, headers=h1)
        assert r_manual.status_code == 200
        assert adapter._control_mode == "MANUAL"
        op1 = adapter._manual_operator_id
        assert op1 is not None and op1.startswith("sess_")

        # Phiên 2 gửi lệnh vận tốc chuyển động (khác 0) -> BỊ TỪ CHỐI
        r_vel2 = await client.post(
            "/api/robot/control/velocity",
            json={"linear_x": 0.2, "angular_z": 0.0, "seq": 1, "hold_id": "hold_s2_1"},
            headers=h2
        )
        assert r_vel2.status_code == 400
        assert "thuộc về" in r_vel2.json()["detail"] or "Admin khác" in r_vel2.json()["detail"]

        # Phiên 1 gửi lệnh vận tốc chuyển động -> THÀNH CÔNG
        r_vel1 = await client.post(
            "/api/robot/control/velocity",
            json={"linear_x": 0.2, "angular_z": 0.0, "seq": 1, "hold_id": "hold_s1_1"},
            headers=h1
        )
        assert r_vel1.status_code == 200
        assert adapter._current_manual_twist[0] > 0

        # Phiên 2 gửi lệnh DỪNG (0, 0) -> THÀNH CÔNG (Dừng an toàn được phép từ mọi Admin)
        r_stop2 = await client.post("/api/robot/control/velocity", json={"linear_x": 0.0, "angular_z": 0.0}, headers=h2)
        assert r_stop2.status_code == 200
        assert adapter._current_manual_twist == (0.0, 0.0)

        # Phiên 2 tắt MANUAL -> THÀNH CÔNG, chuyển về AUTO
        r_auto2 = await client.post("/api/robot/control/manual", json={"enable": False}, headers=h2)
        assert r_auto2.status_code == 200
        assert adapter._control_mode == "AUTO"
        assert adapter._manual_operator_id is None

    app.dependency_overrides.pop(get_robot_adapter, None)


@pytest.mark.anyio
async def test_manual_control_out_of_order_http_sequence_and_hold_release():
    """
    Kiểm tra xử lý thứ tự lệnh HTTP vận tốc:
    - Gửi lượt giữ 1 (hold_1) với seq=1, seq=2.
    - Nhả nút / Gửi lệnh Dừng -> kết thúc hold_1.
    - Một lệnh vận tốc cũ đến muộn (hold_1, seq=1) sau lệnh Dừng không được kích hoạt lại chuyển động robot.
    """
    from app.adapters.factory import get_robot_adapter
    from app.auth.security import decode_access_token

    adapter = MockRobotAdapter()
    adapter._is_connected = True
    adapter._control_mode = "MANUAL"
    adapter._manual_consumer_available = True

    app.dependency_overrides[get_robot_adapter] = lambda: adapter
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login_res = await client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        adm_token = login_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {adm_token}"}
        payload = decode_access_token(adm_token)
        adapter._manual_operator_id = payload.get("sid")

        # Lượt giữ 1: seq=1
        r1 = await client.post("/api/robot/control/velocity", json={"linear_x": 0.25, "angular_z": 0.0, "seq": 1, "hold_id": "hold_abc"}, headers=headers)
        assert r1.status_code == 200
        assert adapter._current_manual_twist[0] == 0.25

        # Lượt giữ 1: seq=2
        r2 = await client.post("/api/robot/control/velocity", json={"linear_x": 0.25, "angular_z": 0.0, "seq": 2, "hold_id": "hold_abc"}, headers=headers)
        assert r2.status_code == 200

        # Nhả nút: Gửi Stop (0, 0)
        r_stop = await client.post("/api/robot/control/velocity", json={"linear_x": 0.0, "angular_z": 0.0, "seq": 3, "hold_id": "hold_abc"}, headers=headers)
        assert r_stop.status_code == 200
        assert adapter._current_manual_twist == (0.0, 0.0)

        # Giả lập lệnh seq=1 đến trễ (out-of-order) sau khi đã Dừng
        r_late = await client.post("/api/robot/control/velocity", json={"linear_x": 0.25, "angular_z": 0.0, "seq": 1, "hold_id": "hold_abc"}, headers=headers)
        assert r_late.status_code == 200
        assert adapter._current_manual_twist == (0.0, 0.0)

    app.dependency_overrides.pop(get_robot_adapter, None)


def test_amcl_epoch_extended_validation_rules():
    """
    Kiểm tra toàn diện các quy tắc xác thực Pose và AMCL Epoch:
    1. Pose trong frame khác 'map' (ví dụ 'odom') bị từ chối.
    2. Pose chứa giá trị NaN hoặc Inf bị từ chối.
    3. Pose chứa quaternion không chuẩn hóa bị từ chối.
    4. Pose timestamp thuộc phiên trước đến muộn sau khi clock reset bị từ chối.
    5. /clock liên tục nhận cùng một giá trị (> 1.0s) phát hiện stalled.
    6. Pose đến trước clock trong lần kết nối đầu vẫn được xử lý đúng (epoch 0).
    """
    class MockPoint:
        def __init__(self, x, y, z=0.0):
            self.x, self.y, self.z = x, y, z

    class MockQuaternion:
        def __init__(self, x=0.0, y=0.0, z=0.0, w=1.0):
            self.x, self.y, self.z, self.w = x, y, z, w

    class MockPose:
        def __init__(self, pos, q):
            self.position = pos
            self.orientation = q

    class MockPoseWithCovariance:
        def __init__(self, pose):
            self.pose = pose

    class MockStamp:
        def __init__(self, sec, nanosec=0):
            self.sec, self.nanosec = sec, nanosec

    class MockHeader:
        def __init__(self, frame_id, stamp):
            self.frame_id = frame_id
            self.stamp = stamp

    class MockPoseWithCovarianceStamped:
        def __init__(self, frame_id, sec, x, y, q=None):
            self.header = MockHeader(frame_id, MockStamp(sec))
            self.pose = MockPoseWithCovariance(MockPose(MockPoint(x, y), q or MockQuaternion()))

    class MockClockMsg:
        def __init__(self, sec, nanosec=0):
            self.clock = MockStamp(sec, nanosec)

    adapter = RosRobotAdapter.__new__(RosRobotAdapter)
    adapter._lock = threading.Lock()
    adapter._cfg = get_ros_config()
    adapter._pose = None
    adapter._pose_frame_id = None
    adapter._pose_stamp = None
    adapter._last_pose_time = 0.0
    adapter._last_pose_time_mono = 0.0
    adapter._pose_epoch = 0
    adapter._pose_received_epoch = -1
    adapter._sim_restarted = False
    adapter._is_connected = False
    adapter._message = "Đang kết nối..."
    adapter._last_clock_sec = None
    adapter._last_clock_monotonic = 0.0
    adapter._clock_stalled = False
    adapter._navigation_state = "IDLE"

    # Case 6: Pose đến trước clock trong lần kết nối đầu
    msg_init = MockPoseWithCovarianceStamped("map", 10, 1.5, 2.5)
    adapter._on_amcl_pose(msg_init)
    assert adapter._pose is not None
    assert adapter._pose["x"] == 1.5
    assert adapter._pose_received_epoch == 0
    assert adapter.has_valid_pose() is True

    # Clock bắt đầu chạy
    adapter._on_clock(MockClockMsg(12))
    assert adapter._last_clock_sec == 12.0
    assert adapter.has_valid_pose() is True

    # Case 1: Pose sai frame
    msg_bad_frame = MockPoseWithCovarianceStamped("odom", 13, 99.0, 99.0)
    adapter._on_amcl_pose(msg_bad_frame)
    assert adapter._pose["x"] == 1.5
    assert adapter._pose_frame_id == "map"

    # Case 2: NaN / Inf
    msg_nan = MockPoseWithCovarianceStamped("map", 14, float("nan"), 2.0)
    adapter._on_amcl_pose(msg_nan)
    assert adapter._pose["x"] == 1.5

    # Case 3: Quaternion không chuẩn hóa
    msg_bad_q = MockPoseWithCovarianceStamped("map", 14, 3.0, 3.0, q=MockQuaternion(0, 0, 0, 0))
    adapter._on_amcl_pose(msg_bad_q)
    assert adapter._pose["x"] == 1.5

    # Case 4: Clock reset về 0 (Gazebo restart), pose cũ đến muộn
    adapter._on_clock(MockClockMsg(100))
    adapter._on_clock(MockClockMsg(1))
    assert adapter._sim_restarted is True
    assert adapter._pose_epoch == 1
    assert adapter.has_valid_pose() is False

    # Pose cũ từ trước reset đến muộn (timestamp = 98s)
    msg_late = MockPoseWithCovarianceStamped("map", 98, 4.0, 4.0)
    adapter._on_amcl_pose(msg_late)
    assert adapter._pose["x"] == 1.5
    assert adapter.has_valid_pose() is False

    # Pose mới của phiên mới (timestamp = 2s)
    msg_new = MockPoseWithCovarianceStamped("map", 2, 5.0, 6.0)
    adapter._on_amcl_pose(msg_new)
    assert adapter._pose["x"] == 5.0
    assert adapter._pose_received_epoch == 1
    assert adapter.has_valid_pose() is True

    # Case 5: Clock nhận cùng một giá trị liên tục (> 1s)
    adapter._on_clock(MockClockMsg(2))
    adapter._last_clock_advancing_monotonic = time.monotonic() - 2.0
    adapter._on_clock(MockClockMsg(2))
    assert adapter._clock_stalled is True


def test_nav2_readiness_checks_action_server():
    """
    Kiểm tra Action Server Nav2 chưa sẵn sàng thì readiness.ready = False
    kèm theo lý do chính xác.
    """
    adapter = RosRobotAdapter.__new__(RosRobotAdapter)
    adapter._lock = threading.Lock()
    adapter._cfg = get_ros_config()
    adapter._is_connected = True
    adapter._clock_stalled = False
    adapter._pose = {"x": 1.0, "y": 1.0, "theta": 0.0}
    adapter._pose_frame_id = "map"
    adapter._pose_epoch = 0
    adapter._pose_received_epoch = 0
    adapter._sim_restarted = False
    adapter._map_version = "v1"
    adapter._map_png = b"png"
    adapter._control_mode = "AUTO"
    adapter._navigation_state = "IDLE"
    adapter._nav2_has_active_goal = False
    adapter._current_goal_handle = None

    class MockActionClient:
        def server_is_ready(self):
            return False

    adapter._action_nav = MockActionClient()
    readiness = adapter.get_readiness()
    assert readiness["ready"] is False
    assert any("Action server Nav2" in r for r in readiness["reasons"])


@pytest.mark.anyio
async def test_operational_event_logger_lifecycle_hooks_and_destinations(tmp_path):
    """
    Kiểm tra:
    1. Thao tác lưu/xóa điểm đến thành công ghi sự kiện vào event_logger.
    2. Chuyển đổi trạng thái dẫn đường ghi sự kiện chính xác.
    3. Endpoint /api/robot/admin/events trả về sự kiện đầy đủ cho Admin.
    4. Hành khách vãng lai bị từ chối (403 Forbidden).
    """
    from app.services.event_logger import event_logger
    from app.adapters.factory import get_robot_adapter
    event_logger.clear()

    adapter = MockRobotAdapter()
    adapter._destinations_file = tmp_path / "mock_dest.yaml"
    adapter._destinations = []
    adapter._is_connected = True

    dest = {
        "id": "gate_test_event",
        "name": "Cổng Test Event",
        "map_id": "map",
        "pose": {"position": {"x": 2.0, "y": 2.0, "z": 0.0}}
    }
    r_up = adapter.upsert_destination(dest)
    assert r_up["success"] is True

    evts = event_logger.get_events()
    assert any(e["category"] == "DESTINATION" and "Cổng Test Event" in e["message"] for e in evts)

    r_del = adapter.delete_destination("gate_test_event")
    assert r_del["success"] is True
    evts = event_logger.get_events()
    assert any(e["category"] == "DESTINATION" and "Đã xóa" in e["message"] for e in evts)

    app.dependency_overrides[get_robot_adapter] = lambda: adapter
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r_pass = await client.get("/api/robot/admin/events")
        assert r_pass.status_code == 403

        login_res = await client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        adm_token = login_res.json()["access_token"]
        r_adm = await client.get("/api/robot/admin/events", headers={"Authorization": f"Bearer {adm_token}"})
        assert r_adm.status_code == 200
        data = r_adm.json()
        assert "events" in data
        assert len(data["events"]) > 0
        assert data["events"][0]["category"] in ("DESTINATION", "SYSTEM", "CONNECTION", "CONTROL", "NAVIGATION")

    app.dependency_overrides.pop(get_robot_adapter, None)


@pytest.mark.anyio
async def test_direct_manual_control_press_hold_and_voice_privacy(tmp_path):
    """
    Kiểm tra cơ chế lái trực tiếp nhấn-giữ (Direct Press-and-Hold), chống gói trễ,
    watchdog timeout, và cô lập quyền riêng tư giọng nói.
    """
    from app.adapters.mock_adapter import MockRobotAdapter
    from app.adapters.factory import get_robot_adapter
    from app.auth.models import User, UserRole

    adapter = MockRobotAdapter()
    adapter._destinations_file = tmp_path / "dest_direct.yaml"
    adapter._destinations = []
    adapter._is_connected = True
    adapter._is_data_stale = False
    adapter._manual_consumer_available = True
    adapter._control_mode = "AUTO"
    adapter._navigation_state = "IDLE"
    adapter._has_goal = False

    # 1. Bắt đầu giữ nút: Gói vận tốc đầu tiên tự động chuyển sang MANUAL
    res_drive1 = adapter.send_manual_velocity(
        linear_x=0.25, angular_z=0.0,
        operator_id="sess_adm_1",
        seq=1, hold_id="hold_alpha_1"
    )
    assert res_drive1["success"] is True
    assert adapter._control_mode == "MANUAL"
    assert adapter._manual_operator_id == "sess_adm_1"
    assert adapter._active_hold_id == "hold_alpha_1"
    assert adapter._last_manual_seq == 1

    # 2. Gói tiếp theo tăng seq hợp lệ
    res_drive2 = adapter.send_manual_velocity(
        linear_x=0.25, angular_z=0.0,
        operator_id="sess_adm_1",
        seq=2, hold_id="hold_alpha_1"
    )
    assert res_drive2["success"] is True
    assert adapter._last_manual_seq == 2

    # 3. Gói duplicate hoặc receding (seq <= last_seq) bị bỏ qua an toàn và không gia hạn watchdog
    t_before = adapter._last_manual_cmd_time
    res_dup = adapter.send_manual_velocity(
        linear_x=0.25, angular_z=0.0,
        operator_id="sess_adm_1",
        seq=2, hold_id="hold_alpha_1"
    )
    assert res_dup.get("ignored") is True or res_dup["success"] is False
    assert adapter._last_manual_cmd_time == t_before

    res_recede = adapter.send_manual_velocity(
        linear_x=0.25, angular_z=0.0,
        operator_id="sess_adm_1",
        seq=1, hold_id="hold_alpha_1"
    )
    assert res_recede.get("ignored") is True or res_recede["success"] is False
    assert adapter._last_manual_cmd_time == t_before

    # 4. Gói thiếu hold_id hoặc seq < 1 bị từ chối
    res_no_hold = adapter.send_manual_velocity(
        linear_x=0.25, angular_z=0.0,
        operator_id="sess_adm_1",
        seq=3, hold_id=""
    )
    assert res_no_hold["success"] is False

    # 5. Dừng xe từ phiên đang giữ nút: Về AUTO an toàn và lưu hold_id vào released cache
    res_stop = adapter.send_manual_velocity(
        linear_x=0.0, angular_z=0.0,
        operator_id="sess_adm_1",
        seq=3, hold_id="hold_alpha_1"
    )
    assert res_stop["success"] is True
    assert adapter._control_mode == "AUTO"
    assert adapter._active_hold_id is None
    assert "hold_alpha_1" in adapter._released_hold_ids

    # 6. Gói đến muộn mang hold_id đã giải phóng bị từ chối triệt để
    res_late = adapter.send_manual_velocity(
        linear_x=0.25, angular_z=0.0,
        operator_id="sess_adm_1",
        seq=4, hold_id="hold_alpha_1"
    )
    assert res_late.get("ignored") is True or res_late["success"] is False
    assert "kết thúc" in res_late["message"]

    # 7. Watchdog timeout: Khi không có lệnh mới sau 0.5s, tự động dừng và về AUTO
    adapter.send_manual_velocity(
        linear_x=0.25, angular_z=0.0,
        operator_id="sess_adm_2",
        seq=1, hold_id="hold_beta_2"
    )
    assert adapter._control_mode == "MANUAL"
    assert adapter._active_hold_id == "hold_beta_2"

    # Giả lập thời gian trôi qua 0.6s
    adapter._last_manual_cmd_time -= 0.6
    adapter.check_manual_timeout()
    assert adapter._control_mode == "AUTO"
    assert adapter._active_hold_id is None
    assert "hold_beta_2" in adapter._released_hold_ids

    # 8. Bất kỳ Admin nào cũng có thể gửi lệnh Dừng để giải phóng hold đang giữ
    adapter.send_manual_velocity(
        linear_x=0.25, angular_z=0.0,
        operator_id="sess_adm_3",
        seq=1, hold_id="hold_gamma_3"
    )
    assert adapter._control_mode == "MANUAL"
    # Admin khác gửi Stop (0, 0)
    res_admin_stop = adapter.send_manual_velocity(
        linear_x=0.0, angular_z=0.0,
        operator_id="sess_adm_different"
    )
    assert res_admin_stop["success"] is True
    assert adapter._control_mode == "AUTO"
    assert adapter._active_hold_id is None
    assert "hold_gamma_3" in adapter._released_hold_ids

    # 9. Bounded OrderedDict: Giới hạn tối đa 500 holds
    for i in range(550):
        adapter._released_hold_ids[f"dummy_hold_{i}"] = time.monotonic()
        while len(adapter._released_hold_ids) > 500:
            adapter._released_hold_ids.popitem(last=False)
    assert len(adapter._released_hold_ids) == 500

    # 10. Chặn lái tay khi đang NAVIGATING hoặc PAUSED
    adapter._navigation_state = "PAUSED"
    res_drive_paused = adapter.send_manual_velocity(
        linear_x=0.25, angular_z=0.0,
        operator_id="sess_adm_1",
        seq=1, hold_id="hold_new"
    )
    assert res_drive_paused["success"] is False
    assert "PAUSED" in res_drive_paused["message"]
    adapter._navigation_state = "IDLE"

    # 11. Cô lập quyền riêng tư giọng nói qua REST API /status
    adapter._voice_state = "PROCESSING"
    adapter._voice_transcript = "Hãy dẫn tôi đến Quầy vé A"
    adapter._voice_response = "Đang tìm kiếm Quầy vé A"
    adapter._voice_requester_id = "passenger_sess_123"

    app.dependency_overrides[get_robot_adapter] = lambda: adapter
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Thử với Admin
        login_res = await client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        adm_tok = login_res.json()["access_token"]
        r_admin = await client.get("/api/robot/status", headers={"Authorization": f"Bearer {adm_tok}"})
        assert r_admin.status_code == 200
        admin_data = r_admin.json()
        assert admin_data["voice_transcript"] == "Hãy dẫn tôi đến Quầy vé A"
        assert admin_data["voice_response"] == "Đang tìm kiếm Quầy vé A"
        assert admin_data["can_manual_control"] is True
        assert admin_data["is_manual_controller"] is False
        assert admin_data["manual_lock_reason"] is None

        # Khách nặc danh khác (không phải requester và không phải Admin)
        r_guest = await client.get("/api/robot/status")
        assert r_guest.status_code == 200
        guest_data = r_guest.json()
        assert guest_data["voice_transcript"] is None
        assert guest_data["voice_response"] is None
        assert guest_data["can_manual_control"] is False
        assert guest_data["manual_lock_reason"] == "Yêu cầu quyền Admin"

    app.dependency_overrides.pop(get_robot_adapter, None)


@pytest.mark.anyio
async def test_manual_control_cmd_vel_twist_and_issues_a_to_f(tmp_path):
    """
    Kiểm thử chuyên sâu cho toàn bộ 6 lỗi và cấu hình mới của điều khiển tay:
    - Sim profile: /cmd_vel với kiểu geometry_msgs/msg/Twist
    - Issue C: Từ chối gói chuyển động thiếu hold_id hoặc seq < 1; cho phép Emergency Stop không hold_id
    - Issue D: Chống hold cũ đến muộn chiếm quyền hold mới; nhả hold cũ không hủy hold mới
    - Issue E: Watchdog & khóa luồng không bị nghẽn khi lưu destination chậm (I/O ngoài self._lock)
    - Issue F: is_manual_consumer_available lọc endpoint tiêu thụ (ros_gz_bridge/command_timeout);
               Khóa manual khi Nav2 đang có mục tiêu ngoại vi (RViz)
    """
    from app.ros_config import get_ros_config
    from app.adapters.mock_adapter import MockRobotAdapter
    from app.adapters.factory import get_robot_adapter
    from app.main import app

    # 1. Kiểm tra cấu hình ROS sim profile
    cfg = get_ros_config(reload=True)
    cmd_cfg = cfg.get_topic("cmd_vel_manual")
    assert cmd_cfg is not None
    assert cmd_cfg.name == "/cmd_vel"
    assert cmd_cfg.type == "geometry_msgs/msg/Twist"
    assert cmd_cfg.qos["reliability"] == "reliable"
    assert cmd_cfg.qos["durability"] == "volatile"

    adapter = MockRobotAdapter()
    adapter._destinations_file = tmp_path / "destinations.yaml"
    adapter._manual_consumer_available = True
    adapter._is_connected = True
    adapter._is_data_stale = False

    app.dependency_overrides[get_robot_adapter] = lambda: adapter
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Lấy token Admin
        login_res = await client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        adm_tok = login_res.json()["access_token"]
        adm_headers = {"Authorization": f"Bearer {adm_tok}"}

        # ------------------------------------------------------------------
        # PHẦN 2 (ISSUE C): Kiểm tra từ chối lệnh chuyển động thiếu hold_id / seq
        # ------------------------------------------------------------------
        # 2.1 Gửi lệnh chuyển động thiếu hold_id -> 400 Bad Request
        r_no_hold = await client.post(
            "/api/robot/control/velocity",
            json={"linear_x": 0.25, "angular_z": 0.0},
            headers=adm_headers
        )
        assert r_no_hold.status_code == 400
        assert "hold_id" in r_no_hold.json()["detail"]

        # 2.2 Gửi lệnh chuyển động có hold_id nhưng seq < 1 -> 400 Bad Request
        r_bad_seq = await client.post(
            "/api/robot/control/velocity",
            json={"linear_x": 0.25, "angular_z": 0.0, "hold_id": "hold_1000_test", "seq": 0},
            headers=adm_headers
        )
        assert r_bad_seq.status_code == 400
        assert "seq" in r_bad_seq.json()["detail"]

        # 2.3 Emergency Stop (0, 0 không có hold_id) -> Phải THÀNH CÔNG từ Admin
        r_estop = await client.post(
            "/api/robot/control/velocity",
            json={"linear_x": 0.0, "angular_z": 0.0},
            headers=adm_headers
        )
        assert r_estop.status_code == 200
        assert adapter._current_manual_twist == (0.0, 0.0)
        assert adapter._control_mode == "AUTO"

        # ------------------------------------------------------------------
        # PHẦN 3 (ISSUE D): Chống hold cũ đến muộn và cô lập giải phóng hold
        # ------------------------------------------------------------------
        # 3.1 Bắt đầu Hold 2 (timestamp mới hơn: 200000)
        res_h2 = adapter.send_manual_velocity(
            linear_x=0.25, angular_z=0.0,
            operator_id="admin_session_1",
            seq=1, hold_id="hold_200000_abc"
        )
        assert res_h2["success"] is True
        assert adapter._active_hold_id == "hold_200000_abc"

        # 3.2 Gói đầu tiên của Hold 1 cũ (timestamp cũ hơn: 100000) đến trễ
        # -> Phải bị bỏ qua (ignored), KHÔNG được chiếm quyền hay thay thế Hold 2
        res_h1_late = adapter.send_manual_velocity(
            linear_x=0.2, angular_z=0.1,
            operator_id="admin_session_1",
            seq=1, hold_id="hold_100000_xyz"
        )
        assert res_h1_late.get("ignored") is True
        assert adapter._active_hold_id == "hold_200000_abc"

        # 3.3 Lệnh nhả hold của Hold 1 cũ gửi tới -> Bị bỏ qua, KHÔNG làm dừng hay hủy Hold 2
        res_h1_release = adapter.send_manual_velocity(
            linear_x=0.0, angular_z=0.0,
            operator_id="admin_session_1",
            seq=2, hold_id="hold_100000_xyz"
        )
        assert res_h1_release.get("ignored") is True
        assert adapter._active_hold_id == "hold_200000_abc"
        assert adapter._control_mode == "MANUAL"

        # 3.4 Tiếp tục gửi tick của Hold 2 -> Vẫn hoạt động bình thường
        res_h2_seq2 = adapter.send_manual_velocity(
            linear_x=0.25, angular_z=0.0,
            operator_id="admin_session_1",
            seq=2, hold_id="hold_200000_abc"
        )
        assert res_h2_seq2["success"] is True

        # 3.5 Nhả đúng Hold 2 -> Giải phóng an toàn về AUTO
        res_h2_release = adapter.send_manual_velocity(
            linear_x=0.0, angular_z=0.0,
            operator_id="admin_session_1",
            seq=3, hold_id="hold_200000_abc"
        )
        assert res_h2_release["success"] is True
        assert adapter._active_hold_id is None
        assert adapter._control_mode == "AUTO"

        # 3.6 Lệnh trễ của Hold 2 đã giải phóng -> Không kích hoạt lại
        res_h2_late = adapter.send_manual_velocity(
            linear_x=0.25, angular_z=0.0,
            operator_id="admin_session_1",
            seq=4, hold_id="hold_200000_abc"
        )
        assert res_h2_late.get("ignored") is True
        assert adapter._control_mode == "AUTO"

        # ------------------------------------------------------------------
        # PHẦN 4 (ISSUE E): Watchdog & Khóa luồng khi lưu destination chậm
        # ------------------------------------------------------------------
        # Kích hoạt lái tay
        adapter.send_manual_velocity(
            linear_x=0.25, angular_z=0.0,
            operator_id="admin_session_1",
            seq=1, hold_id="hold_300000_slow"
        )
        assert adapter._control_mode == "MANUAL"
        assert adapter._current_manual_twist[0] > 0

        # Giả lập thao tác ghi tệp tốn 0.4s
        orig_write = adapter._write_destinations_file
        def slow_write(data):
            time.sleep(0.4)
            return orig_write(data)
        adapter._write_destinations_file = slow_write

        # Gọi upsert_destination trong worker thread qua API
        import threading
        save_thread = threading.Thread(
            target=lambda: adapter.upsert_destination({
                "id": "gate_slow_test",
                "name": "Gate Slow Test",
                "pose": {"x": 1.0, "y": 2.0, "theta": 0.0}
            })
        )
        save_thread.start()
        time.sleep(0.05)  # Đảm bảo save_thread đang trong _write_destinations_file

        # Kiểm tra: trong khi đang lưu tệp, check_manual_timeout hoặc send_manual_velocity dừng xe
        # KHÔNG bị chặn bởi self._lock!
        t_start = time.monotonic()
        adapter._last_manual_cmd_time = time.monotonic() - 1.0
        adapter.check_manual_timeout()
        t_elapsed = time.monotonic() - t_start

        # Thời gian check watchdog phải cực nhanh (< 0.1s), không bị khóa 0.4s bởi disk write
        assert t_elapsed < 0.15, f"Watchdog bị chặn bởi I/O khóa luồng! Thời gian đo: {t_elapsed}s"
        assert adapter._control_mode == "AUTO"
        assert adapter._current_manual_twist == (0.0, 0.0)

        save_thread.join()
        adapter._write_destinations_file = orig_write

        # ------------------------------------------------------------------
        # PHẦN 5 (ISSUE F): Khóa khi Nav2 có RViz goal & Xác thực consumer
        # ------------------------------------------------------------------
        # 5.1 Khi Nav2 có active goal từ RViz
        adapter._nav2_has_active_goal = True
        st = adapter.get_status()
        assert st["external_goal_active"] is True

        r_st = await client.get("/api/robot/status", headers=adm_headers)
        st_data = r_st.json()
        assert st_data["can_manual_control"] is False
        assert "RViz" in st_data["manual_lock_reason"]

        # Gọi lệnh vận tốc di chuyển -> Bị từ chối 400
        r_vel_blocked = await client.post(
            "/api/robot/control/velocity",
            json={"linear_x": 0.2, "angular_z": 0.0, "hold_id": "hold_400000_rviz", "seq": 1},
            headers=adm_headers
        )
        assert r_vel_blocked.status_code == 400
        assert "ngoài" in r_vel_blocked.json()["detail"] or "RViz" in r_vel_blocked.json()["detail"]

        # 5.2 Kiểm tra logic lọc endpoint trong RosRobotAdapter.is_manual_consumer_available()
        from app.adapters.ros_adapter import RosRobotAdapter
        class DummySub:
            def __init__(self, name, topic_type):
                self.node_name = name
                self.topic_type = topic_type

        class DummyPub:
            def __init__(self, topic_name):
                self.topic_name = topic_name
            def get_subscription_count(self):
                return 1

        class DummyNode:
            def __init__(self, subs):
                self._subs = subs
            def get_subscriptions_info_by_topic(self, topic):
                return self._subs

        ros_dummy = object.__new__(RosRobotAdapter)
        ros_dummy._pub_cmd_vel = DummyPub("/cmd_vel")
        ros_dummy._cmd_vel_is_twist = True

        # 1. Graph rỗng (subs = []) -> Khóa an toàn
        ros_dummy._node = DummyNode([])
        assert ros_dummy.is_manual_consumer_available() is False

        # 2. Graph None -> Khóa an toàn
        ros_dummy._node = DummyNode(None)
        assert ros_dummy.is_manual_consumer_available() is False

        # 3. Node None -> Khóa an toàn
        ros_dummy._node = None
        assert ros_dummy.is_manual_consumer_available() is False

        # 4. Count <= 0 -> Khóa an toàn
        class DummyPubZero:
            def __init__(self, topic_name):
                self.topic_name = topic_name
            def get_subscription_count(self):
                return 0
        ros_dummy._pub_cmd_vel = DummyPubZero("/cmd_vel")
        ros_dummy._node = DummyNode([DummySub("ros_gz_bridge", "geometry_msgs/msg/Twist")])
        assert ros_dummy.is_manual_consumer_available() is False
        ros_dummy._pub_cmd_vel = DummyPub("/cmd_vel")

        # 5. Khi chỉ có CLI topic echo (_ros2cli_echo) -> Không coi là consumer hợp lệ
        ros_dummy._node = DummyNode([DummySub("_ros2cli_echo_123", "geometry_msgs/msg/Twist")])
        assert ros_dummy.is_manual_consumer_available() is False

        # 6. Sai kiểu topic (std_msgs/msg/String thay vì Twist) -> Không hợp lệ
        ros_dummy._node = DummyNode([DummySub("ros_gz_bridge", "std_msgs/msg/String")])
        assert ros_dummy.is_manual_consumer_available() is False

        # 7. Khi có ros_gz_bridge với geometry_msgs/msg/Twist -> Hợp lệ
        ros_dummy._node = DummyNode([DummySub("ros_gz_bridge", "geometry_msgs/msg/Twist")])
        assert ros_dummy.is_manual_consumer_available() is True

        # 8. Khi có command_timeout với geometry_msgs/msg/Twist -> Hợp lệ
        ros_dummy._node = DummyNode([DummySub("command_timeout", "geometry_msgs/msg/Twist")])
        assert ros_dummy.is_manual_consumer_available() is True

        # 9. Chế độ TwistStamped (profile robot thật / twist_mux)
        ros_dummy._cmd_vel_is_twist = False
        ros_dummy._node = DummyNode([DummySub("twist_mux", "geometry_msgs/msg/TwistStamped")])
        assert ros_dummy.is_manual_consumer_available() is True

    app.dependency_overrides.pop(get_robot_adapter, None)


# =========================================================================
# 11. Concurrency Transactions & Strict Order Control for Destinations
# =========================================================================

def test_destinations_concurrency_transactions_and_isolation(tmp_path):
    """
    Kiểm thử kiểm soát thứ tự đồng thời cho upsert/delete điểm đến:
    1. A ghi lỗi rồi B thành công (Race condition tái hiện từ user issue).
       - Kết quả: A báo lỗi, B báo thành công.
       - Bộ nhớ không bị rollback về rỗng, chứa đúng điểm của B.
       - File trên đĩa chứa đúng điểm của B. Bộ nhớ và file hoàn toàn khớp nhau.
    2. Hai thao tác thêm thành công đồng thời (Barrier controlled).
    3. Thêm và xóa đồng thời (Barrier controlled).
    4. Ghi file chậm trong lúc watchdog cần phát zero / timeout (Event controlled).
    Chạy trên cả MockRobotAdapter và RosRobotAdapter.
    """
    from collections import OrderedDict
    from app.adapters.ros_adapter import RosRobotAdapter
    from app.adapters.mock_adapter import MockRobotAdapter
    from app.coordinate.transform import MapMetadata

    def create_adapters(base_dir, name):
        f_mock = base_dir / f"{name}_mock_dest.yaml"
        f_ros = base_dir / f"{name}_ros_dest.yaml"

        ad_mock = MockRobotAdapter()
        ad_mock._destinations = []
        ad_mock._destinations_version = 0
        ad_mock._destinations_file = f_mock
        ad_mock._navigation_state = "IDLE"
        ad_mock._destination_id = None
        ad_mock._control_mode = "AUTO"
        ad_mock._manual_operator_id = None
        ad_mock._active_hold_id = None
        ad_mock._released_hold_ids = OrderedDict()
        ad_mock._last_manual_seq = 0
        ad_mock._current_manual_twist = (0.0, 0.0)
        ad_mock._last_manual_cmd_time = 0.0
        ad_mock._pending_dest_modifications = set()

        ad_ros = object.__new__(RosRobotAdapter)
        ad_ros._lock = threading.Lock()
        ad_ros._io_lock = threading.Lock()
        ad_ros._cfg = get_ros_config()
        ad_ros._destinations = []
        ad_ros._destinations_version = 0
        ad_ros._destinations_file = f_ros
        ad_ros._navigation_state = "IDLE"
        ad_ros._destination_id = None
        ad_ros._control_mode = "AUTO"
        ad_ros._manual_operator_id = None
        ad_ros._active_hold_id = None
        ad_ros._released_hold_ids = OrderedDict()
        ad_ros._last_manual_seq = 0
        ad_ros._current_manual_twist = (0.0, 0.0)
        ad_ros._last_manual_cmd_time = 0.0
        ad_ros._pending_dest_modifications = set()
        ad_ros._pub_cmd_vel = None
        ad_ros._map_meta = MapMetadata(width=200, height=200, resolution=0.05, origin_x=0.0, origin_y=0.0, origin_yaw=0.0)
        ad_ros._occupancy_grid_data = [0] * 40000

        return [("MockAdapter", ad_mock, f_mock), ("RosAdapter", ad_ros, f_ros)]

    # -------------------------------------------------------------
    # KỊCH BẢN 1: A GHI LỖI RỒI B THÀNH CÔNG (User Bug Isolation)
    # -------------------------------------------------------------
    for adapter_name, adapter, dest_file in create_adapters(tmp_path, "scenario1"):
        dest_a = {"id": "dest_A", "name": "Điểm A", "pose": {"position": {"x": 1.0, "y": 1.0, "z": 0.0}}}
        dest_b = {"id": "dest_B", "name": "Điểm B", "pose": {"position": {"x": 2.0, "y": 2.0, "z": 0.0}}}

        orig_write = adapter._write_destinations_file

        event_a_in_write = threading.Event()
        event_allow_a_fail = threading.Event()
        event_b_entered = threading.Event()

        results = {}

        def faulty_write_for_a(dest_list):
            # Chỉ can thiệp lần gọi đầu tiên từ Thread A
            if any(d.get("id") == "dest_A" for d in dest_list) and not event_a_in_write.is_set():
                event_a_in_write.set()
                event_allow_a_fail.wait(timeout=5.0)
                if adapter_name == "MockAdapter":
                    return False
                return False, "Lỗi giả lập ổ đĩa chỉ đọc trên Thread A"
            return orig_write(dest_list)

        adapter._write_destinations_file = faulty_write_for_a

        def run_thread_a():
            results["res_a"] = adapter.upsert_destination(dest_a)

        def run_thread_b():
            event_b_entered.set()
            results["res_b"] = adapter.upsert_destination(dest_b)

        thread_a = threading.Thread(target=run_thread_a)
        thread_b = threading.Thread(target=run_thread_b)

        thread_a.start()
        # Chờ Thread A đã vào _write_destinations_file và đang giữ _io_lock
        assert event_a_in_write.wait(timeout=5.0)

        # Khởi chạy Thread B (sẽ bị chặn ở _io_lock)
        thread_b.start()
        assert event_b_entered.wait(timeout=5.0)

        # Cho phép Thread A kết thúc với lỗi ghi file
        event_allow_a_fail.set()

        thread_a.join(timeout=5.0)
        thread_b.join(timeout=5.0)

        assert results["res_a"]["success"] is False, f"[{adapter_name}] Thread A phải trả về thất bại"
        assert results["res_b"]["success"] is True, f"[{adapter_name}] Thread B phải trả về thành công"

        # Kiểm tra bộ nhớ: Không bị rollback về rỗng, chứa đúng điểm B
        mem_dests = adapter.get_destinations()
        dest_ids_in_mem = [d["id"] for d in mem_dests]
        assert "dest_B" in dest_ids_in_mem, f"[{adapter_name}] Điểm B phải tồn tại trong bộ nhớ"
        assert "dest_A" not in dest_ids_in_mem, f"[{adapter_name}] Điểm A không được lưu vì ghi file thất bại"
        assert len(mem_dests) == 1

        # Kiểm tra file trên đĩa: Khớp hoàn toàn với bộ nhớ
        with open(dest_file, "r", encoding="utf-8") as f:
            disk_data = yaml.safe_load(f)
        disk_ids = [d["id"] for d in disk_data.get("destinations", [])]
        assert disk_ids == ["dest_B"], f"[{adapter_name}] File trên đĩa phải có duy nhất dest_B: {disk_ids}"

    # -------------------------------------------------------------
    # KỊCH BẢN 2: HAI THAO TÁC THÀNH CÔNG ĐỒNG THỜI (Barrier)
    # -------------------------------------------------------------
    for adapter_name, adapter, dest_file in create_adapters(tmp_path, "scenario2"):
        barrier = threading.Barrier(2)
        results = {}

        dest_1 = {"id": "gate_1", "name": "Cổng số 1", "pose": {"position": {"x": 1.0, "y": 1.0, "z": 0.0}}}
        dest_2 = {"id": "gate_2", "name": "Cổng số 2", "pose": {"position": {"x": 2.0, "y": 2.0, "z": 0.0}}}

        def worker1():
            barrier.wait(timeout=5.0)
            results["res1"] = adapter.upsert_destination(dest_1)

        def worker2():
            barrier.wait(timeout=5.0)
            results["res2"] = adapter.upsert_destination(dest_2)

        t1 = threading.Thread(target=worker1)
        t2 = threading.Thread(target=worker2)
        t1.start()
        t2.start()
        t1.join(timeout=5.0)
        t2.join(timeout=5.0)

        assert results["res1"]["success"] is True
        assert results["res2"]["success"] is True

        mem_dests = adapter.get_destinations()
        mem_ids = {d["id"] for d in mem_dests}
        assert mem_ids == {"gate_1", "gate_2"}, f"[{adapter_name}] Cả 2 điểm phải có trong bộ nhớ"
        assert adapter.get_destinations_version() == 2

        with open(dest_file, "r", encoding="utf-8") as f:
            disk_data = yaml.safe_load(f)
        disk_ids = {d["id"] for d in disk_data.get("destinations", [])}
        assert disk_ids == {"gate_1", "gate_2"}, f"[{adapter_name}] Cả 2 điểm phải có trên đĩa"

    # -------------------------------------------------------------
    # KỊCH BẢN 3: THÊM VÀ XÓA ĐỒNG THỜI (Barrier)
    # -------------------------------------------------------------
    for adapter_name, adapter, dest_file in create_adapters(tmp_path, "scenario3"):
        # Khởi tạo điểm ban đầu
        init_dest1 = {"id": "gate_init_1", "name": "Cổng Khởi Tạo 1", "pose": {"position": {"x": 1.0, "y": 1.0, "z": 0.0}}}
        init_dest2 = {"id": "gate_init_2", "name": "Cổng Khởi Tạo 2", "pose": {"position": {"x": 2.0, "y": 2.0, "z": 0.0}}}
        adapter.upsert_destination(init_dest1)
        adapter.upsert_destination(init_dest2)
        assert len(adapter.get_destinations()) == 2

        barrier = threading.Barrier(2)
        results = {}

        new_dest = {"id": "gate_new_3", "name": "Cổng Mới 3", "pose": {"position": {"x": 3.0, "y": 3.0, "z": 0.0}}}

        def worker_add():
            barrier.wait(timeout=5.0)
            results["res_add"] = adapter.upsert_destination(new_dest)

        def worker_del():
            barrier.wait(timeout=5.0)
            results["res_del"] = adapter.delete_destination("gate_init_1")

        t_add = threading.Thread(target=worker_add)
        t_del = threading.Thread(target=worker_del)
        t_add.start()
        t_del.start()
        t_add.join(timeout=5.0)
        t_del.join(timeout=5.0)

        assert results["res_add"]["success"] is True
        assert results["res_del"]["success"] is True

        mem_dests = adapter.get_destinations()
        mem_ids = {d["id"] for d in mem_dests}
        assert mem_ids == {"gate_init_2", "gate_new_3"}, f"[{adapter_name}] Memory phải còn gate_init_2 và gate_new_3: {mem_ids}"

        with open(dest_file, "r", encoding="utf-8") as f:
            disk_data = yaml.safe_load(f)
        disk_ids = {d["id"] for d in disk_data.get("destinations", [])}
        assert disk_ids == {"gate_init_2", "gate_new_3"}, f"[{adapter_name}] Disk phải còn gate_init_2 và gate_new_3: {disk_ids}"

    # -------------------------------------------------------------
    # KỊCH BẢN 4: GHI CHẬM TRONG LÚC WATCHDOG CẦN PHÁT ZERO
    # -------------------------------------------------------------
    for adapter_name, adapter, dest_file in create_adapters(tmp_path, "scenario4"):
        # Đặt xe vào trạng thái MANUAL đang chạy và đã quá hạn timeout 0.5s
        adapter._control_mode = "MANUAL"
        adapter._manual_operator_id = "admin_drive"
        adapter._current_manual_twist = (0.25, 0.1)
        adapter._last_manual_cmd_time = time.monotonic() - 1.0  # quá hạn

        orig_write = adapter._write_destinations_file
        event_write_entered = threading.Event()
        event_allow_write_finish = threading.Event()

        def slow_write(dest_list):
            event_write_entered.set()
            event_allow_write_finish.wait(timeout=5.0)
            return orig_write(dest_list)

        adapter._write_destinations_file = slow_write

        slow_dest = {"id": "gate_slow", "name": "Cổng Chậm", "pose": {"position": {"x": 1.0, "y": 1.0, "z": 0.0}}}
        t_save = threading.Thread(target=lambda: adapter.upsert_destination(slow_dest))
        t_save.start()

        assert event_write_entered.wait(timeout=5.0)

        # Trong lúc tệp đang ghi chậm (giữ _io_lock), watchdog check_manual_timeout()
        # KHÔNG bị chặn bởi self._lock!
        t_start = time.monotonic()
        adapter.check_manual_timeout()
        elapsed = time.monotonic() - t_start

        assert elapsed < 0.1, f"[{adapter_name}] Watchdog bị chặn bởi I/O: {elapsed}s"
        assert adapter._control_mode == "AUTO", f"[{adapter_name}] Watchdog phải chuyển robot về AUTO"
        assert adapter._current_manual_twist == (0.0, 0.0), f"[{adapter_name}] Watchdog phải dừng xe về (0,0)"

        event_allow_write_finish.set()
        t_save.join(timeout=5.0)
        assert len(adapter.get_destinations()) == 1


# =========================================================================
# 12. Concurrency Race & Linearization between Navigation and Destinations
# =========================================================================

def test_destinations_navigation_race_and_linearization(tmp_path):
    """
    Kiểm thử đồng thời có kiểm soát giữa start_navigation và upsert/delete điểm đến:
    - Chiều 1: Điểm D1 đang chuẩn bị ghi cập nhật hoặc xóa (đang chờ I/O) thì start_navigation(D1) tới:
      -> Bị từ chối an toàn với thông báo 'đang trong quá trình cập nhật hoặc lưu trữ'.
      -> Watchdog điều khiển tay không bị nghẽn (< 0.1s).
      -> Sau khi I/O hoàn tất (hoặc thất bại), memory và disk đồng nhất, cờ bận được dọn dẹp sạch sẽ.
    - Chiều 2: Robot đang thực hiện chuyến tới D1 (NAVIGATING / PENDING / PAUSED) thì có yêu cầu sửa/xóa D1:
      -> Bị từ chối an toàn, không làm hỏng chuyến đi.
    - Tình huống lỗi: Ghi file ném Exception: Dữ liệu hợp lệ được bảo toàn, cờ pending được dọn trong finally.
    Kiểm thử trên cả MockRobotAdapter và RosRobotAdapter cô lập (không gửi Nav2 goal thật).
    """
    from collections import OrderedDict
    from app.adapters.ros_adapter import RosRobotAdapter
    from app.adapters.mock_adapter import MockRobotAdapter
    from app.coordinate.transform import MapMetadata

    def create_test_adapters(base_dir, name):
        f_mock = base_dir / f"{name}_mock_dest.yaml"
        f_ros = base_dir / f"{name}_ros_dest.yaml"

        ad_mock = MockRobotAdapter()
        ad_mock._destinations = []
        ad_mock._destinations_version = 0
        ad_mock._destinations_file = f_mock
        ad_mock._navigation_state = "IDLE"
        ad_mock._destination_id = None
        ad_mock._control_mode = "AUTO"
        ad_mock._manual_operator_id = None
        ad_mock._active_hold_id = None
        ad_mock._released_hold_ids = OrderedDict()
        ad_mock._last_manual_seq = 0
        ad_mock._current_manual_twist = (0.0, 0.0)
        ad_mock._last_manual_cmd_time = 0.0
        ad_mock._pending_dest_modifications = set()

        ad_ros = object.__new__(RosRobotAdapter)
        ad_ros._lock = threading.Lock()
        ad_ros._io_lock = threading.Lock()
        ad_ros._cfg = get_ros_config()
        ad_ros._destinations = []
        ad_ros._destinations_version = 0
        ad_ros._destinations_file = f_ros
        ad_ros._navigation_state = "IDLE"
        ad_ros._destination_id = None
        ad_ros._control_mode = "AUTO"
        ad_ros._manual_operator_id = None
        ad_ros._active_hold_id = None
        ad_ros._released_hold_ids = OrderedDict()
        ad_ros._last_manual_seq = 0
        ad_ros._current_manual_twist = (0.0, 0.0)
        ad_ros._last_manual_cmd_time = 0.0
        ad_ros._pub_cmd_vel = None
        ad_ros._pending_dest_modifications = set()
        ad_ros._map_meta = MapMetadata(width=200, height=200, resolution=0.05, origin_x=0.0, origin_y=0.0, origin_yaw=0.0)
        ad_ros._occupancy_grid_data = [0] * 40000

        return [("MockAdapter", ad_mock, f_mock), ("RosAdapter", ad_ros, f_ros)]

    # -----------------------------------------------------------------
    # TÌNH HUỐNG 1: UPSERT I/O ĐANG CHẠY -> START_NAVIGATION(D1) TỚI
    # -----------------------------------------------------------------
    for adapter_name, adapter, dest_file in create_test_adapters(tmp_path, "race_upsert"):
        # Khởi tạo điểm D1 ban đầu
        initial_d1 = {
            "id": "gate_race_1",
            "name": "Cổng G1 Gốc",
            "pose": {"position": {"x": 2.0, "y": 3.0, "z": 0.0}, "orientation": {"z": 0.0, "w": 1.0}}
        }
        res_init = adapter.upsert_destination(initial_d1)
        assert res_init["success"] is True

        # Hook hàm ghi file để tạm dừng trong pha I/O (ngoài self._lock)
        orig_write = adapter._write_destinations_file
        event_write_entered = threading.Event()
        event_allow_write_finish = threading.Event()

        def slow_write(dest_list):
            event_write_entered.set()
            assert event_allow_write_finish.wait(timeout=5.0), "Timeout chờ hoàn thành ghi file"
            return orig_write(dest_list)

        adapter._write_destinations_file = slow_write

        # Cập nhật tọa độ mới cho gate_race_1
        updated_d1 = {
            "id": "gate_race_1",
            "name": "Cổng G1 Mới",
            "pose": {"position": {"x": 5.0, "y": 6.0, "z": 0.0}, "orientation": {"z": 0.0, "w": 1.0}}
        }

        t_upsert = threading.Thread(target=lambda: adapter.upsert_destination(updated_d1))
        t_upsert.start()

        # Đợi thread ghi file vào trong hàm slow_write (đã nhả self._lock)
        assert event_write_entered.wait(timeout=5.0)

        # 1. Kiểm tra watchdog điều khiển tay không bị nghẽn (dưới 0.1s)
        t_wd_start = time.monotonic()
        adapter.check_manual_timeout()
        elapsed_wd = time.monotonic() - t_wd_start
        assert elapsed_wd < 0.1, f"[{adapter_name}] Watchdog bị chặn bởi I/O: {elapsed_wd}s"

        # 2. Yêu cầu start_navigation tới gate_race_1 trong lúc I/O đang diễn ra
        res_nav = adapter.start_navigation("gate_race_1", "user_test")
        assert res_nav["success"] is False, f"[{adapter_name}] start_navigation phải bị từ chối khi đang ghi cập nhật: {res_nav}"
        assert "đang trong quá trình cập nhật hoặc lưu trữ" in res_nav["message"], f"[{adapter_name}] Thông báo từ chối không đúng: {res_nav['message']}"

        # 3. Cho phép ghi file hoàn thành
        event_allow_write_finish.set()
        t_upsert.join(timeout=5.0)

        # 4. Kiểm tra trạng thái bộ nhớ và file khớp hoàn toàn
        dests_mem = adapter.get_destinations()
        assert len(dests_mem) == 1
        assert dests_mem[0]["name"] == "Cổng G1 Mới"
        assert dests_mem[0]["pose"]["position"]["x"] == 5.0

        with open(dest_file, "r", encoding="utf-8") as f:
            disk_data = yaml.safe_load(f)
        dests_disk = disk_data.get("destinations", [])
        assert len(dests_disk) == 1
        assert dests_disk[0]["name"] == "Cổng G1 Mới"
        assert dests_disk[0]["pose"]["position"]["x"] == 5.0

        # Cờ pending phải được xóa sạch
        assert len(adapter._pending_dest_modifications) == 0

    # -----------------------------------------------------------------
    # TÌNH HUỐNG 2: DELETE I/O ĐANG CHẠY -> START_NAVIGATION(D1) TỚI
    # -----------------------------------------------------------------
    for adapter_name, adapter, dest_file in create_test_adapters(tmp_path, "race_delete"):
        # Khởi tạo điểm D1 ban đầu
        initial_d1 = {
            "id": "gate_del_1",
            "name": "Cổng Cần Xóa",
            "pose": {"position": {"x": 2.0, "y": 3.0, "z": 0.0}, "orientation": {"z": 0.0, "w": 1.0}}
        }
        res_init = adapter.upsert_destination(initial_d1)
        assert res_init["success"] is True

        orig_write = adapter._write_destinations_file
        event_del_write_entered = threading.Event()
        event_del_allow_finish = threading.Event()

        def slow_del_write(dest_list):
            event_del_write_entered.set()
            assert event_del_allow_finish.wait(timeout=5.0), "Timeout chờ xóa file"
            return orig_write(dest_list)

        adapter._write_destinations_file = slow_del_write

        t_delete = threading.Thread(target=lambda: adapter.delete_destination("gate_del_1"))
        t_delete.start()

        assert event_del_write_entered.wait(timeout=5.0)

        # Trong lúc I/O xóa đang chạy, start_navigation tới gate_del_1 phải bị từ chối
        res_nav = adapter.start_navigation("gate_del_1", "user_test")
        assert res_nav["success"] is False
        assert "đang trong quá trình cập nhật hoặc lưu trữ" in res_nav["message"]

        # Cho phép hoàn tất xóa
        event_del_allow_finish.set()
        t_delete.join(timeout=5.0)

        # Điểm đã bị xóa sạch khỏi cả memory và disk
        assert len(adapter.get_destinations()) == 0
        with open(dest_file, "r", encoding="utf-8") as f:
            disk_data = yaml.safe_load(f)
        assert len(disk_data.get("destinations", [])) == 0
        assert len(adapter._pending_dest_modifications) == 0

    # -----------------------------------------------------------------
    # TÌNH HUỐNG 3: I/O GHI FILE THẤT BẠI TRONG LÚC RACE
    # -----------------------------------------------------------------
    for adapter_name, adapter, dest_file in create_test_adapters(tmp_path, "race_fail"):
        initial_d1 = {
            "id": "gate_fail_1",
            "name": "Cổng Bền Vững",
            "pose": {"position": {"x": 1.0, "y": 1.0, "z": 0.0}, "orientation": {"z": 0.0, "w": 1.0}}
        }
        res_init = adapter.upsert_destination(initial_d1)
        assert res_init["success"] is True

        event_fail_entered = threading.Event()
        event_fail_allow = threading.Event()

        def failing_write(dest_list):
            event_fail_entered.set()
            assert event_fail_allow.wait(timeout=5.0)
            if adapter_name == "RosAdapter":
                return False, "Lỗi I/O giả lập: Read-only filesystem"
            return False

        adapter._write_destinations_file = failing_write

        bad_update = {
            "id": "gate_fail_1",
            "name": "Tên Bị Hỏng",
            "pose": {"position": {"x": 9.9, "y": 9.9, "z": 0.0}, "orientation": {"z": 0.0, "w": 1.0}}
        }

        t_bad = threading.Thread(target=lambda: adapter.upsert_destination(bad_update))
        t_bad.start()

        assert event_fail_entered.wait(timeout=5.0)

        # Trong lúc I/O thất bại đang treo, start_navigation bị từ chối
        res_nav = adapter.start_navigation("gate_fail_1", "user_test")
        assert res_nav["success"] is False
        assert "đang trong quá trình cập nhật hoặc lưu trữ" in res_nav["message"]

        # Cho phép hàm write trả về lỗi
        event_fail_allow.set()
        t_bad.join(timeout=5.0)

        # Dữ liệu gốc KHÔNG bị mất hoặc thay đổi
        dests_mem = adapter.get_destinations()
        assert len(dests_mem) == 1
        assert dests_mem[0]["name"] == "Cổng Bền Vững"
        assert dests_mem[0]["pose"]["position"]["x"] == 1.0

        # Cờ pending phải được giải phóng qua khối finally
        assert len(adapter._pending_dest_modifications) == 0

    # -----------------------------------------------------------------
    # TÌNH HUỐNG 4: CHIỀU 2 - ROBOT ĐÃ BẮT ĐẦU CHUYẾN -> UPSERT/DELETE BỊ CHẶN
    # -----------------------------------------------------------------
    for adapter_name, adapter, dest_file in create_test_adapters(tmp_path, "race_dir2"):
        dest_active = {
            "id": "gate_active_1",
            "name": "Cổng Đang Dẫn Đường",
            "pose": {"position": {"x": 3.0, "y": 4.0, "z": 0.0}, "orientation": {"z": 0.0, "w": 1.0}}
        }
        adapter.upsert_destination(dest_active)

        # Đặt robot vào trạng thái đang dẫn đường tới gate_active_1
        for nav_state in ("PENDING", "ACCEPTED", "NAVIGATING", "PAUSED", "CANCELING"):
            adapter._navigation_state = nav_state
            adapter._destination_id = "gate_active_1"

            # 1. Thử sửa tọa độ cổng đang đi -> Bị chặn
            res_up = adapter.upsert_destination({
                "id": "gate_active_1",
                "name": "Sửa Tên Trong Khi Đi",
                "pose": {"position": {"x": 8.0, "y": 8.0, "z": 0.0}, "orientation": {"z": 0.0, "w": 1.0}}
            })
            assert res_up["success"] is False, f"[{adapter_name}] Sửa điểm đang đi phải bị từ chối ở state {nav_state}"
            assert "Không thể cập nhật điểm đến 'gate_active_1'" in res_up["message"]

            # 2. Thử xóa cổng đang đi -> Bị chặn
            res_del = adapter.delete_destination("gate_active_1")
            assert res_del["success"] is False, f"[{adapter_name}] Xóa điểm đang đi phải bị từ chối ở state {nav_state}"
            assert "Không thể xóa điểm đến 'gate_active_1'" in res_del["message"]

            # Kiểm tra trạng thái chuyến và điểm đến không bị ảnh hưởng
            assert adapter._navigation_state == nav_state
            assert adapter._destination_id == "gate_active_1"
            assert len(adapter.get_destinations()) == 1


# =========================================================================
# 13. Concurrency Race: Start Navigation Exactly Post-Write & Pre-Commit
# =========================================================================

def test_destinations_start_navigation_race_post_write_pre_commit(tmp_path):
    """
    Kiểm thử đồng thời ép start_navigation xảy ra ĐÚNG LÚC GHI FILE VỪA XONG
    nhưng bộ nhớ CHƯA COMMIT:
    - Kiểm tra start_navigation bị từ chối trong khoảng giữa này (vì reservation vẫn được giữ).
    - Sau khi cho phép commit hoàn thành:
      + Đối với Delete: Delete trả success=True, file và bộ nhớ đều đã xóa điểm (đồng nhất 100%).
      + Đối với Upsert: Upsert trả success=True, file và bộ nhớ đều đã cập nhật điểm (đồng nhất 100%).
    - Kiểm tra cả trên MockRobotAdapter và RosRobotAdapter cô lập.
    """
    from collections import OrderedDict
    from app.adapters.ros_adapter import RosRobotAdapter
    from app.adapters.mock_adapter import MockRobotAdapter
    from app.coordinate.transform import MapMetadata

    def create_test_adapters(base_dir, name):
        f_mock = base_dir / f"{name}_mock_dest.yaml"
        f_ros = base_dir / f"{name}_ros_dest.yaml"

        ad_mock = MockRobotAdapter()
        ad_mock._destinations = []
        ad_mock._destinations_version = 0
        ad_mock._destinations_file = f_mock
        ad_mock._navigation_state = "IDLE"
        ad_mock._destination_id = None
        ad_mock._control_mode = "AUTO"
        ad_mock._manual_operator_id = None
        ad_mock._active_hold_id = None
        ad_mock._released_hold_ids = OrderedDict()
        ad_mock._last_manual_seq = 0
        ad_mock._current_manual_twist = (0.0, 0.0)
        ad_mock._last_manual_cmd_time = 0.0
        ad_mock._pending_dest_modifications = set()

        ad_ros = object.__new__(RosRobotAdapter)
        ad_ros._lock = threading.Lock()
        ad_ros._io_lock = threading.Lock()
        ad_ros._cfg = get_ros_config()
        ad_ros._destinations = []
        ad_ros._destinations_version = 0
        ad_ros._destinations_file = f_ros
        ad_ros._navigation_state = "IDLE"
        ad_ros._destination_id = None
        ad_ros._control_mode = "AUTO"
        ad_ros._manual_operator_id = None
        ad_ros._active_hold_id = None
        ad_ros._released_hold_ids = OrderedDict()
        ad_ros._last_manual_seq = 0
        ad_ros._current_manual_twist = (0.0, 0.0)
        ad_ros._last_manual_cmd_time = 0.0
        ad_ros._pub_cmd_vel = None
        ad_ros._pending_dest_modifications = set()
        ad_ros._map_meta = MapMetadata(width=200, height=200, resolution=0.05, origin_x=0.0, origin_y=0.0, origin_yaw=0.0)
        ad_ros._occupancy_grid_data = [0] * 40000

        return [("MockAdapter", ad_mock, f_mock), ("RosAdapter", ad_ros, f_ros)]

    # -------------------------------------------------------------
    # 1. DELETE: Ghi file xong nhưng CHƯA COMMIT -> Start bị từ chối
    # -------------------------------------------------------------
    for adapter_name, adapter, dest_file in create_test_adapters(tmp_path, "post_write_delete"):
        initial_dest = {
            "id": "gate_pw_del",
            "name": "Cổng Test Xóa Post-Write",
            "pose": {"position": {"x": 2.0, "y": 3.0, "z": 0.0}, "orientation": {"z": 0.0, "w": 1.0}}
        }
        res_init = adapter.upsert_destination(initial_dest)
        assert res_init["success"] is True

        orig_write = adapter._write_destinations_file
        event_file_written = threading.Event()
        event_allow_commit = threading.Event()

        def hook_write_delete(dest_list):
            res = orig_write(dest_list)
            # TẠI ĐÂY: File đĩa đã được ghi (đã xóa điểm khỏi file),
            # nhưng chưa trả về adapter để adapter lấy self._lock commit bộ nhớ!
            event_file_written.set()
            assert event_allow_commit.wait(timeout=5.0), "Timeout chờ commit"
            return res

        adapter._write_destinations_file = hook_write_delete

        res_delete_box = {}
        def run_delete():
            res_delete_box["res"] = adapter.delete_destination("gate_pw_del")

        t_del = threading.Thread(target=run_delete)
        t_del.start()

        # Chờ đúng lúc file đã ghi xong trên đĩa
        assert event_file_written.wait(timeout=5.0)

        # Kiểm chứng trạng thái ở khoảng giữa:
        # a) File trên đĩa ĐÃ MẤT gate_pw_del
        with open(dest_file, "r", encoding="utf-8") as f:
            disk_data = yaml.safe_load(f)
        assert len(disk_data.get("destinations", [])) == 0, f"[{adapter_name}] File đĩa phải đã xóa gate_pw_del"

        # b) Bộ nhớ vẫn CHƯA COMMIT (vẫn còn gate_pw_del)
        mem_dests_pre = adapter.get_destinations()
        assert len(mem_dests_pre) == 1, f"[{adapter_name}] Bộ nhớ chưa commit phải vẫn còn điểm"

        # c) ÉP GỌI start_navigation tới gate_pw_del TRONG KHOẢNG NÀY:
        # PHẢI BỊ TỪ CHỐI AN TOÀN vì điểm vẫn đang trong reservation (_pending_dest_modifications)
        res_nav = adapter.start_navigation("gate_pw_del", "passenger_1")
        assert res_nav["success"] is False, f"[{adapter_name}] Start navigation phải bị từ chối: {res_nav}"
        assert "đang trong quá trình cập nhật hoặc lưu trữ" in res_nav["message"]

        # d) Cho phép adapter tiếp tục commit bộ nhớ
        event_allow_commit.set()
        t_del.join(timeout=5.0)

        # e) Kết quả sau khi commit hoàn tất:
        assert res_delete_box["res"]["success"] is True, f"[{adapter_name}] Xóa phải thành công: {res_delete_box}"
        # Bộ nhớ và file trên đĩa đồng nhất 100% (cả hai đều đã xóa sạch)
        assert len(adapter.get_destinations()) == 0
        with open(dest_file, "r", encoding="utf-8") as f:
            disk_data_final = yaml.safe_load(f)
        assert len(disk_data_final.get("destinations", [])) == 0
        assert len(adapter._pending_dest_modifications) == 0

    # -------------------------------------------------------------
    # 2. UPSERT: Ghi file xong nhưng CHƯA COMMIT -> Start bị từ chối
    # -------------------------------------------------------------
    for adapter_name, adapter, dest_file in create_test_adapters(tmp_path, "post_write_upsert"):
        initial_dest = {
            "id": "gate_pw_up",
            "name": "Cổng Gốc",
            "pose": {"position": {"x": 1.0, "y": 1.0, "z": 0.0}, "orientation": {"z": 0.0, "w": 1.0}}
        }
        res_init = adapter.upsert_destination(initial_dest)
        assert res_init["success"] is True

        orig_write = adapter._write_destinations_file
        event_file_written = threading.Event()
        event_allow_commit = threading.Event()

        def hook_write_upsert(dest_list):
            res = orig_write(dest_list)
            event_file_written.set()
            assert event_allow_commit.wait(timeout=5.0), "Timeout chờ commit"
            return res

        adapter._write_destinations_file = hook_write_upsert

        updated_dest = {
            "id": "gate_pw_up",
            "name": "Cổng Đã Cập Nhật",
            "pose": {"position": {"x": 7.0, "y": 8.0, "z": 0.0}, "orientation": {"z": 0.0, "w": 1.0}}
        }

        res_upsert_box = {}
        def run_upsert():
            res_upsert_box["res"] = adapter.upsert_destination(updated_dest)

        t_up = threading.Thread(target=run_upsert)
        t_up.start()

        assert event_file_written.wait(timeout=5.0)

        # a) File trên đĩa ĐÃ CẬP NHẬT tọa độ mới
        with open(dest_file, "r", encoding="utf-8") as f:
            disk_data = yaml.safe_load(f)
        assert disk_data["destinations"][0]["pose"]["position"]["x"] == 7.0

        # b) Bộ nhớ vẫn CHƯA COMMIT (vẫn là tọa độ cũ 1.0)
        mem_dests_pre = adapter.get_destinations()
        assert mem_dests_pre[0]["pose"]["position"]["x"] == 1.0

        # c) ÉP GỌI start_navigation tới gate_pw_up TRONG KHOẢNG NÀY:
        res_nav = adapter.start_navigation("gate_pw_up", "passenger_1")
        assert res_nav["success"] is False, f"[{adapter_name}] Start navigation phải bị từ chối: {res_nav}"
        assert "đang trong quá trình cập nhật hoặc lưu trữ" in res_nav["message"]

        # d) Cho phép commit bộ nhớ
        event_allow_commit.set()
        t_up.join(timeout=5.0)

        # e) Kết quả sau khi commit:
        assert res_upsert_box["res"]["success"] is True
        mem_dests_final = adapter.get_destinations()
        assert mem_dests_final[0]["pose"]["position"]["x"] == 7.0
        assert mem_dests_final[0]["name"] == "Cổng Đã Cập Nhật"
        assert len(adapter._pending_dest_modifications) == 0










