import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ErrorBoundary from "./ErrorBoundary";

// Annotated as `ReactNode` so it satisfies the JSX component contract — TS
// would otherwise infer `void` from the unconditional throw.
function Boom({ message = "kaboom" }: { message?: string }): ReactNode {
  throw new Error(message);
}

describe("ErrorBoundary", () => {
  // React + jsdom log caught errors as console.error. Silence them so test
  // output stays clean, but keep the spy so we can assert on logging.
  let consoleSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    consoleSpy.mockRestore();
  });

  it("renders children when no error is thrown", () => {
    render(
      <ErrorBoundary>
        <div>healthy content</div>
      </ErrorBoundary>,
    );
    expect(screen.getByText("healthy content")).toBeInTheDocument();
  });

  it("shows the fallback UI when a child throws", () => {
    render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>,
    );

    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByText(/Something went wrong/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /reload/i })).toBeInTheDocument();
  });

  it("logs the captured error so it surfaces in dev tools", () => {
    render(
      <ErrorBoundary>
        <Boom message="trackable-failure" />
      </ErrorBoundary>,
    );

    const logged = consoleSpy.mock.calls.some((call) =>
      call.some(
        (arg) =>
          arg instanceof Error
            ? arg.message === "trackable-failure"
            : typeof arg === "string" && arg.includes("ErrorBoundary"),
      ),
    );
    expect(logged).toBe(true);
  });

  it("calls window.location.reload when the reload button is clicked", async () => {
    // jsdom's location.reload is a no-op getter; replace just for this test.
    const originalLocation = window.location;
    const reload = vi.fn();
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { ...originalLocation, reload },
    });

    try {
      const user = userEvent.setup();
      render(
        <ErrorBoundary>
          <Boom />
        </ErrorBoundary>,
      );

      await user.click(screen.getByRole("button", { name: /reload/i }));
      expect(reload).toHaveBeenCalledTimes(1);
    } finally {
      Object.defineProperty(window, "location", {
        configurable: true,
        value: originalLocation,
      });
    }
  });

  it("renders a custom fallback when provided", () => {
    render(
      <ErrorBoundary fallback={<div>custom fallback</div>}>
        <Boom />
      </ErrorBoundary>,
    );
    expect(screen.getByText("custom fallback")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /reload/i })).not.toBeInTheDocument();
  });
});
