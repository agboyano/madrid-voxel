import { defineConfig } from 'vite';
import { versionedData } from './tools/version-data.mjs';

export default defineConfig({
  base: './',
  plugins: [versionedData()],
  worker: { format: 'es' },
  build: { chunkSizeWarningLimit: 2000 },
});
