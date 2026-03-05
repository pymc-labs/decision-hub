import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeAll, describe, expect, it, vi } from "vitest";
import AskModal from "./AskModal";

beforeAll(() => {
  // jsdom does not implement scrollIntoView
  Element.prototype.scrollIntoView = vi.fn();
});

describe("AskModal", () => {
  it("renders input field", () => {
    render(<MemoryRouter><AskModal isOpen onClose={vi.fn()} /></MemoryRouter>);
    expect(screen.getByRole("textbox")).toBeInTheDocument();
  });

  it("calls onClose when close button clicked", async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(<MemoryRouter><AskModal isOpen onClose={onClose} /></MemoryRouter>);
    const closeBtn = screen.getByLabelText("Close");
    await user.click(closeBtn);
    expect(onClose).toHaveBeenCalled();
  });

  it("renders suggestion buttons", () => {
    render(<MemoryRouter><AskModal isOpen onClose={vi.fn()} /></MemoryRouter>);
    const buttons = screen.getAllByRole("button");
    expect(buttons.length).toBeGreaterThan(1);
  });
});
