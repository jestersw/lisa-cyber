/**
 * Procedural project thumbnail from the mockup: two-color gradient with two
 * layers of SVG turbulence for a grainy, cloud-like AI-style look. Each
 * project gets a stable seed so the picture is deterministic.
 */
type Props = {
  id: string;
  c1: string;
  c2: string;
  seed: number;
};

export function ProjectThumb({ id, c1, c2, seed }: Props) {
  return (
    <svg
      className="thumb-svg"
      viewBox="0 0 320 180"
      preserveAspectRatio="xMidYMid slice"
      xmlns="http://www.w3.org/2000/svg"
    >
      <defs>
        <linearGradient id={`g${id}`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor={c1} />
          <stop offset="1" stopColor={c2} />
        </linearGradient>
        <filter id={`cloud${id}`}>
          <feTurbulence
            type="fractalNoise"
            baseFrequency="0.014"
            numOctaves={3}
            seed={seed}
          />
          <feColorMatrix type="saturate" values="0" />
        </filter>
        <filter id={`grain${id}`}>
          <feTurbulence
            type="fractalNoise"
            baseFrequency="0.9"
            numOctaves={2}
            seed={seed + 5}
          />
          <feColorMatrix type="saturate" values="0" />
        </filter>
      </defs>
      <rect width="320" height="180" fill={`url(#g${id})`} />
      <rect
        width="320"
        height="180"
        filter={`url(#cloud${id})`}
        opacity="0.55"
        style={{ mixBlendMode: "soft-light" }}
      />
      <rect
        width="320"
        height="180"
        filter={`url(#grain${id})`}
        opacity="0.34"
        style={{ mixBlendMode: "overlay" }}
      />
    </svg>
  );
}
