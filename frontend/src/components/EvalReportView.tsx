import {
  CheckCircle,
  XCircle,
  AlertTriangle,
  Clock,
  Cpu,
  FileText,
} from "lucide-react";
import type { EvalReport, EvalCaseResult } from "../types/api";
import Card from "./Card";
import styles from "./EvalReportView.module.css";

interface EvalReportViewProps {
  report: EvalReport;
}

function VerdictIcon({ verdict }: { verdict: string }) {
  switch (verdict) {
    case "pass":
      return <CheckCircle size={16} className={styles.pass} />;
    case "fail":
      return <XCircle size={16} className={styles.fail} />;
    default:
      return <AlertTriangle size={16} className={styles.error} />;
  }
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${(ms / 60000).toFixed(1)}m`;
}

function CaseResultCard({ result }: { result: EvalCaseResult }) {
  return (
    <Card>
      <div className={styles.caseCard}>
        <div className={styles.caseHeader}>
          <div className={styles.caseName}>
            <VerdictIcon verdict={result.verdict} />
            <h4>{result.name}</h4>
          </div>
          <div className={styles.caseMeta}>
            <span className={styles.caseDuration}>
              <Clock size={12} />
              {formatDuration(result.duration_ms)}
            </span>
            <span
              className={`${styles.caseVerdict} ${styles[result.verdict]}`}
            >
              {result.verdict.toUpperCase()}
            </span>
          </div>
        </div>

        <p className={styles.caseDesc}>{result.description}</p>

        {result.reasoning && (
          <div className={styles.caseSection}>
            <h5 className={styles.caseSectionTitle}>
              <FileText size={12} /> Judge Reasoning
            </h5>
            <pre className={styles.casePre}>{result.reasoning}</pre>
          </div>
        )}

        {result.agent_output && (
          <div className={styles.caseSection}>
            <h5 className={styles.caseSectionTitle}>
              <Cpu size={12} /> Agent Output
            </h5>
            <pre className={styles.casePre}>{result.agent_output}</pre>
          </div>
        )}

        {result.agent_stderr && (
          <div className={styles.caseSection}>
            <h5 className={`${styles.caseSectionTitle} ${styles.stderrTitle}`}>
              stderr
            </h5>
            <pre className={`${styles.casePre} ${styles.stderr}`}>
              {result.agent_stderr}
            </pre>
          </div>
        )}

        {result.exit_code !== 0 && (
          <span className={styles.exitCode}>
            Exit code: {result.exit_code}
          </span>
        )}
      </div>
    </Card>
  );
}

export default function EvalReportView({ report }: EvalReportViewProps) {
  const passRate =
    report.total > 0
      ? Math.round((report.passed / report.total) * 100)
      : 0;

  return (
    <div className={styles.report}>
      {/* Summary bar */}
      <div className={styles.summary}>
        <Card>
          <div className={styles.summaryInner}>
            <div className={styles.summaryScore}>
              <span className={styles.summaryNumber}>{report.passed}</span>
              <span className={styles.summarySlash}>/</span>
              <span className={styles.summaryTotal}>{report.total}</span>
            </div>
            <div className={styles.summaryDetails}>
              <div className={styles.summaryBar}>
                <div
                  className={styles.summaryBarFill}
                  style={{ width: `${passRate}%` }}
                />
              </div>
              <div className={styles.summaryMeta}>
                <span>
                  <Cpu size={12} /> Agent: {report.agent}
                </span>
                <span>
                  Judge: {report.judge_model}
                </span>
                <span>
                  <Clock size={12} /> {formatDuration(report.total_duration_ms)}
                </span>
                <span className={`${styles.summaryStatus} ${styles[report.status]}`}>
                  {report.status}
                </span>
              </div>
            </div>
          </div>
        </Card>
      </div>

      {report.error_message && (
        <Card>
          <div className={styles.errorMsg}>
            <AlertTriangle size={16} />
            <span>{report.error_message}</span>
          </div>
        </Card>
      )}

      {/* Case results */}
      <div className={styles.cases}>
        {report.case_results.map((result) => (
          <CaseResultCard key={result.name} result={result} />
        ))}
      </div>
    </div>
  );
}
