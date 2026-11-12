/**
 * REST API Client cho Airport Guide Robot
 * Dùng relative path '/api' để tự động định tuyến qua Vite proxy (dev) hoặc Nginx (prod).
 */

class ApiClient {
  private token: string | null = null;

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
