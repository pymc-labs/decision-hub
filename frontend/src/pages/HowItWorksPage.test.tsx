import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import HowItWorksPage from "./HowItWorksPage";

describe("HowItWorksPage", () => {
  it("renders the three act labels", () => {
    render(<MemoryRouter><HowItWorksPage /></MemoryRouter>);
    // Use exact text matching on the act label spans (not case-insensitive regex
    // which matches word fragments inside bullet text too)
    const labels = screen.getAllByText((_, el) =>
      el?.tagName === "SPAN" && el.className.includes("actLabel"),
    );
    const texts = labels.map((l) => l.textContent);
    expect(texts).toContain("DISCOVER");
    expect(texts).toContain("TRUST");
    expect(texts).toContain("SHIP");
  });

  it("renders feature cards", () => {
    render(<MemoryRouter><HowItWorksPage /></MemoryRouter>);
    const headings = screen.getAllByRole("heading");
    expect(headings.length).toBeGreaterThan(3);
  });
});
