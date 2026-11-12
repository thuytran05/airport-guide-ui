import React from 'react';

export const AirportMapSvg: React.FC<{ className?: string }> = ({ className }) => {
  return (
    <svg
      viewBox="0 0 800 500"
      className={className}
      style={{ width: '100%', height: '100%', display: 'block', backgroundColor: '#F8FAFC' }}
      xmlns="http://www.w3.org/2000/svg"
    >
      <defs>
        <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
          <path d="M 40 0 L 0 0 0 40" fill="none" stroke="#E2E8F0" strokeWidth="1" />
        </pattern>
      </defs>

      {/* Grid background */}
      <rect width="800" height="500" fill="url(#grid)" />

      {/* Terminal Outline */}
      <rect
        x="40"
        y="30"
        width="720"
        height="440"
        rx="16"
        fill="#FFFFFF"
        stroke="#94A3B8"
        strokeWidth="3"
        filter="drop-shadow(0 2px 8px rgba(0,0,0,0.06))"
      />

      {/* Main Corridor */}
      <rect x="70" y="210" width="660" height="80" rx="8" fill="#F1F5F9" stroke="#CBD5E1" strokeWidth="2" strokeDasharray="6 4" />
      <text x="85" y="255" fill="#94A3B8" fontSize="13" fontWeight="600" letterSpacing="2">
        HÀNH LANG TRUNG TÂM (CHÍNH)
      </text>

      {/* Top Gates Wing A */}
      <rect x="70" y="50" width="450" height="110" rx="8" fill="#EFF6FF" stroke="#BFDBFE" strokeWidth="1.5" />
      <text x="85" y="72" fill="#1D4ED8" fontSize="13" fontWeight="bold">KHU VỰC CỔNG A (CÁNH BẮC)</text>

      {/* Gate boxes */}
      {/* Gate A1 */}
      <rect x="90" y="85" width="60" height="55" rx="6" fill="#DBEAFE" stroke="#3B82F6" strokeWidth="1.5" />
      <text x="120" y="117" textAnchor="middle" fill="#1E40AF" fontSize="14" fontWeight="bold">A1</text>

      {/* Gate A2 */}
      <rect x="200" y="85" width="60" height="55" rx="6" fill="#DBEAFE" stroke="#3B82F6" strokeWidth="1.5" />
      <text x="230" y="117" textAnchor="middle" fill="#1E40AF" fontSize="14" fontWeight="bold">A2</text>

      {/* Gate A3 */}
      <rect x="310" y="85" width="60" height="55" rx="6" fill="#DBEAFE" stroke="#3B82F6" strokeWidth="1.5" />
      <text x="340" y="117" textAnchor="middle" fill="#1E40AF" fontSize="14" fontWeight="bold">A3</text>

      {/* Gate A5 */}
      <rect x="420" y="85" width="60" height="55" rx="6" fill="#DBEAFE" stroke="#3B82F6" strokeWidth="1.5" />
      <text x="450" y="117" textAnchor="middle" fill="#1E40AF" fontSize="14" fontWeight="bold">A5</text>

      {/* Bottom Gates Wing B */}
      <rect x="70" y="340" width="450" height="110" rx="8" fill="#EFF6FF" stroke="#BFDBFE" strokeWidth="1.5" />
      <text x="85" y="362" fill="#1D4ED8" fontSize="13" fontWeight="bold">KHU VỰC CỔNG B (CÁNH NAM)</text>

      {/* Gate B1 */}
      <rect x="90" y="375" width="60" height="55" rx="6" fill="#DBEAFE" stroke="#3B82F6" strokeWidth="1.5" />
      <text x="120" y="407" textAnchor="middle" fill="#1E40AF" fontSize="14" fontWeight="bold">B1</text>

      {/* Gate B2 */}
      <rect x="200" y="375" width="60" height="55" rx="6" fill="#DBEAFE" stroke="#3B82F6" strokeWidth="1.5" />
      <text x="230" y="407" textAnchor="middle" fill="#1E40AF" fontSize="14" fontWeight="bold">B2</text>

      {/* Gate B3 */}
      <rect x="310" y="375" width="60" height="55" rx="6" fill="#DBEAFE" stroke="#3B82F6" strokeWidth="1.5" />
      <text x="340" y="407" textAnchor="middle" fill="#1E40AF" fontSize="14" fontWeight="bold">B3</text>

      {/* Food area */}
      <rect x="360" y="220" width="85" height="60" rx="6" fill="#FEF3C7" stroke="#F59E0B" strokeWidth="1.5" />
      <text x="402" y="246" textAnchor="middle" fill="#B45309" fontSize="11" fontWeight="bold">🍽️ Ăn uống</text>
      <text x="402" y="262" textAnchor="middle" fill="#92400E" fontSize="10">Khu ẩm thực</text>

      {/* WC A & B */}
      <rect x="475" y="95" width="55" height="45" rx="4" fill="#F3E8FF" stroke="#A855F7" strokeWidth="1" />
      <text x="502" y="122" textAnchor="middle" fill="#7E22CE" fontSize="11" fontWeight="bold">🚻 WC A</text>

      <rect x="475" y="360" width="55" height="45" rx="4" fill="#F3E8FF" stroke="#A855F7" strokeWidth="1" />
      <text x="502" y="387" textAnchor="middle" fill="#7E22CE" fontSize="11" fontWeight="bold">🚻 WC B</text>

      {/* Check-in Zone */}
      <rect x="550" y="160" width="100" height="180" rx="8" fill="#ECFDF5" stroke="#10B981" strokeWidth="1.5" />
      <text x="600" y="185" textAnchor="middle" fill="#047857" fontSize="12" fontWeight="bold">QUẦY CHECK-IN</text>
      <line x1="560" y1="205" x2="640" y2="205" stroke="#6EE7B7" strokeWidth="1" strokeDasharray="3 3" />
      <line x1="560" y1="240" x2="640" y2="240" stroke="#6EE7B7" strokeWidth="1" strokeDasharray="3 3" />
      <line x1="560" y1="275" x2="640" y2="275" stroke="#6EE7B7" strokeWidth="1" strokeDasharray="3 3" />
      <text x="600" y="315" textAnchor="middle" fill="#065F46" fontSize="10">Quầy thủ tục 1-5</text>

      {/* Info Desk */}
      <rect x="660" y="220" width="45" height="60" rx="6" fill="#E0F2FE" stroke="#0284C7" strokeWidth="1.5" />
      <text x="682" y="246" textAnchor="middle" fill="#0369A1" fontSize="12" fontWeight="bold">ℹ️</text>
      <text x="682" y="263" textAnchor="middle" fill="#075985" fontSize="9" fontWeight="bold">Thông tin</text>

      {/* Exit */}
      <rect x="715" y="215" width="35" height="70" rx="4" fill="#FEE2E2" stroke="#EF4444" strokeWidth="1.5" />
      <text x="732" y="255" textAnchor="middle" fill="#B91C1C" fontSize="10" fontWeight="bold" transform="rotate(-90 732 255)">
        LỐI RA
      </text>

      {/* Legend / Mock disclaimer */}
      <rect x="50" y="445" width="220" height="22" rx="4" fill="#FFFBEB" stroke="#FDE68A" strokeWidth="1" />
      <text x="60" y="460" fill="#D97706" fontSize="10" fontWeight="bold">
        ⚠️ Sơ đồ minh họa — không phải bản đồ thật
      </text>
    </svg>
  );
};
