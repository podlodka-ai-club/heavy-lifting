// sim.jsx — Factory simulation engine for the AI agent floor.
// Tickets flow: INTAKE → PLAN → CODE → TEST → REVIEW → SHIP
// Each station has N agents. Tickets queue, get picked, occupy an agent
// for `work` ticks, then route via the orchestrator's strategy to the next belt.

const STATIONS = [
  { id: 'intake',  name: 'INTAKE',   short: 'IN',  work: [12, 18], color: '#7a8896' },
  { id: 'plan',    name: 'PLAN',     short: 'PL',  work: [40, 80], color: '#f5c518' },
  { id: 'code',    name: 'CODE',     short: 'CD',  work: [80, 160], color: '#ff7a18' },
  { id: 'test',    name: 'TEST',     short: 'TS',  work: [40, 90], color: '#7ad7f0' },
  { id: 'review',  name: 'REVIEW',   short: 'RV',  work: [30, 70], color: '#c084fc' },
  { id: 'ship',    name: 'SHIP',     short: 'SH',  work: [10, 20], color: '#5cd66a' },
];

const TICKET_KINDS = [
  { kind: 'feat',  label: 'FEAT',  glyph: '◆' },
  { kind: 'bug',   label: 'BUG',   glyph: '✱' },
  { kind: 'chore', label: 'CHORE', glyph: '▲' },
  { kind: 'docs',  label: 'DOCS',  glyph: '■' },
];

let _nid = 1000;
const newId = () => (++_nid).toString(36).toUpperCase();

function rand(a, b) { return a + Math.random() * (b - a); }
function pick(arr) { return arr[Math.floor(Math.random() * arr.length)]; }

// ── Sim factory ─────────────────────────────────────────────────────────────
function createSim(opts = {}) {
  const agentsPerStation = opts.agentsPerStation || {
    intake: 1, plan: 2, code: 3, test: 1, review: 1, ship: 1,
  };
  const strategy = opts.strategy || 'load';
  const spawnEvery = opts.spawnEvery || 22; // ticks between intake spawns

  const stations = {};
  STATIONS.forEach((s) => {
    stations[s.id] = {
      ...s,
      queue: [],         // tickets waiting
      agents: Array.from({ length: agentsPerStation[s.id] || 1 }, (_, i) => ({
        id: `${s.id}-a${i + 1}`,
        ticket: null,
        progress: 0,
        total: 0,
        completed: 0,
      })),
      throughput: 0,     // total finished
      recentFinishes: [],// timestamps for throughput rate
      cycleSamples: [],  // last N cycle times
    };
  });

  const tickets = new Map();         // id → ticket
  const inFlight = [];               // tickets in transit on belts (ticket has .belt segment)
  const log = [];                    // recent orchestrator decisions
  const shipped = [];                // completed
  let tick = 0;
  let lastSpawn = 0;

  // Belts: from station idx -> next idx. Tickets travel for BELT_TICKS to cross.
  const BELT_TICKS = 30;

  const order = STATIONS.map((s) => s.id);

  function idxOf(id) { return order.indexOf(id); }

  function spawnTicket() {
    const k = pick(TICKET_KINDS);
    const t = {
      id: 'T-' + newId(),
      kind: k.kind, label: k.label, glyph: k.glyph,
      created: tick,
      stationIdx: 0,
      // Position: 'queue' | 'work' | 'belt'
      pos: 'queue',
      beltFrom: null, beltTo: null, beltProg: 0,
      history: [{ at: tick, what: 'created', where: 'intake' }],
    };
    tickets.set(t.id, t);
    stations.intake.queue.push(t);
    pushLog(`Spawned ${t.id} → INTAKE`);
  }

  function pushLog(s) {
    log.unshift({ at: tick, msg: s });
    if (log.length > 12) log.pop();
  }

  function chooseAgent(st) {
    // Find the first idle agent based on strategy
    const idle = st.agents.filter((a) => !a.ticket);
    if (idle.length === 0) return null;
    if (strategy === 'round') {
      // Rotate
      st._rr = ((st._rr || 0) + 1) % st.agents.length;
      // Find next idle starting from rr
      for (let i = 0; i < st.agents.length; i++) {
        const a = st.agents[(st._rr + i) % st.agents.length];
        if (!a.ticket) return a;
      }
      return idle[0];
    }
    if (strategy === 'priority') {
      // Lowest completed-count first (give junior agents work)
      return idle.sort((a, b) => a.completed - b.completed)[0];
    }
    // 'load' — least busy lifetime workload (most balanced over time)
    return idle.sort((a, b) => a.completed - b.completed)[0];
  }

  function moveToBelt(t, fromIdx, toIdx) {
    t.pos = 'belt';
    t.beltFrom = fromIdx;
    t.beltTo = toIdx;
    t.beltProg = 0;
    inFlight.push(t);
    t.history.push({ at: tick, what: 'belt', from: order[fromIdx], to: order[toIdx] });
  }

  function step() {
    tick++;

    // Spawn
    if (tick - lastSpawn >= spawnEvery) {
      lastSpawn = tick;
      spawnTicket();
    }

    // Belts advance
    for (let i = inFlight.length - 1; i >= 0; i--) {
      const t = inFlight[i];
      t.beltProg++;
      if (t.beltProg >= BELT_TICKS) {
        // Arrive at toIdx
        const dest = order[t.beltTo];
        stations[dest].queue.push(t);
        t.pos = 'queue';
        t.stationIdx = t.beltTo;
        t.beltFrom = null; t.beltTo = null; t.beltProg = 0;
        t.history.push({ at: tick, what: 'arrived', where: dest });
        inFlight.splice(i, 1);
      }
    }

    // Stations: assign queue → idle agents, advance work, dispatch finished
    STATIONS.forEach((sdef, idx) => {
      const st = stations[sdef.id];

      // Assign
      while (st.queue.length > 0) {
        const a = chooseAgent(st);
        if (!a) break;
        const t = st.queue.shift();
        a.ticket = t;
        a.progress = 0;
        a.total = Math.round(rand(sdef.work[0], sdef.work[1]));
        t.pos = 'work';
        t.history.push({ at: tick, what: 'picked', where: sdef.id, agent: a.id });
        if (idx === 0) pushLog(`${a.id} picked ${t.id}`);
      }

      // Work
      st.agents.forEach((a) => {
        if (!a.ticket) return;
        a.progress++;
        if (a.progress >= a.total) {
          const t = a.ticket;
          a.completed++;
          a.ticket = null;
          a.progress = 0;
          a.total = 0;
          st.throughput++;
          st.recentFinishes.push(tick);
          // trim recent to last 600 ticks
          while (st.recentFinishes.length && st.recentFinishes[0] < tick - 600) {
            st.recentFinishes.shift();
          }
          // Route
          if (idx < order.length - 1) {
            // 5% chance test sends back to code as rework
            if (sdef.id === 'test' && Math.random() < 0.08) {
              moveToBelt(t, idx, idxOf('code'));
              pushLog(`Rework: ${t.id} → CODE`);
            } else if (sdef.id === 'review' && Math.random() < 0.05) {
              moveToBelt(t, idx, idxOf('code'));
              pushLog(`Reject: ${t.id} → CODE`);
            } else {
              moveToBelt(t, idx, idx + 1);
            }
          } else {
            // SHIP
            t.pos = 'done';
            t.shippedAt = tick;
            const cycle = tick - t.created;
            st.cycleSamples.push(cycle);
            if (st.cycleSamples.length > 30) st.cycleSamples.shift();
            shipped.push(t);
            tickets.delete(t.id);
            pushLog(`Shipped ${t.id} (${cycle}t)`);
          }
        }
      });
    });
  }

  function metrics() {
    const out = {};
    let maxQ = 0, bottleneck = null;
    STATIONS.forEach((sdef) => {
      const st = stations[sdef.id];
      const wip = st.agents.filter((a) => a.ticket).length;
      const cap = st.agents.length;
      const util = cap ? wip / cap : 0;
      // throughput per minute (assume 60 ticks/sec => 3600 t/min, but let's say 1 tick = 100ms)
      // We display rate as finishes in last 600 ticks / (600/60) min = finishes/10  (since 1 tick ~ 100ms => 600 ticks = 60s = 1 min)
      const rate = st.recentFinishes.length;
      const cyc = st.cycleSamples.length
        ? Math.round(st.cycleSamples.reduce((a, b) => a + b, 0) / st.cycleSamples.length)
        : null;
      out[sdef.id] = {
        queue: st.queue.length,
        wip, cap, util,
        rate, // tasks/min approx
        finished: st.throughput,
        cycle: cyc,
      };
      const score = st.queue.length + (cap ? wip / cap : 0) * 2;
      if (score > maxQ) { maxQ = score; bottleneck = sdef.id; }
    });
    // Bottleneck only flagged if queue > 2
    if (out[bottleneck] && out[bottleneck].queue < 3) bottleneck = null;
    return { stations: out, bottleneck, tick, shipped: shipped.length };
  }

  function snapshot() {
    return {
      tick,
      stations: STATIONS.map((sdef) => {
        const st = stations[sdef.id];
        return {
          id: sdef.id,
          name: sdef.name,
          short: sdef.short,
          color: sdef.color,
          queue: st.queue.map((t) => ({ id: t.id, kind: t.kind, glyph: t.glyph, label: t.label })),
          agents: st.agents.map((a) => ({
            id: a.id,
            busy: !!a.ticket,
            progress: a.total ? a.progress / a.total : 0,
            ticket: a.ticket ? {
              id: a.ticket.id, kind: a.ticket.kind, glyph: a.ticket.glyph, label: a.ticket.label,
            } : null,
            completed: a.completed,
          })),
        };
      }),
      belts: inFlight.map((t) => ({
        id: t.id, kind: t.kind, glyph: t.glyph, label: t.label,
        from: t.beltFrom, to: t.beltTo, prog: t.beltProg / BELT_TICKS,
      })),
      log: log.slice(),
      metrics: metrics(),
    };
  }

  function setStrategy(s) { /* re-bind */ Object.defineProperty(this, 'strategy', { value: s }); }
  function reconfigureAgents(per) {
    STATIONS.forEach((sdef) => {
      const st = stations[sdef.id];
      const want = per[sdef.id] || 1;
      const have = st.agents.length;
      if (want > have) {
        for (let i = have; i < want; i++) {
          st.agents.push({ id: `${sdef.id}-a${i + 1}`, ticket: null, progress: 0, total: 0, completed: 0 });
        }
      } else if (want < have) {
        // Remove from end; if busy, return ticket to queue
        while (st.agents.length > want) {
          const a = st.agents.pop();
          if (a.ticket) { st.queue.unshift(a.ticket); a.ticket.pos = 'queue'; }
        }
      }
    });
  }

  return {
    STATIONS, TICKET_KINDS,
    step, snapshot, metrics, reconfigureAgents,
    setStrategy(s) { strategy && (opts.strategy = s); _strategy.value = s; },
    get strategy() { return _strategy.value; },
  };
}

// Strategy mutable holder so we can swap at runtime
const _strategy = { value: 'load' };

// Wrap createSim to use the holder
function makeSim(opts = {}) {
  _strategy.value = opts.strategy || 'load';
  // Patch chooseAgent to read from _strategy
  const sim = (function build() {
    const agentsPerStation = opts.agentsPerStation || {
      intake: 1, plan: 2, code: 3, test: 1, review: 1, ship: 1,
    };
    const spawnEvery = opts.spawnEvery || 22;

    const stations = {};
    STATIONS.forEach((s) => {
      stations[s.id] = {
        ...s,
        queue: [],
        agents: Array.from({ length: agentsPerStation[s.id] || 1 }, (_, i) => ({
          id: `${s.id}-a${i + 1}`, ticket: null, progress: 0, total: 0, completed: 0,
        })),
        throughput: 0,
        recentFinishes: [],
        cycleSamples: [],
        _rr: 0,
      };
    });

    const inFlight = [];
    const log = [];
    const shipped = [];
    let tick = 0;
    let lastSpawn = 0;
    const BELT_TICKS = 36;
    const order = STATIONS.map((s) => s.id);
    const idxOf = (id) => order.indexOf(id);

    function pushLog(s) {
      log.unshift({ at: tick, msg: s });
      if (log.length > 14) log.pop();
    }

    function chooseAgent(st) {
      const idle = st.agents.filter((a) => !a.ticket);
      if (idle.length === 0) return null;
      const strat = _strategy.value;
      if (strat === 'round') {
        st._rr = (st._rr + 1) % st.agents.length;
        for (let i = 0; i < st.agents.length; i++) {
          const a = st.agents[(st._rr + i) % st.agents.length];
          if (!a.ticket) return a;
        }
        return idle[0];
      }
      if (strat === 'priority') {
        // priority: tickets with longest wait first; but that's about queue. For agents, just first idle.
        return idle[0];
      }
      // load: least completed
      return idle.slice().sort((a, b) => a.completed - b.completed)[0];
    }

    function spawn() {
      const k = pick(TICKET_KINDS);
      const t = {
        id: 'T-' + newId(),
        kind: k.kind, label: k.label, glyph: k.glyph,
        created: tick, stationIdx: 0, pos: 'queue',
        beltFrom: null, beltTo: null, beltProg: 0,
      };
      stations.intake.queue.push(t);
    }

    function moveBelt(t, fromIdx, toIdx) {
      t.pos = 'belt';
      t.beltFrom = fromIdx; t.beltTo = toIdx; t.beltProg = 0;
      inFlight.push(t);
    }

    function step() {
      tick++;
      if (tick - lastSpawn >= spawnEvery) { lastSpawn = tick; spawn(); }

      for (let i = inFlight.length - 1; i >= 0; i--) {
        const t = inFlight[i];
        t.beltProg++;
        if (t.beltProg >= BELT_TICKS) {
          const dest = order[t.beltTo];
          stations[dest].queue.push(t);
          t.pos = 'queue';
          t.stationIdx = t.beltTo;
          t.beltFrom = null; t.beltTo = null; t.beltProg = 0;
          inFlight.splice(i, 1);
        }
      }

      STATIONS.forEach((sdef, idx) => {
        const st = stations[sdef.id];

        while (st.queue.length > 0) {
          const a = chooseAgent(st);
          if (!a) break;
          // priority strategy: sort queue by age first
          if (_strategy.value === 'priority') {
            st.queue.sort((x, y) => x.created - y.created);
          }
          const t = st.queue.shift();
          a.ticket = t;
          a.progress = 0;
          a.total = Math.round(rand(sdef.work[0], sdef.work[1]));
          t.pos = 'work';
        }

        st.agents.forEach((a) => {
          if (!a.ticket) return;
          a.progress++;
          if (a.progress >= a.total) {
            const t = a.ticket;
            a.completed++;
            a.ticket = null; a.progress = 0; a.total = 0;
            st.throughput++;
            st.recentFinishes.push(tick);
            while (st.recentFinishes.length && st.recentFinishes[0] < tick - 600) st.recentFinishes.shift();
            if (idx < order.length - 1) {
              if (sdef.id === 'test' && Math.random() < 0.08) {
                moveBelt(t, idx, idxOf('code'));
                pushLog(`✗ rework ${t.id} → CODE`);
              } else if (sdef.id === 'review' && Math.random() < 0.05) {
                moveBelt(t, idx, idxOf('code'));
                pushLog(`↺ reject ${t.id} → CODE`);
              } else {
                moveBelt(t, idx, idx + 1);
              }
            } else {
              t.pos = 'done'; t.shippedAt = tick;
              const cyc = tick - t.created;
              st.cycleSamples.push(cyc);
              if (st.cycleSamples.length > 30) st.cycleSamples.shift();
              shipped.push(t);
              pushLog(`✓ shipped ${t.id} • ${cyc}t cycle`);
            }
          }
        });
      });
    }

    function metrics() {
      const out = {};
      let bottleneck = null, worstScore = 0;
      STATIONS.forEach((sdef) => {
        const st = stations[sdef.id];
        const wip = st.agents.filter((a) => a.ticket).length;
        const cap = st.agents.length;
        const util = cap ? wip / cap : 0;
        const rate = st.recentFinishes.length; // ~ per minute if 1 tick=100ms
        const cyc = st.cycleSamples.length
          ? Math.round(st.cycleSamples.reduce((a, b) => a + b, 0) / st.cycleSamples.length)
          : null;
        out[sdef.id] = { queue: st.queue.length, wip, cap, util, rate, finished: st.throughput, cycle: cyc };
        const score = st.queue.length * 2 + util * 3;
        if (score > worstScore && st.queue.length >= 3) { worstScore = score; bottleneck = sdef.id; }
      });
      return { stations: out, bottleneck, tick, shipped: shipped.length };
    }

    function snapshot() {
      return {
        tick,
        stations: STATIONS.map((sdef) => {
          const st = stations[sdef.id];
          return {
            id: sdef.id, name: sdef.name, short: sdef.short, color: sdef.color,
            queue: st.queue.map((t) => ({ id: t.id, kind: t.kind, glyph: t.glyph, label: t.label, age: tick - t.created })),
            agents: st.agents.map((a) => ({
              id: a.id, busy: !!a.ticket,
              progress: a.total ? a.progress / a.total : 0,
              ticket: a.ticket ? { id: a.ticket.id, kind: a.ticket.kind, glyph: a.ticket.glyph, label: a.ticket.label } : null,
              completed: a.completed,
            })),
          };
        }),
        belts: inFlight.map((t) => ({
          id: t.id, kind: t.kind, glyph: t.glyph, label: t.label,
          from: t.beltFrom, to: t.beltTo, prog: t.beltProg / BELT_TICKS,
        })),
        log: log.slice(),
        metrics: metrics(),
      };
    }

    function reconfigureAgents(per) {
      STATIONS.forEach((sdef) => {
        const st = stations[sdef.id];
        const want = Math.max(1, per[sdef.id] || 1);
        while (st.agents.length < want) {
          st.agents.push({ id: `${sdef.id}-a${st.agents.length + 1}`, ticket: null, progress: 0, total: 0, completed: 0 });
        }
        while (st.agents.length > want) {
          const a = st.agents.pop();
          if (a.ticket) { st.queue.unshift(a.ticket); a.ticket.pos = 'queue'; }
        }
      });
    }

    return { STATIONS, step, snapshot, reconfigureAgents };
  })();

  return sim;
}

window.makeSim = makeSim;
window.STATIONS = STATIONS;
window.TICKET_KINDS = TICKET_KINDS;
window._strategy = _strategy;
