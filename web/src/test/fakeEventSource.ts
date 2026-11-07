// A stand-in for EventSource in tests: records every stream opened and lets a test push frames or errors.
export class FakeEventSource {
  static all: FakeEventSource[] = []
  static get last(): FakeEventSource | null {
    return FakeEventSource.all[FakeEventSource.all.length - 1] ?? null
  }
  static reset() {
    FakeEventSource.all = []
  }
  onopen: (() => void) | null = null
  onmessage: ((m: MessageEvent) => void) | null = null
  onerror: (() => void) | null = null
  closed = false
  listeners: Record<string, ((m: MessageEvent) => void)[]> = {}
  constructor(public url: string) {
    FakeEventSource.all.push(this)
  }
  addEventListener(type: string, fn: (m: MessageEvent) => void) {
    ;(this.listeners[type] ??= []).push(fn)
  }
  close() {
    this.closed = true
  }
  emit(type: string, data: object, id = "") {
    const m = new MessageEvent(type, { data: JSON.stringify(data), lastEventId: id })
    this.listeners[type]?.forEach((f) => f(m))
  }
  fail() {
    this.onerror?.()
  }
}
