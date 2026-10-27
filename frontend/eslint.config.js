/**
 * ESLint flat config for the ChatAssist frontend.
 *
 * What it does: lints the frontend with the recommended core JS rules (spread into `rules`,
 * not into the config object, or they get overwritten) plus the React
 * and react-hooks rules (a missing useEffect dependency is a real bug).
 * Where it fits: `npm run lint`, and the frontend CI job.
 * Notes: eslint-plugin-react-hooks is pinned to 5.x on purpose — 7.x adds
 * React Compiler rules whose fixes would change behavior.
 */

import js from "@eslint/js";
import globals from "globals";
import react from "eslint-plugin-react";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";

export default [
  { ignores: ["dist/**", "node_modules/**", "coverage/**"] },

  {
    files: ["**/*.{js,jsx}"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "module",
      globals: { ...globals.browser, ...globals.es2021 },
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
    settings: { react: { version: "19.2" } },
    plugins: {
      react,
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      // core recommended წესები აქ უნდა იყოს: `...js.configs.recommended` ობიექტის
      // დონეზე გავრცელება მათ `rules`-ის გასაღებით ანაცვლებდა (no-undef და სხვა გამორთული იყო)
      ...js.configs.recommended.rules,
      ...react.configs.recommended.rules,
      ...reactHooks.configs.recommended.rules,
      // ახალი JSX transform — React-ის იმპორტი აღარ სჭირდება
      "react/react-in-jsx-scope": "off",
      "react/jsx-uses-react": "off",
      // PropTypes-ს არ ვიყენებთ
      "react/prop-types": "off",
      "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],
      // ignoreRestSiblings — `const { a, ...rest } = obj` ველის ჩამოშორების იდიომაა
      "no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_", ignoreRestSiblings: true },
      ],
    },
  },

  {
    // Node-ის კონფიგები — ბრაუზერის გლობალები აქ არ არსებობს
    files: ["*.config.js", "vitest.setup.js"],
    languageOptions: { globals: { ...globals.node } },
  },

  {
    files: ["**/*.test.{js,jsx}", "vitest.setup.js"],
    languageOptions: { globals: { ...globals.node, ...globals.vitest } },
  },
];
