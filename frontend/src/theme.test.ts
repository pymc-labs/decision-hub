import { describe, expect, it } from "vitest";
import { COLORS } from "./theme";

describe("theme", () => {
  it("exports all color tokens", () => {
    expect(COLORS.cream).toBe("hsl(35, 25%, 97%)");
    expect(COLORS.black).toBe("hsl(35, 0%, 15%)");
    expect(COLORS.olive).toBe("hsl(85, 15%, 45%)");
    expect(COLORS.terracotta).toBe("hsl(15, 45%, 55%)");
  });
});
