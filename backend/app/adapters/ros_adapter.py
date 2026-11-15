from __future__ import annotations

import time
import math
import uuid
import io
import os
import threading
import logging
import pathlib
import yaml
from typing import Dict, Any, List, Optional, Tuple

from .base import BaseRobotAdapter
from ..ros_config import get_ros_config
from ..coordinate.transform import MapMetadata, quaternion_to_yaw

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
    from geometry_msgs.msg import PoseStamped, PoseWithCovarianceStamped, TwistStamped
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

        self._lock = threading.Lock()
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
        self._navigation_state = "IDLE"
        self._has_goal = False
        self._goal_id = ""
        self._trip_id = ""
        self._destination_id = ""
        self._voice_state = "IDLE"
        self._voice_transcript: Optional[str] = None
        self._voice_response: Optional[str] = None
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
                String, transcript_cfg.name, lambda m: setattr(self, "_voice_transcript", m.data), 1
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
            self._pub_cmd_vel = self._node.create_publisher(TwistStamped, cmd_cfg.name, qos)
            logger.info(f"Created publisher cmd_vel_manual: {cmd_cfg.name}")
        else:
            self._pub_cmd_vel = None

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
        """
        with self._lock:
            pose = msg.pose.pose
            q = pose.orientation
            theta = quaternion_to_yaw(q.x, q.y, q.z, q.w)
            self._pose = {
                "x": float(pose.position.x),
                "y": float(pose.position.y),
                "theta": float(theta)
            }
            frame_id = msg.header.frame_id
            self._pose_frame_id = frame_id
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

            if frame_id != "map":
                logger.warning(
                    f"Pose nhận được trong frame '{frame_id}' thay vì 'map'. "
                    f"Tọa độ hiển thị có thể không chính xác."
                )

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

            self._last_clock_sec = new_sec
            self._last_clock_monotonic = now_mono
            # Mỗi khi nhận clock message, clock đang tiến → bỏ flag stalled
            self._clock_stalled = False

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

                # Pose hợp lệ: đã nhận ít nhất 1 pose và thuộc đúng epoch hiện tại
                has_valid_pose = (
                    self._pose is not None
                    and not getattr(self, "_sim_restarted", False)
                    and (getattr(self, "_pose_received_epoch", 0) == getattr(self, "_pose_epoch", 0))
                )

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
            }

            # Thông tin bổ sung cho sim profile
            if self._cfg.use_sim_time:
                result["sim_clock_stalled"] = self._clock_stalled
                result["sim_restarted"] = self._sim_restarted and not (
                    self._pose_received_epoch == self._pose_epoch
                )

            return result

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

    def _save_destinations(self) -> Tuple[bool, str]:
        """
        Lưu danh sách điểm đến bền vững ra tệp YAML:
        - Ghi an toàn thông qua tệp tạm (atomic write với os.replace).
        - Nếu có lỗi ghi giữa chừng, tệp gốc không bị mất hoặc hỏng.
        - Xử lý đồng thời được bảo vệ bởi self._lock.
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
                    "destinations": self._destinations
                }, f, allow_unicode=True, sort_keys=False)
                f.flush()
                os.fsync(f.fileno())

            # Hoán đổi nguyên tử (atomic replace)
            os.replace(temp_file, target_file)
            logger.info(f"Đã lưu an toàn {len(self._destinations)} điểm đến vào {target_file}")
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
        """
        with self._lock:
            dest_id = destination.get("id")
            name = destination.get("name")
            if not dest_id or not str(dest_id).strip():
                return {"success": False, "message": "ID điểm đến không được để trống"}
            if not name or not str(name).strip():
                return {"success": False, "message": "Tên điểm đến không được để trống"}

            dest_id = str(dest_id).strip()

            # Kiểm tra xem có đang dẫn đường tới điểm này không (kể cả khi tạm dừng hoặc đang hủy)
            if self._navigation_state in ("PENDING", "ACCEPTED", "NAVIGATING", "PAUSING", "PAUSED", "CANCELING") and self._destination_id == dest_id:
                return {"success": False, "message": f"Không thể cập nhật điểm đến '{dest_id}' khi đang có chuyến dẫn đường tới điểm này (trạng thái: {self._navigation_state})"}

            # Xác thực tọa độ
            val_res = self.validate_destination_coordinates(destination)
            if not val_res.get("valid"):
                return {"success": False, "message": val_res.get("message")}

            # Chuẩn hóa cấu trúc
            clean_dest = {
                "id": dest_id,
                "name": str(name).strip(),
                "map_id": destination.get("map_id", "airport_floor_1"),
                "pose": destination.get("pose", {})
            }

            old_destinations = list(self._destinations)

            found = False
            for idx, d in enumerate(self._destinations):
                if d.get("id") == dest_id:
                    self._destinations[idx] = clean_dest
                    found = True
                    break
            if not found:
                self._destinations.append(clean_dest)

            # Thử lưu ra file bền vững
            saved, save_err = self._save_destinations()
            if not saved:
                # Rollback bộ nhớ
                self._destinations = old_destinations
                return {"success": False, "message": f"Không thể lưu điểm đến: {save_err}"}

            self._destinations_version = getattr(self, "_destinations_version", 0) + 1
            return {"success": True, "message": f"Đã lưu điểm đến '{name}' thành công"}

    def delete_destination(self, destination_id: str) -> Dict[str, Any]:
        """
        Xóa một điểm đến lưu bền vững (Admin).
        - Yêu cầu destination_id hợp lệ.
        - Chặn xóa điểm đang có chuyến dẫn đường chưa kết thúc (PENDING, ACCEPTED, NAVIGATING, CANCELING).
        - Ghi an toàn bằng tệp tạm (atomic write với os.replace).
        - Nếu lưu tệp thất bại, khôi phục lại danh sách cũ trong bộ nhớ và trả thông báo lỗi thực tế.
        - Khi xóa thành công, tăng _destinations_version để đồng bộ tức thì tới tất cả các client.
        - Hỗ trợ xóa toàn bộ điểm đến: khi danh sách rỗng, lưu 'destinations: []' vào tệp dữ liệu lưu trữ
          và giữ nguyên rỗng sau khi recreate backend mà không nạp lại seed file.
        """
        with self._lock:
            dest_id = str(destination_id).strip()
            if not dest_id:
                return {"success": False, "message": "ID điểm đến không được để trống"}

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

            # Sao lưu để rollback nếu ghi thất bại
            old_destinations = list(self._destinations)
            deleted_dest = self._destinations.pop(existing_idx)

            # Lưu bền vững ra tệp YAML
            saved_ok, save_err = self._save_destinations()
            if not saved_ok:
                # Rollback
                self._destinations = old_destinations
                return {"success": False, "message": f"Không thể lưu điểm đến sau khi xóa: {save_err}"}

            self._destinations_version = getattr(self, "_destinations_version", 0) + 1
            deleted_name = deleted_dest.get("name") or dest_id
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
            if self._control_mode == "MANUAL":
                return {"success": False, "message": "Robot đang ở chế độ điều khiển thủ công (MANUAL). Hãy chuyển sang AUTO trước."}

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
            if getattr(self, "_control_mode", "AUTO") == "MANUAL":
                return {"success": False, "message": "Robot đang ở chế độ điều khiển thủ công (MANUAL). Hãy chuyển sang AUTO trước khi tiếp tục."}

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

    def start_voice_session(self) -> Dict[str, Any]:
        if not hasattr(self, "_cli_voice_start") or not self._cli_voice_start:
            return {"success": False, "message": "Service trigger giọng nói chưa được cấu hình."}

        if not self._cli_voice_start.wait_for_service(timeout_sec=2.0):
            return {"success": False, "message": "ROS Service /airport/voice/start không phản hồi."}

        req = Trigger.Request()
        future = self._cli_voice_start.call_async(req)
        return {"success": True, "message": "Đã gửi tín hiệu kích hoạt microphone tới ROS."}

    def set_manual_control(self, enable: bool) -> Dict[str, Any]:
        if not hasattr(self, "_cli_set_manual") or not self._cli_set_manual:
            return {"success": False, "message": "Service chuyển chế độ thủ công chưa được cấu hình."}

        if not self._cli_set_manual.wait_for_service(timeout_sec=2.0):
            return {"success": False, "message": "ROS Service /airport/control/set_manual không phản hồi."}

        req = SetBool.Request()
        req.data = enable
        self._cli_set_manual.call_async(req)
        return {"success": True, "message": f"Đã gửi yêu cầu chuyển sang chế độ {'MANUAL' if enable else 'AUTO'}."}

    def send_manual_velocity(self, linear_x: float, angular_z: float) -> bool:
        if not self._pub_cmd_vel:
            return False

        limits = self._cfg.velocity_limits
        lin_max = limits.get("linear_max", 0.3)
        ang_max = limits.get("angular_max", 0.5)

        linear_x = max(-lin_max, min(lin_max, linear_x))
        angular_z = max(-ang_max, min(ang_max, angular_z))

        msg = TwistStamped()
        msg.header.stamp = self._node.get_clock().now().to_msg()
        msg.header.frame_id = self._cfg.frames.get("base_link", "base_link")
        msg.twist.linear.x = float(linear_x)
        msg.twist.angular.z = float(angular_z)
        self._pub_cmd_vel.publish(msg)
        return True

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
