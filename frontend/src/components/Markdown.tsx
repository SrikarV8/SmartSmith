import React from "react";

/**
 * Tiny, dependency-free markdown renderer for streamed answers.
 * Builds React elements only (no innerHTML), so model output can't inject markup.
 */

const INLINE =
  /(\*\*[^*\n]+\*\*|`[^`\n]+`|\[[^\]\n]+\]\(https?:\/\/[^)\s]+\)|https?:\/\/[^\s<>)\]]+|\*[^*\n]+\*)/g;

function renderInline(text: string, keyPrefix: string): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  let last = 0;
  let n = 0;
  for (const match of Array.from(text.matchAll(INLINE))) {
    const token = match[0];
    const index = match.index ?? 0;
    if (index > last) out.push(text.slice(last, index));
    const key = `${keyPrefix}-${n++}`;
    if (token.startsWith("**")) {
      out.push(<strong key={key}>{renderInline(token.slice(2, -2), key)}</strong>);
    } else if (token.startsWith("`")) {
      out.push(<code key={key}>{token.slice(1, -1)}</code>);
    } else if (token.startsWith("[")) {
      const m = token.match(/^\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)$/);
      out.push(
        m ? (
          <a key={key} href={m[2]} target="_blank" rel="noreferrer">
            {m[1]}
          </a>
        ) : (
          token
        )
      );
    } else if (token.startsWith("http")) {
      const trimmed = token.replace(/[.,;:!?]+$/, "");
      out.push(
        <a key={key} href={trimmed} target="_blank" rel="noreferrer">
          {trimmed}
        </a>
      );
      if (trimmed.length < token.length) out.push(token.slice(trimmed.length));
    } else {
      out.push(<em key={key}>{token.slice(1, -1)}</em>);
    }
    last = index + token.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

const Markdown: React.FC<{ text: string }> = ({ text }) => {
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  const blocks: React.ReactNode[] = [];
  let i = 0;
  let k = 0;

  while (i < lines.length) {
    const line = lines[i];

    if (!line.trim()) {
      i++;
      continue;
    }

    if (line.trim().startsWith("```")) {
      const code: string[] = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith("```")) code.push(lines[i++]);
      i++;
      blocks.push(
        <pre key={k++}>
          <code>{code.join("\n")}</code>
        </pre>
      );
      continue;
    }

    const heading = line.match(/^(#{1,4})\s+(.*)$/);
    if (heading) {
      const level = Math.min(heading[1].length, 4);
      const Tag = `h${level}` as "h1" | "h2" | "h3" | "h4";
      blocks.push(<Tag key={k++}>{renderInline(heading[2], `h${k}`)}</Tag>);
      i++;
      continue;
    }

    if (/^\s*([-*_])\1{2,}\s*$/.test(line)) {
      blocks.push(<hr key={k++} />);
      i++;
      continue;
    }

    if (/^\s*>\s?/.test(line)) {
      const quote: string[] = [];
      while (i < lines.length && /^\s*>\s?/.test(lines[i])) quote.push(lines[i++].replace(/^\s*>\s?/, ""));
      blocks.push(<blockquote key={k++}>{renderInline(quote.join(" "), `q${k}`)}</blockquote>);
      continue;
    }

    const ul = /^\s*[-*•]\s+/;
    const ol = /^\s*\d+[.)]\s+/;
    if (ul.test(line) || ol.test(line)) {
      const ordered = ol.test(line);
      const re = ordered ? ol : ul;
      const items: string[] = [];
      while (i < lines.length && (re.test(lines[i]) || (lines[i].startsWith("  ") && lines[i].trim() && items.length))) {
        if (re.test(lines[i])) items.push(lines[i].replace(re, ""));
        else items[items.length - 1] += " " + lines[i].trim();
        i++;
      }
      const Tag = ordered ? "ol" : "ul";
      const listKey = k++;
      blocks.push(
        <Tag key={listKey}>
          {items.map((item, idx) => (
            <li key={idx}>{renderInline(item, `l${listKey}-${idx}`)}</li>
          ))}
        </Tag>
      );
      continue;
    }

    const para: string[] = [];
    while (
      i < lines.length &&
      lines[i].trim() &&
      !/^(#{1,4})\s+/.test(lines[i]) &&
      !ul.test(lines[i]) &&
      !ol.test(lines[i]) &&
      !lines[i].trim().startsWith("```") &&
      !/^\s*>\s?/.test(lines[i])
    ) {
      para.push(lines[i++]);
    }
    blocks.push(<p key={k++}>{renderInline(para.join(" "), `p${k}`)}</p>);
  }

  return <div className="prose-forge">{blocks}</div>;
};

export default Markdown;
