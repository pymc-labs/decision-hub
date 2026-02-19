import { useState, useRef, useEffect, useCallback } from "react";
import { Link } from "react-router-dom";
import { Search, X, Send, Loader2, ExternalLink, Sparkles } from "lucide-react";
import { askQuestion } from "../api/client";
import GradeBadge from "./GradeBadge";
import type { AskResponse, AskSkillRef } from "../types/api";
import styles from "./AskModal.module.css";

interface Message {
  role: "user" | "assistant";
  content: string;
  skills?: AskSkillRef[];
}

interface AskModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export default function AskModal({ isOpen, onClose }: AskModalProps) {
  const [query, setQuery] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Focus input when modal opens
  useEffect(() => {
    if (isOpen) {
      // Small delay so the modal animation completes before focusing
      const timer = setTimeout(() => inputRef.current?.focus(), 100);
      return () => clearTimeout(timer);
    }
  }, [isOpen]);

  // Scroll to bottom when new messages arrive
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Close on Escape
  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose]);

  // Prevent body scroll when modal is open
  useEffect(() => {
    if (isOpen) {
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = "";
    }
    return () => {
      document.body.style.overflow = "";
    };
  }, [isOpen]);

  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      const trimmed = query.trim();
      if (!trimmed || loading) return;

      setMessages((prev) => [...prev, { role: "user", content: trimmed }]);
      setQuery("");
      setLoading(true);
      setError(null);

      try {
        const response: AskResponse = await askQuestion(trimmed);
        setMessages((prev) => [
          ...prev,
          {
            role: "assistant",
            content: response.answer,
            skills: response.skills,
          },
        ]);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Something went wrong");
      } finally {
        setLoading(false);
      }
    },
    [query, loading]
  );

  if (!isOpen) return null;

  return (
    <div className={styles.overlay} onClick={onClose}>
      <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
        <div className={styles.header}>
          <div className={styles.headerTitle}>
            <Sparkles size={18} className={styles.sparkleIcon} />
            <span>Ask Decision Hub</span>
          </div>
          <button className={styles.closeBtn} onClick={onClose} aria-label="Close">
            <X size={18} />
          </button>
        </div>

        <div className={styles.conversation}>
          {messages.length === 0 && (
            <div className={styles.emptyState}>
              <Search size={32} className={styles.emptyIcon} />
              <p className={styles.emptyTitle}>What are you looking for?</p>
              <p className={styles.emptyHint}>
                Ask about skills, tools, or capabilities. I'll find the best
                matches and explain why they fit.
              </p>
              <div className={styles.suggestions}>
                {[
                  "Help me build a Bayesian model",
                  "Tools for writing LinkedIn posts",
                  "Analyze A/B test results",
                ].map((suggestion) => (
                  <button
                    key={suggestion}
                    className={styles.suggestion}
                    onClick={() => {
                      setQuery(suggestion);
                      inputRef.current?.focus();
                    }}
                  >
                    {suggestion}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((msg, i) => (
            <div
              key={i}
              className={`${styles.message} ${
                msg.role === "user" ? styles.userMessage : styles.assistantMessage
              }`}
            >
              <div className={styles.messageContent}>
                {msg.content.split("\n").map((line, j) => (
                  <p key={j}>{line || "\u00A0"}</p>
                ))}
              </div>
              {msg.skills && msg.skills.length > 0 && (
                <div className={styles.skillCards}>
                  {msg.skills.map((skill) => (
                    <Link
                      key={`${skill.org_slug}/${skill.skill_name}`}
                      to={`/skills/${skill.org_slug}/${skill.skill_name}`}
                      className={styles.skillCard}
                      onClick={onClose}
                    >
                      <div className={styles.skillCardHeader}>
                        <span className={styles.skillName}>
                          {skill.org_slug}/{skill.skill_name}
                        </span>
                        <GradeBadge grade={skill.safety_rating} size="sm" />
                      </div>
                      {skill.description && (
                        <p className={styles.skillDescription}>
                          {skill.description}
                        </p>
                      )}
                      {skill.reason && (
                        <p className={styles.skillReason}>{skill.reason}</p>
                      )}
                      <ExternalLink size={12} className={styles.linkIcon} />
                    </Link>
                  ))}
                </div>
              )}
            </div>
          ))}

          {loading && (
            <div className={`${styles.message} ${styles.assistantMessage}`}>
              <div className={styles.loadingIndicator}>
                <Loader2 size={16} className={styles.spinner} />
                <span>Searching skills...</span>
              </div>
            </div>
          )}

          {error && (
            <div className={styles.errorMessage}>
              {error}
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        <form className={styles.inputArea} onSubmit={handleSubmit}>
          <input
            ref={inputRef}
            type="text"
            className={styles.input}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Ask about skills..."
            disabled={loading}
            maxLength={500}
          />
          <button
            type="submit"
            className={styles.sendBtn}
            disabled={!query.trim() || loading}
            aria-label="Send"
          >
            <Send size={16} />
          </button>
        </form>
      </div>
    </div>
  );
}
