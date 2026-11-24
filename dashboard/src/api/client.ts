import createClient, { type Middleware } from "openapi-fetch";
import type { paths } from "./schema";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

/** Turn FastAPI error bodies ({detail}) into thrown ApiErrors so React Query sees them. */
const throwOnError: Middleware = {
  async onResponse({ response }) {
    if (response.ok) return response;
    const body = (await response.clone().json().catch(() => ({}))) as { detail?: unknown };
    const detail = typeof body.detail === "string" ? body.detail : `HTTP ${response.status}`;
    throw new ApiError(response.status, detail);
  },
};

export const api = createClient<paths>({
  baseUrl: globalThis.location?.origin ?? "",
  // resolve fetch per call (not at import) so tests and polyfills can swap it
  fetch: (req) => globalThis.fetch(req),
});
api.use(throwOnError);

/** Unwrap openapi-fetch results, narrowing untyped dict responses to our domain types. */
export async function call<T>(p: Promise<{ data?: unknown }>): Promise<T> {
  const { data } = await p;
  return data as T;
}
