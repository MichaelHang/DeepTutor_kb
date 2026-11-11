import { forwardBackendUpload } from "@/lib/streaming-upload-proxy";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * Reading materials are streamed to FastAPI without being materialized in the
 * Next.js process.
 *
 * A lecture video is far larger than the proxy's request-clone cap, and a
 * cloned body is truncated at that cap: the backend then receives a broken
 * multipart and the browser sees an opaque 500 instead of the size limit it
 * should have been told about. This route is excluded from `proxy.ts` for the
 * same reason the knowledge-base upload route is.
 */
export function GET(request: Request): Promise<Response> {
  return forwardBackendUpload(request);
}

export function POST(request: Request): Promise<Response> {
  return forwardBackendUpload(request);
}
