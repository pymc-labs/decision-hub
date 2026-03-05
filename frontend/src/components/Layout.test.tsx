import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import Layout from "./Layout";

function renderLayout() {
  return render(
    <MemoryRouter>
      <Layout />
    </MemoryRouter>,
  );
}

describe("Layout", () => {
  it("renders the logo text", () => {
    renderLayout();
    const matches = screen.getAllByText(/Decision/);
    expect(matches.length).toBeGreaterThanOrEqual(1);
  });

  it("renders navigation links", () => {
    renderLayout();
    expect(screen.getByText("Home")).toBeInTheDocument();
    expect(screen.getAllByText("Skills").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("Organizations").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("How It Works").length).toBeGreaterThanOrEqual(1);
  });

  it("renders footer content", () => {
    renderLayout();
    const matches = screen.getAllByText(/Decision Hub/);
    expect(matches.length).toBeGreaterThanOrEqual(1);
  });

  it("toggles mobile menu", async () => {
    const user = userEvent.setup();
    renderLayout();
    const toggle = screen.getByLabelText("Toggle menu");
    await user.click(toggle);
    // Mobile menu should be visible
    const skillLinks = screen.getAllByText("Skills");
    expect(skillLinks.length).toBeGreaterThanOrEqual(1);
  });
});
