import styles from "./GradeBadge.module.css";

interface GradeBadgeProps {
  grade: string;
  size?: "sm" | "md" | "lg";
}

const GRADE_CONFIG: Record<string, { label: string; color: string; tooltip: string }> = {
  A: { label: "A", color: "olive", tooltip: "Grade A — Safe: No dangerous patterns detected" },
  B: { label: "B", color: "charcoal", tooltip: "Grade B — Elevated: Minor risks identified, reviewed safe" },
  C: { label: "C", color: "terracotta", tooltip: "Grade C — Risky: Contains patterns that need careful review" },
  F: { label: "F", color: "destructive", tooltip: "Grade F — Unsafe: Dangerous patterns detected" },
  pending: { label: "...", color: "muted", tooltip: "Security analysis pending" },
};

export default function GradeBadge({ grade, size = "md" }: GradeBadgeProps) {
  // The API returns safety_rating as formatted strings like "A  Safe"
  const trimmed = grade.trim().toLowerCase();
  const gradeKey = trimmed === "pending" ? "pending" : trimmed.charAt(0).toUpperCase();
  const config = GRADE_CONFIG[gradeKey] ?? { label: grade, color: "muted", tooltip: "Unknown grade" };

  return (
    <span
      className={`${styles.badge} ${styles[config.color]} ${styles[size]}`}
      title={config.tooltip}
    >
      {config.label}
    </span>
  );
}
