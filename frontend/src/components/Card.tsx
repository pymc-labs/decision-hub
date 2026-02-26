import type { ReactNode, CSSProperties, KeyboardEvent } from "react";
import styles from "./Card.module.css";

interface CardProps {
  children: ReactNode;
  accent?: "blue" | "green" | "violet" | "pink" | "default";
  className?: string;
  onClick?: () => void;
  style?: CSSProperties;
}

export default function Card({
  children,
  accent = "default",
  className = "",
  onClick,
  style,
}: CardProps) {
  const handleKeyDown = onClick
    ? (e: KeyboardEvent) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onClick();
        }
      }
    : undefined;

  return (
    <div
      className={[styles.card, styles[accent], onClick && styles.clickable, className].filter(Boolean).join(" ")}
      onClick={onClick}
      onKeyDown={handleKeyDown}
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
      style={style}
    >
      {children}
    </div>
  );
}
