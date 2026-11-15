import React, { createContext, useContext, useEffect, useState, useCallback, useRef, ReactNode } from 'react';
import { RobotStatus, Destination, AlertItem, PathPoint, MapData, OperationalEvent } from '../types';
import { apiClient } from '../api/client';
import { wsClient } from '../api/wsClient';
import { useAuth } from './AuthContext';

interface RobotContextType {
  status: RobotStatus;
  destinations: Destination[];
  alerts: AlertItem[];
  events: OperationalEvent[];
  eventsStartedAt: number | null;
  path: PathPoint[] | null;
  isBackendConnected: boolean;
  mapData: MapData | null;
  isMapLoading: boolean;
  mapError: string | null;
  refreshMap: () => Promise<void>;
  refreshDestinations: () => Promise<void>;
  refreshEvents: () => Promise<void>;
  startNavigation: (destinationId: string) => Promise<{ success: boolean; message?: string }>;
  cancelNavigation: () => Promise<{ success: boolean; message?: string }>;
  pauseNavigation: () => Promise<{ success: boolean; message?: string }>;
  resumeNavigation: () => Promise<{ success: boolean; message?: string }>;
  startVoiceSession: () => Promise<{ success: boolean; message?: string }>;
  confirmVoiceProposal: (proposalId: string, destinationId?: string) => Promise<{ success: boolean; message?: string }>;
  dismissVoiceProposal: () => Promise<{ success: boolean; message?: string }>;
  setManualControl: (enable: boolean) => Promise<{ success: boolean; message?: string }>;
  sendManualVelocity: (linear_x: number, angular_z: number, seq?: number, hold_id?: string) => Promise<boolean>;
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
  voiceAvailable: false,
  voiceProposal: null,
  message: 'Đang kết nối tới máy chủ...',
  manualConsumerAvailable: false,
  manualOperatorId: null,
  readiness: null,
  lastUpdated: 0,
};

const RobotContext = createContext<RobotContextType | undefined>(undefined);

export function RobotProvider({ children }: { children: ReactNode }) {
  const { token, effectiveToken, currentUser } = useAuth();
  const [status, setStatus] = useState<RobotStatus>(DEFAULT_STATUS);
  const [destinations, setDestinations] = useState<Destination[]>([]);
  const [alerts, setAlerts] = useState<AlertItem[]>([]);
  const [events, setEvents] = useState<OperationalEvent[]>([]);
  const [eventsStartedAt, setEventsStartedAt] = useState<number | null>(null);
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
  const lastFailedMapRef = useRef<{ version: string | null; time: number }>({ version: null, time: 0 });

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

    // Throttle nếu phiên bản này vừa thất bại trong vòng 5 giây (tránh spam 5Hz khi lỗi token/mạng)
    const now = Date.now();
    if (
      targetVersion &&
      lastFailedMapRef.current.version === targetVersion &&
      now - lastFailedMapRef.current.time < 5000
    ) {
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
      lastFailedMapRef.current = { version: null, time: 0 };

      // Chỉ công bố cặp mới lên UI sau khi ảnh đã tải thành công
      setMapData(meta);
      setMapError(null);
    } catch (err: any) {
      if (currentSeq === fetchSeqRef.current) {
        console.warn('Lỗi khi tải bản đồ OccupancyGrid:', err);
        setMapError(err.message || 'Không thể tải bản đồ từ máy chủ.');
        inFlightVersionRef.current = null;
        lastFailedMapRef.current = { version: targetVersion || null, time: Date.now() };
      }
    } finally {
      if (currentSeq === fetchSeqRef.current) {
        setIsMapLoading(false);
      }
    }
  }, []);

  const refreshMap = useCallback(async () => {
    activeMapVersionRef.current = null;
    lastFailedMapRef.current = { version: null, time: 0 };
    await fetchMapData();
  }, [fetchMapData]);

  const refreshEvents = useCallback(async () => {
    try {
      const res = await apiClient.get<{ events: OperationalEvent[]; started_at: number; version: number }>('/api/robot/admin/events');
      if (res && res.events) {
        setEvents(res.events);
        if (res.started_at) {
          setEventsStartedAt(res.started_at);
        }
      }
    } catch {
      // ignore if not admin
    }
  }, []);

  // Dọn dẹp dữ liệu Admin khi chuyển sang vai trò Passenger (logout)
  useEffect(() => {
    if (currentUser?.role !== 'admin') {
      setEvents([]);
      setEventsStartedAt(null);
      setAlerts([]);
      setStatus((prev) => ({
        ...prev,
        voiceProposal: null,
      }));
    }
  }, [currentUser?.role]);

  // 3. Kết nối WebSocket khi khởi động hoặc khi token phiên thay đổi
  useEffect(() => {
    activeMapVersionRef.current = null;
    lastFailedMapRef.current = { version: null, time: 0 };
    wsClient.connect(effectiveToken);

    const unsubStatus = wsClient.onStatusChange((connected) => {
      setIsBackendConnected(connected);
      if (connected) {
        // Tải bản đồ khi WebSocket kết nối thành công hoặc kết nối lại
        fetchMapData();
      } else {
        setStatus((prev) => ({
          ...prev,
          isDataStale: true,
          message: 'Đang kết nối lại với máy chủ...',
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
            voiceAvailable: rob.voice_available ?? false,
            voiceProposal: rob.voice_proposal || null,
            message: rob.message || '',
            manualConsumerAvailable: rob.manual_consumer_available ?? false,
            manualOperatorId: rob.manual_operator_id ?? null,
            readiness: rob.readiness ?? null,
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

        if (payload.admin_data) {
          if (payload.admin_data.alerts) {
            setAlerts(payload.admin_data.alerts);
          }
          if (payload.admin_data.events) {
            setEvents(payload.admin_data.events);
          }
          if (payload.admin_data.events_started_at) {
            setEventsStartedAt(payload.admin_data.events_started_at);
          }
        }
      }
    });

    refreshDestinations();
    fetchMapData();
    if (currentUser?.role === 'admin') {
      refreshEvents();
    }

    return () => {
      unsubStatus();
      unsubTelemetry();
    };
  }, [effectiveToken, currentUser?.role, refreshDestinations, fetchMapData, refreshEvents]);

  // 4. Các hàm nghiệp vụ (REST calls)
  const startNavigation = async (destinationId: string) => {
    try {
      if (!token) {
        await apiClient.ensurePassengerToken();
      }
      const res = await apiClient.post<{ success: boolean; message?: string }>('/api/robot/navigate', {
        destination_id: destinationId,
      });
      if (res && res.success) {
        setStatus((prev) => ({
          ...prev,
          isOwner: true,
          hasActiveTrip: true,
          destinationId: destinationId,
          navigationState: prev.navigationState === 'IDLE' ? 'PENDING' : prev.navigationState,
        }));
      }
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

  const confirmVoiceProposal = async (proposalId: string, destinationId?: string) => {
    try {
      const res = await apiClient.post<{ success: boolean; message?: string }>('/api/robot/voice/confirm', {
        proposal_id: proposalId,
        destination_id: destinationId,
      });
      // Khi đã xác nhận thành công, dọn dẹp proposal trên local state để chặn bấm xác nhận lần 2
      setStatus((prev) => ({ ...prev, voiceProposal: null }));
      return res;
    } catch (err: any) {
      return { success: false, message: err.message };
    }
  };

  const dismissVoiceProposal = async () => {
    try {
      const res = await apiClient.post<{ success: boolean; message?: string }>('/api/robot/voice/dismiss');
      setStatus((prev) => ({ ...prev, voiceProposal: null }));
      return res;
    } catch (err: any) {
      setStatus((prev) => ({ ...prev, voiceProposal: null }));
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

  const sendManualVelocity = async (
    linear_x: number,
    angular_z: number,
    seq?: number,
    hold_id?: string
  ): Promise<boolean> => {
    try {
      await apiClient.post('/api/robot/control/velocity', {
        linear_x,
        angular_z,
        seq: seq ?? 0,
        hold_id: hold_id || undefined,
      });
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
        events,
        eventsStartedAt,
        path,
        isBackendConnected,
        mapData,
        isMapLoading,
        mapError,
        refreshMap,
        refreshDestinations,
        refreshEvents,
        startNavigation,
        cancelNavigation,
        pauseNavigation,
        resumeNavigation,
        startVoiceSession,
        confirmVoiceProposal,
        dismissVoiceProposal,
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
