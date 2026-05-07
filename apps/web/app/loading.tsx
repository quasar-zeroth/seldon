export default function Loading() {
  return (
    <main>
      <section className="header">
        <div>
          <div className="eyebrow">The Seldon Project</div>
          <h1>Loading mission control…</h1>
          <p className="muted">Fetching scenarios, agent runs, graph evidence, and predictions.</p>
        </div>
        <div className="status">Syncing</div>
      </section>
      <section className="grid">
        {Array.from({ length: 6 }).map((_, index) => <div className="card skeleton" key={index} />)}
      </section>
    </main>
  );
}
