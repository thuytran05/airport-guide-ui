import React from 'react';
import { Outlet, NavLink, useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { useRobot } from '../contexts/RobotContext';
import styles from './AppLayout.module.css';

export default function AppLayout() {
  const { currentUser, isAdmin, logout } = useAuth();
  const { isBackendConnected, status } = useRobot();
  const navigate = useNavigate();

  return (
    <div className={styles.layout}>
      <header className={styles.header}>
        <div className={styles.brand}>
          <div className={styles.logoIcon}>🤖</div>
          <div>
            <h1 className={styles.appTitle}>AIRPORT GUIDE ROBOT</h1>
            <p className={styles.appSubtitle}>Hệ Thống Dẫn Đường Sân Bay Thông Minh</p>
          </div>
        </div>

        {/* Thanh chuyển đổi màn hình */}
        <nav className={styles.nav}>
          <NavLink
            to="/"
            className={({ isActive }) => `${styles.navLink} ${isActive ? styles.active : ''}`}
            end
          >
            Hành Khách
          </NavLink>
          <NavLink
            to="/admin"
            className={({ isActive }) => `${styles.navLink} ${isActive ? styles.active : ''}`}
          >
            Quản Trị Hệ Thống {isAdmin ? '' : '🔒'}
          </NavLink>
        </nav>

        {/* Trạng thái kết nối và người dùng */}
        <div className={styles.statusArea}>
          <div className={styles.connectionBadges}>
            <span
              className={`${styles.badge} ${isBackendConnected ? styles.ok : styles.error}`}
              title="Kết nối giữa Trình duyệt và Backend API"
            >
              Gateway: {isBackendConnected ? 'OK' : 'Mất'}
            </span>
            <span
              className={`${styles.badge} ${status.isConnected ? styles.ok : styles.warn}`}
              title="Kết nối giữa Backend và Robot ROS 2"
            >
              Robot: {status.isConnected ? 'OK' : 'Chưa kết nối'}
            </span>
          </div>

          <div className={styles.authInfo}>
            {isAdmin ? (
              <div className={styles.userBox}>
                <span className={styles.userName}>Admin</span>
                <button onClick={logout} className={styles.logoutBtn}>
                  Đăng xuất
                </button>
              </div>
            ) : (
              <button onClick={() => navigate('/login')} className={styles.loginBtn}>
                Đăng nhập Admin
              </button>
            )}
          </div>
        </div>
      </header>

      <main className={styles.content}>
        <Outlet />
      </main>
    </div>
  );
}
