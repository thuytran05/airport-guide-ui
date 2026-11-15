import React, { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import { User, UserRole } from '../types';
import { apiClient, isTokenExpired } from '../api/client';

interface AuthContextType {
  currentUser: User;
  isAdmin: boolean;
  token: string | null;
  loginAdmin: (username: string, password: string) => Promise<{ success: boolean; message?: string }>;
  logout: () => void;
}

const DEFAULT_PASSENGER: User = {
  id: 'guest-passenger',
  username: 'passenger',
  fullName: 'Hành khách',
  role: 'passenger',
};

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [currentUser, setCurrentUser] = useState<User>(() => {
    const savedToken = localStorage.getItem('airport_robot_jwt');
    if (!savedToken || isTokenExpired(savedToken)) {
      try {
        localStorage.removeItem('airport_robot_jwt');
        localStorage.removeItem('airport_robot_user');
      } catch {
        // ignore
      }
      return DEFAULT_PASSENGER;
    }

    const savedUser = localStorage.getItem('airport_robot_user');
    if (savedUser) {
      try {
        const parsed = JSON.parse(savedUser);
        if (parsed.role === 'admin') return parsed;
      } catch (e) {
        // ignore
      }
    }
    return DEFAULT_PASSENGER;
  });

  const [token, setToken] = useState<string | null>(() => {
    const saved = localStorage.getItem('airport_robot_jwt');
    if (saved && isTokenExpired(saved)) {
      return null;
    }
    return saved;
  });

  useEffect(() => {
    const unsub = apiClient.onAuthError(() => {
      try {
        localStorage.removeItem('airport_robot_jwt');
        localStorage.removeItem('airport_robot_user');
      } catch {
        // ignore
      }
      setToken(null);
      setCurrentUser(DEFAULT_PASSENGER);
    });
    return unsub;
  }, []);

  useEffect(() => {
    if (token) {
      apiClient.setToken(token);
    } else {
      apiClient.clearToken();
    }
  }, [token]);

  const loginAdmin = async (username: string, password: string) => {
    try {
      const res = await apiClient.post<{
        access_token: string;
        user: { id: string; username: string; full_name: string; role: UserRole };
      }>('/api/auth/login', { username, password });

      const adminUser: User = {
        id: res.user.id,
        username: res.user.username,
        fullName: res.user.full_name,
        role: res.user.role,
      };

      setToken(res.access_token);
      setCurrentUser(adminUser);
      localStorage.setItem('airport_robot_jwt', res.access_token);
      localStorage.setItem('airport_robot_user', JSON.stringify(adminUser));
      return { success: true };
    } catch (err: any) {
      return {
        success: false,
        message: err.message || 'Tên đăng nhập hoặc mật khẩu không chính xác.',
      };
    }
  };

  const logout = () => {
    apiClient.clearToken();
    try {
      localStorage.removeItem('airport_robot_jwt');
      localStorage.removeItem('airport_robot_user');
    } catch {
      // ignore
    }
    setToken(null);
    setCurrentUser(DEFAULT_PASSENGER);
  };

  return (
    <AuthContext.Provider
      value={{
        currentUser,
        isAdmin: currentUser.role === 'admin',
        token,
        loginAdmin,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth phải được sử dụng bên trong AuthProvider');
  }
  return context;
}
