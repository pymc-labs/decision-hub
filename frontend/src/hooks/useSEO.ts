import { useEffect } from "react";

const SITE_NAME = "Decision Hub";
const PROD_URL = "https://hub.decision.ai";
const DEFAULT_DESCRIPTION =
  "Decision Hub is the skill registry for AI coding agents. Every skill is automatically evaluated in a sandbox, security-graded A through F, and searchable in natural language.";

// Use the live origin so dev (hub-dev.decision.ai) and local builds emit
// canonical/og:url tags that point at themselves instead of at prod.
// Falls back to the prod URL for non-browser contexts (tests, SSR).
function getBaseUrl(): string {
  if (typeof window !== "undefined" && window.location?.origin) {
    return window.location.origin;
  }
  return PROD_URL;
}

interface SEOProps {
  title?: string;
  description?: string;
  path?: string;
  /** JSON-LD structured data object to inject as a <script type="application/ld+json"> tag. */
  jsonLd?: Record<string, unknown>;
}

function setMetaTag(
  attribute: "name" | "property",
  key: string,
  content: string,
) {
  let el = document.querySelector(
    `meta[${attribute}="${key}"]`,
  ) as HTMLMetaElement | null;
  if (el) {
    el.setAttribute("content", content);
  } else {
    el = document.createElement("meta");
    el.setAttribute(attribute, key);
    el.setAttribute("content", content);
    document.head.appendChild(el);
  }
}

function setCanonical(url: string) {
  let el = document.querySelector(
    'link[rel="canonical"]',
  ) as HTMLLinkElement | null;
  if (el) {
    el.href = url;
  } else {
    el = document.createElement("link");
    el.rel = "canonical";
    el.href = url;
    document.head.appendChild(el);
  }
}

const JSON_LD_ID = "seo-json-ld";

function setJsonLd(data: Record<string, unknown> | undefined) {
  let el = document.getElementById(JSON_LD_ID) as HTMLScriptElement | null;
  if (!data) {
    el?.remove();
    return;
  }
  if (!el) {
    el = document.createElement("script");
    el.id = JSON_LD_ID;
    el.type = "application/ld+json";
    document.head.appendChild(el);
  }
  el.textContent = JSON.stringify(data);
}

/**
 * Lightweight SEO hook that manages document title, meta description,
 * Open Graph tags, Twitter Card tags, canonical URL, and JSON-LD structured data.
 *
 * Call once per page component. Tags are restored to defaults on unmount.
 */
export function useSEO({ title, description, path, jsonLd }: SEOProps) {
  useEffect(() => {
    const baseUrl = getBaseUrl();
    const fullTitle = title ? `${title} | ${SITE_NAME}` : `${SITE_NAME} - Skill Registry for AI Agents`;
    const desc = description ?? DEFAULT_DESCRIPTION;
    const url = path ? `${baseUrl}${path}` : baseUrl;

    document.title = fullTitle;

    // Standard meta
    setMetaTag("name", "description", desc);

    // Open Graph
    setMetaTag("property", "og:title", fullTitle);
    setMetaTag("property", "og:description", desc);
    setMetaTag("property", "og:url", url);

    // Twitter Card
    setMetaTag("name", "twitter:title", fullTitle);
    setMetaTag("name", "twitter:description", desc);

    // Canonical
    setCanonical(url);

    // JSON-LD
    setJsonLd(jsonLd);

    return () => {
      // Restore defaults on unmount so navigating away resets
      document.title = `${SITE_NAME} - Skill Registry for AI Agents`;
      setMetaTag("name", "description", DEFAULT_DESCRIPTION);
      setMetaTag("property", "og:title", `${SITE_NAME} - Skill Registry for AI Agents`);
      setMetaTag("property", "og:description", DEFAULT_DESCRIPTION);
      setMetaTag("property", "og:url", baseUrl);
      setMetaTag("name", "twitter:title", `${SITE_NAME} - Skill Registry for AI Agents`);
      setMetaTag("name", "twitter:description", DEFAULT_DESCRIPTION);
      setCanonical(baseUrl);
      setJsonLd(undefined);
    };
  }, [title, description, path, jsonLd]);
}
