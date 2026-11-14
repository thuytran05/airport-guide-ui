/**
 * REST API Client cho Airport Guide Robot
 * Dùng relative path '/api' để tự động định tuyến qua Vite proxy (dev) hoặc Nginx (prod).
 */

class ApiClient {
  private token: string | null = null;
  private passengerToken: string | null = null;
  private tokenPromise: Promise<string | null> | null = null;

  constructor() {
    try {
      if (typeof window !== 'undefined') {
        this.passengerToken = sessionStorage.getItem('airport_passenger_token');
      }
    } catch {
      // ignore storage errors
    }
  }

  async ensurePassengerToken(): Promise<string | null> {
    if (this.passengerToken) return this.passengerToken;
    if (typeof window === 'undefined') return null;

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
              sessionStorage.setItem('airport_passenger_token', data.session_token);
              return data.session_token;
            }
          }
        } catch {
          // ignore
        }
        return null;
      })();
    }
    return this.tokenPromise;
  }

  getStoredPassengerToken(): string | null {
    if (this.passengerToken) return this.passengerToken;
    try {
      if (typeof window !== 'undefined') {
        return sessionStorage.getItem('airport_passenger_token');
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
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      ...((options.headers as Record<string, string>) || {}),
    };

    if (this.token) {
      headers['Authorization'] = `Bearer ${this.token}`;
    } else if (!endpoint.includes('/api/auth/session')) {
      const pToken = await this.ensurePassengerToken();
      if (pToken) {
        headers['X-Passenger-Token'] = pToken;
      }
    }

    const url = endpoint.startsWith('/') ? endpoint : `/${endpoint}`;

    try {
      const response = await fetch(url, { ...options, headers });

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
