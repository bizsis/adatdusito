export type Topic = {
  id: string;
  title: string;
  description: string;
  order: number;
};
export type Block =
  | { type: "heading" | "paragraph"; text: string }
  | { type: "list" | "steps"; items: string[] }
  | { type: "note" | "warning"; title: string; text: string }
  | { type: "link"; article: string; text: string }
  | { type: "table"; caption: string; headers: string[]; rows: string[][] }
  | { type: "image"; src: string; alt: string; caption?: string };
export type Article = {
  id: string;
  topic: string;
  title: string;
  summary: string;
  order: number;
  blocks: Block[];
  related: string[];
};
export type HelpRoute = {
  article: string | null;
  query: string;
  topic: string;
};
const slug = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
export function isHelpHash(hash: string): boolean {
  return /^#\/segedlet(?:[/?]|$)/.test(hash);
}
export function helpHref(
  article: string | null = null,
  query = "",
  topic = "",
): string {
  const params = new URLSearchParams();
  if (query) params.set("q", query.slice(0, 256));
  if (topic) params.set("tema", topic);
  return `#/segedlet${article && slug.test(article) ? `/${article}` : ""}${params.size ? `?${params}` : ""}`;
}
export function readHelpRoute(hash: string): HelpRoute {
  const [path, search = ""] = hash.replace(/^#/, "").split("?", 2);
  let article: string | null = null;
  if (path !== "/segedlet" && path !== "/segedlet/") {
    try {
      article = decodeURIComponent(path.slice("/segedlet/".length));
    } catch {
      article = "invalid-url";
    }
    if (!slug.test(article)) article = "invalid-url";
  }
  const params = new URLSearchParams(search);
  return {
    article,
    query: (params.get("q") || "").slice(0, 256),
    topic: params.get("tema") || "",
  };
}
export function normalize(text: string): string {
  return text
    .normalize("NFD")
    .replace(/\p{M}/gu, "")
    .toLocaleLowerCase("hu")
    .replace(/\s+/g, " ")
    .trim();
}
export function articleText(article: Article): string {
  return normalize(
    [
      article.title,
      article.summary,
      ...article.blocks.flatMap((b) => {
        if (b.type === "table")
          return [b.caption, ...b.headers, ...b.rows.flat()];
        if ("items" in b) return b.items;
        if (b.type === "image") return [b.alt, b.caption || ""];
        if (b.type === "note" || b.type === "warning") return [b.title, b.text];
        return [b.text];
      }),
    ].join(" "),
  );
}
export function searchArticles(
  articles: Article[],
  query: string,
  topic = "",
): Article[] {
  const words = normalize(query).split(" ").filter(Boolean);
  return articles
    .filter(
      (a) =>
        (!topic || a.topic === topic) &&
        words.every((w) => articleText(a).includes(w)),
    )
    .sort((a, b) => a.order - b.order || a.title.localeCompare(b.title, "hu"));
}
export function safeImage(src: string): boolean {
  return /^\/help\/images\/[a-z0-9]+(?:-[a-z0-9]+)*\.(?:png|webp|jpg|jpeg)$/.test(
    src,
  );
}
