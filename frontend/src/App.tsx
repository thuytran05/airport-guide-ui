import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider } from './contexts/AuthContext';
import { RobotProvider } from './contexts/RobotContext';
import { RouteGuard } from './router/RouteGuard';
import AppLayout from './layouts/AppLayout';

import Login from './pages/Login';
import PassengerHome from './pages/passenger/Home';
import AdminDashboard from './pages/admin/Dashboard';

export default function App() {
  return (
    <AuthProvider>
      <RobotProvider>
        <BrowserRouter>
          <Routes>
            {/* Đăng nhập Admin */}
            <Route path="/login" element={<Login />} />

            {/* Khung giao diện chính */}
            <Route element={<AppLayout />}>
              {/* Trang mặc định công khai: Hành khách */}
              <Route path="/" element={<PassengerHome />} />

              {/* Trang quản trị: Cần đăng nhập Admin */}
              <Route element={<RouteGuard />}>
                <Route path="/admin" element={<AdminDashboard />} />
              </Route>
            </Route>

            {/* Fallback chuyển về trang chủ */}
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
      </RobotProvider>
    </AuthProvider>
  );
}
