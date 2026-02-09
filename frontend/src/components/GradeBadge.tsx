import styles from "./GradeBadge.module.css";

interface GradeBadgeProps {
  grade: string;
  size?: "sm" | "md" | "lg";
}

const GRADE_CONFIG: Record<string, { label: string; color: string }> = {
  A: { label: "A", color: "green" },
  B: { label: "B", color: "cyan" },
  C: { label: "C", color: "yellow" },
  F: { label: "F", color: "red" },
  pending: { label: "...", color: "muted" },
};

export default function GradeBadge({ grade, size = "md" }: GradeBadgeProps) {
  // The API returns safety_rating as formatted strings like "A  Safe"
  const trimmed = grade.trim().toLowerCase();
  const gradeKey = trimmed === "pending" ? "pending" : trimmed.charAt(0).toUpperCase();
  const config = GRADE_CONFIG[gradeKey] ?? { label: grade, color: "muted" };

  return (
    <span className={`${styles.badge} ${styles[config.color]} ${styles[size]}`}>
      {config.label}
    </span>
  );
}
