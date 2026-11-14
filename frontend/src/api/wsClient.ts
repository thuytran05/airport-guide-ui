export type TelemetryCallback = (data: any) => void;
export type ConnectionStatusCallback = (isConnected: boolean) => void;

class WebSocketClient {
  private ws: WebSocket | null = null;
  private telemetryCallbacks: Set<TelemetryCallback> = new Set();
  private statusCallbacks: Set<ConnectionStatusCallback> = new Set();
  private reconnectAttempts = 0;
  private maxBackoffMs = 8000;
  private isExplicitlyClosed = false;
  private pingTimer: any = null;
  private reconnectTimer: any = null;
  private currentToken: string | null = null;
  private currentWsUrl: string | null = null;

  public isConnected = false;

  public connect(token: string | null = null): void {
    this.currentToken = token;
    this.isExplicitlyClosed = false;

    // Hủy bỏ bất kỳ timer reconnect nào đang chờ
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host;
    let effectiveToken = token;
    if (!effectiveToken && typeof window !== 'undefined') {
      try {
        effectiveToken = sessionStorage.getItem('airport_passenger_token');
      } catch {
        // ignore
      }
    }
    const query = effectiveToken ? `?token=${encodeURIComponent(effectiveToken)}` : '';
    const wsUrl = `${protocol}//${host}/ws${query}`;

    // Nếu socket hiện tại đã mở hoặc đang kết nối với cùng URL và token, giữ nguyên kết nối
    if (
      this.ws &&
      this.currentWsUrl === wsUrl &&
      (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)
    ) {
      return;
    }

    // Dọn dẹp socket cũ triệt để: tháo gỡ toàn bộ callbacks để tránh event rác bắn vào client
    if (this.ws) {
      const oldWs = this.ws;
      this.ws = null;
      oldWs.onopen = null;
      oldWs.onclose = null;
      oldWs.onerror = null;
      oldWs.onmessage = null;
      try {
        oldWs.close();
      } catch {
        // ignore
      }
    }

    this.currentWsUrl = wsUrl;

    try {
      const socket = new WebSocket(wsUrl);
      this.ws = socket;

      socket.onopen = () => {
        if (this.ws !== socket) return;
        this.isConnected = true;
        this.reconnectAttempts = 0;
        this.notifyStatus(true);
        this.startPing();
      };

      socket.onmessage = (event) => {
        if (this.ws !== socket) return;
        try {
          const data = JSON.parse(event.data);
          this.notifyTelemetry(data);
        } catch (e) {
          console.warn('Lỗi phân tích cú pháp WebSocket message:', e);
        }
      };

      socket.onclose = () => {
        // Bỏ qua nếu đây là socket cũ đã bị thay thế
        if (this.ws !== socket) return;

        this.isConnected = false;
        this.stopPing();
        this.notifyStatus(false);

        if (!this.isExplicitlyClosed) {
          if (this.reconnectTimer) {
            clearTimeout(this.reconnectTimer);
          }
          const delay = Math.min(1000 * Math.pow(1.5, this.reconnectAttempts), this.maxBackoffMs);
          this.reconnectAttempts++;
          this.reconnectTimer = setTimeout(() => {
            this.reconnectTimer = null;
            if (!this.isExplicitlyClosed) {
              this.connect(this.currentToken);
            }
          }, delay);
        }
      };

      socket.onerror = () => {
        if (this.ws !== socket) return;
        this.isConnected = false;
        this.notifyStatus(false);
      };
    } catch (e) {
      this.isConnected = false;
      this.notifyStatus(false);
    }
  }

  public authenticate(token: string) {
    this.currentToken = token;
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: 'authenticate', token }));
    } else {
      this.connect(token);
    }
  }

  public disconnect(): void {
    this.isExplicitlyClosed = true;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.stopPing();
    if (this.ws) {
      const oldWs = this.ws;
      this.ws = null;
      oldWs.onopen = null;
      oldWs.onclose = null;
      oldWs.onerror = null;
      oldWs.onmessage = null;
      try {
        oldWs.close();
      } catch {
        // ignore
      }
    }
    this.currentWsUrl = null;
    this.isConnected = false;
    this.notifyStatus(false);
  }

  private startPing(): void {
    this.stopPing();
    this.pingTimer = setInterval(() => {
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({ type: 'ping' }));
      }
    }, 15000);
  }

  private stopPing(): void {
    if (this.pingTimer) {
      clearInterval(this.pingTimer);
      this.pingTimer = null;
    }
  }

  public onTelemetry(cb: TelemetryCallback): () => void {
    this.telemetryCallbacks.add(cb);
    return () => this.telemetryCallbacks.delete(cb);
  }

  public onStatusChange(cb: ConnectionStatusCallback): () => void {
    this.statusCallbacks.add(cb);
    return () => this.statusCallbacks.delete(cb);
  }

  private notifyTelemetry(data: any): void {
    this.telemetryCallbacks.forEach((cb) => cb(data));
  }

  private notifyStatus(status: boolean): void {
    this.statusCallbacks.forEach((cb) => cb(status));
  }
}

export const wsClient = new WebSocketClient();
