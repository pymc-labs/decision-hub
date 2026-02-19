import type { ReactNode } from "react";
import styles from "./TerminalBlock.module.css";

interface TerminalBlockProps {
  title?: string;
  children: ReactNode;
  /** When true, lines starting with $ render as white (commands), the rest as cyan (output). */
  colorCommands?: boolean;
}

function colorize(text: string): ReactNode {
  const lines = text.split("\n");
  return lines.map((line, i) => {
    const isCommand = line.trimStart().startsWith("$");
    const cls = isCommand ? styles.command : styles.output;
    return (
      <span key={i} className={cls}>
        {line}
        {i < lines.length - 1 ? "\n" : ""}
      </span>
    );
  });
}

export default function TerminalBlock({ title, children, colorCommands }: TerminalBlockProps) {
  const content = colorCommands && typeof children === "string" ? colorize(children) : children;

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
      <pre className={styles.body}>{content}</pre>
    </div>
  );
}
