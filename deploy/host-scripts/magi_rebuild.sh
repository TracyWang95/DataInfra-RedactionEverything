LOG=~/magi-build.log
exec >> "$LOG" 2>&1
set -x
echo "=== MAGI REBUILD $(date) ==="
cd ~/MagiAttention || exit 1
export CUDA_HOME=/usr/local/cuda-12.8
export PATH=$CUDA_HOME/bin:$PATH
export TORCH_CUDA_ARCH_LIST="12.0"
export MAX_JOBS=32
~/rvenv/la/bin/pip install --no-build-isolation . 2>&1 | tail -15 && echo MAGI_BUILD_DONE
~/rvenv/la/bin/python -c "import magi_attention; print('MAGI_OK', getattr(magi_attention,'__version__','?'))" && echo MAGI_IMPORT_OK || echo MAGI_IMPORT_FAIL2
echo "=== MAGI REBUILD DONE $(date) ==="
