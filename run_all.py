"""
Launcher for all three MedPage agents.

Starts Operator, Priority Handler, and Case Handler in separate PROCESSES
so the full system runs with one command. Each agent gets its own event loop.

Usage:
    python run_all.py
    python run_all.py --log-level INFO

To stop: Ctrl+C (sends SIGTERM to all processes)
"""
from __future__ import annotations
import argparse
import multiprocessing
import os
import sys
import time
from pathlib import Path

# Ensure repo root on path
sys.path.insert(0, str(Path(__file__).parent))

os.environ.setdefault("OPERATOR_PORT", "8001")
os.environ.setdefault("PRIORITY_PORT", "8002")
os.environ.setdefault("CASE_PORT", "8003")
os.environ.setdefault("SENTINEL_PORT", "8004")


def run_priority():
    """Start Priority Handler Agent in its own process."""
    import asyncio
    asyncio.set_event_loop(asyncio.new_event_loop())
    from agents.priority_handler import agent
    agent.run()


def run_case():
    """Start Case Handler Agent in its own process."""
    import asyncio
    asyncio.set_event_loop(asyncio.new_event_loop())
    from agents.case_handler import agent
    agent.run()


def run_operator():
    """Start Operator Agent in its own process."""
    import asyncio
    asyncio.set_event_loop(asyncio.new_event_loop())
    from agents.operator_agent import agent
    agent.run()


def run_sentinel():
    """Start Sentinel Agent in its own process (30s interval pattern detector)."""
    import asyncio
    asyncio.set_event_loop(asyncio.new_event_loop())
    from agents.sentinel_agent import agent
    agent.run()


def derive_operator_address() -> str:
    """Compute the Operator Agent's address from its seed without booting it."""
    from uagents import Agent
    seed = os.getenv("OPERATOR_SEED", "operator-dev-seed")
    a = Agent(name="operator_agent", seed=seed)
    return a.address


def wait_for_agents(timeout: float = 30.0) -> bool:
    """Quick health check that all agents are listening."""
    import socket
    ports = [8001, 8002, 8003, 8004]
    start = time.time()
    while time.time() - start < timeout:
        all_ready = True
        for port in ports:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                    pass
            except Exception:
                all_ready = False
                break
        if all_ready:
            return True
        time.sleep(0.5)
    return False


def main():
    parser = argparse.ArgumentParser(description="Launch all MedPage agents")
    parser.add_argument("--log-level", default="INFO", help="Logging level")
    args = parser.parse_args()
    
    # Set global log level
    import logging
    logging.basicConfig(level=getattr(logging, args.log_level.upper()))
    
    print("\n" + "=" * 60)
    print("MedPage Multi-Agent System Starting...")
    print("=" * 60)
    print("\nStarting agents in separate processes:")
    print("  - Priority Handler:               port 8002")
    print("  - Case Handler:                   port 8003")
    print("  - Operator Agent (Chat Protocol): port 8001")
    print("  - Sentinel Agent (30s timer):     port 8004")
    print("")
    
    # Pre-compute Operator's address so the Sentinel knows where to send insights.
    try:
        op_addr = derive_operator_address()
        os.environ["OPERATOR_ADDRESS"] = op_addr
        print(f"  - Operator address: {op_addr}")
    except Exception as e:
        print(f"  ⚠️  Could not derive OPERATOR_ADDRESS: {e}")
    print("")

    # Start agents in separate processes (not threads - each needs own event loop)
    processes = [
        multiprocessing.Process(target=run_priority, name="priority"),
        multiprocessing.Process(target=run_case, name="case"),
        multiprocessing.Process(target=run_operator, name="operator"),
        multiprocessing.Process(target=run_sentinel, name="sentinel"),
    ]
    
    for p in processes:
        p.start()
        time.sleep(1.5)  # Stagger to avoid startup races
    
    print("Waiting for agents to initialize...")
    
    if wait_for_agents(timeout=30):
        print("\n✅ All agents ready!")
        print("\nTest commands:")
        print('  python -m agents._probe "cardiac arrest room 412"')
        print('  python -m agents._probe "stroke patient room 301"')
        print('  python -m agents._probe "cardiac"  # sparse mode')
        print("\nPress Ctrl+C to stop all agents.\n")
    else:
        print("\n⚠️ Timeout waiting for agents — check logs above.")
    
    # Keep main thread alive, wait for interrupt
    try:
        while any(p.is_alive() for p in processes):
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n\n[launcher] Shutting down...")
    finally:
        for p in processes:
            if p.is_alive():
                p.terminate()
                p.join(timeout=2)
        sys.exit(0)


if __name__ == "__main__":
    # Required for Windows multiprocessing
    multiprocessing.set_start_method("spawn", force=True)
    main()
