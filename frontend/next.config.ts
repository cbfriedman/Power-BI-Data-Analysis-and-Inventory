import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Emits .next/standalone, which the production Dockerfile copies. Without it
  // the runtime image would need the full node_modules tree.
  output: "standalone",
  reactStrictMode: true,
  poweredByHeader: false,
};

export default nextConfig;
