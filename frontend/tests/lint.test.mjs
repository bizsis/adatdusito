import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";
import { ESLint } from "eslint";
import { parser } from "typescript-eslint";

const eslint = new ESLint();

test("hook dependencies, hook ordering and baseline rules remain blocking", async () => {
  const [result] = await eslint.lintText(
    `
    import {useEffect, useState} from 'react';
    export function Example({enabled, value}: {enabled: boolean; value: string}) {
      const unused = 1;
      if (enabled) useState('');
      useEffect(() => { console.log(value); }, []);
      try {} catch {}
      return null;
    }
  `,
    { filePath: "src/lint-fixture.tsx" },
  );
  const rules = new Set(
    result.messages.filter((m) => m.severity === 2).map((m) => m.ruleId),
  );
  for (const rule of [
    "react-hooks/rules-of-hooks",
    "react-hooks/exhaustive-deps",
    "@typescript-eslint/no-unused-vars",
    "no-empty",
  ])
    assert.ok(rules.has(rule), `${rule} must be an error`);
  assert.equal(result.warningCount, 0);
});

test("stable callbacks and complete effect dependencies pass", async () => {
  const [result] = await eslint.lintText(
    `
    import {useCallback, useEffect, useState} from 'react';
    export function Example({value}: {value: string}) {
      const [data, setData] = useState('');
      const load = useCallback(() => setData(value), [value]);
      useEffect(() => { load(); }, [load]);
      return data;
    }
  `,
    { filePath: "src/lint-fixture.tsx" },
  );
  assert.deepEqual(result.messages, []);
});

test("scoped minimatch security override supports the parser project service", async () => {
  const root = await mkdtemp(path.join(tmpdir(), "frontend-lint-"));
  try {
    await writeFile(
      path.join(root, "tsconfig.json"),
      JSON.stringify({ include: ["src/**/*.ts"] }),
    );
    const result = parser.parseForESLint("export const value: number = 1;", {
      filePath: path.join(root, "fixture.ts"),
      tsconfigRootDir: root,
      projectService: { allowDefaultProject: ["fixture.ts"] },
      loc: true,
      range: true,
    });
    assert.ok(result.services.program);
    assert.equal(result.ast.body[0].type, "ExportNamedDeclaration");
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
