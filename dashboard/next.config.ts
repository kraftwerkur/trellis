import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "export",
  // In production (static export served by FastAPI), API calls go to same origin.
  // In dev, .env.local sets NEXT_PUBLIC_TRELLIS_API_URL=http://localhost:8100
  // Dynamic routes handled client-side
  trailingSlash: true,
};

export default nextConfig;
