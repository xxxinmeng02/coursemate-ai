"use client";

export default function ErrorPage({ reset }: { reset: () => void }) {
  return (
    <main className="route-error">
      <span className="state-icon error-icon">!</span>
      <h1>Something went wrong</h1>
      <p>CourseMate hit an unexpected error while rendering this page.</p>
      <button className="button primary" type="button" onClick={reset}>Try again</button>
    </main>
  );
}