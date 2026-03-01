import styles from "./GradientMesh.module.css";

export default function GradientMesh() {
  return (
    <div className={styles.mesh} aria-hidden="true">
      <div className={styles.blob1} />
      <div className={styles.blob2} />
      <div className={styles.blob3} />
      <div className={styles.blob4} />
    </div>
  );
}
