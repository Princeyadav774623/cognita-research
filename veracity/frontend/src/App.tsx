import { useCallback, useEffect, useRef, useState } from "react";
import {
  api, VERDICTS,
  type Analysis, type AskAnswer, type Claim, type Media, type Transcript,
} from "./api";

const MODES = [
  { id: "summary", label: "Summary", cost: "1x", blurb: "What was said." },
  { id: "deep", label: "Deep", cost: "~4x", blurb: "How it was argued, and the claims in it." },
  { id: "report", label: "Report", cost: "~15x", blurb: "Every claim checked against independent sources." },
] as const;

const BUSY: Media["state"][] = [
  "pending", "fetching", "probing", "extracting", "transcribing", "chunking",
];

export function App() {
  const [items, setItems] = useState<Media[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setItems((await api.list()).items);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  // Poll only while something is mid-ingest. A fixed interval would keep the
  // tab busy forever on a page that is not changing.
  const busy = items.some((m) => BUSY.includes(m.state));
  useEffect(() => {
    if (!busy) return;
    const t = setInterval(() => void refresh(), 2000);
    return () => clearInterval(t);
  }, [busy, refresh]);

  const current = items.find((m) => m.id === selected) ?? null;

  return (
    <div className="shell">
      <header className="top">
        <div className="brand">Verac<span>i</span>ty</div>
        <div className="tag">claims, checked</div>
      </header>
      <p className="lede">
        Upload a video or audio file. You get a transcript anchored to
        timestamps and, at report depth, every factual claim in it checked
        against sources the speaker never cited.
      </p>

      {error && <div className="err">{error}</div>}

      <div className="grid">
        <div>
          <Uploader onDone={refresh} onError={setError} />
          <div className="card" style={{ marginTop: 16 }}>
            <h2>Your media</h2>
            {items.length === 0 ? (
              <div className="empty">Nothing yet.</div>
            ) : (
              items.map((m) => (
                <MediaRow
                  key={m.id} media={m} active={m.id === selected}
                  onPick={() => setSelected(m.id)}
                  onDelete={async () => {
                    await api.remove(m.id);
                    if (selected === m.id) setSelected(null);
                    void refresh();
                  }}
                />
              ))
            )}
          </div>
        </div>

        <div>
          {current ? (
            <Detail media={current} onError={setError} />
          ) : (
            <div className="card">
              <div className="empty">Pick something on the left, or upload a file.</div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function Uploader({ onDone, onError }: {
  onDone: () => void; onError: (m: string) => void;
}) {
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  const send = async (file: File | undefined) => {
    if (!file) return;
    setBusy(true);
    try {
      await api.upload(file);
      onDone();
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  };

  return (
    <div className="card">
      <h2>Add media</h2>
      <div
        className={over ? "drop over" : "drop"}
        onDragOver={(e) => { e.preventDefault(); setOver(true); }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault(); setOver(false);
          void send(e.dataTransfer.files[0]);
        }}
      >
        {busy ? (
          <><span className="spin" /> uploading…</>
        ) : (
          <>
            Drop a file here, or{" "}
            <label htmlFor="pick">choose one</label>
            <input id="pick" ref={input} type="file"
                   accept="audio/*,video/*"
                   onChange={(e) => void send(e.target.files?.[0])} />
            <div className="hint">Audio or video. Transcribed, then analysed on request.</div>
          </>
        )}
      </div>
    </div>
  );
}

function MediaRow({ media, active, onPick, onDelete }: {
  media: Media; active: boolean; onPick: () => void; onDelete: () => void;
}) {
  const working = BUSY.includes(media.state);
  return (
    <div className="row" style={{ gap: 6 }}>
      <button className={active ? "item on" : "item"} onClick={onPick}
              style={{ flex: 1 }}>
        <div className="name">{media.title || media.filename || media.id.slice(0, 8)}</div>
        <div className="meta">
          {working && <span className="spin" style={{ marginRight: 6 }} />}
          {media.state === "ready"
            ? `${media.duration ?? "—"} · ${media.language ?? "?"}`
            : media.state}
          {media.state === "failed" && " · see below"}
        </div>
      </button>
      <button className="item" style={{ width: "auto", color: "var(--ink-3)" }}
              onClick={onDelete} aria-label="Delete">×</button>
    </div>
  );
}

function Detail({ media, onError }: { media: Media; onError: (m: string) => void }) {
  const [transcript, setTranscript] = useState<Transcript | null>(null);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [pending, setPending] = useState<string | null>(null);

  useEffect(() => {
    setTranscript(null); setAnalysis(null); setPending(null);
    if (media.state !== "ready") return;
    api.transcript(media.id).then(setTranscript).catch(() => setTranscript(null));
    // Show the newest finished analysis without making the user ask for it.
    api.analyses(media.id).then(({ items }) => {
      const done = items.find((a) => a.state === "complete");
      if (done) void api.analysis(media.id, done.id).then(setAnalysis);
    }).catch(() => undefined);
  }, [media.id, media.state]);

  // While an analysis is running, poll it rather than leaving a dead spinner.
  useEffect(() => {
    if (!pending) return;
    const t = setInterval(async () => {
      try {
        const a = await api.analysis(media.id, pending);
        if (a.state === "complete" || a.state === "failed") {
          setAnalysis(a);
          setPending(null);
          if (a.state === "failed" && a.error) onError(a.error);
        }
      } catch { /* keep polling; a transient failure is not fatal */ }
    }, 3000);
    return () => clearInterval(t);
  }, [pending, media.id, onError]);

  const start = async (mode: string) => {
    try {
      const { id } = await api.analyse(media.id, mode);
      setAnalysis(null);
      setPending(id);
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    }
  };

  if (media.state === "failed") {
    return (
      <div className="card">
        <h2>Could not process this</h2>
        <div className="err" style={{ marginBottom: 0 }}>{media.error}</div>
      </div>
    );
  }
  if (media.state !== "ready") {
    return (
      <div className="card">
        <h2>Working</h2>
        <div className="empty">
          <span className="spin" style={{ marginRight: 8 }} />
          {media.state}…
        </div>
      </div>
    );
  }

  return (
    <>
      <div className="card" style={{ marginBottom: 16 }}>
        <h2>Analyse</h2>
        <div className="modes">
          {MODES.map((m) => (
            <button key={m.id} className="mode" disabled={!!pending}
                    onClick={() => void start(m.id)} title={m.blurb}>
              {m.label}<span className="cost">{m.cost}</span>
            </button>
          ))}
        </div>
        {pending && (
          <div className="note">
            <span className="spin" style={{ marginRight: 8 }} />
            Running. Report depth searches for every claim separately, so it
            takes a couple of minutes.
          </div>
        )}
        <div className="hint" style={{ marginTop: 10 }}>
          {MODES.map((m) => `${m.label}: ${m.blurb}`).join("  ")}
        </div>
      </div>

      <AskPanel mediaId={media.id} onError={onError} />

      {analysis && <AnalysisView analysis={analysis} />}

      {transcript && (
        <div className="card" style={{ marginTop: 16 }}>
          <h2>Transcript · {transcript.segment_count} segments</h2>
          {transcript.confidence !== null && (
            <div className="hint" style={{ marginBottom: 10 }}>
              Transcription confidence {(transcript.confidence * 100).toFixed(0)}%
              {transcript.confidence_is_derived &&
                " — derived from the model's per-segment average, not a measured per-word probability."}
            </div>
          )}
          <div className="scroll">
            {transcript.segments.map((s) => (
              <div className="seg" key={s.ordinal}>
                <div className="t">{s.at}</div>
                <div className="x">{s.text}</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </>
  );
}

function AskPanel({ mediaId, onError }: {
  mediaId: string; onError: (m: string) => void;
}) {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<AskAnswer | null>(null);
  const [busy, setBusy] = useState(false);

  // A new item means a new transcript; keeping the previous answer on screen
  // would attribute it to media it did not come from.
  useEffect(() => { setAnswer(null); setQuestion(""); }, [mediaId]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const q = question.trim();
    if (!q || busy) return;
    setBusy(true);
    try {
      setAnswer(await api.ask(mediaId, q));
    } catch (err) {
      onError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card" style={{ marginBottom: 16 }}>
      <h2>Ask this transcript</h2>
      <form onSubmit={submit} className="row" style={{ gap: 8 }}>
        <input
          className="ask" value={question} disabled={busy}
          placeholder="What did they say about…?"
          onChange={(e) => setQuestion(e.target.value)}
        />
        <button className="mode" type="submit" disabled={busy || !question.trim()}>
          {busy ? <span className="spin" /> : "Ask"}
        </button>
      </form>

      {answer && (
        <div style={{ marginTop: 14 }}>
          <div className="row" style={{ marginBottom: 8 }}>
            <span className={answer.answered ? "pill ok" : "pill warn"}>
              {answer.answered ? "Answered" : "Not in this transcript"}
            </span>
          </div>
          <p style={{ fontFamily: "var(--serif)", margin: "0 0 10px" }}>
            {answer.answer}
          </p>
          {answer.passages.some((p) => p.used) && (
            <>
              <div className="hint" style={{ marginBottom: 6 }}>
                Answered from these moments — click a timestamp to see the words.
              </div>
              {answer.passages.filter((p) => p.used).map((p) => (
                <div className="seg" key={p.start_ms}>
                  <div className="t">{p.at}</div>
                  <div className="x">{p.text}</div>
                </div>
              ))}
            </>
          )}
        </div>
      )}
      {!answer && (
        <div className="hint" style={{ marginTop: 10 }}>
          Answers come only from what was actually said. If the transcript does
          not cover it, you get told so rather than a plausible guess.
        </div>
      )}
    </div>
  );
}

function AnalysisView({ analysis: a }: { analysis: Analysis }) {
  const counts = a.confidence_factors?.counts ?? {};
  return (
    <>
      {a.overall_confidence !== null && (
        <div className="card" style={{ marginBottom: 16 }}>
          <h2>How much to trust this</h2>
          <div className="score">
            <div className="n" style={{ color: tone(a.overall_confidence) }}>
              {(a.overall_confidence * 100).toFixed(0)}%
            </div>
            <div className="row">
              {Object.entries(counts)
                .filter(([, n]) => n > 0)
                .map(([k, n]) => (
                  <span key={k} className={`pill ${VERDICTS[k as keyof typeof VERDICTS]?.tone ?? "mute"}`}>
                    {n} {VERDICTS[k as keyof typeof VERDICTS]?.label ?? k}
                  </span>
                ))}
            </div>
          </div>
          <ul className="factors">
            {(a.confidence_factors?.factors ?? []).map((f, i) => <li key={i}>{f}</li>)}
          </ul>
          <div className="hint" style={{ marginTop: 10 }}>
            {a.tokens_used.toLocaleString()} tokens · ${a.cost_usd.toFixed(4)}
          </div>
        </div>
      )}

      {a.summary && (
        <div className="card" style={{ marginBottom: 16 }}>
          <h2>Summary</h2>
          <p style={{ fontFamily: "var(--serif)", marginTop: 0 }}>{a.summary}</p>
          {a.key_points.length > 0 && (
            <ul className="factors">
              {a.key_points.map((p, i) => (
                <li key={i}>
                  {p.at && <span className="at">{p.at} </span>}
                  {p.point}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {a.claims.length > 0 && (
        <div className="card" style={{ marginBottom: 16 }}>
          <h2>Claims · {a.claims.length}</h2>
          {a.claims.map((c) => <ClaimCard key={c.ordinal} claim={c} />)}
        </div>
      )}

      {a.perspectives.length > 0 && (
        <div className="card">
          <h2>The other side</h2>
          <div className="hint" style={{ marginBottom: 12 }}>
            Found by searching for material that disagrees — not generated for balance.
          </div>
          {a.perspectives.map((p, i) => (
            <div className="claim" key={i}>
              <div className="head">
                {p.at && <span className="at">{p.at}</span>}
                <span className="pill accent">{p.kind.replace(/_/g, " ")}</span>
              </div>
              <p className="prop">{p.claim}</p>
              <p className="why">{p.summary}</p>
              {p.held_by && <p className="spoken">Held by: {p.held_by}</p>}
            </div>
          ))}
        </div>
      )}
    </>
  );
}

function ClaimCard({ claim: c }: { claim: Claim }) {
  const v = VERDICTS[c.verdict];
  return (
    <div className="claim">
      <div className="head">
        <span className="at">{c.at}</span>
        <span className={`pill ${v.tone}`}>{v.label}</span>
        {c.verdict_confidence !== null && c.verdict_confidence > 0 && (
          <span className="pill mute">{(c.verdict_confidence * 100).toFixed(0)}% sure</span>
        )}
        {c.independently_corroborated && (
          <span className="pill mute">independent</span>
        )}
      </div>
      <p className="prop">{c.proposition}</p>
      {c.spoken !== c.proposition && <p className="spoken">“{c.spoken}”</p>}
      <p className="why">{c.reasoning || v.means}</p>
      {c.evidence.length > 0 && (
        <ul className="sources">
          {c.evidence.slice(0, 4).map((e, i) => (
            <li key={i}>
              <a href={e.url} target="_blank" rel="noreferrer noopener" title={e.title}>
                {hostOf(e.url)}
              </a>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function tone(score: number): string {
  if (score >= 0.75) return "var(--ok)";
  if (score >= 0.5) return "var(--warn)";
  return "var(--bad)";
}

function hostOf(url: string): string {
  try { return new URL(url).hostname.replace(/^www\./, ""); }
  catch { return url.slice(0, 32); }
}
