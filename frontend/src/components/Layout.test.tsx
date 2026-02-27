import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import Layout from "./Layout";

// Mock AskModal to avoid rendering the full modal in layout tests
vi.mock("./AskModal", () => ({
  default: ({ isOpen }: { isOpen: boolean }) =>
    isOpen ? <div data-testid="ask-modal">Ask Modal</div> : null,
}));

function renderLayout(initialPath = "/") {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Layout />
    </MemoryRouter>,
  );
}

describe("Layout", () => {
  it("renders the logo with link to home", () => {
    renderLayout();
    const logos = screen.getAllByText("Decision Hub");
    // Logo in header + brand in footer
    expect(logos.length).toBeGreaterThanOrEqual(2);
    const headerLogo = logos.find((el) => el.closest("a")?.getAttribute("href") === "/");
    expect(headerLogo).toBeDefined();
  });

  it("renders all navigation links", () => {
    renderLayout();
    expect(screen.getByText("Home")).toBeInTheDocument();
    expect(screen.getByText("Skills")).toBeInTheDocument();
    expect(screen.getByText("Organizations")).toBeInTheDocument();
    expect(screen.getByText("How it Works")).toBeInTheDocument();
    expect(screen.getByText("Ask")).toBeInTheDocument();
  });

  it("highlights active nav link for current path", () => {
    renderLayout("/skills");
    const skillsLink = screen.getByText("Skills").closest("a");
    expect(skillsLink?.className).toMatch(/navLinkActive/);
  });

  it("renders footer with brand and links", () => {
    renderLayout();
    const footerBrand = screen.getAllByText("Decision Hub").find(
      (el) => el.className.includes("footerBrand"),
    );
    expect(footerBrand).toBeDefined();
    expect(screen.getByText("PyMC Labs")).toBeInTheDocument();
    expect(screen.getByText("Terms")).toBeInTheDocument();
    expect(screen.getByText("Privacy")).toBeInTheDocument();
  });

  it("toggles mobile menu on button click", async () => {
    const user = userEvent.setup();
    renderLayout();
    const toggle = screen.getByLabelText("Open menu");
    await user.click(toggle);
    const closeBtn = screen.getByLabelText("Close menu");
    expect(closeBtn).toBeInTheDocument();
  });

  it("opens ask modal when Ask button is clicked", async () => {
    const user = userEvent.setup();
    renderLayout();
    const askBtn = screen.getByText("Ask");
    await user.click(askBtn);
    expect(screen.getByTestId("ask-modal")).toBeInTheDocument();
  });

  it("opens ask modal via custom event", async () => {
    renderLayout();
    window.dispatchEvent(new CustomEvent("open-ask-modal"));
    // The mock renders the modal when isOpen is true
    expect(await screen.findByTestId("ask-modal")).toBeInTheDocument();
  });
});
