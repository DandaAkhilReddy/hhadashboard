import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Proxy /api/* to the FastAPI backend in dev so we can use relative fetch paths
  async rewrites() {
    const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";
    return [
      { source: "/api/:path*", destination: `${apiBase}/api/:path*` },
      { source: "/health", destination: `${apiBase}/health` },
      { source: "/ready", destination: `${apiBase}/ready` },
    ];
  },
};

export default nextConfig;
