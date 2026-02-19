import { useSEO } from "../hooks/useSEO";
import styles from "./LegalPage.module.css";

export default function PrivacyPage() {
  useSEO({
    title: "Privacy Policy",
    description: "Privacy Policy for Decision Hub, the skill registry for AI coding agents.",
    path: "/privacy",
  });

  return (
    <div className="container">
      <article className={styles.legal}>
        <h1>Privacy Policy</h1>
        <p className={styles.updated}>Last updated: February 19, 2026</p>

        <section>
          <h2>1. Who We Are</h2>
          <p>
            Decision Hub is operated by PyMC Labs. This policy explains what data we collect,
            why, and how we handle it.
          </p>
        </section>

        <section>
          <h2>2. Data We Collect</h2>

          <h3>Account Data (via GitHub OAuth)</h3>
          <p>When you log in, we receive from GitHub:</p>
          <ul>
            <li>Your GitHub username and display name</li>
            <li>Your email address (as configured in GitHub)</li>
            <li>Your avatar URL</li>
            <li>Your GitHub organization memberships (for namespace scoping)</li>
          </ul>
          <p>
            We store this data to identify your account and scope skill publishing to your
            organizations. We do not access your repositories, code, issues, or other GitHub
            data.
          </p>

          <h3>Usage Data</h3>
          <p>We collect:</p>
          <ul>
            <li>Skill publish and download events (what was published/installed, when)</li>
            <li>Search queries (to improve search relevance)</li>
            <li>Basic access logs (IP address, user agent, timestamps)</li>
          </ul>

          <h3>Published Skills</h3>
          <p>
            Skills you publish are stored on our infrastructure and subject to automated
            security analysis and evaluation. Skill metadata (name, description, version,
            safety grade) is publicly visible. Skill files are available to authenticated users
            within the skill's namespace scope.
          </p>
        </section>

        <section>
          <h2>3. How We Use Your Data</h2>
          <ul>
            <li>To authenticate you and manage your account</li>
            <li>To scope skill publishing to your GitHub organizations</li>
            <li>To run automated security analysis and evaluations on published skills</li>
            <li>To provide search and discovery features</li>
            <li>To monitor and improve the Service</li>
          </ul>
          <p>We do not sell your data. We do not use your data for advertising.</p>
        </section>

        <section>
          <h2>4. Data Sharing</h2>
          <p>
            We do not share your personal data with third parties, except:
          </p>
          <ul>
            <li>Infrastructure providers (cloud hosting) who process data on our behalf</li>
            <li>When required by law or legal process</li>
          </ul>
        </section>

        <section>
          <h2>5. Data Retention</h2>
          <p>
            Account data is retained as long as your account is active. Published skills are
            retained until you delete them or request removal. Access logs are retained for
            up to 90 days.
          </p>
        </section>

        <section>
          <h2>6. Your Rights</h2>
          <p>You can:</p>
          <ul>
            <li>Request a copy of your data</li>
            <li>Request deletion of your account and associated data</li>
            <li>Unpublish skills you have published</li>
          </ul>
          <p>
            To exercise these rights, contact{" "}
            <a href="mailto:info@pymc-labs.com">info@pymc-labs.com</a>.
          </p>
        </section>

        <section>
          <h2>7. Cookies</h2>
          <p>
            We use essential cookies for authentication (session tokens). We do not use
            tracking cookies or third-party analytics cookies.
          </p>
        </section>

        <section>
          <h2>8. Changes</h2>
          <p>
            We may update this policy from time to time. We will notify users of material
            changes via the Service.
          </p>
        </section>

        <section>
          <h2>9. Contact</h2>
          <p>
            For privacy questions, contact{" "}
            <a href="mailto:info@pymc-labs.com">info@pymc-labs.com</a>.
          </p>
        </section>
      </article>
    </div>
  );
}
