import { useState } from "react";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/esm/styles/prism";
import { File, Folder, ChevronRight, ChevronDown } from "lucide-react";
import type { SkillFile } from "../types/api";
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

// Editorial theme: warm, light background with muted syntax colors
const editorialTheme = {
  ...oneDark,
  'pre[class*="language-"]': {
    ...oneDark['pre[class*="language-"]'],
    background: "hsl(35, 20%, 94%)",
    fontSize: "0.85rem",
    lineHeight: "1.6",
    color: "hsl(35, 2%, 25%)",
  },
  'code[class*="language-"]': {
    ...oneDark['code[class*="language-"]'],
    background: "transparent",
    color: "hsl(35, 2%, 25%)",
  },
  comment: { color: "hsl(35, 5%, 60%)", fontStyle: "italic" },
  prolog: { color: "hsl(35, 5%, 60%)" },
  doctype: { color: "hsl(35, 5%, 60%)" },
  cdata: { color: "hsl(35, 5%, 60%)" },
  punctuation: { color: "hsl(35, 3%, 40%)" },
  property: { color: "hsl(15, 45%, 55%)" },
  tag: { color: "hsl(15, 45%, 55%)" },
  boolean: { color: "hsl(85, 15%, 45%)" },
  number: { color: "hsl(85, 15%, 45%)" },
  constant: { color: "hsl(85, 15%, 45%)" },
  symbol: { color: "hsl(85, 15%, 45%)" },
  selector: { color: "hsl(85, 15%, 45%)" },
  "attr-name": { color: "hsl(35, 3%, 40%)" },
  string: { color: "hsl(85, 15%, 45%)" },
  char: { color: "hsl(85, 15%, 45%)" },
  builtin: { color: "hsl(15, 45%, 55%)" },
  operator: { color: "hsl(35, 3%, 40%)" },
  entity: { color: "hsl(15, 45%, 55%)" },
  url: { color: "hsl(35, 3%, 40%)" },
  keyword: { color: "hsl(15, 45%, 55%)" },
  regex: { color: "hsl(85, 15%, 45%)" },
  important: { color: "hsl(15, 45%, 55%)" },
  atrule: { color: "hsl(15, 45%, 55%)" },
  "attr-value": { color: "hsl(85, 15%, 45%)" },
  function: { color: "hsl(35, 2%, 25%)" },
  "class-name": { color: "hsl(15, 45%, 55%)" },
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
                  color: "hsl(35, 5%, 60%)",
                  minWidth: "3em",
                  paddingRight: "1em",
                  borderRight: "1px solid hsl(35, 10%, 88%)",
                  marginRight: "1em",
                }}
                customStyle={{
                  margin: 0,
                  padding: "16px",
                  background: "hsl(35, 20%, 94%)",
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
