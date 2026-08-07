const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type HealthResponse = {
  data?: {
    status?: string;
    database?: string;
    redis?: string;
  };
  meta?: { request_id?: string };
};

async function getHealth(): Promise<HealthResponse | null> {
  try {
    const res = await fetch(`${API_URL}/health`, { cache: "no-store" });
    if (!res.ok) return null;
    return (await res.json()) as HealthResponse;
  } catch {
    return null;
  }
}

export default async function HomePage() {
  const health = await getHealth();
  const status = health?.data?.status ?? "unreachable";

  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col gap-8 p-8">
      <header>
        <p className="text-sm font-medium uppercase tracking-wide text-slate-500">HRMS Platform</p>
        <h1 className="mt-2 text-3xl font-semibold text-slate-900">Local development</h1>
        <p className="mt-2 text-slate-600">
          Next.js frontend and FastAPI backend. This page calls the API health endpoint on each
          request.
        </p>
      </header>

      <section className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
        <h2 className="text-lg font-medium text-slate-900">API status</h2>
        <dl className="mt-4 grid gap-3 text-sm">
          <div className="flex justify-between gap-4">
            <dt className="text-slate-500">Backend URL</dt>
            <dd className="font-mono text-slate-800">{API_URL}</dd>
          </div>
          <div className="flex justify-between gap-4">
            <dt className="text-slate-500">Overall</dt>
            <dd className="font-medium capitalize text-slate-800">{status}</dd>
          </div>
          {health?.data && (
            <>
              <div className="flex justify-between gap-4">
                <dt className="text-slate-500">Database</dt>
                <dd className="capitalize text-slate-800">{health.data.database}</dd>
              </div>
              <div className="flex justify-between gap-4">
                <dt className="text-slate-500">Redis check</dt>
                <dd className="capitalize text-slate-800">{health.data.redis}</dd>
              </div>
            </>
          )}
        </dl>
      </section>

      <section className="text-sm text-slate-500">
        <p>
          API docs:{" "}
          <a className="text-blue-600 underline" href={`${API_URL}/docs`}>
            {API_URL}/docs
          </a>
        </p>
      </section>
    </main>
  );
}
