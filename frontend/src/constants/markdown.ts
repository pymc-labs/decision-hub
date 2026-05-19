// Shared remark/rehype plugin list for ReactMarkdown.
//
// Each component that renders user-controlled markdown (SkillDetailPage,
// AskModal, ...) used to declare its own `const REMARK_PLUGINS = [remarkGfm]`,
// so the plugin set diverged silently whenever one was tweaked. Centralising
// it keeps every renderer in lockstep on which markdown extensions are
// understood — important when the same content is rendered in multiple
// surfaces.
import remarkGfm from "remark-gfm";
import type { PluggableList } from "unified";

export const REMARK_PLUGINS: PluggableList = [remarkGfm];
