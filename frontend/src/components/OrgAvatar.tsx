import { useState, useEffect } from "react";
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
  const [imgError, setImgError] = useState(false);

  useEffect(() => {
    setImgError(false);
  }, [avatarUrl]);

  if (avatarUrl && !imgError) {
    return (
      <img
        src={avatarUrl}
        alt="org avatar"
        className={`${styles.avatar} ${styles[size]}`}
        onError={() => setImgError(true)}
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
