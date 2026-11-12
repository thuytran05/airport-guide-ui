import React, { useState, useRef } from 'react';
import { RobotPose, Destination, PathPoint } from '../../types';
import styles from './MapView.module.css';

interface MapViewProps {
  robotPose: RobotPose | null;
  destinations?: Destination[];
  selectedDestinationId?: string | null;
  path?: PathPoint[] | null;
  onDestinationSelect?: (id: string) => void;
  className?: string;
}

// Giả định hệ tọa độ bản đồ hiển thị:
// Kích thước khung 800 x 500, tỉ lệ 20 pixel / mét
const SCALE_M_TO_PX = 25;
const MAP_ORIGIN_X = 50;  // pixel
const MAP_ORIGIN_Y = 450; // pixel (trục Y hướng lên trên mặt phẳng ROS)

function rosToSvg(x: number, y: number) {
  return {
    px: MAP_ORIGIN_X + x * SCALE_M_TO_PX,
    py: MAP_ORIGIN_Y - y * SCALE_M_TO_PX,
  };
}

export const MapView: React.FC<MapViewProps> = ({
  robotPose,
  destinations = [],
  selectedDestinationId,
  path,
  onDestinationSelect,
  className,
}) => {
  const [scale, setScale] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [isDragging, setIsDragging] = useState(false);
  const dragStartRef = useRef({ x: 0, y: 0 });
  const currentPanRef = useRef({ x: 0, y: 0 });

  const handleMouseDown = (e: React.MouseEvent) => {
    if (e.button !== 0) return;
    setIsDragging(true);
    dragStartRef.current = { x: e.clientX, y: e.clientY };
    currentPanRef.current = { ...pan };
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (!isDragging) return;
    setPan({
      x: currentPanRef.current.x + (e.clientX - dragStartRef.current.x),
      y: currentPanRef.current.y + (e.clientY - dragStartRef.current.y),
    });
  };

  const handleMouseUp = () => setIsDragging(false);

  const resetView = () => {
    setScale(1);
    setPan({ x: 0, y: 0 });
  };

  // Tính tọa độ pixel cho robot
  const robotSvg = robotPose ? rosToSvg(robotPose.x, robotPose.y) : null;
  const robotDeg = robotPose ? (-robotPose.theta * 180) / Math.PI : 0;

  // Tính tọa độ đường đi (path)
  const polylinePoints = path && path.length > 0
    ? path.map((pt) => {
        const svgPt = rosToSvg(pt.x, pt.y);
        return `${svgPt.px},${svgPt.py}`;
      }).join(' ')
    : '';

  return (
    <div
      className={`${styles.mapContainer} ${className || ''}`}
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseUp}
      style={{ cursor: isDragging ? 'grabbing' : 'grab' }}
    >
      {/* HUD Controls */}
      <div className={styles.controls} onClick={(e) => e.stopPropagation()}>
        <button onClick={() => setScale((s) => Math.min(2.5, s + 0.2))} title="Phóng to">+</button>
        <button onClick={() => setScale((s) => Math.max(0.6, s - 0.2))} title="Thu nhỏ">-</button>
        <button onClick={resetView} title="Căn giữa">⊙</button>
      </div>

      {/* Thông báo nếu chưa có dữ liệu vị trí */}
      {!robotPose && (
        <div className={styles.noDataBadge}>
          <span>⚠️ Chưa có dữ liệu vị trí robot</span>
        </div>
      )}

      <svg
        className={styles.svgMap}
        viewBox="0 0 800 500"
        style={{
          transform: `translate(${pan.x}px, ${pan.y}px) scale(${scale})`,
          transformOrigin: 'center center',
          transition: isDragging ? 'none' : 'transform 0.1s ease-out',
        }}
      >
        {/* Nền bản đồ và lưới tọa độ */}
        <defs>
          <pattern id="grid" width="25" height="25" patternUnits="userSpaceOnUse">
            <path d="M 25 0 L 0 0 0 25" fill="none" stroke="#E2E8F0" strokeWidth="0.8" />
          </pattern>
        </defs>
        <rect width="800" height="500" fill="#F8FAFC" />
        <rect width="800" height="500" fill="url(#grid)" />

        {/* Khu vực minh họa tòa nhà ga */}
        <rect x="40" y="40" width="720" height="420" rx="12" fill="none" stroke="#CBD5E1" strokeWidth="2" strokeDasharray="6 4" />
        <text x="55" y="65" fill="#94A3B8" fontSize="13" fontWeight="bold">BẢN ĐỒ TẦNG 1 — SÂN BAY QUỐC TẾ</text>

        {/* Lộ trình di chuyển Nav2 (Path) */}
        {polylinePoints && (
          <polyline
            points={polylinePoints}
            fill="none"
            stroke="#0284C7"
            strokeWidth="3.5"
            strokeDasharray="5 3"
            strokeLinecap="round"
          />
        )}

        {/* Các điểm đến (Destinations) */}
        {destinations.map((dest) => {
          const pt = rosToSvg(dest.pose.position.x, dest.pose.position.y);
          const isSelected = dest.id === selectedDestinationId;
          return (
            <g
              key={dest.id}
              transform={`translate(${pt.px}, ${pt.py})`}
              style={{ cursor: 'pointer' }}
              onClick={(e) => {
                e.stopPropagation();
                if (onDestinationSelect) onDestinationSelect(dest.id);
              }}
            >
              <circle
                r={isSelected ? 16 : 10}
                fill={isSelected ? '#22C55E' : '#3B82F6'}
                stroke="#FFFFFF"
                strokeWidth="2.5"
                opacity={isSelected ? 0.95 : 0.8}
              />
              <text
                y={-14}
                textAnchor="middle"
                fill={isSelected ? '#15803D' : '#1E293B'}
                fontSize="11"
                fontWeight={isSelected ? 'bold' : 'normal'}
                className={styles.markerLabel}
              >
                {dest.name}
              </text>
            </g>
          );
        })}

        {/* Marker Robot */}
        {robotSvg && (
          <g transform={`translate(${robotSvg.px}, ${robotSvg.py}) rotate(${robotDeg})`}>
            {/* Vòng hào quang robot */}
            <circle r="18" fill="#3B82F6" opacity="0.25" />
            <circle r="12" fill="#1D4ED8" stroke="#FFFFFF" strokeWidth="2.5" />
            {/* Mũi tên chỉ hướng robot (theta) */}
            <polygon points="0,-16 6,-4 -6,-4" fill="#F59E0B" stroke="#FFFFFF" strokeWidth="1" />
          </g>
        )}
      </svg>
    </div>
  );
};
