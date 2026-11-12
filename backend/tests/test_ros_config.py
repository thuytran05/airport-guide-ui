import pytest
import tempfile
import yaml
from pathlib import Path
from app.ros_config import RosConfig, get_ros_config

SAMPLE_YAML = """
schema_version: "1.0"
active_profile: "sim"

connection:
  gateway_http_url: "http://localhost:8000"
  ros_domain_id: 42

frames:
  map: "map"
  odom: "odom"
  base_link: "base_link"

topics:
  map:
    name: "/test/map"
    type: "nav_msgs/msg/OccupancyGrid"
    direction: "subscribe"
    enabled: true
    required: true
  robot_pose:
    name: "/test/pose"
    type: "geometry_msgs/msg/PoseStamped"
    direction: "subscribe"
    enabled: true
    required: true
  robot_state:
    name: "/test/state"
    type: "airport_robot_interfaces/msg/RobotState"
    direction: "subscribe"
    enabled: true
    required: true
  destinations:
    name: "/test/destinations"
    type: "airport_robot_interfaces/msg/DestinationList"
    direction: "subscribe"
    enabled: true
    required: true

actions:
  navigate:
    name: "/test/navigate_to_pose"
    type: "nav2_msgs/action/NavigateToPose"
    direction: "action_client"
    enabled: true
    required: true

profiles:
  sim:
    use_sim_time: true
    connection:
      ros_domain_id: 42
  real:
    use_sim_time: false
    connection:
      ros_domain_id: 0
    topics:
      map:
        name: "/real/map"
"""

def test_load_and_profile_merge():
    with tempfile.NamedTemporaryFile("w+", suffix=".yaml", delete=False, encoding="utf-8") as f:
        f.write(SAMPLE_YAML)
        temp_path = f.name

    try:
        # 1. Kiểm tra profile SIM
        cfg_sim = RosConfig(config_path=temp_path)
        assert cfg_sim.active_profile == "sim"
        assert cfg_sim.use_sim_time is True
        assert cfg_sim.ros_domain_id == 42
        assert cfg_sim.get_topic("map").name == "/test/map"

        # 2. Đổi sang profile REAL và kiểm tra merge ghi đè
        with open(temp_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        data["active_profile"] = "real"
        with open(temp_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f)

        cfg_real = RosConfig(config_path=temp_path)
        assert cfg_real.active_profile == "real"
        assert cfg_real.use_sim_time is False
        assert cfg_real.ros_domain_id == 0
        # Kiểm tra ghi đè topic name ở profile real
        assert cfg_real.get_topic("map").name == "/real/map"
        # Các topic khác vẫn giữ nguyên từ cấu hình chung
        assert cfg_real.get_topic("robot_pose").name == "/test/pose"

    finally:
        Path(temp_path).unlink(missing_ok=True)

def test_topic_name_change_propagation():
    """Chứng minh khi đổi một tên topic trong YAML, RosConfig đọc được tên mới sau khởi động lại"""
    with tempfile.NamedTemporaryFile("w+", suffix=".yaml", delete=False, encoding="utf-8") as f:
        f.write(SAMPLE_YAML)
        temp_path = f.name

    try:
        cfg1 = RosConfig(config_path=temp_path)
        assert cfg1.get_topic("robot_pose").name == "/test/pose"

        # Thay đổi tên topic robot_pose
        with open(temp_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        data["topics"]["robot_pose"]["name"] = "/custom/airport/my_pose"
        with open(temp_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f)

        # Nạp lại cấu hình (tương đương backend khởi động lại)
        cfg2 = RosConfig(config_path=temp_path)
        assert cfg2.get_topic("robot_pose").name == "/custom/airport/my_pose"

    finally:
        Path(temp_path).unlink(missing_ok=True)

def test_validation_missing_required():
    """Kiểm tra báo lỗi rõ khi YAML thiếu topic bắt buộc"""
    bad_yaml = """
schema_version: "1.0"
active_profile: "sim"
topics:
  map:
    name: "/test/map"
    type: "nav_msgs/msg/OccupancyGrid"
actions:
  navigate:
    name: "/test/navigate"
    type: "nav2_msgs/action/NavigateToPose"
"""
    with tempfile.NamedTemporaryFile("w+", suffix=".yaml", delete=False, encoding="utf-8") as f:
        f.write(bad_yaml)
        temp_path = f.name

    try:
        with pytest.raises(ValueError, match="Thiếu định nghĩa topic bắt buộc"):
            RosConfig(config_path=temp_path)
    finally:
        Path(temp_path).unlink(missing_ok=True)
