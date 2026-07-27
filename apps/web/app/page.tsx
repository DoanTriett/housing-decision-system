import Link from "next/link";
import { SignedIn, SignedOut } from "@clerk/nextjs";

import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export default function LandingPage() {
  return (
    <section className="relative mx-auto flex min-h-[calc(100vh-3.5rem)] max-w-5xl flex-col justify-center px-4 py-16 sm:px-6">
      <div className="pointer-events-none absolute inset-x-0 top-10 -z-10 mx-auto h-64 max-w-3xl rounded-full bg-[radial-gradient(circle,_rgba(15,84,68,0.18),_transparent_70%)] blur-2xl" />
      <p className="font-[family-name:var(--font-display)] text-5xl tracking-tight text-[#0f5444] sm:text-6xl md:text-7xl">
        Housing Decision
      </p>
      <h1 className="mt-6 max-w-2xl text-2xl font-medium tracking-tight text-foreground sm:text-3xl">
        Ranked apartments with explicit trade-offs — not another endless listing
        feed.
      </h1>
      <p className="mt-4 max-w-xl text-base leading-relaxed text-muted-foreground sm:text-lg">
        Tell us your budget, commute anchor, and hard constraints. Specialist
        agents evaluate candidates in parallel and return a scored top pick with
        reasons you can trust.
      </p>
      <div className="mt-8 flex flex-wrap items-center gap-3">
        <SignedOut>
          <Link href="/sign-up" className={cn(buttonVariants({ size: "lg" }))}>
            Create an account
          </Link>
          <Link
            href="/sign-in"
            className={cn(buttonVariants({ variant: "outline", size: "lg" }))}
          >
            Sign in
          </Link>
        </SignedOut>
        <SignedIn>
          <Link href="/request" className={cn(buttonVariants({ size: "lg" }))}>
            Start a request
          </Link>
        </SignedIn>
      </div>
    </section>
  );
}
