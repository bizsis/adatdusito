import assert from "node:assert/strict";
import {
  readFile,
  readdir,
  mkdtemp,
  writeFile,
  rm,
  access,
} from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import test from "node:test";
import ts from "typescript";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

const temp = await mkdtemp(path.resolve("tests/.help-modules-"));
for (const file of ["model.ts", "ArticleBody.tsx"]) {
  const source = (await readFile(`src/support/${file}`, "utf8")).replace(
    '"./model"',
    '"./model.mjs"',
  );
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.ESNext,
      target: ts.ScriptTarget.ES2022,
      jsx: ts.JsxEmit.ReactJSX,
    },
  });
  await writeFile(path.join(temp, file.replace(/\.tsx?$/, ".mjs")), outputText);
}
const model = await import(pathToFileURL(path.join(temp, "model.mjs")));
const { ArticleBody } = await import(
  pathToFileURL(path.join(temp, "ArticleBody.mjs"))
);
test.after(() => rm(temp, { recursive: true, force: true }));
const topics = JSON.parse(await readFile("src/support/topics.json", "utf8"));
const files = await readdir("src/support/articles");
const articles = await Promise.all(
  files
    .filter((f) => f.endsWith(".json"))
    .map(async (f) =>
      JSON.parse(await readFile(`src/support/articles/${f}`, "utf8")),
    ),
);

test("title and full body search are accent-insensitive and combine terms", () => {
  assert.ok(
    model
      .searchArticles(articles, "xlsx")
      .some((a) => a.id === "csv-xlsx-feltoltes"),
  );
  assert.ok(model.searchArticles(articles, "cp1250").length === 0);
  assert.ok(
    model
      .searchArticles(articles, "fejlec elvalaszto")
      .some((a) => a.id === "csv-xlsx-feltoltes"),
  );
  assert.ok(
    model
      .searchArticles(articles, "zárOLás")
      .some((a) => a.id === "kezi-parameterek"),
  );
  assert.deepEqual(
    model.searchArticles(articles, "semmikeppen-nem-letezo-123"),
    [],
  );
});
test("topic filtering preserves authored article order", () => {
  const found = model.searchArticles(articles, "", "import");
  assert.equal(
    found.length,
    articles.filter((a) => a.topic === "import").length,
  );
  assert.ok(found.every((a) => a.topic === "import"));
  assert.deepEqual(
    found.map((a) => a.order),
    [...found.map((a) => a.order)].sort((a, b) => a - b),
  );
});
test("article deep links, query context and malformed links are safe", () => {
  const href = model.helpHref(
    "kezi-parameterek",
    "kézi & zárolás",
    "parameterek",
  );
  assert.deepEqual(model.readHelpRoute(href), {
    article: "kezi-parameterek",
    query: "kézi & zárolás",
    topic: "parameterek",
  });
  assert.equal(model.readHelpRoute("#/segedlet/%E0%A4").article, "invalid-url");
  assert.equal(
    model.readHelpRoute("#/segedlet/nem-letezik").article,
    "nem-letezik",
  );
  assert.equal(model.helpHref("javascript:alert(1)"), "#/segedlet");
  assert.equal(model.isHelpHash("#invite=abc"), false);
  assert.equal(model.isHelpHash("#security"), false);
  assert.equal(model.isHelpHash("#/segedlet/kezi-parameterek"), true);
});
test("repository content has eight topics, unique URLs and valid internal links", () => {
  assert.equal(topics.length, 8);
  assert.equal(new Set(topics.map((t) => t.id)).size, 8);
  assert.ok(articles.length >= 12);
  const ids = new Set(articles.map((a) => a.id));
  assert.equal(ids.size, articles.length);
  for (const a of articles) {
    assert.match(a.id, /^[a-z0-9]+(?:-[a-z0-9]+)*$/);
    assert.ok(topics.some((t) => t.id === a.topic));
    assert.ok(
      a.title && a.summary && a.blocks.length && Number.isInteger(a.order),
    );
    for (const block of a.blocks) {
      assert.ok(
        [
          "heading",
          "paragraph",
          "steps",
          "list",
          "note",
          "warning",
          "link",
          "image",
        ].includes(block.type),
      );
      if ("items" in block)
        assert.ok(
          Array.isArray(block.items) &&
            block.items.every((item) => typeof item === "string"),
        );
      if ("text" in block) assert.equal(typeof block.text, "string");
    }
    for (const id of [
      ...a.related,
      ...a.blocks.filter((b) => b.type === "link").map((b) => b.article),
    ])
      assert.ok(ids.has(id), `${a.id}: missing ${id}`);
  }
});
test("all authored screenshot files exist and have descriptions", async () => {
  let count = 0;
  for (const a of articles)
    for (const b of a.blocks.filter((b) => b.type === "image")) {
      assert.ok(model.safeImage(b.src));
      assert.ok(b.alt.trim());
      await access(`public${b.src}`);
      count++;
    }
  assert.ok(count >= 8);
});
test("structured renderer escapes HTML and prevents script links / remote images", () => {
  const html = renderToStaticMarkup(
    React.createElement(ArticleBody, {
      blocks: [
        {
          type: "paragraph",
          text: '<script>alert("xss")</script><img src=x onerror=alert(1)>',
        },
        {
          type: "link",
          article: "javascript:alert(1)",
          text: "<b>Nem HTML</b>",
        },
        {
          type: "image",
          src: "https://tracker.invalid/x.png",
          alt: "external",
        },
        { type: "image", src: "javascript:alert(1)", alt: "script" },
      ],
    }),
  );
  assert.ok(html.includes("&lt;script&gt;"));
  assert.ok(!html.includes("<script"));
  assert.ok(!html.includes("<img"));
  assert.ok(!html.includes('href="javascript:'));
  assert.ok(!html.includes("tracker.invalid"));
  assert.ok(html.includes("&lt;b&gt;Nem HTML&lt;/b&gt;"));
});
test("renderer supports ordered steps, notes, captions and multiple pictures", () => {
  const html = renderToStaticMarkup(
    React.createElement(ArticleBody, {
      blocks: [
        { type: "steps", items: ["Első", "Második"] },
        { type: "warning", title: "Figyelem", text: "Ellenőrizd!" },
        {
          type: "image",
          src: "/help/images/oszlopok.png",
          alt: "Oszlopok",
          caption: "Képaláírás",
        },
        {
          type: "image",
          src: "/help/images/beszallito.png",
          alt: "Beszállító",
        },
      ],
    }),
  );
  assert.ok(html.includes("<ol>"));
  assert.ok(html.includes('role="note"'));
  assert.ok(html.includes("<figcaption>Képaláírás</figcaption>"));
  assert.equal((html.match(/<figure>/g) || []).length, 2);
});
