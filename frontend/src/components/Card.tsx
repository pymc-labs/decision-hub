import type { ReactNode } from "react";
import styles from "./Card.module.css";

interface CardProps {
  children: ReactNode;
  variant?: "default" | "elevated";
  className?: string;
  onClick?: () => void;
}

export default function Card({ children, variant = "default", className = "", onClick }: CardProps) {
  const variantClass = variant === "elevated" ? styles.elevated : "";
  return (
    <div className={`${styles.card} ${variantClass} ${className}`} onClick={onClick}>
      {children}
    </div>
  );
}
