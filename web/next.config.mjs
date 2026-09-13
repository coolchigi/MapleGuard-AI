/** @type {import('next').NextConfig} */
// Vercel: this app is the repo's `web/` directory. Set the project Root Directory to `web`.
const nextConfig = {
  reactStrictMode: true,
  webpack: (config) => {
    // pdfjs-dist references an optional native `canvas` module (server-side rendering only). We only
    // extract text in the browser, so stub it out rather than fail the build resolving it.
    config.resolve.alias = { ...config.resolve.alias, canvas: false };
    return config;
  },
};

export default nextConfig;
