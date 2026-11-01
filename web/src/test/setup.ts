import "@testing-library/jest-dom/vitest"

// jsdom has no ResizeObserver; Radix checkboxes, switches and popovers measure with it.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver ??= ResizeObserverStub
