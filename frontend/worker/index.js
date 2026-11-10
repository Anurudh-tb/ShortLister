// Serves the Angular app from static assets and forwards /api/* to the backend.
// BACKEND_URL is the public tunnel URL of the FastAPI server (set in wrangler.jsonc "vars").
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname.startsWith("/api/")) {
      if (!env.BACKEND_URL) {
        return Response.json({ detail: "Backend is not configured" }, { status: 503 });
      }
      const target = new URL(url.pathname + url.search, env.BACKEND_URL);
      try {
        return await fetch(new Request(target, request));
      } catch {
        return Response.json({ detail: "Backend is offline" }, { status: 502 });
      }
    }
    return env.ASSETS.fetch(request);
  },
};
