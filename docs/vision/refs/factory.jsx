// factory.jsx — Isometric AI Agent Factory
// Renders the floor: stations, conveyor belts, agents, tickets, orchestrator,
// HUD overlays, and live stats. Reads snapshots from sim.jsx every frame.

const { useState, useEffect, useRef, useMemo } = React;

// ── Iso math ────────────────────────────────────────────────────────────────
// 2:1 dimetric. World grid coord (gx, gy) → screen (px, py).
const TILE_W = 64;
const TILE_H = 32;
function iso(gx, gy) {
  return {
    x: (gx - gy) * (TILE_W / 2),
    y: (gx + gy) * (TILE_H / 2),
  };
}

// Station floor positions in grid coords. To make the floor read horizontally
// on screen we want screen-y constant, which means gx - gy = const (step in gx
// matched by equal step in gy). We slope very slightly upward by stepping gy
// one less than gx every other station so depth is felt without going off-screen.
const STATION_GX = [0, 3, 6, 9, 12, 15];
const STATION_GY = [4, 3, 2, 1, 0, -1];
function stationPos(idx) {
  return iso(STATION_GX[idx], STATION_GY[idx]);
}

// ── Visual primitives ───────────────────────────────────────────────────────

// Hazard-stripe pattern definition (reusable in multiple SVGs)
function HazardPattern({ id }) {
  return (
    <pattern id={id} width="12" height="12" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
      <rect width="12" height="12" fill="#1a1410" />
      <rect width="6" height="12" fill="#f5c518" />
    </pattern>
  );
}

// A single isometric tile (diamond)
function Tile({ x, y, fill = '#1f1a14', stroke = '#2a221a', strokeWidth = 1 }) {
  const pts = [
    [x, y - TILE_H / 2],
    [x + TILE_W / 2, y],
    [x, y + TILE_H / 2],
    [x - TILE_W / 2, y],
  ].map((p) => p.join(',')).join(' ');
  return <polygon points={pts} fill={fill} stroke={stroke} strokeWidth={strokeWidth} />;
}

// Iso block (cube-ish) for stations — top diamond + two side faces
function IsoBlock({ cx, cy, w = 3, d = 3, h = 60, top = '#2a2218', left = '#1a140e', right = '#221c14', stroke = '#3a2e22' }) {
  // w,d in tile units. Compute corners in iso space.
  const tlX = cx, tlY = cy - (w + d) * TILE_H / 4 - 0; // not used directly
  const A = iso(0, 0); // anchor placeholder
  // Build top diamond from 4 corners around (cx,cy):
  const halfW = (w * TILE_W) / 2;
  const halfD = (d * TILE_H) / 2;
  // top corners (iso)
  const N = { x: cx, y: cy - halfD }; // back
  const E = { x: cx + halfW, y: cy };
  const S = { x: cx, y: cy + halfD };
  const W = { x: cx - halfW, y: cy };
  // bottom corners (just shift down by h)
  const Nb = { x: N.x, y: N.y + h };
  const Eb = { x: E.x, y: E.y + h };
  const Sb = { x: S.x, y: S.y + h };
  const Wb = { x: W.x, y: W.y + h };

  return (
    <g>
      {/* left face (W → S) */}
      <polygon points={`${W.x},${W.y} ${S.x},${S.y} ${Sb.x},${Sb.y} ${Wb.x},${Wb.y}`}
               fill={left} stroke={stroke} strokeWidth="1" />
      {/* right face (S → E) */}
      <polygon points={`${S.x},${S.y} ${E.x},${E.y} ${Eb.x},${Eb.y} ${Sb.x},${Sb.y}`}
               fill={right} stroke={stroke} strokeWidth="1" />
      {/* top */}
      <polygon points={`${N.x},${N.y} ${E.x},${E.y} ${S.x},${S.y} ${W.x},${W.y}`}
               fill={top} stroke={stroke} strokeWidth="1" />
    </g>
  );
}

// Belt segment between two station positions (straight diagonal in iso along +x grid)
function Belt({ fromIdx, toIdx, animate = true, hot = false }) {
  const a = stationPos(fromIdx);
  const b = stationPos(toIdx);
  // Belts have 1 tile thickness (TILE_H) — draw two parallel lines forming an iso strip.
  // Direction in screen space:
  const dx = b.x - a.x, dy = b.y - a.y;
  const len = Math.hypot(dx, dy);
  const ux = dx / len, uy = dy / len;
  // Perpendicular for thickness (in iso, perpendicular to +x grid direction is +y grid direction; here we cheat with a small offset)
  const thickness = 22;
  const px = -uy * thickness / 2;
  const py = ux * thickness / 2;

  const A1 = { x: a.x + px, y: a.y + py };
  const A2 = { x: a.x - px, y: a.y - py };
  const B1 = { x: b.x + px, y: b.y + py };
  const B2 = { x: b.x - px, y: b.y - py };

  // back-side (further from camera) is the upper edge in iso (smaller y)
  return (
    <g>
      {/* shadow */}
      <polygon points={`${A1.x},${A1.y + 6} ${B1.x},${B1.y + 6} ${B2.x},${B2.y + 6} ${A2.x},${A2.y + 6}`}
               fill="rgba(0,0,0,0.55)" />
      {/* belt body */}
      <polygon points={`${A1.x},${A1.y} ${B1.x},${B1.y} ${B2.x},${B2.y} ${A2.x},${A2.y}`}
               fill="#15110c" stroke="#2a2218" strokeWidth="1" />
      {/* belt centerline rail */}
      <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke={hot ? '#ff7a18' : '#3a2e22'} strokeWidth="1.5" strokeDasharray="6 4">
        {animate && (
          <animate attributeName="stroke-dashoffset" from="0" to="-20" dur="0.8s" repeatCount="indefinite" />
        )}
      </line>
      {/* arrow chevrons */}
      {Array.from({ length: 6 }).map((_, i) => {
        const t = (i + 0.5) / 6;
        const cx = a.x + dx * t;
        const cy = a.y + dy * t;
        const angle = Math.atan2(dy, dx) * 180 / Math.PI;
        return (
          <g key={i} transform={`translate(${cx},${cy}) rotate(${angle})`}>
            <path d="M -5 -3 L 0 0 L -5 3" fill="none" stroke={hot ? '#ffb200' : '#5a4838'} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              {animate && (
                <animate attributeName="opacity" values="0.3;1;0.3" dur="1.2s" begin={`${i * -0.2}s`} repeatCount="indefinite" />
              )}
            </path>
          </g>
        );
      })}
    </g>
  );
}

// Ticket sprite — a small iso-cube
function Ticket({ x, y, kind = 'feat', glyph = '◆', size = 14, dim = false }) {
  const colors = {
    feat:  { top: '#f5c518', side: '#a37a00' },
    bug:   { top: '#ff5544', side: '#a02a1c' },
    chore: { top: '#7ad7f0', side: '#2e7a92' },
    docs:  { top: '#c084fc', side: '#5a3a82' },
  }[kind] || { top: '#aaa', side: '#555' };
  const w = size, h = size * 0.5, dh = size * 0.6;

  return (
    <g transform={`translate(${x},${y})`} opacity={dim ? 0.55 : 1}>
      {/* shadow */}
      <ellipse cx="0" cy={dh + 3} rx={w * 0.6} ry={3} fill="rgba(0,0,0,0.6)" />
      {/* left face */}
      <polygon points={`${-w},0 0,${h} 0,${h + dh} ${-w},${dh}`} fill={colors.side} />
      {/* right face */}
      <polygon points={`0,${h} ${w},0 ${w},${dh} 0,${h + dh}`} fill={colors.side} stroke="#000" strokeOpacity="0.3" />
      {/* top */}
      <polygon points={`0,${-h} ${w},0 0,${h} ${-w},0`} fill={colors.top} stroke="#000" strokeOpacity="0.3" />
      {/* glyph on top */}
      <text x="0" y="3" fontSize="9" fontFamily="ui-monospace, monospace" fontWeight="700"
            textAnchor="middle" fill="#1a1410">{glyph}</text>
    </g>
  );
}

// Station building — base + machine
function StationBuilding({ idx, station, bottleneck, highlight }) {
  const { x: sx, y: sy } = stationPos(idx);
  const { color, name, short } = station;
  const isBottle = highlight && bottleneck === station.id;

  // Base platform (iso block)
  return (
    <g>
      {/* platform */}
      <IsoBlock cx={sx} cy={sy + 8} w={3} d={3} h={10}
                top={isBottle ? '#3a2218' : '#1f1a14'}
                left="#100c08" right="#15110c" stroke="#2e2418" />
      {/* machine body */}
      <g transform={`translate(${sx},${sy - 18})`}>
        <IsoBlock cx={0} cy={0} w={2.2} d={2.2} h={42}
                  top={isBottle ? '#5a2418' : '#2a221a'}
                  left="#150f0a" right="#1c160f" stroke="#3a2e22" />
        {/* color stripe band on top */}
        <rect x={-22} y={-4} width="44" height="3" fill={color} opacity="0.85" />
        {/* status light */}
        <circle cx={0} cy={-12} r="3" fill={isBottle ? '#ff3322' : color}>
          <animate attributeName="opacity" values="1;0.4;1" dur={isBottle ? '0.4s' : '1.6s'} repeatCount="indefinite" />
        </circle>
        {/* bottleneck hazard tape */}
        {isBottle && (
          <g>
            <rect x={-30} y={26} width="60" height="6" fill="url(#hz)" />
          </g>
        )}
      </g>
      {/* label */}
      <g transform={`translate(${sx},${sy + 36})`}>
        <rect x={-30} y={-8} width="60" height="16" rx="2" fill="#0a0805" stroke="#2a2218" />
        <text x="0" y="3" fontSize="10" fontFamily="ui-monospace, monospace" fontWeight="700"
              textAnchor="middle" fill={color} letterSpacing="1">{short}</text>
      </g>
    </g>
  );
}

// Agent — small iso figure beside station, with progress arc
function AgentSprite({ x, y, busy, progress, ticket, label }) {
  return (
    <g transform={`translate(${x},${y})`}>
      {/* shadow */}
      <ellipse cx="0" cy="14" rx="9" ry="3" fill="rgba(0,0,0,0.6)" />
      {/* body — iso cube */}
      <polygon points="-7,0 0,4 0,14 -7,10" fill="#3a2e22" />
      <polygon points="0,4 7,0 7,10 0,14" fill="#4a3a2a" />
      <polygon points="0,-4 7,0 0,4 -7,0" fill={busy ? '#ff7a18' : '#5a4838'} />
      {/* head — cyclopic eye */}
      <circle cx="0" cy="-2" r="2.2" fill={busy ? '#ffe066' : '#3a2e22'}>
        {busy && <animate attributeName="opacity" values="1;0.5;1" dur="0.8s" repeatCount="indefinite" />}
      </circle>
      {/* progress arc */}
      {busy && (
        <g>
          <circle cx="0" cy="-12" r="6" fill="none" stroke="#0a0805" strokeWidth="2" />
          <circle cx="0" cy="-12" r="6" fill="none" stroke="#f5c518" strokeWidth="2"
                  strokeDasharray={`${progress * 37.7} 37.7`}
                  transform="rotate(-90 0 -12)" strokeLinecap="round" />
        </g>
      )}
      {/* held ticket floating above */}
      {busy && ticket && (
        <g transform="translate(0,-22)">
          <Ticket x={0} y={0} kind={ticket.kind} glyph={ticket.glyph} size={6} />
        </g>
      )}
      {/* agent id */}
      <text x="0" y="22" fontSize="6" fontFamily="ui-monospace, monospace"
            textAnchor="middle" fill="#5a4838" letterSpacing="0.5">{label}</text>
    </g>
  );
}

// Queue — render a line of tickets in front of station
function StationQueue({ idx, queue }) {
  const { x: sx, y: sy } = stationPos(idx);
  // Queue runs to the south-west of station (down-left in iso)
  const items = queue.slice(0, 8);
  return (
    <g>
      {items.map((t, i) => {
        const off = (i + 1);
        const px = sx - off * 10;
        const py = sy + 18 + off * 5;
        return <Ticket key={t.id} x={px} y={py} kind={t.kind} glyph={t.glyph} size={6} dim={i > 4} />;
      })}
      {queue.length > 8 && (
        <text x={sx - 90} y={sy + 70} fontSize="9" fontFamily="ui-monospace, monospace"
              fill="#ff7a18" fontWeight="700">+{queue.length - 8}</text>
      )}
    </g>
  );
}

// Belt ticket (in transit)
function BeltTicket({ ticket }) {
  const a = stationPos(ticket.from);
  const b = stationPos(ticket.to);
  const t = ticket.prog;
  const x = a.x + (b.x - a.x) * t;
  const y = a.y + (b.y - a.y) * t - 6 + Math.sin(t * Math.PI * 4) * 1.5;
  return <Ticket x={x} y={y} kind={ticket.kind} glyph={ticket.glyph} size={7} />;
}

// Orchestrator — control tower above the floor with beams to each station
function Orchestrator({ stations, bottleneck }) {
  // Center above the line of stations
  const midX = (stationPos(0).x + stationPos(STATION_GX.length - 1).x) / 2;
  const midY = (stationPos(0).y + stationPos(STATION_GX.length - 1).y) / 2 - 220;

  return (
    <g>
      {/* beams from tower to each station */}
      {stations.map((st, i) => {
        const sp = stationPos(i);
        const isHot = bottleneck === st.id;
        return (
          <g key={st.id}>
            <line x1={midX} y1={midY + 18} x2={sp.x} y2={sp.y - 30}
                  stroke={isHot ? '#ff3322' : st.color} strokeWidth="1" opacity="0.35"
                  strokeDasharray="3 4">
              <animate attributeName="stroke-dashoffset" from="0" to="-14" dur="1.6s" repeatCount="indefinite" />
            </line>
            {/* data packet pulse */}
            <circle r="2.5" fill={st.color} opacity="0.9">
              <animateMotion dur={`${2.4 + i * 0.3}s`} repeatCount="indefinite"
                             path={`M ${midX} ${midY + 18} L ${sp.x} ${sp.y - 30}`} />
              <animate attributeName="opacity" values="0;1;0" dur={`${2.4 + i * 0.3}s`} repeatCount="indefinite" />
            </circle>
          </g>
        );
      })}

      {/* tower base */}
      <g transform={`translate(${midX},${midY})`}>
        {/* legs */}
        <line x1={-30} y1={20} x2={-12} y2={70} stroke="#3a2e22" strokeWidth="2" />
        <line x1={30} y1={20} x2={12} y2={70} stroke="#3a2e22" strokeWidth="2" />
        <line x1={0} y1={26} x2={0} y2={70} stroke="#3a2e22" strokeWidth="2" />
        {/* tower body — hexagonal-ish iso */}
        <IsoBlock cx={0} cy={0} w={2.6} d={2.6} h={26}
                  top="#1a1410" left="#0c0805" right="#13100a" stroke="#3a2e22" />
        {/* roof / antenna housing */}
        <polygon points="-30,0 0,-16 30,0 0,16" fill="#0c0805" stroke="#ff7a18" strokeWidth="1.5" />
        {/* center console — bright */}
        <rect x={-8} y={-6} width="16" height="10" fill="#1a1410" stroke="#ff7a18" />
        <rect x={-6} y={-4} width="12" height="6" fill="#ff7a18" opacity="0.85">
          <animate attributeName="opacity" values="0.6;1;0.6" dur="1.2s" repeatCount="indefinite" />
        </rect>
        {/* antenna */}
        <line x1={0} y1={-16} x2={0} y2={-34} stroke="#ff7a18" strokeWidth="1.2" />
        <circle cx={0} cy={-36} r="2.5" fill="#ff7a18">
          <animate attributeName="r" values="2;4;2" dur="1.4s" repeatCount="indefinite" />
          <animate attributeName="opacity" values="1;0.3;1" dur="1.4s" repeatCount="indefinite" />
        </circle>
        {/* radar arc */}
        <path d="M -30 -2 A 30 14 0 0 1 30 -2" fill="none" stroke="#f5c518" strokeWidth="0.8" opacity="0.5" />
        <path d="M -22 -1 A 22 10 0 0 1 22 -1" fill="none" stroke="#f5c518" strokeWidth="0.8" opacity="0.3" />
        {/* label */}
        <g transform="translate(0, 80)">
          <rect x={-46} y={-9} width="92" height="18" rx="2" fill="#0a0805" stroke="#ff7a18" strokeWidth="1" />
          <text x={0} y={4} fontSize="10" fontFamily="ui-monospace, monospace" fontWeight="700"
                textAnchor="middle" fill="#ff7a18" letterSpacing="2">ORCHESTRATOR</text>
        </g>
      </g>
    </g>
  );
}

// Floor grid (subtle iso tiles under stations)
function FloorGrid() {
  const tiles = [];
  for (let gx = -2; gx <= 17; gx++) {
    for (let gy = -3; gy <= 6; gy++) {
      const { x, y } = iso(gx, gy);
      const dim = ((gx + gy) % 2 === 0);
      tiles.push(
        <Tile key={`${gx},${gy}`} x={x} y={y}
              fill={dim ? '#0e0a07' : '#120d09'}
              stroke="#1a1410" strokeWidth="0.5" />
      );
    }
  }
  return <g opacity="0.95">{tiles}</g>;
}

// Stat chip
function StatChip({ label, value, accent = '#f5c518', flash = false }) {
  return (
    <div style={{
      display: 'flex', flexDirection: 'column', gap: 2,
      padding: '6px 10px',
      background: 'rgba(0,0,0,0.55)',
      border: `1px solid ${accent}55`,
      borderLeft: `3px solid ${accent}`,
      minWidth: 88,
    }}>
      <div style={{ fontSize: 9, letterSpacing: 1.5, color: '#7a6e5a', fontFamily: 'ui-monospace, monospace', textTransform: 'uppercase' }}>{label}</div>
      <div style={{ fontSize: 16, color: accent, fontFamily: 'ui-monospace, monospace', fontWeight: 700, fontVariantNumeric: 'tabular-nums' }}>{value}</div>
    </div>
  );
}

// Station HUD card
function StationHUD({ station, m, isBottle }) {
  return (
    <div style={{
      flex: 1,
      padding: '8px 10px',
      background: 'rgba(0,0,0,0.6)',
      border: `1px solid ${isBottle ? '#ff3322' : station.color + '44'}`,
      borderTop: `3px solid ${isBottle ? '#ff3322' : station.color}`,
      display: 'flex', flexDirection: 'column', gap: 4,
      position: 'relative', overflow: 'hidden',
    }}>
      {isBottle && (
        <div style={{
          position: 'absolute', inset: 0,
          background: 'repeating-linear-gradient(45deg, rgba(255,51,34,0.0) 0 8px, rgba(255,51,34,0.08) 8px 16px)',
          pointerEvents: 'none',
        }} />
      )}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
        <span style={{ fontSize: 10, color: station.color, fontFamily: 'ui-monospace, monospace', fontWeight: 700, letterSpacing: 1.5 }}>
          {station.short} · {station.name}
        </span>
        {isBottle && <span style={{ fontSize: 9, color: '#ff3322', fontWeight: 700, letterSpacing: 1.5 }}>⚠ BOTTLE</span>}
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 2, fontSize: 10, fontFamily: 'ui-monospace, monospace', color: '#a89878' }}>
        <span>Q <span style={{ color: m.queue >= 4 ? '#ff7a18' : '#e8d8a8', fontWeight: 700 }}>{m.queue}</span></span>
        <span>WIP <span style={{ color: '#e8d8a8', fontWeight: 700 }}>{m.wip}/{m.cap}</span></span>
        <span>UTL <span style={{ color: '#e8d8a8', fontWeight: 700 }}>{Math.round(m.util * 100)}%</span></span>
        <span>OUT <span style={{ color: '#e8d8a8', fontWeight: 700 }}>{m.finished}</span></span>
      </div>
      {/* utilization bar */}
      <div style={{ height: 3, background: '#1a1410', position: 'relative' }}>
        <div style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: `${Math.min(100, m.util * 100)}%`, background: isBottle ? '#ff3322' : station.color }} />
      </div>
    </div>
  );
}

// Activity log
function ActivityLog({ log }) {
  return (
    <div style={{
      width: 260,
      background: 'rgba(0,0,0,0.7)',
      border: '1px solid #2a2218',
      borderLeft: '3px solid #ff7a18',
      padding: 10,
      fontSize: 10,
      fontFamily: 'ui-monospace, monospace',
      color: '#a89878',
      maxHeight: 200,
      overflow: 'hidden',
    }}>
      <div style={{ fontSize: 9, color: '#ff7a18', letterSpacing: 1.5, marginBottom: 6, fontWeight: 700 }}>◆ ORCH LOG</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        {log.slice(0, 10).map((l, i) => (
          <div key={l.at + '-' + i} style={{ opacity: 1 - i * 0.07, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
            <span style={{ color: '#5a4838' }}>{String(l.at).padStart(5, '0')}</span> {l.msg}
          </div>
        ))}
      </div>
    </div>
  );
}

// Legend
function Legend() {
  return (
    <div style={{
      display: 'flex', gap: 12,
      background: 'rgba(0,0,0,0.6)',
      border: '1px solid #2a2218',
      padding: '6px 10px',
      fontSize: 9, fontFamily: 'ui-monospace, monospace', color: '#a89878',
      letterSpacing: 1,
    }}>
      {[['feat', 'FEAT'], ['bug', 'BUG'], ['chore', 'CHORE'], ['docs', 'DOCS']].map(([k, l]) => (
        <span key={k} style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
          <svg width="10" height="10" viewBox="-7 -7 14 14"><Ticket x={0} y={0} kind={k} glyph="" size={5} /></svg>
          {l}
        </span>
      ))}
    </div>
  );
}

// ── Main App ────────────────────────────────────────────────────────────────
const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "intake_n": 1,
  "plan_n": 2,
  "code_n": 3,
  "test_n": 1,
  "review_n": 1,
  "ship_n": 1,
  "highlight_bottleneck": true,
  "strategy": "load",
  "speed": 2
}/*EDITMODE-END*/;

function App() {
  const [t, setTweak] = useTweaks(TWEAK_DEFAULTS);
  const [snap, setSnap] = useState(null);
  const simRef = useRef(null);

  // Init sim once
  useEffect(() => {
    simRef.current = window.makeSim({
      agentsPerStation: {
        intake: t.intake_n, plan: t.plan_n, code: t.code_n,
        test: t.test_n, review: t.review_n, ship: t.ship_n,
      },
      strategy: t.strategy,
    });
    setSnap(simRef.current.snapshot());
  }, []);

  // React to agent count changes
  useEffect(() => {
    if (!simRef.current) return;
    simRef.current.reconfigureAgents({
      intake: t.intake_n, plan: t.plan_n, code: t.code_n,
      test: t.test_n, review: t.review_n, ship: t.ship_n,
    });
  }, [t.intake_n, t.plan_n, t.code_n, t.test_n, t.review_n, t.ship_n]);

  useEffect(() => {
    window._strategy.value = t.strategy;
  }, [t.strategy]);

  // Sim loop
  useEffect(() => {
    let raf;
    let acc = 0;
    let last = performance.now();
    const tickMs = 100; // 1 tick = 100ms baseline
    const loop = (now) => {
      const dt = now - last; last = now;
      acc += dt * t.speed;
      const sim = simRef.current;
      if (sim) {
        let steps = 0;
        while (acc >= tickMs && steps < 20) {
          sim.step();
          acc -= tickMs;
          steps++;
        }
        setSnap(sim.snapshot());
      }
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [t.speed]);

  if (!snap) return null;

  // Compute total stats
  const totalShipped = snap.metrics.shipped;
  const totalThroughput = Object.values(snap.metrics.stations).reduce((a, m) => a + m.rate, 0);
  // global avg cycle from ship station
  const globalCycle = snap.metrics.stations.ship.cycle;
  const totalAgents = snap.stations.reduce((a, s) => a + s.agents.length, 0);
  const busyAgents = snap.stations.reduce((a, s) => a + s.agents.filter((x) => x.busy).length, 0);
  const totalWIP = busyAgents;
  const totalQueued = snap.stations.reduce((a, s) => a + s.queue.length, 0) + snap.belts.length;

  // Compute viewport for SVG — fit all station positions plus margins
  const allXs = STATION_GX.map((_, i) => stationPos(i).x);
  const allYs = STATION_GX.map((_, i) => stationPos(i).y);
  const minX = Math.min(...allXs) - 220;
  const maxX = Math.max(...allXs) + 220;
  const minY = Math.min(...allYs) - 300;
  const maxY = Math.max(...allYs) + 160;
  const vbW = maxX - minX;
  const vbH = maxY - minY;

  // Agent positions around station (in iso, west and east of station base)
  const agentSlots = (count) => {
    // arrange around station in a small circle
    const slots = [];
    for (let i = 0; i < count; i++) {
      const ang = (i / count) * Math.PI * 2 + Math.PI / 4;
      const r = 38;
      // iso projection: x stretched, y squished
      slots.push({ dx: Math.cos(ang) * r, dy: Math.sin(ang) * r * 0.5 + 8 });
    }
    return slots;
  };

  const bottleneck = t.highlight_bottleneck ? snap.metrics.bottleneck : null;

  return (
    <div style={{
      minHeight: '100vh',
      background: 'radial-gradient(ellipse at center, #15110c 0%, #0a0805 70%, #050302 100%)',
      color: '#e8d8a8',
      fontFamily: 'ui-monospace, "SF Mono", "JetBrains Mono", Menlo, monospace',
      padding: 24,
      display: 'flex', flexDirection: 'column', gap: 14,
      position: 'relative',
    }}>
      {/* Top bar */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          <div style={{
            width: 36, height: 36,
            background: 'repeating-linear-gradient(45deg, #f5c518 0 6px, #1a1410 6px 12px)',
            border: '1px solid #2a2218',
          }} />
          <div>
            <div style={{ fontSize: 11, letterSpacing: 3, color: '#7a6e5a', fontWeight: 600 }}>FACILITY 02 · SECTOR 7G</div>
            <div style={{ fontSize: 22, letterSpacing: 1, color: '#f5c518', fontWeight: 700, fontFamily: '"Inter", system-ui, sans-serif' }}>
              AI Coding Foundry <span style={{ color: '#ff7a18' }}>// AGENT FLOOR</span>
            </div>
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <StatChip label="SHIPPED" value={totalShipped} accent="#5cd66a" />
          <StatChip label="WIP" value={`${totalWIP}/${totalAgents}`} accent="#ff7a18" />
          <StatChip label="QUEUE" value={totalQueued} accent="#f5c518" />
          <StatChip label="THRU/MIN" value={totalThroughput} accent="#7ad7f0" />
          <StatChip label="CYCLE·t" value={globalCycle ?? '—'} accent="#c084fc" />
        </div>
      </div>

      {/* Main canvas */}
      <div style={{
        position: 'relative', flex: 1,
        background: 'linear-gradient(180deg, #0a0805 0%, #050302 100%)',
        border: '1px solid #2a2218',
        overflow: 'hidden',
        minHeight: 560,
      }}>
        {/* corner crosshairs */}
        {[[8, 8], [8, 'r'], ['b', 8], ['b', 'r']].map(([a, b], i) => (
          <div key={i} style={{
            position: 'absolute',
            top: a === 'b' ? 'auto' : a, bottom: a === 'b' ? 8 : 'auto',
            left: b === 'r' ? 'auto' : b, right: b === 'r' ? 8 : 'auto',
            width: 14, height: 14,
            borderTop: a === 'b' ? 'none' : '1px solid #ff7a18',
            borderBottom: a === 'b' ? '1px solid #ff7a18' : 'none',
            borderLeft: b === 'r' ? 'none' : '1px solid #ff7a18',
            borderRight: b === 'r' ? '1px solid #ff7a18' : 'none',
          }} />
        ))}

        {/* scanline overlay */}
        <div style={{
          position: 'absolute', inset: 0, pointerEvents: 'none',
          background: 'repeating-linear-gradient(0deg, rgba(255,255,255,0.0) 0px, rgba(255,255,255,0.015) 1px, rgba(255,255,255,0) 2px, rgba(0,0,0,0.06) 3px)',
          mixBlendMode: 'overlay',
        }} />

        <svg viewBox={`${minX} ${minY} ${vbW} ${vbH}`} style={{ width: '100%', height: '100%', display: 'block' }}>
          <defs>
            <HazardPattern id="hz" />
            <radialGradient id="floorGlow" cx="0.5" cy="0.5" r="0.7">
              <stop offset="0%" stopColor="#ff7a18" stopOpacity="0.06" />
              <stop offset="100%" stopColor="#ff7a18" stopOpacity="0" />
            </radialGradient>
          </defs>

          {/* floor */}
          <FloorGrid />
          <ellipse cx={(stationPos(0).x + stationPos(5).x) / 2} cy={(stationPos(0).y + stationPos(5).y) / 2 + 60} rx={vbW * 0.45} ry={80} fill="url(#floorGlow)" />

          {/* belts */}
          {[0, 1, 2, 3, 4].map((i) => (
            <Belt key={i} fromIdx={i} toIdx={i + 1} hot={bottleneck === snap.stations[i + 1].id} />
          ))}

          {/* queues, stations, agents drawn back-to-front */}
          {snap.stations.map((st, idx) => {
            const sp = stationPos(idx);
            const slots = agentSlots(st.agents.length);
            return (
              <g key={st.id}>
                <StationQueue idx={idx} queue={st.queue} />
                <StationBuilding idx={idx} station={st} bottleneck={snap.metrics.bottleneck} highlight={t.highlight_bottleneck} />
                {st.agents.map((a, ai) => {
                  const slot = slots[ai];
                  return (
                    <AgentSprite key={a.id}
                                 x={sp.x + slot.dx}
                                 y={sp.y + slot.dy}
                                 busy={a.busy}
                                 progress={a.progress}
                                 ticket={a.ticket}
                                 label={`A${ai + 1}`} />
                  );
                })}
              </g>
            );
          })}

          {/* tickets in flight */}
          {snap.belts.map((b) => <BeltTicket key={b.id} ticket={b} />)}

          {/* orchestrator on top */}
          <Orchestrator stations={snap.stations} bottleneck={bottleneck} />
        </svg>

        {/* facility overlay text */}
        <div style={{
          position: 'absolute', top: 12, left: 12,
          fontSize: 9, fontFamily: 'ui-monospace, monospace',
          color: '#5a4838', letterSpacing: 2,
        }}>
          T+{String(snap.tick).padStart(6, '0')} · 100ms/tick · STRAT={t.strategy.toUpperCase()}
        </div>
        <div style={{ position: 'absolute', top: 12, right: 12 }}><Legend /></div>
      </div>

      {/* Station HUD row */}
      <div style={{ display: 'flex', gap: 8 }}>
        {snap.stations.map((st) => (
          <StationHUD key={st.id} station={st}
                      m={snap.metrics.stations[st.id]}
                      isBottle={t.highlight_bottleneck && snap.metrics.bottleneck === st.id} />
        ))}
      </div>

      {/* bottom row: log + speed */}
      <div style={{ display: 'flex', gap: 8, alignItems: 'stretch' }}>
        <ActivityLog log={snap.log} />
        <div style={{
          flex: 1,
          background: 'rgba(0,0,0,0.6)',
          border: '1px solid #2a2218',
          borderLeft: '3px solid #f5c518',
          padding: 10,
          fontSize: 10, fontFamily: 'ui-monospace, monospace', color: '#a89878',
        }}>
          <div style={{ fontSize: 9, color: '#f5c518', letterSpacing: 1.5, marginBottom: 6, fontWeight: 700 }}>◆ FLOW SCHEMATIC</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
            {snap.stations.map((st, i) => (
              <React.Fragment key={st.id}>
                <span style={{
                  padding: '3px 8px',
                  border: `1px solid ${st.color}66`,
                  color: st.color,
                  fontWeight: 700, letterSpacing: 1.2,
                  background: snap.metrics.bottleneck === st.id && t.highlight_bottleneck ? 'rgba(255,51,34,0.15)' : 'rgba(0,0,0,0.4)',
                }}>{st.short}</span>
                {i < snap.stations.length - 1 && <span style={{ color: '#3a2e22' }}>━━▶</span>}
              </React.Fragment>
            ))}
          </div>
          <div style={{ marginTop: 8, color: '#5a4838', fontSize: 9 }}>
            Tickets enter at INTAKE, are routed by the ORCHESTRATOR through PLAN → CODE → TEST → REVIEW → SHIP. Failed tests rework back to CODE. Adjust agents, strategy and bottleneck highlighting from <span style={{ color: '#f5c518' }}>Tweaks</span>.
          </div>
        </div>
      </div>

      <TweaksPanel title="Tweaks">
        <TweakSection label="Agents per Station" />
        <TweakSlider label="Intake" value={t.intake_n} min={1} max={4} onChange={(v) => setTweak('intake_n', v)} />
        <TweakSlider label="Plan"   value={t.plan_n}   min={1} max={6} onChange={(v) => setTweak('plan_n', v)} />
        <TweakSlider label="Code"   value={t.code_n}   min={1} max={8} onChange={(v) => setTweak('code_n', v)} />
        <TweakSlider label="Test"   value={t.test_n}   min={1} max={6} onChange={(v) => setTweak('test_n', v)} />
        <TweakSlider label="Review" value={t.review_n} min={1} max={4} onChange={(v) => setTweak('review_n', v)} />
        <TweakSlider label="Ship"   value={t.ship_n}   min={1} max={4} onChange={(v) => setTweak('ship_n', v)} />
        <TweakSection label="Orchestrator" />
        <TweakRadio label="Strategy" value={t.strategy}
                    options={[{value:'round',label:'Round'},{value:'load',label:'Load'},{value:'priority',label:'Priority'}]}
                    onChange={(v) => setTweak('strategy', v)} />
        <TweakSection label="Display" />
        <TweakToggle label="Highlight bottleneck" value={t.highlight_bottleneck} onChange={(v) => setTweak('highlight_bottleneck', v)} />
        <TweakSlider label="Sim speed" value={t.speed} min={1} max={8} unit="×" onChange={(v) => setTweak('speed', v)} />
      </TweaksPanel>
    </div>
  );
}

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(<App />);
