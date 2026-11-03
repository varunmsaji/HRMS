import Image from "next/image";

interface LogoProps {
  /** `full` = mark + wordmark, `mark` = icon only, `wordmark` = text only. */
  variant?: "full" | "mark" | "wordmark";
  /** Use the white wordmark on dark backgrounds. */
  onDark?: boolean;
  /** Rendered height of the mark in px (wordmark scales proportionally). */
  size?: number;
  className?: string;
}

// Intrinsic aspect ratios of the files in /public/brand.
const MARK_RATIO = 648 / 592;
const WORDMARK_RATIO = 1640 / 260;

export function Logo({ variant = "full", onDark = false, size = 32, className }: LogoProps) {
  const mark = (
    <Image
      src={onDark ? "/brand/krewoxa-mark-on-dark.svg" : "/brand/krewoxa-mark.svg"}
      alt={variant === "mark" ? "Krewoxa" : ""}
      width={Math.round(size * MARK_RATIO)}
      height={size}
      unoptimized
      priority
    />
  );
  const wordHeight = Math.round(size * 0.55);
  const wordmark = (
    <Image
      src={onDark ? "/brand/krewoxa-wordmark-white.svg" : "/brand/krewoxa-wordmark.svg"}
      alt={variant === "wordmark" ? "Krewoxa" : ""}
      width={Math.round(wordHeight * WORDMARK_RATIO)}
      height={wordHeight}
      unoptimized
      priority
    />
  );
  if (variant === "mark") return <span className={className}>{mark}</span>;
  if (variant === "wordmark") return <span className={className}>{wordmark}</span>;
  return (
    <span className={`inline-flex items-center gap-2.5 ${className ?? ""}`} role="img" aria-label="Krewoxa">
      {mark}
      {wordmark}
    </span>
  );
}
