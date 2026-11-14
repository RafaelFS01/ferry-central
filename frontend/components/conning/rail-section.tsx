interface RailSectionProps {
  title: string;
  aside?: React.ReactNode;
  children: React.ReactNode;
}

/** Seção do rail de conning, separada das vizinhas apenas por um filete. */
export function RailSection({ title, aside, children }: RailSectionProps) {
  return (
    <section className="border-b border-line px-5 py-5 last:border-0">
      <header className="mb-4 flex items-baseline justify-between gap-3">
        <h2 className="engraved">{title}</h2>
        {aside}
      </header>
      {children}
    </section>
  );
}
