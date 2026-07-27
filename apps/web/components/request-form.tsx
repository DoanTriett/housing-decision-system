"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@clerk/nextjs";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { toast } from "sonner";

import { ApiError, submitRequest } from "@/lib/api-client";
import {
  housingRequestSchema,
  type HousingRequestFormValues,
} from "@/lib/validations";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Slider } from "@/components/ui/slider";
import { Textarea } from "@/components/ui/textarea";

export function RequestForm() {
  const router = useRouter();
  const { getToken } = useAuth();
  const [submitting, setSubmitting] = useState(false);

  const form = useForm<HousingRequestFormValues>({
    resolver: zodResolver(housingRequestSchema),
    defaultValues: {
      budget_max: 1200,
      anchor_address: "",
      max_commute_minutes: undefined,
      requires_laundry: false,
      requires_pet_friendly: false,
      free_text: undefined,
    },
    mode: "onSubmit",
  });

  const freeText = form.watch("free_text") ?? "";
  const budget = form.watch("budget_max");

  async function onSubmit(values: HousingRequestFormValues) {
    setSubmitting(true);
    try {
      const payload = {
        budget_max: values.budget_max,
        anchor_address: values.anchor_address,
        max_commute_minutes: values.max_commute_minutes ?? null,
        requires_laundry: values.requires_laundry,
        requires_pet_friendly: values.requires_pet_friendly,
        free_text: values.free_text ?? null,
      };
      const { request_id } = await submitRequest(payload, () => getToken());
      toast.success("Request submitted", {
        description: `Tracking ID ${request_id}`,
      });
      router.push(`/request/${request_id}`);
    } catch (err) {
      if (err instanceof ApiError) {
        toast.error(`Request failed (${err.status})`, {
          description: err.detail,
        });
      } else if (err instanceof Error) {
        toast.error("Request failed", { description: err.message });
      } else {
        toast.error("Request failed", {
          description: "Unexpected error — see console for details.",
        });
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Form {...form}>
      <form
        onSubmit={form.handleSubmit(onSubmit)}
        className="mx-auto flex w-full max-w-xl flex-col gap-6"
        noValidate
      >
        <FormField
          control={form.control}
          name="budget_max"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Monthly budget (USD)</FormLabel>
              <FormControl>
                <Input
                  type="number"
                  inputMode="decimal"
                  min={1}
                  max={99999}
                  step={50}
                  {...field}
                  value={field.value ?? ""}
                  onChange={(event) => {
                    const raw = event.target.value;
                    field.onChange(raw === "" ? undefined : Number(raw));
                  }}
                />
              </FormControl>
              <div className="pt-2">
                <Slider
                  min={200}
                  max={5000}
                  step={50}
                  value={[
                    typeof budget === "number" && Number.isFinite(budget)
                      ? Math.min(5000, Math.max(200, budget))
                      : 1200,
                  ]}
                  onValueChange={(value) => {
                    const next = Array.isArray(value) ? value[0] : value;
                    field.onChange(next);
                  }}
                />
              </div>
              <FormDescription>
                Must be greater than $0 and less than $100,000.
              </FormDescription>
              <FormMessage />
            </FormItem>
          )}
        />

        <FormField
          control={form.control}
          name="anchor_address"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Anchor address</FormLabel>
              <FormControl>
                <Input
                  placeholder="e.g., University of Texas at Austin, Austin, TX"
                  {...field}
                />
              </FormControl>
              <FormDescription>
                Commute times are measured from this location.
              </FormDescription>
              <FormMessage />
            </FormItem>
          )}
        />

        <FormField
          control={form.control}
          name="max_commute_minutes"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Max commute (minutes)</FormLabel>
              <FormControl>
                <Input
                  type="number"
                  inputMode="numeric"
                  min={1}
                  max={180}
                  placeholder="Optional — e.g. 20"
                  name={field.name}
                  ref={field.ref}
                  onBlur={field.onBlur}
                  value={field.value ?? ""}
                  onChange={(event) => {
                    const raw = event.target.value;
                    field.onChange(raw === "" ? undefined : Number(raw));
                  }}
                />
              </FormControl>
              <FormDescription>
                Optional. If set, must be between 1 and 180 minutes.
              </FormDescription>
              <FormMessage />
            </FormItem>
          )}
        />

        <div className="grid gap-4 sm:grid-cols-2">
          <FormField
            control={form.control}
            name="requires_laundry"
            render={({ field }) => (
              <FormItem className="flex flex-row items-start gap-3 space-y-0 rounded-lg border border-border/70 p-3">
                <FormControl>
                  <Checkbox
                    checked={field.value}
                    onCheckedChange={(checked) =>
                      field.onChange(checked === true)
                    }
                  />
                </FormControl>
                <div className="space-y-1 leading-none">
                  <FormLabel>Requires laundry</FormLabel>
                  <FormDescription>In-unit or on-site laundry.</FormDescription>
                </div>
              </FormItem>
            )}
          />

          <FormField
            control={form.control}
            name="requires_pet_friendly"
            render={({ field }) => (
              <FormItem className="flex flex-row items-start gap-3 space-y-0 rounded-lg border border-border/70 p-3">
                <FormControl>
                  <Checkbox
                    checked={field.value}
                    onCheckedChange={(checked) =>
                      field.onChange(checked === true)
                    }
                  />
                </FormControl>
                <div className="space-y-1 leading-none">
                  <FormLabel>Requires pet-friendly</FormLabel>
                  <FormDescription>Allows cats or dogs.</FormDescription>
                </div>
              </FormItem>
            )}
          />
        </div>

        <FormField
          control={form.control}
          name="free_text"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Other preferences</FormLabel>
              <FormControl>
                <Textarea
                  rows={4}
                  maxLength={500}
                  placeholder="Any other preferences? (e.g., quiet area, concerned about safety)"
                  {...field}
                  value={field.value ?? ""}
                />
              </FormControl>
              <div className="flex items-center justify-between gap-2">
                <FormDescription>Optional. Max 500 characters.</FormDescription>
                <span className="text-xs text-muted-foreground tabular-nums">
                  {String(freeText).length}/500
                </span>
              </div>
              <FormMessage />
            </FormItem>
          )}
        />

        <Button type="submit" size="lg" disabled={submitting} className="w-full">
          {submitting ? "Submitting…" : "Submit housing request"}
        </Button>
      </form>
    </Form>
  );
}
