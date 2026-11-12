import React, { createContext, useContext, useEffect, useState, useCallback, ReactNode } from 'react';
import { RobotStatus, Destination, AlertItem, PathPoint } from '../types';
import { apiClient } from '../api/client';
import { wsClient } from '../api/wsClient';
import { useAuth } from './AuthContext';

interface RobotContextType {
  status: RobotStatus;
  destinations: Destination[];
  alerts: AlertItem[];
  path: PathPoint[] | null;
  isBackendConnected: boolean;
  refreshDestinations: () => Promise<void>;
  startNavigation: (destinationId: string) => Promise<{ success: boolean; message?: string }>;
  cancelNavigation: () => Promise<{ success: boolean; message?: string }>;
  startVoiceSession: () => Promise<{ success: boolean; message?: string }>;
  setManualControl: (enable: boolean) => Promise<{ success: boolean; message?: string }>;
  sendManualVelocity: (linear_x: number, angular_z: number) => Promise<boolean>;
  upsertDestination: (dest: Destination) => Promise<{ success: boolean; message?: string }>;
}

const DEFAULT_STATUS: RobotStatus = {
  pose: null,
  batteryPercent: null,
  isConnected: false,
  isDataStale: true,
  controlMode: 'AUTO',
  navigationState: 'IDLE',
  hasGoal: false,
  goalId: '',
  destinationId: '',
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

  // 1. Tải danh sách điểm đến từ backend
  const refreshDestinations = useCallback(async () => {
    try {
      const data = await apiClient.get<Destination[]>('/api/robot/destinations');
      setDestinations(data);
    } catch (err) {
      console.warn('Chưa thể lấy danh sách điểm đến:', err);
    }
  }, []);

  // 2. Kết nối WebSocket khi khởi động
  useEffect(() => {
    wsClient.connect(token);

    const unsubStatus = wsClient.onStatusChange((connected) => {
      setIsBackendConnected(connected);
      if (!connected) {
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
            batteryPercent: rob.battery_percent,
            isConnected: rob.is_connected,
            isDataStale: rob.is_data_stale,
            controlMode: rob.control_mode || 'AUTO',
            navigationState: rob.navigation_state || 'IDLE',
            hasGoal: rob.has_goal || false,
            goalId: rob.goal_id || '',
            destinationId: rob.destination_id || '',
            voiceState: rob.voice_state || 'IDLE',
            voiceTranscript: rob.voice_transcript,
            voiceResponse: rob.voice_response,
            message: rob.message || '',
            lastUpdated: rob.last_updated || Date.now(),
          });
        }

        if (payload.path) {
          setPath(payload.path);
        }

        if (payload.admin_data && payload.admin_data.alerts) {
          setAlerts(payload.admin_data.alerts);
        }
      }
    });

    refreshDestinations();

    return () => {
      unsubStatus();
      unsubTelemetry();
    };
  }, [token, refreshDestinations]);

  // 3. Các hàm nghiệp vụ (REST calls)
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

  return (
    <RobotContext.Provider
      value={{
        status,
        destinations,
        alerts,
        path,
        isBackendConnected,
        refreshDestinations,
        startNavigation,
        cancelNavigation,
        startVoiceSession,
        setManualControl,
        sendManualVelocity,
        upsertDestination,
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
