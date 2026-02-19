import { useSEO } from "../hooks/useSEO";
import styles from "./LegalPage.module.css";

export default function TermsPage() {
  useSEO({
    title: "Terms of Service",
    description: "Terms of Service for Decision Hub, the skill registry for AI coding agents.",
    path: "/terms",
  });

  return (
    <div className="container">
      <article className={styles.legal}>
        <h1>Terms of Service</h1>
        <p className={styles.updated}>Last updated: February 19, 2026</p>

        <section>
          <h2>1. Overview</h2>
          <p>
            Decision Hub ("the Service") is operated by PyMC Labs ("we", "us", "our").
            By accessing or using the Service, you agree to be bound by these Terms of Service.
          </p>
        </section>

        <section>
          <h2>2. Account &amp; Authentication</h2>
          <p>
            The Service uses GitHub OAuth for authentication. By logging in, you authorize us
            to access your GitHub profile information (username, email, avatar, and organization
            memberships) as needed to operate the Service. We do not access your repositories,
            code, or other GitHub data beyond what is required for authentication and namespace
            scoping.
          </p>
        </section>

        <section>
          <h2>3. Published Skills</h2>
          <p>
            When you publish a skill to Decision Hub, you represent that you have the right to
            distribute the content. Published skills are subject to automated security analysis
            and evaluation. Skills are scoped to your GitHub organization or personal namespace.
          </p>
          <p>
            We reserve the right to remove or quarantine skills that are found to contain
            malicious code, violate these terms, or pose a security risk to users.
          </p>
        </section>

        <section>
          <h2>4. Acceptable Use</h2>
          <p>You agree not to:</p>
          <ul>
            <li>Publish skills containing malicious code, malware, or data exfiltration mechanisms</li>
            <li>Attempt to circumvent security analysis or safety grading</li>
            <li>Use the Service to distribute content that violates applicable law</li>
            <li>Interfere with or disrupt the Service or its infrastructure</li>
            <li>Scrape or bulk-download data from the Service beyond normal API usage</li>
          </ul>
        </section>

        <section>
          <h2>5. Intellectual Property</h2>
          <p>
            You retain ownership of skills you publish. By publishing to Decision Hub, you grant
            us a license to host, distribute, analyze, and evaluate your skills as part of the
            Service. Other users who install your skills receive them under whatever license you
            specify in your skill package.
          </p>
        </section>

        <section>
          <h2>6. Disclaimer</h2>
          <p>
            The Service is provided "as is" without warranties of any kind. Safety grades and
            evaluation results are automated assessments and do not constitute a guarantee of
            security or correctness. You are responsible for reviewing skills before using them
            in production systems.
          </p>
        </section>

        <section>
          <h2>7. Limitation of Liability</h2>
          <p>
            To the maximum extent permitted by law, PyMC Labs shall not be liable for any
            indirect, incidental, or consequential damages arising from the use of the Service
            or any skills obtained through it.
          </p>
        </section>

        <section>
          <h2>8. Changes</h2>
          <p>
            We may update these terms from time to time. Continued use of the Service after
            changes are posted constitutes acceptance of the updated terms.
          </p>
        </section>

        <section>
          <h2>9. Contact</h2>
          <p>
            For questions about these terms, contact us at{" "}
            <a href="mailto:info@pymc-labs.com">info@pymc-labs.com</a>.
          </p>
        </section>
      </article>
    </div>
  );
}
