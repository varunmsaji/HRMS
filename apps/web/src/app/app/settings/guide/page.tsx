"use client";

import { ArrowUpRight } from "lucide-react";
import Link from "next/link";

import { PageHeader } from "@/components/common/page-header";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { SETTINGS_GUIDE, guideGroups } from "@/lib/settings-guide/types";

export default function SettingsGuidePage() {
  const { overview } = SETTINGS_GUIDE;
  const groups = guideGroups(SETTINGS_GUIDE);

  return (
    <div className="space-y-6">
      <PageHeader
        backHref="/app/settings"
        backLabel="Settings"
        title="Settings Guide"
        description="What each setting is, what every option does, and how to use it — in plain English."
      />

      <div className="grid gap-8 lg:grid-cols-[14rem_minmax(0,1fr)]">
        <nav
          aria-label="Guide contents"
          className="hidden lg:sticky lg:top-6 lg:block lg:max-h-[calc(100vh-3rem)] lg:self-start lg:overflow-y-auto"
        >
          <ul className="space-y-4 text-sm">
            <li>
              <a
                href="#overview"
                className="font-medium text-foreground-secondary hover:text-primary"
              >
                How it fits together
              </a>
            </li>
            {groups.map((group) => (
              <li key={group.group}>
                <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-foreground-muted">
                  {group.group}
                </p>
                <ul className="space-y-1">
                  {group.sections.map((section) => (
                    <li key={section.id}>
                      <a
                        href={`#${section.id}`}
                        className="block rounded px-2 py-1 text-foreground-secondary hover:bg-primary-subtle hover:text-primary"
                      >
                        {section.title}
                      </a>
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        </nav>

        <div className="space-y-8">
          <Card id="overview" className="scroll-mt-6">
            <CardHeader>
              <h2 className="text-base font-semibold leading-snug tracking-tight text-foreground">{overview.title}</h2>
            </CardHeader>
            <CardContent className="space-y-4 text-sm text-foreground-secondary">
              {overview.paragraphs.map((paragraph) => (
                <p key={paragraph}>{paragraph}</p>
              ))}
              <div>
                <h3 className="mb-2 text-sm font-semibold text-foreground">{overview.stepsTitle}</h3>
                <ol className="list-decimal space-y-1.5 pl-5">
                  {overview.steps.map((step) => (
                    <li key={step}>{step}</li>
                  ))}
                </ol>
              </div>
              <dl className="grid gap-3 sm:grid-cols-2">
                {overview.glossary.map((entry) => (
                  <div key={entry.term} className="rounded-md border border-border p-3">
                    <dt className="text-sm font-medium text-foreground">{entry.term}</dt>
                    <dd className="mt-1 text-xs">{entry.text}</dd>
                  </div>
                ))}
              </dl>
            </CardContent>
          </Card>

          {groups.map((group) => (
            <div key={group.group} className="space-y-6">
              <h2 className="text-md font-semibold text-foreground">{group.group}</h2>
              {group.sections.map((section) => (
                <Card key={section.id} id={section.id} className="scroll-mt-6">
                  <CardHeader className="flex-row items-start justify-between gap-3 space-y-0">
                    <h3 className="text-base font-semibold leading-snug tracking-tight text-foreground">{section.title}</h3>
                    <Link
                      href={section.href}
                      className="inline-flex shrink-0 items-center gap-1 text-xs font-medium text-primary hover:underline"
                    >
                      Open setting
                      <ArrowUpRight className="h-3.5 w-3.5" aria-hidden="true" />
                    </Link>
                  </CardHeader>
                  <CardContent className="space-y-5 text-sm text-foreground-secondary">
                    <p className="text-foreground">{section.summary}</p>
                    <p>
                      <span className="font-medium text-foreground">When to use it: </span>
                      {section.whenToUse}
                    </p>

                    {section.parts.map((part) => (
                      <section key={part.title} className="space-y-2">
                        <h4 className="text-sm font-semibold text-foreground">{part.title}</h4>
                        {part.intro ? <p className="text-xs">{part.intro}</p> : null}
                        <dl className="divide-y divide-border rounded-md border border-border">
                          {part.items.map((item) => (
                            <div
                              key={item.name}
                              className="grid gap-1 px-3 py-2 sm:grid-cols-[13rem_minmax(0,1fr)] sm:gap-4"
                            >
                              <dt className="font-medium text-foreground">{item.name}</dt>
                              <dd>{item.text}</dd>
                            </div>
                          ))}
                        </dl>
                      </section>
                    ))}

                    {section.example ? (
                      <div className="rounded-md bg-muted/50 p-3">
                        <p className="text-xs font-semibold uppercase tracking-wide text-foreground-muted">
                          Example
                        </p>
                        <p className="mt-1">{section.example}</p>
                      </div>
                    ) : null}

                    {section.tips.length > 0 ? (
                      <div>
                        <p className="text-xs font-semibold uppercase tracking-wide text-foreground-muted">
                          Good to know
                        </p>
                        <ul className="mt-1 list-disc space-y-1 pl-5">
                          {section.tips.map((tip) => (
                            <li key={tip}>{tip}</li>
                          ))}
                        </ul>
                      </div>
                    ) : null}
                  </CardContent>
                </Card>
              ))}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
