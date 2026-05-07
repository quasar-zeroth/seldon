"use client";

export default function ErrorState({ error, reset }: { error: Error; reset: () => void }) {
  return (
    <main>
      <section className="header">
        <div>
          <div className="eyebrow">The Seldon Project</div>
          <h1>Mission control hit an error</h1>
          <p className="muted">{error.message || "Something went wrong while rendering the console."}</p>
        </div>
        <button className="button" onClick={reset}>Try again</button>
      </section>
    </main>
  );
}
