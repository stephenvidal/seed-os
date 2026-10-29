/** Minimal EventSource stand-in: tests push events through `emit` and `end`. */
export class FakeEventSource {
  static last: FakeEventSource | undefined;
  onmessage: ((m: MessageEvent<string>) => void) | null = null;
  closed = false;
  private listeners: Record<string, () => void> = {};
  constructor(readonly url: string) {
    FakeEventSource.last = this;
  }
  addEventListener(type: string, fn: () => void) {
    this.listeners[type] = fn;
  }
  close() {
    this.closed = true;
  }
  emit(seq: number, type: string, data: Record<string, unknown> = {}, attempt = 1) {
    const payload = { seq, attempt, type, data, created_at: "2026-10-28T22:00:01Z" };
    this.onmessage?.(new MessageEvent("message", { data: JSON.stringify(payload) }));
  }
  end() {
    this.listeners.end?.();
  }
}
