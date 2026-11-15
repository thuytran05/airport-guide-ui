import React, { useState } from 'react';
import { useRobot } from '../../contexts/RobotContext';
import styles from './VoicePanel.module.css';

export const VoicePanel: React.FC = () => {
  const { status, startVoiceSession, confirmVoiceProposal, dismissVoiceProposal } = useRobot();
  const [triggerError, setTriggerError] = useState<string | null>(null);
  const [isCalling, setIsCalling] = useState(false);
  const [isConfirming, setIsConfirming] = useState(false);
  const [confirmError, setConfirmError] = useState<string | null>(null);

  const isAvailable = Boolean(status.voiceAvailable);
  const isBusy =
    status.voiceState === 'LISTENING' ||
    status.voiceState === 'PROCESSING' ||
    status.voiceState === 'SPEAKING' ||
    isCalling;

  const isDisabled = !isAvailable || isBusy;

  const handleMicClick = async () => {
    if (isDisabled) return;
    setTriggerError(null);
    setConfirmError(null);
    setIsCalling(true);
    try {
      const res = await startVoiceSession();
      if (!res.success) {
        setTriggerError(res.message || 'Không thể kích hoạt lượt nghe.');
      }
    } catch (err: any) {
      setTriggerError(err?.message || 'Lỗi khi gửi yêu cầu kích hoạt microphone.');
    } finally {
      setIsCalling(false);
    }
  };

  const handleConfirmProposal = async () => {
    if (!status.voiceProposal || isConfirming) return;
    setIsConfirming(true);
    setConfirmError(null);
    try {
      const res = await confirmVoiceProposal(
        status.voiceProposal.proposal_id,
        status.voiceProposal.destination_id || undefined
      );
      if (!res.success) {
        setConfirmError(res.message || 'Không thể bắt đầu dẫn đường tới điểm đến.');
      }
    } catch (err: any) {
      setConfirmError(err?.message || 'Lỗi khi gửi xác nhận.');
    } finally {
      setIsConfirming(false);
    }
  };

  const handleDismissProposal = async () => {
    setConfirmError(null);
    await dismissVoiceProposal();
  };

  const getStatusText = () => {
    if (!isAvailable) {
      return 'Tính năng trợ lý giọng nói hiện chưa sẵn sàng. Nút microphone tạm thời được khóa an toàn.';
    }
    if (isCalling) return 'Đang gửi yêu cầu tới robot...';
    switch (status.voiceState) {
      case 'LISTENING':
        return '🎤 Đang nghe (nói vào microphone của robot)...';
      case 'PROCESSING':
        return '⚙️ Đang xử lý yêu cầu giọng nói...';
      case 'SPEAKING':
        return '🔊 Robot đang phát âm thanh phản hồi...';
      case 'ERROR':
        return '⚠️ Trợ lý giọng nói gặp sự cố tạm thời.';
      case 'IDLE':
      default:
        return 'Nhấn nút microphone để bắt đầu trò chuyện với robot';
    }
  };

  const getButtonTitle = () => {
    if (!isAvailable) {
      return 'Trợ lý giọng nói hiện chưa sẵn sàng';
    }
    if (isBusy) {
      return 'Đang trong phiên tương tác giọng nói';
    }
    return 'Bấm để nói (microphone trên robot)';
  };

  const proposal = status.voiceProposal;

  return (
    <div className={styles.voiceCard}>
      <div className={styles.header}>
        <span className={styles.title}>Trợ lý Giọng nói Robot</span>
        <span
          className={`${styles.stateBadge} ${
            !isAvailable ? styles.offline : styles[status.voiceState.toLowerCase()] || styles.idle
          }`}
        >
          {!isAvailable ? 'OFFLINE' : status.voiceState}
        </span>
      </div>

      {!isAvailable && (
        <div className={styles.offlineBanner}>
          <span>⚠️ Trợ lý giọng nói trên robot hiện chưa sẵn sàng. Nút microphone đã được khóa an toàn.</span>
        </div>
      )}

      <div className={styles.micSection}>
        <button
          className={`${styles.micButton} ${isBusy && isAvailable ? styles.active : ''}`}
          onClick={handleMicClick}
          disabled={isDisabled}
          title={getButtonTitle()}
          aria-label={getButtonTitle()}
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

      {/* Đề xuất điểm đến từ nhận dạng giọng nói cần xác nhận */}
      {proposal && proposal.status === 'MATCHED' && (
        <div className={styles.proposalCard}>
          <div className={styles.proposalHeader}>
            <span className={styles.proposalIcon}>📍</span>
            <span className={styles.proposalTitle}>Xác Nhận Điểm Đến</span>
          </div>
          <p className={styles.proposalQuestion}>
            Bạn muốn đến <strong>{proposal.destination_name}</strong>?
          </p>
          <div className={styles.proposalActions}>
            <button
              type="button"
              className={styles.confirmBtn}
              onClick={handleConfirmProposal}
              disabled={isConfirming || status.navigationState !== 'IDLE'}
              title={status.navigationState !== 'IDLE' ? 'Robot đang thực hiện chuyến đi' : 'Bấm để robot dẫn đường'}
            >
              {isConfirming ? 'Đang gửi lệnh...' : '✓ Xác nhận'}
            </button>
            <button
              type="button"
              className={styles.dismissBtn}
              onClick={handleDismissProposal}
              disabled={isConfirming}
              title="Bỏ qua đề xuất này"
            >
              ✕ Bỏ qua
            </button>
          </div>
          {confirmError && (
            <div className={styles.confirmErrorMessage}>
              <span>{confirmError}</span>
            </div>
          )}
        </div>
      )}

      {proposal && proposal.status === 'NO_MATCH' && (
        <div className={styles.proposalNotice}>
          <p className={styles.proposalNoticeText}>
            ⚠️ Không tìm thấy điểm đến phù hợp với yêu cầu: <em>"{proposal.transcript}"</em>. Vui lòng chọn lại điểm đến từ danh sách.
          </p>
          <button type="button" className={styles.dismissSmallBtn} onClick={handleDismissProposal}>
            Đã hiểu
          </button>
        </div>
      )}

      {proposal && proposal.status === 'AMBIGUOUS' && (
        <div className={styles.proposalNotice}>
          <p className={styles.proposalNoticeText}>
            ⚠️ Tìm thấy nhiều điểm đến trùng khớp với yêu cầu: <em>"{proposal.transcript}"</em>. Vui lòng chọn trực tiếp từ danh sách điểm đến.
          </p>
          <button type="button" className={styles.dismissSmallBtn} onClick={handleDismissProposal}>
            Đã hiểu
          </button>
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
        <small>💡 Giọng nói được xử lý trực tiếp qua microphone trên thân robot. Trình duyệt không thu âm microphone máy tính.</small>
      </div>
    </div>
  );
};
