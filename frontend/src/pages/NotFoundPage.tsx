import { Link } from "react-router-dom";
import { useSEO } from "../hooks/useSEO";

export default function NotFoundPage() {
  useSEO({ title: "404 — Page Not Found", path: "/404" });
  return (
    <div
      className="container"
      style={{ textAlign: "center", paddingTop: "4rem", paddingBottom: "4rem" }}
    >
      <p style={{ fontSize: "var(--text-hero)", fontWeight: 800, color: "var(--color-primary)", margin: 0, letterSpacing: "-0.04em" }}>
        404
      </p>
      <h1 style={{ fontSize: "var(--text-heading)", margin: "0.75rem 0 0.5rem" }}>Page not found</h1>
      <p style={{ color: "var(--text-muted)", marginBottom: "2rem" }}>
        The page you&apos;re looking for doesn&apos;t exist.
      </p>
      <Link to="/" style={{ color: "var(--color-primary)" }}>
        ← Back to home
      </Link>
    </div>
  );
}
