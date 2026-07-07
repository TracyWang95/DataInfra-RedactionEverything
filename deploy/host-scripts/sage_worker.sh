LOG=~/sage-build.log
exec >> "$LOG" 2>&1
echo "=== SAGE INSTALL $(date) MemoryMax=90G MAX_JOBS=8 ==="
export CUDA_HOME=/usr/local/cuda-12.8
export PATH=$CUDA_HOME/bin:$PATH
export TORCH_CUDA_ARCH_LIST="12.0"
export MAX_JOBS=8
export EXT_PARALLEL=2
export NVCC_APPEND_FLAGS="--threads 4"
# watchdog backstop
(
  while true; do
    avail=$(free -g | awk '/Mem|内存/{print $7; exit}')
    if [ -n "$avail" ] && [ "$avail" -lt 35 ]; then
      echo "!!! WATCHDOG avail=${avail}G<35G kill !!!"; pkill -9 nvcc; pkill -9 cicc; pkill -9 ptxas; pkill -9 -f no-build-isolation; pkill -9 -f setup.py; echo SAGE_WATCHDOG_ABORT; exit 0
    fi
    pgrep -f sage_worker.sh >/dev/null || exit 0
    sleep 2
  done
) &
WATCH=$!
systemd-run --user --scope -p MemoryMax=90G -p MemorySwapMax=0 \
  ~/rvenv/la/bin/pip install sageattention==2.2.0 --no-build-isolation -i https://mirrors.aliyun.com/pypi/simple/ 2>&1 | tail -25
RC=${PIPESTATUS[0]}
kill $WATCH 2>/dev/null
echo "PIP_RC=$RC"
echo "=== verify (neutral cwd) ==="
cd /tmp
if ~/rvenv/la/bin/python -c "import sageattention; from sageattention import sageattn; print('SAGE_VER', getattr(sageattention,'__version__','?'))" 2>~/sage-err.txt; then echo SAGE_IMPORT_OK; else echo SAGE_IMPORT_FAIL; tail -4 ~/sage-err.txt; fi
~/rvenv/la/bin/pip show sageattention 2>/dev/null | grep -E 'Version|Location' || echo "not in site-packages"
echo "=== SAGE DONE $(date) ==="
