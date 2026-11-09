import path from 'path';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig, type Plugin } from 'vite';
import type { IncomingMessage, ServerResponse } from 'node:http';

import runtimeErrorOverlay from '@replit/vite-plugin-runtime-error-modal';

const rawPort = process.env.PORT;

if (!rawPort) {
  throw new Error(
    'PORT environment variable is required but was not provided.',
  );
}

const port = Number(rawPort);

if (Number.isNaN(port) || port <= 0) {
  throw new Error(`Invalid PORT value: "${rawPort}"`);
}

const basePath = process.env.BASE_PATH;

if (!basePath) {
  throw new Error(
    'BASE_PATH environment variable is required but was not provided.',
  );
}

// This must run before Vite's base-path guard, which otherwise returns 404
// for the slash-less artifact root selected by the workspace router.
function canonicalAdminRoot(req: IncomingMessage, res: ServerResponse, next: () => void) {
  const url = new URL(req.url ?? '/', 'http://internal.invalid');
  if (url.pathname === basePath!.replace(/\/+$/, '') && ['GET', 'HEAD'].includes(req.method ?? '')) {
    res.writeHead(308, { Location: basePath! + url.search, 'Cache-Control': 'no-store' });
    res.end();
  } else next();
}
const canonicalBase: Plugin = {
  name: 'canonical-admin-root',
  configureServer(server) { server.middlewares.use(canonicalAdminRoot); },
  configurePreviewServer(server) { server.middlewares.use(canonicalAdminRoot); },
};

export default defineConfig({
  base: basePath,
  plugins: [
    canonicalBase,
    react(),
    tailwindcss({ optimize: false }),
    runtimeErrorOverlay(),
    ...(process.env.NODE_ENV !== 'production' &&
    process.env.REPL_ID !== undefined
      ? [
          await import('@replit/vite-plugin-cartographer').then((m) =>
            m.cartographer({
              root: path.resolve(import.meta.dirname, '..'),
            }),
          ),
        ]
      : []),
  ],
  resolve: {
    alias: {
      '@': path.resolve(import.meta.dirname, 'src'),
      '@assets': path.resolve(
        import.meta.dirname,
        '..',
        '..',
        'attached_assets',
      ),
    },
    dedupe: ['react', 'react-dom'],
  },
  root: path.resolve(import.meta.dirname),
  build: {
    outDir: path.resolve(import.meta.dirname, 'dist/public'),
    emptyOutDir: true,
  },
  server: {
    port,
    strictPort: true,
    host: '0.0.0.0',
    allowedHosts: true,
    fs: {
      strict: true,
    },
  },
  preview: {
    port,
    host: '0.0.0.0',
    allowedHosts: true,
  },
});
