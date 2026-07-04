LOG=~/magi-build.log
exec >> "$LOG" 2>&1
echo "=== MAGI INSTALL (kernels cached) $(date) MemoryMax=120G ==="
cd ~/MagiAttention || exit 1
export CUDA_HOME=/usr/local/cuda-12.8
export PATH=$CUDA_HOME/bin:$PATH
export TORCH_CUDA_ARCH_LIST="12.0"
export MAGI_ATTENTION_PREBUILD_FFA_JOBS=24
export MAX_JOBS=24
export NVCC_THREADS=1
# watchdog backstop at avail<35G
(
  while true; do
    avail=$(free -g | awk '/Mem|内存/{print $7; exit}')
    if [ -n "$avail" ] && [ "$avail" -lt 35 ]; then
      echo "!!! WATCHDOG avail=${avail}G<35G killing !!!"; pkill -9 nvcc; pkill -9 cicc; pkill -9 ptxas; pkill -9 cc1plus; pkill -9 ninja; pkill -9 -f no-build-isolation; echo MAGI_WATCHDOG_ABORT; exit 0
    fi
    pgrep -f 'magi_install_worker.sh' >/dev/null || exit 0
    sleep 2
  done
) &
WATCH=$!
systemd-run --user --scope -p MemoryMax=120G -p MemorySwapMax=0 \
  ~/rvenv/la/bin/pip install --no-build-isolation . 2>&1 | tail -25
echo "PIP_RC=${PIPESTATUS[0]}"
kill $WATCH 2>/dev/null
echo "=== verify (neutral cwd) ==="
cd /tmp && ~/rvenv/la/bin/python -c "import magi_attention; print('MAGI_INSTALLED_OK', magi_attention.__version__)" 2>&1 | tail -2 && echo MAGI_FINAL_OK || echo MAGI_FINAL_FAIL
~/rvenv/la/bin/pip show magi_attention 2>/dev/null | grep -E 'Version|Location' || echo "still not in site-packages"
echo "=== MAGI INSTALL DONE $(date) ==="
