// The benchmark index, built from the run records by the Vite plugin in vite.config.ts.
// The whole index as one module: tests only (the app fetches it in parts).
declare module "virtual:pii-guard/benchmarks-index" {
  const index: unknown;
  export default index;
}

// Where each part of the split index is (a BenchmarkManifest, src/api/benchmarksSplit.ts).
declare module "virtual:pii-guard/benchmarks-manifest" {
  const manifest: unknown;
  export default manifest;
}
