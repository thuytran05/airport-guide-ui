/**
 * REST API Client cho Airport Guide Robot
 * Dùng relative path '/api' để tự động định tuyến qua Vite proxy (dev) hoặc Nginx (prod).
 */

export function isTokenExpired(token: string | null): boolean {
  if (!token) return true;
  try {
    const parts = token.split('.');
    if (parts.length !== 3) return true;
    let base64 = parts[1].replace(/-/g, '+').replace(/_/g, '/');
    while (base64.length % 4) {
      base64 += '=';
    }
    const json = decodeURIComponent(
      atob(base64)
        .split('')
        .map((c) => '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2))
        .join('')
    );
    const payload = JSON.parse(json);
    if (typeof payload.exp === 'number') {
      return Date.now() >= (payload.exp - 5) * 1000;
    }
    return false;
  } catch {
    return true;
  }
}

class ApiClient {
  private token: string | null = null;
  private passengerToken: string | null = null;
  private tokenPromise: Promise<string | null> | null = null;
  private authErrorListeners: Set<() => void> = new Set();

  constructor() {
    try {
      if (typeof window !== 'undefined') {
        const stored = sessionStorage.getItem('airport_passenger_token');
        if (stored && !isTokenExpired(stored)) {
          this.passengerToken = stored;
        }
      }
    } catch {
      // ignore storage errors
    }
  }

  onAuthError(cb: () => void): () => void {
    this.authErrorListeners.add(cb);
    return () => this.authErrorListeners.delete(cb);
  }

  notifyAuthError(): void {
    for (const cb of this.authErrorListeners) {
      try {
        cb();
      } catch (e) {
        console.error('Lỗi khi thực thi AuthError callback:', e);
      }
    }
  }

  async ensurePassengerToken(forceRefresh = false): Promise<string | null> {
    if (!forceRefresh && this.passengerToken && !isTokenExpired(this.passengerToken)) {
      return this.passengerToken;
    }
    if (typeof window === 'undefined') return null;

    if (forceRefresh) {
      this.passengerToken = null;
      try {
        sessionStorage.removeItem('airport_passenger_token');
      } catch {
        // ignore
      }
    }

    if (!this.tokenPromise) {
      this.tokenPromise = (async () => {
        try {
          const res = await fetch('/api/auth/session', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
          });
          if (res.ok) {
            const data = await res.json();
            if (data && data.session_token) {
              this.passengerToken = data.session_token;
              try {
                sessionStorage.setItem('airport_passenger_token', data.session_token);
              } catch {
                // ignore
              }
              return data.session_token;
            }
          }
        } catch (err) {
          console.warn('Không thể tạo phiên hành khách:', err);
        } finally {
          this.tokenPromise = null;
        }
        return null;
      })();
    }
    return this.tokenPromise;
  }

  getStoredPassengerToken(): string | null {
    if (this.passengerToken && !isTokenExpired(this.passengerToken)) {
      return this.passengerToken;
    }
    try {
      if (typeof window !== 'undefined') {
        const stored = sessionStorage.getItem('airport_passenger_token');
        if (stored && !isTokenExpired(stored)) {
          this.passengerToken = stored;
          return stored;
        }
      }
    } catch {
      // ignore
    }
    return null;
  }

  setToken(t: string) {
    this.token = t;
  }

  clearToken() {
    this.token = null;
  }

  private async request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
    // 1. Kiểm tra hạn token Admin trước khi gửi
    if (this.token && isTokenExpired(this.token)) {
      this.token = null;
      this.notifyAuthError();
    }

    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      ...((options.headers as Record<string, string>) || {}),
    };

    if (this.token) {
      headers['Authorization'] = `Bearer ${this.token}`;
    } else if (!endpoint.includes('/api/auth/session') && !endpoint.includes('/api/auth/login')) {
      const pToken = await this.ensurePassengerToken();
      if (pToken) {
        headers['X-Passenger-Token'] = pToken;
      }
    }

    const url = endpoint.startsWith('/') ? endpoint : `/${endpoint}`;

    try {
      let response = await fetch(url, { ...options, headers });

      // 2. Xử lý khi Backend trả về 401 Unauthorized
      if (response.status === 401) {
        if (this.token) {
          this.token = null;
          this.notifyAuthError();
        }

        const isAdminPage =
          typeof window !== 'undefined' &&
          (window.location.pathname.startsWith('/admin') || window.location.pathname.startsWith('/login'));

        if (isAdminPage) {
          let errorDetail = 'Phiên làm việc đã hết hạn. Vui lòng đăng nhập lại.';
          try {
            const data = await response.json();
            if (data && data.detail) errorDetail = data.detail;
          } catch {
            // ignore
          }
          throw new Error(errorDetail);
        }

        // Với giao diện hành khách, tự động lấy lại session_token mới và thử lại 1 lần duy nhất
        const newPassengerToken = await this.ensurePassengerToken(true);
        if (newPassengerToken) {
          const retryHeaders: Record<string, string> = {
            ...headers,
            'X-Passenger-Token': newPassengerToken,
          };
          delete retryHeaders['Authorization'];
          response = await fetch(url, { ...options, headers: retryHeaders });
        }
      }

      if (!response.ok) {
        let errorDetail = `Lỗi hệ thống (${response.status})`;
        try {
          const data = await response.json();
          if (data && data.detail) errorDetail = data.detail;
        } catch {
          // ignore
        }
        throw new Error(errorDetail);
      }

      return (await response.json()) as T;
    } catch (err: any) {
      if (err.message.includes('Failed to fetch') || err.name === 'TypeError') {
        throw new Error('Không thể kết nối tới máy chủ Backend.');
      }
      throw err;
    }
  }

  get<T>(endpoint: string): Promise<T> {
    return this.request<T>(endpoint, { method: 'GET' });
  }

  post<T>(endpoint: string, body?: any): Promise<T> {
    return this.request<T>(endpoint, {
      method: 'POST',
      body: body ? JSON.stringify(body) : undefined,
    });
  }

  put<T>(endpoint: string, body?: any): Promise<T> {
    return this.request<T>(endpoint, {
      method: 'PUT',
      body: body ? JSON.stringify(body) : undefined,
    });
  }

  delete<T>(endpoint: string): Promise<T> {
    return this.request<T>(endpoint, { method: 'DELETE' });
  }
}

export const apiClient = new ApiClient();
