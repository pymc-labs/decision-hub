import type { ReactNode, CSSProperties } from "react";
import styles from "./Card.module.css";

interface CardProps {
  children: ReactNode;
  variant?: "default" | "accent" | "success" | "danger";
  className?: string;
  onClick?: () => void;
  style?: CSSProperties;
}

export default function Card({
  children,
  variant = "default",
  className = "",
  onClick,
  style,
}: CardProps) {
  return (
    <div
      className={`${styles.card} ${styles[variant]} ${onClick ? styles.clickable : ""} ${className}`}
      onClick={onClick}
      style={style}
    >
      {children}
    </div>
  );
}
