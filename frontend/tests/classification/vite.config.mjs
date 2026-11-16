// Test-only entry: never use this configuration for the production image.
import { fileURLToPath } from "node:url";
const root = fileURLToPath(new URL("../../", import.meta.url));
if (!process.env.CATEGORY02_TEST_DIST)
  throw new Error("CATEGORY02_TEST_DIST is required");
export default {
  root,
  build: {
    outDir: process.env.CATEGORY02_TEST_DIST,
    emptyOutDir: true,
    rollupOptions: { input: `${root}/tests/classification/index.html` },
  },
};
