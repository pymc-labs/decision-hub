import { useState } from "react";
import { ChevronDown, ChevronRight, AlertTriangle, Clock, Info, Code, ExternalLink } from "lucide-react";
import type { ScanReport, ScanFinding } from "../types/api";
import styles from "./ScannerReport.module.css";

const SCANNER_REPO = "https://github.com/cisco-ai-defense/skill-scanner";

const SEVERITY_COLORS: Record<string, string> = {
  CRITICAL: "#ff4757",
  HIGH: "#ff6b35",
  MEDIUM: "#ffa502",
  LOW: "#3742fa",
  INFO: "#747d8c",
  SAFE: "#2ed573",
};

const VERDICT_COLORS: Record<string, string> = {
  SAFE: "#2ed573",
  SUSPICIOUS: "#ffa502",
  MALICIOUS: "#ff4757",
};

function LabeledBadge({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <span className={styles.labeledBadge}>
      <span className={styles.badgeLabel}>{label}</span>
      <span className={styles.badgeValue} style={{ borderColor: color, color }}>
        {value}
      </span>
    </span>
  );
}

function VerdictBadge({ verdict }: { verdict: string }) {
  const color = VERDICT_COLORS[verdict] || "#747d8c";
  return (
    <span className={styles.labeledBadge}>
      <span className={styles.badgeLabel}>verdict</span>
      <span className={styles.verdictValue} style={{ backgroundColor: color }}>
        {verdict}
      </span>
    </span>
  );
}

function FindingRow({ finding }: { finding: ScanFinding }) {
  const [expanded, setExpanded] = useState(false);
  const isFP = finding.is_false_positive === true;
  const severityColor = SEVERITY_COLORS[finding.severity] || "#747d8c";

  return (
    <div
      className={`${styles.findingRow} ${isFP ? styles.findingFP : ""}`}
      onClick={() => setExpanded(!expanded)}
    >
      <div className={styles.findingHeader}>
        {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        <span className={styles.severityBadge} style={{ borderColor: severityColor, color: severityColor }}>
          {finding.severity}
        </span>
        <span className={styles.findingTitle}>{finding.title}</span>
        {isFP && <span className={styles.fpLabel}>false positive</span>}
        {finding.meta_confidence && !isFP && (
          <span className={styles.confidenceLabel}>conf: {finding.meta_confidence}</span>
        )}
      </div>
      <div className={styles.findingMeta}>
        {finding.analyzer && <span>{finding.analyzer}</span>}
        {finding.category && <span>{finding.category.replace(/_/g, " ")}</span>}
        {finding.meta_impact && <span>impact: {finding.meta_impact}</span>}
        {finding.meta_exploitability && finding.meta_exploitability !== "N/A" && (
          <span>exploit: {finding.meta_exploitability}</span>
        )}
      </div>
      {expanded && (
        <div className={styles.findingDetails}>
          {finding.description && <p>{finding.description}</p>}
          {finding.meta_confidence_reason && (
            <p className={styles.confidenceReason}>{finding.meta_confidence_reason}</p>
          )}
          {finding.file_path && (
            <div className={styles.findingLocation}>
              {finding.file_path}
              {finding.line_number != null && `:${finding.line_number}`}
            </div>
          )}
          {finding.snippet && (
            <pre className={styles.findingSnippet}>{finding.snippet}</pre>
          )}
          {finding.remediation && (
            <div className={styles.findingRemediation}>
              <strong>Fix:</strong> {finding.remediation}
            </div>
          )}
          {isFP && finding.meta_confidence_reason && (
            <div className={styles.findingFPReason}>
              <Info size={12} /> FP reason: {finding.meta_confidence_reason}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function ScannerReport({ report }: { report: ScanReport }) {
  const [showFindings, setShowFindings] = useState(true);
  const [showFP, setShowFP] = useState(false);
  const [showRawReport, setShowRawReport] = useState(false);

  const realFindings = report.findings
    .filter((f) => f.is_false_positive !== true)
    .sort((a, b) => (a.meta_priority ?? 999) - (b.meta_priority ?? 999));
  const fpFindings = report.findings.filter((f) => f.is_false_positive === true);
  const fpCount = report.meta_false_positive_count ?? fpFindings.length;
  const durationSec = report.scan_duration_ms
    ? (report.scan_duration_ms / 1000).toFixed(0)
    : null;

  const fpByOriginalIndex = new Map(
    report.findings.map((f, i) => [i, f.is_false_positive === true])
  );

  const actionableCorrelations = (report.meta_correlations ?? []).filter((c) => {
    const indices = (c.finding_indices as number[]) ?? [];
    return indices.length === 0 || !indices.every((i) => fpByOriginalIndex.get(i));
  });

  const scanDate = report.created_at
    ? new Date(report.created_at).toLocaleDateString()
    : null;

  const isStale =
    report.scanned_semver &&
    report.latest_semver &&
    report.scanned_semver !== report.latest_semver;

  return (
    <div className={styles.scannerReport}>
      <div className={styles.reportHeader}>
        <div className={styles.reportHeaderInfo}>
          {report.meta_risk_level && (
            <LabeledBadge
              label="risk"
              value={report.meta_risk_level}
              color={SEVERITY_COLORS[report.meta_risk_level] || "#747d8c"}
            />
          )}
          <a
            href={SCANNER_REPO}
            target="_blank"
            rel="noopener noreferrer"
            className={styles.reportTitleLink}
            onClick={(e) => e.stopPropagation()}
          >
            Cisco Skill Scanner
            <ExternalLink size={11} />
          </a>
        </div>
        {scanDate && <span className={styles.reportDate}>{scanDate}</span>}
      </div>

      {isStale && (
        <div className={styles.staleWarning}>
          <Clock size={13} />
          Scanned v{report.scanned_semver} — latest is v{report.latest_semver}
        </div>
      )}

      <div className={styles.summaryBar}>
        <LabeledBadge
          label="severity"
          value={report.max_severity}
          color={SEVERITY_COLORS[report.max_severity] || "#747d8c"}
        />
        {report.meta_verdict && (
          <VerdictBadge verdict={report.meta_verdict} />
        )}
        <div className={styles.summaryStats}>
          <span>
            {realFindings.length} finding{realFindings.length !== 1 ? "s" : ""}
          </span>
          {fpCount > 0 && <span>{fpCount} false positive{fpCount !== 1 ? "s" : ""}</span>}
          {report.analyzability_score != null && (
            <span>
              analyzability: {Math.round(report.analyzability_score)}%
            </span>
          )}
        </div>
      </div>

      {report.meta_summary && (
        <p className={styles.metaSummary}>
          <strong>Summary:</strong> {report.meta_summary}
        </p>
      )}

      {report.meta_verdict_reasoning && (
        <p className={styles.verdictReasoning}>
          <strong>Reasoning:</strong> {report.meta_verdict_reasoning}
        </p>
      )}

      {report.llm_primary_threats && report.llm_primary_threats.length > 0 && (
        <div className={styles.primaryThreats}>
          {report.llm_primary_threats.map((t, i) => (
            <span key={i} className={styles.threatTag}>{t}</span>
          ))}
        </div>
      )}

      {report.llm_overall_assessment && !report.meta_summary && (
        <p className={styles.metaSummary}>{report.llm_overall_assessment}</p>
      )}

      {actionableCorrelations.length > 0 && (
        <div className={styles.correlations}>
          <h4>Correlated Findings</h4>
          {actionableCorrelations.map((c, i) => (
            <div key={i} className={styles.correlationGroup}>
              <div className={styles.correlationHeader}>
                <AlertTriangle size={14} />
                <strong>{String(c.group_name || `Group ${i + 1}`)}</strong>
                {!!c.combined_severity && (
                  <span
                    className={styles.severityBadge}
                    style={{
                      borderColor: SEVERITY_COLORS[String(c.combined_severity)] || "#747d8c",
                      color: SEVERITY_COLORS[String(c.combined_severity)] || "#747d8c",
                    }}
                  >
                    {String(c.combined_severity)}
                  </span>
                )}
              </div>
              {!!c.relationship && (
                <p className={styles.correlationDesc}>
                  {String(c.relationship)}
                </p>
              )}
              {!!c.consolidated_remediation && (
                <p className={styles.correlationFix}>
                  <strong>Fix:</strong> {String(c.consolidated_remediation)}
                </p>
              )}
            </div>
          ))}
        </div>
      )}

      {report.findings.length > 0 && (
        <div className={styles.findingsSection}>
          <button
            className={styles.findingsToggle}
            onClick={() => setShowFindings(!showFindings)}
          >
            {showFindings ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            Findings ({realFindings.length})
          </button>
          {showFindings && (
            <div className={styles.findingsList}>
              {realFindings.map((f, i) => (
                <FindingRow key={`${f.rule_id}-${i}`} finding={f} />
              ))}
              {fpFindings.length > 0 && (
                <div
                  className={`${styles.findingRow} ${styles.findingFP}`}
                  onClick={() => setShowFP(!showFP)}
                >
                  <div className={styles.findingHeader}>
                    {showFP ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                    <span className={styles.findingTitle}>
                      {fpFindings.length} false positive{fpFindings.length !== 1 ? "s" : ""} filtered
                    </span>
                  </div>
                </div>
              )}
              {showFP && fpFindings.map((f, i) => (
                <FindingRow key={`fp-${f.rule_id}-${i}`} finding={f} />
              ))}
            </div>
          )}
        </div>
      )}

      {report.meta_recommendations && report.meta_recommendations.length > 0 && (
        <div className={styles.recommendations}>
          <h4>Recommendations</h4>
          {report.meta_recommendations.map((r, i) => (
            <div key={i} className={styles.recommendation}>
              <span className={styles.recPriority}>
                {Number(r.priority) || i + 1}.
              </span>
              <span>{String(r.title || r.fix || "")}</span>
              {!!r.effort && (
                <span className={styles.recEffort}>{String(r.effort)} effort</span>
              )}
            </div>
          ))}
        </div>
      )}

      <div className={styles.reportFooter}>
        <span>
          Analyzers: {report.analyzers_used.join(", ")}
        </span>
        <span>Policy: {report.policy_name || "default"}</span>
        {durationSec && <span>Duration: {durationSec}s</span>}
        {report.scanner_version && (
          <span>Scanner v{report.scanner_version}</span>
        )}
      </div>

      {report.full_report && (
        <div className={styles.rawReportSection}>
          <button
            className={styles.findingsToggle}
            onClick={() => setShowRawReport(!showRawReport)}
          >
            {showRawReport ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            <Code size={14} />
            Raw Report
          </button>
          {showRawReport && (
            <pre className={styles.rawReport}>
              {JSON.stringify(report.full_report, null, 2)}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}
