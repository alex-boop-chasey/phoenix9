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

// The build wizard keeps its answers per project in localStorage; no test should see another's.
afterEach(() => {
  try {
    for (const k of Object.keys(localStorage)) if (k.startsWith("phoenix9.wizard.")) localStorage.removeItem(k)
  } catch {
    // no storage
  }
})
