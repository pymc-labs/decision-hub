import { useState, useMemo, useCallback, useEffect, useRef } from "react";
import { useParams, Link } from "react-router-dom";
import {
  ArrowLeft,
  Puzzle,
  FileText,
  Shield,
  Clock,
  User,
  Download,
  Star,
  Scale,
  Github,
  Copy,
  Check,
  Package,
  Terminal,
  Bot,
  Webhook,
  FolderOpen,
} from "lucide-react";
import JSZip from "jszip";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { PluggableList } from "unified";
import { getPluginDetail, getPluginVersions, getPluginAuditLog, downloadPluginZip } from "../api/client";
import { useApi } from "../hooks/useApi";
import { useSEO } from "../hooks/useSEO";
import type { PluginDetail, PluginVersionEntry, PluginAuditEntry, SkillFile } from "../types/api";
import NeonCard from "../components/NeonCard";
import GradeBadge from "../components/GradeBadge";
import LoadingSpinner from "../components/LoadingSpinner";
import CheckResultsGrid from "../components/CheckResultsGrid";
import FileBrowser from "../components/FileBrowser";
import styles from "./PluginDetailPage.module.css";

const REMARK_PLUGINS: PluggableList = [remarkGfm];

type Tab = "overview" | "files" | "versions" | "audit";

export default function PluginDetailPage() {
  const { orgSlug, pluginName } = useParams<{
    orgSlug: string;
    pluginName: string;
  }>();
  const [activeTab, setActiveTab] = useState<Tab>("overview");
  const [copied, setCopied] = useState(false);
  const [zipData, setZipData] = useState<ArrayBuffer | null>(null);
  const [zipLoading, setZipLoading] = useState(false);
  const [zipError, setZipError] = useState<string | null>(null);
  const [files, setFiles] = useState<SkillFile[]>([]);
  const [readmeContent, setReadmeContent] = useState<string | null>(null);
  const zipRetries = useRef(0);
  const retryTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const MAX_ZIP_ATTEMPTS = 3;

  // Reset zip state when navigating to a different plugin
  useEffect(() => {
    setZipData(null);
    setZipError(null);
    setZipLoading(false);
    setFiles([]);
    setReadmeContent(null);
    zipRetries.current = 0;
    if (retryTimer.current) {
      clearTimeout(retryTimer.current);
      retryTimer.current = null;
    }
  }, [orgSlug, pluginName]);

  const { data: plugin, loading: pluginLoading } = useApi<PluginDetail>(
    () => getPluginDetail(orgSlug!, pluginName!),
    [orgSlug, pluginName],
  );

  const { data: versions, loading: versionsLoading } = useApi<PluginVersionEntry[]>(
    () => activeTab === "versions" ? getPluginVersions(orgSlug!, pluginName!) : Promise.resolve(null as unknown as PluginVersionEntry[]),
    [orgSlug, pluginName, activeTab],
  );

  const { data: auditLog, loading: auditLoading } = useApi<PluginAuditEntry[]>(
    () => activeTab === "audit" ? getPluginAuditLog(orgSlug!, pluginName!) : Promise.resolve(null as unknown as PluginAuditEntry[]),
    [orgSlug, pluginName, activeTab],
  );

  const seoTitle = `${orgSlug}/${pluginName}`;
  const seoDescription = plugin
    ? `${plugin.description} -- ${plugin.platforms.join(", ")} plugin with ${plugin.skill_count} skills. Safety grade: ${plugin.safety_rating}.`
    : `View the ${orgSlug}/${pluginName} plugin on Decision Hub.`;
  const jsonLd = useMemo(
    () =>
      plugin
        ? {
            "@context": "https://schema.org",
            "@type": "SoftwareApplication",
            name: `${orgSlug}/${pluginName}`,
            description: plugin.description,
            softwareVersion: plugin.latest_version,
            author: { "@type": "Organization", name: plugin.org_slug },
            applicationCategory: plugin.category || "AI Agent Plugin",
          }
        : undefined,
    [plugin, orgSlug, pluginName],
  );
  useSEO({
    title: seoTitle,
    description: seoDescription,
    path: `/plugins/${orgSlug}/${pluginName}`,
    jsonLd,
  });

  const handleCopyInstall = () => {
    navigator.clipboard.writeText(`dhub install ${orgSlug}/${pluginName} --agent all`);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const loadZip = useCallback(async () => {
    if (!orgSlug || !pluginName || zipData || zipLoading) return;
    setZipLoading(true);
    setZipError(null);
    try {
      const buf = await downloadPluginZip(orgSlug, pluginName);
      const zip = await JSZip.loadAsync(buf);

      // Extract README.md (case-insensitive)
      const readmeEntry = Object.values(zip.files).find(
        (f) => !f.dir && /^readme\.md$/i.test(f.name.split("/").pop() ?? ""),
      );
      if (readmeEntry) {
        const raw = await readmeEntry.async("string");
        setReadmeContent(raw);
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
  }, [orgSlug, pluginName, zipData, zipLoading]);

  // Trigger zip download when overview or files tab is first visited
  useEffect(() => {
    if ((activeTab === "overview" || activeTab === "files") && !zipData && !zipLoading && !zipError) {
      loadZip();
    }
  }, [activeTab, zipData, zipLoading, zipError, loadZip]);

  if (pluginLoading) {
    return <LoadingSpinner text={`Loading ${orgSlug}/${pluginName}...`} />;
  }

  if (!plugin) {
    return (
      <div className="container">
        <NeonCard glow="pink">
          <p style={{ color: "var(--neon-pink)" }}>
            Plugin not found: {orgSlug}/{pluginName}
          </p>
        </NeonCard>
      </div>
    );
  }

  const tabs: { id: Tab; label: string; icon: typeof Puzzle }[] = [
    { id: "overview", label: "Overview", icon: FileText },
    { id: "files", label: "Files", icon: FolderOpen },
    { id: "versions", label: "Versions", icon: Clock },
    { id: "audit", label: "Audit Log", icon: Shield },
  ];

  return (
    <div className="container">
      <Link to="/plugins" className={styles.back}>
        <ArrowLeft size={16} />
        All Plugins
      </Link>

      {/* Header */}
      <div className={styles.header}>
        <div className={styles.headerTitle}>
          <Link to={`/orgs/${orgSlug}`} className={styles.org}>
            {orgSlug}
          </Link>
          <span className={styles.slash}>/</span>
          <h1 className={styles.name}>{pluginName}</h1>
        </div>
        <p className={styles.desc}>{plugin.description}</p>
        {plugin.platforms.length > 0 && (
          <div className={styles.headerPlatforms}>
            {plugin.platforms.map((p) => (
              <span key={p} className={styles.platformBadge}>{p}</span>
            ))}
          </div>
        )}
      </div>

      {/* Tabs row */}
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
            {activeTab === "overview" && <OverviewTab plugin={plugin} readmeContent={readmeContent} readmeLoading={zipLoading} sourceRepoUrl={plugin.source_repo_url} />}
            {activeTab === "versions" && <VersionsTab versions={versions ?? []} loading={versionsLoading} />}
            {activeTab === "audit" && <AuditTab entries={auditLog ?? []} loading={auditLoading} />}
          </div>
        </div>

        {/* Sidebar */}
        <aside className={styles.sidebar}>
          <NeonCard glow={plugin.safety_rating === "A" ? "green" : plugin.safety_rating === "F" ? "pink" : "purple"}>
            <div className={styles.sidebarGrade}>
              <GradeBadge grade={plugin.safety_rating} size="lg" />
              <span className={styles.sidebarGradeLabel}>Safety Grade</span>
            </div>
            <div className={styles.sidebarActions}>
              <button onClick={handleCopyInstall} className={styles.installBtn}>
                {copied ? <Check size={14} /> : <Copy size={14} />}
                {copied ? "Copied!" : "dhub install"}
              </button>
            </div>
          </NeonCard>

          <NeonCard glow="purple">
            <div className={styles.sidebarMeta}>
              {plugin.latest_version && (
                <div className={styles.sidebarRow}>
                  <span className={styles.sidebarLabel}>Version</span>
                  <span className={styles.sidebarValue}>v{plugin.latest_version}</span>
                </div>
              )}
              <div className={styles.sidebarRow}>
                <span className={styles.sidebarLabel}><Download size={12} /> Downloads</span>
                <span className={styles.sidebarValue}>{plugin.download_count.toLocaleString()}</span>
              </div>
              {plugin.github_stars != null && plugin.github_stars > 0 && (
                <div className={styles.sidebarRow}>
                  <span className={styles.sidebarLabel}><Star size={12} /> Stars</span>
                  <span className={styles.sidebarValue}>{plugin.github_stars.toLocaleString()}</span>
                </div>
              )}
              {(plugin.license || plugin.github_license) && (
                <div className={styles.sidebarRow}>
                  <span className={styles.sidebarLabel}><Scale size={12} /> License</span>
                  <span className={styles.sidebarValue}>{plugin.license || plugin.github_license}</span>
                </div>
              )}
              {plugin.author_name && (
                <div className={styles.sidebarRow}>
                  <span className={styles.sidebarLabel}><User size={12} /> Author</span>
                  <span className={styles.sidebarValue}>{plugin.author_name}</span>
                </div>
              )}
              {plugin.category && (
                <div className={styles.sidebarRow}>
                  <span className={styles.sidebarLabel}>Category</span>
                  <span className={styles.sidebarValue}>{plugin.category}</span>
                </div>
              )}
              {plugin.source_repo_url && (
                <div className={styles.sidebarRow}>
                  <span className={styles.sidebarLabel}><Github size={12} /> Source</span>
                  <a
                    href={plugin.source_repo_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className={styles.sidebarLink}
                  >
                    GitHub
                  </a>
                </div>
              )}
              {plugin.homepage && plugin.homepage.replace(/\/+$/, "") !== (plugin.source_repo_url ?? "").replace(/\/+$/, "") && (
                <div className={styles.sidebarRow}>
                  <span className={styles.sidebarLabel}>Homepage</span>
                  <a
                    href={plugin.homepage}
                    target="_blank"
                    rel="noopener noreferrer"
                    className={styles.sidebarLink}
                  >
                    Link
                  </a>
                </div>
              )}
            </div>
          </NeonCard>

          {/* Component summary card */}
          <NeonCard glow="cyan">
            <div className={styles.sidebarMeta}>
              <div className={styles.sidebarRow}>
                <span className={styles.sidebarLabel}><Package size={12} /> Skills</span>
                <span className={styles.sidebarValue}>{plugin.skill_count}</span>
              </div>
              <div className={styles.sidebarRow}>
                <span className={styles.sidebarLabel}><Webhook size={12} /> Hooks</span>
                <span className={styles.sidebarValue}>{plugin.hook_count}</span>
              </div>
              <div className={styles.sidebarRow}>
                <span className={styles.sidebarLabel}><Bot size={12} /> Agents</span>
                <span className={styles.sidebarValue}>{plugin.agent_count}</span>
              </div>
              <div className={styles.sidebarRow}>
                <span className={styles.sidebarLabel}><Terminal size={12} /> Commands</span>
                <span className={styles.sidebarValue}>{plugin.command_count}</span>
              </div>
            </div>
          </NeonCard>
        </aside>
      </div>
      )}
    </div>
  );
}

/* --- Tab components --- */

function OverviewTab({
  plugin,
  readmeContent,
  readmeLoading,
  sourceRepoUrl,
}: {
  plugin: PluginDetail;
  readmeContent: string | null;
  readmeLoading: boolean;
  sourceRepoUrl: string | null;
}) {
  return (
    <div className={styles.overview}>
      {/* README */}
      {readmeLoading && <LoadingSpinner text="Loading README..." />}
      {!readmeLoading && readmeContent && (
        <div className={styles.readmeSection}>
          <ReactMarkdown
            remarkPlugins={REMARK_PLUGINS}
            components={{
              a: ({ href, children, ...props }) => {
                const isExternal = href && /^https?:\/\//.test(href);
                return (
                  <a
                    href={href}
                    {...(isExternal ? { target: "_blank", rel: "noopener noreferrer" } : {})}
                    {...props}
                  >
                    {children}
                  </a>
                );
              },
              img: ({ src, ...props }) => {
                // Resolve relative image URLs to raw GitHub URLs
                const resolved = src && sourceRepoUrl && !/^https?:\/\//.test(src)
                  ? `${sourceRepoUrl}/raw/main/${src}`
                  : src;
                return <img src={resolved} {...props} />;
              },
            }}
          >
            {readmeContent}
          </ReactMarkdown>
        </div>
      )}

      {/* Install */}
      <div className={styles.installSection}>
        <h3 className={styles.sectionTitle}>
          <Package size={16} />
          Install
        </h3>
        <p className={styles.installHint}>Install the entire plugin:</p>
        <code className={styles.codeBlock}>
          dhub install {plugin.org_slug}/{plugin.plugin_name} --agent all
        </code>
        {plugin.published_skills.length > 0 && (
          <p className={styles.installHint}>Or install individual skills:</p>
        )}
        {plugin.published_skills.map((s) => (
          <code key={`${s.org_slug}/${s.skill_name}`} className={styles.codeBlock}>
            dhub install {s.org_slug}/{s.skill_name} --agent all
          </code>
        ))}
      </div>

      {/* Published Skills */}
      {plugin.published_skills.length > 0 && (
        <div className={styles.skillsSection}>
          <h3 className={styles.sectionTitle}>
            <Package size={16} />
            Included Skills ({plugin.published_skills.length})
          </h3>
          <div className={styles.skillsGrid}>
            {plugin.published_skills.map((skill) => (
              <Link
                key={`${skill.org_slug}/${skill.skill_name}`}
                to={`/skills/${skill.org_slug}/${skill.skill_name}`}
                className={styles.skillLink}
              >
                <div className={styles.skillCard}>
                  <div className={styles.skillCardHeader}>
                    <span className={styles.skillName}>{skill.skill_name}</span>
                    <GradeBadge grade={skill.safety_rating} size="sm" />
                  </div>
                  {skill.description && (
                    <p className={styles.skillDesc}>{skill.description}</p>
                  )}
                  <div className={styles.skillCardMeta}>
                    <span className={styles.skillVersion}>v{skill.latest_version}</span>
                    <span className={styles.skillDownloads}>
                      <Download size={11} />
                      {skill.download_count.toLocaleString()}
                    </span>
                  </div>
                </div>
              </Link>
            ))}
          </div>
        </div>
      )}

      {/* Hooks */}
      {plugin.hooks.length > 0 && (
        <div className={styles.hooksSection}>
          <h3 className={styles.sectionTitle}>
            <Webhook size={16} />
            Hooks ({plugin.hooks.length})
          </h3>
          <div className={styles.hooksList}>
            {plugin.hooks.map((hook, i) => (
              <div key={i} className={styles.hookItem}>
                <span className={styles.hookEvent}>{hook.event}</span>
                <code className={styles.hookCommand}>{hook.command}</code>
                {hook.is_async && <span className={styles.asyncBadge}>async</span>}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Agents */}
      {plugin.agents.length > 0 && (
        <div className={styles.listSection}>
          <h3 className={styles.sectionTitle}>
            <Bot size={16} />
            Agents ({plugin.agents.length})
          </h3>
          <div className={styles.componentList}>
            {plugin.agents.map((a) => (
              <div key={a} className={styles.componentItem}>
                <Bot size={14} />
                <span>{a}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Commands */}
      {plugin.commands.length > 0 && (
        <div className={styles.listSection}>
          <h3 className={styles.sectionTitle}>
            <Terminal size={16} />
            Commands ({plugin.commands.length})
          </h3>
          <div className={styles.componentList}>
            {plugin.commands.map((c) => (
              <div key={c} className={styles.componentItem}>
                <Terminal size={14} />
                <span>{c}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Keywords */}
      {plugin.keywords.length > 0 && (
        <div className={styles.listSection}>
          <h3 className={styles.sectionTitle}>Keywords</h3>
          <div className={styles.tagList}>
            {plugin.keywords.map((k) => (
              <span key={k} className={styles.keywordTag}>{k}</span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function VersionsTab({
  versions,
  loading,
}: {
  versions: PluginVersionEntry[];
  loading: boolean;
}) {
  if (loading) return <LoadingSpinner text="Loading versions..." />;
  if (versions.length === 0) {
    return (
      <div className={styles.emptyTab}>
        <Clock size={48} />
        <p>No version history available</p>
      </div>
    );
  }

  return (
    <div className={styles.versionList}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th>Version</th>
            <th>Publisher</th>
            <th>Status</th>
            <th>Published</th>
          </tr>
        </thead>
        <tbody>
          {versions.map((v) => (
            <tr key={v.semver}>
              <td className={styles.versionCell}>v{v.semver}</td>
              <td>{v.published_by}</td>
              <td>
                {v.eval_status ? (
                  <span className={styles.evalStatus}>{v.eval_status}</span>
                ) : (
                  <span className={styles.evalPending}>pending</span>
                )}
              </td>
              <td className={styles.dateCell}>
                {new Date(v.created_at).toLocaleDateString()}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function AuditTab({
  entries,
  loading,
}: {
  entries: PluginAuditEntry[];
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
          key={`${entry.semver}-${entry.created_at}`}
          glow={entry.grade === "F" ? "pink" : entry.grade === "A" ? "green" : "purple"}
        >
          <div className={styles.auditEntry}>
            <div className={styles.auditHeader}>
              <div className={styles.auditInfo}>
                <GradeBadge grade={entry.grade} size="sm" />
                <span className={styles.auditVersion}>v{entry.semver}</span>
                <span className={styles.auditPublisher}>by {entry.publisher}</span>
              </div>
              <span className={styles.auditDate}>
                {new Date(entry.created_at).toLocaleDateString()}
              </span>
            </div>
            {entry.check_results && entry.check_results.length > 0 && (
              <CheckResultsGrid checks={entry.check_results} />
            )}
            {entry.quarantined && (
              <span className={styles.auditQuarantine}>Quarantined</span>
            )}
          </div>
        </NeonCard>
      ))}
    </div>
  );
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
        <p>No files to display.</p>
      </div>
    );
  }
  return <FileBrowser files={files} />;
}
