import {defineConfig} from 'vite';
import react from '@vitejs/plugin-react';

// Local-only previews; fail on conflict instead of taking another process's port.
// `npm run dev -- --port 18911` overrides the port without changing the host.
export default defineConfig({
  plugins: [react()],
  server: {host: '127.0.0.1', port: 18910, strictPort: true},
  preview: {host: '127.0.0.1', port: 18910, strictPort: true},
});
