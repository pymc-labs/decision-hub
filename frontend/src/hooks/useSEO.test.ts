import { renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { useSEO } from "./useSEO";

const DEFAULT_TITLE = "Decision Hub - Skill Registry for AI Agents";
const DEFAULT_DESCRIPTION =
  "Decision Hub is the skill registry for AI coding agents. Every skill is automatically evaluated in a sandbox, security-graded A through F, and searchable in natural language.";
const BASE_URL = "https://hub.decision.ai";
const JSON_LD_ID = "seo-json-ld";

function metaContent(attribute: "name" | "property", key: string): string | null {
  const el = document.querySelector<HTMLMetaElement>(
    `meta[${attribute}="${key}"]`,
  );
  return el?.getAttribute("content") ?? null;
}

function canonicalHref(): string | null {
  const el = document.querySelector<HTMLLinkElement>('link[rel="canonical"]');
  // Read the raw attribute, not the resolved `.href` — jsdom normalises
  // absolute-URL hrefs by appending a trailing slash, which would make
  // the assertion depend on browser URL-parsing quirks rather than what
  // the component actually wrote.
  return el?.getAttribute("href") ?? null;
}

function jsonLdContent(): string | null {
  const el = document.getElementById(JSON_LD_ID) as HTMLScriptElement | null;
  return el?.textContent ?? null;
}

describe("useSEO", () => {
  beforeEach(() => {
    document.head.innerHTML = "";
    document.title = "";
  });

  afterEach(() => {
    document.head.innerHTML = "";
    document.title = "";
  });

  it("sets document.title, meta description, OG, Twitter, canonical", () => {
    renderHook(() =>
      useSEO({
        title: "Skills",
        description: "Browse the registry",
        path: "/skills",
      }),
    );

    expect(document.title).toBe("Skills | Decision Hub");
    expect(metaContent("name", "description")).toBe("Browse the registry");
    expect(metaContent("property", "og:title")).toBe("Skills | Decision Hub");
    expect(metaContent("property", "og:description")).toBe("Browse the registry");
    expect(metaContent("property", "og:url")).toBe(`${BASE_URL}/skills`);
    expect(metaContent("name", "twitter:title")).toBe("Skills | Decision Hub");
    expect(metaContent("name", "twitter:description")).toBe("Browse the registry");
    expect(canonicalHref()).toBe(`${BASE_URL}/skills`);
  });

  it("falls back to defaults when title/description/path omitted", () => {
    renderHook(() => useSEO({}));

    expect(document.title).toBe(DEFAULT_TITLE);
    expect(metaContent("name", "description")).toBe(DEFAULT_DESCRIPTION);
    expect(canonicalHref()).toBe(BASE_URL);
  });

  it("restores defaults on unmount", () => {
    const { unmount } = renderHook(() =>
      useSEO({ title: "Page", description: "Body", path: "/x" }),
    );

    expect(document.title).toBe("Page | Decision Hub");

    unmount();

    expect(document.title).toBe(DEFAULT_TITLE);
    expect(metaContent("name", "description")).toBe(DEFAULT_DESCRIPTION);
    expect(canonicalHref()).toBe(BASE_URL);
  });

  it("injects JSON-LD as an application/ld+json script tag", () => {
    const ld = {
      "@context": "https://schema.org",
      "@type": "WebSite",
      name: "Test",
    };
    renderHook(() => useSEO({ path: "/", jsonLd: ld }));

    const el = document.getElementById(JSON_LD_ID) as HTMLScriptElement | null;
    expect(el).not.toBeNull();
    expect(el?.type).toBe("application/ld+json");
    expect(el?.textContent && JSON.parse(el.textContent)).toEqual(ld);
  });

  it("removes the JSON-LD script tag on unmount", () => {
    const { unmount } = renderHook(() =>
      useSEO({ path: "/", jsonLd: { a: 1 } }),
    );

    expect(document.getElementById(JSON_LD_ID)).not.toBeNull();

    unmount();

    expect(document.getElementById(JSON_LD_ID)).toBeNull();
  });

  it("does not re-run the effect when jsonLd is a fresh object with same content", () => {
    // Regression: the deps array used to include the jsonLd object
    // reference. Consumers that forgot to wrap the object in useMemo
    // would pass a new reference on every parent render — the effect
    // would re-run, its cleanup would flash the tags back to defaults
    // before writing them again, and the <script> tag would briefly
    // disappear. Guard by depending on the serialized JSON-LD.
    const initialLd = { "@type": "WebSite", name: "Test" };
    const { rerender } = renderHook(({ jsonLd }) => useSEO({ jsonLd }), {
      initialProps: { jsonLd: initialLd },
    });

    const scriptBefore = document.getElementById(JSON_LD_ID);
    expect(scriptBefore).not.toBeNull();
    const contentBefore = jsonLdContent();

    // Re-render with a NEW object reference but equivalent content.
    rerender({ jsonLd: { "@type": "WebSite", name: "Test" } });

    // Same physical element must survive — if the cleanup+re-run cycle
    // fired, the element would be a fresh one (identity !==).
    const scriptAfter = document.getElementById(JSON_LD_ID);
    expect(scriptAfter).toBe(scriptBefore);
    expect(jsonLdContent()).toBe(contentBefore);
  });

  it("does update JSON-LD when the content actually changes", () => {
    const { rerender } = renderHook(({ jsonLd }) => useSEO({ jsonLd }), {
      initialProps: { jsonLd: { "@type": "WebSite", name: "A" } },
    });

    expect(jsonLdContent() && JSON.parse(jsonLdContent()!)).toEqual({
      "@type": "WebSite",
      name: "A",
    });

    rerender({ jsonLd: { "@type": "WebSite", name: "B" } });

    expect(jsonLdContent() && JSON.parse(jsonLdContent()!)).toEqual({
      "@type": "WebSite",
      name: "B",
    });
  });
});
