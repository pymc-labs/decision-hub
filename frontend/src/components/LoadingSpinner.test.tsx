import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import LoadingSpinner from "./LoadingSpinner";

describe("LoadingSpinner", () => {
  it("renders with default message", () => {
    render(<LoadingSpinner />);
    expect(screen.getByText(/loading/i)).toBeInTheDocument();
  });

  it("renders with custom message", () => {
    render(<LoadingSpinner text="Fetching data" />);
    expect(screen.getByText("Fetching data")).toBeInTheDocument();
  });
});
