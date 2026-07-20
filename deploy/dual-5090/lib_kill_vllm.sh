#!/bin/bash
# Shared vLLM lifecycle helpers. Source this from start_all.sh / restart scripts.
#
# WHY THIS EXISTS (recurs constantly on the dual 5090/casdao boxes):
# A vLLM server is TWO processes — the APIServer (binds the port) and a
# VLLM::EngineCore child (a separate PID that actually holds the multi-GB of
# GPU memory). `pkill -f vllm` / `pkill -f <script>` kills only the APIServer;
# the EngineCore keeps running as an ORPHAN (ppid=1), pinning its VRAM. The next
# service that tries to load then hits CUDA OOM (classically YOLO/has_image or
# the LA MoonViT vision encode → 503), and the two cards drift out of balance
# (one ~8 GB heavier than the other). See memory feedback_vllm_restart_pgid.

# Kill the whole vLLM server listening on a port: the APIServer AND its
# EngineCore, by process group, so no orphan survives.
kill_vllm_port() {
  local port="$1"
  local api
  api=$(ss -ltnp 2>/dev/null | grep ":$port " | grep -oE 'pid=[0-9]+' | head -1 | cut -d= -f2)
  [ -z "$api" ] && return 0
  local pgid
  pgid=$(ps -o pgid= -p "$api" 2>/dev/null | tr -d ' ')
  echo "  [kill] vLLM :$port APIServer=$api pgid=$pgid (+EngineCore)"
  [ -n "$pgid" ] && kill -9 -"$pgid" 2>/dev/null
  kill -9 "$api" 2>/dev/null
}

# Reap every orphaned EngineCore (ppid=1) — leftovers from earlier crashed or
# half-killed restarts that are still pinning VRAM for no live parent. Safe:
# a healthy EngineCore always has its APIServer as parent, never PID 1.
reap_orphan_enginecores() {
  local pid ppid
  for pid in $(pgrep -f "VLLM::EngineCore" 2>/dev/null); do
    ppid=$(ps -o ppid= -p "$pid" 2>/dev/null | tr -d ' ')
    if [ "$ppid" = "1" ]; then
      echo "  [reap] orphan EngineCore pid=$pid (ppid=1, pinning VRAM)"
      kill -9 "$pid" 2>/dev/null
    fi
  done
}

# Full clean restart of a vLLM service: kill anything on the port, reap orphans,
# wait for VRAM to actually release, then it's safe for the caller to relaunch.
stop_vllm_clean() {
  local port="$1"
  kill_vllm_port "$port"
  reap_orphan_enginecores
  sleep 8
}
