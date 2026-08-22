// Extension .cjs : le paquet declare `"type": "module"`, donc un .js serait
// charge comme ESM et `require` y serait indefini.
const tsParser = require('@typescript-eslint/parser');
const tsPlugin = require('@typescript-eslint/eslint-plugin');

/** @type {import("eslint").Linter.Config[]} */
module.exports = [
  {
    files: ['**/*.ts'],
    ignores: ['dist/**'],
    languageOptions: {
      parser: tsParser,
      parserOptions: { project: './tsconfig.json' },
    },
    plugins: { '@typescript-eslint': tsPlugin },
    rules: {
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
      '@typescript-eslint/no-explicit-any': 'error',
      // Le worker n'a pas de console : toute sortie passe par le logger Pino,
      // seul moyen d'obtenir des lignes structurées exploitables en production.
      'no-console': 'error',
    },
  },
];
