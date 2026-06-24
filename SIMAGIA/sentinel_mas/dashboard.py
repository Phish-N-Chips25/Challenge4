"""Web dashboard for SentinelMAS.

Runs inside the MAS process (same asyncio loop / SPADE container), so it reads
agent state directly and injects events in-memory — no second XMPP client.

Enabled by launching:  python main.py --web
Then open the printed URL (default http://localhost:8080) in a browser.

Exposes:
    GET  /            -> the dashboard page (self-contained HTML/JS)
    GET  /api/state   -> live JSON state (zones, patrol, log)
    POST /api/inject  -> {"zone": "...", "choice": "4"|"c"} inject an event/scenario
"""

import asyncio

from aiohttp import web
from spade.agent import Agent
from spade.behaviour import CyclicBehaviour

from config import settings
from utils import build_msg
from utils.messaging import INFORM
from agents.console_injector import EVENTS, SCENARIOS
import dashboard_log


# ════════════════════════════════════════════════════════════
#  In-process injector driven by the web UI
# ════════════════════════════════════════════════════════════

class WebInjectorAgent(Agent):
    """Receives (zone, [event_keys]) from the web layer and emits the
    corresponding INFORM messages into the container."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.queue: asyncio.Queue = asyncio.Queue()

    async def enqueue(self, zone: str, keys: list[str]):
        await self.queue.put((zone, keys))

    class Drain(CyclicBehaviour):
        async def run(self):
            try:
                zone, keys = await asyncio.wait_for(self.agent.queue.get(), timeout=1)
            except asyncio.TimeoutError:
                return
            for k in keys:
                ev = EVENTS[k]
                body = {"event": ev["event"], "zone": zone, **ev["extra"]}
                await self.send(build_msg(
                    settings.ZONE_COORDINATOR_JIDS[zone], INFORM, body))
                dashboard_log.push("Injector", f"{ev['event']} -> {zone}")
                await asyncio.sleep(0.05)

    async def setup(self):
        self.add_behaviour(self.Drain())


# ════════════════════════════════════════════════════════════
#  Coordinate projection: Webots metres → SVG viewBox (0..100)
# ════════════════════════════════════════════════════════════
# ZONE_POS / patrol.pos are now in Webots metres (x∈[-10,10], y∈[-6,6], y-up).
# The dashboard SVG draws on a 0..100 grid with y growing DOWN, so project the
# bounding box of all zones+base into [pad, 100-pad] and flip y. Derived from
# the actual positions, so it adapts to any layout with no hardcoded numbers.

def _load_walls_raw():
    """Wall segments (metres) from the RL office_map — the SAME geometry the
    path planner uses, parsed from the .wbt. Soft-fails to [] (schematic only)
    if the RL stack isn't importable here."""
    try:
        import sys
        if settings.RL_DIR not in sys.path:
            sys.path.insert(0, settings.RL_DIR)
        from office_map import WALLS
        return [tuple(map(float, w)) for w in WALLS]
    except Exception as e:
        print(f"[dashboard] wall geometry unavailable ({e!r}); drawing schematic only.")
        return []


_WALLS_RAW = _load_walls_raw()


def _make_projector():
    # Base the projection on the WALLS extent (true building bounds) so the whole
    # floor plan fits; fall back to zones+base if no walls are available.
    pts = list(settings.ZONE_POS.values()) + [tuple(settings.PATROL_BASE_POS)]
    for (x1, y1, x2, y2) in _WALLS_RAW:
        pts.append((x1, y1))
        pts.append((x2, y2))
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    xmin, xmax, ymin, ymax = min(xs), max(xs), min(ys), max(ys)
    padx = (xmax - xmin) * 0.04 or 1.0
    pady = (ymax - ymin) * 0.04 or 1.0
    xmin, xmax = xmin - padx, xmax + padx
    ymin, ymax = ymin - pady, ymax + pady

    def project(x, y):
        sx = (x - xmin) / (xmax - xmin) * 100.0
        sy = (1.0 - (y - ymin) / (ymax - ymin)) * 100.0   # flip: metre y-up → svg y-down
        return round(sx, 2), round(sy, 2)
    return project


_PROJECT = _make_projector()
# Project the static wall segments once.
_PROJECTED_WALLS = [[*_PROJECT(x1, y1), *_PROJECT(x2, y2)]
                    for (x1, y1, x2, y2) in _WALLS_RAW]


# ════════════════════════════════════════════════════════════
#  State + HTTP handlers
# ════════════════════════════════════════════════════════════

def _build_state(zcs: dict, patrol) -> dict:
    zones = []
    for zid in settings.ZONES:
        zc = zcs.get(zid)
        b = zc.beliefs if zc else None
        get = (lambda k, d=None: b.get(k, d)) if b else (lambda k, d=None: d)
        px, py = _PROJECT(*settings.ZONE_POS.get(zid, (0, 0)))
        zones.append({
            "zone": zid,
            "threat": get("threat_level", 0) or 0,
            "interpretation": get("interpretation", "clear"),
            "cyber": bool(get("cyber_anomaly", False)),
            "physical": bool(get("physical_presence", False)),
            "unknown": bool(get("unknown_face", False)),
            "authorized": bool(get("last_identity")) and not get("unknown_face"),
            "patrol_status": get("patrol_status"),
            "motion_count": get("motion_count", 0) or 0,
            "modalities": sorted(settings.ZONE_MODALITIES.get(zid, [])),
            "x": px, "y": py,
        })
    rpos = getattr(patrol, "pos", settings.PATROL_BASE_POS)
    rx, ry = _PROJECT(rpos[0], rpos[1])
    bx, by = _PROJECT(*settings.PATROL_BASE_POS)
    return {
        "zones": zones,
        "patrol": {
            "busy": bool(getattr(patrol, "busy", False)),
            "zone": getattr(patrol, "current_zone", None),
            "phase": getattr(patrol, "phase", "idle"),
            "x": rx, "y": ry,
            "last_auction": getattr(patrol, "last_auction", None),
        },
        "base": {"x": bx, "y": by},
        "walls": _PROJECTED_WALLS,
        "log": dashboard_log.snapshot(60),
        "events": {k: v["label"] for k, v in EVENTS.items()},
        "scenarios": {k: v["label"] for k, v in SCENARIOS.items()},
    }


async def _state(request):
    return web.json_response(_build_state(request.app["zcs"], request.app["patrol"]))


async def _inject(request):
    data = await request.json()
    zone = data.get("zone")
    choice = str(data.get("choice", "")).lower()
    if zone not in settings.ZONES:
        return web.json_response({"error": "unknown zone"}, status=400)
    if choice in EVENTS:
        keys = [choice]
    elif choice in SCENARIOS:
        keys = SCENARIOS[choice]["events"]
    else:
        return web.json_response({"error": "unknown choice"}, status=400)
    await request.app["injector"].enqueue(zone, keys)
    return web.json_response({"ok": True})


async def _index(request):
    return web.Response(text=PAGE, content_type="text/html")


async def start_dashboard(zcs: dict, patrol, injector, host="localhost", port=8080):
    app = web.Application()
    app["zcs"] = zcs
    app["patrol"] = patrol
    app["injector"] = injector
    app.router.add_get("/", _index)
    app.router.add_get("/api/state", _state)
    app.router.add_post("/api/inject", _inject)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    return runner


# ════════════════════════════════════════════════════════════
#  The page (self-contained)
# ════════════════════════════════════════════════════════════

PAGE = r"""<!doctype html>
<html lang="pt">
<head>
<meta charset="utf-8">
<title>SentinelMAS Dashboard</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin: 0; font-family: ui-sans-serif, system-ui, Segoe UI, Roboto, sans-serif;
         background: #0f1115; color: #e6e6e6; }
  header { padding: 12px 20px; background: #161922; border-bottom: 1px solid #262b38;
           display: flex; align-items: center; gap: 16px; }
  header h1 { font-size: 18px; margin: 0; font-weight: 600; }
  header .sub { color: #8b93a7; font-size: 13px; }
  main { display: grid; grid-template-columns: 1fr 340px; gap: 16px; padding: 16px; }
  .col { display: flex; flex-direction: column; gap: 16px; min-width: 0; }
  .panel { background: #161922; border: 1px solid #262b38; border-radius: 12px; padding: 14px; }
  .panel h3 { margin: 0 0 10px; font-size: 14px; color: #b8c0d4; }
  /* map */
  #map { width: 100%; aspect-ratio: 1/1; background: #0c0e13; border-radius: 10px;
         border: 1px solid #222838; }
  .room { transition: fill .4s, stroke .4s; }
  .roomlbl { font: 600 3px ui-sans-serif, sans-serif; fill: #e8ecf6; text-anchor: middle; }
  .roomth  { font: 700 2.4px ui-sans-serif, sans-serif; text-anchor: middle; }
  .wall { stroke: #6b7488; stroke-width: 0.9; stroke-linecap: round; }
  #robot { transition: transform .6s linear; }
  #robot.moving .ring { animation: pulse 1s ease-out infinite; }
  @keyframes pulse { from { r: 3; opacity:.7 } to { r: 7; opacity:0 } }
  /* zone cards */
  .zones { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px,1fr)); gap: 12px; }
  .card { background: #161922; border: 1px solid #262b38; border-radius: 12px; padding: 12px;
          border-left: 6px solid #2e7d32; }
  .card h2 { margin: 0 0 2px; font-size: 15px; text-transform: capitalize; }
  .mods { color: #8b93a7; font-size: 10px; letter-spacing: .04em; text-transform: uppercase; margin-bottom: 8px; }
  .threat { display: inline-block; padding: 2px 9px; border-radius: 999px; font-weight: 700; font-size: 11px; color: #fff; }
  .interp { font-size: 12px; color: #c8cee0; margin: 7px 0; min-height: 16px; }
  .chips { display: flex; flex-wrap: wrap; gap: 5px; margin-bottom: 8px; }
  .chip { font-size: 10px; padding: 2px 7px; border-radius: 6px; border: 1px solid #2b3142; background: #1d2230; color: #9aa3b8; }
  .chip.cyber.on { background: #6a1b9a; border-color: #8e24aa; color:#fff; }
  .chip.presence.on { background: #1565c0; border-color: #1976d2; color:#fff; }
  .chip.unknown.on { background: #c62828; border-color: #e53935; color:#fff; }
  .chip.auth.on { background: #2e7d32; border-color: #43a047; color:#fff; }
  .btns { display: flex; flex-wrap: wrap; gap: 4px; }
  .btns button { font-size: 11px; padding: 3px 8px; border-radius: 6px; cursor: pointer;
                 background: #232838; color: #d6dbe8; border: 1px solid #313749; }
  .btns button:hover { background: #2d3447; }
  .btns button.sc { background: #2a2140; border-color: #4a3a78; }
  .btns .sep { width: 100%; height: 0; }
  .robot { font-size: 14px; } .robot .big { font-size: 15px; font-weight: 700; }
  .bids { font-family: ui-monospace, monospace; font-size: 12px; color: #c8cee0; margin-top: 6px; }
  .log { height: 38vh; overflow-y: auto; font-family: ui-monospace, monospace; font-size: 12px; line-height: 1.5; }
  .log .ln { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .src { display: inline-block; min-width: 92px; color: #7d8597; }
  .src.alert { color: #ff5252; font-weight: 700; } .src.patrol { color: #ffca28; }
  .src.injector { color: #66bb6a; } .src.zc { color: #29b6f6; }
</style>
</head>
<body>
<header><h1>SentinelMAS</h1><span class="sub" id="sub">a ligar…</span></header>
<main>
  <div class="col">
    <div class="panel">
      <h3>Planta — robô de patrulha</h3>
      <svg id="map" viewBox="0 0 100 100" preserveAspectRatio="xMidYMid meet"></svg>
    </div>
    <section class="zones" id="zones"></section>
  </div>
  <div class="col">
    <div class="panel">
      <h3>Robô</h3>
      <div class="robot" id="robotinfo">—</div>
      <div class="bids" id="auction"></div>
    </div>
    <div class="panel">
      <h3>Timeline</h3>
      <div class="log" id="log"></div>
    </div>
  </div>
</main>
<script>
const THREAT = {
  0:{l:"LOW",c:"#2e7d32"}, 1:{l:"MEDIUM",c:"#f9a825"},
  2:{l:"HIGH",c:"#ef6c00"}, 3:{l:"CRITICAL",c:"#c62828"} };
let EVENTS = {}, SCENARIOS = {}, mapBuilt = false;

async function inject(zone, choice) {
  await fetch("/api/inject", {method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({zone, choice})});
}

function buildMap(s) {
  const svg = document.getElementById("map");
  let h = "";
  // actual office walls (real floor plan, from the .wbt geometry the planner uses)
  (s.walls || []).forEach(w => {
    h += `<line class="wall" x1="${w[0]}" y1="${w[1]}" x2="${w[2]}" y2="${w[3]}"/>`;
  });
  // zone markers (threat-coloured dot + label + level), placed at zone centres
  s.zones.forEach(z => {
    h += `<circle id="rm-${z.zone}" class="room" cx="${z.x}" cy="${z.y}" r="1.8"
            fill="#2e7d32" stroke="#0c0e13" stroke-width="0.4"/>
          <text class="roomlbl" x="${z.x}" y="${z.y-2.6}">${z.zone.replace("_"," ")}</text>
          <text class="roomth" id="th-${z.zone}" x="${z.x}" y="${z.y+4}" fill="#2e7d32">LOW</text>`;
  });
  // base marker
  h += `<circle cx="${s.base.x}" cy="${s.base.y}" r="1.4" fill="#39405a"/>`;
  h += `<rect x="${s.base.x-3}" y="${s.base.y-3}" width="6" height="6" rx="1" fill="none" stroke="#39405a" stroke-width="0.5"/>`;
  h += `<text x="${s.base.x}" y="${s.base.y+5}" class="roomth" fill="#5b647d">base</text>`;
  // robot (kept as a persistent node so CSS transition animates movement)
  h += `<g id="robot" transform="translate(${s.patrol.x},${s.patrol.y})">
          <circle class="ring" r="3" fill="none" stroke="#ffca28" stroke-width="0.6"/>
          <circle r="2.4" fill="#ffca28" stroke="#7a5b00" stroke-width="0.4"/>
          <text id="robotph" y="-4" class="roomth" fill="#ffca28">idle</text>
        </g>`;
  svg.innerHTML = h;
  mapBuilt = true;
}

function updateMap(s) {
  s.zones.forEach(z => {
    const t = THREAT[z.threat] || THREAT[0];
    const rm = document.getElementById("rm-"+z.zone);
    const th = document.getElementById("th-"+z.zone);
    if (rm) { rm.setAttribute("fill", t.c); }
    if (th) { th.textContent = t.l; th.setAttribute("fill", t.c); }
  });
  const robot = document.getElementById("robot");
  if (robot) {
    robot.setAttribute("transform", `translate(${s.patrol.x},${s.patrol.y})`);
    robot.classList.toggle("moving", s.patrol.phase==="traveling"||s.patrol.phase==="returning");
    const ph = document.getElementById("robotph");
    if (ph) ph.textContent = s.patrol.phase;
  }
}

function zoneCard(z) {
  const t = THREAT[z.threat] || THREAT[0];
  const div = document.createElement("div");
  div.className = "card"; div.style.borderLeftColor = t.c;
  const ev = Object.keys(EVENTS).map(k =>
    `<button onclick="inject('${z.zone}','${k}')" title="${EVENTS[k]}">${k}</button>`).join("");
  const sc = Object.keys(SCENARIOS).map(k =>
    `<button class="sc" onclick="inject('${z.zone}','${k}')" title="${SCENARIOS[k]}">${k}</button>`).join("");
  div.innerHTML = `
    <h2>${z.zone.replace("_"," ")}</h2>
    <div class="mods">${z.modalities.join(" · ") || "—"}</div>
    <span class="threat" style="background:${t.c}">${t.l}</span>
    <div class="interp">${z.interpretation || ""}</div>
    <div class="chips">
      <span class="chip cyber ${z.cyber?"on":""}">cyber</span>
      <span class="chip presence ${z.physical?"on":""}">presence</span>
      <span class="chip unknown ${z.unknown?"on":""}">unknown</span>
      <span class="chip auth ${z.authorized?"on":""}">authorized</span></div>
    <div class="btns">${ev}<span class="sep"></span>${sc}</div>`;
  return div;
}

function render(s) {
  EVENTS = s.events; SCENARIOS = s.scenarios;
  document.getElementById("sub").textContent =
    s.zones.length + " zonas · robô " + (s.patrol.busy ? s.patrol.phase : "livre");
  if (!mapBuilt) buildMap(s);
  updateMap(s);

  const zc = document.getElementById("zones"); zc.innerHTML = "";
  s.zones.forEach(z => zc.appendChild(zoneCard(z)));

  const p = s.patrol;
  document.getElementById("robotinfo").innerHTML = p.busy
    ? `<span class="big" style="color:#ffca28">${p.phase.toUpperCase()}${p.zone?(" → "+p.zone):""}</span>`
    : `<span class="big" style="color:#66bb6a">LIVRE</span>`;
  const a = p.last_auction;
  document.getElementById("auction").innerHTML = a
    ? `leilão #${a.id} · vencedor <b>${a.winner}</b><br>bids: ` + a.bids.map(b=>`${b[0]}=${b[1]}`).join(", ")
    : "sem leilões ainda";

  const log = document.getElementById("log");
  const atBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 40;
  log.innerHTML = s.log.map(e => {
    const cls = e.source.toLowerCase().startsWith("zc") ? "zc" : e.source.toLowerCase();
    return `<div class="ln"><span class="src ${cls}">${e.source}</span> ${e.text}</div>`;
  }).join("");
  if (atBottom) log.scrollTop = log.scrollHeight;
}

async function tick() {
  try { const r = await fetch("/api/state"); render(await r.json()); }
  catch (e) { document.getElementById("sub").textContent = "desligado"; }
}
setInterval(tick, 600);
tick();
</script>
</body>
</html>
"""
