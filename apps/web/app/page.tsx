import BackendStatus from "./backend-status";

export default function Home() {
  return (
    <main className="flex min-h-screen items-center justify-center px-6">
      <section className="w-full max-w-lg rounded-lg border border-slate-200 bg-white p-8 shadow-sm">
        <h1 className="text-3xl font-semibold tracking-tight text-slate-900">
          CourseMate AI
        </h1>
        <p className="mt-2 text-slate-600">AI-powered course study assistant</p>

        <div className="mt-8 space-y-3 text-sm">
          <p>
            Frontend: <span className="font-medium text-green-700">Running</span>
          </p>
          <BackendStatus />
        </div>
      </section>
    </main>
  );
}
