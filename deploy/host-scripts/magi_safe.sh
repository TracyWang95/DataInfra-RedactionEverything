LOG=~/magi-build.log
exec >> "$LOG" 2>&1
echo "=== MAGI SAFE COMPILE $(date) MAX_JOBS=2 watchdog@40G ==="
cd ~/MagiAttention || exit 1
export CUDA_HOME=/usr/local/cuda-12.8
export PATH=$CUDA_HOME/bin:$PATH
export TORCH_CUDA_ARCH_LIST="12.0"
export MAX_JOBS=2
export NVCC_THREADS=1
# memory watchdog: abort compile if available RAM drops below 40G
(
  while true; do
    avail=$(free -g | awk '/Mem|内存/{print $7; exit}')
    [ -z "$avail" ] && avail=$(free -g | sed -n '2p' | awk '{print $7}')
    if [ -n "$avail" ] && [ "$avail" -lt 40 ]; then
      echo "!!! MEMORY GUARD TRIGGERED: avail=${avail}G < 40G -> killing compile !!!"
      pkill -9 -f no-build-isolation; pkill -9 ninja; pkill -9 nvcc; pkill -9 cicc; pkill -9 cc1plus; pkill -9 cicc
      echo MAGI_ABORTED_OOM_GUARD
      exit 0
    fi
    pgrep -f 'no-build-isolation' >/dev/null || exit 0
    sleep 3
  done
) &
WATCH=$!
~/rvenv/la/bin/pip install --no-build-isolation . 2>&1 | tail -15 && echo MAGI_BUILD_DONE
kill $WATCH 2>/dev/null
~/rvenv/la/bin/python -c "import magi_attention; print('MAGI_OK', getattr(magi_attention,'__version__','?'))" && echo MAGI_IMPORT_OK || echo MAGI_IMPORT_FAIL2
echo "=== MAGI DONE $(date) ==="
