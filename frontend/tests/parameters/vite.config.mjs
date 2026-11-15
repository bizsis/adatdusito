import { fileURLToPath } from "node:url";
const root = fileURLToPath(new URL("../../", import.meta.url));
if (!process.env.CATEGORY03_TEST_DIST)
  throw new Error("CATEGORY03_TEST_DIST is required");
export default {
  root,
  build: {
    outDir: process.env.CATEGORY03_TEST_DIST,
    emptyOutDir: true,
    rollupOptions: { input: `${root}/tests/parameters/index.html` },
  },
};
