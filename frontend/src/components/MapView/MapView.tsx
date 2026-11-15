import React, { useState, useRef, useMemo, useEffect, useCallback } from 'react';
import { RobotPose, Destination, PathPoint, MapData } from '../../types';
import { useRobot } from '../../contexts/RobotContext';
import styles from './MapView.module.css';

export type MapBackgroundMode = 'ros' | 'passenger';

export interface MapViewProps {
  robotPose?: RobotPose | null;
  destinations?: Destination[];
  selectedDestinationId?: string | null;
  path?: PathPoint[] | null;
  onDestinationSelect?: (id: string) => void;
  className?: string;
  customMapData?: MapData | null;
  backgroundMode?: MapBackgroundMode;
  isSelectingCoordinate?: boolean;
  onCoordinateSelect?: (coords: { x: number; y: number; yawDeg?: number }) => void;
  onPickingGuide?: (msg: string) => void;
  previewPoint?: { x: number; y: number; yawDeg?: number } | null;
}

export const PASSENGER_MAP_URL = '/maps/passenger-map.png';

/**
 * Phép chiếu tọa độ ROS (frame map) sang tọa độ pixel trên ảnh bản đồ:
 * dx = rosX - originX
 * dy = rosY - originY
 * a = originYaw (radian)
 * px = (cos(a) * dx + sin(a) * dy) / resolution
 * py = height - (-sin(a) * dx + cos(a) * dy) / resolution
 */
export function projectRosToMapPixel(
  rosX: number,
  rosY: number,
  originX: number,
  originY: number,
  originYaw: number,
  resolution: number,
  height: number
): { px: number; py: number } {
  const dx = rosX - originX;
  const dy = rosY - originY;
  const a = originYaw;
  const px = (Math.cos(a) * dx + Math.sin(a) * dy) / resolution;
  const py = height - (-Math.sin(a) * dx + Math.cos(a) * dy) / resolution;
  return { px, py };
}

/**
 * Phép chiếu ngược từ tọa độ pixel trên SVG/ảnh bản đồ sang tọa độ thực ROS (frame map):
 * u = px * resolution
 * v = (height - py) * resolution
 * a = originYaw (radian)
 * dx = cos(a) * u - sin(a) * v
 * dy = sin(a) * u + cos(a) * v
 * rosX = originX + dx
 * rosY = originY + dy
 */
export function projectMapPixelToRos(
  px: number,
  py: number,
  originX: number,
  originY: number,
  originYaw: number,
  resolution: number,
  height: number
): { rosX: number; rosY: number } {
  const u = px * resolution;
  const v = (height - py) * resolution;
  const a = originYaw;
  const dx = Math.cos(a) * u - Math.sin(a) * v;
  const dy = Math.sin(a) * u + Math.cos(a) * v;
  return {
    rosX: originX + dx,
    rosY: originY + dy,
  };
}

/**
 * Tính góc xoay hiển thị trên SVG (độ):
 * headingDeg = -(theta - originYaw) * 180 / Math.PI
 * Giả sử icon mặc định có đầu hướng sang phải (trục +X).
 */
export function calculateHeadingDeg(theta: number, originYaw: number): number {
  return -((theta - originYaw) * 180) / Math.PI;
}

export const MapView: React.FC<MapViewProps> = ({
  robotPose: propRobotPose,
  destinations = [],
  selectedDestinationId,
  path: propPath,
  onDestinationSelect,
  className,
  customMapData,
  backgroundMode = 'ros',
  isSelectingCoordinate = false,
  onCoordinateSelect,
  onPickingGuide,
  previewPoint = null,
}) => {
  const {
    status,
    mapData: contextMapData,
    isMapLoading,
    mapError,
    isBackendConnected,
    path: contextPath,
  } = useRobot();

  const containerRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const [containerSize, setContainerSize] = useState<{ width: number; height: number }>({ width: 0, height: 0 });

  const [scale, setScale] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [isDragging, setIsDragging] = useState(false);
  const dragStartRef = useRef({ x: 0, y: 0 });
  const currentPanRef = useRef({ x: 0, y: 0 });

  // Trạng thái kéo-thả định hướng (RViz Drag-to-Orient)
  const [orienting, setOrienting] = useState<{
    startRos: { x: number; y: number };
    startPx: number;
    startPy: number;
    currentPx: number;
    currentPy: number;
    screenDist: number;
    headingDeg: number;
    yawDeg: number;
  } | null>(null);

  // Hủy định hướng khi tắt chế độ chọn tọa độ hoặc nhấn Esc
  useEffect(() => {
    if (!isSelectingCoordinate) {
      setOrienting(null);
    }
  }, [isSelectingCoordinate]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setOrienting(null);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  // Trạng thái kiểm tra sự tồn tại của file sơ đồ hành khách PNG
  const [passengerMapStatus, setPassengerMapStatus] = useState<'checking' | 'available' | 'missing'>('checking');

  // Bản đồ ưu tiên: prop nếu có, ngược lại dùng từ context
  const activeMap = customMapData !== undefined ? customMapData : contextMapData;

  // Pose ưu tiên: prop nếu có, ngược lại lấy từ status.pose
  const currentPose = propRobotPose !== undefined ? propRobotPose : status.pose;
  const poseFrameId = status.frame_id || 'map';

  // Path ưu tiên: prop nếu có, ngược lại lấy từ context
  const currentPath = propPath !== undefined ? propPath : (contextPath || null);

  // Lưu trữ vị trí cuối cùng hợp lệ để hiển thị khi dữ liệu stale hoặc mất kết nối
  const lastKnownPoseRef = useRef<RobotPose | null>(null);

  // Kích thước khung nhìn SVG (chuẩn theo metadata ROS, mặc định 384 nếu chưa có)
  const mapWidth = activeMap?.metadata.width || 384;
  const mapHeight = activeMap?.metadata.height || 384;

  const isPassengerMode = backgroundMode === 'passenger';

  // Theo dõi kích thước thực của container để cố định kích thước marker trên màn hình
  useEffect(() => {
    if (!containerRef.current) return;
    const el = containerRef.current;
    const updateSize = () => {
      setContainerSize({
        width: el.clientWidth,
        height: el.clientHeight,
      });
    };
    updateSize();

    if (typeof ResizeObserver !== 'undefined') {
      const ro = new ResizeObserver(updateSize);
      ro.observe(el);
      return () => ro.disconnect();
    }
  }, []);

  // Kiểm tra sự tồn tại của ảnh sơ đồ hành khách (không gọi lặp theo WebSocket 5Hz)
  const checkPassengerMap = useCallback(async () => {
    try {
      const res = await fetch(PASSENGER_MAP_URL, { method: 'GET', cache: 'no-cache' });
      const contentType = res.headers.get('content-type') || '';
      if (!res.ok || contentType.includes('text/html')) {
        setPassengerMapStatus('missing');
        return;
      }
      const img = new Image();
      img.onload = () => {
        if (img.naturalWidth > 0 && img.naturalHeight > 0) {
          setPassengerMapStatus('available');
        } else {
          setPassengerMapStatus('missing');
        }
      };
      img.onerror = () => setPassengerMapStatus('missing');
      img.src = PASSENGER_MAP_URL;
    } catch {
      setPassengerMapStatus('missing');
    }
  }, []);

  useEffect(() => {
    checkPassengerMap();
  }, [checkPassengerMap, backgroundMode]);

  const handleMouseDown = (e: React.MouseEvent) => {
    if (e.button !== 0) return;

    // Chế độ chọn vị trí & hướng trên bản đồ ROS (Drag-to-Orient RViz style)
    if (isSelectingCoordinate && backgroundMode === 'ros' && activeMap && svgRef.current) {
      const svg = svgRef.current;
      const pt = svg.createSVGPoint();
      pt.x = e.clientX;
      pt.y = e.clientY;
      const ctm = svg.getScreenCTM();
      if (ctm) {
        const inverseCTM = ctm.inverse();
        const svgPoint = pt.matrixTransform(inverseCTM);
        const meta = activeMap.metadata;
        if (
          svgPoint.x >= 0 &&
          svgPoint.x <= meta.width &&
          svgPoint.y >= 0 &&
          svgPoint.y <= meta.height
        ) {
          const ros = projectMapPixelToRos(
            svgPoint.x,
            svgPoint.y,
            meta.origin_x,
            meta.origin_y,
            meta.origin_yaw,
            meta.resolution,
            meta.height
          );
          dragStartRef.current = { x: e.clientX, y: e.clientY };
          setOrienting({
            startRos: { x: Number(ros.rosX.toFixed(2)), y: Number(ros.rosY.toFixed(2)) },
            startPx: svgPoint.x,
            startPy: svgPoint.y,
            currentPx: svgPoint.x,
            currentPy: svgPoint.y,
            screenDist: 0,
            headingDeg: 0,
            yawDeg: 0,
          });
          return;
        }
      }
    }

    setIsDragging(true);
    dragStartRef.current = { x: e.clientX, y: e.clientY };
    currentPanRef.current = { ...pan };
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (orienting && activeMap && svgRef.current) {
      const svg = svgRef.current;
      const pt = svg.createSVGPoint();
      pt.x = e.clientX;
      pt.y = e.clientY;
      const ctm = svg.getScreenCTM();
      if (ctm) {
        const inverseCTM = ctm.inverse();
        const svgPoint = pt.matrixTransform(inverseCTM);
        const meta = activeMap.metadata;
        const screenDist = Math.hypot(e.clientX - dragStartRef.current.x, e.clientY - dragStartRef.current.y);

        if (screenDist >= 15) {
          const currRos = projectMapPixelToRos(
            svgPoint.x,
            svgPoint.y,
            meta.origin_x,
            meta.origin_y,
            meta.origin_yaw,
            meta.resolution,
            meta.height
          );
          const dx = currRos.rosX - orienting.startRos.x;
          const dy = currRos.rosY - orienting.startRos.y;
          const yawRad = Math.atan2(dy, dx);
          let yawDeg = Math.round((yawRad * 180) / Math.PI);
          if (yawDeg > 180) yawDeg -= 360;
          if (yawDeg <= -180) yawDeg += 360;

          const pdx = svgPoint.x - orienting.startPx;
          const pdy = svgPoint.y - orienting.startPy;
          const headingDeg = (Math.atan2(pdy, pdx) * 180) / Math.PI;

          setOrienting((prev) =>
            prev
              ? {
                  ...prev,
                  currentPx: svgPoint.x,
                  currentPy: svgPoint.y,
                  screenDist,
                  headingDeg,
                  yawDeg,
                }
              : null
          );
        } else {
          setOrienting((prev) =>
            prev
              ? {
                  ...prev,
                  currentPx: svgPoint.x,
                  currentPy: svgPoint.y,
                  screenDist,
                }
              : null
          );
        }
      }
      return;
    }

    if (!isDragging) return;
    setPan({
      x: currentPanRef.current.x + (e.clientX - dragStartRef.current.x),
      y: currentPanRef.current.y + (e.clientY - dragStartRef.current.y),
    });
  };

  const handleMouseUp = (e: React.MouseEvent) => {
    if (orienting) {
      if (orienting.screenDist >= 15) {
        onCoordinateSelect?.({
          x: orienting.startRos.x,
          y: orienting.startRos.y,
          yawDeg: orienting.yawDeg,
        });
      } else {
        // Kéo ngắn hoặc click một điểm: chỉ lấy tọa độ X, Y; không tự ý gán yaw 0
        onCoordinateSelect?.({
          x: orienting.startRos.x,
          y: orienting.startRos.y,
        });
        onPickingGuide?.('Kéo chuột từ vị trí ghim để chọn hướng (Yaw), hoặc tự nhập góc trong ô Yaw');
      }
      setOrienting(null);
      return;
    }

    if (isDragging) {
      setIsDragging(false);
    }
  };

  // Lắng nghe sự kiện wheel với { passive: false } trên vùng bản đồ để chặn triệt để cuộn trang
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const onWheel = (e: WheelEvent) => {
      // Chặn cuộn trang khi con trỏ nằm trong khung bản đồ, kể cả ở ngưỡng zoom min/max
      e.preventDefault();
      const zoomFactor = e.deltaY < 0 ? 1.15 : 0.87;
      setScale((s) => Math.min(4.0, Math.max(0.4, Number((s * zoomFactor).toFixed(2)))));
    };

    el.addEventListener('wheel', onWheel, { passive: false });
    return () => {
      el.removeEventListener('wheel', onWheel);
    };
  }, []);

  const resetView = () => {
    setScale(1);
    setPan({ x: 0, y: 0 });
  };

  // 1. Kiểm tra tính hợp lệ của pose và frame
  const isPoseValid = useMemo(() => {
    if (!currentPose) return false;
    return (
      typeof currentPose.x === 'number' &&
      typeof currentPose.y === 'number' &&
      typeof currentPose.theta === 'number' &&
      Number.isFinite(currentPose.x) &&
      Number.isFinite(currentPose.y) &&
      Number.isFinite(currentPose.theta)
    );
  }, [currentPose]);

  const isFrameMatching = useMemo(() => {
    if (!activeMap) return false;
    return !poseFrameId || poseFrameId === activeMap.frame_id;
  }, [activeMap, poseFrameId]);

  // Lưu lại vị trí cuối cùng khi pose hợp lệ và frame khớp
  useEffect(() => {
    if (isPoseValid && isFrameMatching && currentPose) {
      lastKnownPoseRef.current = currentPose;
    }
  }, [isPoseValid, isFrameMatching, currentPose]);

  // Quyết định pose hiển thị: dùng pose hiện tại nếu hợp lệ, hoặc vị trí cuối cùng nếu có
  const displayPose = isPoseValid && isFrameMatching ? currentPose : lastKnownPoseRef.current;
  const isLastKnown = !isPoseValid || !isFrameMatching || !isBackendConnected || status.isDataStale || status.simClockStalled;

  // 2. Tính tọa độ pixel cho marker robot (khi có metadata ROS)
  const robotMarker = useMemo(() => {
    if (!activeMap || !displayPose) return null;
    const meta = activeMap.metadata;
    const { px, py } = projectRosToMapPixel(
      displayPose.x,
      displayPose.y,
      meta.origin_x,
      meta.origin_y,
      meta.origin_yaw,
      meta.resolution,
      meta.height
    );
    const deg = calculateHeadingDeg(displayPose.theta, meta.origin_yaw);
    return { px, py, deg };
  }, [activeMap, displayPose]);

  // 3. Tính tọa độ pixel cho các điểm đến (Destinations)
  const projectedDestinations = useMemo(() => {
    if (!activeMap || !destinations || destinations.length === 0) return [];
    const meta = activeMap.metadata;
    return destinations.map((dest) => {
      const { px, py } = projectRosToMapPixel(
        dest.pose.position.x,
        dest.pose.position.y,
        meta.origin_x,
        meta.origin_y,
        meta.origin_yaw,
        meta.resolution,
        meta.height
      );
      return {
        ...dest,
        px,
        py,
      };
    });
  }, [activeMap, destinations]);

  // 4. Tính polyline cho đường dẫn Nav2 (Path)
  const pathPolylinePoints = useMemo(() => {
    if (!activeMap || !currentPath || currentPath.length === 0) return '';
    const meta = activeMap.metadata;
    return currentPath
      .map((pt) => {
        const { px, py } = projectRosToMapPixel(
          pt.x,
          pt.y,
          meta.origin_x,
          meta.origin_y,
          meta.origin_yaw,
          meta.resolution,
          meta.height
        );
        return `${px},${py}`;
      })
      .join(' ');
  }, [activeMap, currentPath]);

  // 4b. Tính tọa độ pixel cho Preview Pin (Điểm nháp xem trước)
  const previewMarker = useMemo(() => {
    if (!activeMap || !previewPoint) return null;
    if (typeof previewPoint.x !== 'number' || typeof previewPoint.y !== 'number') return null;
    if (isNaN(previewPoint.x) || isNaN(previewPoint.y)) return null;

    const meta = activeMap.metadata;
    const { px, py } = projectRosToMapPixel(
      previewPoint.x,
      previewPoint.y,
      meta.origin_x,
      meta.origin_y,
      meta.origin_yaw,
      meta.resolution,
      meta.height
    );

    const yawDeg = typeof previewPoint.yawDeg === 'number' && !isNaN(previewPoint.yawDeg)
      ? previewPoint.yawDeg
      : 0;
    const yawRad = (yawDeg * Math.PI) / 180.0;
    const headingDeg = calculateHeadingDeg(yawRad, meta.origin_yaw);

    return { px, py, headingDeg, x: previewPoint.x, y: previewPoint.y, yawDeg };
  }, [activeMap, previewPoint]);

  // 5. Tính hệ số co dãn để giữ marker robot cố định khoảng 16-20px trên màn hình khi zoom
  const baseScale = useMemo(() => {
    if (containerSize.width > 0 && containerSize.height > 0 && mapWidth > 0 && mapHeight > 0) {
      return Math.min(containerSize.width / mapWidth, containerSize.height / mapHeight);
    }
    return 1;
  }, [containerSize, mapWidth, mapHeight]);

  const markerScreenScale = useMemo(() => {
    const effective = baseScale * scale;
    return effective > 0 ? 1 / effective : 1;
  }, [baseScale, scale]);

  // 6. Xác định thông báo Badge trạng thái
  const badgeMessage = useMemo(() => {
    if (isPassengerMode && passengerMapStatus !== 'available') {
      return null;
    }

    if (!activeMap) {
      if (isMapLoading) return '⏳ Đang tải bản đồ từ máy chủ...';
      if (mapError) return `❌ Lỗi bản đồ: ${mapError}`;
      return '⚠️ Đang chờ bản đồ từ ROS';
    }

    if (!isBackendConnected) {
      return '⚠️ Mất kết nối máy chủ';
    }

    if (status.simClockStalled) {
      return '⚠️ Mô phỏng không cập nhật';
    }

    if (!isPoseValid && !lastKnownPoseRef.current) {
      return 'ℹ️ Chưa có vị trí robot';
    }

    if (!isFrameMatching) {
      if (isPassengerMode) {
        return '⚠️ Vị trí robot chưa đồng bộ';
      }
      return `⚠️ Lệch hệ quy chiếu (pose: ${poseFrameId}, map: ${activeMap.frame_id})`;
    }

    if (status.isDataStale) {
      return '⚠️ Vị trí robot cũ (chưa cập nhật)';
    }

    return null;
  }, [isPassengerMode, passengerMapStatus, activeMap, isMapLoading, mapError, isBackendConnected, status.simClockStalled, isPoseValid, isFrameMatching, poseFrameId, status.isDataStale]);

  const mapImageUrl = activeMap?.imageBlobUrl || activeMap?.image_url;

  return (
    <div
      ref={containerRef}
      className={`${styles.mapContainer} ${className || ''}`}
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseUp}
      style={{
        cursor: isSelectingCoordinate && !isPassengerMode
          ? 'crosshair'
          : isDragging
          ? 'grabbing'
          : 'grab',
      }}
    >
      {/* HUD Controls */}
      <div className={styles.controls} onClick={(e) => e.stopPropagation()} onMouseDown={(e) => e.stopPropagation()}>
        <button onClick={() => setScale((s) => Math.min(4.0, s + 0.25))} title="Phóng to">+</button>
        <button onClick={() => setScale((s) => Math.max(0.4, s - 0.25))} title="Thu nhỏ">-</button>
        <button onClick={resetView} title="Căn giữa">⊙</button>
      </div>

      {/* Banner chế độ chọn tọa độ */}
      {isSelectingCoordinate && !isPassengerMode && (
        <div className={styles.coordinatePickerBanner}>
          <span>
            {orienting && orienting.screenDist >= 15
              ? `🎯 Đang chọn hướng: Yaw = ${orienting.yawDeg}° (Thả chuột để xác nhận)`
              : orienting
              ? '🎯 Giữ chuột và kéo để xoay hướng (Yaw) theo ý muốn'
              : '📍 Nhấn và kéo chuột trên bản đồ để chọn vị trí & hướng (hoặc nhấp chỉ chọn vị trí)'}
          </span>
        </div>
      )}

      {/* Thông báo trạng thái Badge */}
      {badgeMessage && (
        <div className={styles.noDataBadge}>
          <span>{badgeMessage}</span>
        </div>
      )}

      {/* Placeholder khi chưa có file ảnh Sơ đồ hành khách */}
      {isPassengerMode && passengerMapStatus !== 'available' && (
        <div className={styles.passengerMapPlaceholder}>
          <div className={styles.placeholderCard}>
            <span className={styles.placeholderIcon}>🗺️</span>
            <h3 className={styles.placeholderTitle}>Sơ đồ đang được cập nhật</h3>
            <p className={styles.placeholderSubtitle}>
              Hệ thống đang chuẩn bị sơ đồ hành khách. Vui lòng quay lại sau.
            </p>
          </div>
        </div>
      )}

      {/* Overlay khi đang tải bản đồ ROS */}
      {!isPassengerMode && !activeMap && isMapLoading && (
        <div className={styles.mapLoadingOverlay}>
          <div className="spinner" />
          <span>Đang tải bản đồ OccupancyGrid...</span>
        </div>
      )}

      <svg
        ref={svgRef}
        className={styles.svgMap}
        viewBox={`0 0 ${mapWidth} ${mapHeight}`}
        style={{
          transform: `translate(${pan.x}px, ${pan.y}px) scale(${scale})`,
          transformOrigin: 'center center',
          transition: isDragging ? 'none' : 'transform 0.1s ease-out',
        }}
      >
        {/* Nền bản đồ xám trung tính */}
        <rect width={mapWidth} height={mapHeight} fill={isPassengerMode ? '#F8FAFC' : '#CDCDCD'} />

        {/* ẢNH NỀN 1: Ảnh OccupancyGrid thực tế từ ROS 2 /map */}
        {!isPassengerMode && mapImageUrl && (
          <image
            href={mapImageUrl}
            x={0}
            y={0}
            width={mapWidth}
            height={mapHeight}
            preserveAspectRatio="none"
          />
        )}

        {/* ẢNH NỀN 2: Ảnh Sơ đồ hành khách PNG */}
        {isPassengerMode && passengerMapStatus === 'available' && (
          <image
            href={PASSENGER_MAP_URL}
            x={0}
            y={0}
            width={mapWidth}
            height={mapHeight}
            preserveAspectRatio="none"
          />
        )}

        {/* Lộ trình di chuyển Nav2 (Path) */}
        {pathPolylinePoints && (!isPassengerMode || passengerMapStatus === 'available') && (
          <polyline
            points={pathPolylinePoints}
            fill="none"
            stroke="#2563EB"
            strokeWidth={2.5 * markerScreenScale}
            strokeDasharray={`${5 * markerScreenScale} ${3 * markerScreenScale}`}
            strokeLinecap="round"
          />
        )}

        {/* Các điểm đến (Destinations) */}
        {(!isPassengerMode || passengerMapStatus === 'available') &&
          projectedDestinations.map((dest) => {
            const isSelected = dest.id === selectedDestinationId;
            return (
              <g
                key={dest.id}
                transform={`translate(${dest.px}, ${dest.py}) scale(${markerScreenScale})`}
                style={{ cursor: onDestinationSelect ? 'pointer' : 'default' }}
                onClick={(e) => {
                  e.stopPropagation();
                  if (onDestinationSelect) onDestinationSelect(dest.id);
                }}
              >
                {isSelected && <circle r={13} fill="#22C55E" opacity={0.25} />}
                <circle
                  r={isSelected ? 8 : 6}
                  fill={isSelected ? '#16A34A' : '#3B82F6'}
                  stroke="#FFFFFF"
                  strokeWidth={1.5}
                />
                <text
                  y={-10}
                  textAnchor="middle"
                  fill={isSelected ? '#15803D' : '#1E293B'}
                  fontSize={11}
                  fontWeight={isSelected ? 'bold' : '600'}
                  className={styles.markerLabel}
                >
                  {dest.name}
                </text>
              </g>
            );
          })}

        {/* Điểm nháp xem trước (Preview Pin) */}
        {previewMarker && (!isPassengerMode || passengerMapStatus === 'available') && (
          <g
            transform={`translate(${previewMarker.px}, ${previewMarker.py}) scale(${markerScreenScale})`}
            className={styles.previewPinGroup}
          >
            {/* Vòng hào quang đứt nét nhấp nháy nhẹ */}
            <circle
              r={14}
              fill="rgba(245, 158, 11, 0.25)"
              stroke="#F59E0B"
              strokeWidth={1.5}
              strokeDasharray="4 2"
            />
            {/* Pin tròn màu cam amber */}
            <circle
              r={7}
              fill="#F59E0B"
              stroke="#FFFFFF"
              strokeWidth={1.5}
            />
            {/* Mũi tên chỉ hướng theo Yaw */}
            <g transform={`rotate(${previewMarker.headingDeg})`}>
              <line
                x1={0}
                y1={0}
                x2={16}
                y2={0}
                stroke="#D97706"
                strokeWidth={2}
                strokeLinecap="round"
              />
              <polygon
                points="18,0 12,-4 12,4"
                fill="#D97706"
              />
            </g>
            {/* Nhãn điểm nháp */}
            <rect
              x={-28}
              y={-24}
              width={56}
              height={14}
              rx={3}
              fill="rgba(255, 255, 255, 0.95)"
              stroke="#F59E0B"
              strokeWidth={1}
            />
            <text
              x={0}
              y={-14}
              textAnchor="middle"
              fill="#B45309"
              fontSize={9}
              fontWeight="bold"
            >
              Điểm nháp
            </text>
          </g>
        )}

        {/* Marker Robot có hướng (đường kính ~18px cố định trên màn hình, không phóng to khi zoom) */}
        {robotMarker && (!isPassengerMode || passengerMapStatus === 'available') && (
          <g
            transform={`translate(${robotMarker.px}, ${robotMarker.py}) rotate(${robotMarker.deg}) scale(${markerScreenScale})`}
          >
            {/* Vòng hào quang robot */}
            <circle
              r={14}
              fill="#3B82F6"
              opacity={isLastKnown ? 0.1 : 0.25}
            />
            {/* Thân robot (bán kính 9px = đường kính 18px trên màn hình) */}
            <circle
              r={9}
              fill={isLastKnown ? '#64748B' : '#1D4ED8'}
              stroke="#FFFFFF"
              strokeWidth={1.5}
            />
            {/* Mũi tên chỉ hướng robot (đỉnh chỉ sang phải +X tại (15, 0)) */}
            <polygon
              points="15,0 2,-4.5 2,4.5"
              fill={isLastKnown ? '#94A3B8' : '#F59E0B'}
              stroke="#FFFFFF"
              strokeWidth={1}
            />
          </g>
        )}

        {/* Mũi tên định hướng tương tác RViz khi kéo-thả (Drag-to-Orient) */}
        {orienting && (
          <g className={styles.orientingGroup}>
            {/* Điểm ghim bắt đầu */}
            <circle
              cx={orienting.startPx}
              cy={orienting.startPy}
              r={6 * markerScreenScale}
              fill="#2563EB"
              stroke="#FFFFFF"
              strokeWidth={1.5 * markerScreenScale}
            />
            {orienting.screenDist >= 15 ? (
              <>
                {/* Đường thân mũi tên từ điểm bắt đầu đến con trỏ */}
                <line
                  x1={orienting.startPx}
                  y1={orienting.startPy}
                  x2={orienting.currentPx}
                  y2={orienting.currentPy}
                  stroke="#2563EB"
                  strokeWidth={3 * markerScreenScale}
                  strokeLinecap="round"
                />
                {/* Đầu mũi tên tại vị trí con trỏ */}
                <g
                  transform={`translate(${orienting.currentPx}, ${orienting.currentPy}) rotate(${orienting.headingDeg}) scale(${markerScreenScale})`}
                >
                  <polygon
                    points="0,0 -14,-7 -14,7"
                    fill="#2563EB"
                    stroke="#FFFFFF"
                    strokeWidth={1.5}
                  />
                </g>
                {/* Thẻ hiển thị góc Yaw */}
                <g
                  transform={`translate(${orienting.currentPx}, ${orienting.currentPy - 16 * markerScreenScale}) scale(${markerScreenScale})`}
                >
                  <rect
                    x={-24}
                    y={-14}
                    width={48}
                    height={16}
                    rx={4}
                    fill="rgba(15, 23, 42, 0.92)"
                    stroke="#2563EB"
                    strokeWidth={1}
                  />
                  <text
                    x={0}
                    y={-3}
                    textAnchor="middle"
                    fill="#FFFFFF"
                    fontSize={10}
                    fontWeight="bold"
                  >
                    {orienting.yawDeg}°
                  </text>
                </g>
              </>
            ) : (
              /* Vòng tròn gợi ý kéo chuột */
              <circle
                cx={orienting.startPx}
                cy={orienting.startPy}
                r={16 * markerScreenScale}
                fill="rgba(37, 99, 235, 0.15)"
                stroke="#2563EB"
                strokeWidth={1.5 * markerScreenScale}
                strokeDasharray={`${4 * markerScreenScale} ${2 * markerScreenScale}`}
              />
            )}
          </g>
        )}
      </svg>
    </div>
  );
};
