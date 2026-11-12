import time
import math
import threading
import logging
from typing import Dict, Any, List, Optional

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
    from geometry_msgs.msg import PoseStamped, TwistStamped
    from sensor_msgs.msg import BatteryState
    from nav_msgs.msg import OccupancyGrid, Path
    from std_msgs.msg import String
    from std_srvs.srv import Trigger, SetBool
    from diagnostic_msgs.msg import DiagnosticArray
    HAS_RCLPY = True
except ImportError:
    HAS_RCLPY = False

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
    HAS_NAV2_ACTION = True
except ImportError:
    HAS_NAV2_ACTION = False


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
        self._destination_id = ""
        self._voice_state = "IDLE"
        self._voice_transcript: Optional[str] = None
        self._voice_response: Optional[str] = None
        self._message = "Đang kết nối tới các topic ROS..."

        self._destinations: List[Dict[str, Any]] = []
        self._alerts: List[Dict[str, Any]] = []
        self._path: Optional[List[Dict[str, float]]] = None
        self._current_goal_handle = None

        # Khởi tạo Node ROS 2 với tên từ cấu hình
        if not rclpy.ok():
            rclpy.init()

        node_name = self._cfg.merged_config.get("nodes", {}).get("web_gateway", "airport_web_gateway").lstrip("/")
        self._node = rclpy.create_node(node_name)

        if self._cfg.use_sim_time:
            self._node.set_parameters([rclpy.parameter.Parameter('use_sim_time', rclpy.Parameter.Type.BOOL, True)])
            logger.info("Đã bật use_sim_time=True theo profile cấu hình.")

        self._setup_subscribers_and_clients()

        # Thread spin ROS
        self._executor = rclpy.executors.SingleThreadedExecutor()
        self._executor.add_node(self._node)
        self._spin_thread = threading.Thread(target=self._executor.spin, daemon=True)
        self._spin_thread.start()

        logger.info(f"RosRobotAdapter đã khởi tạo hoàn tất với node [{node_name}]")

    def _setup_subscribers_and_clients(self):
        # 1. Pose Topic
        pose_cfg = self._cfg.get_topic("robot_pose")
        if pose_cfg and pose_cfg.enabled:
            qos = _build_qos(pose_cfg.qos)
            self._sub_pose = self._node.create_subscription(
                PoseStamped, pose_cfg.name, self._on_pose, qos
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
                Path, path_cfg.name, self._on_path, qos
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

        # 12. Nav2 Action Client
        nav_action_cfg = self._cfg.get_action("navigate")
        if nav_action_cfg and nav_action_cfg.enabled and HAS_NAV2_ACTION:
            self._action_nav = ActionClient(self._node, NavigateToPose, nav_action_cfg.name)
            logger.info(f"Created Nav2 action client: {nav_action_cfg.name}")
        else:
            self._action_nav = None

    def _on_pose(self, msg: PoseStamped):
        with self._lock:
            q = msg.pose.orientation
            theta = quaternion_to_yaw(q.x, q.y, q.z, q.w)
            self._pose = {
                "x": float(msg.pose.position.x),
                "y": float(msg.pose.position.y),
                "theta": float(theta)
            }
            self._last_pose_time = time.time()
            self._is_connected = True

    def _on_map(self, msg: OccupancyGrid):
        with self._lock:
            self._map_meta = MapMetadata(
                resolution=msg.info.resolution,
                width=msg.info.width,
                height=msg.info.height,
                origin_x=msg.info.origin.position.x,
                origin_y=msg.info.origin.position.y
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

    def _on_path(self, msg: Path):
        with self._lock:
            self._path = [
                {"x": p.pose.position.x, "y": p.pose.position.y}
                for p in msg.poses
            ]

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            now = time.time()
            # Kiểm tra dữ liệu cũ: nếu không có pose trong 1.5s thì đánh dấu stale
            is_stale = (now - self._last_pose_time) > 1.5 if self._last_pose_time > 0 else True
            is_conn = (now - self._last_pose_time) < 5.0 if self._last_pose_time > 0 else False

            return {
                "pose": dict(self._pose) if self._pose else None,
                "battery_percent": self._battery_percent,
                "is_connected": is_conn,
                "is_data_stale": is_stale,
                "control_mode": self._control_mode,
                "navigation_state": self._navigation_state,
                "has_goal": self._has_goal,
                "goal_id": self._goal_id,
                "destination_id": self._destination_id,
                "voice_state": self._voice_state,
                "voice_transcript": self._voice_transcript,
                "voice_response": self._voice_response,
                "message": self._message,
                "last_updated": int(now * 1000)
            }

    def get_destinations(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._destinations)

    def upsert_destination(self, destination: Dict[str, Any]) -> Dict[str, Any]:
        if not self._cli_upsert_dest or not HAS_AIRPORT_INTERFACES:
            return {"success": False, "message": "Service upsert destination hoặc package airport_robot_interfaces chưa sẵn sàng."}
        
        if not self._cli_upsert_dest.wait_for_service(timeout_sec=2.0):
            return {"success": False, "message": "Không tìm thấy ROS service upsert destination."}

        req = UpsertDestination.Request()
        dest_msg = Destination()
        dest_msg.id = destination.get("id", "")
        dest_msg.name = destination.get("name", "")
        dest_msg.map_id = destination.get("map_id", "map")
        
        # Điền pose
        pose_data = destination.get("pose", {})
        pos = pose_data.get("position", {})
        orient = pose_data.get("orientation", {})
        dest_msg.pose.header.frame_id = self._cfg.frames.get("map", "map")
        dest_msg.pose.pose.position.x = float(pos.get("x", 0.0))
        dest_msg.pose.pose.position.y = float(pos.get("y", 0.0))
        dest_msg.pose.pose.position.z = float(pos.get("z", 0.0))
        dest_msg.pose.pose.orientation.x = float(orient.get("x", 0.0))
        dest_msg.pose.pose.orientation.y = float(orient.get("y", 0.0))
        dest_msg.pose.pose.orientation.z = float(orient.get("z", 0.0))
        dest_msg.pose.pose.orientation.w = float(orient.get("w", 1.0))
        req.destination = dest_msg

        future = self._cli_upsert_dest.call_async(req)
        # Chờ phản hồi tối đa timeout_sec cấu hình
        timeout = self._cfg.get_service("destinations_upsert").timeout_sec or 5.0
        time.sleep(0.1)
        return {"success": True, "message": "Đã gửi yêu cầu lưu điểm đến sang ROS service."}

    def start_navigation(self, destination_id: str, owner_id: str) -> Dict[str, Any]:
        if not self._action_nav or not HAS_NAV2_ACTION:
            return {"success": False, "message": "Action client Nav2 chưa được khởi tạo."}

        dest = next((d for d in self._destinations if d.get("id") == destination_id), None)
        if not dest:
            return {"success": False, "message": "Không tìm thấy điểm đến yêu cầu."}

        if not self._action_nav.wait_for_server(timeout_sec=2.0):
            return {"success": False, "message": "Server action điều hướng chưa sẵn sàng."}

        goal_msg = NavigateToPose.Goal()
        goal_msg.pose.header.frame_id = self._cfg.frames.get("map", "map")
        goal_msg.pose.header.stamp = self._node.get_clock().now().to_msg()
        pos = dest["pose"]["position"]
        orient = dest["pose"]["orientation"]
        goal_msg.pose.pose.position.x = float(pos["x"])
        goal_msg.pose.pose.position.y = float(pos["y"])
        goal_msg.pose.pose.orientation.x = float(orient.get("x", 0.0))
        goal_msg.pose.pose.orientation.y = float(orient.get("y", 0.0))
        goal_msg.pose.pose.orientation.z = float(orient.get("z", 0.0))
        goal_msg.pose.pose.orientation.w = float(orient.get("w", 1.0))

        send_future = self._action_nav.send_goal_async(goal_msg)
        return {"success": True, "message": f"Đã gửi mục tiêu điều hướng tới: {dest['name']}"}

    def cancel_navigation(self, owner_id: str, is_admin: bool = False) -> Dict[str, Any]:
        if not self._action_nav or not HAS_NAV2_ACTION:
            return {"success": False, "message": "Action client chưa sẵn sàng."}

        if self._current_goal_handle:
            self._current_goal_handle.cancel_goal_async()
            return {"success": True, "message": "Đã gửi tín hiệu hủy goal qua action cancel."}
        
        return {"success": False, "message": "Không có goal handle đang chạy để hủy."}

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

    def dispose(self) -> None:
        try:
            if hasattr(self, "_node") and self._node:
                self._node.destroy_node()
            if rclpy.ok():
                rclpy.shutdown()
        except Exception:
            pass
