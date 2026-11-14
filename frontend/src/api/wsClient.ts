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
  private currentToken: string | null = null;

  public isConnected = false;

  public connect(token: string | null = null): void {
    this.currentToken = token;
    this.isExplicitlyClosed = false;

    if (this.ws) {
      try {
        this.ws.close();
      } catch (e) {
        // ignore
      }
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

    try {
      this.ws = new WebSocket(wsUrl);

      this.ws.onopen = () => {
        this.isConnected = true;
        this.reconnectAttempts = 0;
        this.notifyStatus(true);
        this.startPing();
      };

      this.ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          this.notifyTelemetry(data);
        } catch (e) {
          console.warn('Lỗi phân tích cú pháp WebSocket message:', e);
        }
      };

      this.ws.onclose = () => {
        this.isConnected = false;
        this.stopPing();
        this.notifyStatus(false);

        if (!this.isExplicitlyClosed) {
          const delay = Math.min(1000 * Math.pow(1.5, this.reconnectAttempts), this.maxBackoffMs);
          this.reconnectAttempts++;
          setTimeout(() => {
            if (!this.isExplicitlyClosed) {
              this.connect(this.currentToken);
            }
          }, delay);
        }
      };

      this.ws.onerror = () => {
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
    this.stopPing();
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
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
