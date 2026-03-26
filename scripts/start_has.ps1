# HaS NER (llama.cpp) — 端口 8080
# 若 conda 环境 legal-redaction 内存在 llama-server，则用 conda run 启动（PATH/DLL 与 Python 栈一致）；
# 否则回退到 PATH / Winget 下的 llama-server.exe（原生进程，不经过 conda）。
$ErrorActionPreference = "Stop"
$ScriptDir = $PSScriptRoot
$ProjectRoot = Split-Path -Parent $ScriptDir
$LogDir = Join-Path $ProjectRoot "logs"
$null = New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$LogOut = Join-Path $LogDir "has_llama_stdout.log"
$LogErr = Join-Path $LogDir "has_llama_stderr.log"

$EnvName = if ($env:LEGAL_REDACTION_CONDA_ENV) { $env:LEGAL_REDACTION_CONDA_ENV } else { "legal-redaction" }

function Get-CondaRoot {
    if ($env:CONDA_ROOT -and (Test-Path (Join-Path $env:CONDA_ROOT "Scripts\conda.exe"))) { return $env:CONDA_ROOT }
    foreach ($c in @("conda-root", "C:\ProgramData\miniconda3", "C:\ProgramData\anaconda3", "$env:USERPROFILE\anaconda3", "$env:USERPROFILE\miniconda3")) {
        if (Test-Path (Join-Path $c "Scripts\conda.exe")) { return $c }
    }
    $cmd = Get-Command conda -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source -match 'conda\.exe$') { return (Split-Path (Split-Path $cmd.Source)) }
    return $null
}

function Resolve-LlamaServerInConda {
    param([string]$CondaRoot, [string]$Name)
    if (-not $CondaRoot) { return $null }
    foreach ($rel in @(
            "envs\$Name\Library\bin\llama-server.exe",
            "envs\$Name\Scripts\llama-server.exe"
        )) {
        $p = Join-Path $CondaRoot $rel
        if (Test-Path -LiteralPath $p) { return $p }
    }
    return $null
}

function Resolve-LlamaServer {
    $cmd = Get-Command "llama-server.exe" -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $wingetGuess = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages\ggml.llamacpp_Microsoft.Winget.Source_8wekyb3d8bbwe\llama-server.exe"
    if (Test-Path -LiteralPath $wingetGuess) { return $wingetGuess }
    $pkgRoot = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages"
    $dirs = Get-ChildItem $pkgRoot -Directory -Filter "ggml.llamacpp*" -ErrorAction SilentlyContinue
    foreach ($d in $dirs) {
        $p = Join-Path $d.FullName "llama-server.exe"
        if (Test-Path -LiteralPath $p) { return $p }
    }
    return $null
}

$CondaRoot = Get-CondaRoot
$CondaExe = if ($CondaRoot) { Join-Path $CondaRoot "Scripts\conda.exe" } else { $null }
$llamaConda = Resolve-LlamaServerInConda $CondaRoot $EnvName
$LLAMA_SERVER = if ($llamaConda) { $llamaConda } else { Resolve-LlamaServer }

if (-not $LLAMA_SERVER) {
    $msg = "llama-server.exe not found. Install in conda env $EnvName, winget ggml.llamacpp, or add to PATH."
    Write-Host $msg -ForegroundColor Red
    Set-Content -Path (Join-Path $LogDir "has_start_failed.txt") -Value $msg -Encoding UTF8
    exit 1
}

# HaS Text 0209 Q4_K_M：见 https://huggingface.co/xuanwulab/HaS_Text_0209_0.6B_Q4
$HfRepo = if ($env:HAS_NER_HF_REPO -and $env:HAS_NER_HF_REPO.Trim()) { $env:HAS_NER_HF_REPO.Trim() } else { "xuanwulab/HaS_Text_0209_0.6B_Q4" }
$DefaultGguf = "has_models/HaS_Text_0209_0.6B_Q4_K_M.gguf"
$LegacyGguf = "has_models/has_4.0_0.6B_q4.gguf"
$HAS_MODEL = $null
if ($env:HAS_NER_GGUF -and (Test-Path -LiteralPath $env:HAS_NER_GGUF.Trim())) {
    $HAS_MODEL = $env:HAS_NER_GGUF.Trim()
} elseif (Test-Path -LiteralPath $DefaultGguf) {
    $HAS_MODEL = $DefaultGguf
} elseif (Test-Path -LiteralPath $LegacyGguf) {
    $HAS_MODEL = $LegacyGguf
    Write-Host "HaS NER: using legacy GGUF $HAS_MODEL (set HAS_NER_GGUF to HaS_Text_0209 .gguf for latest)" -ForegroundColor DarkYellow
}
# 与模型卡接近：-c 8192 -np 1；层数可按显存用 HAS_NER_NGL 覆盖（默认 99）
$Ngl = if ($env:HAS_NER_NGL -and $env:HAS_NER_NGL.Trim()) { $env:HAS_NER_NGL.Trim() } else { "99" }
$ngl = [string]$Ngl
if (-not $ngl) { $ngl = "99" }
if ($HAS_MODEL) {
    Write-Host "HaS NER: local model $HAS_MODEL" -ForegroundColor Green
    $qm = '"' + ($HAS_MODEL -replace '"', '') + '"'
    # Do not embed $qm inside double quotes — embedded quotes break PS parsing and corrupt -ngl.
    $llamaArgLine = '-m ' + $qm + ' --port 8080 -ngl ' + $ngl + ' --host 0.0.0.0 -c 8192 -np 1'
} else {
    Write-Host "HaS NER: no local .gguf, using -hf $HfRepo" -ForegroundColor Yellow
    $llamaArgLine = '-hf ' + $HfRepo + ' --port 8080 -ngl ' + $ngl + ' --host 0.0.0.0 -c 8192 -np 1'
}

Write-Host "HaS NER: llama-server = $LLAMA_SERVER" -ForegroundColor Cyan
if ($llamaConda) {
    Write-Host "HaS NER: using conda env $EnvName" -ForegroundColor DarkGray
} else {
    Write-Host "HaS NER: using system or winget llama-server" -ForegroundColor DarkYellow
}
Write-Host ("HaS NER: logs -> {0} | {1}" -f $LogOut, $LogErr) -ForegroundColor DarkGray

"" | Set-Content -Path $LogOut -Encoding UTF8
"" | Set-Content -Path $LogErr -Encoding UTF8

if ($llamaConda -and $CondaExe -and (Test-Path -LiteralPath $CondaExe)) {
    $exeQ = '"' + ($LLAMA_SERVER -replace '"', '') + '"'
    $condaLine = 'run -n ' + $EnvName + ' --no-capture-output ' + $exeQ + ' ' + $llamaArgLine
    $p = Start-Process -FilePath $CondaExe -ArgumentList $condaLine -WorkingDirectory $ProjectRoot -WindowStyle Minimized -PassThru -RedirectStandardOutput $LogOut -RedirectStandardError $LogErr
    Write-Host "HaS NER: started PID=$($p.Id) port 8080 (conda run)" -ForegroundColor Green
} else {
    $p = Start-Process -FilePath $LLAMA_SERVER -ArgumentList $llamaArgLine -WorkingDirectory $ProjectRoot -WindowStyle Minimized -PassThru -RedirectStandardOutput $LogOut -RedirectStandardError $LogErr
    Write-Host "HaS NER: started PID=$($p.Id) port 8080" -ForegroundColor Green
}
exit 0
