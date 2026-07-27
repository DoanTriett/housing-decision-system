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
      <RequestForm />
    </div>
  );
}
