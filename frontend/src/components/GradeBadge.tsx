import styles from "./GradeBadge.module.css";

interface GradeBadgeProps {
  grade: string | null | undefined;
  size?: "sm" | "md" | "lg";
}

const GRADE_CONFIG: Record<string, { label: string; color: string; tooltip: string }> = {
  A: { label: "A", color: "green", tooltip: "Grade A — Safe: No dangerous patterns detected" },
  B: { label: "B", color: "cyan", tooltip: "Grade B — Elevated: Minor risks identified, reviewed safe" },
  C: { label: "C", color: "yellow", tooltip: "Grade C — Risky: Contains patterns that need careful review" },
  F: { label: "F", color: "red", tooltip: "Grade F — Unsafe: Dangerous patterns detected" },
  pending: { label: "...", color: "muted", tooltip: "Security analysis pending" },
};

export default function GradeBadge({ grade, size = "md" }: GradeBadgeProps) {
  // The API returns safety_rating as formatted strings like "A  Safe", or
  // null when scanning is still in progress — treat null/undefined as pending.
  const raw = grade ?? "";
  const trimmed = raw.trim().toLowerCase();
  if (!trimmed) {
    const pending = GRADE_CONFIG.pending;
    return (
      <span
        className={`${styles.badge} ${styles[pending.color]} ${styles[size]}`}
        title={pending.tooltip}
      >
        {pending.label}
      </span>
    );
  }
  const gradeKey = trimmed === "pending" ? "pending" : trimmed.charAt(0).toUpperCase();
  const config = GRADE_CONFIG[gradeKey] ?? { label: raw, color: "muted", tooltip: "Unknown grade" };

  return (
    <span
      className={`${styles.badge} ${styles[config.color]} ${styles[size]}`}
      title={config.tooltip}
    >
      {config.label}
    </span>
  );
}
