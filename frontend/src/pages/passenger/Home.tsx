import React, { useState } from 'react';
import { useRobot } from '../../contexts/RobotContext';
import { MapView } from '../../components/MapView/MapView';
import { VoicePanel } from '../../components/VoicePanel/VoicePanel';
import styles from './Home.module.css';

export default function PassengerHome() {
  const {
    status,
    destinations,
    path,
    startNavigation,
    cancelNavigation,
  } = useRobot();

  const [selectedDestId, setSelectedDestId] = useState<string>('');
  const [actionError, setActionError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const selectedDest = destinations.find((d) => d.id === selectedDestId);
  const isNavigating = status.navigationState === 'NAVIGATING' || status.navigationState === 'ACCEPTED';
  const isCanceling = status.navigationState === 'CANCELING';

  const handleStart = async () => {
    if (!selectedDestId) return;
    setActionError(null);
    setIsSubmitting(true);
    const res = await startNavigation(selectedDestId);
    setIsSubmitting(false);
    if (!res.success) {
      setActionError(res.message || 'Không thể bắt đầu chuyến dẫn đường.');
    }
  };

  const handleCancel = async () => {
    setActionError(null);
    setIsSubmitting(true);
    const res = await cancelNavigation();
    setIsSubmitting(false);
    if (!res.success) {
      setActionError(res.message || 'Không thể hủy chuyến.');
    }
  };

  return (
    <div className={styles.container}>
      {/* Cảnh báo mất kết nối nếu có */}
      {!status.isConnected && (
        <div className={styles.alertBanner}>
          ⚠️ Chưa kết nối với Robot ROS 2. Vui lòng kiểm tra Docker hoặc mạng nội bộ.
        </div>
      )}

      {status.controlMode === 'MANUAL' && (
        <div className={styles.manualNotice}>
          ℹ️ Robot hiện đang được điều khiển thủ công bởi Quản trị viên. Chức năng tự động tạm khóa.
        </div>
      )}

      <div className={styles.mainGrid}>
        {/* Cột trái: Chọn điểm đến & Điều khiển chuyến */}
        <div className={styles.sidebar}>
          <div className={styles.card}>
            <h2 className={styles.cardTitle}>1. Chọn Điểm Đến</h2>
            {destinations.length === 0 ? (
              <p className={styles.emptyText}>Chưa có điểm đến nào được cấu hình trong hệ thống.</p>
            ) : (
              <div className={styles.destList}>
                {destinations.map((dest) => (
                  <button
                    key={dest.id}
                    className={`${styles.destItem} ${selectedDestId === dest.id ? styles.selected : ''}`}
                    onClick={() => {
                      if (!isNavigating) setSelectedDestId(dest.id);
                    }}
                    disabled={isNavigating}
                  >
                    <span className={styles.destName}>{dest.name}</span>
                    <span className={styles.destCoord}>
                      ({dest.pose.position.x}m, {dest.pose.position.y}m)
                    </span>
                  </button>
                ))}
              </div>
            )}

            {/* Trạng thái nhiệm vụ */}
            <div className={styles.statusSection}>
              <h3 className={styles.subTitle}>Trạng thái chuyến đi</h3>
              <div className={styles.statusBox}>
                <div className={styles.statusRow}>
                  <span>Trạng thái:</span>
                  <strong className={styles[status.navigationState.toLowerCase()]}>
                    {status.navigationState}
                  </strong>
                </div>
                {status.message && <p className={styles.statusMessage}>{status.message}</p>}
              </div>

              {actionError && <div className={styles.errorText}>{actionError}</div>}

              {/* Nút thao tác */}
              <div className={styles.actions}>
                {!isNavigating ? (
                  <button
                    className={styles.primaryBtn}
                    onClick={handleStart}
                    disabled={!selectedDestId || isSubmitting || status.controlMode === 'MANUAL' || !status.isConnected}
                  >
                    {isSubmitting ? 'Đang gửi lệnh...' : 'Bắt Đầu Dẫn Đường'}
                  </button>
                ) : (
                  <button
                    className={styles.cancelBtn}
                    onClick={handleCancel}
                    disabled={isCanceling || isSubmitting}
                  >
                    {isCanceling ? 'Đang dừng và hủy...' : 'Hủy Chuyến Đi'}
                  </button>
                )}
              </div>
            </div>
          </div>

          {/* Bảng tương tác giọng nói */}
          <VoicePanel />
        </div>

        {/* Cột phải: Bản đồ hiển thị */}
        <div className={styles.mapArea}>
          <div className={styles.mapHeader}>
            <span className={styles.mapTitle}>Sơ đồ vị trí & Đường đi</span>
            <span className={styles.mapHelp}>Kéo chuột để di chuyển • Lăn chuột để phóng to</span>
          </div>
          <div className={styles.mapWrapper}>
            <MapView
              robotPose={status.pose}
              destinations={destinations}
              selectedDestinationId={selectedDestId}
              path={path}
              onDestinationSelect={(id) => {
                if (!isNavigating) setSelectedDestId(id);
              }}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
