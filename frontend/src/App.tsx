import { Routes, Route, useParams } from "react-router-dom";
import Layout from "./components/Layout";
import HomePage from "./pages/HomePage";
import SkillsPage from "./pages/SkillsPage";
import SkillDetailPage from "./pages/SkillDetailPage";
import OrgsPage from "./pages/OrgsPage";
import OrgDetailPage from "./pages/OrgDetailPage";
import HowItWorksPage from "./pages/HowItWorksPage";
import TermsPage from "./pages/TermsPage";
import PrivacyPage from "./pages/PrivacyPage";
import PluginsPage from "./pages/PluginsPage";
import PluginDetailPage from "./pages/PluginDetailPage";
import NotFoundPage from "./pages/NotFoundPage";

/** Wrapper that remounts PluginDetailPage when URL params change, resetting all local state. */
function PluginDetailRoute() {
  const { orgSlug, pluginName } = useParams();
  return <PluginDetailPage key={`${orgSlug}/${pluginName}`} />;
}

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<HomePage />} />
        <Route path="/skills" element={<SkillsPage />} />
        <Route path="/skills/:orgSlug/:skillName" element={<SkillDetailPage />} />
        <Route path="/plugins" element={<PluginsPage />} />
        <Route path="/plugins/:orgSlug/:pluginName" element={<PluginDetailRoute />} />
        <Route path="/orgs" element={<OrgsPage />} />
        <Route path="/orgs/:orgSlug" element={<OrgDetailPage />} />
        <Route path="/how-it-works" element={<HowItWorksPage />} />
        <Route path="/terms" element={<TermsPage />} />
        <Route path="/privacy" element={<PrivacyPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
