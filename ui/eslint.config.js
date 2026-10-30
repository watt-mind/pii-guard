import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist", "node_modules", "coverage"] },
  {
    files: ["**/*.{ts,tsx,js}"],
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    languageOptions: {
      ecmaVersion: 2023,
      globals: { ...globals.browser, ...globals.node },
    },
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "react-refresh/only-export-components": ["error", { allowConstantExport: true }],
      "@typescript-eslint/consistent-type-imports": "error",
      "no-console": ["error", { allow: ["warn", "error"] }],
      "max-depth": ["error", 5],
    },
  },
  {
    files: [
      "src/App.tsx",
      "src/components/EntityTable.tsx",
      "src/components/HighlightedText.tsx",
      "src/components/Legend.tsx",
      "src/components/Placeholder.tsx",
      "src/components/RestoredText.tsx",
      "src/hosted/PublicHeader.tsx",
      "src/lib/entities.ts",
      "src/lib/placeholders.ts",
      "src/projects/ProjectSwitcher.tsx",
      "src/screens/Policy.tsx",
    ],
    rules: {
      complexity: ["error", 10],
      "max-depth": ["error", 3],
    },
  },
  {
    files: ["**/*.test.{ts,tsx}", "src/test/**"],
    rules: { "react-refresh/only-export-components": "off" },
  },
);
