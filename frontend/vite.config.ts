import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
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
