import math
from typing import Dict, Any, Tuple, Optional
from pydantic import BaseModel

class MapMetadata(BaseModel):
    resolution: float = 0.05       # meters per pixel/cell
    width: int = 800               # pixels
    height: int = 500              # pixels
    origin_x: float = -20.0        # ROS map origin x in meters
    origin_y: float = -12.5        # ROS map origin y in meters
    origin_yaw: float = 0.0        # rotation of the map origin in radians

def quaternion_to_yaw(x: float, y: float, z: float, w: float) -> float:
    """
    Chuyển đổi góc quay quaternion (x, y, z, w) sang góc yaw (radians) quanh trục Z trong ROS.
    """
    siny_cosp = 2.0 * (w * z + x * y)
    cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
    return math.atan2(siny_cosp, cosy_cosp)

def ros_to_canvas_pose(
    ros_x: float,
    ros_y: float,
    ros_theta: float,
    map_meta: MapMetadata,
    canvas_width: float = 800.0,
    canvas_height: float = 500.0
) -> Dict[str, float]:
    """
    Biến đổi tọa độ ROS trong frame 'map' (meters, trục Y hướng lên, góc yaw CCW)
    sang tọa độ Canvas hiển thị trên Web (pixels, trục Y hướng xuống, góc yaw CW).

    LƯU Ý KỸ THUẬT:
    1. Tọa độ đầu vào PHẢI nằm trong frame 'map' (đã biến đổi qua TF map -> base_link).
       Tuyệt đối không lấy tọa độ odom (frame odom trôi theo thời gian và không khớp với bản đồ tĩnh).
    2. Phép biến đổi:
       x_map_cell = (ros_x - origin_x) / resolution
       y_map_cell = (ros_y - origin_y) / resolution
       y_canvas = canvas_height - (y_map_cell * (canvas_height / map_meta.height))
    """
    # 1. Trừ origin của bản đồ
    dx = ros_x - map_meta.origin_x
    dy = ros_y - map_meta.origin_y

    # Nếu origin có góc xoay origin_yaw
    if abs(map_meta.origin_yaw) > 1e-5:
        c = math.cos(-map_meta.origin_yaw)
        s = math.sin(-map_meta.origin_yaw)
        dx_rot = dx * c - dy * s
        dy_rot = dx * s + dy * c
        dx, dy = dx_rot, dy_rot

    # 2. Quy đổi sang đơn vị pixel/cell trên bản đồ gốc
    px = dx / map_meta.resolution
    py = dy / map_meta.resolution

    # 3. Tỉ lệ scale sang kích thước canvas
    scale_x = canvas_width / float(map_meta.width)
    scale_y = canvas_height / float(map_meta.height)

    canvas_x = px * scale_x
    # Trục Y của canvas hướng xuống dưới, trong khi trục Y của ROS hướng lên trên
    canvas_y = canvas_height - (py * scale_y)

    # 4. Góc quay trên Canvas: ROS yaw là CCW (ngược chiều kim đồng hồ),
    # trong hệ SVG/Canvas góc quay là CW (thuận chiều kim đồng hồ)
    canvas_theta = - (ros_theta - map_meta.origin_yaw)

    return {
        "x": round(canvas_x, 2),
        "y": round(canvas_y, 2),
        "theta": round(canvas_theta, 4)
    }

def canvas_to_ros_pose(
    canvas_x: float,
    canvas_y: float,
    canvas_theta: float,
    map_meta: MapMetadata,
    canvas_width: float = 800.0,
    canvas_height: float = 500.0
) -> Dict[str, float]:
    """
    Biến đổi ngược từ tọa độ nhấp chuột / điểm cấu hình trên Web Canvas sang tọa độ ROS mét (frame 'map').
    Dùng khi Operator chọn hoặc thêm địa điểm trên giao diện web.
    """
    scale_x = canvas_width / float(map_meta.width)
    scale_y = canvas_height / float(map_meta.height)

    px = canvas_x / scale_x
    py = (canvas_height - canvas_y) / scale_y

    dx = px * map_meta.resolution
    dy = py * map_meta.resolution

    if abs(map_meta.origin_yaw) > 1e-5:
        c = math.cos(map_meta.origin_yaw)
        s = math.sin(map_meta.origin_yaw)
        ros_x = dx * c - dy * s + map_meta.origin_x
        ros_y = dx * s + dy * c + map_meta.origin_y
    else:
        ros_x = dx + map_meta.origin_x
        ros_y = dy + map_meta.origin_y

    ros_theta = -canvas_theta + map_meta.origin_yaw

    return {
        "x": round(ros_x, 4),
        "y": round(ros_y, 4),
        "theta": round(ros_theta, 4)
    }
