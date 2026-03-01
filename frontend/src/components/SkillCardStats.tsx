import { Download, Star, Scale } from "lucide-react";
import styles from "./SkillCardStats.module.css";

interface SkillCardStatsProps {
  github_stars: number | null;
  github_license: string | null;
  download_count: number;
}

export default function SkillCardStats({ github_stars, github_license, download_count }: SkillCardStatsProps) {
  return (
    <span className={styles.stats}>
      {github_stars != null && github_stars > 0 && (
        <span className={styles.stat}>
          <Star size={12} />
          {github_stars.toLocaleString()}
        </span>
      )}
      {github_license && (
        <span className={styles.stat}>
          <Scale size={12} />
          {github_license}
        </span>
      )}
      <span className={styles.stat}>
        <Download size={12} />
        {download_count.toLocaleString()}
      </span>
    </span>
  );
}
