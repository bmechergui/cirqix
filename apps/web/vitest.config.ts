import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    poolOptions: { threads: { maxThreads: 1, minThreads: 1 } },
    setupFiles: ['./src/test/setup.ts'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'lcov'],
      thresholds: { lines: 80, functions: 80, branches: 80 },
      include: [
        'src/app/api/**/*.ts',
        'src/shared/store/**/*.ts',
        'src/features/auth/ui/**/*.tsx',
      ],
    },
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
      '@cirqix/types': path.resolve(__dirname, '../../packages/types/src/index.ts'),
      '@cirqix/agents': path.resolve(__dirname, '../../packages/agents/src/index.ts'),
    },
  },
});
