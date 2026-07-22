#!/bin/bash
# 把运行态代码从 git 仓库同步到 ~/redaction-live 并生成 live 部署脚本。
#
# 为什么要隔离：这台机器上仓库是共享的，别人 checkout/reset 分支时，工作树里的
# app/scripts/config 会被 git 还原成那个分支的版本——运行中的服务代码就被换掉了
# （本轮实测被冲三次：backend_g0.sh 退回 ~/redaction-deploy 老路径起不来、
# la_consensus.py 整个消失、preset 里的签字查询词退回旧措辞）。把代码复制出去跑，
# 仓库照旧给人提交，运行态与 git 彻底解耦。
#
# 只隔离代码。models/data/uploads/outputs 体积大且是运行态资产，软链回仓库原处，
# 既不搬也不受 git 影响（它们不在版本控制里）。
#
# 用法：bash deploy/dual-5090/sync_to_live.sh   然后 ~/redaction-live/deploy/start_all.sh
set -u
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RB="$REPO/backend"
LIVE="${REDACTION_LIVE_DIR:-$HOME/redaction-live}"
LB="$LIVE/backend"

echo "repo=$REPO"
echo "live=$LIVE"

mkdir -p "$LB" "$LIVE/deploy"

echo "[1] 同步代码 (app/scripts/config)"
for d in app scripts config; do
  rm -rf "${LB:?}/$d"
  cp -r "$RB/$d" "$LB/$d"
done
echo "  app=$(find "$LB/app" -name '*.py' | wc -l)py scripts=$(ls "$LB"/scripts/*.py 2>/dev/null | wc -l)py"

echo "[2] 运行态资产软链回仓库 (不搬)"
for d in models data uploads outputs; do
  rm -rf "${LB:?}/$d"
  ln -s "$RB/$d" "$LB/$d"
done

echo "[2b] 前端 dist"
# app/main.py 解析 _FRONTEND_DIST = <backend>/../../frontend/dist，所以后端从
# 哪个目录跑，就得在那个目录旁边有 frontend/dist —— 否则 "/" 返回 API 的 JSON
# 而不是应用，浏览器里看着就是"改动没生效"。
if [ -d "$REPO/frontend/dist" ]; then
  mkdir -p "$LIVE/frontend"
  rm -rf "$LIVE/frontend/dist"
  cp -r "$REPO/frontend/dist" "$LIVE/frontend/dist"
  echo "  dist -> $LIVE/frontend/dist"
else
  echo "  跳过: $REPO/frontend/dist 不存在 (先 npm run build)"
fi

echo "[3] 生成 live 部署脚本 (把仓库路径改写成 live 路径)"
for f in "$REPO"/deploy/dual-5090/*.sh; do
  b="$(basename "$f")"
  case "$b" in start_all.sh|sync_to_live.sh|build_*.sh) continue ;; esac
  sed "s|$RB|$LB|g" "$f" > "$LIVE/deploy/$b"
done
cp "$REPO/deploy/dual-5090/lib_kill_vllm.sh" "$LIVE/deploy/" 2>/dev/null
# 四个 lb_*.sh 都 cd 到自己所在目录跑 lb_proxy:app，所以它必须跟着过来。
cp "$REPO/deploy/dual-5090/lb_proxy.py" "$LIVE/deploy/" || { echo "  致命: lb_proxy.py 缺失, 四个 LB 起不来"; exit 1; }
chmod +x "$LIVE"/deploy/*.sh
stale=$(grep -l "$RB" "$LIVE"/deploy/*.sh 2>/dev/null | wc -l)
echo "  脚本=$(ls "$LIVE"/deploy/*.sh | wc -l) 残留仓库路径=$stale"
[ "$stale" != "0" ] && echo "  警告: 仍有脚本指向仓库, 检查上面的 sed 替换"
# sed 只认得仓库路径。上一代部署留下的死路径(~/redaction-deploy、/home/adminroot、
# ~/rvenv)它换不掉，会被原样带进 live —— 本轮 lb_ocr/ocr_g0b 就是这么起不来的。
dead=$(grep -lE "redaction-deploy|adminroot|rvenv" "$LIVE"/deploy/*.sh 2>/dev/null | xargs -r -n1 basename | tr '\n' ' ')
[ -n "$dead" ] && echo "  警告: 这些脚本还带着上一代死路径, 起不来: $dead"

echo "[4] 写 start_all (完整启动顺序)"
cat > "$LIVE/deploy/start_all.sh" <<'SAEOF'
#!/bin/bash
# 一键拉起全栈（从 ~/redaction-live 跑，与 git 解耦）。只启动当前 DOWN 的服务，
# 可随时重跑。端口一律 2 前缀（28xxx/29xxx），避开这台机器上别人的同名服务。
set -u
SD="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p ~/logs
# pkill 只杀 vLLM 的 APIServer，EngineCore 子进程会变孤儿继续占几个 GB 显存，
# 下一个起的服务就 OOM——先按进程组收干净。
[ -f "$SD/lib_kill_vllm.sh" ] && . "$SD/lib_kill_vllm.sh" && reap_orphan_enginecores
up(){ ss -ltn 2>/dev/null | grep -q ":$1 "; }
launch(){
  local name=$1 port=$2 script=$SD/$3
  if up "$port"; then echo "  [skip] $name :$port UP"; return; fi
  [ -f "$script" ] || { echo "  [MISS] $name: $script"; return; }
  nohup bash "$script" > ~/logs/"$name".log 2>&1 &
  echo "  [start] $name :$port"
}
waitport(){ for i in $(seq 1 "$2"); do up "$1" && return 0; sleep 6; done; return 1; }

echo "=== 1. 识别/OCR 模型服务 ==="
launch vl_serve_g0 28118 vl_serve_g0.sh
launch vl_serve_g1 28119 vl_serve_g1.sh
launch has_g0 28080 has_g0.sh
launch has_g1 28081 has_g1.sh
launch yolo_g0 28140 yolo_g0.sh
launch yolo_g1 28141 yolo_g1.sh
echo "  [wait] OCR 启动时要 POST vl_serve 预热, 先等它就绪"
waitport 28118 40; waitport 28119 40
launch ocr_g0 28082 ocr_g0.sh
launch ocr_g1 28083 ocr_g1.sh
launch ocr_g0b 28084 ocr_g0b.sh
launch ocr_g1b 28085 ocr_g1b.sh

echo "=== 2. LA 视觉塔 (vision-only) ==="
# 必须先起：vLLM 模式下它只加载 MoonViT，把整模型的显存腾出来给 la_lm。
launch la_g0 28090 la_g0.sh
launch la_g1 28091 la_g1.sh
waitport 28090 40; waitport 28091 40

echo "=== 3. LA 文本解码器 (vLLM), 必须在 LA 之后 ==="
launch la_lm_g0 28092 la_lm_g0.sh
launch la_lm_g1 28093 la_lm_g1.sh
waitport 28092 60; waitport 28093 60

echo "=== 4. 负载均衡 ==="
launch lb_has 29080 lb_has.sh
launch lb_ocr 29082 lb_ocr.sh
launch lb_la 29090 lb_la.sh
launch lb_yolo 29140 lb_yolo.sh

echo "=== 5. 后端 ==="
launch backend 28001 backend_g0.sh
waitport 28001 30 && echo "  backend UP" || echo "  backend 未就绪, 看 ~/logs/backend.log"

echo ""
echo "状态:"
for p in 28118 28119 28080 28081 28082 28083 28084 28085 28090 28091 28092 28093 28140 28141 29080 29082 29090 29140 28001; do
  up "$p" && echo "  :$p UP" || echo "  :$p DOWN"
done
SAEOF
chmod +x "$LIVE/deploy/start_all.sh"

echo ""
echo "完成。启动：$LIVE/deploy/start_all.sh"
