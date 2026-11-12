import React, { useState, useEffect, useRef } from 'react';
import { useRobot } from '../../contexts/RobotContext';
import { Destination } from '../../types';
import { MapView } from '../../components/MapView/MapView';
import styles from './Dashboard.module.css';

export default function AdminDashboard() {
  const {
    status,
    destinations,
    alerts,
    path,
    setManualControl,
    sendManualVelocity,
    upsertDestination,
  } = useRobot();

  const [isSwitchingMode, setIsSwitchingMode] = useState(false);
  const [controlMsg, setControlMsg] = useState<string | null>(null);

  // Form thêm / sửa điểm đến
  const [destId, setDestId] = useState('');
  const [destName, setDestName] = useState('');
  const [destX, setDestX] = useState('0.0');
  const [destY, setDestY] = useState('0.0');
  const [destYaw, setDestYaw] = useState('0');
  const [destMsg, setDestMsg] = useState<string | null>(null);

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

    const x = parseFloat(destX) || 0.0;
    const y = parseFloat(destY) || 0.0;
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
    if (res.success) {
      setDestMsg(`✅ ${res.message || 'Đã lưu điểm đến thành công.'}`);
      setDestId('');
      setDestName('');
    } else {
      setDestMsg(`❌ ${res.message || 'Lỗi khi lưu điểm đến.'}`);
    }
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

          {/* Form thêm/sửa điểm đến */}
          <div className={styles.card}>
            <h2 className={styles.cardTitle}>Thêm / Cập Nhật Điểm Đến</h2>
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
              {destMsg && <div className={styles.feedbackMsg}>{destMsg}</div>}
              <button type="submit" className={styles.submitBtn}>
                Lưu Điểm Đến (ROS Upsert)
              </button>
            </form>
          </div>
        </div>

        {/* Cột 2: Bản đồ và Cảnh báo */}
        <div className={styles.rightCol}>
          {/* Bản đồ */}
          <div className={styles.card} style={{ padding: 0, overflow: 'hidden' }}>
            <div className={styles.mapHeader}>
              <span className={styles.cardTitle} style={{ margin: 0, padding: '12px 16px' }}>
                Bản Đồ Giám Sát Vận Hành
              </span>
            </div>
            <div style={{ height: '360px' }}>
              <MapView
                robotPose={status.pose}
                destinations={destinations}
                path={path}
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
    </div>
  );
}
