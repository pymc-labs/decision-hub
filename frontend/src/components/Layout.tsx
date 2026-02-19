import { useState } from "react";
import { Outlet, Link, useLocation } from "react-router-dom";
import { Zap, Package, Building2, Home, BookOpen, Menu, X, Star } from "lucide-react";
import styles from "./Layout.module.css";

const IS_DEV = import.meta.env.VITE_ENV !== "prod";

const NAV_ITEMS = [
  { path: "/", label: "Home", icon: Home },
  { path: "/skills", label: "Skills", icon: Package },
  { path: "/orgs", label: "Organizations", icon: Building2 },
  { path: "/how-it-works", label: "How it Works", icon: BookOpen },
];

export default function Layout() {
  const location = useLocation();
  const [mobileMenuState, setMobileMenuState] = useState({
    isOpen: false,
    openedOnPath: location.pathname,
  });
  const mobileMenuOpen =
    mobileMenuState.isOpen && mobileMenuState.openedOnPath === location.pathname;

  return (
    <div className={styles.layout}>
      <header className={styles.header}>
        <div className={styles.headerInner}>
          <Link to="/" className={styles.logo}>
            <Zap className={styles.logoIcon} />
            <span className={styles.logoText}>Decision Hub</span>
            {IS_DEV && <span className={styles.devBadge}>DEV</span>}
          </Link>

          <nav className={`${styles.nav} ${mobileMenuOpen ? styles.navOpen : ""}`}>
            {NAV_ITEMS.map(({ path, label, icon: Icon }) => (
              <Link
                key={path}
                to={path}
                onClick={() =>
                  setMobileMenuState({
                    isOpen: false,
                    openedOnPath: location.pathname,
                  })
                }
                className={`${styles.navLink} ${
                  (path === "/" ? location.pathname === "/" : location.pathname.startsWith(path)) ? styles.navLinkActive : ""
                }`}
              >
                <Icon size={16} />
                <span>{label}</span>
              </Link>
            ))}
          </nav>

          <div className={styles.headerRight}>
            <a
              href="https://github.com/pymc-labs/decision-hub"
              target="_blank"
              rel="noopener noreferrer"
              className={styles.starBtn}
              aria-label="Star on GitHub"
            >
              <Star size={16} />
              <span>Star on GitHub</span>
            </a>
            <button
              className={styles.menuToggle}
              onClick={() =>
                setMobileMenuState(() => ({
                  isOpen: !mobileMenuOpen,
                  openedOnPath: location.pathname,
                }))
              }
              aria-label={mobileMenuOpen ? "Close menu" : "Open menu"}
            >
              {mobileMenuOpen ? <X size={22} /> : <Menu size={22} />}
            </button>
          </div>
        </div>
      </header>

      <main className={styles.main}>
        <Outlet />
      </main>

      <footer className={styles.footer}>
        <div className={styles.footerInner}>
          <span className={styles.footerGlow}>DECISION HUB</span>
          <span className={styles.footerText}>
            Auto-evaluated · Security-graded · Searchable in plain English
          </span>
        </div>
      </footer>
    </div>
  );
}
