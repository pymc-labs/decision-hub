import { useState } from "react";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/esm/styles/prism";
import { File, Folder, ChevronRight, ChevronDown } from "lucide-react";
import type { SkillFile } from "../types/api";
import { COLORS } from "../theme";
import styles from "./FileBrowser.module.css";

interface FileBrowserProps {
  files: SkillFile[];
}

interface TreeNode {
  name: string;
  path: string;
  children: TreeNode[];
  file?: SkillFile;
}

function buildTree(files: SkillFile[]): TreeNode[] {
  const root: TreeNode[] = [];

  for (const file of files) {
    const parts = file.path.split("/");
    let current = root;

    for (let i = 0; i < parts.length; i++) {
      const name = parts[i];
      const isFile = i === parts.length - 1;
      let node = current.find((n) => n.name === name);

      if (!node) {
        node = {
          name,
          path: parts.slice(0, i + 1).join("/"),
          children: [],
          file: isFile ? file : undefined,
        };
        current.push(node);
      }
      current = node.children;
    }
  }

  // Sort: directories first, then alphabetically
  function sortTree(nodes: TreeNode[]) {
    nodes.sort((a, b) => {
      const aIsDir = a.children.length > 0 && !a.file;
      const bIsDir = b.children.length > 0 && !b.file;
      if (aIsDir && !bIsDir) return -1;
      if (!aIsDir && bIsDir) return 1;
      return a.name.localeCompare(b.name);
    });
    for (const n of nodes) sortTree(n.children);
  }
  sortTree(root);
  return root;
}

function getLanguage(path: string): string {
  const ext = path.split(".").pop()?.toLowerCase() ?? "";
  const map: Record<string, string> = {
    py: "python",
    js: "javascript",
    ts: "typescript",
    tsx: "tsx",
    jsx: "jsx",
    json: "json",
    yaml: "yaml",
    yml: "yaml",
    md: "markdown",
    toml: "toml",
    sh: "bash",
    bash: "bash",
    css: "css",
    html: "html",
    sql: "sql",
    rs: "rust",
    go: "go",
    lock: "text",
    txt: "text",
    cfg: "ini",
    ini: "ini",
    env: "bash",
  };
  return map[ext] ?? "text";
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function TreeNodeView({
  node,
  depth,
  selectedPath,
  onSelect,
}: {
  node: TreeNode;
  depth: number;
  selectedPath: string | null;
  onSelect: (file: SkillFile) => void;
}) {
  const [expanded, setExpanded] = useState(depth < 2);
  const isDir = node.children.length > 0 && !node.file;
  const isSelected = node.path === selectedPath;

  if (isDir) {
    return (
      <div>
        <button
          className={styles.treeItem}
          style={{ paddingLeft: `${12 + depth * 16}px` }}
          onClick={() => setExpanded(!expanded)}
        >
          {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          <Folder size={14} className={styles.folderIcon} />
          <span>{node.name}</span>
        </button>
        {expanded &&
          node.children.map((child) => (
            <TreeNodeView
              key={child.path}
              node={child}
              depth={depth + 1}
              selectedPath={selectedPath}
              onSelect={onSelect}
            />
          ))}
      </div>
    );
  }

  return (
    <button
      className={`${styles.treeItem} ${isSelected ? styles.treeItemActive : ""}`}
      style={{ paddingLeft: `${12 + depth * 16}px` }}
      onClick={() => node.file && onSelect(node.file)}
    >
      <File size={14} className={styles.fileIcon} />
      <span>{node.name}</span>
    </button>
  );
}

// Editorial theme: warm, light background with muted syntax colors.
// Color values sourced from theme.ts COLORS to stay DRY with index.css.
const editorialTheme = {
  ...oneDark,
  'pre[class*="language-"]': {
    ...oneDark['pre[class*="language-"]'],
    background: COLORS.paper,
    fontSize: "0.85rem",
    lineHeight: "1.6",
    color: COLORS.ink,
  },
  'code[class*="language-"]': {
    ...oneDark['code[class*="language-"]'],
    background: "transparent",
    color: COLORS.ink,
  },
  comment: { color: COLORS.fog, fontStyle: "italic" },
  prolog: { color: COLORS.fog },
  doctype: { color: COLORS.fog },
  cdata: { color: COLORS.fog },
  punctuation: { color: COLORS.charcoal },
  property: { color: COLORS.terracotta },
  tag: { color: COLORS.terracotta },
  boolean: { color: COLORS.olive },
  number: { color: COLORS.olive },
  constant: { color: COLORS.olive },
  symbol: { color: COLORS.olive },
  selector: { color: COLORS.olive },
  "attr-name": { color: COLORS.charcoal },
  string: { color: COLORS.olive },
  char: { color: COLORS.olive },
  builtin: { color: COLORS.terracotta },
  operator: { color: COLORS.charcoal },
  entity: { color: COLORS.terracotta },
  url: { color: COLORS.charcoal },
  keyword: { color: COLORS.terracotta },
  regex: { color: COLORS.olive },
  important: { color: COLORS.terracotta },
  atrule: { color: COLORS.terracotta },
  "attr-value": { color: COLORS.olive },
  function: { color: COLORS.ink },
  "class-name": { color: COLORS.terracotta },
};

export default function FileBrowser({ files }: FileBrowserProps) {
  const defaultSelection = files.find((f) => f.path === "SKILL.md") ?? files[0] ?? null;

  // Reset selection when files change (render-time adjustment per React docs:
  // https://react.dev/learn/you-might-not-need-an-effect#adjusting-some-state-when-a-prop-changes)
  const [prevFiles, setPrevFiles] = useState(files);
  const [selected, setSelected] = useState<SkillFile | null>(defaultSelection);
  if (prevFiles !== files) {
    setPrevFiles(files);
    setSelected(defaultSelection);
  }

  const tree = buildTree(files);

  return (
    <div className={styles.browser}>
      <div className={styles.sidebar}>
        <div className={styles.sidebarHeader}>
          <Folder size={14} />
          <span>Files</span>
          <span className={styles.fileCount}>{files.length}</span>
        </div>
        <div className={styles.tree}>
          {tree.map((node) => (
            <TreeNodeView
              key={node.path}
              node={node}
              depth={0}
              selectedPath={selected?.path ?? null}
              onSelect={setSelected}
            />
          ))}
        </div>
      </div>

      <div className={styles.editor}>
        {selected ? (
          <>
            <div className={styles.editorHeader}>
              <span className={styles.editorPath}>{selected.path}</span>
              <span className={styles.editorSize}>
                {formatSize(selected.size)}
              </span>
            </div>
            <div className={styles.editorContent}>
              <SyntaxHighlighter
                language={getLanguage(selected.path)}
                style={editorialTheme}
                showLineNumbers
                lineNumberStyle={{
                  color: COLORS.fog,
                  minWidth: "3em",
                  paddingRight: "1em",
                  borderRight: `1px solid ${COLORS.mist}`,
                  marginRight: "1em",
                }}
                customStyle={{
                  margin: 0,
                  padding: "16px",
                  background: COLORS.paper,
                  borderRadius: 0,
                  minHeight: "400px",
                }}
              >
                {selected.content}
              </SyntaxHighlighter>
            </div>
          </>
        ) : (
          <div className={styles.editorEmpty}>
            <File size={48} />
            <p>Select a file to view</p>
          </div>
        )}
      </div>
    </div>
  );
}
