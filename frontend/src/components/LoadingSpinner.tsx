import styles from "./LoadingSpinner.module.css";

interface LoadingSpinnerProps {
  text?: string;
}

export default function LoadingSpinner({ text = "Loading..." }: LoadingSpinnerProps) {
  return (
    <div className={styles.wrapper}>
      <div className={styles.ring} />
      <p className={styles.text}>{text}</p>
    </div>
  );
}
