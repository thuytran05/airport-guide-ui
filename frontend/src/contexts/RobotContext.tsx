import React, { createContext, useContext, useEffect, useState, useCallback, useRef, ReactNode } from 'react';
import { RobotStatus, Destination, AlertItem, PathPoint, MapData } from '../types';
import { apiClient } from '../api/client';
import { wsClient } from '../api/wsClient';
import { useAuth } from './AuthContext';

interface RobotContextType {
  status: RobotStatus;
  destinations: Destination[];
  alerts: AlertItem[];
  path: PathPoint[] | null;
  isBackendConnected: boolean;
  mapData: MapData | null;
  isMapLoading: boolean;
  mapError: string | null;
  refreshMap: () => Promise<void>;
  refreshDestinations: () => Promise<void>;
  startNavigation: (destinationId: string) => Promise<{ success: boolean; message?: string }>;
  cancelNavigation: () => Promise<{ success: boolean; message?: string }>;
  pauseNavigation: () => Promise<{ success: boolean; message?: string }>;
  resumeNavigation: () => Promise<{ success: boolean; message?: string }>;
  startVoiceSession: () => Promise<{ success: boolean; message?: string }>;
  setManualControl: (enable: boolean) => Promise<{ success: boolean; message?: string }>;
  sendManualVelocity: (linear_x: number, angular_z: number) => Promise<boolean>;
  upsertDestination: (dest: Destination) => Promise<{ success: boolean; message?: string }>;
  deleteDestination: (id: string) => Promise<{ success: boolean; message?: string }>;
}

const DEFAULT_STATUS: RobotStatus = {
  pose: null,
  frame_id: 'map',
  stamp: null,
  batteryPercent: null,
  isConnected: false,
  isDataStale: true,
  simClockStalled: false,
  mapVersion: null,
  controlMode: 'AUTO',
  navigationState: 'IDLE',
  hasGoal: false,
  goalId: '',
  tripId: '',
  destinationId: '',
  isOwner: false,
  hasActiveTrip: false,
  distanceRemaining: null,
  estimatedTimeRemaining: null,
  voiceState: 'IDLE',
  voiceTranscript: null,
  voiceResponse: null,
  message: 'Đang kết nối tới máy chủ...',
  lastUpdated: 0,
};

const RobotContext = createContext<RobotContextType | undefined>(undefined);

export function RobotProvider({ children }: { children: ReactNode }) {
  const { token } = useAuth();
  const [status, setStatus] = useState<RobotStatus>(DEFAULT_STATUS);
  const [destinations, setDestinations] = useState<Destination[]>([]);
  const [alerts, setAlerts] = useState<AlertItem[]>([]);
  const [path, setPath] = useState<PathPoint[] | null>(null);
  const [isBackendConnected, setIsBackendConnected] = useState<boolean>(false);

  // Quản lý bản đồ OccupancyGrid
  const [mapData, setMapData] = useState<MapData | null>(null);
  const [isMapLoading, setIsMapLoading] = useState<boolean>(false);
  const [mapError, setMapError] = useState<string | null>(null);

  // Refs để kiểm soát tải bản đồ và điểm đến, tránh gọi HTTP lặp ở 5Hz
  const activeMapVersionRef = useRef<string | null>(null);
  const activeDestinationsVersionRef = useRef<number | null>(null);
  const fetchSeqRef = useRef<number>(0);
  const inFlightVersionRef = useRef<string | null>(null);

  // 1. Tải danh sách điểm đến từ backend
  const refreshDestinations = useCallback(async () => {
    try {
      const data = await apiClient.get<Destination[]>('/api/robot/destinations');
      setDestinations(data);
    } catch (err) {
      console.warn('Chưa thể lấy danh sách điểm đến:', err);
    }
  }, []);

  // 2. Hàm tải bản đồ (Metadata + PNG thành một cặp nguyên tử)
  const fetchMapData = useCallback(async (targetVersion?: string, retryCount = 0) => {
    // Nếu targetVersion trùng với phiên bản đang hiển thị thành công, không gọi lại
    if (targetVersion && targetVersion === activeMapVersionRef.current) {
      return;
    }

    // Nếu đang trong quá trình tải đúng version này rồi, tránh trùng lặp
    if (targetVersion && targetVersion === inFlightVersionRef.current) {
      return;
    }

    const currentSeq = ++fetchSeqRef.current;
    inFlightVersionRef.current = targetVersion || null;
    setIsMapLoading(true);

    try {
      // Tải metadata từ backend qua proxy tương đối
      const meta = await apiClient.get<MapData>('/api/robot/map');

      // Nếu đã có bản đồ phiên bản này rồi và mapData đã sẵn sàng
      if (
        meta.map_version === activeMapVersionRef.current &&
        currentSeq === fetchSeqRef.current
      ) {
        setIsMapLoading(false);
        inFlightVersionRef.current = null;
        return;
      }

      // Pre-load ảnh PNG tương ứng với phiên bản để bảo đảm ảnh đã sẵn sàng trước khi công bố lên UI
      const imageUrl = meta.image_url.startsWith('/') ? meta.image_url : `/${meta.image_url}`;
      await new Promise<void>((resolve, reject) => {
        const img = new Image();
        img.onload = () => resolve();
        img.onerror = () => reject(new Error('Không thể tải ảnh bản đồ từ máy chủ.'));
        img.src = imageUrl;
      });

      // Nếu đã có request mới hơn bắt đầu, bỏ kết quả cũ
      if (currentSeq !== fetchSeqRef.current) {
        return;
      }

      activeMapVersionRef.current = meta.map_version;
      inFlightVersionRef.current = null;

      // Chỉ công bố cặp mới lên UI sau khi ảnh đã tải thành công
      setMapData(meta);
      setMapError(null);
    } catch (err: any) {
      if (currentSeq === fetchSeqRef.current) {
        console.warn('Lỗi khi tải bản đồ OccupancyGrid:', err);
        setMapError(err.message || 'Không thể tải bản đồ từ máy chủ.');
        inFlightVersionRef.current = null;
      }
    } finally {
      if (currentSeq === fetchSeqRef.current) {
        setIsMapLoading(false);
      }
    }
  }, []);

  const refreshMap = useCallback(async () => {
    activeMapVersionRef.current = null;
    await fetchMapData();
  }, [fetchMapData]);

  // 3. Kết nối WebSocket khi khởi động
  useEffect(() => {
    wsClient.connect(token);

    const unsubStatus = wsClient.onStatusChange((connected) => {
      setIsBackendConnected(connected);
      if (connected) {
        // Tải bản đồ khi WebSocket kết nối thành công hoặc kết nối lại
        fetchMapData();
      } else {
        setStatus((prev) => ({
          ...prev,
          isConnected: false,
          isDataStale: true,
          message: 'Mất kết nối với máy chủ Backend',
        }));
      }
    });

    const unsubTelemetry = wsClient.onTelemetry((payload) => {
      if (payload && payload.type === 'telemetry') {
        const rob = payload.robot_status;
        if (rob) {
          setStatus({
            pose: rob.pose,
            frame_id: rob.frame_id || 'map',
            stamp: rob.stamp || null,
            batteryPercent: rob.battery_percent,
            isConnected: rob.is_connected,
            isDataStale: rob.is_data_stale,
            simClockStalled: rob.sim_clock_stalled || false,
            mapVersion: rob.map_version || null,
            controlMode: rob.control_mode || 'AUTO',
            navigationState: rob.navigation_state || 'IDLE',
            hasGoal: rob.has_goal || false,
            goalId: rob.goal_id || '',
            tripId: rob.trip_id || '',
            destinationId: rob.destination_id || '',
            isOwner: rob.is_owner ?? false,
            hasActiveTrip: rob.has_active_trip ?? false,
            distanceRemaining: rob.distance_remaining ?? null,
            estimatedTimeRemaining: rob.estimated_time_remaining ?? null,
            voiceState: rob.voice_state || 'IDLE',
            voiceTranscript: rob.voice_transcript,
            voiceResponse: rob.voice_response,
            message: rob.message || '',
            lastUpdated: rob.last_updated || Date.now(),
          });

          // Tải bản đồ mới khi phát hiện map_version thay đổi
          if (rob.map_version && rob.map_version !== activeMapVersionRef.current) {
            fetchMapData(rob.map_version);
          }

          // Cập nhật danh sách điểm đến khi phát hiện destinations_version thay đổi
          if (
            rob.destinations_version !== undefined &&
            activeDestinationsVersionRef.current !== null &&
            rob.destinations_version !== activeDestinationsVersionRef.current
          ) {
            refreshDestinations();
          }
          if (rob.destinations_version !== undefined) {
            activeDestinationsVersionRef.current = rob.destinations_version;
          }
        }

        if (payload.path !== undefined) {
          if (payload.path === null || payload.path.length === 0) {
            setPath(null);
          } else {
            setPath(payload.path);
          }
        } else if (rob && ['IDLE', 'SUCCEEDED', 'CANCELED', 'FAILED', 'PAUSED'].includes(rob.navigation_state)) {
          setPath(null);
        }

        if (payload.admin_data && payload.admin_data.alerts) {
          setAlerts(payload.admin_data.alerts);
        }
      }
    });

    refreshDestinations();
    fetchMapData();

    return () => {
      unsubStatus();
      unsubTelemetry();
    };
  }, [token, refreshDestinations, fetchMapData]);

  // 4. Các hàm nghiệp vụ (REST calls)
  const startNavigation = async (destinationId: string) => {
    try {
      const res = await apiClient.post<{ success: boolean; message?: string }>('/api/robot/navigate', {
        destination_id: destinationId,
      });
      return res;
    } catch (err: any) {
      return { success: false, message: err.message };
    }
  };

  const cancelNavigation = async () => {
    try {
      const res = await apiClient.post<{ success: boolean; message?: string }>('/api/robot/cancel');
      return res;
    } catch (err: any) {
      return { success: false, message: err.message };
    }
  };

  const pauseNavigation = async () => {
    try {
      const res = await apiClient.post<{ success: boolean; message?: string }>('/api/robot/pause');
      return res;
    } catch (err: any) {
      return { success: false, message: err.message };
    }
  };

  const resumeNavigation = async () => {
    try {
      const res = await apiClient.post<{ success: boolean; message?: string }>('/api/robot/resume');
      return res;
    } catch (err: any) {
      return { success: false, message: err.message };
    }
  };

  const startVoiceSession = async () => {
    try {
      const res = await apiClient.post<{ success: boolean; message?: string }>('/api/robot/voice/start');
      return res;
    } catch (err: any) {
      return { success: false, message: err.message };
    }
  };

  const setManualControl = async (enable: boolean) => {
    try {
      const res = await apiClient.post<{ success: boolean; message?: string }>('/api/robot/control/manual', {
        enable,
      });
      return res;
    } catch (err: any) {
      return { success: false, message: err.message };
    }
  };

  const sendManualVelocity = async (linear_x: number, angular_z: number): Promise<boolean> => {
    try {
      await apiClient.post('/api/robot/control/velocity', { linear_x, angular_z });
      return true;
    } catch {
      return false;
    }
  };

  const upsertDestination = async (dest: Destination) => {
    try {
      const res = await apiClient.post<{ success: boolean; message?: string }>('/api/robot/destinations', dest);
      await refreshDestinations();
      return res;
    } catch (err: any) {
      return { success: false, message: err.message };
    }
  };

  const deleteDestination = async (id: string) => {
    try {
      const res = await apiClient.delete<{ success: boolean; message?: string }>(`/api/robot/destinations/${encodeURIComponent(id)}`);
      await refreshDestinations();
      return res;
    } catch (err: any) {
      return { success: false, message: err.message };
    }
  };

  return (
    <RobotContext.Provider
      value={{
        status,
        destinations,
        alerts,
        path,
        isBackendConnected,
        mapData,
        isMapLoading,
        mapError,
        refreshMap,
        refreshDestinations,
        startNavigation,
        cancelNavigation,
        pauseNavigation,
        resumeNavigation,
        startVoiceSession,
        setManualControl,
        sendManualVelocity,
        upsertDestination,
        deleteDestination,
      }}
    >
      {children}
    </RobotContext.Provider>
  );
}

export function useRobot() {
  const context = useContext(RobotContext);
  if (!context) {
    throw new Error('useRobot phải được sử dụng bên trong RobotProvider');
  }
  return context;
}
