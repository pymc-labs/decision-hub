import type { ReactNode, CSSProperties } from "react";
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
  return (
    <div
      className={`${styles.card} ${styles[accent]} ${onClick ? styles.clickable : ""} ${className}`}
      onClick={onClick}
      style={style}
    >
      {children}
    </div>
  );
}
