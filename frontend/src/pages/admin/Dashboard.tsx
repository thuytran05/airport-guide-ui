import React, { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import { useRobot } from '../../contexts/RobotContext';
import { Destination } from '../../types';
import { MapView, MapBackgroundMode } from '../../components/MapView/MapView';
import styles from './Dashboard.module.css';

export default function AdminDashboard() {
  const {
    status,
    destinations,
    alerts,
    path,
    mapData,
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

  // Form thêm / sửa điểm đến
  const [destId, setDestId] = useState('');
  const [destName, setDestName] = useState('');
  const [destX, setDestX] = useState('0.0');
  const [destY, setDestY] = useState('0.0');
  const [destYaw, setDestYaw] = useState('0');
  const [destMsg, setDestMsg] = useState<string | null>(null);
  const [isSavingDest, setIsSavingDest] = useState(false);

  // Quản lý xóa điểm đến
  const [destToDelete, setDestToDelete] = useState<Destination | null>(null);
  const [isDeletingDest, setIsDeletingDest] = useState(false);
  const [deleteModalError, setDeleteModalError] = useState<string | null>(null);
  const [deleteActionError, setDeleteActionError] = useState<string | null>(null);
  const [deleteSuccessMsg, setDeleteSuccessMsg] = useState<string | null>(null);

  // Chế độ chọn tọa độ trên bản đồ ROS và sao chép YAML
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

  const handleCoordinateSelect = useCallback((coords: { x: number; y: number }) => {
    setDestX(coords.x.toFixed(2));
    setDestY(coords.y.toFixed(2));
    setIsPickingCoord(false);
    setDestMsg(`📍 Đã lấy tọa độ từ bản đồ: X=${coords.x.toFixed(2)}m, Y=${coords.y.toFixed(2)}m`);
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
      setDestMsg('ℹ️ Chế độ chọn tọa độ: Click một điểm trên Bản đồ ROS để lấy X/Y.');
    } else {
      setIsPickingCoord(false);
      setDestMsg(null);
    }
  };

  // Preview Pin xem trước trên bản đồ (Điểm nháp)
  const previewPoint = useMemo(() => {
    const x = parseFloat(destX);
    const y = parseFloat(destY);
    const yawDeg = parseFloat(destYaw);
    if (isNaN(x) || isNaN(y)) return null;
    return {
      x,
      y,
      yawDeg: isNaN(yawDeg) ? 0 : yawDeg,
    };
  }, [destX, destY, destYaw]);

  const generateYamlSnippet = () => {
    const id = destId.trim() || 'destination_id';
    const name = destName.trim() || 'Tên điểm đến';
    const x = parseFloat(destX) || 0.0;
    const y = parseFloat(destY) || 0.0;
    const yawDeg = parseFloat(destYaw) || 0.0;
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

  // Vòng lặp gửi vận tốc 10Hz khi giữ nút điều khiển
  const driveTimerRef = useRef<any>(null);
  const activeVelRef = useRef<{ lin: number; ang: number }>({ lin: 0, ang: 0 });

  const isManual = status.controlMode === 'MANUAL';

  const handleToggleManual = async () => {
    setIsSwitchingMode(true);
    setControlMsg(null);
    const targetMode = !isManual;
    const res = await setManualControl(targetMode);
    setIsSwitchingMode(false);
    if (!res.success) {
      setControlMsg(res.message || 'Không thể đổi chế độ điều khiển.');
    }
  };

  const startDrive = (lin: number, ang: number) => {
    if (!isManual) return;
    stopDrive();
    activeVelRef.current = { lin, ang };
    // Gửi ngay lập tức tick đầu tiên
    sendManualVelocity(lin, ang);
    // Gửi chu kỳ 10Hz (100ms) trong khi còn giữ nút
    driveTimerRef.current = setInterval(() => {
      sendManualVelocity(activeVelRef.current.lin, activeVelRef.current.ang);
    }, 100);
  };

  const stopDrive = () => {
    if (driveTimerRef.current) {
      clearInterval(driveTimerRef.current);
      driveTimerRef.current = null;
    }
    activeVelRef.current = { lin: 0, ang: 0 };
    if (isManual) {
      sendManualVelocity(0, 0);
    }
  };

  useEffect(() => {
    // Watchdog an toàn: Dừng robot nếu tab trình duyệt mất focus hoặc unmount
    const handleBlur = () => stopDrive();
    window.addEventListener('blur', handleBlur);
    return () => {
      stopDrive();
      window.removeEventListener('blur', handleBlur);
    };
  }, [isManual]);

  const handleSaveDestination = async (e: React.FormEvent) => {
    e.preventDefault();
    setDestMsg(null);
    if (!destId.trim() || !destName.trim()) {
      setDestMsg('Vui lòng nhập ID và Tên điểm đến.');
      return;
    }

    const x = parseFloat(destX);
    const y = parseFloat(destY);
    if (isNaN(x) || isNaN(y)) {
      setDestMsg('Tọa độ X và Y phải là số thực hợp lệ.');
      return;
    }

    setIsSavingDest(true);
    const yawDeg = parseFloat(destYaw) || 0.0;
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
    } else {
      setDestMsg(`❌ ${res.message || 'Lỗi khi lưu điểm đến.'}`);
    }
  };

  const isNavigating =
    status.navigationState === 'NAVIGATING' ||
    status.navigationState === 'ACCEPTED' ||
    status.navigationState === 'PENDING' ||
    status.navigationState === 'PAUSING' ||
    status.navigationState === 'PAUSED' ||
    status.navigationState === 'CANCELING';
  const isCanceling = status.navigationState === 'CANCELING';
  const isPausing = status.navigationState === 'PAUSING';
  const isPaused = status.navigationState === 'PAUSED';

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
      {/* Hàng trạng thái nhanh */}
      <div className={styles.statsRow}>
        <div className={styles.statBox}>
          <span className={styles.statLabel}>Chế độ điều khiển</span>
          <strong className={`${styles.statValue} ${styles[status.controlMode.toLowerCase()]}`}>
            {status.controlMode}
          </strong>
        </div>
        <div className={styles.statBox}>
          <span className={styles.statLabel}>Dung lượng Pin</span>
          <strong className={styles.statValue}>
            {status.batteryPercent !== null
              ? `${(status.batteryPercent * 100).toFixed(0)}%`
              : 'Chưa có dữ liệu'}
          </strong>
        </div>
        <div className={styles.statBox}>
          <span className={styles.statLabel}>Tọa độ Robot (Map)</span>
          <strong className={styles.statValue}>
            {status.pose
              ? `X: ${status.pose.x.toFixed(2)}m, Y: ${status.pose.y.toFixed(2)}m`
              : 'Chưa có dữ liệu'}
          </strong>
        </div>
        <div className={styles.statBox}>
          <span className={styles.statLabel}>Trạng thái Điều hướng</span>
          <strong className={styles.statValue}>{status.navigationState}</strong>
        </div>
      </div>

      <div className={styles.grid}>
        {/* Cột 1: Điều khiển thủ công & Điểm đến */}
        <div className={styles.leftCol}>
          {/* Bảng điều khiển thủ công */}
          <div className={styles.card}>
            <div className={styles.cardHeader}>
              <h2 className={styles.cardTitle}>Điều Khiển Vận Tốc Thủ Công</h2>
              <button
                className={`${styles.modeBtn} ${isManual ? styles.manualActive : ''}`}
                onClick={handleToggleManual}
                disabled={isSwitchingMode}
              >
                {isSwitchingMode
                  ? 'Đang chuyển...'
                  : isManual
                  ? 'TẮT THỦ CÔNG (VỀ AUTO)'
                  : 'BẬT THỦ CÔNG (MANUAL)'}
              </button>
            </div>

            {controlMsg && <div className={styles.errorText}>{controlMsg}</div>}

            <p className={styles.helpText}>
              {isManual
                ? 'Nhấn và giữ chuột hoặc phím điều hướng để di chuyển. Nhả nút sẽ dừng ngay lập tức.'
                : 'Cần bấm "BẬT THỦ CÔNG" để kích hoạt bàn điều khiển bên dưới.'}
            </p>

            <div className={`${styles.dpad} ${!isManual ? styles.disabled : ''}`}>
              <div className={styles.dpadRow}>
                <button
                  className={styles.dpadBtn}
                  onMouseDown={() => startDrive(0.25, 0)}
                  onMouseUp={stopDrive}
                  onMouseLeave={stopDrive}
                  disabled={!isManual}
                  title="Tiến thẳng (0.25 m/s)"
                >
                  ▲
                </button>
              </div>
              <div className={styles.dpadRow}>
                <button
                  className={styles.dpadBtn}
                  onMouseDown={() => startDrive(0, 0.4)}
                  onMouseUp={stopDrive}
                  onMouseLeave={stopDrive}
                  disabled={!isManual}
                  title="Quay trái (0.4 rad/s)"
                >
                  ◀
                </button>
                <button
                  className={`${styles.dpadBtn} ${styles.stopBtn}`}
                  onClick={stopDrive}
                  disabled={!isManual}
                  title="Dừng khẩn cấp"
                >
                  ■
                </button>
                <button
                  className={styles.dpadBtn}
                  onMouseDown={() => startDrive(0, -0.4)}
                  onMouseUp={stopDrive}
                  onMouseLeave={stopDrive}
                  disabled={!isManual}
                  title="Quay phải (-0.4 rad/s)"
                >
                  ▶
                </button>
              </div>
              <div className={styles.dpadRow}>
                <button
                  className={styles.dpadBtn}
                  onMouseDown={() => startDrive(-0.2, 0)}
                  onMouseUp={stopDrive}
                  onMouseLeave={stopDrive}
                  disabled={!isManual}
                  title="Lùi lại (-0.2 m/s)"
                >
                  ▼
                </button>
              </div>
            </div>
          </div>

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
              <div className={styles.formRow}>
                <div className={styles.formGroup}>
                  <label>Tọa độ X (mét):</label>
                  <input
                    type="number"
                    step="0.1"
                    value={destX}
                    onChange={(e) => setDestX(e.target.value)}
                    required
                  />
                </div>
                <div className={styles.formGroup}>
                  <label>Tọa độ Y (mét):</label>
                  <input
                    type="number"
                    step="0.1"
                    value={destY}
                    onChange={(e) => setDestY(e.target.value)}
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
                  {isPickingCoord ? '✖ Hủy chọn tọa độ' : '📍 Chọn tọa độ trên bản đồ'}
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
                {isSavingDest ? 'Đang lưu điểm đến...' : 'Lưu Điểm Đến (Lưu Bền Vững)'}
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

        {/* Cột 2: Bản đồ và Cảnh báo */}
        <div className={styles.rightCol}>
          {/* Bản đồ */}
          <div className={styles.card} style={{ padding: 0, overflow: 'hidden' }}>
            <div className={styles.mapHeader}>
              <span className={styles.cardTitle}>
                Bản Đồ Giám Sát Vận Hành
              </span>
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
            <div style={{ height: '360px' }}>
              <MapView
                backgroundMode={mapMode}
                robotPose={status.pose}
                destinations={destinations}
                path={path}
                isSelectingCoordinate={isPickingCoord}
                onCoordinateSelect={handleCoordinateSelect}
                previewPoint={previewPoint}
              />
            </div>
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
