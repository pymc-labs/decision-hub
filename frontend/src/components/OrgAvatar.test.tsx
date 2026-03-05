import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import OrgAvatar from "./OrgAvatar";

describe("OrgAvatar", () => {
  it("renders image when avatarUrl provided", () => {
    render(<OrgAvatar avatarUrl="https://example.com/avatar.png" isPersonal={false} />);
    expect(screen.getByRole("img")).toBeInTheDocument();
  });

  it("renders fallback icon when no avatarUrl", () => {
    const { container } = render(<OrgAvatar avatarUrl={null} isPersonal={false} />);
    expect(container.querySelector("svg")).toBeInTheDocument();
  });
});
