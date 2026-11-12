"""
Bộ nạp và kiểm tra tính hợp lệ của cấu hình giao tiếp ROS (ROS Interface Config Loader).
Đọc file config/robot_interface.yaml duy nhất, áp dụng profile (sim/real), và cung cấp
thông số cho backend/adapters mà không bị hardcode trong mã nguồn.
"""

import os
import sys
import copy
from pathlib import Path
from typing import Any, Dict, Optional
import yaml
from pydantic import BaseModel, Field

class InterfaceEntry(BaseModel):
    name: str
    type: str
    direction: str  # subscribe, publish, service_client, action_client
    enabled: bool = True
    required: bool = False
    qos: Optional[Dict[str, Any]] = None
    timeout_sec: Optional[float] = None
    description: str = ""

def deep_merge(source: dict, overrides: dict) -> dict:
    """Gộp đệ quy từ điển overrides vào source mà không làm mất các khóa gốc."""
    result = copy.deepcopy(source)
    for key, value in overrides.items():
        if isinstance(value, dict) and key in result and isinstance(result[key], dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result

class RosConfig:
    _instance: Optional["RosConfig"] = None

    def __init__(self, config_path: Optional[str] = None):
        self.config_path = self._resolve_config_path(config_path)
        self.raw_data = self._load_yaml(self.config_path)
        self.active_profile = self.raw_data.get("active_profile", "sim")
        self.merged_config = self._build_merged_config()
        self._validate()

    @staticmethod
    def _resolve_config_path(custom_path: Optional[str] = None) -> Path:
        if custom_path:
            p = Path(custom_path)
            if p.is_file():
                return p
        env_path = os.getenv("ROBOT_CONFIG_PATH")
        if env_path and Path(env_path).is_file():
            return Path(env_path)
        
        # Thử tìm theo cấu trúc thư mục của project
        current = Path(__file__).resolve().parent  # backend/app
        candidate1 = current.parent.parent / "config" / "robot_interface.yaml"
        if candidate1.is_file():
            return candidate1
        candidate2 = Path.cwd() / "config" / "robot_interface.yaml"
        if candidate2.is_file():
            return candidate2
        candidate3 = Path("config/robot_interface.yaml")
        if candidate3.is_file():
            return candidate3.resolve()
        
        raise FileNotFoundError("Không tìm thấy file cấu hình config/robot_interface.yaml!")

    @staticmethod
    def _load_yaml(path: Path) -> dict:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if not isinstance(data, dict):
                    raise ValueError("Nội dung file YAML không đúng định dạng từ điển (dict).")
                return data
        except Exception as e:
            raise RuntimeError(f"Lỗi khi đọc file YAML '{path}': {e}")

    def _build_merged_config(self) -> dict:
        """Gộp cấu hình chung với profile tương ứng (sim hoặc real)"""
        base = {
            "schema_version": self.raw_data.get("schema_version", "1.0"),
            "active_profile": self.active_profile,
            "connection": self.raw_data.get("connection", {}),
            "frames": self.raw_data.get("frames", {}),
            "topics": self.raw_data.get("topics", {}),
            "services": self.raw_data.get("services", {}),
            "actions": self.raw_data.get("actions", {}),
            "nodes": self.raw_data.get("nodes", {}),
            "velocity_limits": self.raw_data.get("velocity_limits", {}),
            "destinations_storage_path": self.raw_data.get("destinations_storage_path", "config/destinations.yaml"),
            "use_sim_time": False
        }

        profiles = self.raw_data.get("profiles", {})
        if self.active_profile in profiles:
            profile_overrides = profiles[self.active_profile]
            base = deep_merge(base, profile_overrides)
        
        return base

    def _validate(self):
        """Kiểm tra các trường bắt buộc theo quy định"""
        if "schema_version" not in self.merged_config:
            raise ValueError("Thiếu trường 'schema_version' trong cấu hình.")
        if "topics" not in self.merged_config:
            raise ValueError("Thiếu khối cấu hình 'topics'.")
        
        # Kiểm tra các topic cốt lõi
        required_topics = ["map", "robot_pose", "robot_state", "destinations"]
        for topic_key in required_topics:
            if topic_key not in self.merged_config["topics"]:
                raise ValueError(f"Thiếu định nghĩa topic bắt buộc '{topic_key}' trong file cấu hình.")
            topic = self.merged_config["topics"][topic_key]
            if not topic.get("name") or not topic.get("type"):
                raise ValueError(f"Topic '{topic_key}' thiếu thuộc tính 'name' hoặc 'type'.")

        # Kiểm tra action navigate
        actions = self.merged_config.get("actions", {})
        if "navigate" not in actions:
            raise ValueError("Thiếu action 'navigate' trong khối cấu hình 'actions'.")

    def get_topic(self, key: str) -> Optional[InterfaceEntry]:
        t = self.merged_config.get("topics", {}).get(key)
        if not t:
            return None
        return InterfaceEntry(**t)

    def get_service(self, key: str) -> Optional[InterfaceEntry]:
        s = self.merged_config.get("services", {}).get(key)
        if not s:
            return None
        return InterfaceEntry(**s)

    def get_action(self, key: str) -> Optional[InterfaceEntry]:
        a = self.merged_config.get("actions", {}).get(key)
        if not a:
            return None
        return InterfaceEntry(**a)

    @property
    def frames(self) -> Dict[str, str]:
        return self.merged_config.get("frames", {})

    @property
    def velocity_limits(self) -> Dict[str, Any]:
        return self.merged_config.get("velocity_limits", {
            "linear_max": 0.3,
            "angular_max": 0.5,
            "cmd_publish_rate_hz": 10,
            "cmd_timeout_sec": 0.5
        })

    @property
    def use_sim_time(self) -> bool:
        return self.merged_config.get("use_sim_time", False)

    @property
    def ros_domain_id(self) -> int:
        return self.merged_config.get("connection", {}).get("ros_domain_id", 0)

    @property
    def destinations_storage_path(self) -> str:
        return self.merged_config.get("destinations_storage_path", "config/destinations.yaml")

    def print_active_config(self):
        """In ra bảng cấu hình đang kích hoạt theo định dạng CLI dễ nhìn"""
        print("=" * 88)
        print(f" CẤU HÌNH GIAO TIẾP ROS HIỆN HÀNH (AIRPORT GUIDE ROBOT)")
        print(f" File nguồn : {self.config_path}")
        print(f" Profile    : {self.active_profile.upper()} (use_sim_time={self.use_sim_time}, ROS_DOMAIN_ID={self.ros_domain_id})")
        print("=" * 88)
        header = f"{'Loại':<10} | {'Khóa':<18} | {'Tên ROS':<30} | {'Chiều':<15} | {'Trạng thái'}"
        print(header)
        print("-" * 88)

        # Topics
        for k, v in self.merged_config.get("topics", {}).items():
            status = "BẬT" if v.get("enabled", True) else "TẮT"
            req = " (Bắt buộc)" if v.get("required") else ""
            print(f"{'Topic':<10} | {k:<18} | {v.get('name',''):<30} | {v.get('direction',''):<15} | {status}{req}")

        # Services
        for k, v in self.merged_config.get("services", {}).items():
            status = "BẬT" if v.get("enabled", True) else "TẮT"
            req = " (Bắt buộc)" if v.get("required") else ""
            print(f"{'Service':<10} | {k:<18} | {v.get('name',''):<30} | {v.get('direction',''):<15} | {status}{req}")

        # Actions
        for k, v in self.merged_config.get("actions", {}).items():
            status = "BẬT" if v.get("enabled", True) else "TẮT"
            req = " (Bắt buộc)" if v.get("required") else ""
            print(f"{'Action':<10} | {k:<18} | {v.get('name',''):<30} | {v.get('direction',''):<15} | {status}{req}")

        print("=" * 88)
        print(f" Frames quy chiếu: map='{self.frames.get('map')}', odom='{self.frames.get('odom')}', base_link='{self.frames.get('base_link')}'")
        print(f" Giới hạn vận tốc: Linear Max={self.velocity_limits.get('linear_max')} m/s, Angular Max={self.velocity_limits.get('angular_max')} rad/s")
        print(f" Watchdog timeout: {self.velocity_limits.get('cmd_timeout_sec')}s")
        print("=" * 88)

def get_ros_config(reload: bool = False) -> RosConfig:
    if RosConfig._instance is None or reload:
        RosConfig._instance = RosConfig()
    return RosConfig._instance

if __name__ == "__main__":
    try:
        cfg = get_ros_config()
        cfg.print_active_config()
    except Exception as err:
        print(f"LỖI CẤU HÌNH: {err}", file=sys.stderr)
        sys.exit(1)
