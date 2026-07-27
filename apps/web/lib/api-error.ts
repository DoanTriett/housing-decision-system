export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

export function formatDetail(payload: unknown): string {
  if (payload == null) {
    return "Request failed";
  }
  if (typeof payload === "string") {
    return payload;
  }
  if (typeof payload !== "object") {
    return String(payload);
  }
  const obj = payload as Record<string, unknown>;
  if (typeof obj.detail === "string") {
    return obj.detail;
  }
  if (Array.isArray(obj.detail)) {
    return obj.detail
      .map((item) => {
        if (item && typeof item === "object" && "msg" in item) {
          const loc = Array.isArray((item as { loc?: unknown }).loc)
            ? (item as { loc: unknown[] }).loc.join(".")
            : "";
          return loc
            ? `${loc}: ${(item as { msg: string }).msg}`
            : (item as { msg: string }).msg;
        }
        return JSON.stringify(item);
      })
      .join("; ");
  }
  if (typeof obj.error === "string") {
    return obj.error;
  }
  return JSON.stringify(payload);
}
