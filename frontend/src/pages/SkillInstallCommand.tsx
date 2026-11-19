import { useEffect, useState } from "react";
import { Copy } from "lucide-react";
import type { SkillSummary } from "../types/api";
import styles from "./SkillDetailPage.module.css";

export default function SkillInstallCommand({ skill }: { skill: SkillSummary }) {
  const [pinVersion, setPinVersion] = useState(false);
  const versionFlag = pinVersion ? ` --version ${skill.latest_version}` : "";
  const riskFlag = skill.safety_rating === "C" ? " --allow-risky" : "";
  const command = `dhub install ${skill.org_slug}/${skill.skill_name}${versionFlag} --agent all${riskFlag}`;

  return (
    <div className={styles.installControls}>
      <label className={styles.installVersion}>
        Install version
        <select
          value={pinVersion ? "exact" : "latest"}
          onChange={(event) => setPinVersion(event.target.value === "exact")}
        >
          <option value="latest">Latest</option>
          <option value="exact">Exact ({skill.latest_version})</option>
        </select>
      </label>
      <CopyCommand key={command} command={command} />
    </div>
  );
}

function CopyCommand({ command }: { command: string }) {
  const [status, setStatus] = useState<"idle" | "copying" | "copied" | "failed">("idle");

  useEffect(() => {
    if (status !== "copied") return;
    const timeout = window.setTimeout(() => setStatus("idle"), 2000);
    return () => window.clearTimeout(timeout);
  }, [status]);

  async function copy() {
    setStatus("copying");
    try {
      await navigator.clipboard.writeText(command);
      setStatus("copied");
    } catch {
      setStatus("failed");
    }
  }

  return (
    <>
      <div className={styles.installCommand}>
        <code>{command}</code>
        <button
          type="button"
          className={styles.installBtn}
          aria-label="Copy install command"
          title="Copy install command"
          onClick={copy}
          disabled={status === "copying"}
        >
          <Copy size={16} aria-hidden="true" />
        </button>
      </div>
      <p role="status" aria-label="Install command" className={styles.copyFeedback}>
        {status === "copied" && "Copied!"}
        {status === "failed" && "Clipboard unavailable. Copy the command manually."}
      </p>
    </>
  );
}
