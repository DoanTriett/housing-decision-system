import { RequestForm } from "@/components/request-form";

export default function RequestPage() {
  return (
    <div className="mx-auto max-w-5xl px-4 py-10 sm:px-6">
      <div className="mb-8 max-w-xl">
        <h1 className="font-[family-name:var(--font-display)] text-3xl tracking-tight text-[#0f5444] sm:text-4xl">
          New housing request
        </h1>
        <p className="mt-2 text-muted-foreground">
          We&apos;ll queue a multi-agent run against your constraints. Live
          progress starts immediately, and ranked results are saved to history.
        </p>
      </div>
      <p className="mb-6 max-w-xl rounded-xl border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-950">
        📍 Currently, listing data is available for the Austin, Texas area
        only. More cities coming soon!
      </p>
      <RequestForm />
    </div>
  );
}
