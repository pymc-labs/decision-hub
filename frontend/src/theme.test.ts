import { describe, expect, it } from "vitest";
import { COLORS, FONTS, GRADE_COLORS } from "./theme";

describe("theme", () => {
  it("exports all color tokens", () => {
    expect(COLORS.cream).toBe("hsl(35, 25%, 97%)");
    expect(COLORS.black).toBe("hsl(35, 0%, 15%)");
    expect(COLORS.olive).toBe("hsl(85, 15%, 45%)");
    expect(COLORS.terracotta).toBe("hsl(15, 45%, 55%)");
  });

  it("exports font families", () => {
    expect(FONTS.serif).toContain("Newsreader");
    expect(FONTS.sans).toContain("Inter");
    expect(FONTS.mono).toContain("IBM Plex Mono");
  });

  it("maps grade letters to editorial colors", () => {
    expect(GRADE_COLORS.A).toBe("olive");
    expect(GRADE_COLORS.B).toBe("charcoal");
    expect(GRADE_COLORS.C).toBe("terracotta");
    expect(GRADE_COLORS.F).toBe("destructive");
    expect(GRADE_COLORS.pending).toBe("muted");
  });
});
