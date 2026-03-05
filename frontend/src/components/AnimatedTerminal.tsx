import { useState, useEffect, useRef } from "react";
import styles from "./AnimatedTerminal.module.css";

interface TerminalLine {
  text: string;
  type: "prompt" | "agent" | "dim" | "success" | "output";
  delay: number; // ms before this line appears
  typewriter?: boolean; // animate character by character
}

const SCRIPT: TerminalLine[] = [
  { text: "$ claude", type: "prompt", delay: 0 },
  { text: "", type: "output", delay: 600 },
  { text: "  Claude Code v1.0.26", type: "dim", delay: 800 },
  { text: "", type: "output", delay: 1000 },
  { text: "> teach yourself how to use pymc on dhub", type: "prompt", delay: 1400, typewriter: true },
  { text: "", type: "output", delay: 4200 },
  { text: "⏺ Loading dhub skill from ~/.claude/skills/dhub-cli ...", type: "agent", delay: 4800 },
  { text: "", type: "output", delay: 5600 },
  { text: "⏺ Searching Decision Hub for PyMC skills...", type: "agent", delay: 6200 },
  { text: "  Found: pymc-labs/pymc-modeling v2.1.0 [A - Safe]", type: "success", delay: 7400 },
  { text: "", type: "output", delay: 7800 },
  { text: "⏺ Installing pymc-labs/pymc-modeling...", type: "agent", delay: 8200 },
  { text: "  ✓ Installed to Claude, Cursor, Codex", type: "success", delay: 9400 },
  { text: "", type: "output", delay: 9800 },
  { text: "⏺ Ready, I am now an expert on Bayesian Statistics and PyMC.", type: "agent", delay: 10400 },
  { text: "  I can now help you build models, run MCMC inference, and", type: "agent", delay: 10600 },
  { text: "  interpret results. What would you like to start with?", type: "agent", delay: 10800 },
];

export default function AnimatedTerminal() {
  const [visibleLines, setVisibleLines] = useState<number>(0);
  const [typedChars, setTypedChars] = useState<number>(0);
  const [hasStarted, setHasStarted] = useState(false);
  const [isComplete, setIsComplete] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const bodyRef = useRef<HTMLPreElement>(null);

  // Start animation when terminal scrolls into view
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting && !hasStarted) {
          setHasStarted(true);
        }
      },
      { threshold: 0.3 },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [hasStarted]);

  // Drive the line-by-line reveal
  useEffect(() => {
    if (!hasStarted || isComplete) return;
    if (visibleLines >= SCRIPT.length) return;

    const currentLine = SCRIPT[visibleLines];
    const prevDelay = visibleLines > 0 ? SCRIPT[visibleLines - 1].delay : 0;
    const wait = currentLine.delay - prevDelay;

    const timer = setTimeout(() => {
      if (currentLine.typewriter) {
        setTypedChars(0);
      }
      setVisibleLines((v) => {
        const next = v + 1;
        if (next >= SCRIPT.length) {
          setIsComplete(true);
        }
        return next;
      });
    }, Math.max(wait, 50));

    return () => clearTimeout(timer);
  }, [hasStarted, visibleLines, isComplete]);

  // Drive typewriter effect for the current typewriter line
  const typewriterLineIndex = SCRIPT.findIndex(
    (l, i) => l.typewriter && i < visibleLines && i === visibleLines - 1,
  );
  const typewriterLine = typewriterLineIndex >= 0 ? SCRIPT[typewriterLineIndex] : null;

  useEffect(() => {
    if (!typewriterLine) return;
    if (typedChars >= typewriterLine.text.length) return;

    const timer = setTimeout(() => {
      setTypedChars((c) => c + 1);
    }, 45);

    return () => clearTimeout(timer);
  }, [typewriterLine, typedChars]);

  // Auto-scroll to bottom
  useEffect(() => {
    if (bodyRef.current) {
      bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
    }
  }, [visibleLines, typedChars]);

  // Restart animation on click after completion
  const handleRestart = () => {
    if (!isComplete) return;
    setVisibleLines(0);
    setTypedChars(0);
    setIsComplete(false);
    setHasStarted(true);
  };

  return (
    <div className={styles.terminal} ref={containerRef} onClick={handleRestart}>
      <div className={styles.header}>
        <span className={styles.dot} style={{ background: "var(--stone)" }} />
        <span className={styles.dot} style={{ background: "var(--stone)" }} />
        <span className={styles.dot} style={{ background: "var(--stone)" }} />
        <span className={styles.title}>~/projects/my-analysis</span>
      </div>
      <pre className={styles.body} ref={bodyRef}>
        {SCRIPT.slice(0, visibleLines).map((line, i) => {
          const isTypewriting = line.typewriter && i === visibleLines - 1 && typedChars < line.text.length;
          const displayText = isTypewriting
            ? line.text.slice(0, typedChars)
            : line.text;

          return (
            <div key={i} className={styles[line.type]}>
              {displayText}
              {isTypewriting && <span className={styles.cursor}>▋</span>}
            </div>
          );
        })}
        {!hasStarted && (
          <div className={styles.dim}>
            <span className={styles.cursor}>▋</span>
          </div>
        )}
        {isComplete && <div className={styles.replay}>click to replay</div>}
      </pre>
    </div>
  );
}
