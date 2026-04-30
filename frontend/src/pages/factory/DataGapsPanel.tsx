type DataGapsPanelProps = {
  dataGaps: string[];
};

export function DataGapsPanel({ dataGaps }: DataGapsPanelProps) {
  return (
    <section className="gaps-panel" aria-label="Data gaps">
      <div>
        <p className="eyebrow">Data gaps</p>
        <h2>Не показываем то, чего нет в API</h2>
      </div>
      <ul>
        {dataGaps.map((gap) => (
          <li key={gap}>{gap}</li>
        ))}
      </ul>
    </section>
  );
}
