"use client";

import { Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

/** Top-bar search for the company view. Searches employees (the directory filters by name/code). */
export function CompanySearch() {
  const router = useRouter();
  const [query, setQuery] = useState("");

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    const q = query.trim();
    router.push(q ? `/app/employees?q=${encodeURIComponent(q)}` : "/app/employees");
  }

  return (
    <form onSubmit={onSubmit} role="search" className="relative hidden shrink-0 lg:block lg:w-60 xl:w-72">
      <Search
        className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-foreground-muted"
        aria-hidden="true"
      />
      <input
        type="search"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Search employees..."
        aria-label="Search employees"
        className="h-10 w-full rounded-lg bg-muted pl-9 pr-3 text-sm text-foreground placeholder:text-foreground-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      />
    </form>
  );
}
