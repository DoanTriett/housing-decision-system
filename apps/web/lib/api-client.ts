import { API_BASE_URL } from "@/lib/config";
import { ApiError, formatDetail } from "@/lib/api-error";
import type {
  CreateHousingRequestResponse,
  ObservabilitySummary,
  RequestListResponse,
  RequestResult,
  UserHousingRequestPayload,
} from "@/lib/types";

export { ApiError } from "@/lib/api-error";

export type GetToken = () => Promise<string | null>;

async function parseError(response: Response): Promise<ApiError> {
  let detail = response.statusText || "Request failed";
  try {
    const payload: unknown = await response.json();
    detail = formatDetail(payload);
  } catch {
    try {
      detail = await response.text();
    } catch {
      /* keep statusText */
    }
  }

  if (response.status === 401) {
    detail =
      `Backend rejected the Clerk token (401): ${detail}. ` +
      "This usually means JWKS/issuer mismatch between the frontend Clerk app " +
      "and apps/api CLERK_JWKS_URL / CLERK_ISSUER — do not fall back to local HS256 tokens.";
  }

  return new ApiError(response.status, detail);
}

async function apiFetch<T>(
  path: string,
  getToken: GetToken,
  init?: RequestInit
): Promise<T> {
  const token = await getToken();
  if (!token) {
    throw new ApiError(
      401,
      "No Clerk session token available. Sign in and try again."
    );
  }

  const headers = new Headers(init?.headers);
  headers.set("Authorization", `Bearer ${token}`);
  if (init?.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers,
  });

  if (!response.ok) {
    throw await parseError(response);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

export async function submitRequest(
  payload: UserHousingRequestPayload,
  getToken: GetToken
): Promise<CreateHousingRequestResponse> {
  return apiFetch<CreateHousingRequestResponse>("/api/requests", getToken, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getRequest(
  id: string,
  getToken: GetToken
): Promise<RequestResult> {
  return apiFetch<RequestResult>(`/api/requests/${id}`, getToken);
}

export async function listRequests(
  getToken: GetToken,
  limit = 20,
  offset = 0
): Promise<RequestListResponse> {
  const qs = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  });
  return apiFetch<RequestListResponse>(
    `/api/requests?${qs.toString()}`,
    getToken
  );
}

export async function getObservabilitySummary(
  getToken: GetToken
): Promise<ObservabilitySummary> {
  return apiFetch<ObservabilitySummary>(
    "/api/admin/observability/summary",
    getToken
  );
}
