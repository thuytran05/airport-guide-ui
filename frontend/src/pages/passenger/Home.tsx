import React, { useState, useEffect } from 'react';
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

  // Nếu điểm đang chọn bị xóa khỏi hệ thống, bỏ lựa chọn đó và khóa nút "Bắt đầu dẫn đường"
  useEffect(() => {
    if (selectedDestId && !destinations.some((d) => d.id === selectedDestId)) {
      setSelectedDestId('');
    }
  }, [destinations, selectedDestId]);

  const selectedDest = destinations.find((d) => d.id === selectedDestId);
  const isNavigating =
    status.navigationState === 'NAVIGATING' ||
    status.navigationState === 'ACCEPTED' ||
    status.navigationState === 'PENDING' ||
    status.navigationState === 'PAUSING' ||
    status.navigationState === 'PAUSED' ||
    status.navigationState === 'CANCELING';
  const isCanceling = status.navigationState === 'CANCELING';

  // Lý do khóa nút Bắt đầu (nếu có) để hiển thị tooltip/thông báo rõ ràng
  let startDisabledReason = '';
  if (!status.isConnected) {
    startDisabledReason = 'Chưa kết nối với hệ thống robot';
  } else if (status.controlMode === 'MANUAL') {
    startDisabledReason = 'Robot đang ở chế độ điều khiển thủ công (MANUAL)';
  } else if (!status.pose) {
    startDisabledReason = 'Chưa có vị trí định vị robot từ AMCL';
  } else if (status.isDataStale) {
    startDisabledReason = 'Dữ liệu vị trí robot chưa cập nhật';
  } else if (!selectedDestId) {
    startDisabledReason = 'Vui lòng chọn một điểm đến trong danh sách';
  } else if (isNavigating) {
    startDisabledReason = 'Robot đang thực hiện một chuyến đi khác';
  }

  const STATE_LABELS: Record<string, string> = {
    IDLE: 'Sẵn sàng đón khách',
    PENDING: 'Đang gửi yêu cầu...',
    ACCEPTED: 'Nav2 đã chấp nhận',
    NAVIGATING: 'Đang di chuyển dẫn đường',
    PAUSING: 'Đang tạm dừng chuyến đi...',
    PAUSED: 'Chuyến đi đang tạm dừng',
    CANCELING: 'Đang dừng và hủy chuyến...',
    SUCCEEDED: 'Đã đến đích thành công',
    CANCELED: 'Chuyến đi đã bị hủy',
    FAILED: 'Dẫn đường thất bại',
  };

  const activeDest = destinations.find((d) => d.id === status.destinationId);

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
          ⚠️ Mất kết nối tới robot dẫn đường. Hệ thống đang tự động thử kết nối lại...
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
                  <strong className={styles[status.navigationState.toLowerCase()] || styles.idle}>
                    {STATE_LABELS[status.navigationState] || status.navigationState}
                  </strong>
                </div>
                {activeDest && (
                  <div className={styles.statusRow} style={{ marginTop: '6px' }}>
                    <span>Điểm đến:</span>
                    <strong>{activeDest.name}</strong>
                  </div>
                )}
                {status.distanceRemaining !== null && status.distanceRemaining !== undefined && (
                  <div className={styles.statusRow} style={{ marginTop: '6px' }}>
                    <span>Khoảng cách còn lại:</span>
                    <strong>~{status.distanceRemaining.toFixed(1)} m</strong>
                  </div>
                )}
                {status.message && <p className={styles.statusMessage}>{status.message}</p>}
              </div>

              {actionError && <div className={styles.errorText}>{actionError}</div>}

              {/* Nút thao tác */}
              <div className={styles.actions}>
                {!isNavigating ? (
                  <button
                    className={styles.primaryBtn}
                    onClick={handleStart}
                    disabled={Boolean(startDisabledReason) || isSubmitting}
                    title={startDisabledReason || 'Bắt đầu chuyến đi'}
                  >
                    {isSubmitting ? 'Đang gửi lệnh...' : 'Bắt Đầu Dẫn Đường'}
                  </button>
                ) : status.isOwner ? (
                  <button
                    className={styles.cancelBtn}
                    onClick={handleCancel}
                    disabled={isCanceling || isSubmitting}
                    title="Dừng robot và hủy chuyến dẫn đường của bạn"
                  >
                    {isCanceling ? 'Đang dừng và hủy...' : 'Hủy Chuyến Đi'}
                  </button>
                ) : (
                  <div className={styles.otherPassengerNotice}>
                    <span>ℹ️ Robot đang thực hiện chuyến đi của hành khách khác.</span>
                  </div>
                )}
              </div>
              {!isNavigating && startDisabledReason && (
                <p className={styles.disabledHelpText}>ℹ️ {startDisabledReason}</p>
              )}
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
              backgroundMode="passenger"
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
