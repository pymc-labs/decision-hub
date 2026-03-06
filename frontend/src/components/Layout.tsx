import { useState, useCallback, useEffect } from "react";
import { Outlet, Link, useLocation } from "react-router-dom";
import { Zap, Package, Building2, Home, BookOpen, Menu, X, Star, MessageCircle } from "lucide-react";
import AskModal from "./AskModal";
import styles from "./Layout.module.css";
import { useGitHubStars } from "../hooks/useGitHubStars";

const IS_DEV = import.meta.env.VITE_ENV !== "prod";

const NAV_ITEMS = [
  { path: "/", label: "Home", icon: Home },
  { path: "/skills", label: "Skills", icon: Package },
  { path: "/orgs", label: "Organizations", icon: Building2 },
  { path: "/how-it-works", label: "How it Works", icon: BookOpen },
];

function formatStars(n: number): string {
  if (n >= 1000) {
    const divided = n / 1000;
    // Use integer display once the rounded value reaches 10k to avoid "10.0k"
    return divided >= 9.95 ? `${Math.round(divided)}k` : `${divided.toFixed(1)}k`;
  }
  return n.toString();
}

export default function Layout() {
  const location = useLocation();
  const stars = useGitHubStars();
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
            <a
              href="https://github.com/pymc-labs/decision-hub"
              target="_blank"
              rel="noopener noreferrer"
              className={styles.starBtn}
              aria-label="Star on GitHub"
            >
              <Star size={16} />
              <span>Star</span>
              {stars !== null && (
                <span className={styles.starCount}>{formatStars(stars)}</span>
              )}
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
          <div className={styles.footerBrand}>
            <span className={styles.footerGlow}>DECISION HUB</span>
            <p className={styles.footerTagline}>
              The open registry for AI agent skills. Discover, evaluate, and publish reusable skill manifests for any AI coding agent.
            </p>
          </div>
          <div className={styles.footerColumns}>
            <div className={styles.footerColumn}>
              <h4 className={styles.footerColumnTitle}>Product</h4>
              <Link to="/skills">Skills</Link>
              <Link to="/orgs">Organizations</Link>
              <Link to="/how-it-works">How It Works</Link>
            </div>
            <div className={styles.footerColumn}>
              <h4 className={styles.footerColumnTitle}>Resources</h4>
              <a href="https://github.com/pymc-labs/decision-hub" target="_blank" rel="noopener noreferrer">
                GitHub
              </a>
              <a href="https://www.pymc-labs.com" target="_blank" rel="noopener noreferrer">
                PyMC Labs
              </a>
            </div>
            <div className={styles.footerColumn}>
              <h4 className={styles.footerColumnTitle}>Legal</h4>
              <Link to="/terms">Terms</Link>
              <Link to="/privacy">Privacy</Link>
            </div>
          </div>
        </div>
        <div className={styles.footerBottom}>
          <span>&copy; 2026 PyMC Labs. All rights reserved.</span>
        </div>
      </footer>

      <AskModal isOpen={askOpen} onClose={closeAsk} />
    </div>
  );
}
