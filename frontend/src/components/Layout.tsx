import { useState } from "react";
import { Outlet, Link, useLocation } from "react-router-dom";
import { Zap, Package, Building2, Home, BookOpen, Menu, X } from "lucide-react";
import styles from "./Layout.module.css";

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
          </Link>

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
