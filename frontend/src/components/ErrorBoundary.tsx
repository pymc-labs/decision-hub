import { Component, type ErrorInfo, type ReactNode } from "react";
import { AlertTriangle, RotateCw } from "lucide-react";
import styles from "./ErrorBoundary.module.css";

interface Props {
  children: ReactNode;
  /** Optional override for the fallback UI. */
  fallback?: ReactNode;
}

interface State {
  error: Error | null;
}

/**
 * Top-level error boundary that catches render errors anywhere below it and
 * shows a neon-themed fallback instead of leaving the user with a blank page.
 *
 * Must be a class component — React 19 still has no functional API for
 * componentDidCatch / getDerivedStateFromError.
 */
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // No remote error reporting wired up yet; log to the console so the stack
    // is visible in dev tools and captured by the browser's error events.
    console.error("ErrorBoundary caught render error:", error, info);
  }

  handleReload = (): void => {
    // Full reload is the cheapest way to recover from a broken render tree:
    // we don't know which providers/hooks the error corrupted.
    window.location.reload();
  };

  render(): ReactNode {
    if (!this.state.error) {
      return this.props.children;
    }

    if (this.props.fallback !== undefined) {
      return this.props.fallback;
    }

    return (
      <div className={styles.wrapper} role="alert">
        <div className={styles.card}>
          <AlertTriangle className={styles.icon} aria-hidden="true" />
          <h1 className={styles.title}>Something went wrong</h1>
          <p className={styles.message}>
            Decision Hub hit an unexpected error rendering this page. Reload to try again.
          </p>
          <button type="button" className={styles.button} onClick={this.handleReload}>
            <RotateCw className={styles.buttonIcon} aria-hidden="true" />
            Reload
          </button>
        </div>
      </div>
    );
  }
}
