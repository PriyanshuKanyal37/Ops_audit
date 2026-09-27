import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Pin the project root: a stray pnpm-workspace.yaml in the user's home folder
  // otherwise makes Next.js guess the wrong root.
  turbopack: { root: __dirname },
};

export default nextConfig;
