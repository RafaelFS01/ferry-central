import type { TelemetryPoint } from '@/lib/central-api';
import { cardinalOf, formatNumber } from '@/lib/format';
import { RailSection } from './rail-section';

function HeadingArrow({ heading }: { heading: number }) {
  return (
    <svg viewBox="0 0 24 24" className="size-7 text-ship transition-transform duration-700" style={{ transform: `rotate(${heading}deg)` }} aria-hidden>
      <circle cx={12} cy={12} r={11} fill="none" stroke="currentColor" strokeOpacity={0.35} />
      <path d="M12 3 L16.5 16 L12 13.5 L7.5 16 Z" fill="currentColor" />
    </svg>
  );
}

/** Velocidade e rumo sobre o fundo em números grandes, como no bloco de conning do ECDIS. */
export function NavigationSection({ latest }: { latest: TelemetryPoint | null }) {
  const heading = latest?.heading ?? null;

  return (
    <RailSection title="Navegação">
      <dl className="grid grid-cols-2 gap-4">
        <div>
          <dt className="text-sm text-muted">Velocidade · SOG</dt>
          <dd className="mt-1 font-mono text-5xl font-medium leading-none tracking-tight">
            {formatNumber(latest?.speedKnots ?? null, 1)}
            <span className="ml-1.5 text-sm font-normal text-muted">nós</span>
          </dd>
        </div>
        <div>
          <dt className="text-sm text-muted">Rumo · COG</dt>
          <dd className="mt-1 flex items-center gap-3 font-mono text-5xl font-medium leading-none tracking-tight">
            {heading === null ? '—' : `${String(Math.round(heading) % 360).padStart(3, '0')}°`}
            {heading !== null && (
              <span className="flex flex-col items-center gap-0.5">
                <HeadingArrow heading={heading} />
                <span className="text-[0.6875rem] font-normal tracking-normal text-muted">{cardinalOf(heading)}</span>
              </span>
            )}
          </dd>
        </div>
      </dl>
    </RailSection>
  );
}
