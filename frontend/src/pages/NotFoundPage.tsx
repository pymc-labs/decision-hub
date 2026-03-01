import { Link } from "react-router-dom";
import { useSEO } from "../hooks/useSEO";

export default function NotFoundPage() {
  useSEO({ title: "404 — Page Not Found", path: "/404" });
  return (
    <div
      className="container"
      style={{ textAlign: "center", paddingTop: "4rem", paddingBottom: "4rem" }}
    >
      <p style={{ fontSize: "3.5rem", fontWeight: 800, color: "var(--text-primary)", margin: 0, letterSpacing: "-0.03em" }}>
        404
      </p>
      <h1 style={{ fontSize: "1.375rem", margin: "0.75rem 0 0.5rem", fontWeight: 600 }}>Page not found</h1>
      <p style={{ color: "var(--text-muted)", marginBottom: "2rem" }}>
        The page you&apos;re looking for doesn&apos;t exist.
      </p>
      <Link to="/" style={{ color: "var(--color-primary)" }}>
        &larr; Back to home
      </Link>
    </div>
  );
}
