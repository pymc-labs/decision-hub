import type { ReactNode, CSSProperties } from "react";
import styles from "./NeonCard.module.css";

interface NeonCardProps {
  children: ReactNode;
  glow?: "cyan" | "pink" | "purple" | "green";
  className?: string;
  onClick?: () => void;
  style?: CSSProperties;
}

export default function NeonCard({
  children,
  glow = "cyan",
  className = "",
  onClick,
  style,
}: NeonCardProps) {
  return (
    <div
      className={`${styles.card} ${styles[glow]} ${onClick ? styles.clickable : ""} ${className}`}
      onClick={onClick}
      style={style}
    >
      {children}
    </div>
  );
}
