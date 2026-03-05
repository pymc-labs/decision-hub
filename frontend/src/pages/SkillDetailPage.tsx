import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import { useParams, Link } from "react-router-dom";
import {
  ArrowLeft,
  Download,
  Package,
  Shield,
  FileText,
  Activity,
  FolderOpen,
  User,
  Clock,
  Copy,
  Check,
  Github,
  GitFork,
  Star,
  Scale,
  RefreshCw,
  CheckCircle,
  XCircle,
  AlertTriangle,
} from "lucide-react";
import JSZip from "jszip";
import { saveAs } from "file-saver";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { PluggableList } from "unified";
import {
  getSkill,
  getEvalReport,
  getAuditLog,
  downloadSkillZip,
} from "../api/client";
import { useApi } from "../hooks/useApi";
import { useSEO } from "../hooks/useSEO";
import type { SkillSummary, EvalReport, AuditLogEntry, CheckResult, PaginatedAuditLogResponse, SkillFile } from "../types/api";
import NeonCard from "../components/NeonCard";
import GradeBadge from "../components/GradeBadge";
import LoadingSpinner from "../components/LoadingSpinner";
import EvalReportView from "../components/EvalReportView";
import FileBrowser from "../components/FileBrowser";
import { formatCheckName } from "./auditUtils";
import { LINK_TO_MANIFEST } from "../featureFlags";
import styles from "./SkillDetailPage.module.css";

const REMARK_PLUGINS: PluggableList = [remarkGfm];

type Tab = "overview" | "evals" | "files" | "audit";

export default function SkillDetailPage() {
  const { orgSlug, skillName } = useParams<{
    orgSlug: string;
    skillName: string;
  }>();
  const [activeTab, setActiveTab] = useState<Tab>("overview");
  const [zipData, setZipData] = useState<ArrayBuffer | null>(null);
  const [zipLoading, setZipLoading] = useState(false);
  const [zipError, setZipError] = useState<string | null>(null);
  const [files, setFiles] = useState<SkillFile[]>([]);
  const [skillMdContent, setSkillMdContent] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);
  const [copied, setCopied] = useState(false);
  const zipRetries = useRef(0);
  const retryTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const MAX_ZIP_ATTEMPTS = 3;

  // Reset state when navigating to a different skill
  useEffect(() => {
    setZipData(null);
    setZipError(null);
    setZipLoading(false);
    setFiles([]);
    setSkillMdContent(null);
    zipRetries.current = 0;
    if (retryTimer.current) {
      clearTimeout(retryTimer.current);
      retryTimer.current = null;
    }
  }, [orgSlug, skillName]);

  // Fetch single skill
  const { data: skill, loading: skillLoading } = useApi<SkillSummary>(
    () => getSkill(orgSlug!, skillName!),
    [orgSlug, skillName]
  );

  // Fetch eval report
  const {
    data: evalReport,
    loading: evalLoading,
  } = useApi<EvalReport | null>(
    () =>
      orgSlug && skillName && skill
        ? getEvalReport(orgSlug, skillName, skill.latest_version)
        : Promise.resolve(null),
    [orgSlug, skillName, skill?.latest_version]
  );

  // Fetch audit log
  const { data: auditLogResponse, loading: auditLoading } = useApi<PaginatedAuditLogResponse>(
    () =>
      orgSlug && skillName
        ? getAuditLog(orgSlug, skillName)
        : Promise.resolve({ items: [], total: 0, page: 1, page_size: 20, total_pages: 1 }),
    [orgSlug, skillName]
  );
  const auditLog = auditLogResponse?.items ?? [];

  const seoTitle = `${orgSlug}/${skillName}`;
  const seoDescription = skill
    ? `${skill.description} — Safety grade: ${skill.safety_rating}, v${skill.latest_version}. Install with: dhub install ${orgSlug}/${skillName}`
    : `View the ${orgSlug}/${skillName} skill on Decision Hub.`;
  const jsonLd = useMemo(
    () =>
      skill
        ? {
            "@context": "https://schema.org",
            "@type": "SoftwareApplication",
            name: `${orgSlug}/${skillName}`,
            description: skill.description,
            softwareVersion: skill.latest_version,
            author: {
              "@type": "Organization",
              name: skill.org_slug,
            },
            applicationCategory: skill.category || "AI Agent Skill",
          }
        : undefined,
    [skill, orgSlug, skillName],
  );
  useSEO({
    title: seoTitle,
    description: seoDescription,
    path: `/skills/${orgSlug}/${skillName}`,
    jsonLd,
  });

  // Download zip once, extract SKILL.md and file list from it.
  // Retries up to MAX_ZIP_ATTEMPTS total on transient failures with exponential backoff.
  const loadZip = useCallback(async () => {
    if (!orgSlug || !skillName || !skill || zipData || zipLoading) return;
    setZipLoading(true);
    setZipError(null);
    try {
      const allowRisky = skill?.safety_rating === "C";
      const buf = await downloadSkillZip(orgSlug, skillName, "latest", allowRisky);
      const zip = await JSZip.loadAsync(buf);

      const skillMdEntry = zip.file("SKILL.md");
      if (skillMdEntry) {
        const raw = await skillMdEntry.async("string");
        const stripped = raw.replace(/^---\n[\s\S]*?\n---\n?/, "");
        setSkillMdContent(stripped);
      }

      const fileList: SkillFile[] = [];
      for (const [path, entry] of Object.entries(zip.files)) {
        if (entry.dir) continue;
        const content = await entry.async("string");
        fileList.push({ path, content, size: content.length });
      }
      setFiles(fileList);
      setZipData(buf);
      zipRetries.current = 0;
    } catch (err) {
      zipRetries.current += 1;
      if (zipRetries.current < MAX_ZIP_ATTEMPTS) {
        const delay = 2000 * zipRetries.current;
        retryTimer.current = setTimeout(() => {
          retryTimer.current = null;
          setZipLoading(false);
        }, delay);
        return;
      }
      setZipError(err instanceof Error ? err.message : "Failed to load package");
    } finally {
      if (zipRetries.current === 0 || zipRetries.current >= MAX_ZIP_ATTEMPTS) {
        setZipLoading(false);
      }
    }
  }, [orgSlug, skillName, zipData, zipLoading, skill]);

  // Trigger zip download when overview or files tab is first visited
  useEffect(() => {
    if ((activeTab === "overview" || activeTab === "files") && !zipData && !zipLoading && !zipError) {
      loadZip();
    }
  }, [activeTab, zipData, zipLoading, zipError, loadZip]);

  const handleDownload = async () => {
    if (!orgSlug || !skillName) return;
    setDownloading(true);
    try {
      const allowRisky = skill?.safety_rating === "C";
      const zipData = await downloadSkillZip(orgSlug, skillName, "latest", allowRisky);
      const blob = new Blob([zipData], { type: "application/zip" });
      saveAs(blob, `${orgSlug}-${skillName}.zip`);
    } catch (err) {
      console.error("Download failed:", err);
    } finally {
      setDownloading(false);
    }
  };

  const handleCopyInstall = () => {
    navigator.clipboard.writeText(`dhub install ${orgSlug}/${skillName} --agent all`);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  if (skillLoading) {
    return <LoadingSpinner text={`Loading ${orgSlug}/${skillName}...`} />;
  }

  if (!skill) {
    return (
      <div className="container">
        <NeonCard glow="pink">
          <p style={{ color: "var(--neon-pink)" }}>
            Skill not found: {orgSlug}/{skillName}
          </p>
        </NeonCard>
      </div>
    );
  }

  const tabs: { id: Tab; label: string; icon: typeof Package }[] = [
    { id: "overview", label: "Overview", icon: FileText },
    { id: "files", label: "Files", icon: FolderOpen },
    { id: "audit", label: "Audit Log", icon: Shield },
    { id: "evals", label: "Evals", icon: Activity },
  ];

  return (
    <div className="container">
      <Link to="/skills" className={styles.back}>
        <ArrowLeft size={16} />
        All Skills
      </Link>

      {/* Header */}
      <div className={styles.header}>
        <div className={styles.headerTitle}>
          <Link to={`/orgs/${orgSlug}`} className={styles.org}>
            {orgSlug}
          </Link>
          <span className={styles.slash}>/</span>
          <h1 className={styles.name}>{skillName}</h1>
        </div>
        <p className={styles.desc}>{skill.description}</p>
      </div>

      {/* Tabs row — always full width */}
      <div className={styles.tabs}>
        {tabs.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            className={`${styles.tab} ${activeTab === id ? styles.tabActive : ""}`}
            onClick={() => setActiveTab(id)}
          >
            <Icon size={14} />
            {label}
          </button>
        ))}
      </div>

      {/* Files tab — full width, no sidebar */}
      {activeTab === "files" && (
        <FilesTab files={files} loading={zipLoading} error={zipError} />
      )}

      {/* Other tabs — two-column body with sidebar */}
      {activeTab !== "files" && (
      <div className={styles.pageBody}>
        <div className={styles.main}>
          <div className={styles.content}>
            {activeTab === "overview" && <OverviewTab content={skillMdContent} loading={zipLoading} error={zipError} />}
            {activeTab === "evals" && (
              <EvalsTab report={evalReport} loading={evalLoading} />
            )}
            {activeTab === "audit" && (
              <AuditTab entries={auditLog ?? []} loading={auditLoading} />
            )}
          </div>
        </div>

        {/* Right: sidebar */}
        <aside className={styles.sidebar}>
          <NeonCard glow={skill.safety_rating === "A" ? "green" : skill.safety_rating === "F" ? "pink" : "cyan"}>
            <div className={styles.sidebarGrade}>
              <GradeBadge grade={skill.safety_rating} size="lg" />
              <span className={styles.sidebarGradeLabel}>Safety Grade</span>
            </div>
            <div className={styles.sidebarActions}>
              <button onClick={handleCopyInstall} className={styles.installBtn}>
                {copied ? <Check size={14} /> : <Copy size={14} />}
                {copied ? "Copied!" : "dhub install"}
              </button>
              <button onClick={handleDownload} disabled={downloading} className={styles.downloadBtn}>
                <Download size={14} />
                {downloading ? "Downloading..." : "Download .zip"}
              </button>
            </div>
          </NeonCard>

          <NeonCard glow="cyan">
            <div className={styles.sidebarMeta}>
              <div className={styles.sidebarRow}>
                <span className={styles.sidebarLabel}>Version</span>
                <span className={styles.sidebarValue}>v{skill.latest_version}</span>
              </div>
              <div className={styles.sidebarRow}>
                <span className={styles.sidebarLabel}><Download size={12} /> Downloads</span>
                <span className={styles.sidebarValue}>{skill.download_count.toLocaleString()}</span>
              </div>
              {skill.github_stars != null && skill.github_stars > 0 && (
                <div className={styles.sidebarRow}>
                  <span className={styles.sidebarLabel}><Star size={12} /> Stars</span>
                  <span className={styles.sidebarValue}>{skill.github_stars.toLocaleString()}</span>
                </div>
              )}
              {skill.github_forks != null && skill.github_forks > 0 && (
                <div className={styles.sidebarRow}>
                  <span className={styles.sidebarLabel}><GitFork size={12} /> Forks</span>
                  <span className={styles.sidebarValue}>{skill.github_forks.toLocaleString()}</span>
                </div>
              )}
              {skill.github_license && (
                <div className={styles.sidebarRow}>
                  <span className={styles.sidebarLabel}><Scale size={12} /> License</span>
                  <span className={styles.sidebarValue}>{skill.github_license}</span>
                </div>
              )}
              {skill.author && (
                <div className={styles.sidebarRow}>
                  <span className={styles.sidebarLabel}><User size={12} /> Author</span>
                  <span className={styles.sidebarValue}>{skill.author}</span>
                </div>
              )}
              {skill.updated_at && (
                <div className={styles.sidebarRow}>
                  <span className={styles.sidebarLabel}><Clock size={12} /> Updated</span>
                  <span className={styles.sidebarValue}>{skill.updated_at}</span>
                </div>
              )}
              {skill.category && (
                <div className={styles.sidebarRow}>
                  <span className={styles.sidebarLabel}>Category</span>
                  <span className={styles.sidebarValue}>{skill.category}</span>
                </div>
              )}
              {skill.source_repo_url && (
                <div className={styles.sidebarRow}>
                  <span className={styles.sidebarLabel}><Github size={12} /> Source</span>
                  <a
                    href={LINK_TO_MANIFEST && skill.manifest_path
                      ? `${skill.source_repo_url}/blob/main/${skill.manifest_path}`
                      : skill.source_repo_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className={styles.sidebarLink}
                  >
                    GitHub ↗
                  </a>
                </div>
              )}
              {skill.is_auto_synced && (
                <div className={styles.sidebarRow}>
                  <span className={styles.sidebarLabel}><RefreshCw size={12} /> Sync</span>
                  <span className={styles.sidebarValue}>Auto-synced</span>
                </div>
              )}
              {skill.source_repo_removed && (
                <div className={styles.sidebarRow}>
                  <span className={styles.metaRemoved}>Removed from GitHub</span>
                </div>
              )}
            </div>
          </NeonCard>
        </aside>
      </div>
      )}
    </div>
  );
}

/* --- Tab components --- */

function OverviewTab({ content, loading, error }: { content: string | null; loading: boolean; error: string | null }) {
  if (loading) return <LoadingSpinner text="Loading SKILL.md..." />;
  if (error) return (
    <NeonCard glow="pink">
      <p style={{ color: "var(--neon-pink)" }}>Failed to load package: {error}</p>
    </NeonCard>
  );
  if (!content) return (
    <div className={styles.emptyTab}>
      <FileText size={48} />
      <p>SKILL.md not found in package</p>
    </div>
  );

  return (
    <div className={styles.skillMd}>
      <ReactMarkdown remarkPlugins={REMARK_PLUGINS}>{content}</ReactMarkdown>
    </div>
  );
}

function EvalsTab({
  report,
  loading,
}: {
  report: EvalReport | null;
  loading: boolean;
}) {
  if (loading) return <LoadingSpinner text="Loading eval report..." />;
  if (!report) {
    return (
      <div className={styles.emptyTab}>
        <Activity size={48} />
        <p>No evaluation report available for this version</p>
      </div>
    );
  }
  return <EvalReportView report={report} />;
}

function FilesTab({
  files,
  loading,
  error,
}: {
  files: SkillFile[];
  loading: boolean;
  error: string | null;
}) {
  if (loading) return <LoadingSpinner text="Extracting files from package..." />;
  if (error) {
    return (
      <NeonCard glow="pink">
        <p style={{ color: "var(--neon-pink)" }}>Error: {error}</p>
      </NeonCard>
    );
  }
  if (files.length === 0) {
    return (
      <div className={styles.emptyTab}>
        <FolderOpen size={48} />
        <p>No files to display. Click to load files from the package.</p>
      </div>
    );
  }
  return <FileBrowser files={files} />;
}

export function CheckResultsGrid({ checks }: { checks: CheckResult[] }) {
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

function AuditTab({
  entries,
  loading,
}: {
  entries: AuditLogEntry[];
  loading: boolean;
}) {
  if (loading) return <LoadingSpinner text="Loading audit log..." />;
  if (entries.length === 0) {
    return (
      <div className={styles.emptyTab}>
        <Shield size={48} />
        <p>No audit log entries found</p>
      </div>
    );
  }

  return (
    <div className={styles.auditList}>
      {entries.map((entry) => (
        <NeonCard
          key={entry.id}
          glow={entry.grade === "F" ? "pink" : entry.grade === "A" ? "green" : "cyan"}
        >
          <div className={styles.auditEntry}>
            <div className={styles.auditHeader}>
              <div className={styles.auditInfo}>
                <GradeBadge grade={entry.grade} size="sm" />
                <span className={styles.auditVersion}>v{entry.semver}</span>
                <span className={styles.auditPublisher}>
                  by {entry.publisher}
                </span>
              </div>
              {entry.created_at && (
                <span className={styles.auditDate}>
                  {new Date(entry.created_at).toLocaleDateString()}
                </span>
              )}
            </div>

            {entry.check_results.length > 0 && (
              <CheckResultsGrid checks={entry.check_results} />
            )}

            {entry.quarantine_s3_key && (
              <span className={styles.auditQuarantine}>
                Quarantined: {entry.quarantine_s3_key}
              </span>
            )}
          </div>
        </NeonCard>
      ))}
    </div>
  );
}
