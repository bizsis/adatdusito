// CI-only ESLint baseline for frontend/src (advisory, see docs/development/CI.md).
// Intentionally minimal: recommended JS + TypeScript rules and the React hooks
// rules. Move to frontend/eslint.config.js once the frontend owner adds ESLint
// to frontend/package.json.
import js from "@eslint/js";
import tseslint from "typescript-eslint";
import reactHooks from "eslint-plugin-react-hooks";

export default tseslint.config(
  { ignores: ["frontend/dist/**", "frontend/node_modules/**"] },
  {
    files: ["frontend/src/**/*.{ts,tsx}"],
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    plugins: { "react-hooks": reactHooks },
    rules: { ...reactHooks.configs.recommended.rules },
  },
);
