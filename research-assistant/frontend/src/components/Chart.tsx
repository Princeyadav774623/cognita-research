/**
 * Charts from a ```chart fence in the report.
 *
 * Hand-drawn SVG rather than a charting library: the whole surface needed is
 * bars, lines and a pie, and a library would ship far more than that while
 * fighting the theme. Everything reads from the same CSS variables as the rest
 * of the app, so both themes work without a second palette.
 *
 * The model emits JSON, which is far more reliable than asking it to produce
 * correct SVG or a chart DSL:
 *
 *   ```chart
 *   {"type":"bar","title":"Cost per MWh","unit":"$",
 *    "data":[{"label":"Solar","value":40},{"label":"Gas","value":70}]}
 *   ```
 */

export interface ChartPoint {
  label: string;
  value: number;
}

export interface ChartSpec {
  type: "bar" | "line" | "pie";
  title?: string;
  unit?: string;
  data: ChartPoint[];
}

/** Sequential tints of the accent, so a chart never introduces a palette the
 *  rest of the page doesn't use. */
const SLICE_OPACITY = [1, 0.82, 0.64, 0.48, 0.36, 0.26, 0.18, 0.12];

export function parseChartSpec(raw: string): ChartSpec | null {
  try {
    const parsed = JSON.parse(raw);
    if (!parsed || !Array.isArray(parsed.data) || parsed.data.length === 0) return null;
    const data: ChartPoint[] = parsed.data
      .filter((d: unknown): d is ChartPoint =>
        !!d && typeof (d as ChartPoint).label === "string" &&
        typeof (d as ChartPoint).value === "number" && Number.isFinite((d as ChartPoint).value))
      .slice(0, 12);
    if (!data.length) return null;
    const type = ["bar", "line", "pie"].includes(parsed.type) ? parsed.type : "bar";
    return { type, title: parsed.title, unit: parsed.unit, data };
  } catch {
    return null;
  }
}

function formatValue(value: number, unit?: string): string {
  const n = Number.isInteger(value) ? value.toString() : value.toFixed(1);
  if (!unit) return n;
  return unit === "%" || unit === "$" ? (unit === "$" ? `$${n}` : `${n}%`) : `${n} ${unit}`;
}

/** Horizontal bars: labels stay readable at any length, which vertical bars
 *  cannot promise, and comparison is what a bar chart is for. */
function BarChart({ spec }: { spec: ChartSpec }) {
  const max = Math.max(...spec.data.map((d) => Math.abs(d.value)), 0) || 1;
  return (
    <div className="chart-bars">
      {spec.data.map((d, i) => (
        <div className="chart-bar" key={`${d.label}-${i}`}>
          <span className="chart-bar__label" title={d.label}>{d.label}</span>
          <span className="chart-bar__track">
            <span
              className="chart-bar__fill"
              style={{ width: `${Math.max((Math.abs(d.value) / max) * 100, 1)}%` }}
            />
          </span>
          <span className="chart-bar__value">{formatValue(d.value, spec.unit)}</span>
        </div>
      ))}
    </div>
  );
}

function LineChart({ spec }: { spec: ChartSpec }) {
  const W = 640, H = 220, PAD_L = 8, PAD_R = 8, PAD_T = 14, PAD_B = 28;
  const values = spec.data.map((d) => d.value);
  const max = Math.max(...values), min = Math.min(...values, 0);
  const span = max - min || 1;
  const stepX = (W - PAD_L - PAD_R) / Math.max(spec.data.length - 1, 1);
  const y = (v: number) => PAD_T + (1 - (v - min) / span) * (H - PAD_T - PAD_B);
  const pts = spec.data.map((d, i) => [PAD_L + i * stepX, y(d.value)] as const);
  const path = pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ");
  const area = `${path} L${pts[pts.length - 1][0].toFixed(1)},${H - PAD_B} L${pts[0][0].toFixed(1)},${H - PAD_B} Z`;

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="chart-svg" role="img"
         aria-label={`Line chart: ${spec.data.map((d) => `${d.label} ${d.value}`).join(", ")}`}>
      <path d={area} fill="var(--accent-subtle)" />
      <path d={path} fill="none" stroke="var(--accent-warm)" strokeWidth="2"
            strokeLinejoin="round" strokeLinecap="round" />
      {pts.map((p, i) => (
        <g key={i}>
          <circle cx={p[0]} cy={p[1]} r="3" fill="var(--accent-warm)" />
          <text x={p[0]} y={H - PAD_B + 16} textAnchor="middle"
                fill="var(--text-muted)" fontSize="11" fontFamily="var(--font-mono)">
            {spec.data[i].label}
          </text>
          <text x={p[0]} y={p[1] - 9} textAnchor="middle"
                fill="var(--text-secondary)" fontSize="11" fontFamily="var(--font-mono)">
            {formatValue(spec.data[i].value, spec.unit)}
          </text>
        </g>
      ))}
    </svg>
  );
}

function PieChart({ spec }: { spec: ChartSpec }) {
  const total = spec.data.reduce((sum, d) => sum + Math.abs(d.value), 0) || 1;
  const R = 78, C = 100;
  let angle = -Math.PI / 2;

  return (
    <div className="chart-pie">
      <svg viewBox="0 0 200 200" className="chart-svg chart-svg--pie" role="img"
           aria-label={`Pie chart: ${spec.data.map((d) => `${d.label} ${d.value}`).join(", ")}`}>
        {spec.data.map((d, i) => {
          const slice = (Math.abs(d.value) / total) * Math.PI * 2;
          const x1 = C + R * Math.cos(angle), y1 = C + R * Math.sin(angle);
          angle += slice;
          const x2 = C + R * Math.cos(angle), y2 = C + R * Math.sin(angle);
          const large = slice > Math.PI ? 1 : 0;
          // A single slice covering everything cannot be drawn as an arc —
          // the start and end points coincide, so the path collapses.
          const d3 = spec.data.length === 1
            ? `M${C},${C} m-${R},0 a${R},${R} 0 1,0 ${R * 2},0 a${R},${R} 0 1,0 -${R * 2},0`
            : `M${C},${C} L${x1.toFixed(2)},${y1.toFixed(2)} A${R},${R} 0 ${large},1 ${x2.toFixed(2)},${y2.toFixed(2)} Z`;
          return <path key={i} d={d3} fill="var(--accent-warm)"
                       opacity={SLICE_OPACITY[i % SLICE_OPACITY.length]}
                       stroke="var(--bg-app)" strokeWidth="1.5" />;
        })}
      </svg>
      <ul className="chart-legend">
        {spec.data.map((d, i) => (
          <li key={i}>
            <span className="chart-legend__swatch"
                  style={{ opacity: SLICE_OPACITY[i % SLICE_OPACITY.length] }} />
            <span className="chart-legend__label">{d.label}</span>
            <span className="chart-legend__value">
              {formatValue(d.value, spec.unit)}
              {/* The share is only worth adding when the value isn't already a
                  percentage — otherwise the legend reads "61% 61%". */}
              {spec.unit !== "%" && (
                <span className="chart-legend__pct">
                  {Math.round((Math.abs(d.value) / total) * 100)}%
                </span>
              )}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function Chart({ spec }: { spec: ChartSpec }) {
  return (
    <figure className="chart">
      {spec.title && <figcaption className="chart__title">{spec.title}</figcaption>}
      {spec.type === "pie" ? <PieChart spec={spec} />
        : spec.type === "line" ? <LineChart spec={spec} />
        : <BarChart spec={spec} />}
    </figure>
  );
}
