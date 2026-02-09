import { Outlet, Link, useLocation } from "react-router-dom";
import { Zap, Package, Building2, Home, BookOpen } from "lucide-react";
import styles from "./Layout.module.css";

const NAV_ITEMS = [
  { path: "/", label: "Home", icon: Home },
  { path: "/skills", label: "Skills", icon: Package },
  { path: "/orgs", label: "Organizations", icon: Building2 },
  { path: "/how-it-works", label: "How it Works", icon: BookOpen },
];

export default function Layout() {
  const location = useLocation();

  return (
    <div className={styles.layout}>
      <header className={styles.header}>
        <div className={styles.headerInner}>
          <Link to="/" className={styles.logo}>
            <Zap className={styles.logoIcon} />
            <span className={styles.logoText}>Decision Hub</span>
          </Link>

          <nav className={styles.nav}>
            {NAV_ITEMS.map(({ path, label, icon: Icon }) => (
              <Link
                key={path}
                to={path}
                className={`${styles.navLink} ${
                  location.pathname === path ? styles.navLinkActive : ""
                }`}
              >
                <Icon size={16} />
                <span>{label}</span>
              </Link>
            ))}
          </nav>
        </div>
      </header>

      <main className={styles.main}>
        <Outlet />
      </main>

      <footer className={styles.footer}>
        <div className={styles.footerInner}>
          <span className={styles.footerGlow}>DECISION HUB</span>
          <span className={styles.footerText}>
            Skill Registry for Data Science Agents
          </span>
        </div>
      </footer>
    </div>
  );
}
