import { useEffect } from "react";

const SITE_NAME = "Decision Hub";
const BASE_URL = "https://decisionhub.dev";
const DEFAULT_DESCRIPTION =
  "Decision Hub is the skill registry for data science agents. Discover, install, and share executable skills with built-in safety grading and automated evaluations.";

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
    const fullTitle = title ? `${title} | ${SITE_NAME}` : `${SITE_NAME} - Skill Registry for AI Agents`;
    const desc = description ?? DEFAULT_DESCRIPTION;
    const url = path ? `${BASE_URL}${path}` : BASE_URL;

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
      setMetaTag("property", "og:url", BASE_URL);
      setMetaTag("name", "twitter:title", `${SITE_NAME} - Skill Registry for AI Agents`);
      setMetaTag("name", "twitter:description", DEFAULT_DESCRIPTION);
      setCanonical(BASE_URL);
      setJsonLd(undefined);
    };
  }, [title, description, path, jsonLd]);
}
