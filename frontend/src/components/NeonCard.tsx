import type { ReactNode, CSSProperties } from "react";
import Card from "./Card";

interface NeonCardProps {
  children: ReactNode;
  glow?: "cyan" | "pink" | "purple" | "green";
  className?: string;
  onClick?: () => void;
  style?: CSSProperties;
}

const GLOW_TO_ACCENT: Record<string, "blue" | "green" | "violet" | "pink" | "default"> = {
  cyan: "blue",
  pink: "pink",
  purple: "violet",
  green: "green",
};

/** @deprecated Wrapper — use Card directly */
export default function NeonCard({
  children,
  glow = "cyan",
  className = "",
  onClick,
  style,
}: NeonCardProps) {
  return (
    <Card
      accent={GLOW_TO_ACCENT[glow] ?? "default"}
      className={className}
      onClick={onClick}
      style={style}
    >
      {children}
    </Card>
  );
}
