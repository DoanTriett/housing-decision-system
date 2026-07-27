"use client";

import Link from "next/link";

export default function NotFound() {
  return (
    <div className="mx-auto flex min-h-[60vh] max-w-lg flex-col items-center justify-center px-4 text-center">
      <p className="text-sm uppercase tracking-wide text-muted-foreground">404</p>
      <h1 className="mt-2 font-[family-name:var(--font-display)] text-3xl text-[#0f5444]">
        Page not found
      </h1>
      <p className="mt-3 text-muted-foreground">
        That route doesn&apos;t exist. Head home or start a new housing request.
      </p>
      <div className="mt-6 flex gap-4 text-sm">
        <Link href="/" className="font-medium text-[#0f5444] underline-offset-4 hover:underline">
          Home
        </Link>
        <Link
          href="/request"
          className="font-medium text-[#0f5444] underline-offset-4 hover:underline"
        >
          New request
        </Link>
      </div>
    </div>
  );
}
