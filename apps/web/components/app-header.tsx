"use client";

import Link from "next/link";
import { SignedIn, SignedOut, UserButton } from "@clerk/nextjs";

import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export function AppHeader() {
  return (
    <header className="border-b border-border/80 bg-background/80 backdrop-blur-md">
      <div className="mx-auto flex h-14 max-w-5xl items-center justify-between px-4 sm:px-6">
        <div className="flex items-center gap-6">
          <Link
            href="/"
            className="font-[family-name:var(--font-display)] text-lg tracking-tight text-foreground"
          >
            Housing Decision
          </Link>
          <SignedIn>
            <nav className="flex items-center gap-4 text-sm text-muted-foreground">
              <Link
                href="/request"
                className="transition-colors hover:text-foreground"
              >
                New request
              </Link>
              <Link
                href="/history"
                className="transition-colors hover:text-foreground"
              >
                History
              </Link>
              <Link
                href="/admin/observability"
                className="transition-colors hover:text-foreground"
              >
                Observability
              </Link>
            </nav>
          </SignedIn>
        </div>
        <div className="flex items-center gap-2">
          <SignedOut>
            <Link
              href="/sign-in"
              className={cn(buttonVariants({ variant: "ghost", size: "sm" }))}
            >
              Sign in
            </Link>
            <Link
              href="/sign-up"
              className={cn(buttonVariants({ size: "sm" }))}
            >
              Sign up
            </Link>
          </SignedOut>
          <SignedIn>
            <UserButton afterSignOutUrl="/" />
          </SignedIn>
        </div>
      </div>
    </header>
  );
}
