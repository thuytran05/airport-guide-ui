import React, { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import { useRobot } from '../../contexts/RobotContext';
import { useAuth } from '../../contexts/AuthContext';
import { Destination } from '../../types';
import { MapView, MapBackgroundMode } from '../../components/MapView/MapView';
import styles from './Dashboard.module.css';

export default function AdminDashboard() {
  const { currentUser } = useAuth();
  const {
    status,
    destinations,
    alerts,
    events,
    eventsStartedAt,
    refreshEvents,
    isBackendConnected,
    path,
    mapData,
    isMapLoading,
    setManualControl,
    sendManualVelocity,
    upsertDestination,
    deleteDestination,
    startNavigation,
    cancelNavigation,
    pauseNavigation,
    resumeNavigation,
  } = useRobot();

  const [isSwitchingMode, setIsSwitchingMode] = useState(false);
  const [controlMsg, setControlMsg] = useState<string | null>(null);
  const [mapMode, setMapMode] = useState<MapBackgroundMode>('ros');

  // Điều khiển dẫn đường Nav2 phía Admin
  const [selectedNavDestId, setSelectedNavDestId] = useState('');
  const [navActionMsg, setNavActionMsg] = useState<string | null>(null);
  const [isNavSubmitting, setIsNavSubmitting] = useState(false);

  // Nếu điểm đang chọn bị xóa khỏi hệ thống, bỏ lựa chọn đó và khóa nút "Bắt đầu dẫn đường"
  useEffect(() => {
    if (selectedNavDestId && !destinations.some((d) => d.id === selectedNavDestId)) {
      setSelectedNavDestId('');
    }
  }, [destinations, selectedNavDestId]);

  // Form thêm / sửa điểm đến (Khởi tạo chuỗi rỗng để không ép giá trị 0)
  const [destId, setDestId] = useState('');
  const [destName, setDestName] = useState('');
  const [destX, setDestX] = useState('');
  const [destY, setDestY] = useState('');
  const [destYaw, setDestYaw] = useState('');
  const [destMsg, setDestMsg] = useState<string | null>(null);
  const [isSavingDest, setIsSavingDest] = useState(false);

  // Quản lý xóa điểm đến
  const [destToDelete, setDestToDelete] = useState<Destination | null>(null);
  const [isDeletingDest, setIsDeletingDest] = useState(false);
  const [deleteModalError, setDeleteModalError] = useState<string | null>(null);
  const [deleteActionError, setDeleteActionError] = useState<string | null>(null);
  const [deleteSuccessMsg, setDeleteSuccessMsg] = useState<string | null>(null);

  // Chế độ chọn vị trí & hướng trên bản đồ ROS và sao chép YAML
  const [isPickingCoord, setIsPickingCoord] = useState(false);
  const [copySuccessMsg, setCopySuccessMsg] = useState<string | null>(null);
  const [showCopyModal, setShowCopyModal] = useState(false);
  const [copiedYamlSnippet, setCopiedYamlSnippet] = useState('');

  const hasValidMap = Boolean(
    mapData &&
    mapData.metadata &&
    mapData.metadata.width > 0 &&
    mapData.metadata.height > 0 &&
    mapData.metadata.resolution > 0
  );

  const handleCoordinateSelect = useCallback((coords: { x: number; y: number; yawDeg?: number }) => {
    setDestX(coords.x.toFixed(2));
    setDestY(coords.y.toFixed(2));
    if (coords.yawDeg !== undefined) {
      setDestYaw(Math.round(coords.yawDeg).toString());
      setDestMsg(`📍 Đã lấy vị trí & hướng: X=${coords.x.toFixed(2)}m, Y=${coords.y.toFixed(2)}m, Yaw=${Math.round(coords.yawDeg)}°`);
    } else {
      setDestMsg(`📍 Đã lấy vị trí từ bản đồ: X=${coords.x.toFixed(2)}m, Y=${coords.y.toFixed(2)}m`);
    }
    setIsPickingCoord(false);
  }, []);

  const handleTogglePicking = () => {
    if (!isPickingCoord) {
      if (!hasValidMap) {
        setDestMsg('⚠️ Chưa có metadata bản đồ ROS hợp lệ để chọn tọa độ.');
        return;
      }
      if (mapMode !== 'ros') {
        setMapMode('ros');
      }
      setIsPickingCoord(true);
      setDestMsg('ℹ️ Chế độ chọn vị trí & hướng: Nhấn và kéo chuột trên bản đồ để chọn tọa độ và góc xoay.');
    } else {
      setIsPickingCoord(false);
      setDestMsg(null);
    }
  };

  // Preview Pin xem trước trên bản đồ (Điểm nháp)
  const previewPoint = useMemo(() => {
    if (destX.trim() === '' || destY.trim() === '') return null;
    const x = parseFloat(destX);
    const y = parseFloat(destY);
    if (isNaN(x) || isNaN(y)) return null;
    const yawDeg = destYaw.trim() !== '' ? parseFloat(destYaw) : undefined;
    return {
      x,
      y,
      yawDeg: isNaN(yawDeg as number) ? undefined : yawDeg,
    };
  }, [destX, destY, destYaw]);

  const generateYamlSnippet = () => {
    const id = destId.trim() || 'destination_id';
    const name = destName.trim() || 'Tên điểm đến';
    const x = destX.trim() !== '' ? parseFloat(destX) : 0.0;
    const y = destY.trim() !== '' ? parseFloat(destY) : 0.0;
    const yawDeg = destYaw.trim() !== '' ? parseFloat(destYaw) : 0.0;
    const yawRad = (yawDeg * Math.PI) / 180.0;
    const qz = Number(Math.sin(yawRad / 2).toFixed(4));
    const qw = Number(Math.cos(yawRad / 2).toFixed(4));

    return `  - id: "${id}"
    name: "${name}"
    map_id: "airport_floor_1"
    pose:
      header:
        frame_id: "map"
      position:
        x: ${x}
        y: ${y}
        z: 0.0
      orientation:
        x: 0.0
        y: 0.0
        z: ${qz}
        w: ${qw}`;
  };

  const handleCopyYaml = async () => {
    const snippet = generateYamlSnippet();
    setCopiedYamlSnippet(snippet);
    try {
      if (navigator?.clipboard?.writeText) {
        await navigator.clipboard.writeText(snippet);
        setCopySuccessMsg('Đã sao chép cấu hình YAML vào clipboard!');
        setTimeout(() => setCopySuccessMsg(null), 4000);
      } else {
        setShowCopyModal(true);
      }
    } catch {
      setShowCopyModal(true);
    }
  };

  // Trạng thái chuyến đi & quyền điều khiển
  const isNavTripActive =
    status.navigationState === 'NAVIGATING' ||
    status.navigationState === 'ACCEPTED' ||
    status.navigationState === 'PENDING' ||
    status.navigationState === 'PAUSING' ||
    status.navigationState === 'PAUSED' ||
    status.navigationState === 'CANCELING';
  const isNavigating = isNavTripActive;
  const isCanceling = status.navigationState === 'CANCELING';
  const isPausing = status.navigationState === 'PAUSING';
  const isPaused = status.navigationState === 'PAUSED';

  const isManual = status.controlMode === 'MANUAL';
  const hasConsumer = status.manualConsumerAvailable ?? false;
  const isOccupiedByOther = Boolean(
    isManual &&
    status.manualOperatorId &&
    currentUser &&
    status.manualOperatorId !== currentUser.id
  );

  // Phân quyền lái tay trực tiếp (Direct Press-and-Hold)
  const canDrive = Boolean(
    status.canManualControl ??
    (!isNavTripActive && status.isConnected && !status.isDataStale && hasConsumer && !isOccupiedByOther)
  );
  const manualLockReason = status.manualLockReason || (!hasConsumer ? 'Đường lệnh ROS (/airport/cmd_vel_manual) chưa có consumer tiếp nhận' : null);

  // Đánh giá trạng thái sẵn sàng dẫn đường & phân tích lý do nếu bị khóa
  // Dùng status.readiness từ backend làm nguồn sự thật duy nhất
  const readinessCheck = useMemo(() => {
    if (!isBackendConnected) {
      return {
        ready: false,
        severity: 'err' as const,
        title: 'Mất kết nối Gateway / WebSocket',
        badge: 'MẤT WEBSOCKET',
        reason: 'Không có kết nối thời gian thực tới Backend Gateway. Vui lòng kiểm tra tiến trình backend.',
      };
    }

    if (status.readiness && !status.readiness.ready) {
      const primaryReason = status.readiness.reasons[0] || 'Robot chưa sẵn sàng dẫn đường';
      const isSevere = !status.isConnected || status.isDataStale;
      return {
        ready: false,
        severity: isSevere ? ('err' as const) : ('warn' as const),
        title: primaryReason,
        badge: isSevere ? 'LỖI HỆ THỐNG' : 'CHƯA SẴN SÀNG',
        reason: status.readiness.reasons.join(' • '),
      };
    }

    if (!hasValidMap) {
      return {
        ready: false,
        severity: 'warn' as const,
        title: 'Chưa có bản đồ ROS',
        badge: 'CHỜ BẢN ĐỒ',
        reason: 'Chưa nhận được metadata và ảnh bản đồ OccupancyGrid hợp lệ từ /map.',
      };
    }

    if (destinations.length === 0) {
      return {
        ready: false,
        severity: 'warn' as const,
        title: 'Chưa có điểm đến',
        badge: 'THIẾU ĐIỂM ĐẾN',
        reason: 'Hệ thống chưa có điểm đến nào được lưu. Vui lòng thêm điểm đến bên dưới.',
      };
    }

    if (!selectedNavDestId) {
      return {
        ready: true,
        severity: 'ready' as const,
        title: 'Robot sẵn sàng dẫn đường',
        badge: 'SẴN SÀNG',
        reason: 'Tất cả các hệ thống con hoạt động bình thường. Vui lòng chọn một điểm đến để bắt đầu.',
      };
    }

    return {
      ready: true,
      severity: 'ready' as const,
      title: 'Robot sẵn sàng dẫn đường',
      badge: 'SẴN SÀNG',
      reason: 'Tất cả các hệ thống con (Gateway, AMCL, Bản đồ, Nav2, AUTO) đều sẵn sàng.',
    };
  }, [
    isBackendConnected,
    status.readiness,
    status.isConnected,
    status.isDataStale,
    hasValidMap,
    destinations.length,
    selectedNavDestId,
  ]);

  const sortedEvents = useMemo(() => {
    return [...events].sort((a, b) => b.timestamp - a.timestamp);
  }, [events]);

  // Vòng lặp gửi vận tốc 10Hz khi giữ nút điều khiển
  const driveTimerRef = useRef<any>(null);
  const activeVelRef = useRef<{ lin: number; ang: number }>({ lin: 0, ang: 0 });
  const activeHoldIdRef = useRef<string | null>(null);
  const holdSeqRef = useRef<number>(0);
  const stopDriveRef = useRef<() => void>(() => {});

  const [showSystemDetails, setShowSystemDetails] = useState(false);
  const [isRefreshingEvents, setIsRefreshingEvents] = useState(false);

  const isDrivingNow = Boolean(status.controlMode === 'MANUAL' && (status.isManualController || activeHoldIdRef.current));

  const handleRefreshEvents = async () => {
    setIsRefreshingEvents(true);
    try {
      await refreshEvents();
    } finally {
      setIsRefreshingEvents(false);
    }
  };

  const stopDrive = useCallback(() => {
    if (driveTimerRef.current) {
      clearInterval(driveTimerRef.current);
      driveTimerRef.current = null;
    }
    const finishedHoldId = activeHoldIdRef.current;
    activeHoldIdRef.current = null;
    activeVelRef.current = { lin: 0, ang: 0 };
    if (finishedHoldId) {
      holdSeqRef.current += 1;
      sendManualVelocity(0, 0, holdSeqRef.current, finishedHoldId);
    }
  }, [sendManualVelocity]);

  useEffect(() => {
    stopDriveRef.current = stopDrive;
  }, [stopDrive]);

  const startDrive = (lin: number, ang: number) => {
    if (!canDrive) return;
    if (driveTimerRef.current) {
      clearInterval(driveTimerRef.current);
      driveTimerRef.current = null;
    }
    const holdId = `hold_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`;
    activeHoldIdRef.current = holdId;
    holdSeqRef.current = 1;
    activeVelRef.current = { lin, ang };

    // Gửi ngay lập tức tick đầu tiên (Backend tự động chuyển tạm sang MANUAL)
    sendManualVelocity(lin, ang, 1, holdId);

    // Gửi chu kỳ 10Hz (100ms) trong khi còn giữ nút
    driveTimerRef.current = setInterval(async () => {
      if (activeHoldIdRef.current !== holdId) return;
      holdSeqRef.current += 1;
      const ok = await sendManualVelocity(
        activeVelRef.current.lin,
        activeVelRef.current.ang,
        holdSeqRef.current,
        holdId
      );
      if (!ok) {
        stopDrive();
      }
    }, 100);
  };

  useEffect(() => {
    // Watchdog an toàn: Dừng robot nếu tab trình duyệt mất focus, ẩn hoặc unmount
    const handleStop = () => stopDriveRef.current();
    const handleVisibilityChange = () => {
      if (document.hidden) stopDriveRef.current();
    };

    window.addEventListener('blur', handleStop);
    window.addEventListener('pagehide', handleStop);
    window.addEventListener('pointerup', handleStop);
    window.addEventListener('pointercancel', handleStop);
    document.addEventListener('visibilitychange', handleVisibilityChange);

    return () => {
      stopDriveRef.current();
      window.removeEventListener('blur', handleStop);
      window.removeEventListener('pagehide', handleStop);
      window.removeEventListener('pointerup', handleStop);
      window.removeEventListener('pointercancel', handleStop);
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, []);

  const handleSaveDestination = async (e: React.FormEvent) => {
    e.preventDefault();
    setDestMsg(null);
    if (!destId.trim() || !destName.trim()) {
      setDestMsg('Vui lòng nhập ID và Tên điểm đến.');
      return;
    }

    if (destX.trim() === '' || destY.trim() === '') {
      setDestMsg('Vui lòng nhập đầy đủ tọa độ X và Y (hoặc chọn vị trí trên bản đồ).');
      return;
    }

    const x = parseFloat(destX);
    const y = parseFloat(destY);
    if (isNaN(x) || isNaN(y)) {
      setDestMsg('Tọa độ X và Y phải là số thực hợp lệ.');
      return;
    }

    setIsSavingDest(true);
    const yawDeg = destYaw.trim() !== '' ? parseFloat(destYaw) : 0.0;
    const yawRad = (yawDeg * Math.PI) / 180;

    const newDest: Destination = {
      id: destId.trim(),
      name: destName.trim(),
      map_id: 'airport_floor_1',
      pose: {
        position: { x, y, z: 0.0 },
        orientation: {
          x: 0.0,
          y: 0.0,
          z: Math.sin(yawRad / 2),
          w: Math.cos(yawRad / 2),
        },
      },
    };

    const res = await upsertDestination(newDest);
    setIsSavingDest(false);
    if (res.success) {
      setDestMsg(`✅ ${res.message || 'Đã lưu điểm đến thành công.'}`);
      setDestId('');
      setDestName('');
      setDestX('');
      setDestY('');
      setDestYaw('');
    } else {
      setDestMsg(`❌ ${res.message || 'Lỗi khi lưu điểm đến.'}`);
    }
  };

  const handleAdminStart = async () => {
    if (!selectedNavDestId) return;
    setNavActionMsg(null);
    setIsNavSubmitting(true);
    const res = await startNavigation(selectedNavDestId);
    setIsNavSubmitting(false);
    if (!res.success) {
      setNavActionMsg(`❌ ${res.message || 'Không thể bắt đầu dẫn đường.'}`);
    } else {
      setNavActionMsg(`✅ ${res.message || 'Đã gửi lệnh dẫn đường tới Nav2.'}`);
    }
  };

  const handleAdminPause = async () => {
    setNavActionMsg(null);
    setIsNavSubmitting(true);
    const res = await pauseNavigation();
    setIsNavSubmitting(false);
    if (!res.success) {
      setNavActionMsg(`❌ ${res.message || 'Không thể tạm dừng dẫn đường.'}`);
    } else {
      setNavActionMsg(`✅ ${res.message || 'Đã gửi lệnh tạm dừng tới robot.'}`);
    }
  };

  const handleAdminResume = async () => {
    setNavActionMsg(null);
    setIsNavSubmitting(true);
    const res = await resumeNavigation();
    setIsNavSubmitting(false);
    if (!res.success) {
      setNavActionMsg(`❌ ${res.message || 'Không thể tiếp tục dẫn đường.'}`);
    } else {
      setNavActionMsg(`✅ ${res.message || 'Đã gửi lệnh tiếp tục dẫn đường.'}`);
    }
  };

  const handleAdminCancel = async () => {
    setNavActionMsg(null);
    setIsNavSubmitting(true);
    const res = await cancelNavigation();
    setIsNavSubmitting(false);
    if (!res.success) {
      setNavActionMsg(`❌ ${res.message || 'Không thể hủy chuyến.'}`);
    } else {
      setNavActionMsg(`✅ ${res.message || 'Đã gửi lệnh hủy chuyến.'}`);
    }
  };

  const handleRequestDelete = (dest: Destination) => {
    setDestToDelete(dest);
    setDeleteModalError(null);
    setDeleteActionError(null);
    setDeleteSuccessMsg(null);
  };

  const handleConfirmDelete = async () => {
    if (!destToDelete) return;
    setIsDeletingDest(true);
    setDeleteModalError(null);
    setDeleteActionError(null);
    setDeleteSuccessMsg(null);

    const res = await deleteDestination(destToDelete.id);
    setIsDeletingDest(false);

    if (res.success) {
      setDeleteSuccessMsg(`✅ Đã xóa điểm đến '${destToDelete.name}' thành công.`);
      if (destId === destToDelete.id) {
        setDestId('');
        setDestName('');
      }
      setDestToDelete(null);
    } else {
      setDeleteModalError(`❌ ${res.message || 'Lỗi khi xóa điểm đến.'}`);
      setDeleteActionError(`❌ ${res.message || 'Lỗi khi xóa điểm đến.'}`);
    }
  };

  const handleLoadToForm = (d: Destination) => {
    setDestId(d.id);
    setDestName(d.name);
    setDestX(d.pose.position.x.toFixed(2));
    setDestY(d.pose.position.y.toFixed(2));
    const qz = d.pose.orientation.z;
    const qw = d.pose.orientation.w;
    const yawRad = 2 * Math.atan2(qz, qw);
    const yawDeg = Math.round((yawRad * 180) / Math.PI);
    setDestYaw(yawDeg.toString());
  };

  return (
    <div className={styles.container}>
      {/* 1. Thanh trạng thái vận hành & sẵn sàng gọn gàng */}
      <div className={styles.readinessBar}>
        <div className={styles.readinessBarLeft}>
          <span className={styles.readinessIcon}>
            {readinessCheck.severity === 'ready' ? '🟢' : readinessCheck.severity === 'warn' ? '🟡' : '🔴'}
          </span>
          <div className={styles.readinessInfo}>
            <div className={styles.readinessTitleLine}>
              <strong className={styles.readinessTitle}>{readinessCheck.title}</strong>
              <span
                className={`${styles.readinessBadge} ${
                  readinessCheck.severity === 'ready'
                    ? styles.badgeReady
                    : readinessCheck.severity === 'warn'
                    ? styles.badgeWarn
                    : styles.badgeErr
                }`}
              >
                {readinessCheck.badge}
              </span>
            </div>
            <div className={styles.readinessReason}>{readinessCheck.reason}</div>
          </div>
        </div>
        <button
          type="button"
          className={`${styles.detailsToggleBtn} ${showSystemDetails ? styles.detailsActive : ''}`}
          onClick={() => setShowSystemDetails((v) => !v)}
          title="Bật/tắt xem thông số kỹ thuật 8 hệ thống con"
        >
          ⚙️ Chi tiết hệ thống {showSystemDetails ? '▲' : '▼'}
        </button>
      </div>

      {/* Accordion 8 hệ thống con */}
      {showSystemDetails && (
        <div className={styles.subsystemsAccordion}>
          <div className={styles.subsystemsList}>
            {/* 1. Gateway / WebSocket */}
            <div className={styles.subsystemItem}>
              <div className={styles.subsystemTop}>
                <span className={styles.subsystemLabel}>Gateway / WebSocket</span>
                <span
                  className={`${styles.subsystemIndicator} ${
                    isBackendConnected ? styles.indicatorOk : styles.indicatorErr
                  }`}
                />
              </div>
              <span className={styles.subsystemVal}>
                {isBackendConnected ? 'Đã kết nối' : 'Mất kết nối'}
              </span>
            </div>

            {/* 2. Định vị AMCL */}
            <div className={styles.subsystemItem}>
              <div className={styles.subsystemTop}>
                <span className={styles.subsystemLabel}>Định vị AMCL</span>
                <span
                  className={`${styles.subsystemIndicator} ${
                    status.pose && !status.isDataStale
                      ? styles.indicatorOk
                      : status.isDataStale
                      ? styles.indicatorErr
                      : styles.indicatorWarn
                  }`}
                />
              </div>
              <span className={styles.subsystemVal}>
                {status.pose
                  ? status.isDataStale
                    ? 'Dữ liệu cũ (Stale)'
                    : `X: ${status.pose.x.toFixed(1)}m, Y: ${status.pose.y.toFixed(1)}m`
                  : 'Chờ /amcl_pose'}
              </span>
            </div>

            {/* 3. Bản đồ ROS */}
            <div className={styles.subsystemItem}>
              <div className={styles.subsystemTop}>
                <span className={styles.subsystemLabel}>Bản đồ ROS (/map)</span>
                <span
                  className={`${styles.subsystemIndicator} ${
                    hasValidMap ? styles.indicatorOk : isMapLoading ? styles.indicatorWarn : styles.indicatorErr
                  }`}
                />
              </div>
              <span className={styles.subsystemVal}>
                {hasValidMap
                  ? `Sẵn sàng (${mapData?.metadata.width}x${mapData?.metadata.height})`
                  : isMapLoading
                  ? 'Đang tải bản đồ...'
                  : 'Chưa nhận được'}
              </span>
            </div>

            {/* 4. Nav2 Stack */}
            <div className={styles.subsystemItem}>
              <div className={styles.subsystemTop}>
                <span className={styles.subsystemLabel}>Nav2 Stack</span>
                <span
                  className={`${styles.subsystemIndicator} ${
                    ['IDLE', 'SUCCEEDED'].includes(status.navigationState)
                      ? styles.indicatorOk
                      : ['NAVIGATING', 'ACCEPTED', 'PENDING'].includes(status.navigationState)
                      ? styles.indicatorOk
                      : status.navigationState === 'PAUSED'
                      ? styles.indicatorWarn
                      : styles.indicatorErr
                  }`}
                />
              </div>
              <span className={styles.subsystemVal}>{status.navigationState}</span>
            </div>

            {/* 5. Chế độ điều khiển */}
            <div className={styles.subsystemItem}>
              <div className={styles.subsystemTop}>
                <span className={styles.subsystemLabel}>Chế độ điều khiển</span>
                <span
                  className={`${styles.subsystemIndicator} ${
                    status.controlMode === 'AUTO' ? styles.indicatorOk : styles.indicatorWarn
                  }`}
                />
              </div>
              <span className={styles.subsystemVal}>
                {status.controlMode === 'AUTO'
                  ? 'Tự động (AUTO)'
                  : `Thủ công (${status.manualOperatorId ? 'Admin ' + status.manualOperatorId : 'MANUAL'})`}
              </span>
            </div>

            {/* 6. Chuyến hiện tại */}
            <div className={styles.subsystemItem}>
              <div className={styles.subsystemTop}>
                <span className={styles.subsystemLabel}>Chuyến hiện tại</span>
                <span
                  className={`${styles.subsystemIndicator} ${
                    status.hasActiveTrip ? styles.indicatorOk : styles.indicatorNeutral
                  }`}
                />
              </div>
              <span className={styles.subsystemVal}>
                {status.hasActiveTrip
                  ? status.navigationState === 'PAUSED'
                    ? 'Đang tạm dừng'
                    : 'Đang hoạt động'
                  : 'Không có chuyến'}
              </span>
            </div>

            {/* 7. Pin Robot (chỉ hiện dữ liệu thật) */}
            <div className={styles.subsystemItem}>
              <div className={styles.subsystemTop}>
                <span className={styles.subsystemLabel}>Pin Robot</span>
                <span
                  className={`${styles.subsystemIndicator} ${
                    status.batteryPercent !== null ? styles.indicatorOk : styles.indicatorNeutral
                  }`}
                />
              </div>
              <span className={styles.subsystemVal}>
                {status.batteryPercent !== null
                  ? `${(status.batteryPercent * 100).toFixed(0)}%`
                  : 'Chưa có cảm biến'}
              </span>
            </div>

            {/* 8. Giọng nói ROS (chỉ hiện dữ liệu thật) */}
            <div className={styles.subsystemItem}>
              <div className={styles.subsystemTop}>
                <span className={styles.subsystemLabel}>Giọng nói ROS</span>
                <span
                  className={`${styles.subsystemIndicator} ${
                    status.voiceAvailable ? styles.indicatorOk : styles.indicatorNeutral
                  }`}
                />
              </div>
              <span className={styles.subsystemVal}>
                {status.voiceAvailable ? `Sẵn sàng (${status.voiceState})` : 'Node chưa kết nối'}
              </span>
            </div>
          </div>
        </div>
      )}

      <div className={styles.grid}>
        {/* Cột 1: Bản đồ giám sát (Dominant) + D-pad Overlay + Nhật ký vận hành + Cảnh báo */}
        <div className={styles.leftCol}>
          {/* Bản đồ Dominant */}
          <div className={styles.mapCard}>
            <div className={styles.mapHeader}>
              <div className={styles.mapHeaderLeft}>
                <h2 className={styles.cardTitle}>Bản Đồ Giám Sát Vận Hành</h2>
                <div className={styles.mapTabs} role="tablist">
                  <button
                    type="button"
                    role="tab"
                    aria-selected={mapMode === 'ros'}
                    className={`${styles.mapTabBtn} ${mapMode === 'ros' ? styles.activeTab : ''}`}
                    onClick={() => setMapMode('ros')}
                  >
                    Bản đồ ROS
                  </button>
                  <button
                    type="button"
                    role="tab"
                    aria-selected={mapMode === 'passenger'}
                    className={`${styles.mapTabBtn} ${mapMode === 'passenger' ? styles.activeTab : ''}`}
                    onClick={() => setMapMode('passenger')}
                  >
                    Sơ đồ hành khách
                  </button>
                </div>
              </div>
            </div>

            {controlMsg && <div className={styles.mapBannerError}>{controlMsg}</div>}

            {isOccupiedByOther && (
              <div className={styles.mapBannerWarn}>
                🔒 Quyền điều khiển tay đang thuộc về Admin: <strong>{status.manualOperatorId}</strong>. Bạn chỉ có thể theo dõi hoặc bấm nút &ldquo;Dừng&rdquo; trên bàn điều khiển để dừng khẩn cấp an toàn.
              </div>
            )}

            {!hasConsumer && (
              <div className={styles.mapBannerWarn}>
                ⚠️ Đường lệnh điều khiển tay tới Gazebo (<code>/airport/cmd_vel_manual</code>) chưa có consumer (0 subscriber). Các nút vận tốc được khóa an toàn để tránh bỏ qua bộ phân luồng và các lớp an toàn (collision_monitor / velocity_smoother).
              </div>
            )}

            <div className={styles.mapWrapper}>
              <MapView
                backgroundMode={mapMode}
                robotPose={status.pose}
                destinations={destinations}
                path={path}
                isSelectingCoordinate={isPickingCoord}
                onCoordinateSelect={handleCoordinateSelect}
                onPickingGuide={(msg) => setDestMsg(`ℹ️ ${msg}`)}
                previewPoint={previewPoint}
              />

              {/* D-pad 5 nút phủ góc dưới phải bản đồ (Nền trong suốt, nút 36px) */}
              <div
                className={`${styles.dpadOverlay} ${!canDrive ? styles.dpadDisabled : ''}`}
                title={
                  !canDrive
                    ? (manualLockReason || 'Không thể điều khiển tay lúc này')
                    : 'Bàn điều khiển tay 5 nút (Nhấn giữ để di chuyển, nhả để dừng)'
                }
              >
                <div className={styles.dpadOverlayHeader}>
                  <span className={styles.dpadOverlayTitle}>Điều khiển tay</span>
                  <span
                    className={`${styles.dpadOverlayBadge} ${
                      isDrivingNow
                        ? styles.badgeManualOk
                        : canDrive
                        ? styles.badgeReady
                        : styles.badgeManualLocked
                    }`}
                  >
                    {isDrivingNow ? 'ĐANG LÁI' : canDrive ? 'SẴN SÀNG' : 'KHÓA'}
                  </span>
                </div>
                <div className={styles.dpadRow}>
                  <button
                    type="button"
                    className={styles.dpadBtn}
                    onPointerDown={(e) => {
                      e.currentTarget.setPointerCapture(e.pointerId);
                      startDrive(0.25, 0);
                    }}
                    onPointerUp={(e) => {
                      try {
                        e.currentTarget.releasePointerCapture(e.pointerId);
                      } catch {}
                      stopDrive();
                    }}
                    onPointerCancel={(e) => {
                      try {
                        e.currentTarget.releasePointerCapture(e.pointerId);
                      } catch {}
                      stopDrive();
                    }}
                    onContextMenu={(e) => e.preventDefault()}
                    disabled={!canDrive}
                    title={!canDrive ? (manualLockReason || 'Không thể điều khiển tay') : 'Tiến thẳng (0.25 m/s)'}
                    aria-label="Tiến thẳng"
                  >
                    ▲
                  </button>
                </div>
                <div className={styles.dpadRow}>
                  <button
                    type="button"
                    className={styles.dpadBtn}
                    onPointerDown={(e) => {
                      e.currentTarget.setPointerCapture(e.pointerId);
                      startDrive(0, 0.4);
                    }}
                    onPointerUp={(e) => {
                      try {
                        e.currentTarget.releasePointerCapture(e.pointerId);
                      } catch {}
                      stopDrive();
                    }}
                    onPointerCancel={(e) => {
                      try {
                        e.currentTarget.releasePointerCapture(e.pointerId);
                      } catch {}
                      stopDrive();
                    }}
                    onContextMenu={(e) => e.preventDefault()}
                    disabled={!canDrive}
                    title={!canDrive ? (manualLockReason || 'Không thể điều khiển tay') : 'Quay trái (0.4 rad/s)'}
                    aria-label="Quay trái"
                  >
                    ◀
                  </button>
                  <button
                    type="button"
                    className={`${styles.dpadBtn} ${styles.stopBtn}`}
                    onClick={() => {
                      stopDrive();
                      sendManualVelocity(0, 0, 0, undefined);
                    }}
                    title="Dừng robot ngay lập tức"
                    aria-label="Dừng di chuyển"
                  >
                    Dừng
                  </button>
                  <button
                    type="button"
                    className={styles.dpadBtn}
                    onPointerDown={(e) => {
                      e.currentTarget.setPointerCapture(e.pointerId);
                      startDrive(0, -0.4);
                    }}
                    onPointerUp={(e) => {
                      try {
                        e.currentTarget.releasePointerCapture(e.pointerId);
                      } catch {}
                      stopDrive();
                    }}
                    onPointerCancel={(e) => {
                      try {
                        e.currentTarget.releasePointerCapture(e.pointerId);
                      } catch {}
                      stopDrive();
                    }}
                    onContextMenu={(e) => e.preventDefault()}
                    disabled={!canDrive}
                    title={!canDrive ? (manualLockReason || 'Không thể điều khiển tay') : 'Quay phải (-0.4 rad/s)'}
                    aria-label="Quay phải"
                  >
                    ▶
                  </button>
                </div>
                <div className={styles.dpadRow}>
                  <button
                    type="button"
                    className={styles.dpadBtn}
                    onPointerDown={(e) => {
                      e.currentTarget.setPointerCapture(e.pointerId);
                      startDrive(-0.2, 0);
                    }}
                    onPointerUp={(e) => {
                      try {
                        e.currentTarget.releasePointerCapture(e.pointerId);
                      } catch {}
                      stopDrive();
                    }}
                    onPointerCancel={(e) => {
                      try {
                        e.currentTarget.releasePointerCapture(e.pointerId);
                      } catch {}
                      stopDrive();
                    }}
                    onContextMenu={(e) => e.preventDefault()}
                    disabled={!canDrive}
                    title={!canDrive ? (manualLockReason || 'Không thể điều khiển tay') : 'Lùi lại (-0.2 m/s)'}
                    aria-label="Lùi lại"
                  >
                    ▼
                  </button>
                </div>
              </div>
            </div>
          </div>

          {/* Bảng Nhật ký vận hành Admin (RAM circular buffer 100 sự kiện) */}
          <div className={styles.card}>
            <div className={styles.cardHeader}>
              <h2 className={styles.cardTitle}>Nhật Ký Vận Hành Admin ({events.length}/100)</h2>
              <button
                type="button"
                className={styles.refreshEventsBtn}
                onClick={() => refreshEvents()}
                title="Tải lại danh sách sự kiện từ bộ đệm RAM backend"
              >
                🔄 Làm mới
              </button>
            </div>
            <p className={styles.eventLogSubtitle}>
              Ghi nhận trong bộ đệm RAM từ lúc khởi động
              {eventsStartedAt
                ? `: ${new Date(eventsStartedAt).toLocaleTimeString('vi-VN', { hour12: false })} ngày ${new Date(
                    eventsStartedAt
                  ).toLocaleDateString('vi-VN')}`
                : ''}
              . Tự động đồng bộ thời gian thực qua WebSocket.
            </p>

            {sortedEvents.length === 0 ? (
              <p className={styles.helpText}>Chưa ghi nhận sự kiện nào kể từ khi khởi động hệ thống.</p>
            ) : (
              <div className={styles.eventLogList}>
                {sortedEvents.map((evt) => {
                  const levelClass =
                    evt.level === 'SUCCESS'
                      ? styles.evtSuccess
                      : evt.level === 'WARN'
                      ? styles.evtWarn
                      : evt.level === 'ERROR'
                      ? styles.evtError
                      : styles.evtInfo;

                  const catLabel =
                    evt.category === 'SYSTEM'
                      ? 'Hệ thống'
                      : evt.category === 'CONNECTION'
                      ? 'Kết nối'
                      : evt.category === 'NAVIGATION'
                      ? 'Điều hướng'
                      : evt.category === 'CONTROL'
                      ? 'Điều khiển'
                      : evt.category;

                  return (
                    <div key={evt.id} className={`${styles.eventLogItem} ${levelClass}`}>
                      <span className={styles.eventTime}>
                        {new Date(evt.timestamp).toLocaleTimeString('vi-VN', { hour12: false })}
                      </span>
                      <span className={styles.eventCat}>{catLabel}</span>
                      <span className={styles.eventMsg}>{evt.message}</span>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Bảng chẩn đoán cảnh báo */}
          <div className={styles.card}>
            <h2 className={styles.cardTitle}>Hệ Thống Cảnh Báo (/airport/alerts)</h2>
            {alerts.length === 0 ? (
              <p className={styles.helpText}>Hiện không có cảnh báo nào từ các node ROS.</p>
            ) : (
              <div className={styles.alertList}>
                {alerts.map((al, idx) => (
                  <div
                    key={idx}
                    className={`${styles.alertItem} ${al.level === 0 ? styles.ok : styles.warn}`}
                  >
                    <div className={styles.alertTop}>
                      <strong>{al.name}</strong>
                      <span className={styles.hwId}>[{al.hardware_id || 'system'}]</span>
                    </div>
                    <p className={styles.alertMsg}>{al.message}</p>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Cột 2: Quản lý Nav2 & Điểm đến */}
        <div className={styles.rightCol}>
          {/* Quản lý & Điều khiển dẫn đường Nav2 */}
          <div className={styles.card}>
            <div className={styles.cardHeader}>
              <h2 className={styles.cardTitle}>Giám Sát & Điều Khiển Dẫn Đường (Nav2)</h2>
              <span className={`${styles.navStateBadge} ${styles[status.navigationState.toLowerCase()] || ''}`}>
                {status.navigationState}
              </span>
            </div>

            {isNavigating ? (
              <div className={styles.activeNavBox}>
                <div className={styles.activeNavRow}>
                  <span>Trạng thái:</span>
                  <strong>{status.message || status.navigationState}</strong>
                </div>
                {status.distanceRemaining !== null && status.distanceRemaining !== undefined && (
                  <div className={styles.activeNavRow}>
                    <span>Khoảng cách còn lại:</span>
                    <strong>{status.distanceRemaining.toFixed(1)} m</strong>
                  </div>
                )}
                {status.hasActiveTrip && (
                  <div className={styles.activeNavRow}>
                    <span>Chuyến dẫn đường:</span>
                    <span>Đang hoạt động</span>
                  </div>
                )}
                <div className={styles.navActions}>
                  {isPaused ? (
                    <button
                      type="button"
                      className={styles.adminResumeBtn}
                      onClick={handleAdminResume}
                      disabled={isNavSubmitting || isManual || !status.isConnected}
                      title="Tiếp tục dẫn đường tới điểm đến hiện tại"
                    >
                      {isNavSubmitting ? 'Đang gửi lệnh tiếp tục...' : 'TIẾP TỤC DẪN ĐƯỜNG'}
                    </button>
                  ) : (
                    <button
                      type="button"
                      className={styles.adminPauseBtn}
                      onClick={handleAdminPause}
                      disabled={isNavSubmitting || isCanceling || isPausing || status.navigationState === 'PENDING'}
                      title="Tạm dừng robot tại vị trí hiện tại"
                    >
                      {isPausing ? 'ĐANG TẠM DỪNG...' : 'TẠM DỪNG'}
                    </button>
                  )}
                  <button
                    type="button"
                    className={styles.adminCancelBtn}
                    onClick={handleAdminCancel}
                    disabled={isNavSubmitting || isCanceling || isPausing}
                    title="Hủy hoàn toàn chuyến dẫn đường"
                  >
                    {isCanceling || isNavSubmitting ? 'Đang gửi lệnh hủy...' : 'HỦY CHUYẾN ĐI'}
                  </button>
                </div>
              </div>
            ) : (
              <div className={styles.navStartSection}>
                {destinations.length === 0 ? (
                  <p className={styles.helpText}>
                    Chưa có điểm đến hợp lệ nào trên bản đồ hiện tại. Vui lòng thêm điểm đến bên dưới để bắt đầu.
                  </p>
                ) : (
                  <div className={styles.formGroup}>
                    <label htmlFor="adminNavDestSelect">Chọn điểm đến:</label>
                    <select
                      id="adminNavDestSelect"
                      className={styles.selectInput}
                      value={selectedNavDestId}
                      onChange={(e) => setSelectedNavDestId(e.target.value)}
                      disabled={isNavigating || isManual}
                    >
                      <option value="" disabled>-- Vui lòng chọn một điểm đến --</option>
                      {destinations.map((d) => (
                        <option key={d.id} value={d.id}>
                          {d.name} ({d.id}) — [{d.pose.position.x.toFixed(1)}, {d.pose.position.y.toFixed(1)}]
                        </option>
                      ))}
                    </select>
                  </div>
                )}

                {isManual && (
                  <div className={styles.warnText}>
                    ⚠️ Robot đang ở chế độ MANUAL. Vui lòng tắt thủ công trước khi kích hoạt Nav2.
                  </div>
                )}

                {!readinessCheck.ready && (
                  <div className={styles.blockedNavNote}>
                    <span>ℹ️</span>
                    <div>
                      <strong>Chưa thể bắt đầu:</strong> {readinessCheck.reason}
                    </div>
                  </div>
                )}
                {readinessCheck.ready && !selectedNavDestId && destinations.length > 0 && (
                  <div className={styles.blockedNavNote} style={{ background: '#EFF6FF', borderColor: '#BFDBFE', color: '#1E40AF' }}>
                    <span>ℹ️</span>
                    <div>
                      <strong>Sẵn sàng:</strong> Vui lòng chọn một điểm đến trong danh sách để bắt đầu dẫn đường.
                    </div>
                  </div>
                )}

                <div className={styles.navActions}>
                  <button
                    type="button"
                    className={styles.adminStartBtn}
                    onClick={handleAdminStart}
                    disabled={
                      !selectedNavDestId ||
                      destinations.length === 0 ||
                      isNavigating ||
                      isManual ||
                      !status.isConnected ||
                      isNavSubmitting
                    }
                    title={
                      !readinessCheck.ready
                        ? `Khóa an toàn: ${readinessCheck.reason}`
                        : !selectedNavDestId
                        ? 'Vui lòng chọn một điểm đến'
                        : isNavSubmitting
                        ? 'Đang gửi lệnh...'
                        : 'Kích hoạt nhiệm vụ dẫn đường Nav2'
                    }
                  >
                    {isNavSubmitting ? 'Đang gửi lệnh...' : 'BẮT ĐẦU DẪN ĐƯỜNG'}
                  </button>
                </div>
              </div>
            )}

            {navActionMsg && <div className={styles.feedbackMsg}>{navActionMsg}</div>}
          </div>

          {/* Form thêm/sửa điểm đến */}
          <div className={styles.card}>
            <div className={styles.cardHeader}>
              <h2 className={styles.cardTitle}>Thêm / Cập Nhật Điểm Đến</h2>
              {previewPoint && (
                <span className={styles.draftBadge}>
                  📍 Điểm nháp ({previewPoint.x.toFixed(1)}, {previewPoint.y.toFixed(1)})
                </span>
              )}
            </div>
            <form onSubmit={handleSaveDestination} className={styles.destForm}>
              <div className={styles.formRow}>
                <div className={styles.formGroup}>
                  <label>Mã định danh (ID):</label>
                  <input
                    type="text"
                    value={destId}
                    onChange={(e) => setDestId(e.target.value)}
                    placeholder="vd: gate_a3"
                    required
                  />
                </div>
                <div className={styles.formGroup}>
                  <label>Tên điểm đến:</label>
                  <input
                    type="text"
                    value={destName}
                    onChange={(e) => setDestName(e.target.value)}
                    placeholder="vd: Cổng khởi hành số 3"
                    required
                  />
                </div>
              </div>
              <div className={styles.coordGrid}>
                <div className={styles.formGroup}>
                  <label>Tọa độ X (mét):</label>
                  <input
                    type="number"
                    step="0.01"
                    value={destX}
                    onChange={(e) => setDestX(e.target.value)}
                    placeholder="vd: 0.25"
                    required
                  />
                </div>
                <div className={styles.formGroup}>
                  <label>Tọa độ Y (mét):</label>
                  <input
                    type="number"
                    step="0.01"
                    value={destY}
                    onChange={(e) => setDestY(e.target.value)}
                    placeholder="vd: 1.45"
                    required
                  />
                </div>
                <div className={styles.formGroup}>
                  <label>Góc Yaw (độ):</label>
                  <input
                    type="number"
                    step="1"
                    value={destYaw}
                    onChange={(e) => setDestYaw(e.target.value)}
                    placeholder="vd: 90"
                  />
                </div>
              </div>
              <div className={styles.destToolRow}>
                <button
                  type="button"
                  className={`${styles.toolBtn} ${isPickingCoord ? styles.activeToolBtn : ''}`}
                  onClick={handleTogglePicking}
                  disabled={!hasValidMap}
                  title={!hasValidMap ? 'Cần có metadata bản đồ ROS hợp lệ' : undefined}
                >
                  {isPickingCoord ? '✖ Hủy chọn vị trí & hướng' : '📍 Chọn vị trí & hướng'}
                </button>
                <button
                  type="button"
                  className={styles.toolBtn}
                  onClick={handleCopyYaml}
                  title="Sao chép cấu hình YAML cho config/destinations.yaml"
                >
                  📋 Sao chép cấu hình YAML
                </button>
              </div>
              {copySuccessMsg && <div className={styles.copySuccessMsg}>{copySuccessMsg}</div>}
              {destMsg && <div className={styles.feedbackMsg}>{destMsg}</div>}
              <button
                type="submit"
                className={styles.submitBtn}
                disabled={isSavingDest || !hasValidMap}
                title={!hasValidMap ? 'Cần có metadata bản đồ ROS hợp lệ' : undefined}
              >
                {isSavingDest ? 'Đang lưu...' : 'Lưu điểm đến'}
              </button>
            </form>
          </div>

          {/* Card Quản lý danh sách điểm đến đã lưu */}
          <div className={styles.card}>
            <div className={styles.cardHeader}>
              <h2 className={styles.cardTitle}>Danh Sách Điểm Đến ({destinations.length})</h2>
            </div>
            {deleteSuccessMsg && <div className={styles.copySuccessMsg}>{deleteSuccessMsg}</div>}
            {deleteActionError && <div className={styles.errorText}>{deleteActionError}</div>}
            {destinations.length === 0 ? (
              <p className={styles.helpText}>Chưa có điểm đến nào trong hệ thống. Hãy thêm điểm đến ở form trên.</p>
            ) : (
              <div className={styles.destManageList}>
                {destinations.map((d) => (
                  <div key={d.id} className={styles.destManageItem}>
                    <div className={styles.destManageInfo}>
                      <span className={styles.destManageName}>{d.name}</span>
                      <span className={styles.destManageId}>{d.id}</span>
                      <span className={styles.destManageCoords}>
                        ({d.pose.position.x.toFixed(1)}m, {d.pose.position.y.toFixed(1)}m)
                      </span>
                    </div>
                    <div className={styles.destManageActions}>
                      <button
                        type="button"
                        className={styles.destEditBtn}
                        onClick={() => handleLoadToForm(d)}
                        title="Nạp vào form để xem hoặc sửa"
                      >
                        Sửa
                      </button>
                      <button
                        type="button"
                        className={styles.destDeleteBtn}
                        onClick={() => handleRequestDelete(d)}
                        title={`Xóa điểm đến '${d.name}'`}
                        disabled={isNavigating && status.destinationId === d.id}
                      >
                        Xóa
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {showCopyModal && (
        <div className={styles.modalOverlay} onClick={() => setShowCopyModal(false)}>
          <div className={styles.modalContent} onClick={(e) => e.stopPropagation()}>
            <div className={styles.modalHeader}>
              <h3>Cấu Hình YAML Điểm Đến</h3>
              <button
                type="button"
                className={styles.closeBtn}
                onClick={() => setShowCopyModal(false)}
              >
                ✕
              </button>
            </div>
            <p className={styles.modalHelp}>
              Trình duyệt không cho phép truy cập Clipboard tự động. Vui lòng chọn và sao chép đoạn mã YAML bên dưới rồi dán vào <code>config/destinations.yaml</code> trên máy Host:
            </p>
            <textarea
              className={styles.yamlTextarea}
              rows={12}
              readOnly
              value={copiedYamlSnippet}
              onFocus={(e) => e.target.select()}
            />
            <div className={styles.modalActions}>
              <button
                type="button"
                className={styles.toolBtn}
                onClick={() => setShowCopyModal(false)}
              >
                Đóng
              </button>
            </div>
          </div>
        </div>
      )}

      {destToDelete && (
        <div className={styles.modalOverlay} onClick={() => !isDeletingDest && setDestToDelete(null)}>
          <div className={styles.modalContent} onClick={(e) => e.stopPropagation()}>
            <div className={styles.modalHeader}>
              <h3>Xác Nhận Xóa Điểm Đến</h3>
              <button
                type="button"
                className={styles.closeBtn}
                onClick={() => !isDeletingDest && setDestToDelete(null)}
                disabled={isDeletingDest}
              >
                ✕
              </button>
            </div>
            <p className={styles.modalHelp}>
              Xóa điểm đến <strong>&ldquo;{destToDelete.name}&rdquo;</strong> (<code>{destToDelete.id}</code>)?
            </p>
            <p className={styles.modalSubHelp}>
              Điểm này sẽ bị xóa khỏi tệp lưu trữ <code>data/destinations.yaml</code> và tự động đồng bộ gỡ bỏ trên tất cả các tab đang mở.
            </p>
            {deleteModalError && (
              <div className={styles.modalError}>{deleteModalError}</div>
            )}
            <div className={styles.modalConfirmActions}>
              <button
                type="button"
                className={styles.cancelModalBtn}
                onClick={() => setDestToDelete(null)}
                disabled={isDeletingDest}
              >
                Hủy
              </button>
              <button
                type="button"
                className={styles.confirmDeleteBtn}
                onClick={handleConfirmDelete}
                disabled={isDeletingDest}
              >
                {isDeletingDest ? 'Đang xóa...' : 'Xác Nhận Xóa'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
