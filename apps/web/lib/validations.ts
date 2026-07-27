import { z } from "zod";

/** Mirrors Day 9 backend validation in apps/api/src/api/schemas.py */
const INJECTION_PATTERNS = [
  "ignore previous instructions",
  "system prompt",
] as const;

export const housingRequestSchema = z.object({
  budget_max: z.coerce
    .number()
    .gt(0, "Budget must be greater than 0")
    .lt(100_000, "Budget must be less than 100000"),
  anchor_address: z
    .string()
    .trim()
    .min(3, "Address must be at least 3 characters")
    .max(200, "Address must be at most 200 characters"),
  max_commute_minutes: z.preprocess((value) => {
    if (value === "" || value === null || value === undefined) {
      return undefined;
    }
    const n = typeof value === "number" ? value : Number(value);
    return Number.isFinite(n) ? n : value;
  }, z.number().int().min(1).max(180).optional()),
  requires_laundry: z.boolean().default(false),
  requires_pet_friendly: z.boolean().default(false),
  free_text: z.preprocess((value) => {
    if (value === null || value === undefined) {
      return undefined;
    }
    if (typeof value !== "string") {
      return value;
    }
    const trimmed = value.trim();
    return trimmed === "" ? undefined : trimmed;
  }, z
    .string()
    .max(500, "Free text must be at most 500 characters")
    .refine(
      (text) => {
        const lowered = text.toLowerCase();
        return !INJECTION_PATTERNS.some((pattern) => lowered.includes(pattern));
      },
      {
        message:
          "Free text contains disallowed content (basic prompt-injection defense)",
      }
    )
    .optional()),
});

export type HousingRequestFormValues = z.infer<typeof housingRequestSchema>;
