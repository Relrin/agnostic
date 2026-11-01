// ESLint 9 flat config. Workspace boundaries are enforced with `no-restricted-imports` per
// workspace glob; TypeScript project references enforce the same graph at type-check time.
import js from "@eslint/js";
import jsxA11y from "eslint-plugin-jsx-a11y";
import reactHooks from "eslint-plugin-react-hooks";
import storybook from "eslint-plugin-storybook";
import globals from "globals";
import tseslint from "typescript-eslint";

const noOtherModules = {
  group: ["@agnostic/module-*"],
  message: "Modules never import other modules; navigate with route helpers from @agnostic/core instead.",
};
const noApp = { group: ["@agnostic/web", "@agnostic/web/*"], message: "Nothing imports the app shell." };
const noRadixDirect = {
  group: ["@radix-ui/*", "radix-ui"],
  message: "Use the primitives from @agnostic/ui instead of Radix directly.",
};

export default tseslint.config(
  {
    ignores: [
      "**/node_modules/**",
      "**/.tsbuild/**",
      "**/dist/**",
      "**/storybook-static/**",
      "**/playwright-report/**",
      "**/test-results/**",
      ".yarn/**",
      "packages/api/src/generated/**",
      "packages/api/src/agentos/**",
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.strictTypeChecked,
  ...tseslint.configs.stylisticTypeChecked,
  {
    languageOptions: {
      parserOptions: {
        projectService: { allowDefaultProject: ["*.config.ts", "vitest.setup.ts"] },
        tsconfigRootDir: import.meta.dirname,
      },
      globals: { ...globals.browser },
    },
    plugins: { "react-hooks": reactHooks },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "@typescript-eslint/consistent-type-imports": "error",
      "@typescript-eslint/consistent-type-definitions": ["error", "type"],
      "@typescript-eslint/restrict-template-expressions": ["error", { allowNumber: true }],
      "no-restricted-imports": ["error", { patterns: [noApp, noRadixDirect] }],
    },
  },
  jsxA11y.flatConfigs.recommended,
  {
    files: ["modules/**/*.{ts,tsx}"],
    rules: { "no-restricted-imports": ["error", { patterns: [noApp, noRadixDirect, noOtherModules] }] },
  },
  {
    files: ["packages/**/*.{ts,tsx}"],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          patterns: [
            noApp,
            noOtherModules,
            { group: ["@agnostic/module-*"], message: "Packages never import modules." },
          ],
        },
      ],
    },
  },
  {
    files: ["packages/ui/**/*.{ts,tsx}"],
    rules: {
      "no-restricted-imports": [
        "error",
        { patterns: [{ group: ["@agnostic/*"], message: "@agnostic/ui depends on nothing internal." }] },
      ],
    },
  },
  {
    files: ["**/*.config.{js,ts}", "**/.storybook/*.ts", "scripts/**/*.mjs", "**/e2e/**/*.ts"],
    languageOptions: { globals: { ...globals.node } },
  },
  {
    files: ["**/*.{js,mjs,cjs}"],
    ...tseslint.configs.disableTypeChecked,
  },
  {
    files: ["**/*.cjs"],
    languageOptions: { sourceType: "commonjs", globals: { ...globals.node } },
  },
  ...storybook.configs["flat/recommended"],
);
