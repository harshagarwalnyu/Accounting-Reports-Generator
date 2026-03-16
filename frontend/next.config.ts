import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",       // smaller Docker image if containerized
  compress: true,             // gzip responses
  poweredByHeader: false,     // remove X-Powered-By header
};

export default nextConfig;
