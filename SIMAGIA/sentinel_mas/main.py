"""SentinelMAS launcher — runs the full MAS standalone with simulated sensors.

Usage:
    python main.py                # MAS with simulated sensors
    python main.py --interactive  # MAS + in-process manual event injector (terminal)
    python main.py -i             # same (short form)
    python main.py --web          # MAS + web dashboard at http://localhost:8080

Uses SPADE 4's embedded XMPP server (pyjabber).  On Windows, port 5222 falls
inside a system-reserved range (Hyper-V); XMPP_PORT in settings is used instead.
"""

import asyncio
import sys
from contextlib import suppress

import loguru
from pyjabber.server import Server, Parameters
from spade.container import Container

from config import settings
from agents import (
    ZoneCoordinatorAgent,
    PatrolAgent,
    MotionAgent,
    FaceIDAgent,
    CyberSentinelAgent,
    StaffRequestAgent,
    AlertAgent,
    StressBurstAgent,
)
from agents.console_injector import ConsoleInjectorAgent

INTERACTIVE = "--interactive" in sys.argv or "-i" in sys.argv
WEB = "--web" in sys.argv
STRESS = "--stress" in sys.argv
WEB_PORT = 8080

# CLI --stress flag overrides settings.AUCTION_STRESS_TEST
if STRESS:
    settings.AUCTION_STRESS_TEST = True


async def main():
    pwd = settings.XMPP_PASSWORD
    port = settings.XMPP_PORT
    agents = []
    zcs = {}

    # ── Zone coordinators (deliberative BDI) ─────────────────
    for zone, zc_jid in settings.ZONE_COORDINATOR_JIDS.items():
        zc = ZoneCoordinatorAgent(zc_jid, pwd, zone_id=zone, port=port)
        zcs[zone] = zc
        agents.append(zc)

    # ── Hybrid patrol agent ──────────────────────────────────
    patrol = PatrolAgent(settings.PATROL_JID, pwd, port=port)
    agents.append(patrol)

    # ── Reactive agents ──────────────────────────────────────
    agents.append(MotionAgent(settings.MOTION_JID, pwd, port=port))
    agents.append(FaceIDAgent(settings.FACEID_JID, pwd, port=port))
    agents.append(CyberSentinelAgent(settings.CYBER_JID, pwd, port=port))
    agents.append(StaffRequestAgent(settings.STAFF_REQUEST_JID, pwd, port=port))
    agents.append(AlertAgent(settings.ALERT_JID, pwd, port=port))

    # ── Auction stress-test (--stress / SENTINEL_STRESS=1) ───
    if settings.AUCTION_STRESS_TEST:
        agents.append(
            StressBurstAgent(
                settings.jid("stress_burst"), pwd, port=port
            )
        )

    # ── In-process manual injector (--interactive) ───────────
    if INTERACTIVE:
        agents.append(ConsoleInjectorAgent(settings.jid("injector"), pwd, port=port))

    # ── Web dashboard injector (--web) ───────────────────────
    web_injector = None
    if WEB:
        from dashboard import WebInjectorAgent
        web_injector = WebInjectorAgent(settings.jid("web_injector"), pwd, port=port)
        agents.append(web_injector)

    # ── Start everything ─────────────────────────────────────
    for a in agents:
        await a.start(auto_register=True)

    # ── Start the web dashboard (after agents are live) ──────
    dashboard_runner = None
    if WEB:
        from dashboard import start_dashboard
        dashboard_runner = await start_dashboard(zcs, patrol, web_injector, port=WEB_PORT)

    sensors = "ON (random events)" if settings.SIMULATED_SENSORS else "OFF"
    stress_tag = f" + STRESS BURST every {settings.STRESS_BURST_INTERVAL}s" if settings.AUCTION_STRESS_TEST else ""
    mode = "web dashboard" if WEB else ("interactive injector" if INTERACTIVE else "autonomous")
    print("\n" + "-" * 60)
    print("SentinelMAS running -- Ctrl-C to stop")
    print(f"  {len(settings.ZONES)} ZoneCoordinators (BDI) | 1 Patrol (hybrid) | 5 reactive")
    print(f"  Simulated sensors: {sensors}{stress_tag}  |  mode: {mode}")
    if WEB:
        print(f"  Dashboard:  http://localhost:{WEB_PORT}")
    print("-" * 60 + "\n")

    try:
        while True:
            await asyncio.sleep(1)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        if dashboard_runner is not None:
            await dashboard_runner.cleanup()
        for a in agents:
            await a.stop()
        print("SentinelMAS stopped.")


def run():
    """Start pyjabber on XMPP_PORT (avoids Windows-reserved port 5222)."""
    container = Container()
    server = None

    try:
        loguru.logger.remove()
        server_instance = Server(
            Parameters(
                host="localhost",
                client_port=settings.XMPP_PORT,
                server_port=settings.XMPP_SERVER_PORT,
                database_in_memory=True,
            )
        )
        server = container.loop.create_task(server_instance.start())
        container.run(server_instance.ready.wait())
        print(f"XMPP server up on localhost:{settings.XMPP_PORT}")

        container.run(main())

    except KeyboardInterrupt:
        print("\nKeyboard interrupt - stopping SentinelMAS...")
    except SystemExit:
        # pyjabber raises SystemExit when it cannot bind the XMPP ports.
        print(
            f"\n  ERROR: could not start the XMPP server on "
            f"localhost:{settings.XMPP_PORT}/{settings.XMPP_SERVER_PORT}.\n"
            f"  A previous SentinelMAS is probably still running and holding\n"
            f"  the port. Close it (or kill the leftover python process) and\n"
            f"  try again."
        )
    except Exception:
        import traceback
        traceback.print_exc()

    container.stop_agents()

    if server:
        server.cancel()
        with suppress(Exception):
            container.run(server)

    tasks = asyncio.all_tasks(loop=container.loop)
    for task in tasks:
        task.cancel()
        with suppress(asyncio.CancelledError):
            container.run(task)

    container.loop.run_until_complete(container.loop.shutdown_asyncgens())
    container.loop.close()


if __name__ == "__main__":
    run()
