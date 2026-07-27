import type { AppSnapshot } from "../types";

export type SentMessage = {
  version: number;
  type: string;
  request_id?: string;
  payload: unknown;
};

export class FakeWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static latest: FakeWebSocket | null = null;
  static instances: FakeWebSocket[] = [];

  readyState = FakeWebSocket.CONNECTING;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  sent: SentMessage[] = [];

  constructor(
    private readonly options: {
      initialSnapshot?: AppSnapshot;
      connectDelayMs?: number;
      autoReply?: (message: SentMessage) => void;
    } = {},
  ) {
    FakeWebSocket.latest = this;
    FakeWebSocket.instances.push(this);
    const delay = options.connectDelayMs ?? 0;
    window.setTimeout(() => {
      this.readyState = FakeWebSocket.OPEN;
      this.onopen?.();
      if (options.initialSnapshot) {
        this.emit("app.snapshot", options.initialSnapshot);
      }
    }, delay);
  }

  send(data: string) {
    if (this.readyState !== FakeWebSocket.OPEN) return;
    const message = JSON.parse(data) as SentMessage;
    this.sent.push(message);
    this.options.autoReply?.(message);
  }

  close() {
    this.onclose?.();
  }

  emit(type: string, payload: unknown, request_id?: string) {
    this.onmessage?.({
      data: JSON.stringify({ version: 1, type, payload, request_id }),
    });
  }

  emitError(request_id: string, error: string) {
    this.emit("error", { error }, request_id);
  }

  disconnect() {
    this.onclose?.();
  }
}

let installOptions: ConstructorParameters<typeof FakeWebSocket>[0] = {};

export function installFakeWebSocket(options?: ConstructorParameters<typeof FakeWebSocket>[0]) {
  installOptions = options ?? {};
  class WebSocketCtor extends FakeWebSocket {
    constructor() {
      super(installOptions);
    }
  }
  Object.assign(WebSocketCtor, { OPEN: FakeWebSocket.OPEN, CONNECTING: FakeWebSocket.CONNECTING });
  Object.defineProperty(globalThis, "WebSocket", {
    writable: true,
    configurable: true,
    value: WebSocketCtor,
  });
  FakeWebSocket.latest = null;
  FakeWebSocket.instances = [];
  return FakeWebSocket;
}
