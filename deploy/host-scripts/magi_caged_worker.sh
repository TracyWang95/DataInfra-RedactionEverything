LOG=~/magi-build.log
exec >> "$LOG" 2>&1
echo "=== MAGI CAGED COMPILE $(date) PREBUILD_FFA_JOBS=24 MemoryMax=80G watchdog@45G ==="
cd ~/MagiAttention || exit 1
export CUDA_HOME=/usr/local/cuda-12.8
export PATH=$CUDA_HOME/bin:$PATH
export TORCH_CUDA_ARCH_LIST="12.0"
export MAGI_ATTENTION_PREBUILD_FFA_JOBS=24
export MAX_JOBS=24
export NVCC_THREADS=1

# external watchdog: hard backstop if available RAM drops below 45G
(
  while true; do
    avail=$(free -g | awk '/Mem|内存/{print $7; exit}')
    if [ -n "$avail" ] && [ "$avail" -lt 45 ]; then
      echo "!!! WATCHDOG: avail=${avail}G < 45G -> killing compile !!!"
      pkill -9 nvcc; pkill -9 cicc; pkill -9 ptxas; pkill -9 cc1plus; pkill -9 ninja
      pkill -9 -f 'no-build-isolation'; pkill -9 -f 'setup.py'
      echo MAGI_WATCHDOG_ABORT
      exit 0
    fi
    pgrep -f 'no-build-isolation|setup.py bdist|ninja|nvcc' >/dev/null || { sleep 5; pgrep -f 'no-build-isolation' >/dev/null || exit 0; }
    sleep 2
  done
) &
WATCH=$!

# cgroup hard cap via user-level systemd scope (falls back to plain run if unavailable)
if systemd-run --user --scope -p MemoryMax=80G -p MemorySwapMax=0 true >/dev/null 2>&1; then
  echo "cgroup MemoryMax enforced via systemd-run --user"
  systemd-run --user --scope -p MemoryMax=80G -p MemorySwapMax=0 \
    ~/rvenv/la/bin/pip install --no-build-isolation . 2>&1 | tail -20
  RC=${PIPESTATUS[0]}
else
  echo "systemd-run --user scope unavailable; relying on PREBUILD_FFA_JOBS=24 + watchdog"
  ~/rvenv/la/bin/pip install --no-build-isolation . 2>&1 | tail -20
  RC=${PIPESTATUS[0]}
fi
echo "PIP_RC=$RC"
kill $WATCH 2>/dev/null
echo "=== verify install ==="
~/rvenv/la/bin/python -c "import magi_attention; print('MAGI_OK', magi_attention.__version__)" 2>&1 | tail -2 && echo MAGI_IMPORT_OK || echo MAGI_IMPORT_FAIL
~/rvenv/la/bin/pip show magi_attention 2>/dev/null | grep -E 'Version|Location' || echo "not in venv site-packages"
echo "=== MAGI CAGED DONE $(date) ==="
