import type { SessionRecord } from "./api";

/** Characters BibTeX treats as markup, plus the accents it wants escaped. */
function bibtexEscape(value: string): string {
  return value
    .replace(/[\\{}&%$#_^~]/g, (c) => `\\${c}`)
    .replace(/\s+/g, " ")
    .trim();
}

/** A stable, readable citation key: firstword-domain-year. */
function citationKey(title: string, url: string, index: number): string {
  const word = (title.match(/[A-Za-z]{3,}/) || ["source"])[0].toLowerCase();
  let host = "web";
  try {
    host = new URL(url).hostname.replace(/^www\./, "").split(".")[0];
  } catch {
    // Not a parseable URL (an upload:// corpus document, say) — keep "web".
  }
  return `${word}-${host}-${index + 1}`;
}

/**
 * Sources as BibTeX. Researchers put these in a bibliography, not a Markdown
 * file — Markdown-only export meant retyping every reference by hand.
 *
 * Entries are @misc with an access date: these are web sources, and claiming
 * @article would assert bibliographic detail the pipeline never collected.
 */
export function toBibTeX(result: SessionRecord): string {
  const accessed = result.created_at ? new Date(result.created_at) : new Date();
  const urldate = accessed.toISOString().slice(0, 10);

  const entries = (result.sources ?? []).map((source, i) => {
    const key = citationKey(source.title || "source", source.url, i);
    return [
      `@misc{${key},`,
      `  title        = {${bibtexEscape(source.title || "Untitled source")}},`,
      `  howpublished = {\\url{${source.url}}},`,
      `  note         = {Accessed: ${urldate}},`,
      `  urldate      = {${urldate}}`,
      `}`,
    ].join("\n");
  });

  const header = [
    `% Sources for: ${bibtexEscape(result.query)}`,
    `% Exported from Cognita on ${urldate}`,
    `% ${entries.length} reference${entries.length === 1 ? "" : "s"}`,
    "",
  ].join("\n");

  return header + entries.join("\n\n") + "\n";
}

export function downloadText(filename: string, contents: string, mime: string): void {
  const blob = new Blob([contents], { type: `${mime};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
