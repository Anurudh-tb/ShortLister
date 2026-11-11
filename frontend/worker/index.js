// Serves the Angular app from static assets and forwards /api/* to the backend.
// BACKEND is a Workers VPC binding to the local FastAPI server, reached through the named
// Cloudflare Tunnel "shortlister-backend" (see wrangler.jsonc). The backend has no public URL.
const ORIGIN = "http://127.0.0.1:8000";

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname.startsWith("/api/")) {
      if (!env.BACKEND) {
        return Response.json({ detail: "Backend is not configured" }, { status: 503 });
      }
      try {
        return await env.BACKEND.fetch(new Request(ORIGIN + url.pathname + url.search, request));
      } catch {
        return Response.json({ detail: "Backend is offline" }, { status: 502 });
      }
    }
    return env.ASSETS.fetch(request);
  },
};
