"use client";

import { useEffect } from "react";
import Link from "next/link";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <html lang="en">
      <body className="min-h-screen bg-[#f7f4ef] px-4 py-16 text-[#14201c]">
        <div className="mx-auto max-w-lg text-center">
          <h1 className="text-2xl font-semibold text-[#0f5444]">Something went wrong</h1>
          <p className="mt-3 text-sm text-[#5b675f]">
            {error.message || "An unexpected error occurred."}
          </p>
          <div className="mt-6 flex justify-center gap-4 text-sm">
            <button
              type="button"
              onClick={reset}
              className="rounded-md bg-[#0f5444] px-3 py-1.5 text-white"
            >
              Try again
            </button>
            <Link href="/" className="underline underline-offset-4">
              Home
            </Link>
          </div>
        </div>
      </body>
    </html>
  );
}
