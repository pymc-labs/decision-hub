import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";

/** Inject <meta name="robots" content="noindex, nofollow"> into the static
 *  HTML when building for a non-prod environment so crawlers that don't
 *  execute JavaScript still see the directive. */
function noindexPlugin(): Plugin {
  return {
    name: "noindex-non-prod",
    transformIndexHtml(html) {
      if (process.env.VITE_ENV === "prod") return html;
      return html.replace(
        "</head>",
        '    <meta name="robots" content="noindex, nofollow" />\n  </head>',
      );
    },
  };
}

export default defineConfig({
  plugins: [react(), noindexPlugin()],
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          "syntax-highlighter": ["react-syntax-highlighter"],
          vendor: ["react", "react-dom", "react-router-dom"],
        },
      },
    },
  },
});
