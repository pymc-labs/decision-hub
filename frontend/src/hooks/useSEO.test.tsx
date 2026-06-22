import { render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { useSEO } from "./useSEO";

function TestPage(props: Parameters<typeof useSEO>[0]) {
  useSEO(props);
  return null;
}

function getMeta(attr: "name" | "property", key: string): string | null {
  return (
    document
      .querySelector(`meta[${attr}="${key}"]`)
      ?.getAttribute("content") ?? null
  );
}

function getCanonical(): string | null {
  // Read the raw attribute — the .href property normalizes the URL (e.g.
  // appends a trailing slash to bare origins), which makes assertions brittle.
  return (
    document.querySelector('link[rel="canonical"]')?.getAttribute("href") ?? null
  );
}

describe("useSEO", () => {
  const originalTitle = document.title;

  beforeEach(() => {
    // Clear meta + canonical between tests so leftover state doesn't bleed.
    document.head
      .querySelectorAll(
        'meta[name="description"], meta[name^="twitter:"], meta[property^="og:"], link[rel="canonical"]',
      )
      .forEach((el) => el.remove());
  });

  afterEach(() => {
    document.title = originalTitle;
  });

  it("uses the current window origin for canonical and og:url", () => {
    const origin = window.location.origin;
    render(<TestPage title="Test" path="/skills/foo/bar" />);

    expect(getCanonical()).toBe(`${origin}/skills/foo/bar`);
    expect(getMeta("property", "og:url")).toBe(`${origin}/skills/foo/bar`);
  });

  it("does not leak the hardcoded prod URL into canonical on non-prod origins", () => {
    // jsdom defaults the origin to http://localhost — this asserts the fix:
    // canonical must NOT be the old hardcoded https://hub.decision.ai.
    render(<TestPage title="Test" />);
    expect(getCanonical()).not.toBe("https://hub.decision.ai");
    expect(getCanonical()).toBe(window.location.origin);
  });

  it("sets document title with the site suffix", () => {
    render(<TestPage title="My Page" />);
    expect(document.title).toBe("My Page | Decision Hub");
  });

  it("uses default title when none provided", () => {
    render(<TestPage />);
    expect(document.title).toBe("Decision Hub - Skill Registry for AI Agents");
  });

  it("writes og:title, og:description, and twitter:* tags", () => {
    render(<TestPage title="Skills" description="Browse skills" path="/skills" />);

    expect(getMeta("property", "og:title")).toBe("Skills | Decision Hub");
    expect(getMeta("property", "og:description")).toBe("Browse skills");
    expect(getMeta("name", "twitter:title")).toBe("Skills | Decision Hub");
    expect(getMeta("name", "twitter:description")).toBe("Browse skills");
    expect(getMeta("name", "description")).toBe("Browse skills");
  });

  it("injects and removes JSON-LD on mount/unmount", () => {
    const jsonLd = { "@context": "https://schema.org", "@type": "WebSite" };
    const { unmount } = render(<TestPage jsonLd={jsonLd} />);

    const tag = document.getElementById("seo-json-ld");
    expect(tag).not.toBeNull();
    expect(tag?.textContent).toContain('"@type":"WebSite"');

    unmount();
    expect(document.getElementById("seo-json-ld")).toBeNull();
  });

  it("restores defaults on unmount using the current origin", () => {
    const origin = window.location.origin;
    const { unmount } = render(<TestPage title="Detail" path="/x" />);
    unmount();

    expect(document.title).toBe("Decision Hub - Skill Registry for AI Agents");
    expect(getCanonical()).toBe(origin);
    expect(getMeta("property", "og:url")).toBe(origin);
  });
});
