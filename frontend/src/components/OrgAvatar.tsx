import { useState } from "react";
import { Building2, User } from "lucide-react";
import styles from "./OrgAvatar.module.css";

interface OrgAvatarProps {
  avatarUrl: string | null | undefined;
  isPersonal: boolean;
  size?: "sm" | "md" | "lg";
}

const ICON_SIZES: Record<string, number> = {
  sm: 20,
  md: 28,
  lg: 36,
};

export default function OrgAvatar({ avatarUrl, isPersonal, size = "md" }: OrgAvatarProps) {
  // Track which URL failed so a new avatarUrl automatically gets a fresh attempt
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  const showImage = avatarUrl && avatarUrl !== failedUrl;

  if (showImage) {
    return (
      <img
        src={avatarUrl}
        alt="org avatar"
        className={`${styles.avatar} ${styles[size]}`}
        onError={() => setFailedUrl(avatarUrl)}
      />
    );
  }

  const Icon = isPersonal ? User : Building2;
  return (
    <div className={`${styles.fallback} ${styles[size]}`}>
      <Icon size={ICON_SIZES[size]} />
    </div>
  );
}
