import "@testing-library/jest-dom/vitest";

// JSDOM does not implement scrollIntoView — stub it globally for tests.
Element.prototype.scrollIntoView = () => {};

// JSDOM does not implement IntersectionObserver — provide a no-op stub
// that prevents components like AnimatedTerminal and useCountUp from crashing.
if (typeof globalThis.IntersectionObserver === "undefined") {
  globalThis.IntersectionObserver = class IntersectionObserver {
    constructor() {}
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof globalThis.IntersectionObserver;
}

// JSDOM does not implement the Clipboard API. Provide a mock so that
// components calling navigator.clipboard.writeText() don't crash.
// Individual tests can spy on this mock to verify clipboard writes.
if (!navigator.clipboard) {
  Object.defineProperty(navigator, "clipboard", {
    value: {
      writeText: () => Promise.resolve(),
      readText: () => Promise.resolve(""),
    },
    writable: true,
    configurable: true,
  });
}
