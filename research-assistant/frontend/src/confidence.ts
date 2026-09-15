/**
 * One definition of what a confidence score means.
 *
 * There were three sets of thresholds: the badge colour switched at 0.8/0.5,
 * the label at 0.8/0.6/0.4, and the backend's own label at 0.8/0.6/0.4 again.
 * Between 0.50 and 0.59 that produced a moderate-coloured badge reading
 * "Low Grounding". Must stay in step with get_confidence_label in
 * backend/agents/report_agent.py.
 */
export const CONFIDENCE_BANDS = [
  { min: 0.8, label: "High Grounding", tone: "high" },
  { min: 0.6, label: "Moderate Grounding", tone: "mod" },
  { min: 0.4, label: "Low Grounding", tone: "low" },
  { min: 0, label: "Uncertain", tone: "low" },
] as const;

export function confidenceBand(score: number) {
  return CONFIDENCE_BANDS.find((b) => score >= b.min) ?? CONFIDENCE_BANDS[CONFIDENCE_BANDS.length - 1];
}
