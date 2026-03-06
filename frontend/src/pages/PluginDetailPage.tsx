import { useState, useMemo } from "react";
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
} from "lucide-react";
import { getPluginDetail, getPluginVersions, getPluginAuditLog } from "../api/client";
import { useApi } from "../hooks/useApi";
import { useSEO } from "../hooks/useSEO";
import type { PluginDetail, PluginVersionEntry, PluginAuditEntry } from "../types/api";
import NeonCard from "../components/NeonCard";
import GradeBadge from "../components/GradeBadge";
import LoadingSpinner from "../components/LoadingSpinner";
import styles from "./PluginDetailPage.module.css";

type Tab = "overview" | "versions" | "audit";

export default function PluginDetailPage() {
  const { orgSlug, pluginName } = useParams<{
    orgSlug: string;
    pluginName: string;
  }>();
  const [activeTab, setActiveTab] = useState<Tab>("overview");
  const [copied, setCopied] = useState(false);

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

      {/* Two-column body with sidebar */}
      <div className={styles.pageBody}>
        <div className={styles.main}>
          <div className={styles.content}>
            {activeTab === "overview" && <OverviewTab plugin={plugin} />}
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
              {plugin.homepage && (
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
    </div>
  );
}

/* --- Tab components --- */

function OverviewTab({ plugin }: { plugin: PluginDetail }) {
  return (
    <div className={styles.overview}>
      {/* Install command */}
      <div className={styles.installSection}>
        <h3 className={styles.sectionTitle}>Install</h3>
        <code className={styles.codeBlock}>
          dhub install {plugin.org_slug}/{plugin.plugin_name} --agent all
        </code>
      </div>

      {/* Description */}
      {plugin.description && (
        <div className={styles.descSection}>
          <h3 className={styles.sectionTitle}>Description</h3>
          <p className={styles.descText}>{plugin.description}</p>
        </div>
      )}

      {/* Skills grid */}
      {plugin.skills.length > 0 && (
        <div className={styles.skillsSection}>
          <h3 className={styles.sectionTitle}>
            <Package size={16} />
            Included Skills ({plugin.skills.length})
          </h3>
          <div className={styles.skillsGrid}>
            {plugin.skills.map((skill) => (
              <div key={skill.name} className={styles.skillCard}>
                <span className={styles.skillName}>{skill.name}</span>
                {skill.description && (
                  <p className={styles.skillDesc}>{skill.description}</p>
                )}
                <span className={styles.skillPath}>{skill.path}</span>
              </div>
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
          <div className={styles.tagList}>
            {plugin.agents.map((a) => (
              <span key={a} className={styles.tagItem}>{a}</span>
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
          <div className={styles.tagList}>
            {plugin.commands.map((c) => (
              <span key={c} className={styles.tagItem}>{c}</span>
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
            {entry.quarantined && (
              <span className={styles.auditQuarantine}>Quarantined</span>
            )}
          </div>
        </NeonCard>
      ))}
    </div>
  );
}
