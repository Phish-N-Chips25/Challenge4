"""SentinelMAS — Webots live dashboard.

Starts the full SPADE MAS (WEBOTS_ENABLED=True) and exposes a per-room
dashboard at http://localhost:8081 that mirrors the 7 physical rooms of
the Webots world (lobby, break_room, work_room 1-4, datacenter).

Usage:
    cd SIMAGIA/sentinel_mas
    python webots_dashboard.py

Then launch Webots and press Play.
"""

import asyncio
import json
import os
import sys
from collections import deque
from contextlib import suppress
from datetime import datetime

import loguru
import numpy as np

# alt1.py lives one level up (SIMAGIA/)
_SIMAGIA = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _SIMAGIA not in sys.path:
    sys.path.insert(0, _SIMAGIA)

from alt1 import validar_pessoa_detalhes, precarregar_recursos_alt1
from aiohttp import web
from pyjabber.server import Server, Parameters
from spade.container import Container

from bridges import WebotsBridge
from config import settings
from agents import (
    ZoneCoordinatorAgent, PatrolAgent, MotionAgent, FaceIDAgent,
    CyberSentinelAgent, StaffRequestAgent, AlertAgent,
)
import dashboard_log

PORT = 8081

# ── Room definitions (Webots physical rooms) ───────────────────────────────

WEBOTS_ROOMS = [
    "lobby", "break_room",
    "work_room_1", "work_room_2", "work_room_3", "work_room_4",
    "datacenter",
]

_ROOM_LABEL = {
    "lobby":       "Lobby",
    "checkpoint":  "Lobby",
    "break_room":  "Break Room",
    "work_room_1": "Sala de Trabalho 1",
    "work_room_2": "Sala de Trabalho 2",
    "work_room_3": "Sala de Trabalho 3",
    "work_room_4": "Sala de Trabalho 4",
    "datacenter":  "Datacenter",
    "server_room": "Datacenter",
}

# Webots room → MAS zone (for threat level lookup and bridge injection)
_ROOM_TO_MAS = {
    "lobby":       "lobby",
    "break_room":  "exterior",
    "work_room_1": "work_room_1",
    "work_room_2": "work_room_2",
    "work_room_3": "work_room_3",
    "work_room_4": "work_room_4",
    "datacenter":  "server_room",
}

# Rooms that support manual cyber-attack injection from the dashboard.
# Datacenter has physical rack LEDs; work rooms trigger ZC:lab dispatch.
_CYBER_ROOMS = {"datacenter", "work_room_1", "work_room_2", "work_room_3", "work_room_4"}

# ── State ──────────────────────────────────────────────────────────────────

_room_events: dict[str, deque] = {r: deque(maxlen=8) for r in WEBOTS_ROOMS}
_activity:    deque             = deque(maxlen=150)
_bridge:      WebotsBridge | None = None
_zcs:         dict              = {}
_patrol:      PatrolAgent | None  = None


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _log(kind: str, text: str) -> None:
    _activity.appendleft({"ts": _ts(), "kind": kind, "text": text})


def _push(webots_room: str, event: dict) -> None:
    """Record a Webots event and emit a human-readable terminal line."""
    if webots_room in _room_events:
        _room_events[webots_room].appendleft({**event, "_ts": _ts()})

    label = _ROOM_LABEL.get(webots_room, webots_room)
    ev    = event.get("event", "")

    if ev == "motion_detected":
        _log("motion", f"Movimento detectado em {label}")
    elif ev == "face_detected":
        identity = event.get("identity", "?")
        conf     = int(event.get("confidence", 0) * 100)
        if identity == "unknown":
            _log("alert", f"Pessoa NÃO reconhecida em {label} (conf. {conf}%)")
        else:
            _log("ok", f"Pessoa identificada: {identity} em {label} (conf. {conf}%)")
    elif ev == "cyber_anomaly":
        score  = event.get("score", "?")
        source = event.get("source", "?")
        _log("cyber", f"Anomalia cyber em {label} — score {score} [{source}]")
    elif ev == "patrol_report":
        status = event.get("status", "?")
        if status == "clear":
            _log("ok", f"Patrulha: {label} está LIMPA")
        elif status == "intruder_confirmed":
            _log("critical", f"Patrulha: INTRUSO CONFIRMADO em {label}!")
        else:
            _log("info", f"Patrulha: {label} — {status}")


# ── HTTP handlers ──────────────────────────────────────────────────────────

async def handle_root(request):
    return web.Response(text=_HTML, content_type="text/html")


async def handle_state(request):
    rooms = {}
    for room in WEBOTS_ROOMS:
        mas_zone = _ROOM_TO_MAS[room]
        zc       = _zcs.get(mas_zone)
        threat   = 0
        snap     = {}
        if zc:
            try:
                threat = int(zc.beliefs.get("threat_level") or 0)
                snap   = zc.beliefs.snapshot()
            except Exception:
                pass
        rooms[room] = {
            "label":    _ROOM_LABEL[room],
            "mas_zone": mas_zone,
            "threat":   threat,
            "beliefs":  snap,
            "events":   list(_room_events[room]),
        }

    patrol_info = {}
    if _patrol:
        patrol_info = {
            "phase": _patrol.phase,
            "zone":  _patrol.current_zone,
        }

    return web.json_response({
        "rooms":    rooms,
        "patrol":   patrol_info,
        "activity": list(_activity),
        "mas_log":  list(reversed(dashboard_log.snapshot(20))),
    })


async def handle_webots_event(request):
    """Receives sensor events from security_supervisor.
    Expects: {..., 'zone': <mas_zone>, 'webots_zone': <raw room name>}
    """
    try:
        data = await request.json()
    except Exception:
        return web.Response(status=400, text="bad json")

    mas_zone    = data.get("zone", "")
    webots_room = data.get("webots_zone", mas_zone)

    if mas_zone not in settings.ZONES:
        return web.Response(status=422, text=f"unknown mas zone: {mas_zone!r}")

    _push(webots_room, data)
    if _bridge:
        _bridge.put_sensor_event({**data, "zone": mas_zone})

    return web.Response(text="ok")


async def handle_cyber(request):
    """Manual cyber attack from dashboard UI — datacenter and work rooms."""
    try:
        data = await request.json()
    except Exception:
        return web.Response(status=400, text="bad json")

    room  = data.get("room", "datacenter")
    score = float(data.get("score", 0.92))

    if room not in _CYBER_ROOMS:
        return web.Response(status=422, text=f"{room} has no cyber sensor")

    mas_zone = _ROOM_TO_MAS[room]
    event = {
        "type": "sensor", "event": "cyber_anomaly",
        "zone": mas_zone, "webots_zone": room,
        "score": score, "source": "manual",
    }
    _push(room, event)
    if _bridge:
        _bridge.put_sensor_event(event)
        # Relay to Webots rack LED only for datacenter (work rooms have no rack LED)
        if room == "datacenter":
            _bridge.put_patrol_command({"action": "relay_cyber", "zone": room})
    _log("cyber", f"[MANUAL] Ataque cyber em {_ROOM_LABEL[room]} — score {score}")
    dashboard_log.push("Inject", f"cyber_anomaly score={score} → {mas_zone}")

    return web.Response(text="ok")


async def handle_patrol_cmd(request):
    if _bridge is None:
        return web.json_response(None)
    cmd = _bridge.get_patrol_command()
    return web.json_response(cmd)


async def handle_patrol_preempted(request):
    try:
        data = await request.json()
    except Exception:
        data = {}
    zone  = data.get("zone", "")
    label = _ROOM_LABEL.get(zone, _room_label_from_mas(zone))
    _log("alert", f"Patrulha REDIRECCIONADA — missão em {label} interrompida (prioridade mais alta)")
    return web.Response(text="ok")


async def handle_patrol_moving(request):
    try:
        data = await request.json()
    except Exception:
        return web.Response(status=400, text="bad json")
    zone  = data.get("zone", "?")
    label = _room_label_from_mas(zone)
    _log("robot", f"Robot de patrulha a deslocar-se para {label}…")
    return web.Response(text="ok")


async def handle_patrol_arrived(request):
    try:
        data = await request.json()
    except Exception:
        data = {}
    zone  = data.get("zone", "")
    label = _room_label_from_mas(zone)
    if label:
        _log("robot", f"Robot de patrulha chegou a {label}")
    if _bridge:
        _bridge.notify_arrived()
    return web.Response(text="ok")


async def handle_recognize_face(request):
    """Receives raw BGRA frame from face_id_agent and returns InsightFace result."""
    data = await request.read()
    if len(data) < 8:
        return web.json_response({"reason": "payload_too_small"})
    w = int.from_bytes(data[0:4], "big")
    h = int.from_bytes(data[4:8], "big")
    expected = w * h * 4
    if len(data) - 8 < expected:
        return web.json_response({"reason": "payload_incomplete"})
    bgra = np.frombuffer(data[8:8 + expected], dtype=np.uint8).reshape((h, w, 4))
    bgr  = bgra[:, :, :3]
    loop     = asyncio.get_event_loop()
    resultado = await loop.run_in_executor(None, validar_pessoa_detalhes, bgr)
    return web.json_response(resultado)


async def handle_scan_result(request):
    try:
        data = await request.json()
    except Exception:
        return web.Response(status=400, text="bad json")

    result      = data.get("result",      "clear")
    mas_zone    = data.get("zone",        "")
    webots_room = data.get("webots_zone", mas_zone)

    if _bridge:
        _bridge.put_scan_result(result)
        _bridge.put_sensor_event({
            "type": "sensor", "event": "patrol_report",
            "zone": mas_zone, "status": result,
        })
    if webots_room:
        _push(webots_room, {"event": "patrol_report", "status": result})

    return web.Response(text="ok")


def _room_label_from_mas(mas_zone: str) -> str:
    """Get a display label from a MAS zone name (patrol uses MAS zones)."""
    _mas_to_label = {
        "lobby":       "Lobby",
        "exterior":    "Break Room",
        "work_room_1": "Sala de Trabalho 1",
        "work_room_2": "Sala de Trabalho 2",
        "work_room_3": "Sala de Trabalho 3",
        "work_room_4": "Sala de Trabalho 4",
        "server_room": "Datacenter",
        "__base__":    "Base",
    }
    return _mas_to_label.get(mas_zone, mas_zone)


# ── Dashboard startup ──────────────────────────────────────────────────────

async def _start_dashboard(zcs, patrol, bridge, port=PORT):
    global _zcs, _patrol, _bridge
    _zcs    = zcs
    _patrol = patrol
    _bridge = bridge

    app = web.Application()
    app.router.add_get ("/",                     handle_root)
    app.router.add_get ("/api/state",            handle_state)
    app.router.add_post("/api/webots_event",     handle_webots_event)
    app.router.add_post("/api/cyber",            handle_cyber)
    app.router.add_get ("/api/patrol_cmd",       handle_patrol_cmd)
    app.router.add_post("/api/patrol_moving",    handle_patrol_moving)
    app.router.add_post("/api/patrol_arrived",   handle_patrol_arrived)
    app.router.add_post("/api/patrol_preempted", handle_patrol_preempted)
    app.router.add_post("/api/scan_result",      handle_scan_result)
    app.router.add_post("/api/recognize_face",   handle_recognize_face)

    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", port).start()
    print(f"Webots dashboard -> http://localhost:{port}", flush=True)
    return runner


# ── MAS coroutine ──────────────────────────────────────────────────────────

async def _mas_main():
    global _bridge

    # Pre-load InsightFace model + face DB before Webots connects
    print("[FaceRec] a carregar modelo InsightFace...", flush=True)
    loop = asyncio.get_event_loop()
    n = await loop.run_in_executor(None, precarregar_recursos_alt1)
    print(f"[FaceRec] BD com {n} pessoa(s) carregada.", flush=True)

    _bridge = WebotsBridge()

    settings.WEBOTS_ENABLED    = True
    settings.WEBOTS_BRIDGE     = _bridge
    settings.SIMULATED_SENSORS = False

    pwd  = settings.XMPP_PASSWORD
    port = settings.XMPP_PORT
    agents = []
    zcs    = {}

    for zone, jid in settings.ZONE_COORDINATOR_JIDS.items():
        zc = ZoneCoordinatorAgent(jid, pwd, zone_id=zone, port=port)
        zcs[zone] = zc
        agents.append(zc)

    patrol = PatrolAgent(settings.PATROL_JID, pwd, port=port)
    patrol.zone_coordinators = zcs   # direct in-process belief access (bypasses XMPP)
    agents.append(patrol)
    agents.append(MotionAgent       (settings.MOTION_JID,        pwd, port=port))
    agents.append(FaceIDAgent       (settings.FACEID_JID,        pwd, port=port))
    agents.append(CyberSentinelAgent(settings.CYBER_JID,         pwd, port=port))
    agents.append(StaffRequestAgent (settings.STAFF_REQUEST_JID, pwd, port=port))
    agents.append(AlertAgent        (settings.ALERT_JID,         pwd, port=port))

    for a in agents:
        await a.start(auto_register=True)

    runner = await _start_dashboard(zcs, patrol, _bridge)

    print("=" * 58, flush=True)
    print("SentinelMAS (Webots mode) ready", flush=True)
    print(f"  Dashboard : http://localhost:{PORT}", flush=True)
    print(f"  XMPP      : localhost:{settings.XMPP_PORT}", flush=True)
    print("=" * 58, flush=True)

    try:
        while True:
            await asyncio.sleep(1)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        if runner:
            await runner.cleanup()
        for a in agents:
            await a.stop()
        print("SentinelMAS stopped.", flush=True)


def run():
    container = Container()
    server    = None
    try:
        loguru.logger.remove()
        si = Server(Parameters(
            host="localhost",
            client_port=settings.XMPP_PORT,
            server_port=settings.XMPP_SERVER_PORT,
            database_in_memory=True,
        ))
        server = container.loop.create_task(si.start())
        container.run(si.ready.wait())
        print(f"XMPP up on :{settings.XMPP_PORT}", flush=True)
        container.run(_mas_main())

    except KeyboardInterrupt:
        print("\nStopping…")
    except SystemExit:
        print(f"\nERROR: porta {settings.XMPP_PORT} já em uso — fecha o SentinelMAS anterior.")
    except Exception:
        import traceback
        traceback.print_exc()

    container.stop_agents()
    if server:
        server.cancel()
        with suppress(Exception):
            container.run(server)
    for t in asyncio.all_tasks(loop=container.loop):
        t.cancel()
        with suppress(asyncio.CancelledError):
            container.run(t)
    container.loop.run_until_complete(container.loop.shutdown_asyncgens())
    container.loop.close()


# ── HTML ───────────────────────────────────────────────────────────────────

_HTML = """<!DOCTYPE html>
<html lang="pt">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SentinelMAS — Webots Live</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',sans-serif;background:#0d1117;color:#c9d1d9;min-height:100vh}
header{display:flex;align-items:center;justify-content:space-between;
       padding:12px 20px;border-bottom:1px solid #21262d;background:#010409}
h1{font-size:1.15em;letter-spacing:2px;color:#58a6ff}
#ts{font-size:.72em;color:#8b949e}

/* ── room grid ── */
.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;padding:14px}
.card{background:#161b22;border:1px solid #21262d;border-radius:8px;
      padding:12px;display:flex;flex-direction:column;gap:7px}
.card.wide{grid-column:span 2}
.card.full{grid-column:span 4}
.card-head{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:4px}
.card-title{font-size:.88em;font-weight:700;color:#f0f6fc}
.mas-tag{font-size:.6em;color:#484f58;margin-left:4px}
.badge{font-size:.63em;font-weight:700;padding:2px 8px;border-radius:10px;white-space:nowrap}
.t0{background:#1b3a1f;color:#56d364}
.t1{background:#4a3500;color:#e3b341}
.t2{background:#4a1f00;color:#f0883e}
.t3{background:#3d0000;color:#ff7b72}

/* beliefs */
.beliefs{font-size:.68em;color:#8b949e;line-height:1.6;min-height:16px}
.bv{color:#79c0ff}.bk{color:#8b949e}
.interp{color:#f0883e}

/* events */
.ev-list{font-size:.69em;display:flex;flex-direction:column;gap:2px;min-height:18px}
.ev{display:flex;gap:6px;align-items:baseline;padding:4px 0;border-bottom:1px solid #1a2233;line-height:1.5}
.ev:last-child{border:none}
.ev-ts{color:#484f58;flex-shrink:0;font-size:.9em}
.motion{color:#79c0ff}.face_ok{color:#56d364}.face_no{color:#ff7b72}
.cyber_ev{color:#d2a8ff}.patrol_ev{color:#e3b341}.other{color:#8b949e}
.no-ev{color:#484f58;font-style:italic;font-size:.9em}

/* cyber buttons */
.cyber-btns{display:flex;gap:6px;margin-top:2px}
.btn{flex:1;padding:5px 4px;border:none;border-radius:5px;cursor:pointer;
     font-size:.72em;font-weight:700;transition:background .15s}
.btn-h{background:#3d2b00;color:#e3b341}.btn-h:hover{background:#6e4e00}
.btn-c{background:#3d0000;color:#ff7b72}.btn-c:hover{background:#700}

/* ── bottom panels ── */
.bottom{display:grid;grid-template-columns:220px 1fr;gap:10px;padding:0 14px 14px}
.panel{background:#161b22;border:1px solid #21262d;border-radius:8px;padding:12px}
.ptitle{font-size:.72em;color:#8b949e;font-weight:700;text-transform:uppercase;
        letter-spacing:1px;margin-bottom:8px}

/* patrol */
.pphase{font-size:.82em;color:#f0f6fc;margin-bottom:3px}
.pzone{font-size:.75em;color:#e3b341}
.ph-idle{color:#56d364}.ph-traveling{color:#79c0ff}
.ph-scanning{color:#d2a8ff}.ph-returning{color:#8b949e}

/* terminal */
.terminal{font-family:'Cascadia Code','Consolas',monospace;font-size:.76em;
          background:#010409;border:1px solid #21262d;border-radius:5px;
          padding:10px 12px;height:280px;overflow-y:scroll;display:flex;flex-direction:column}
.tl{padding:5px 0;border-bottom:1px solid #0d1117;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;line-height:1.5;flex-shrink:0}
.tl:last-child{border-bottom:none}
.tts{color:#484f58;margin-right:10px;font-size:.9em}
.tk-motion{color:#79c0ff}.tk-ok{color:#56d364}.tk-alert{color:#f0883e}
.tk-critical{color:#ff7b72;font-weight:700}.tk-cyber{color:#d2a8ff}
.tk-robot{color:#e3b341}.tk-info{color:#8b949e}

/* mas log */
.mlog{font-size:.69em;max-height:120px;overflow-y:auto;margin-top:8px}
.ml{color:#8b949e;padding:4px 0;border-bottom:1px solid #161b22;line-height:1.5}
.ml:last-child{border:none}
.ms{color:#58a6ff;font-weight:600;margin-right:5px}
</style>
</head>
<body>
<header>
  <h1>&#128737; SentinelMAS — Webots Live</h1>
  <span id="ts">a ligar…</span>
</header>

<div class="grid" id="grid"></div>

<div class="bottom">
  <div class="panel">
    <div class="ptitle">Robot de Patrulha</div>
    <div id="patrol-info"><span style="color:#484f58">aguardar Webots…</span></div>
  </div>
  <div class="panel">
    <div class="ptitle">Actividade — Webots → MAS</div>
    <div class="terminal" id="terminal"></div>
    <div class="ptitle" style="margin-top:8px;font-size:.62em">MAS Interno</div>
    <div class="mlog" id="mlog"></div>
  </div>
</div>

<script>
const THREAT = ["LOW","MEDIUM","HIGH","CRITICAL"];
const TCLS   = ["t0","t1","t2","t3"];
const PHCLS  = {idle:"ph-idle",traveling:"ph-traveling",scanning:"ph-scanning",returning:"ph-returning"};
const CYBER_ROOMS = new Set(["datacenter","work_room_1","work_room_2","work_room_3","work_room_4"]);

// grid layout: [room_id, css_extra_class]
const LAYOUT = [
  ["lobby",       ""],
  ["break_room",  ""],
  ["work_room_1", ""],
  ["work_room_2", ""],
  ["work_room_3", ""],
  ["work_room_4", ""],
  ["datacenter",  "full"],
];

function evCls(e){
  if(e.event==="motion_detected")           return "motion";
  if(e.event==="face_detected")             return e.identity==="unknown"?"face_no":"face_ok";
  if(e.event==="cyber_anomaly")             return "cyber_ev";
  if(e.event&&e.event.startsWith("patrol")) return "patrol_ev";
  return "other";
}
function evLabel(e){
  if(e.event==="motion_detected") return "🚶 movimento detectado";
  if(e.event==="face_detected"){
    const conf = e.confidence?` (${Math.round(e.confidence*100)}%)`:"";
    return e.identity==="unknown"
      ? `👤 pessoa NÃO reconhecida${conf}`
      : `✅ identificado: ${e.identity}${conf}`;
  }
  if(e.event==="cyber_anomaly") return `💻 anomalia score=${e.score} · ${e.source||"?"}`;
  if(e.event==="patrol_report") return `🤖 patrulha: ${e.status}`;
  return e.event||"?";
}

function renderBeliefs(b){
  if(!b||!Object.keys(b).length) return '<span style="color:#484f58">—</span>';
  const skip = new Set(["zone_id","threat_level","interpretation"]);
  const parts = [];
  const interp = b.interpretation;
  if(interp) parts.push(`<span class="interp">${interp}</span>`);
  for(const [k,v] of Object.entries(b)){
    if(skip.has(k)||v===false||v===null||v===undefined||v===0) continue;
    parts.push(v===true
      ? `<span class="bv">${k}</span>`
      : `<span class="bk">${k}:</span><span class="bv">${v}</span>`);
  }
  return parts.length ? parts.join(" · ") : '<span style="color:#484f58">normal</span>';
}

function renderCard(room, d, extra){
  const tl  = d.threat??0;
  const evs = d.events||[];
  const evHtml = evs.length
    ? evs.map(e=>`<div class="ev">
        <span class="ev-ts">${e._ts||""}</span>
        <span class="${evCls(e)}">${evLabel(e)}</span></div>`).join("")
    : '<span class="no-ev">sem eventos</span>';

  const cyberBtns = CYBER_ROOMS.has(room) ? `
    <div class="cyber-btns">
      <button class="btn btn-h" onclick="injectCyber('${room}',0.92)">💻 Cyber HIGH</button>
      <button class="btn btn-c" onclick="injectCyber('${room}',0.98)">⚠️ Cyber CRITICAL</button>
    </div>` : "";

  return `<div class="card ${extra}">
    <div class="card-head">
      <span class="card-title">${d.label}<span class="mas-tag">[${d.mas_zone}]</span></span>
      <span class="badge ${TCLS[tl]}">${THREAT[tl]}</span>
    </div>
    <div class="beliefs">${renderBeliefs(d.beliefs)}</div>
    <div class="ev-list">${evHtml}</div>
    ${cyberBtns}
  </div>`;
}

async function injectCyber(room,score){
  await fetch("/api/cyber",{method:"POST",
    headers:{"Content-Type":"application/json"},
    body:JSON.stringify({room,score})});
}

async function refresh(){
  try{
    const r = await fetch("/api/state");
    if(!r.ok) return;
    const d = await r.json();

    document.getElementById("grid").innerHTML =
      LAYOUT.map(([room,cls])=>{
        const rd = d.rooms&&d.rooms[room];
        return rd ? renderCard(room, rd, cls) : "";
      }).join("");

    const p = d.patrol||{};
    document.getElementById("patrol-info").innerHTML = p.phase
      ? `<div class="pphase">Estado: <span class="${PHCLS[p.phase]||""}">${p.phase}</span></div>
         <div class="pzone">Zona actual: ${p.zone||"—"}</div>`
      : '<span style="color:#484f58">aguardar Webots…</span>';

    const term = document.getElementById("terminal");
    const atBottom = term.scrollHeight - term.scrollTop <= term.clientHeight + 20;
    term.innerHTML =
      (d.activity||[]).slice(0,80).reverse().map(e=>
        `<div class="tl"><span class="tts">${e.ts}</span><span class="tk-${e.kind||"info"}">${e.text}</span></div>`
      ).join("") || '<div class="tl" style="color:#484f58">aguardar eventos do Webots…</div>';
    if (atBottom) term.scrollTop = term.scrollHeight;

    document.getElementById("mlog").innerHTML =
      (d.mas_log||[]).slice(0,12).map(e=>
        `<div class="ml"><span class="ms">${e.source||"?"}</span>${e.text||""}</div>`
      ).join("") || '<div style="color:#484f58">—</div>';

    document.getElementById("ts").textContent =
      "actualizado: "+new Date().toLocaleTimeString("pt-PT");
  }catch(e){
    document.getElementById("ts").textContent = "sem ligação ao dashboard…";
  }
}
refresh();
setInterval(refresh,2000);
</script>
</body>
</html>"""


if __name__ == "__main__":
    run()
