import type { ReactNode } from "react";
import styles from "./TerminalBlock.module.css";

interface TerminalBlockProps {
  title?: string;
  children: ReactNode;
}

export default function TerminalBlock({ title, children }: TerminalBlockProps) {
  return (
    <div className={styles.terminal}>
      {title !== undefined && (
        <div className={styles.header}>
          <span className={styles.dot} style={{ background: "#ff5f56" }} />
          <span className={styles.dot} style={{ background: "#ffbd2e" }} />
          <span className={styles.dot} style={{ background: "#27c93f" }} />
          <span className={styles.title}>{title}</span>
        </div>
      )}
      <pre className={styles.body}>{children}</pre>
    </div>
  );
}
