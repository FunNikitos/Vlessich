/** Inline SVG sparkline for latency probes (bars: green=ok, red=fail). */
import type { HealthProbeOut } from "@/lib/types";

interface Props {
  probes: HealthProbeOut[];
  width?: number;
  height?: number;
}

export function Sparkline({ probes, width = 320, height = 56 }: Props) {
  if (probes.length === 0) {
    return (
      <div
        style={{ width, height }}
        className="flex items-center justify-center rounded-md bg-bg-mid text-[11px] text-text-muted"
      >
        no probes
      </div>
    );
  }
  // Order: oldest → newest (left → right). Backend returns recent_probes desc.
  const ordered = [...probes].reverse();
  const maxLat = Math.max(
    1,
    ...ordered.map((p) => (p.ok && p.latency_ms ? p.latency_ms : 0)),
  );
  const barW = width / ordered.length;
  const gap = barW > 4 ? 1 : 0;

  return (
    <svg
      width={width}
      height={height}
      role="img"
      aria-label="Recent latency probes"
      className="block rounded-md bg-bg-mid"
    >
      {ordered.map((p, i) => {
        const x = i * barW + gap / 2;
        const w = Math.max(1, barW - gap);
        if (!p.ok) {
          return (
            <rect
              key={i}
              x={x}
              y={2}
              width={w}
              height={height - 4}
              fill="#e22134"
              opacity={0.8}
            />
          );
        }
        const lat = p.latency_ms ?? 0;
        const h = Math.max(2, ((height - 4) * lat) / maxLat);
        return (
          <rect
            key={i}
            x={x}
            y={height - 2 - h}
            width={w}
            height={h}
            fill="#1ed760"
          >
            <title>
              {new Date(p.probed_at).toLocaleString("ru-RU")}: {lat}ms
            </title>
          </rect>
        );
      })}
    </svg>
  );
}
