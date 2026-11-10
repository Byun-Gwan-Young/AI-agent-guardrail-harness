import { createServer } from "vite";

// Run Vite in the test coordinator, so Windows needs no taskkill process-tree cleanup.
export default async function setup() {
  const server = await createServer({
    server: { host: "127.0.0.1", port: 5173, strictPort: true },
  });
  await server.listen();
  return async () => {
    await server.close();
  };
}
