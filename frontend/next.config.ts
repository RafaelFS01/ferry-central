import type { NextConfig } from 'next';

// Atrás do Nginx central, /api/* nunca chega ao Next.js.
// O rewrite cobre a execução isolada (npm run dev) apontando direto para a API Python.
const centralApiUrl = process.env.CENTRAL_API_URL ?? 'http://localhost:8000';

// Bind mounts do Docker no Windows/macOS não propagam eventos de arquivo: o
// container de dev define NEXT_WATCH_POLL_MS para o Turbopack usar polling.
const pollIntervalMs = Number(process.env.NEXT_WATCH_POLL_MS) || undefined;

const nextConfig: NextConfig = {
  output: 'standalone',
  watchOptions: { pollIntervalMs },
  poweredByHeader: false,
  reactStrictMode: true,
  async rewrites() {
    return [{ source: '/api/:path*', destination: `${centralApiUrl}/api/:path*` }];
  },
};

export default nextConfig;
