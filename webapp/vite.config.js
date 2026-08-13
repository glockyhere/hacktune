import { defineConfig } from "vite";

// Production build for the web client.
//
// What gets bundled:  index.html -> style.css -> app.js -> (lazy) transport.js
//   transport.js is the only file with bare specifiers (ya-webadb). It lands in
//   its own chunk because app.js imports it dynamically, so the page still
//   renders if ADB support fails to load.
//
// What stays verbatim (public/, copied unhashed so paths are stable):
//   config.js        the seller edits this AFTER deploy — card numbers, API URL,
//                    price. It must never be hashed into a bundle.
//   cat.json         fetched at runtime by the lottie mount
//   vendor/          self-hosted fonts + lottie runtime, with their licences
//
// What is deliberately NOT built: demo.html / demo.js (a simulated device for
// design work) and _zoom.html. Only index.html is an entry, so they cannot
// reach production.
export default defineConfig({
  base: "/",
  build: {
    outDir: "dist",
    emptyOutDir: true,
    target: "es2022",          // WebUSB/Chromium-only anyway; keeps output small
    sourcemap: false,          // nothing secret in here, but no need to ship it
    chunkSizeWarningLimit: 900,
  },
  server: { port: 5173 },
  preview: { port: 4173 },
});
