from __future__ import annotations

import time
import math
import uuid
import io
import os
import threading
import logging
import pathlib
import collections
import yaml
from typing import Dict, Any, List, Optional, Tuple

from .base import BaseRobotAdapter
from ..ros_config import get_ros_config
from ..coordinate.transform import MapMetadata, quaternion_to_yaw
from ..services.voice_matcher import match_destination_from_transcript
from ..services.event_logger import event_logger

logger = logging.getLogger("ros_adapter")

# Kiểm tra xem có rclpy (môi trường ROS 2 Jazzy trên Linux/Docker) hay không
try:
    import rclpy
    from rclpy.node import Node
    from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy, HistoryPolicy
    from rclpy.action import ActionClient
    from rclpy.executors import ExternalShutdownException, ShutdownException
    from rclpy.signals import SignalHandlerOptions
    from action_msgs.msg import GoalStatus, GoalStatusArray
    from geometry_msgs.msg import PoseStamped, PoseWithCovarianceStamped, TwistStamped, Twist
    from sensor_msgs.msg import BatteryState
    from nav_msgs.msg import OccupancyGrid, Path as NavPath
    from std_msgs.msg import String
    from std_srvs.srv import Trigger, SetBool
    from diagnostic_msgs.msg import DiagnosticArray
    from rosgraph_msgs.msg import Clock
    HAS_RCLPY = True
except ImportError:
    HAS_RCLPY = False
    class ExternalShutdownException(Exception): pass
    class ShutdownException(Exception): pass
    class SignalHandlerOptions:
        NO = 0
        ALL = 1
    class GoalStatus:
        STATUS_UNKNOWN = 0
        STATUS_ACCEPTED = 1
        STATUS_EXECUTING = 2
        STATUS_CANCELING = 3
        STATUS_SUCCEEDED = 4
        STATUS_CANCELED = 5
        STATUS_ABORTED = 6
    class GoalStatusArray:
        pass
    class Twist:
        class Vector3:
            def __init__(self, x=0.0, y=0.0, z=0.0):
                self.x = float(x)
                self.y = float(y)
                self.z = float(z)
        def __init__(self):
            self.linear = self.Vector3()
            self.angular = self.Vector3()
    class Trigger:
        class Request:
            pass
        class Response:
            success = False
            message = ""
    class SetBool:
        class Request:
            data = False
        class Response:
            success = False
            message = ""

# Kiểm tra package custom airport_robot_interfaces
try:
    from airport_robot_interfaces.msg import RobotState, DestinationList, Destination
    from airport_robot_interfaces.srv import UpsertDestination
    HAS_AIRPORT_INTERFACES = True
except ImportError:
    HAS_AIRPORT_INTERFACES = False

# Kiểm tra Nav2 action
try:
    from nav2_msgs.action import NavigateToPose
    from action_msgs.msg import GoalStatus
    HAS_NAV2_ACTION = True
except ImportError:
    HAS_NAV2_ACTION = False
    NavigateToPose = None


def _build_qos(qos_dict: Optional[Dict[str, Any]]) -> "QoSProfile":
    """Chuyển đổi cấu hình QoS từ YAML sang rclpy QoSProfile"""
    if not qos_dict:
        return QoSProfile(depth=10)
    
    depth = qos_dict.get("depth", 10)
    reliability_str = qos_dict.get("reliability", "reliable").lower()
    durability_str = qos_dict.get("durability", "volatile").lower()

    rel = ReliabilityPolicy.RELIABLE if reliability_str == "reliable" else ReliabilityPolicy.BEST_EFFORT
    dur = DurabilityPolicy.TRANSIENT_LOCAL if durability_str == "transient_local" else DurabilityPolicy.VOLATILE

    return QoSProfile(
        history=HistoryPolicy.KEEP_LAST,
        depth=depth,
        reliability=rel,
        durability=dur
    )


class RosRobotAdapter(BaseRobotAdapter):
    def __init__(self):
        if not HAS_RCLPY:
            raise RuntimeError(
                "Không tìm thấy thư viện 'rclpy'. RosRobotAdapter chỉ có thể chạy trong môi trường ROS 2 Jazzy. "
                "Hãy đặt ROBOT_ADAPTER_MODE=mock khi chạy trên Windows."
            )

        self._lock = threading.RLock()
        self._io_lock = threading.Lock()
        self._cfg = get_ros_config()
        self._map_meta = MapMetadata()
        self._map_frame_id: str = "map"
        self._map_stamp: Optional[Dict[str, int]] = None
        self._map_version: Optional[str] = None
        self._map_png: Optional[bytes] = None

        # Telemetry
        self._pose: Optional[Dict[str, float]] = None
        self._battery_percent: Optional[float] = None
        self._last_pose_time: float = 0.0
        self._last_state_time: float = 0.0
        self._is_connected = False
        self._control_mode = "AUTO"
        self._manual_operator_id: Optional[str] = None
        self._current_manual_twist = (0.0, 0.0)
        self._last_manual_cmd_time: float = 0.0
        self._active_hold_id: Optional[str] = None
        self._last_manual_seq: int = 0
        self._last_hold_timestamp_ms: int = 0
        self._released_hold_ids: collections.OrderedDict[str, float] = collections.OrderedDict()
        self._navigation_state = "IDLE"
        self._has_goal = False
        self._goal_id = ""
        self._trip_id = ""
        self._destination_id = ""
        self._voice_state = "IDLE"
        self._voice_transcript: Optional[str] = None
        self._voice_response: Optional[str] = None
        self._voice_start_in_progress: bool = False
        self._voice_proposal: Optional[Dict[str, Any]] = None
        self._voice_requester_id: str = ""
        self._voice_session_id: str = ""
        self._message = "Đang kết nối tới các topic ROS..."

        self._destinations_file = pathlib.Path(self._cfg.destinations_storage_path)
        self._destinations_seed_file = pathlib.Path(self._cfg.destinations_seed_path)
        self._destinations_version: int = 0
        self._destinations: List[Dict[str, Any]] = self._load_destinations()
        self._occupancy_grid_data: Optional[List[int]] = None
        self._alerts: List[Dict[str, Any]] = []
        self._path: Optional[List[Dict[str, float]]] = None
        self._path_version: int = 0
        self._current_goal_handle = None
        self._current_target_pose: Optional[Dict[str, float]] = None
        self._current_goal_dispatch_time: float = 0.0
        self._active_request_id: str = ""
        self._cancel_requested_for: Optional[str] = None
        self._pause_requested_for: Optional[str] = None
        self._owner_id: str = ""
        self._distance_remaining: Optional[float] = None
        self._estimated_time_remaining: Optional[float] = None
        self._number_of_recoveries: int = 0
        self._nav2_has_active_goal: bool = False
        self._nav2_action_status_received: bool = False

        # Pose metadata (frame_id, stamp) cho WebSocket telemetry
        self._pose_frame_id: str = ""
        self._pose_stamp: Optional[Dict[str, int]] = None  # {"sec": ..., "nanosec": ...}

        # Sim clock monitoring (chỉ dùng khi use_sim_time=True)
        self._last_clock_sec: Optional[float] = None          # giá trị sim clock cuối
        self._last_clock_monotonic: float = 0.0                # monotonic khi nhận clock cuối
        self._clock_stalled: bool = False                      # True nếu /clock ngừng tiến
        self._sim_restarted: bool = False                      # True nếu clock quay lùi
        self._pose_epoch: int = 0                              # tăng mỗi khi sim restart
        self._pose_received_epoch: int = -1                    # epoch lúc nhận pose cuối
        self._disposed: bool = False
        self._last_map_time: float = 0.0
        self._first_pose_logged: bool = False
        self._first_map_logged: bool = False
        self._first_clock_logged: bool = False

        # Khởi tạo Node ROS 2 với tên từ cấu hình
        if not rclpy.ok():
            try:
                rclpy.init(signal_handler_options=SignalHandlerOptions.NO)
            except Exception:
                rclpy.init()

        node_name = self._cfg.merged_config.get("nodes", {}).get("web_gateway", "airport_web_gateway").lstrip("/")
        self._node = rclpy.create_node(node_name)

        if self._cfg.use_sim_time:
            self._node.set_parameters([rclpy.parameter.Parameter('use_sim_time', rclpy.Parameter.Type.BOOL, True)])
            logger.info("Đã bật use_sim_time=True theo profile cấu hình.")

        self._setup_subscribers_and_clients()

        # Thread spin ROS với worker chống sập
        self._executor = rclpy.executors.SingleThreadedExecutor()
        self._executor.add_node(self._node)
        self._spin_thread = threading.Thread(target=self._spin_worker, daemon=True, name="ros_spin_thread")
        self._spin_thread.start()

        logger.info(f"RosRobotAdapter đã khởi tạo hoàn tất với node [{node_name}]")

    def _spin_worker(self):
        """Worker loop cho luồng spin ROS 2 có khả năng chống sập và bắt biệt lệ shutdown an toàn"""
        while not getattr(self, "_disposed", False) and rclpy.ok():
            try:
                self._executor.spin()
            except (ExternalShutdownException, ShutdownException):
                break
            except Exception as e:
                if not getattr(self, "_disposed", False):
                    logger.error(f"Lỗi không mong muốn trong luồng spin ROS 2: {e}", exc_info=True)
                    time.sleep(0.5)

    def ensure_spinning(self) -> bool:
        """Kiểm tra và phục hồi luồng spin ROS nếu bị dừng bất thường"""
        if getattr(self, "_disposed", False) or not rclpy.ok():
            return False
        with self._lock:
            if not hasattr(self, "_spin_thread") or self._spin_thread is None or not self._spin_thread.is_alive():
                logger.warning("Phát hiện luồng spin ROS đã dừng. Đang tự động khởi động lại luồng spin...")
                try:
                    self._spin_thread = threading.Thread(target=self._spin_worker, daemon=True, name="ros_spin_thread")
                    self._spin_thread.start()
                    return True
                except Exception as e:
                    logger.error(f"Không thể khởi động lại luồng spin: {e}")
                    return False
        return True

    def _setup_subscribers_and_clients(self):
        # 1. Pose Topic — chọn message class và callback theo type trong YAML
        pose_cfg = self._cfg.get_topic("robot_pose")
        if pose_cfg and pose_cfg.enabled:
            qos = _build_qos(pose_cfg.qos)
            if "PoseWithCovarianceStamped" in pose_cfg.type:
                msg_class = PoseWithCovarianceStamped
                callback = self._on_amcl_pose
                logger.info(f"Pose type: PoseWithCovarianceStamped (AMCL)")
            else:
                msg_class = PoseStamped
                callback = self._on_pose
                logger.info(f"Pose type: PoseStamped")
            self._sub_pose = self._node.create_subscription(
                msg_class, pose_cfg.name, callback, qos
            )
            logger.info(f"Subscribed pose topic: {pose_cfg.name}")

        # 2. Map Topic
        map_cfg = self._cfg.get_topic("map")
        if map_cfg and map_cfg.enabled:
            qos = _build_qos(map_cfg.qos)
            self._sub_map = self._node.create_subscription(
                OccupancyGrid, map_cfg.name, self._on_map, qos
            )
            logger.info(f"Subscribed map topic: {map_cfg.name}")

        # 3. Robot State Topic (airport_robot_interfaces)
        state_cfg = self._cfg.get_topic("robot_state")
        if state_cfg and state_cfg.enabled:
            if HAS_AIRPORT_INTERFACES:
                qos = _build_qos(state_cfg.qos)
                self._sub_state = self._node.create_subscription(
                    RobotState, state_cfg.name, self._on_robot_state, qos
                )
                logger.info(f"Subscribed robot_state topic: {state_cfg.name}")
            else:
                logger.warning(f"Chưa có package 'airport_robot_interfaces'. Bỏ qua subscribe topic: {state_cfg.name}")

        # 4. Destinations Topic (airport_robot_interfaces)
        dest_cfg = self._cfg.get_topic("destinations")
        if dest_cfg and dest_cfg.enabled:
            if HAS_AIRPORT_INTERFACES:
                qos = _build_qos(dest_cfg.qos)
                self._sub_destinations = self._node.create_subscription(
                    DestinationList, dest_cfg.name, self._on_destinations, qos
                )
                logger.info(f"Subscribed destinations topic: {dest_cfg.name}")
            else:
                logger.warning(f"Chưa có package 'airport_robot_interfaces'. Bỏ qua subscribe topic: {dest_cfg.name}")

        # 5. Voice State Topic
        voice_state_cfg = self._cfg.get_topic("voice_state")
        if voice_state_cfg and voice_state_cfg.enabled:
            qos = _build_qos(voice_state_cfg.qos)
            self._sub_voice_state = self._node.create_subscription(
                String, voice_state_cfg.name, self._on_voice_state, qos
            )
            logger.info(f"Subscribed voice_state topic: {voice_state_cfg.name}")

        # 6. Alerts Topic
        alerts_cfg = self._cfg.get_topic("alerts")
        if alerts_cfg and alerts_cfg.enabled:
            qos = _build_qos(alerts_cfg.qos)
            self._sub_alerts = self._node.create_subscription(
                DiagnosticArray, alerts_cfg.name, self._on_alerts, qos
            )
            logger.info(f"Subscribed alerts topic: {alerts_cfg.name}")

        # 7. Battery Topic (Tùy chọn)
        battery_cfg = self._cfg.get_topic("battery")
        if battery_cfg and battery_cfg.enabled:
            qos = _build_qos(battery_cfg.qos)
            self._sub_battery = self._node.create_subscription(
                BatteryState, battery_cfg.name, self._on_battery, qos
            )

        # 8. Path Topic (Tùy chọn)
        path_cfg = self._cfg.get_topic("path")
        if path_cfg and path_cfg.enabled:
            qos = _build_qos(path_cfg.qos)
            self._sub_path = self._node.create_subscription(
                NavPath, path_cfg.name, self._on_path, qos
            )

        # 9. Voice transcript & response (Tùy chọn)
        transcript_cfg = self._cfg.get_topic("voice_transcript")
        if transcript_cfg and transcript_cfg.enabled:
            self._sub_transcript = self._node.create_subscription(
                String, transcript_cfg.name, self._on_voice_transcript, 1
            )
        response_cfg = self._cfg.get_topic("voice_response")
        if response_cfg and response_cfg.enabled:
            self._sub_response = self._node.create_subscription(
                String, response_cfg.name, lambda m: setattr(self, "_voice_response", m.data), 1
            )

        # 10. Manual cmd_vel Publisher
        cmd_cfg = self._cfg.get_topic("cmd_vel_manual")
        if cmd_cfg and cmd_cfg.enabled:
            qos = _build_qos(cmd_cfg.qos)
            if getattr(cmd_cfg, "type", "") == "geometry_msgs/msg/Twist":
                self._pub_cmd_vel = self._node.create_publisher(Twist, cmd_cfg.name, qos)
                self._cmd_vel_is_twist = True
            else:
                self._pub_cmd_vel = self._node.create_publisher(TwistStamped, cmd_cfg.name, qos)
                self._cmd_vel_is_twist = False
            logger.info(f"Created publisher cmd_vel_manual: {cmd_cfg.name} (type: {cmd_cfg.type})")
        else:
            self._pub_cmd_vel = None
            self._cmd_vel_is_twist = False

        # 11. Service Clients
        voice_srv_cfg = self._cfg.get_service("voice_start")
        if voice_srv_cfg and voice_srv_cfg.enabled:
            self._cli_voice_start = self._node.create_client(Trigger, voice_srv_cfg.name)

        manual_srv_cfg = self._cfg.get_service("set_manual_control")
        if manual_srv_cfg and manual_srv_cfg.enabled:
            self._cli_set_manual = self._node.create_client(SetBool, manual_srv_cfg.name)

        upsert_srv_cfg = self._cfg.get_service("destinations_upsert")
        if upsert_srv_cfg and upsert_srv_cfg.enabled and HAS_AIRPORT_INTERFACES:
            self._cli_upsert_dest = self._node.create_client(UpsertDestination, upsert_srv_cfg.name)
        else:
            self._cli_upsert_dest = None

        # 12. Nav2 Action Client & Status Monitoring
        nav_action_cfg = self._cfg.get_action("navigate")
        if nav_action_cfg and nav_action_cfg.enabled and HAS_NAV2_ACTION:
            self._action_nav = ActionClient(self._node, NavigateToPose, nav_action_cfg.name)
            logger.info(f"Created Nav2 action client: {nav_action_cfg.name}")
            try:
                from rclpy.qos import QoSProfile, QoSDurabilityPolicy, QoSReliabilityPolicy, QoSHistoryPolicy
                action_status_qos = QoSProfile(
                    reliability=QoSReliabilityPolicy.RELIABLE,
                    durability=QoSDurabilityPolicy.TRANSIENT_LOCAL,
                    history=QoSHistoryPolicy.KEEP_LAST,
                    depth=10
                )
                self._sub_action_status = self._node.create_subscription(
                    GoalStatusArray,
                    f"{nav_action_cfg.name}/_action/status",
                    self._on_action_status,
                    action_status_qos
                )
                logger.info(f"Subscribed action status: {nav_action_cfg.name}/_action/status (TRANSIENT_LOCAL)")
            except Exception as e:
                logger.warning(f"Không thể subscribe action status: {e}")
        else:
            self._action_nav = None

        # 13. Clock Topic (sim profile — theo dõi /clock để phát hiện Gazebo tạm dừng/restart)
        if self._cfg.use_sim_time:
            clock_cfg = self._cfg.get_topic("clock")
            if clock_cfg and clock_cfg.enabled:
                clock_qos = _build_qos(clock_cfg.qos)
                self._sub_clock = self._node.create_subscription(
                    Clock, clock_cfg.name, self._on_clock, clock_qos
                )
                logger.info(f"Subscribed clock topic: {clock_cfg.name} (sim mode)")
            else:
                logger.warning("Profile sim nhưng chưa cấu hình topic 'clock'. Không theo dõi sim clock.")

    def _on_pose(self, msg: PoseStamped):
        """Callback cho PoseStamped (profile real hoặc các cấu hình dùng PoseStamped)."""
        with self._lock:
            q = msg.pose.orientation
            theta = quaternion_to_yaw(q.x, q.y, q.z, q.w)
            self._pose = {
                "x": float(msg.pose.position.x),
                "y": float(msg.pose.position.y),
                "theta": float(theta)
            }
            self._pose_frame_id = msg.header.frame_id
            self._pose_stamp = {
                "sec": msg.header.stamp.sec,
                "nanosec": msg.header.stamp.nanosec
            }
            self._last_pose_time = time.time()
            self._pose_received_epoch = self._pose_epoch
            self._sim_restarted = False
            self._is_connected = True
            if self._message == "Đang kết nối tới các topic ROS...":
                self._message = "Hệ thống sẵn sàng đón khách"

    def _on_amcl_pose(self, msg: PoseWithCovarianceStamped):
        """Callback cho PoseWithCovarianceStamped từ AMCL (/amcl_pose).
        Đọc msg.pose.pose (2-level nesting) thay vì msg.pose (1-level).
        Kiểm tra frame 'map', giá trị số hữu hạn, quaternion chuẩn hóa và epoch clock.
        """
        frame_id = msg.header.frame_id
        if frame_id != "map":
            logger.warning(
                f"Từ chối pose nhận được trong frame '{frame_id}' (yêu cầu bắt buộc là 'map')."
            )
            return

        pose = msg.pose.pose
        px = float(pose.position.x)
        py = float(pose.position.y)
        q = pose.orientation
        qx, qy, qz, qw = float(q.x), float(q.y), float(q.z), float(q.w)

        if not (math.isfinite(px) and math.isfinite(py) and math.isfinite(qx) and math.isfinite(qy) and math.isfinite(qz) and math.isfinite(qw)):
            logger.warning("Từ chối pose chứa giá trị không hợp lệ (NaN hoặc Inf).")
            return

        q_norm_sq = qx * qx + qy * qy + qz * qz + qw * qw
        if abs(q_norm_sq - 1.0) > 0.1 or q_norm_sq < 1e-6:
            logger.warning(f"Từ chối pose chứa quaternion không chuẩn hóa (norm={q_norm_sq:.3f}).")
            return

        with self._lock:
            pose_sec = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
            if self._cfg.use_sim_time and self._last_clock_sec is not None:
                # Nếu pose timestamp thuộc phiên trước (clock đã quay lùi mà pose cũ đến muộn)
                if pose_sec > self._last_clock_sec + 3.0:
                    logger.warning(
                        f"Từ chối pose đến muộn với timestamp {pose_sec:.1f}s vượt quá sim clock hiện tại ({self._last_clock_sec:.1f}s)."
                    )
                    return

            theta = quaternion_to_yaw(qx, qy, qz, qw)
            self._pose = {
                "x": px,
                "y": py,
                "theta": float(theta)
            }
            self._pose_frame_id = frame_id
            self._pose_stamp = {
                "sec": msg.header.stamp.sec,
                "nanosec": msg.header.stamp.nanosec
            }
            self._last_pose_time = time.time()
            self._last_pose_time_mono = time.monotonic()
            self._pose_received_epoch = self._pose_epoch
            self._sim_restarted = False
            self._is_connected = True
            if self._message == "Đang kết nối tới các topic ROS...":
                self._message = "Hệ thống sẵn sàng đón khách"

    def _on_clock(self, msg: Clock):
        """Callback /clock cho sim profile. Phát hiện clock tạm dừng và restart."""
        with self._lock:
            new_sec = msg.clock.sec + msg.clock.nanosec * 1e-9
            now_mono = time.monotonic()

            if self._last_clock_sec is not None:
                # Phát hiện clock quay lùi → sim restart
                if new_sec < self._last_clock_sec - 0.5:
                    logger.warning(
                        f"Sim clock quay lùi: {self._last_clock_sec:.1f}s → {new_sec:.1f}s. "
                        f"Đánh dấu sim restarted, vô hiệu hóa pose cũ."
                    )
                    self._sim_restarted = True
                    self._pose_epoch += 1
                    if self._navigation_state in ("PENDING", "ACCEPTED", "NAVIGATING", "PAUSING", "PAUSED"):
                        self._navigation_state = "IDLE"
                        self._current_goal_handle = None
                        self._path = None
                        self._path_version = getattr(self, "_path_version", 0) + 1

                # Phân biệt clock tiến với clock giữ nguyên cùng giá trị (sim pause)
                if new_sec > self._last_clock_sec + 1e-6:
                    self._last_clock_advancing_monotonic = now_mono
                    self._clock_stalled = False
                elif now_mono - getattr(self, "_last_clock_advancing_monotonic", now_mono) > 1.0:
                    # Clock liên tục nhận cùng một giá trị trong > 1 giây
                    self._clock_stalled = True
            else:
                self._last_clock_advancing_monotonic = now_mono
                self._clock_stalled = False

            self._last_clock_sec = new_sec
            self._last_clock_monotonic = now_mono

    @staticmethod
    def _occupancy_grid_to_png(data: Any, width: int, height: int) -> bytes:
        """
        Chuyển đổi dữ liệu OccupancyGrid 1D phẳng sang ảnh PNG theo đúng quy ước:
        - ROS OccupancyGrid: hàng j=0 là đáy bản đồ (bottom-left).
        - Ảnh PNG: hàng row=0 là đỉnh ảnh (top-left).
        - Hàng ROS j đi vào hàng PNG (height - 1 - j).
        - Ô trống (0): sáng (254)
        - Ô bị chiếm (100): đen (0)
        - Ô chưa biết (-1): xám trung tính (205)
        - Giá trị trung gian (0 < val < 100): nội suy tuyến tính (255 - int(val * 2.55))
        """
        from PIL import Image

        raw_bytes = bytearray(width * height)
        for j in range(height):
            ros_row_offset = j * width
            png_row_offset = (height - 1 - j) * width
            for i in range(width):
                val = data[ros_row_offset + i]
                if val == 0:
                    px = 254
                elif val == 100:
                    px = 0
                elif val == -1:
                    px = 205
                elif 0 < val < 100:
                    px = int(255 - (val * 2.55))
                else:
                    px = 205
                raw_bytes[png_row_offset + i] = px

        img = Image.frombytes("L", (width, height), bytes(raw_bytes))
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()

    def _on_map(self, msg: OccupancyGrid):
        width = msg.info.width
        height = msg.info.height
        res = float(msg.info.resolution)

        # 1. Validation kiểm tra kích thước dương, resolution hữu hạn và dương
        if width <= 0 or height <= 0:
            logger.warning(f"Bỏ qua /map: kích thước không hợp lệ ({width}x{height})")
            return
        if not math.isfinite(res) or res <= 0.0:
            logger.warning(f"Bỏ qua /map: resolution không hợp lệ ({res})")
            return
        if len(msg.data) != width * height:
            logger.warning(f"Bỏ qua /map: độ dài dữ liệu ({len(msg.data)}) != width*height ({width * height})")
            return

        # 2. Tính toán origin và yaw
        orig = msg.info.origin
        q = orig.orientation
        origin_yaw = quaternion_to_yaw(q.x, q.y, q.z, q.w)
        meta = MapMetadata(
            resolution=res,
            width=width,
            height=height,
            origin_x=float(orig.position.x),
            origin_y=float(orig.position.y),
            origin_yaw=float(origin_yaw)
        )
        frame_id = msg.header.frame_id or "map"
        stamp = {
            "sec": msg.header.stamp.sec,
            "nanosec": msg.header.stamp.nanosec
        }

        # 3. Tạo ảnh PNG ngoài lock để không block thread ROS spin
        try:
            png_bytes = self._occupancy_grid_to_png(msg.data, width, height)
        except Exception as e:
            logger.error(f"Lỗi khi mã hóa ảnh PNG từ OccupancyGrid: {e}")
            return

        # 4. Sinh định danh phiên bản mới duy nhất (không trùng lặp sau restart)
        new_version = f"{int(time.time())}-{uuid.uuid4().hex[:8]}"

        # 5. Cập nhật nguyên tử: Metadata và PNG chỉ được công bố cùng nhau khi ảnh đã sẵn sàng
        with self._lock:
            self._map_meta = meta
            self._map_frame_id = frame_id
            self._map_stamp = stamp
            self._map_version = new_version
            self._map_png = png_bytes
            self._occupancy_grid_data = list(msg.data)
            logger.info(
                f"Đã cập nhật bản đồ OccupancyGrid: {width}x{height}, res={res:.4f}m, "
                f"origin=({meta.origin_x:.2f}, {meta.origin_y:.2f}, yaw={meta.origin_yaw:.3f}), "
                f"version={new_version}, size={len(png_bytes)} bytes"
            )

    def _on_robot_state(self, msg):
        with self._lock:
            self._control_mode = msg.control_mode
            self._navigation_state = msg.navigation_state
            self._has_goal = msg.has_goal
            self._goal_id = msg.goal_id
            self._destination_id = msg.destination_id
            self._message = msg.message
            self._last_state_time = time.time()
            self._is_connected = True

    def _on_destinations(self, msg):
        with self._lock:
            self._destinations = [
                {
                    "id": d.id,
                    "name": d.name,
                    "map_id": d.map_id,
                    "pose": {
                        "position": {"x": d.pose.pose.position.x, "y": d.pose.pose.position.y, "z": d.pose.pose.position.z},
                        "orientation": {
                            "x": d.pose.pose.orientation.x,
                            "y": d.pose.pose.orientation.y,
                            "z": d.pose.pose.orientation.z,
                            "w": d.pose.pose.orientation.w
                        }
                    }
                }
                for d in msg.destinations
            ]

    def _on_voice_state(self, msg: String):
        with self._lock:
            self._voice_state = msg.data

    def _on_voice_transcript(self, msg: String):
        """Callback nhận kết quả nhận dạng giọng nói từ ROS topic (/airport/voice/transcript).
        Tránh hoàn toàn khóa lồng nhau (deadlock).
        Interface ROS hiện tại dùng std_msgs/String không có trường correlation (session_id / request_id).
        Do đó đề xuất tự động trong ROS mode được giữ an toàn (khóa) cho đến khi có ROS interface hợp đồng đầy đủ.
        """
        transcript_text = str(msg.data).strip() if msg.data else ""
        with self._lock:
            self._voice_transcript = transcript_text
            # Ghi nhận transcript nhưng không tạo proposal tự động khi thiếu hợp đồng phiên ROS
            self._voice_proposal = None
            logger.debug(
                f"Nhận transcript từ ROS voice node: '{transcript_text}'. "
                f"Interface std_msgs/String chưa có trường session_id; giữ đề xuất khóa trong ROS mode."
            )

    def _on_alerts(self, msg: DiagnosticArray):
        with self._lock:
            self._alerts = [
                {
                    "name": s.name,
                    "level": s.level,
                    "message": s.message,
                    "hardware_id": s.hardware_id
                }
                for s in msg.status
            ]

    def _on_battery(self, msg: BatteryState):
        with self._lock:
            if math.isnan(msg.percentage):
                self._battery_percent = None
            else:
                self._battery_percent = float(msg.percentage)

    def _on_path(self, msg: NavPath):
        with self._lock:
            # 1. Kiểm tra frame_id phải khớp frame map
            map_frame = self._cfg.frames.get("map", "map")
            msg_frame = getattr(getattr(msg, "header", None), "frame_id", "")
            if msg_frame != map_frame:
                logger.warning(f"Bỏ qua nav_msgs/Path vì frame '{msg_frame}' không khớp map frame '{map_frame}'")
                return

            # 2. Chỉ tiếp nhận khi đang có chuyến dẫn đường đang hoạt động của hệ thống
            if self._navigation_state not in ("ACCEPTED", "NAVIGATING"):
                return

            # 3. Chốt chặn quyền sở hữu: Phải sở hữu goal handle tích cực từ backend
            if not getattr(self, "_current_goal_handle", None):
                logger.debug("Bỏ qua nav_msgs/Path: backend không sở hữu goal handle tích cực")
                return

            poses = getattr(msg, "poses", [])
            if not poses:
                return

            # 4. Chốt chặn dung sai endpoint: Điểm cuối của Path phải khớp mục tiêu chuyến đi (dung sai 2.0m)
            target = getattr(self, "_current_target_pose", None)
            if target is not None:
                last_pos = poses[-1].pose.position
                endpoint_dist = math.hypot(float(last_pos.x) - target["x"], float(last_pos.y) - target["y"])
                if endpoint_dist > 2.0:
                    logger.warning(
                        f"Bỏ qua nav_msgs/Path: điểm cuối ({last_pos.x:.2f}, {last_pos.y:.2f}) "
                        f"cách mục tiêu ({target['x']:.2f}, {target['y']:.2f}) {endpoint_dist:.2f}m > dung sai 2.0m"
                    )
                    return

            self._path = [
                {"x": float(p.pose.position.x), "y": float(p.pose.position.y)}
                for p in poses
            ]
            self._path_version = getattr(self, "_path_version", 0) + 1

    def has_valid_pose(self) -> bool:
        """Kiểm tra xem robot đã có tọa độ định vị AMCL hợp lệ trong frame map hay chưa"""
        with self._lock:
            return self._has_valid_pose_locked()

    def _has_valid_pose_locked(self) -> bool:
        if not self._pose:
            return False
        if getattr(self, "_pose_frame_id", "") != "map":
            return False
        x = self._pose.get("x")
        y = self._pose.get("y")
        theta = self._pose.get("theta")
        if not (isinstance(x, (int, float)) and isinstance(y, (int, float)) and isinstance(theta, (int, float))):
            return False
        if not (math.isfinite(x) and math.isfinite(y) and math.isfinite(theta)):
            return False
        if hasattr(self, "_cfg") and self._cfg and self._cfg.use_sim_time:
            if getattr(self, "_sim_restarted", False):
                return False
            if getattr(self, "_pose_received_epoch", 0) != getattr(self, "_pose_epoch", 0):
                return False
        return True

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            now = time.time()
            now_mono = time.monotonic()

            if self._cfg.use_sim_time:
                # --- Sim profile: logic dựa trên /clock ---
                # Clock stalled: không nhận /clock message > 3 giây (wall clock)
                if self._last_clock_sec is not None:
                    if (now_mono - self._last_clock_monotonic) > 3.0:
                        self._clock_stalled = True
                else:
                    self._clock_stalled = True

                # Pose hợp lệ: dùng hàm kiểm tra chuẩn hóa
                has_valid_pose = self._has_valid_pose_locked()

                # is_connected cho sim:
                # - True nếu có pose hợp lệ và sim clock đang hoạt động
                is_conn = has_valid_pose and not self._clock_stalled

                # is_data_stale cho sim:
                # - Clock stalled → dữ liệu không được cập nhật (sim không tiến)
                # - Sim restarted và chưa có pose mới → dữ liệu cũ
                # - Chưa nhận pose nào → stale
                is_stale = False
                if self._clock_stalled:
                    is_stale = True
                elif self._sim_restarted or not has_valid_pose:
                    is_stale = True
                elif self._pose is None:
                    is_stale = True

                # Message mô tả trạng thái
                if self._pose is None:
                    if self._last_clock_sec is None:
                        status_message = "Đang chờ mô phỏng Gazebo/Nav2 khởi động..."
                    else:
                        status_message = "Đang chờ dữ liệu vị trí từ AMCL..."
                elif self._clock_stalled:
                    status_message = "Mô phỏng không cập nhật (clock ngừng tiến)"
                elif self._sim_restarted or (self._pose_received_epoch != self._pose_epoch):
                    status_message = "Mô phỏng đang khởi động lại, chờ vị trí mới từ AMCL..."
                elif self._message == "Đang kết nối tới các topic ROS...":
                    status_message = "Hệ thống sẵn sàng đón khách"
                else:
                    status_message = self._message
            else:
                # --- Real profile: logic thời gian (backward compat) ---
                is_stale = (now - self._last_pose_time) > 1.5 if self._last_pose_time > 0 else True
                is_conn = (now - self._last_pose_time) < 5.0 if self._last_pose_time > 0 else False
                status_message = self._message

            result = {
                "pose": dict(self._pose) if self._pose else None,
                "battery_percent": self._battery_percent,
                "is_connected": is_conn,
                "is_data_stale": is_stale,
                "control_mode": self._control_mode,
                "navigation_state": self._navigation_state,
                "has_goal": self._has_goal,
                "goal_id": self._goal_id,
                "trip_id": getattr(self, "_trip_id", ""),
                "destination_id": self._destination_id,
                "distance_remaining": self._distance_remaining,
                "estimated_time_remaining": self._estimated_time_remaining,
                "number_of_recoveries": self._number_of_recoveries,
                "voice_state": self._voice_state,
                "voice_transcript": self._voice_transcript,
                "voice_response": self._voice_response,
                "voice_requester_id": getattr(self, "_voice_requester_id", ""),
                "voice_available": self.is_voice_available(),
                "message": status_message,
                "last_updated": int(now * 1000),
                "frame_id": self._pose_frame_id,
                "stamp": self._pose_stamp,
                "map_version": self._map_version,
                "destinations_version": getattr(self, "_destinations_version", 0),
                "spin_thread_alive": bool(hasattr(self, "_spin_thread") and self._spin_thread and self._spin_thread.is_alive()),
                "last_clock_time": self._last_clock_monotonic,
                "last_pose_time": self._last_pose_time,
                "last_map_time": getattr(self, "_last_map_time", 0.0),
                "manual_consumer_available": self.is_manual_consumer_available(),
                "manual_operator_id": getattr(self, "_manual_operator_id", None),
                "external_goal_active": getattr(self, "_nav2_has_active_goal", False),
            }

            result["readiness"] = self._get_readiness_locked()

            if self._cfg.use_sim_time:
                result["sim_clock_stalled"] = self._clock_stalled
                result["sim_restarted"] = self._sim_restarted and not (
                    self._pose_received_epoch == self._pose_epoch
                )

            return result

    def get_readiness(self) -> Dict[str, Any]:
        with self._lock:
            return self._get_readiness_locked()

    def _get_readiness_locked(self) -> Dict[str, Any]:
        reasons = []
        if hasattr(self, "_action_nav") and self._action_nav is not None:
            try:
                if not self._action_nav.server_is_ready():
                    reasons.append("Action server Nav2 (/navigate_to_pose) chưa sẵn sàng.")
            except Exception:
                reasons.append("Không thể kết nối tới Action server Nav2.")
        elif not HAS_NAV2_ACTION:
            reasons.append("Nav2 action client chưa được nạp trong môi trường ROS.")

        if not getattr(self, "_is_connected", False):
            reasons.append("Chưa kết nối với hệ thống ROS 2 hoặc robot đang offline.")
        if self._cfg.use_sim_time and getattr(self, "_clock_stalled", False):
            reasons.append("Mô phỏng Gazebo đang tạm dừng (clock không tiến).")
        if not self._has_valid_pose_locked():
            reasons.append("Chưa có vị trí định vị robot hợp lệ từ AMCL trong frame map.")
        if not getattr(self, "_map_version", None) or not getattr(self, "_map_png", None):
            reasons.append("Chưa nhận được bản đồ OccupancyGrid từ ROS (/map).")
        if self._control_mode == "MANUAL":
            reasons.append("Robot đang ở chế độ MANUAL (Cần chuyển sang AUTO trước khi dẫn đường).")
        if self._navigation_state in ("PENDING", "ACCEPTED", "NAVIGATING", "PAUSING", "PAUSED", "CANCELING"):
            reasons.append(f"Robot đang có chuyến dẫn đường hoạt động ({self._navigation_state}).")
        if getattr(self, "_nav2_has_active_goal", False) and not self._current_goal_handle:
            reasons.append("Nav2 đang bận thực hiện mục tiêu ngoại vi (từ RViz hoặc phiên trước).")

        return {
            "ready": len(reasons) == 0,
            "reasons": reasons,
            "reason": reasons[0] if reasons else "Hệ thống sẵn sàng đón khách"
        }

    def _load_destinations(self) -> List[Dict[str, Any]]:
        """
        Đọc danh sách điểm đến:
        1. Ưu tiên đọc từ tệp lưu trữ bền vững (data/destinations.yaml).
           Nếu tệp lưu trữ tồn tại (kể cả khi rỗng 'destinations: []'), nạp danh sách đó
           và không bao giờ quay lại nạp seed file.
        2. Chỉ dùng YAML seed (config/destinations.yaml) khi CHƯA CÓ tệp dữ liệu lưu.
        3. Khởi động lại hoặc recreate backend sẽ đọc tiếp từ tệp lưu trữ, không ghi đè dữ liệu cũ.
        """
        # 1. Thử đọc từ tệp lưu trữ bền vững (nếu tệp đã tồn tại)
        if hasattr(self, "_destinations_file") and self._destinations_file.is_file():
            try:
                with open(self._destinations_file, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                    if isinstance(data, dict):
                        dests = data.get("destinations")
                        if dests is None:
                            dests = []
                        logger.info(f"Đã nạp {len(dests)} điểm đến từ tệp lưu trữ bền vững: {self._destinations_file}")
                        return list(dests)
            except Exception as e:
                logger.warning(f"Lỗi khi đọc file destinations lưu trữ {self._destinations_file}: {e}")
                return []
            return []

        # 2. Nếu chưa có tệp dữ liệu lưu trữ, nạp từ tệp seed khởi tạo
        if hasattr(self, "_destinations_seed_file") and self._destinations_seed_file.is_file():
            try:
                with open(self._destinations_seed_file, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                    if isinstance(data, dict) and "destinations" in data and data["destinations"] is not None:
                        dests = data["destinations"]
                        logger.info(f"Đã nạp {len(dests)} điểm đến khởi tạo từ tệp seed: {self._destinations_seed_file}")
                        return list(dests)
            except Exception as e:
                logger.warning(f"Lỗi khi đọc file destinations seed {self._destinations_seed_file}: {e}")

        return []

    def _write_destinations_file(self, destinations_data: List[Dict[str, Any]]) -> Tuple[bool, str]:
        """
        Lưu danh sách điểm đến bền vững ra tệp YAML (I/O độc lập với self._lock).
        - Ghi an toàn thông qua tệp tạm (atomic write với os.replace).
        - Nếu có lỗi ghi giữa chừng, tệp gốc không bị mất hoặc hỏng.
        - Xử lý đồng thời I/O được bảo vệ bởi self._io_lock.
        """
        temp_file = None
        try:
            target_file = self._destinations_file
            target_file.parent.mkdir(parents=True, exist_ok=True)
            if target_file.exists() and not os.access(target_file, os.W_OK):
                raise PermissionError(f"Tệp {target_file} ở chế độ chỉ đọc (Read-only)")
            if not os.access(target_file.parent, os.W_OK):
                raise PermissionError(f"Thư mục {target_file.parent} ở chế độ chỉ đọc (Read-only mount)")
            temp_file = target_file.with_name(f"{target_file.name}.tmp.{uuid.uuid4().hex}")

            with open(temp_file, "w", encoding="utf-8") as f:
                yaml.dump({
                    "map_id": "airport_floor_1",
                    "destinations": destinations_data
                }, f, allow_unicode=True, sort_keys=False)
                f.flush()
                os.fsync(f.fileno())

            # Hoán đổi nguyên tử (atomic replace)
            os.replace(temp_file, target_file)
            logger.info(f"Đã lưu an toàn {len(destinations_data)} điểm đến vào {target_file}")
            return True, "Thành công"
        except OSError as e:
            if temp_file and temp_file.exists():
                try:
                    temp_file.unlink()
                except Exception:
                    pass
            msg = f"Không thể lưu điểm đến vào {self._destinations_file}: Hệ thống tệp hoặc quyền ghi ({e})"
            logger.error(msg)
            return False, msg
        except Exception as e:
            if temp_file and temp_file.exists():
                try:
                    temp_file.unlink()
                except Exception:
                    pass
            msg = f"Lỗi không xác định khi lưu điểm đến: {e}"
            logger.error(msg)
            return False, msg

    def _save_destinations(self) -> Tuple[bool, str]:
        if not hasattr(self, "_io_lock"):
            self._io_lock = threading.Lock()
        with self._lock:
            snapshot = list(self._destinations)
        with self._io_lock:
            return self._write_destinations_file(snapshot)

    def validate_destination_coordinates(self, dest: Dict[str, Any]) -> Dict[str, Any]:
        """
        Kiểm tra tính hợp lệ của tọa độ điểm đến:
        - Tọa độ là số thực hữu hạn (finite numbers)
        - Frame khớp với frame bản đồ ('map')
        - Bản đồ hiện tại đã sẵn sàng (không cho phép khi thiếu metadata bản đồ)
        - Hỗ trợ origin xoay (origin_yaw != 0) và kích thước động của bản đồ
        - Nằm trong phạm vi biên của OccupancyGrid
        - Nằm trong ô trống (free space, cell value == 0),
          không rơi vào vật cản (cell value > 50) hoặc vùng chưa quét (cell value < 0).
        """
        pose = dest.get("pose", {})
        pos = pose.get("position", {})
        x = pos.get("x")
        y = pos.get("y")

        if x is None or y is None:
            return {"valid": False, "message": "Tọa độ x, y không được để trống"}

        try:
            fx = float(x)
            fy = float(y)
        except (ValueError, TypeError):
            return {"valid": False, "message": "Tọa độ x, y phải là số thực"}

        if not math.isfinite(fx) or not math.isfinite(fy):
            return {"valid": False, "message": "Tọa độ x, y phải là số hữu hạn"}

        frame_id = pose.get("header", {}).get("frame_id") or dest.get("frame_id") or "map"
        expected_frame = self._cfg.frames.get("map", "map")
        if frame_id != expected_frame:
            return {"valid": False, "message": f"Frame '{frame_id}' không khớp với frame bản đồ '{expected_frame}'"}

        # 1. Kiểm tra bản đồ đã sẵn sàng chưa (trường hợp thiếu bản đồ)
        if not self._map_meta or self._map_meta.width <= 0 or self._map_meta.height <= 0 or self._map_meta.resolution <= 0:
            return {"valid": False, "message": "Bản đồ chưa sẵn sàng từ ROS, chưa thể xác thực tọa độ điểm đến"}

        meta = self._map_meta
        res = meta.resolution
        dx = fx - meta.origin_x
        dy = fy - meta.origin_y
        yaw = meta.origin_yaw

        # 2. Xoay tọa độ vào hệ quy chiếu cục bộ của ma trận bản đồ (hỗ trợ origin_yaw != 0)
        if abs(yaw) > 1e-6:
            cos_yaw = math.cos(yaw)
            sin_yaw = math.sin(yaw)
            x_local = dx * cos_yaw + dy * sin_yaw
            y_local = -dx * sin_yaw + dy * cos_yaw
        else:
            x_local = dx
            y_local = dy

        map_w = meta.width * res
        map_h = meta.height * res

        # 3. Kiểm tra biên bản đồ trong hệ cục bộ
        if x_local < 0.0 or x_local >= map_w or y_local < 0.0 or y_local >= map_h:
            return {
                "valid": False,
                "message": f"Tọa độ ({fx:.2f}, {fy:.2f}) nằm ngoài biên bản đồ [{meta.origin_x:.2f}, {meta.origin_x + map_w:.2f}] x [{meta.origin_y:.2f}, {meta.origin_y + map_h:.2f}]"
            }

        col = int(x_local / res)
        row = int(y_local / res)

        if not (0 <= col < meta.width and 0 <= row < meta.height):
            return {
                "valid": False,
                "message": f"Tọa độ ({fx:.2f}, {fy:.2f}) nằm ngoài biên bản đồ"
            }

        # 4. Kiểm tra ô trống OccupancyGrid nếu có dữ liệu
        if self._occupancy_grid_data:
            idx = row * meta.width + col
            if 0 <= idx < len(self._occupancy_grid_data):
                val = self._occupancy_grid_data[idx]
                if val > 50:
                    return {"valid": False, "message": f"Tọa độ ({fx:.2f}, {fy:.2f}) rơi vào vật cản/tường (cell={val})"}
                elif val < 0:
                    return {"valid": False, "message": f"Tọa độ ({fx:.2f}, {fy:.2f}) rơi vào vùng chưa quét/chưa biết (cell={val})"}

        return {"valid": True, "message": "Tọa độ hợp lệ"}

    def get_destinations(self) -> List[Dict[str, Any]]:
        """
        Trả về danh sách tất cả các điểm đến đã được nạp/lưu.
        """
        with self._lock:
            return list(self._destinations)

    def get_destinations_version(self) -> int:
        with self._lock:
            return getattr(self, "_destinations_version", 0)

    def upsert_destination(self, destination: Dict[str, Any]) -> Dict[str, Any]:
        """
        Thêm mới hoặc cập nhật một điểm đến lưu bền vững (Admin).
        Nếu không thể lưu ra file YAML (ví dụ filesystem read-only), báo lỗi thực tế và không lưu vào bộ nhớ.
        File I/O được thực hiện ngoài self._lock (dưới self._io_lock) để không chặn watchdog hay các lệnh vận tốc.
        """
        dest_id = destination.get("id")
        name = destination.get("name")
        if not dest_id or not str(dest_id).strip():
            return {"success": False, "message": "ID điểm đến không được để trống"}
        if not name or not str(name).strip():
            return {"success": False, "message": "Tên điểm đến không được để trống"}

        dest_id = str(dest_id).strip()

        # Xác thực tọa độ
        val_res = self.validate_destination_coordinates(destination)
        if not val_res.get("valid"):
            return {"success": False, "message": val_res.get("message")}

        clean_dest = {
            "id": dest_id,
            "name": str(name).strip(),
            "map_id": destination.get("map_id", "airport_floor_1"),
            "pose": destination.get("pose", {})
        }

        if not hasattr(self, "_io_lock"):
            self._io_lock = threading.Lock()

        # Thực hiện transaction tuần tự qua _io_lock để tránh race condition giữa các thread
        with self._io_lock:
            with self._lock:
                # Kiểm tra xem có đang dẫn đường tới điểm này không (kể cả khi tạm dừng hoặc đang hủy)
                if self._navigation_state in ("PENDING", "ACCEPTED", "NAVIGATING", "PAUSING", "PAUSED", "CANCELING") and self._destination_id == dest_id:
                    return {"success": False, "message": f"Không thể cập nhật điểm đến '{dest_id}' khi đang có chuyến dẫn đường tới điểm này (trạng thái: {self._navigation_state})"}

                # Xây dựng bản sao mới mà KHÔNG làm thay đổi self._destinations trong bộ nhớ trước khi ghi file
                new_destinations = [dict(d) for d in self._destinations]
                found = False
                for idx, d in enumerate(new_destinations):
                    if d.get("id") == dest_id:
                        new_destinations[idx] = clean_dest
                        found = True
                        break
                if not found:
                    new_destinations.append(clean_dest)

                snapshot = list(new_destinations)

            # Lưu file bền vững ngoài self._lock (dưới self._io_lock) để không chặn watchdog hay lệnh vận tốc
            saved, save_err = self._write_destinations_file(snapshot)

            with self._lock:
                if not saved:
                    # Ghi file thất bại: Bộ nhớ hoàn toàn không bị ảnh hưởng, không cần rollback
                    return {"success": False, "message": f"Không thể lưu điểm đến: {save_err}"}

                # Ghi file thành công: Commit vào bộ nhớ và tăng version
                self._destinations = new_destinations
                self._destinations_version = getattr(self, "_destinations_version", 0) + 1
                event_logger.add_event("SUCCESS", "DESTINATION", f"Đã lưu điểm đến '{name}' ({dest_id})")
                return {"success": True, "message": f"Đã lưu điểm đến '{name}' thành công"}

    def delete_destination(self, destination_id: str) -> Dict[str, Any]:
        """
        Xóa một điểm đến lưu bền vững (Admin).
        - Yêu cầu destination_id hợp lệ.
        - Chặn xóa điểm đang có chuyến dẫn đường chưa kết thúc (PENDING, ACCEPTED, NAVIGATING, CANCELING).
        - File I/O ngoài self._lock dưới self._io_lock.
        - Giao dịch an toàn: Chỉ commit bộ nhớ khi ghi file thành công.
        """
        dest_id = str(destination_id).strip()
        if not dest_id:
            return {"success": False, "message": "ID điểm đến không được để trống"}

        if not hasattr(self, "_io_lock"):
            self._io_lock = threading.Lock()

        # Thực hiện transaction tuần tự qua _io_lock
        with self._io_lock:
            with self._lock:
                # Chặn xóa điểm đang dùng cho một chuyến chưa kết thúc (kể cả khi tạm dừng hoặc đang hủy)
                if self._navigation_state in ("PENDING", "ACCEPTED", "NAVIGATING", "PAUSING", "PAUSED", "CANCELING") and self._destination_id == dest_id:
                    return {
                        "success": False,
                        "message": f"Không thể xóa điểm đến '{dest_id}' vì đang có chuyến dẫn đường chưa kết thúc tới điểm này (trạng thái: {self._navigation_state})"
                    }

                # Tìm điểm cần xóa
                existing_idx = next((i for i, d in enumerate(self._destinations) if d.get("id") == dest_id), None)
                if existing_idx is None:
                    return {"success": False, "message": f"Không tìm thấy điểm đến có ID '{dest_id}'"}

                # Xây dựng danh sách mới mà KHÔNG làm thay đổi self._destinations trong bộ nhớ
                new_destinations = [dict(d) for d in self._destinations]
                deleted_dest = new_destinations.pop(existing_idx)
                deleted_name = deleted_dest.get("name") or dest_id
                snapshot = list(new_destinations)

            # Lưu bền vững ra tệp YAML ngoài self._lock (dưới self._io_lock)
            saved_ok, save_err = self._write_destinations_file(snapshot)

            with self._lock:
                if not saved_ok:
                    # Ghi file thất bại: Bộ nhớ không đổi
                    return {"success": False, "message": f"Không thể lưu điểm đến sau khi xóa: {save_err}"}

                # Ghi file thành công: Commit bộ nhớ
                self._destinations = new_destinations
                self._destinations_version = getattr(self, "_destinations_version", 0) + 1
                event_logger.add_event("INFO", "DESTINATION", f"Đã xóa điểm đến '{deleted_name}' ({dest_id})")
                logger.info(
                    f"Đã xóa thành công điểm đến '{dest_id}' ({deleted_name}). "
                    f"Danh sách còn lại {len(self._destinations)} điểm. destinations_version={self._destinations_version}"
                )
                return {
                    "success": True,
                    "message": f"Đã xóa thành công điểm đến '{deleted_name}'",
                    "destinations_version": self._destinations_version,
                }

    def start_navigation(self, destination_id: str, owner_id: str) -> Dict[str, Any]:
        with self._lock:
            # 1. Kiểm tra action client và ROS packages
            if not getattr(self, "_action_nav", None) or not HAS_NAV2_ACTION:
                return {"success": False, "message": "Action client Nav2 chưa được khởi tạo."}

            # 2. Kiểm tra chế độ điều khiển
            if self._control_mode == "MANUAL" or getattr(self, "_active_hold_id", None) is not None:
                return {"success": False, "message": "Không thể bắt đầu dẫn đường: Robot đang trong chế độ điều khiển thủ công (MANUAL) hoặc lượt điều khiển tay."}

            # 3. Kiểm tra sim clock stalled (nếu dùng sim time)
            if self._cfg.use_sim_time and getattr(self, "_clock_stalled", False):
                return {"success": False, "message": "Mô phỏng đang tạm dừng (sim clock stalled). Không thể gửi mục tiêu."}

            if self._cfg.use_sim_time and (
                getattr(self, "_sim_restarted", False)
                or getattr(self, "_pose_received_epoch", 0) != getattr(self, "_pose_epoch", 0)
            ):
                return {
                    "success": False,
                    "message": "Mô phỏng vừa khởi động lại. Đang chờ dữ liệu vị trí robot mới từ AMCL."
                }

            # 4. Kiểm tra xem robot có đang bận thực hiện chuyến nào không (Chống gửi trùng)
            if self._navigation_state in ("PENDING", "ACCEPTED", "NAVIGATING", "PAUSING", "PAUSED", "CANCELING"):
                return {
                    "success": False,
                    "message": f"Robot đang có chuyến dẫn đường đang hoạt động hoặc tạm dừng (trạng thái: {self._navigation_state})."
                }

            # 4b. Kiểm tra nếu Nav2 đang bận thực hiện mục tiêu ngoại vi (từ RViz hoặc do backend restart chưa xong)
            if getattr(self, "_nav2_has_active_goal", False) and not self._current_goal_handle:
                return {
                    "success": False,
                    "message": "Nav2 đang thực hiện một mục tiêu khác (từ RViz hoặc phiên trước). Vui lòng chờ hoàn thành trước khi gửi mục tiêu mới."
                }

            # 5. Kiểm tra vị trí robot hiện tại
            if not self._pose:
                return {"success": False, "message": "Chưa có vị trí robot từ hệ thống định vị (AMCL)."}

            # 6. Tìm điểm đến hợp lệ
            dest = next((d for d in self._destinations if d.get("id") == destination_id), None)
            if not dest:
                return {"success": False, "message": "Không tìm thấy điểm đến yêu cầu."}

            # Xác thực lại tọa độ điểm đến
            val_res = self.validate_destination_coordinates(dest)
            if not val_res.get("valid"):
                return {"success": False, "message": f"Tọa độ điểm đến không hợp lệ: {val_res.get('message')}"}

            # 7. Kiểm tra server action sẵn sàng (không block FastAPI hoặc ROS executor)
            if not self._action_nav.server_is_ready():
                if not self._action_nav.wait_for_server(timeout_sec=0.5):
                    return {"success": False, "message": "Server action điều hướng /navigate_to_pose chưa sẵn sàng."}

            # 8. Chuẩn bị Goal message Nav2
            goal_msg = NavigateToPose.Goal()
            frame_id = self._cfg.frames.get("map", "map")
            goal_msg.pose.header.frame_id = frame_id
            goal_msg.pose.header.stamp = self._node.get_clock().now().to_msg()

            pos = dest["pose"]["position"]
            orient = dest["pose"].get("orientation", {})
            goal_msg.pose.pose.position.x = float(pos["x"])
            goal_msg.pose.pose.position.y = float(pos["y"])
            goal_msg.pose.pose.position.z = float(pos.get("z", 0.0))
            goal_msg.pose.pose.orientation.x = float(orient.get("x", 0.0))
            goal_msg.pose.pose.orientation.y = float(orient.get("y", 0.0))
            goal_msg.pose.pose.orientation.z = float(orient.get("z", 0.0))
            goal_msg.pose.pose.orientation.w = float(orient.get("w", 1.0))

            # 9. Khởi tạo phiên request ID
            req_id = uuid.uuid4().hex
            self._trip_id = uuid.uuid4().hex
            self._active_request_id = req_id
            self._cancel_requested_for = None
            self._pause_requested_for = None
            self._owner_id = owner_id
            self._destination_id = destination_id
            self._current_target_pose = {"x": float(pos["x"]), "y": float(pos["y"])}
            self._current_goal_dispatch_time = time.time()
            self._navigation_state = "PENDING"
            self._has_goal = True
            self._path = None
            self._path_version = getattr(self, "_path_version", 0) + 1
            dest_name = dest.get("name", destination_id)
            self._message = f"Đang gửi yêu cầu dẫn đường tới: {dest_name}..."
            self._distance_remaining = None
            self._estimated_time_remaining = None
            self._number_of_recoveries = 0

            # 10. Gửi bất đồng bộ kèm callbacks
            try:
                send_future = self._action_nav.send_goal_async(
                    goal_msg,
                    feedback_callback=self._on_nav_feedback
                )
                send_future.add_done_callback(lambda f: self._on_goal_response(f, req_id, dest_name, is_resume=False))
            except Exception as e:
                logger.error(f"Lỗi khi gọi send_goal_async: {e}")
                self._navigation_state = "FAILED"
                self._has_goal = False
                self._message = f"Lỗi khi gửi mục tiêu tới Nav2: {e}"
                return {"success": False, "message": self._message}

            return {
                "success": True,
                "request_id": req_id,
                "trip_id": self._trip_id,
                "destination_id": destination_id,
                "message": f"Đã tiếp nhận yêu cầu dẫn đường tới {dest_name}. Đang chờ Nav2 chấp thuận..."
            }

    def _on_goal_response(self, future, req_id: str, dest_name: str, is_resume: bool = False):
        """Callback khi server Nav2 phản hồi chấp thuận hoặc từ chối Goal."""
        with self._lock:
            if req_id != self._active_request_id:
                logger.warning(f"Bỏ qua phản hồi goal cũ (req_id={req_id}, active={self._active_request_id})")
                try:
                    gh = future.result()
                    if gh and gh.accepted:
                        gh.cancel_goal_async()
                except Exception:
                    pass
                return

            try:
                goal_handle = future.result()
            except Exception as e:
                logger.error(f"Lỗi khi nhận kết quả goal handle: {e}")
                if is_resume:
                    self._navigation_state = "PAUSED"
                    self._has_goal = False
                    self._message = f"Lỗi phản hồi từ Nav2 khi tiếp tục: {e}. Vẫn giữ trạng thái tạm dừng."
                else:
                    self._navigation_state = "FAILED"
                    self._has_goal = False
                    self._message = f"Lỗi phản hồi từ Nav2: {e}"
                return

            if not goal_handle.accepted:
                logger.warning(f"Nav2 từ chối goal {req_id} tới {dest_name} (is_resume={is_resume})")
                if is_resume:
                    self._navigation_state = "PAUSED"
                    self._has_goal = False
                    self._current_goal_handle = None
                    self._message = f"Nav2 từ chối tiếp tục dẫn đường tới '{dest_name}'. Vẫn giữ trạng thái tạm dừng."
                else:
                    self._navigation_state = "FAILED"
                    self._has_goal = False
                    self._current_goal_handle = None
                    self._message = f"Mục tiêu tới '{dest_name}' bị Nav2 từ chối (không thể lập quỹ đạo an toàn)."
                return

            # Goal đã được Nav2 chấp nhận
            self._current_goal_handle = goal_handle
            try:
                raw_uuid = bytes(goal_handle.goal_id.uuid)
                self._goal_id = uuid.UUID(bytes=raw_uuid).hex
            except Exception:
                self._goal_id = req_id

            logger.info(f"Nav2 đã chấp nhận goal {self._goal_id} (req={req_id}, is_resume={is_resume}) tới {dest_name}")

            # Kiểm tra xem người dùng có bấm Hủy hoặc Tạm dừng trong khi đang ở trạng thái PENDING không
            if getattr(self, "_cancel_requested_for", None) == req_id:
                logger.info(f"Goal {self._goal_id} có yêu cầu hủy trước đó. Gửi lệnh cancel_goal_async...")
                self._navigation_state = "CANCELING"
                self._message = "Đang dừng robot và hủy chuyến..."
                cancel_future = goal_handle.cancel_goal_async()
                cancel_future.add_done_callback(lambda f: self._on_cancel_response(f, req_id))
            elif getattr(self, "_pause_requested_for", None) == req_id:
                logger.info(f"Goal {self._goal_id} có yêu cầu tạm dừng trước đó. Gửi lệnh cancel_goal_async...")
                self._navigation_state = "PAUSING"
                self._message = "Đang dừng robot và tạm dừng chuyến đi..."
                cancel_future = goal_handle.cancel_goal_async()
                cancel_future.add_done_callback(lambda f: self._on_cancel_response(f, req_id))
            else:
                self._navigation_state = "NAVIGATING"
                self._message = f"Nav2 đang tiếp tục dẫn đường tới: {dest_name}." if is_resume else f"Nav2 đang dẫn đường tới: {dest_name}."
                if is_resume:
                    event_logger.add_event("INFO", "NAVIGATION", f"Tiếp tục chuyến dẫn đường tới điểm: {dest_name}")
                else:
                    event_logger.add_event("INFO", "NAVIGATION", f"Bắt đầu chuyến dẫn đường tới điểm: {dest_name}")

            # Đăng ký nhận kết quả hoàn thành (Result callback)
            result_future = goal_handle.get_result_async()
            result_future.add_done_callback(lambda f: self._on_nav_result(f, req_id, dest_name))

    def _on_nav_feedback(self, feedback_msg):
        """Callback nhận telemetry tiến trình điều hướng từ Nav2."""
        with self._lock:
            if not self._has_goal or self._navigation_state not in ("NAVIGATING", "CANCELING"):
                return

            feedback = getattr(feedback_msg, "feedback", None)
            if not feedback:
                return

            if hasattr(feedback, "distance_remaining"):
                dist = float(feedback.distance_remaining)
                if math.isfinite(dist):
                    self._distance_remaining = dist

            if hasattr(feedback, "estimated_time_remaining"):
                dur = feedback.estimated_time_remaining
                self._estimated_time_remaining = float(dur.sec) + float(dur.nanosec) * 1e-9

            if hasattr(feedback, "number_of_recoveries"):
                self._number_of_recoveries = int(feedback.number_of_recoveries)

            if self._navigation_state == "NAVIGATING":
                dest = next((d for d in self._destinations if d.get("id") == self._destination_id), None)
                dest_name = dest.get("name", "") if dest else ""
                if self._distance_remaining is not None:
                    self._message = f"Đang dẫn đường tới {dest_name} (còn khoảng {self._distance_remaining:.1f} m)..."

    def _on_nav_result(self, future, req_id: str, dest_name: str):
        """Callback khi Goal kết thúc (Thành công, Thất bại hoặc Đã hủy/Tạm dừng)."""
        with self._lock:
            if req_id != self._active_request_id:
                logger.warning(f"Bỏ qua kết quả của goal cũ {req_id}")
                return

            try:
                result_handle = future.result()
                status = result_handle.status
                result_obj = result_handle.result
            except Exception as e:
                logger.error(f"Lỗi khi đọc kết quả goal: {e}")
                self._navigation_state = "FAILED"
                self._has_goal = False
                self._current_goal_handle = None
                self._message = f"Lỗi khi đọc kết quả từ Nav2: {e}"
                return

            trip_id = getattr(self, "_trip_id", "")
            # action_msgs/msg/GoalStatus: 4=STATUS_SUCCEEDED, 5=STATUS_CANCELED, 6=STATUS_ABORTED
            if status == 4:  # STATUS_SUCCEEDED
                self._navigation_state = "SUCCEEDED"
                self._message = f"Đã dẫn đường đến '{dest_name}' thành công!"
                logger.info(f"Trip {trip_id} (Goal {req_id}) SUCCEEDED!")
                event_logger.add_event("SUCCESS", "NAVIGATION", f"Robot đã đến điểm đích thành công: {dest_name}")
                self._has_goal = False
                self._current_goal_handle = None
                self._current_target_pose = None
                self._distance_remaining = None
                self._estimated_time_remaining = None
                self._number_of_recoveries = 0
                self._path = None
                self._path_version = getattr(self, "_path_version", 0) + 1
                self._owner_id = ""
                self._trip_id = ""
                self._destination_id = ""
                self._pause_requested_for = None
                self._cancel_requested_for = None
            elif status == 5:  # STATUS_CANCELED
                if self._navigation_state == "PAUSING":
                    # Tạm dừng thành công! Chuyển sang trạng thái PAUSED
                    self._navigation_state = "PAUSED"
                    self._message = f"Chuyến dẫn đường tới '{dest_name}' đã tạm dừng. Sẵn sàng tiếp tục khi có lệnh."
                    logger.info(f"Trip {trip_id} (Goal {req_id}) PAUSED successfully!")
                    event_logger.add_event("WARN", "NAVIGATION", f"Chuyến dẫn đường tới '{dest_name}' đã tạm dừng an toàn")
                    self._has_goal = False
                    self._current_goal_handle = None
                    # Giữ nguyên self._owner_id, self._trip_id, self._destination_id, self._current_target_pose cho Resume
                    self._distance_remaining = None
                    self._estimated_time_remaining = None
                    self._path = None
                    self._path_version = getattr(self, "_path_version", 0) + 1
                    self._pause_requested_for = None
                else:
                    self._navigation_state = "CANCELED"
                    self._message = f"Chuyến dẫn đường tới '{dest_name}' đã được hủy."
                    logger.info(f"Trip {trip_id} (Goal {req_id}) CANCELED!")
                    event_logger.add_event("WARN", "NAVIGATION", f"Chuyến dẫn đường tới '{dest_name}' đã bị hủy")
                    self._has_goal = False
                    self._current_goal_handle = None
                    self._current_target_pose = None
                    self._distance_remaining = None
                    self._estimated_time_remaining = None
                    self._number_of_recoveries = 0
                    self._path = None
                    self._path_version = getattr(self, "_path_version", 0) + 1
                    self._owner_id = ""
                    self._trip_id = ""
                    self._destination_id = ""
                    self._pause_requested_for = None
                    self._cancel_requested_for = None
            else:  # STATUS_ABORTED hoặc lỗi khác
                self._navigation_state = "FAILED"
                err_msg = getattr(result_obj, "error_msg", "")
                err_code = getattr(result_obj, "error_code", 0)
                self._message = f"Dẫn đường thất bại (mã {err_code}): {err_msg or 'Nav2 không thể đến đích'}."
                logger.warning(f"Trip {trip_id} (Goal {req_id}) FAILED with status {status}, code {err_code}: {err_msg}")
                event_logger.add_event("ERROR", "NAVIGATION", f"Chuyến dẫn đường tới '{dest_name}' thất bại")
                self._has_goal = False
                self._current_goal_handle = None
                self._current_target_pose = None
                self._distance_remaining = None
                self._estimated_time_remaining = None
                self._number_of_recoveries = 0
                self._path = None
                self._path_version = getattr(self, "_path_version", 0) + 1
                self._owner_id = ""
                self._trip_id = ""
                self._destination_id = ""
                self._pause_requested_for = None
                self._cancel_requested_for = None

    def pause_navigation(self) -> Dict[str, Any]:
        """Tạm dừng chuyến dẫn đường hiện tại (Admin only)."""
        with self._lock:
            # 1. Tránh lặp lệnh nếu đang trong quá trình dừng
            if self._navigation_state == "PAUSING":
                return {
                    "success": True,
                    "message": "Yêu cầu tạm dừng chuyến đi đã được tiếp nhận, đang dừng robot..."
                }

            if self._navigation_state == "PAUSED":
                return {
                    "success": True,
                    "message": "Chuyến dẫn đường hiện đã ở trạng thái tạm dừng."
                }

            # 2. Kiểm tra trạng thái có thể tạm dừng
            if self._navigation_state not in ("PENDING", "ACCEPTED", "NAVIGATING"):
                return {
                    "success": False,
                    "message": f"Không có chuyến dẫn đường nào đang hoạt động để tạm dừng (trạng thái: {self._navigation_state})."
                }

            # 3. Nếu đang ở trạng thái PENDING (chưa có goal handle)
            if self._navigation_state == "PENDING" and not self._current_goal_handle:
                self._pause_requested_for = self._active_request_id
                self._navigation_state = "PAUSING"
                self._path = None
                self._path_version = getattr(self, "_path_version", 0) + 1
                self._message = "Đang gửi yêu cầu tạm dừng mục tiêu tới Nav2..."
                return {
                    "success": True,
                    "message": "Đã tiếp nhận yêu cầu tạm dừng. Hệ thống sẽ tạm dừng ngay khi kết nối."
                }

            # 4. Đã có goal handle: gửi cancel_goal_async để dừng robot
            if self._current_goal_handle:
                self._navigation_state = "PAUSING"
                self._path = None
                self._path_version = getattr(self, "_path_version", 0) + 1
                self._message = "Đang dừng robot và tạm dừng chuyến đi..."
                req_id = self._active_request_id
                try:
                    cancel_future = self._current_goal_handle.cancel_goal_async()
                    cancel_future.add_done_callback(lambda f: self._on_cancel_response(f, req_id))
                except Exception as e:
                    logger.error(f"Lỗi gọi cancel_goal_async khi tạm dừng: {e}")
                    return {"success": False, "message": f"Không thể gửi lệnh tạm dừng tới Nav2: {e}"}

                return {
                    "success": True,
                    "message": "Yêu cầu tạm dừng chuyến đi đã được tiếp nhận, đang dừng robot..."
                }

            return {"success": False, "message": "Không tìm thấy goal handle hợp lệ để tạm dừng."}

    def resume_navigation(self) -> Dict[str, Any]:
        """Tiếp tục chuyến dẫn đường sau khi tạm dừng (Admin only)."""
        with self._lock:
            # 1. Kiểm tra trạng thái hiện tại
            # 1. Kiểm tra action client và ROS packages
            if not getattr(self, "_action_nav", None) or not HAS_NAV2_ACTION:
                return {"success": False, "message": "Action client Nav2 chưa được khởi tạo."}

            # 1b. Kiểm tra chế độ điều khiển
            if getattr(self, "_control_mode", "AUTO") == "MANUAL" or getattr(self, "_active_hold_id", None) is not None:
                return {"success": False, "message": "Không thể tiếp tục dẫn đường: Robot đang trong chế độ điều khiển thủ công (MANUAL) hoặc lượt điều khiển tay."}

            # 1c. Kiểm tra trạng thái hiện tại
            if self._navigation_state in ("NAVIGATING", "ACCEPTED", "PENDING"):
                return {
                    "success": False,
                    "message": "Robot đang trong quá trình dẫn đường, không cần tiếp tục."
                }
            if self._navigation_state == "PAUSING":
                return {
                    "success": False,
                    "message": "Robot đang trong quá trình dừng tạm thời. Vui lòng chờ tạm dừng hoàn tất trước khi tiếp tục."
                }
            if self._navigation_state != "PAUSED":
                return {
                    "success": False,
                    "message": f"Không có chuyến dẫn đường nào đang tạm dừng để tiếp tục (trạng thái: {self._navigation_state})."
                }

            # 2. Kiểm tra sim clock nếu use_sim_time
            if self._cfg.use_sim_time and getattr(self, "_clock_stalled", False):
                return {"success": False, "message": "Mô phỏng đang tạm dừng (sim clock stalled). Không thể tiếp tục."}

            if self._cfg.use_sim_time and (
                getattr(self, "_sim_restarted", False)
                or getattr(self, "_pose_received_epoch", 0) != getattr(self, "_pose_epoch", 0)
            ):
                return {
                    "success": False,
                    "message": "Mô phỏng vừa khởi động lại. Đang chờ dữ liệu vị trí robot mới từ AMCL."
                }

            # 3. Kiểm tra vị trí robot hiện tại từ AMCL
            if not self._pose:
                return {"success": False, "message": "Chưa có vị trí robot từ hệ thống định vị (AMCL). Không thể tiếp tục."}

            # 4. Tìm điểm đến đã lưu trong chuyến đi
            dest = next((d for d in self._destinations if d.get("id") == self._destination_id), None)
            if not dest:
                return {"success": False, "message": f"Không tìm thấy thông tin điểm đến '{self._destination_id}' để tiếp tục."}

            # 5. Kiểm tra server action sẵn sàng
            if not self._action_nav.server_is_ready():
                if not self._action_nav.wait_for_server(timeout_sec=0.5):
                    return {"success": False, "message": "Server action điều hướng /navigate_to_pose chưa sẵn sàng."}

            # 6. Chuẩn bị Goal message Nav2 với cùng tọa độ đích
            goal_msg = NavigateToPose.Goal()
            frame_id = self._cfg.frames.get("map", "map")
            goal_msg.pose.header.frame_id = frame_id
            goal_msg.pose.header.stamp = self._node.get_clock().now().to_msg()

            pos = dest["pose"]["position"]
            orient = dest["pose"].get("orientation", {})
            goal_msg.pose.pose.position.x = float(pos["x"])
            goal_msg.pose.pose.position.y = float(pos["y"])
            goal_msg.pose.pose.position.z = float(pos.get("z", 0.0))
            goal_msg.pose.pose.orientation.x = float(orient.get("x", 0.0))
            goal_msg.pose.pose.orientation.y = float(orient.get("y", 0.0))
            goal_msg.pose.pose.orientation.z = float(orient.get("z", 0.0))
            goal_msg.pose.pose.orientation.w = float(orient.get("w", 1.0))

            # 7. Khởi tạo request id mới cho lượt Nav2 này nhưng GIỮ NGUYÊN trip_id, owner_id, destination_id
            req_id = uuid.uuid4().hex
            self._active_request_id = req_id
            self._cancel_requested_for = None
            self._pause_requested_for = None
            self._current_target_pose = {"x": float(pos["x"]), "y": float(pos["y"])}
            self._current_goal_dispatch_time = time.time()
            self._navigation_state = "PENDING"
            self._has_goal = True
            self._path = None
            self._path_version = getattr(self, "_path_version", 0) + 1
            dest_name = dest.get("name", self._destination_id)
            self._message = f"Đang gửi yêu cầu tiếp tục dẫn đường tới: {dest_name}..."
            self._distance_remaining = None
            self._estimated_time_remaining = None
            self._number_of_recoveries = 0

            # 8. Gửi bất đồng bộ với callback is_resume=True
            try:
                send_future = self._action_nav.send_goal_async(
                    goal_msg,
                    feedback_callback=self._on_nav_feedback
                )
                send_future.add_done_callback(lambda f: self._on_goal_response(f, req_id, dest_name, is_resume=True))
            except Exception as e:
                logger.error(f"Lỗi khi gọi send_goal_async để tiếp tục: {e}")
                self._navigation_state = "PAUSED"
                self._has_goal = False
                self._message = f"Lỗi khi gửi mục tiêu tới Nav2: {e}. Vẫn giữ trạng thái tạm dừng."
                return {"success": False, "message": self._message}

            return {
                "success": True,
                "request_id": req_id,
                "trip_id": getattr(self, "_trip_id", ""),
                "destination_id": self._destination_id,
                "message": f"Đã tiếp nhận yêu cầu tiếp tục dẫn đường tới {dest_name}. Đang chờ Nav2 chấp thuận..."
            }

    def cancel_navigation(self, owner_id: str, is_admin: bool = False) -> Dict[str, Any]:
        with self._lock:
            # 1. Kiểm tra quyền sở hữu chuyến đi (Viewer chỉ điều khiển chuyến của mình, Admin quản lý tất cả)
            if not is_admin and self._owner_id and owner_id != self._owner_id:
                return {
                    "success": False,
                    "message": "Bạn không có quyền hủy chuyến dẫn đường của người dùng khác."
                }

            # 2. Tránh gửi lặp lệnh hủy nếu đang hủy
            if self._navigation_state == "CANCELING":
                return {
                    "success": True,
                    "message": "Yêu cầu hủy chuyến đã được tiếp nhận trước đó, đang chờ Nav2 dừng robot..."
                }

            # 3. Nếu đang ở trạng thái PAUSED: Hủy dứt điểm ngay lập tức mà không cần gửi lệnh hủy tới Nav2
            if self._navigation_state == "PAUSED":
                dest = next((d for d in self._destinations if d.get("id") == self._destination_id), None)
                dest_name = dest.get("name", "") if dest else self._destination_id
                self._navigation_state = "CANCELED"
                self._message = f"Chuyến dẫn đường tới '{dest_name}' đã được hủy."
                self._has_goal = False
                self._current_goal_handle = None
                self._current_target_pose = None
                self._distance_remaining = None
                self._estimated_time_remaining = None
                self._number_of_recoveries = 0
                self._path = None
                self._path_version = getattr(self, "_path_version", 0) + 1
                self._destination_id = ""
                self._owner_id = ""
                self._trip_id = ""
                self._pause_requested_for = None
                self._cancel_requested_for = None
                return {
                    "success": True,
                    "message": f"Chuyến dẫn đường tới '{dest_name}' đã được hủy thành công."
                }

            # 4. Nếu đang ở trạng thái PAUSING: chuyển cờ sang CANCELING để khi Nav2 hủy xong sẽ kết thúc là CANCELED
            if self._navigation_state == "PAUSING":
                self._navigation_state = "CANCELING"
                self._message = "Đang dừng robot và hủy chuyến..."
                return {
                    "success": True,
                    "message": "Yêu cầu hủy chuyến đã được tiếp nhận, đang dừng robot..."
                }

            # 5. Kiểm tra trạng thái hiện tại
            if self._navigation_state not in ("PENDING", "ACCEPTED", "NAVIGATING"):
                return {
                    "success": False,
                    "message": f"Không có chuyến dẫn đường nào đang chạy để hủy (trạng thái: {self._navigation_state})."
                }

            # 6. Nếu đang ở trạng thái PENDING (chưa có goal handle từ Nav2)
            if self._navigation_state == "PENDING" and not self._current_goal_handle:
                self._cancel_requested_for = self._active_request_id
                self._navigation_state = "CANCELING"
                self._current_target_pose = None
                self._path = None
                self._path_version = getattr(self, "_path_version", 0) + 1
                self._message = "Đang gửi yêu cầu hủy mục tiêu tới Nav2..."
                return {
                    "success": True,
                    "message": "Đã tiếp nhận yêu cầu hủy. Hệ thống sẽ hủy mục tiêu ngay khi kết nối."
                }

            # 7. Đã có goal handle: gửi cancel_goal_async
            if self._current_goal_handle:
                self._navigation_state = "CANCELING"
                self._current_target_pose = None
                self._path = None
                self._path_version = getattr(self, "_path_version", 0) + 1
                self._message = "Đang dừng robot và hủy chuyến..."
                req_id = self._active_request_id
                try:
                    cancel_future = self._current_goal_handle.cancel_goal_async()
                    cancel_future.add_done_callback(lambda f: self._on_cancel_response(f, req_id))
                except Exception as e:
                    logger.error(f"Lỗi gọi cancel_goal_async: {e}")
                    return {"success": False, "message": f"Không thể gửi lệnh hủy: {e}"}

                return {
                    "success": True,
                    "message": "Yêu cầu hủy chuyến đã được tiếp nhận, đang dừng robot..."
                }

            return {"success": False, "message": "Không tìm thấy goal handle hợp lệ để hủy."}

    def _on_action_status(self, msg: GoalStatusArray):
        """Theo dõi các goal đang chạy trên Nav2 server để phát hiện mục tiêu từ bên ngoài."""
        with self._lock:
            self._nav2_action_status_received = True
            active = [
                s for s in msg.status_list
                if s.status in (GoalStatus.STATUS_ACCEPTED, GoalStatus.STATUS_EXECUTING, GoalStatus.STATUS_CANCELING)
            ]
            self._nav2_has_active_goal = len(active) > 0

    def _on_cancel_response(self, future, req_id: str):
        """Callback khi Nav2 phản hồi yêu cầu cancel."""
        with self._lock:
            if req_id != self._active_request_id:
                return
            # Nếu mục tiêu đã hoàn thành trước đó (ví dụ result về trước callback Hủy), giữ nguyên kết quả cuối
            if self._navigation_state in ("SUCCEEDED", "FAILED", "IDLE"):
                return
            try:
                cancel_response = future.result()
                return_code = getattr(cancel_response, "return_code", 0)
                if return_code != 0:
                    logger.warning(f"Nav2 không thể hủy goal {req_id} (code={return_code}). Chờ kết quả cuối.")
                    # Nếu bị từ chối hủy (return_code == 1):
                    # Nếu đang CANCELING -> chuyển lại NAVIGATING
                    # Nếu đang PAUSING -> chuyển lại NAVIGATING
                    if return_code == 1:
                        dests = getattr(self, "_destinations", []) or []
                        dest = next((d for d in dests if d.get("id") == self._destination_id), None)
                        dest_name = dest.get("name", "") if dest else self._destination_id
                        if self._navigation_state == "CANCELING":
                            self._navigation_state = "NAVIGATING"
                            self._message = f"Yêu cầu hủy bị Nav2 từ chối. Robot tiếp tục dẫn đường tới {dest_name}."
                        elif self._navigation_state == "PAUSING":
                            self._navigation_state = "NAVIGATING"
                            self._message = f"Yêu cầu tạm dừng bị Nav2 từ chối. Robot tiếp tục dẫn đường tới {dest_name}."
            except Exception as e:
                logger.error(f"Lỗi trong _on_cancel_response: {e}")

    def is_voice_available(self) -> bool:
        """Kiểm tra xem ROS Service /airport/voice/start đã sẵn sàng hay chưa"""
        if not hasattr(self, "_cli_voice_start") or self._cli_voice_start is None:
            return False
        try:
            return bool(self._cli_voice_start.service_is_ready())
        except Exception:
            return False

    def get_voice_proposal(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            if not getattr(self, "_voice_proposal", None):
                return None
            now_ms = int(time.time() * 1000)
            if now_ms > self._voice_proposal.get("expires_at", 0):
                self._voice_proposal = None
                return None
            return dict(self._voice_proposal)

    def clear_voice_proposal(self) -> None:
        with self._lock:
            self._voice_proposal = None
            self._voice_transcript = None
            self._voice_response = None
            self._voice_requester_id = ""

    def start_voice_session(self, requester_id: str = "") -> Dict[str, Any]:
        """
        Kích hoạt microphone trên phần cứng robot thông qua ROS Service Trigger /airport/voice/start.
        Có in-flight debounce, non-blocking check, timeout an toàn và liên kết phiên hành khách.
        """
        with self._lock:
            if getattr(self, "_voice_start_in_progress", False):
                return {
                    "success": False,
                    "message": "Yêu cầu kích hoạt microphone đang được xử lý, vui lòng chờ."
                }

            if not hasattr(self, "_cli_voice_start") or not self._cli_voice_start:
                return {
                    "success": False,
                    "message": "Service trigger giọng nói chưa được cấu hình."
                }

            if not self._cli_voice_start.service_is_ready():
                return {
                    "success": False,
                    "message": "ROS Service /airport/voice/start chưa sẵn sàng (node giọng nói chưa khởi chạy)."
                }

            self._voice_start_in_progress = True
            self._voice_requester_id = requester_id
            self._voice_session_id = str(uuid.uuid4())
            self._voice_proposal = None

        timeout_sec = 3.0
        voice_srv_cfg = self._cfg.get_service("voice_start")
        if voice_srv_cfg and hasattr(voice_srv_cfg, "timeout_sec") and voice_srv_cfg.timeout_sec:
            try:
                timeout_sec = float(voice_srv_cfg.timeout_sec)
            except (ValueError, TypeError):
                timeout_sec = 3.0

        req = Trigger.Request()
        event = threading.Event()
        res_container: Dict[str, Any] = {}

        def _on_done(fut):
            try:
                res_container["resp"] = fut.result()
            except Exception as ex:
                res_container["error"] = ex
            finally:
                event.set()

        try:
            future = self._cli_voice_start.call_async(req)
            future.add_done_callback(_on_done)
            finished = event.wait(timeout=timeout_sec)
            if not finished:
                logger.warning(f"Timeout ({timeout_sec}s) khi chờ phản hồi từ /airport/voice/start")
                return {
                    "success": False,
                    "message": f"Hết thời gian chờ phản hồi từ ROS Service /airport/voice/start (timeout {timeout_sec}s)."
                }
            if "error" in res_container:
                logger.error(f"Lỗi khi gọi ROS Service /airport/voice/start: {res_container['error']}")
                return {
                    "success": False,
                    "message": f"Lỗi khi gọi service giọng nói ROS: {res_container['error']}"
                }
            resp = res_container.get("resp")
            if resp is None or not getattr(resp, "success", False):
                err_msg = getattr(resp, "message", "") or "ROS từ chối kích hoạt microphone."
                return {"success": False, "message": err_msg}

            return {
                "success": True,
                "message": getattr(resp, "message", "") or "Đã kích hoạt microphone trên robot thành công."
            }
        except Exception as e:
            logger.error(f"Lỗi không xác định khi gọi /airport/voice/start: {e}")
            return {"success": False, "message": f"Không thể gửi yêu cầu tới ROS: {e}"}
        finally:
            with self._lock:
                self._voice_start_in_progress = False

    def is_manual_consumer_available(self) -> bool:
        if not (hasattr(self, "_pub_cmd_vel") and self._pub_cmd_vel):
            return False
        try:
            count = self._pub_cmd_vel.get_subscription_count()
            if count <= 0:
                return False
            if not hasattr(self, "_node") or not self._node:
                return False
            topic_name = self._pub_cmd_vel.topic_name
            subs = self._node.get_subscriptions_info_by_topic(topic_name)
            if not subs:
                # Graph chưa đủ thông tin hoặc chưa phân giải được subscriber -> khóa an toàn
                return False
            expected_nodes = {"ros_gz_bridge", "command_timeout", "twist_mux", "diffdrive_controller"}
            expected_type = "geometry_msgs/msg/Twist" if getattr(self, "_cmd_vel_is_twist", False) else "geometry_msgs/msg/TwistStamped"
            has_valid_consumer = any(
                getattr(s, "node_name", "") in expected_nodes and
                getattr(s, "topic_type", "") == expected_type
                for s in subs
            )
            return bool(has_valid_consumer)
        except Exception as e:
            logger.warning(f"Lỗi kiểm tra manual consumer: {e}")
            return False

    def _publish_zero_velocity(self) -> None:
        if hasattr(self, "_pub_cmd_vel") and self._pub_cmd_vel:
            try:
                if getattr(self, "_cmd_vel_is_twist", False):
                    msg = Twist()
                    msg.linear.x = 0.0
                    msg.linear.y = 0.0
                    msg.linear.z = 0.0
                    msg.angular.x = 0.0
                    msg.angular.y = 0.0
                    msg.angular.z = 0.0
                    self._pub_cmd_vel.publish(msg)
                else:
                    msg = TwistStamped()
                    msg.header.stamp = self._node.get_clock().now().to_msg()
                    frame = self._cfg.frames.get("base_link", "base_link") if hasattr(self, "_cfg") and hasattr(self._cfg, "frames") else "base_link"
                    msg.header.frame_id = frame
                    msg.twist.linear.x = 0.0
                    msg.twist.angular.z = 0.0
                    self._pub_cmd_vel.publish(msg)
            except Exception as e:
                logger.error(f"Lỗi khi gửi vận tốc zero: {e}")

    def _can_manual_control_locked(self, operator_id: str = "", require_consumer: bool = True) -> Tuple[bool, Optional[str]]:
        # 1. Kiểm tra vị trí và clock
        if not self._has_valid_pose_locked():
            return (False, "Không thể lái tay: Chưa có vị trí định vị AMCL hợp lệ hoặc mô phỏng vừa reset.")
        if self._cfg.use_sim_time and getattr(self, "_clock_stalled", False):
            return (False, "Không thể lái tay: Mô phỏng đang tạm dừng (sim clock stalled).")

        # 2. Kiểm tra chuyến dẫn đường đang hoạt động hoặc tạm dừng
        nav_state = getattr(self, "_navigation_state", "IDLE")
        if nav_state in ("PENDING", "ACCEPTED", "NAVIGATING", "PAUSING", "PAUSED", "CANCELING") or getattr(self, "_has_goal", False):
            return (False, f"Không thể lái tay: Đang có chuyến dẫn đường ({nav_state}).")

        # 3. Kiểm tra mục tiêu ngoại vi từ Nav2 (RViz...)
        if getattr(self, "_nav2_has_active_goal", False):
            return (False, "Không thể chuyển sang MANUAL: Nav2 đang có mục tiêu điều hướng đang chạy từ nguồn ngoài.")

        # 4. Kiểm tra phiên Admin đang giữ quyền
        current_op = getattr(self, "_manual_operator_id", None)
        if getattr(self, "_control_mode", "AUTO") == "MANUAL" and current_op and operator_id and current_op != operator_id:
            op_desc = f" ({current_op})" if current_op and not str(current_op).startswith("sess_") else ""
            return (False, f"Quyền điều khiển thủ công đang thuộc về Admin khác{op_desc}.")

        # 5. Kiểm tra đường điều khiển đã được xác minh (consumer có sẵn) khi cần phát lệnh vận tốc
        if require_consumer and not self.is_manual_consumer_available():
            topic_name = self._pub_cmd_vel.topic_name if (hasattr(self, "_pub_cmd_vel") and self._pub_cmd_vel) else "/cmd_vel"
            return (False, f"Đường lệnh điều khiển tay ROS ({topic_name}) chưa có consumer tiếp nhận.")

        return (True, None)

    def can_manual_control(self, operator_id: str = "") -> Tuple[bool, Optional[str]]:
        with self._lock:
            return self._can_manual_control_locked(operator_id, require_consumer=True)

    def check_manual_timeout(self) -> None:
        with self._lock:
            if getattr(self, "_control_mode", "AUTO") != "MANUAL":
                return
            timeout_sec = 0.5
            if hasattr(self, "_cfg") and hasattr(self._cfg, "velocity_limits"):
                timeout_sec = self._cfg.velocity_limits.get("cmd_timeout_sec", 0.5)
            now = time.monotonic()
            last_time = getattr(self, "_last_manual_cmd_time", 0.0)
            if (now - last_time) >= timeout_sec:
                op_id = getattr(self, "_manual_operator_id", None) or "Admin"
                logger.warning(
                    f"Watchdog timeout ({timeout_sec}s): Không nhận được lệnh điều khiển tay từ {op_id}. Dừng robot an toàn."
                )
                if getattr(self, "_active_hold_id", None):
                    self._released_hold_ids[self._active_hold_id] = now
                    while len(self._released_hold_ids) > 500:
                        self._released_hold_ids.popitem(last=False)
                    self._active_hold_id = None
                self._publish_zero_velocity()
                self._control_mode = "AUTO"
                self._manual_operator_id = None
                self._last_manual_seq = 0
                self._current_manual_twist = (0.0, 0.0)
                self._message = "Chế độ tự động (AUTO) sẵn sàng."

    def set_manual_control(self, enable: bool, operator_id: str = "", force: bool = False) -> Dict[str, Any]:
        with self._lock:
            if enable:
                can_drive, reason = self._can_manual_control_locked(operator_id, require_consumer=False)
                if not can_drive and not force:
                    return {"success": False, "message": f"Không thể chuyển sang MANUAL: {reason}"}

                current_op = getattr(self, "_manual_operator_id", None)
                if getattr(self, "_control_mode", "AUTO") == "MANUAL" and current_op and operator_id and current_op != operator_id and not force:
                    op_desc = f" ({current_op})" if current_op and not str(current_op).startswith("sess_") else ""
                    return {
                        "success": False,
                        "message": f"Quyền điều khiển thủ công đang thuộc về Admin khác{op_desc}."
                    }

                self._control_mode = "MANUAL"
                self._manual_operator_id = operator_id
                self._last_manual_cmd_time = time.monotonic()
                self._current_manual_twist = (0.0, 0.0)
                self._active_hold_id = None
                self._last_manual_seq = 0
                self._message = f"Chế độ điều khiển thủ công (MANUAL) được kích hoạt bởi {operator_id or 'Admin'}."

                if hasattr(self, "_cli_set_manual") and self._cli_set_manual:
                    try:
                        if self._cli_set_manual.service_is_ready():
                            req = SetBool.Request()
                            req.data = True
                            self._cli_set_manual.call_async(req)
                    except Exception as e:
                        logger.warning(f"Không thể gọi service /airport/control/set_manual: {e}")

                event_logger.track_control_mode("MANUAL")
                return {"success": True, "message": "Đã chuyển sang chế độ điều khiển thủ công (MANUAL)."}
            else:
                if getattr(self, "_active_hold_id", None):
                    self._released_hold_ids[self._active_hold_id] = time.monotonic()
                    while len(self._released_hold_ids) > 500:
                        self._released_hold_ids.popitem(last=False)
                    self._active_hold_id = None
                self._control_mode = "AUTO"
                self._manual_operator_id = None
                self._active_hold_id = None
                self._last_manual_seq = 0
                self._publish_zero_velocity()
                self._current_manual_twist = (0.0, 0.0)
                self._last_manual_cmd_time = 0.0
                self._message = "Chế độ tự động (AUTO) sẵn sàng."

                if hasattr(self, "_cli_set_manual") and self._cli_set_manual:
                    try:
                        if self._cli_set_manual.service_is_ready():
                            req = SetBool.Request()
                            req.data = False
                            self._cli_set_manual.call_async(req)
                    except Exception as e:
                        logger.warning(f"Không thể gọi service /airport/control/set_manual: {e}")

                event_logger.track_control_mode("AUTO")
                return {"success": True, "message": "Đã chuyển về chế độ tự động (AUTO)."}

    def send_manual_velocity(
        self,
        linear_x: float,
        angular_z: float,
        operator_id: str = "",
        seq: int = 0,
        hold_id: str = ""
    ) -> Dict[str, Any]:
        with self._lock:
            if not hasattr(self, "_released_hold_ids"):
                self._released_hold_ids = collections.OrderedDict()

            now = time.monotonic()

            # Dọn dẹp cache hold đã giải phóng (> 60s và giữ tối đa 500 phần tử)
            stale_keys = [k for k, t in self._released_hold_ids.items() if (now - t) > 60.0]
            for k in stale_keys:
                self._released_hold_ids.pop(k, None)
            while len(self._released_hold_ids) > 500:
                self._released_hold_ids.popitem(last=False)

            is_stop_cmd = (abs(linear_x) < 1e-4 and abs(angular_z) < 1e-4)

            # 1. Xử lý Lệnh Dừng (Stop / Emergency Stop)
            if is_stop_cmd:
                if not hold_id:
                    # Lệnh Dừng khẩn cấp (Emergency Stop không gắn hold_id):
                    # Bất kỳ Admin nào gọi cũng dừng xe ngay lập tức, hủy mọi active hold và đưa về AUTO.
                    self._publish_zero_velocity()
                    self._current_manual_twist = (0.0, 0.0)
                    self._last_manual_cmd_time = now
                    if getattr(self, "_active_hold_id", None):
                        self._released_hold_ids[self._active_hold_id] = now
                        self._active_hold_id = None
                    was_manual = (getattr(self, "_control_mode", "AUTO") == "MANUAL")
                    self._control_mode = "AUTO"
                    self._manual_operator_id = None
                    self._message = "Chế độ tự động (AUTO) sẵn sàng."
                    if was_manual:
                        event_logger.track_control_mode("AUTO")
                    return {"success": True, "message": "Đã gửi lệnh dừng khẩn cấp (Emergency Stop) thành công."}

                # Lệnh Dừng giải phóng hold cụ thể (release specific hold)
                self._released_hold_ids[hold_id] = now
                active_id = getattr(self, "_active_hold_id", None)
                if active_id == hold_id:
                    self._active_hold_id = None
                    self._publish_zero_velocity()
                    self._current_manual_twist = (0.0, 0.0)
                    self._last_manual_cmd_time = now
                    if seq > getattr(self, "_last_manual_seq", 0):
                        self._last_manual_seq = seq
                    was_manual = (getattr(self, "_control_mode", "AUTO") == "MANUAL")
                    self._control_mode = "AUTO"
                    self._manual_operator_id = None
                    self._message = "Chế độ tự động (AUTO) sẵn sàng."
                    if was_manual:
                        event_logger.track_control_mode("AUTO")
                    return {"success": True, "message": "Đã giải phóng hold và dừng robot an toàn."}
                else:
                    # Hold cũ hoặc không khớp active hold -> Không dừng hay làm gián đoạn active hold mới
                    return {"success": True, "ignored": True, "message": f"Hold '{hold_id}' không còn là active hold, bỏ qua dừng."}

            # 2. Xử lý Lệnh Chuyển động (Vận tốc khác 0)
            # BẮT BUỘC có hold_id và seq >= 1 (Loại bỏ hoàn toàn single-shot/legacy branch cho lệnh chuyển động)
            if not hold_id or seq is None or seq < 1:
                return {
                    "success": False,
                    "message": "Yêu cầu hold_id và seq (seq >= 1) hợp lệ cho lệnh vận tốc di chuyển."
                }

            # Kiểm tra hold đã giải phóng
            if hold_id in self._released_hold_ids:
                return {
                    "success": True,
                    "ignored": True,
                    "message": "Bỏ qua lệnh vận tốc của lượt bấm đã kết thúc."
                }

            # Kiểm tra thứ tự và thời gian tạo hold (Tránh hold cũ đến muộn chiếm quyền hold mới)
            hold_timestamp_ms = None
            if hold_id.startswith("hold_"):
                parts = hold_id.split("_")
                if len(parts) >= 2 and parts[1].isdigit():
                    hold_timestamp_ms = int(parts[1])

            if getattr(self, "_active_hold_id", None) == hold_id:
                last_seq = getattr(self, "_last_manual_seq", 0)
                if seq <= last_seq:
                    return {
                        "success": True,
                        "ignored": True,
                        "message": f"Bỏ qua lệnh vận tốc đến trễ hoặc lặp seq (seq {seq} <= {last_seq})."
                    }
                self._last_manual_seq = seq
            else:
                # Hold mới được khởi tạo
                if hold_timestamp_ms is not None:
                    last_hold_ts = getattr(self, "_last_hold_timestamp_ms", 0)
                    if hold_timestamp_ms < last_hold_ts:
                        logger.warning(
                            f"Bỏ qua hold cũ đến trễ: {hold_id} (ts: {hold_timestamp_ms} < {last_hold_ts})"
                        )
                        return {
                            "success": True,
                            "ignored": True,
                            "message": "Bỏ qua hold cũ đến trễ hơn hold đã xử lý."
                        }
                    self._last_hold_timestamp_ms = hold_timestamp_ms

                # Nếu đang có hold hoạt động khác:
                if getattr(self, "_active_hold_id", None) is not None:
                    current_op = getattr(self, "_manual_operator_id", None)
                    if current_op and operator_id and current_op != operator_id:
                        op_desc = f" ({current_op})" if current_op and not str(current_op).startswith("sess_") else ""
                        return {
                            "success": False,
                            "message": f"Quyền điều khiển đang thuộc về phiên khác{op_desc}."
                        }
                    # Đưa hold cũ vào cache giải phóng
                    self._released_hold_ids[self._active_hold_id] = now

                self._active_hold_id = hold_id
                self._last_manual_seq = seq

            # 3. Kiểm tra điều kiện lái tay toàn diện và quyền Admin
            can_drive, reason = self._can_manual_control_locked(operator_id)
            if not can_drive:
                return {"success": False, "message": reason or "Không đủ điều kiện điều khiển tay."}

            # 4. Kiểm tra dữ liệu đầu vào hữu hạn
            if not (math.isfinite(linear_x) and math.isfinite(angular_z)):
                return {"success": False, "message": "Giá trị vận tốc không hợp lệ (NaN hoặc Inf)."}

            # 5. Kích hoạt MANUAL (không ghi log AUTO/MANUAL cho mỗi nhịp giữ nút tạm thời)
            self._control_mode = "MANUAL"
            self._manual_operator_id = operator_id
            self._message = f"Chế độ điều khiển thủ công (MANUAL) được kích hoạt bởi {operator_id or 'Admin'}."

            # 6. Giới hạn vận tốc và publish
            if not hasattr(self, "_pub_cmd_vel") or not self._pub_cmd_vel:
                return {"success": False, "message": "Topic vận tốc chưa được khởi tạo."}

            limits = self._cfg.velocity_limits if hasattr(self, "_cfg") and hasattr(self._cfg, "velocity_limits") else {}
            lin_max = limits.get("linear_max", 0.3)
            ang_max = limits.get("angular_max", 0.5)

            clamped_x = max(-lin_max, min(lin_max, float(linear_x)))
            clamped_z = max(-ang_max, min(ang_max, float(angular_z)))

            try:
                if getattr(self, "_cmd_vel_is_twist", False):
                    msg = Twist()
                    msg.linear.x = float(clamped_x)
                    msg.linear.y = 0.0
                    msg.linear.z = 0.0
                    msg.angular.x = 0.0
                    msg.angular.y = 0.0
                    msg.angular.z = float(clamped_z)
                    self._pub_cmd_vel.publish(msg)
                else:
                    msg = TwistStamped()
                    msg.header.stamp = self._node.get_clock().now().to_msg()
                    frame = self._cfg.frames.get("base_link", "base_link") if hasattr(self, "_cfg") and hasattr(self._cfg, "frames") else "base_link"
                    msg.header.frame_id = frame
                    msg.twist.linear.x = float(clamped_x)
                    msg.twist.angular.z = float(clamped_z)
                    self._pub_cmd_vel.publish(msg)
            except Exception as e:
                logger.error(f"Lỗi publish cmd_vel_manual: {e}")
                return {"success": False, "message": f"Lỗi publish lệnh vận tốc: {e}"}

            self._last_manual_cmd_time = time.monotonic()
            self._current_manual_twist = (clamped_x, clamped_z)
            return {"success": True, "message": "Đã gửi lệnh vận tốc thành công."}

    def get_alerts(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._alerts)

    def get_path(self) -> Optional[List[Dict[str, float]]]:
        with self._lock:
            return list(self._path) if self._path else None

    def get_path_version(self) -> int:
        with self._lock:
            return getattr(self, "_path_version", 0)

    def get_owner_id(self) -> str:
        with self._lock:
            return self._owner_id

    def get_map_metadata(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            if not self._map_version or not self._map_png:
                return None
            return {
                "status": "ready",
                "map_version": self._map_version,
                "frame_id": self._map_frame_id,
                "stamp": self._map_stamp,
                "metadata": {
                    "width": self._map_meta.width,
                    "height": self._map_meta.height,
                    "resolution": self._map_meta.resolution,
                    "origin_x": self._map_meta.origin_x,
                    "origin_y": self._map_meta.origin_y,
                    "origin_yaw": self._map_meta.origin_yaw
                },
                "image_url": f"/api/robot/map/image?v={self._map_version}"
            }

    def get_map_image(self, version: str) -> Optional[bytes]:
        with self._lock:
            if not self._map_version or not self._map_png:
                return None
            if version != self._map_version:
                return None
            return self._map_png

    def dispose(self) -> None:
        self._disposed = True
        try:
            if hasattr(self, "_executor") and self._executor:
                self._executor.shutdown()
            if hasattr(self, "_node") and self._node:
                self._node.destroy_node()
            if rclpy.ok():
                rclpy.shutdown()
        except Exception:
            pass
