import React, { useState } from 'react';
import { useRobot } from '../../contexts/RobotContext';
import styles from './VoicePanel.module.css';

export const VoicePanel: React.FC = () => {
  const { status, startVoiceSession } = useRobot();
  const [triggerError, setTriggerError] = useState<string | null>(null);
  const [isCalling, setIsCalling] = useState(false);

  const handleMicClick = async () => {
    setTriggerError(null);
    setIsCalling(true);
    const res = await startVoiceSession();
    setIsCalling(false);
    if (!res.success) {
      setTriggerError(res.message || 'Không thể kích hoạt lượt nghe.');
    }
  };

  const getStatusText = () => {
    if (isCalling) return 'Đang gửi yêu cầu tới robot...';
    switch (status.voiceState) {
      case 'LISTENING':
        return '🎤 Robot đang thu âm bằng microphone trên thân xe...';
      case 'PROCESSING':
        return '⚙️ ROS đang xử lý yêu cầu giọng nói...';
      case 'SPEAKING':
        return '🔊 Robot đang phát âm thanh phản hồi...';
      case 'ERROR':
        return '⚠️ Hệ thống giọng nói ROS báo lỗi.';
      case 'IDLE':
      default:
        return 'Nhấn nút microphone để bắt đầu trò chuyện với robot';
    }
  };

  const isBusy = status.voiceState === 'LISTENING' || status.voiceState === 'PROCESSING' || status.voiceState === 'SPEAKING' || isCalling;

  return (
    <div className={styles.voiceCard}>
      <div className={styles.header}>
        <span className={styles.title}>Trợ lý Giọng nói Robot</span>
        <span className={`${styles.stateBadge} ${styles[status.voiceState.toLowerCase()]}`}>
          {status.voiceState}
        </span>
      </div>

      <div className={styles.micSection}>
        <button
          className={`${styles.micButton} ${isBusy ? styles.active : ''}`}
          onClick={handleMicClick}
          disabled={isBusy}
          title={isBusy ? 'Đang trong phiên tương tác' : 'Bấm để nói'}
        >
          <svg viewBox="0 0 24 24" width="32" height="32" fill="currentColor">
            <path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3z" />
            <path d="M17 11c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z" />
          </svg>
        </button>
        <p className={styles.statusDescription}>{getStatusText()}</p>
      </div>

      {triggerError && (
        <div className={styles.errorMessage}>
          <span>{triggerError}</span>
        </div>
      )}

      {/* Hiển thị transcript & response nhận từ ROS nếu có */}
      {(status.voiceTranscript || status.voiceResponse) && (
        <div className={styles.dialogBox}>
          {status.voiceTranscript && (
            <div className={styles.transcriptRow}>
              <strong>Bạn đã nói:</strong>
              <p>"{status.voiceTranscript}"</p>
            </div>
          )}
          {status.voiceResponse && (
            <div className={styles.responseRow}>
              <strong>Robot phản hồi:</strong>
              <p>{status.voiceResponse}</p>
            </div>
          )}
        </div>
      )}

      <div className={styles.footerNote}>
        <small>💡 Giọng nói được xử lý trực tiếp trên phần cứng robot qua ROS 2. Trình duyệt không thu âm.</small>
      </div>
    </div>
  );
};
