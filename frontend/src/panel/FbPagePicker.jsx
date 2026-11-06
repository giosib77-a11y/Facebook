/** Facebook-ზე რამდენიმე გვერდია — მომხმარებელი ირჩევს ერთს (სახელები React-ის escape-ით) */
export default function FbPagePicker({ pages, onPick, onCancel, busyId }) {
  if (!pages || pages.length === 0) return null;
  return (
    <section className="card" aria-label="Facebook გვერდის არჩევა">
      <h2>🔗 რომელი გვერდი დავაკავშირო?</h2>
      <p className="import-hint">
        თქვენს Facebook ანგარიშზე რამდენიმე გვერდია — აირჩიეთ ერთი. არჩევანი 10 წუთი მოქმედებს.
      </p>
      <div className="product-actions">
        {pages.map((p) => (
          <button
            key={p.id}
            type="button"
            className={"btn btn-ghost" + (busyId === p.id ? " is-loading" : "")}
            disabled={!!busyId && busyId !== p.id}
            onClick={() => onPick(p.id)}
          >
            {p.name}
          </button>
        ))}
      </div>
      <button type="button" className="btn btn-ghost btn-sm" onClick={onCancel} disabled={!!busyId}>
        გაუქმება
      </button>
    </section>
  );
}
