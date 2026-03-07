import { useState } from "react";
import { CheckCircle, XCircle, AlertTriangle } from "lucide-react";
import type { CheckResult } from "../types/api";
import { formatCheckName } from "../pages/auditUtils";
import styles from "./CheckResultsGrid.module.css";

export default function CheckResultsGrid({ checks }: { checks: CheckResult[] }) {
  const [expandedIndex, setExpandedIndex] = useState<number | null>(null);

  return (
    <div className={styles.auditChecks}>
      <h5 className={styles.auditCheckTitle}>Safety Checks</h5>
      <div className={styles.checkGrid}>
        {checks.map((check, i) => {
          const severity = check.severity ?? "";
          const checkName = check.check_name ?? "unknown";
          const message = check.message ?? "";
          const SeverityIcon =
            severity === "pass"
              ? CheckCircle
              : severity === "fail"
                ? XCircle
                : AlertTriangle;
          const severityClass =
            severity === "pass"
              ? styles.severityPass
              : severity === "fail"
                ? styles.severityFail
                : styles.severityWarn;
          const isExpanded = expandedIndex === i;
          return (
            <div
              key={i}
              className={`${styles.checkCard} ${severityClass}`}
              onClick={() => setExpandedIndex(isExpanded ? null : i)}
            >
              <div className={styles.checkHeader}>
                <SeverityIcon size={14} className={styles.checkIcon} />
                <span className={styles.checkName}>{formatCheckName(checkName)}</span>
              </div>
              <span className={`${styles.checkMessage} ${isExpanded ? styles.checkMessageExpanded : ""}`}>
                {message}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
