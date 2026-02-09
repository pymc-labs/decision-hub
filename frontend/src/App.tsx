import { Routes, Route } from "react-router-dom";
import Layout from "./components/Layout";
import HomePage from "./pages/HomePage";
import SkillsPage from "./pages/SkillsPage";
import SkillDetailPage from "./pages/SkillDetailPage";
import OrgsPage from "./pages/OrgsPage";
import OrgDetailPage from "./pages/OrgDetailPage";
import HowItWorksPage from "./pages/HowItWorksPage";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<HomePage />} />
        <Route path="/skills" element={<SkillsPage />} />
        <Route path="/skills/:orgSlug/:skillName" element={<SkillDetailPage />} />
        <Route path="/orgs" element={<OrgsPage />} />
        <Route path="/orgs/:orgSlug" element={<OrgDetailPage />} />
        <Route path="/how-it-works" element={<HowItWorksPage />} />
      </Route>
    </Routes>
  );
}
