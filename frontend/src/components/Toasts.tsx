export type ToastItem = { id: string; text: string; kind: string };

export function Toasts({
  items,
  dismiss,
}: {
  items: ToastItem[];
  dismiss: (id: string) => void;
}) {
  return (
    <div className="toasts" aria-live="polite">
      {items.map((item) => (
        <button
          key={item.id}
          type="button"
          className={`toast ${item.kind}`}
          aria-label={`Dismiss notification: ${item.text}`}
          onClick={() => dismiss(item.id)}
        >
          {item.text}
        </button>
      ))}
    </div>
  );
}
