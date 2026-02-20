import { useState, useEffect, useCallback, useMemo } from "react";
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
  RefreshCw,
} from "lucide-react";
import JSZip from "jszip";
import { saveAs } from "file-saver";
import {
  getSkill,
  getEvalReport,
  getAuditLog,
  downloadSkillZip,
} from "../api/client";
import { useApi } from "../hooks/useApi";
import { useSEO } from "../hooks/useSEO";
import type { SkillSummary, EvalReport, AuditLogEntry, PaginatedAuditLogResponse, SkillFile } from "../types/api";
import NeonCard from "../components/NeonCard";
import GradeBadge from "../components/GradeBadge";
import LoadingSpinner from "../components/LoadingSpinner";
import EvalReportView from "../components/EvalReportView";
import FileBrowser from "../components/FileBrowser";
import styles from "./SkillDetailPage.module.css";

type Tab = "overview" | "evals" | "files" | "audit";

export default function SkillDetailPage() {
  const { orgSlug, skillName } = useParams<{
    orgSlug: string;
    skillName: string;
  }>();
  const [activeTab, setActiveTab] = useState<Tab>("overview");
  const [files, setFiles] = useState<SkillFile[]>([]);
  const [filesLoading, setFilesLoading] = useState(false);
  const [filesError, setFilesError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);
  const [copied, setCopied] = useState(false);

  // Reset files when navigating to a different skill
  useEffect(() => {
    setFiles([]);
    setFilesError(null);
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

  // Load files from zip when "files" tab is selected
  const loadFiles = useCallback(async () => {
    if (!orgSlug || !skillName) return;
    setFilesLoading(true);
    setFilesError(null);
    try {
      const zipData = await downloadSkillZip(orgSlug, skillName);
      const zip = await JSZip.loadAsync(zipData);
      const fileList: SkillFile[] = [];

      for (const [path, entry] of Object.entries(zip.files)) {
        if (entry.dir) continue;
        const content = await entry.async("string");
        fileList.push({
          path,
          content,
          size: content.length,
        });
      }

      setFiles(fileList);
    } catch (err) {
      setFilesError(err instanceof Error ? err.message : "Failed to load files");
    } finally {
      setFilesLoading(false);
    }
  }, [orgSlug, skillName]);

  useEffect(() => {
    if (activeTab === "files" && files.length === 0 && !filesLoading) {
      loadFiles();
    }
  }, [activeTab, files.length, filesLoading, loadFiles]);

  const handleDownload = async () => {
    if (!orgSlug || !skillName) return;
    setDownloading(true);
    try {
      const zipData = await downloadSkillZip(orgSlug, skillName);
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
    { id: "evals", label: "Evals", icon: Activity },
    { id: "files", label: "Files", icon: FolderOpen },
    { id: "audit", label: "Audit Log", icon: Shield },
  ];

  return (
    <div className="container">
      <Link to="/skills" className={styles.back}>
        <ArrowLeft size={16} />
        All Skills
      </Link>

      {/* Header */}
      <div className={styles.header}>
        <div className={styles.headerLeft}>
          <div className={styles.headerTitle}>
            <Link to={`/orgs/${orgSlug}`} className={styles.org}>
              {orgSlug}
            </Link>
            <span className={styles.slash}>/</span>
            <h1 className={styles.name}>{skillName}</h1>
          </div>
          <p className={styles.desc}>{skill.description}</p>
          <div className={styles.meta}>
            {skill.author && (
              <span className={styles.metaItem}>
                <User size={14} /> {skill.author}
              </span>
            )}
            <span className={styles.metaItem}>
              v{skill.latest_version}
            </span>
            <span className={styles.metaItem}>
              <Download size={14} /> {skill.download_count} downloads
            </span>
            {skill.updated_at && (
              <span className={styles.metaItem}>
                <Clock size={14} /> {skill.updated_at}
              </span>
            )}
            {skill.source_repo_url && (
              <a
                href={skill.source_repo_url}
                target="_blank"
                rel="noopener noreferrer"
                className={styles.metaItem}
              >
                <Github size={14} /> Source
              </a>
            )}
            {skill.is_auto_synced && (
              <span className={styles.metaItem}>
                <RefreshCw size={14} /> Auto-synced
              </span>
            )}
          </div>
        </div>

        <div className={styles.headerRight}>
          <GradeBadge grade={skill.safety_rating} size="lg" />
          <div className={styles.actions}>
            <button onClick={handleCopyInstall} className={styles.installBtn}>
              {copied ? <Check size={14} /> : <Copy size={14} />}
              {copied ? "Copied!" : "dhub install"}
            </button>
            <button
              onClick={handleDownload}
              disabled={downloading}
              className={styles.downloadBtn}
            >
              <Download size={14} />
              {downloading ? "Downloading..." : "Download .zip"}
            </button>
          </div>
        </div>
      </div>

      {/* Tabs */}
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

      {/* Tab content */}
      <div className={styles.content}>
        {activeTab === "overview" && <OverviewTab skill={skill} />}

        {activeTab === "evals" && (
          <EvalsTab report={evalReport} loading={evalLoading} />
        )}

        {activeTab === "files" && (
          <FilesTab
            files={files}
            loading={filesLoading}
            error={filesError}
          />
        )}

        {activeTab === "audit" && (
          <AuditTab entries={auditLog ?? []} loading={auditLoading} />
        )}
      </div>
    </div>
  );
}

/* --- Tab components --- */

function OverviewTab({ skill }: { skill: SkillSummary }) {
  return (
    <div className={styles.overview}>
      <NeonCard glow="cyan">
        <h3 className={styles.overviewTitle}>Installation</h3>
        <div className={styles.codeBlock}>
          <code>dhub install {skill.org_slug}/{skill.skill_name}</code>
        </div>
        <p className={styles.overviewHint}>
          Install for a specific agent:
        </p>
        <div className={styles.codeBlock}>
          <code>
            dhub install {skill.org_slug}/{skill.skill_name} --agent claude
          </code>
        </div>
      </NeonCard>

      <div className={styles.overviewGrid}>
        <NeonCard glow="green">
          <h4 className={styles.overviewLabel}>Safety Grade</h4>
          <div className={styles.overviewValue}>
            <GradeBadge grade={skill.safety_rating} size="md" />
            <span className={styles.overviewGradeText}>
              {skill.safety_rating}
            </span>
          </div>
        </NeonCard>

        <NeonCard glow="purple">
          <h4 className={styles.overviewLabel}>Version</h4>
          <p className={styles.overviewValueText}>v{skill.latest_version}</p>
        </NeonCard>

        <NeonCard glow="pink">
          <h4 className={styles.overviewLabel}>Downloads</h4>
          <p className={styles.overviewValueText}>
            {skill.download_count.toLocaleString()}
          </p>
        </NeonCard>

        <NeonCard glow="cyan">
          <h4 className={styles.overviewLabel}>Organization</h4>
          <p className={styles.overviewValueText}>{skill.org_slug}</p>
        </NeonCard>
      </div>
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
              <div className={styles.auditChecks}>
                <h5 className={styles.auditCheckTitle}>Safety Checks</h5>
                {entry.check_results.map((check, i) => (
                  <div key={i} className={styles.auditCheck}>
                    <pre className={styles.auditPre}>
                      {JSON.stringify(check, null, 2)}
                    </pre>
                  </div>
                ))}
              </div>
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
