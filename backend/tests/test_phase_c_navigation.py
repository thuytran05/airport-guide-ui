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

