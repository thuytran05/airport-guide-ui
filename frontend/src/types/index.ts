// ===== Định nghĩa kiểu dữ liệu chuẩn (Domain Types) =====

// 1. Phân quyền người dùng (2 vai trò)
export type UserRole = 'passenger' | 'admin';

export interface User {
  id: string;
  username: string;
  fullName: string;
  role: UserRole;
}

// 2. Điểm đến lưu bền vững (Khớp với ROS Destination.msg)
export interface DestinationPose {
  position: {
    x: number;
    y: number;
    z: number;
  };
  orientation: {
    x: number;
    y: number;
    z: number;
    w: number;
  };
}

export interface Destination {
  id: string;
  name: string;
  map_id: string;
  pose: DestinationPose;
}

// 3. Trạng thái Robot (Khớp với ROS RobotState.msg & Telemetry)
export interface RobotPose {
  x: number;
  y: number;
  theta: number; // radian
}

export type ControlMode = 'AUTO' | 'MANUAL' | 'TRANSITION' | 'FAULT';

export type NavigationState =
  | 'IDLE'
  | 'PENDING'
  | 'ACCEPTED'
  | 'NAVIGATING'
  | 'PAUSING'
  | 'PAUSED'
  | 'CANCELING'
  | 'SUCCEEDED'
  | 'CANCELED'
  | 'FAILED'
  | 'UNKNOWN';

export type VoiceState = 'IDLE' | 'LISTENING' | 'PROCESSING' | 'SPEAKING' | 'ERROR';

export interface RobotStatus {
  pose: RobotPose | null;
  frame_id?: string;
  stamp?: {
    sec: number;
    nanosec: number;
  } | null;
  batteryPercent: number | null; // null nếu chưa có dữ liệu đo
  isConnected: boolean;
  isDataStale: boolean;
  simClockStalled?: boolean;
  mapVersion?: string | null;
  controlMode: ControlMode;
  navigationState: NavigationState;
  hasGoal: boolean;
  goalId: string;
  tripId?: string;
  destinationId: string;
  isOwner?: boolean;
  hasActiveTrip?: boolean;
  distanceRemaining?: number | null;
  estimatedTimeRemaining?: number | null;
  voiceState: VoiceState;
  voiceTranscript: string | null;
  voiceResponse: string | null;
  message: string;
  destinationsVersion?: number;
  lastUpdated: number;
}

// 4. Cảnh báo chẩn đoán từ /airport/alerts (Khớp DiagnosticStatus.msg)
export interface AlertItem {
  name: string;
  level: number; // 0=OK, 1=WARN, 2=ERROR, 3=STALE
  message: string;
  hardware_id: string;
}

// 5. Điểm trên đường đi Nav2
export interface PathPoint {
  x: number;
  y: number;
}

// 6. Bản đồ OccupancyGrid 2D từ /map
export interface MapMetadata {
  width: number;
  height: number;
  resolution: number;
  origin_x: number;
  origin_y: number;
  origin_yaw: number;
}

export interface MapData {
  status: string;
  map_version: string;
  frame_id: string;
  stamp?: {
    sec: number;
    nanosec: number;
  };
  metadata: MapMetadata;
  image_url: string;
  imageBlobUrl?: string;
}

// 7. Chế độ hiển thị ảnh nền bản đồ (Bản đồ ROS và Sơ đồ hành khách)
export type MapBackgroundMode = 'ros' | 'passenger';
