import { useEffect } from "react";

/**
 * Redirects to the PyMC Labs website.
 * Renders a fallback link in case the redirect doesn't fire.
 */
export default function AboutPage() {
  useEffect(() => {
    window.location.replace("https://www.pymc-labs.com");
  }, []);

  return (
    <div className="container" style={{ textAlign: "center", padding: "80px 0" }}>
      <p style={{ color: "var(--text-secondary)" }}>
        Redirecting to{" "}
        <a href="https://www.pymc-labs.com" style={{ color: "var(--neon-cyan)" }}>
          pymc-labs.com
        </a>
        ...
      </p>
    </div>
  );
}
