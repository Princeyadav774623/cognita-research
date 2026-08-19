/**
 * Cognita icon set.
 *
 * Replaces the emoji that were previously used as UI icons. Emoji render
 * differently on every OS, carry their own baked-in colour, sit on an
 * inconsistent optical weight, and can't respond to the theme — which is why
 * the interface read as generic.
 *
 * House rules for this set, so additions stay coherent:
 *   - 24×24 grid, geometry drawn on whole/half units
 *   - stroke-only, 1.5 weight, round caps and joins (no filled shapes)
 *   - `currentColor` everywhere, so an icon inherits text colour and any
 *     accent applied by its container, in both light and dark themes
 *   - the brand's four-point spark recurs inside icons that denote an
 *     AI/model action, tying the set to the ✶ wordmark
 */

export type IconName =
  | "spark"
  | "compass"
  | "search"
  | "document"
  | "brain"
  | "verified"
  | "gap"
  | "report"
  | "inspector"
  | "sliders"
  | "download"
  | "copy"
  | "clock"
  | "plus"
  | "close"
  | "check"
  | "cross"
  | "alert"
  | "sun"
  | "moon"
  | "chevron"
  | "upload"
  | "send"
  | "sources"
  | "trash";

interface Props {
  name: IconName;
  size?: number;
  /** Optical stroke weight; 1.5 is the set's default. */
  weight?: number;
  className?: string;
  /** Decorative by default. Pass a label to expose it to screen readers. */
  label?: string;
  style?: React.CSSProperties;
}

/** The four-point spark from the wordmark — reused inside "AI action" icons. */
const SPARK = "M12 3.5 13.1 9l5.4 1.1-5.4 1.1L12 16.5l-1.1-5.3L5.5 10.1 10.9 9z";

const PATHS: Record<IconName, React.ReactNode> = {
  spark: <path d={SPARK} />,

  // Planner — a compass needle, not a magnetic compass: research direction.
  compass: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M15.4 8.6 13.6 13.6 8.6 15.4 10.4 10.4z" />
    </>
  ),

  // Search — offset lens with a directional tail, reads at 16px.
  search: (
    <>
      <circle cx="10.5" cy="10.5" r="6" />
      <path d="M15 15l5 5" />
    </>
  ),

  // Reader — page with a folded corner and text ruling.
  document: (
    <>
      <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />
      <path d="M14 3v5h5" />
      <path d="M9 13h6M9 16.5h4" />
    </>
  ),

  // Analyst — synthesis: converging nodes rather than a literal brain.
  brain: (
    <>
      <circle cx="6" cy="7" r="2.2" />
      <circle cx="6" cy="17" r="2.2" />
      <circle cx="17.5" cy="12" r="2.6" />
      <path d="M8.1 8.2 15.2 11M8.1 15.8 15.2 13" />
    </>
  ),

  // Fact-checker — a check earned inside a seal.
  verified: (
    <>
      <path d="M12 2.8 19.5 6v6c0 4-3.1 7.4-7.5 9.2C7.6 19.4 4.5 16 4.5 12V6z" />
      <path d="M8.9 12.1l2.2 2.2 4.2-4.4" />
    </>
  ),

  // Gap analysis — the reflective loop: re-enter the search with a spark
  // marking the model's own judgement of what's still missing.
  gap: (
    <>
      <path d="M20 12a8 8 0 1 1-2.6-5.9" />
      <path d="M20.2 3.6v4.2H16" />
      <path d="m12 9.2.9 1.9 1.9.9-1.9.9-.9 1.9-.9-1.9-1.9-.9 1.9-.9z" />
    </>
  ),

  // Report — document carrying the spark: model-authored output.
  report: (
    <>
      <path d="M19 10.5V19a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h6" />
      <path d="M8.5 16h7M8.5 12.5h4" />
      <path d="m17.4 2.6.7 2.6 2.6.7-2.6.7-.7 2.6-.7-2.6-2.6-.7 2.6-.7z" />
    </>
  ),

  // Inspector — aperture/iris: looking into the pipeline, not a microscope.
  inspector: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <circle cx="12" cy="12" r="3" />
      <path d="M12 3.5v5M12 15.5v5M3.5 12h5M15.5 12h5" />
    </>
  ),

  // Parameter tuning — three tracks at different positions.
  sliders: (
    <>
      <path d="M5 6h14M5 12h14M5 18h14" />
      <circle cx="9" cy="6" r="2" />
      <circle cx="15" cy="12" r="2" />
      <circle cx="7.5" cy="18" r="2" />
    </>
  ),

  download: (
    <>
      <path d="M12 4v11" />
      <path d="m7.8 10.8 4.2 4.2 4.2-4.2" />
      <path d="M4.5 19.5h15" />
    </>
  ),

  copy: (
    <>
      <rect x="9" y="9" width="11" height="11" rx="2" />
      <path d="M15 9V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h3" />
    </>
  ),

  clock: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 7.2V12l3.2 2" />
    </>
  ),

  plus: <path d="M12 5.5v13M5.5 12h13" />,
  close: <path d="M6.5 6.5l11 11M17.5 6.5l-11 11" />,
  check: <path d="M5 12.5l4.6 4.6L19 7.5" />,
  cross: <path d="M7 7l10 10M17 7L7 17" />,

  alert: (
    <>
      <path d="M12 3.6 21 19.4H3z" />
      <path d="M12 9.8v4.1M12 16.6h.01" />
    </>
  ),

  sun: (
    <>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2.5v2.2M12 19.3v2.2M4.9 4.9l1.6 1.6M17.5 17.5l1.6 1.6M2.5 12h2.2M19.3 12h2.2M4.9 19.1l1.6-1.6M17.5 6.5l1.6-1.6" />
    </>
  ),

  moon: <path d="M20 13.4A8.2 8.2 0 0 1 10.6 4a8.5 8.5 0 1 0 9.4 9.4z" />,
  chevron: <path d="m7 10 5 5 5-5" />,

  upload: (
    <>
      <path d="M12 16V5" />
      <path d="m7.8 9.2 4.2-4.2 4.2 4.2" />
      <path d="M4.5 15v3.5a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2V15" />
    </>
  ),

  send: (
    <>
      <path d="M20 4 3.5 10.4l6.6 2.5 2.5 6.6z" />
      <path d="M20 4l-9.9 8.9" />
    </>
  ),

  // Citations — stacked pages.
  sources: (
    <>
      <path d="M8 4.5h8.5a2 2 0 0 1 2 2V17" />
      <rect x="4.5" y="7.5" width="11" height="12" rx="2" />
    </>
  ),

  trash: (
    <>
      <path d="M4.8 7h14.4" />
      <path d="M9.5 7V5.6a1.6 1.6 0 0 1 1.6-1.6h1.8a1.6 1.6 0 0 1 1.6 1.6V7" />
      <path d="M6.6 7l.8 11.5a2 2 0 0 0 2 1.9h5.2a2 2 0 0 0 2-1.9L17.4 7" />
    </>
  ),
};

export function Icon({ name, size = 18, weight = 1.5, className, label, style }: Props) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={weight}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      style={{ flexShrink: 0, display: "block", ...style }}
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      focusable="false"
    >
      {PATHS[name]}
    </svg>
  );
}
