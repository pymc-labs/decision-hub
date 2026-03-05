import { useState, useCallback, useEffect } from "react";
import { Outlet, Link, useLocation } from "react-router-dom";
import { Package, Building2, Home, BookOpen, Menu, X, Star, MessageCircle } from "lucide-react";
import AskModal from "./AskModal";
import styles from "./Layout.module.css";
import { SHOW_GITHUB_BUTTONS } from "../featureFlags";

const IS_DEV = import.meta.env.VITE_ENV !== "prod";

const NAV_ITEMS = [
  { path: "/", label: "Home", icon: Home },
  { path: "/skills", label: "Skills", icon: Package },
  { path: "/orgs", label: "Organizations", icon: Building2 },
  { path: "/how-it-works", label: "How It Works", icon: BookOpen },
];

const FOOTER_LINKS = {
  Product: [
    { label: "Skills", to: "/skills" },
    { label: "Organizations", to: "/orgs" },
    { label: "How It Works", to: "/how-it-works" },
  ],
  Resources: [
    { label: "GitHub", href: "https://github.com/pymc-labs/decision-hub" },
    { label: "PyMC Labs", href: "https://www.pymc-labs.com" },
  ],
  Legal: [
    { label: "Terms", to: "/terms" },
    { label: "Privacy", to: "/privacy" },
  ],
};

export default function Layout() {
  const location = useLocation();
  const [mobileMenuState, setMobileMenuState] = useState({
    isOpen: false,
    openedOnPath: location.pathname,
  });
  const mobileMenuOpen =
    mobileMenuState.isOpen && mobileMenuState.openedOnPath === location.pathname;
  const [askOpen, setAskOpen] = useState(false);
  const closeAsk = useCallback(() => setAskOpen(false), []);

  useEffect(() => {
    const openAsk = () => setAskOpen(true);
    window.addEventListener("open-ask-modal", openAsk);
    return () => window.removeEventListener("open-ask-modal", openAsk);
  }, []);

  return (
    <div className={styles.layout}>
      <header className={styles.header}>
        <div className={styles.headerInner}>
          <Link to="/" className={styles.logo}>
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
            <button
              className={styles.navLink}
              onClick={() => {
                setAskOpen(true);
                setMobileMenuState({ isOpen: false, openedOnPath: location.pathname });
              }}
            >
              <MessageCircle size={16} />
              <span>Ask</span>
            </button>
          </nav>

          <div className={styles.headerRight}>
            {SHOW_GITHUB_BUTTONS && (
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
            )}
            <button
              className={styles.menuToggle}
              onClick={() =>
                setMobileMenuState(() => ({
                  isOpen: !mobileMenuOpen,
                  openedOnPath: location.pathname,
                }))
              }
              aria-label="Toggle menu"
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
          <div className={styles.footerGrid}>
            <div className={styles.footerBrand}>
              <span className={styles.footerLogo}>Decision Hub</span>
              <p className={styles.footerDescription}>
                The open registry for AI agent skills. Discover, evaluate, and publish reusable skill
                manifests for any AI coding agent.
              </p>
            </div>
            {Object.entries(FOOTER_LINKS).map(([section, links]) => (
              <div key={section} className={styles.footerColumn}>
                <h4 className={styles.footerColumnTitle}>{section}</h4>
                <ul className={styles.footerColumnList}>
                  {links.map((link) => (
                    <li key={link.label}>
                      {"to" in link ? (
                        <Link to={link.to}>{link.label}</Link>
                      ) : (
                        <a href={link.href} target="_blank" rel="noopener noreferrer">
                          {link.label}
                        </a>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
          <div className={styles.footerCopyright}>
            <span>&copy; {new Date().getFullYear()} PyMC Labs. All rights reserved.</span>
          </div>
        </div>
      </footer>

      <AskModal isOpen={askOpen} onClose={closeAsk} />
    </div>
  );
}
