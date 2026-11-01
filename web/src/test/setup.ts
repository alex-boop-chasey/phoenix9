import "@testing-library/jest-dom/vitest"

// jsdom has no ResizeObserver; Radix checkboxes, switches and popovers measure with it.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver ??= ResizeObserverStub

// jsdom lacks the pointer-capture and scroll calls Radix Select makes when it opens.
Element.prototype.hasPointerCapture ??= () => false
Element.prototype.releasePointerCapture ??= () => {}
Element.prototype.scrollIntoView ??= () => {}
