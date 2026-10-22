# booktrans 一键安装（Windows）
# 由 setup.cmd 调用；也可以直接右键「使用 PowerShell 运行」。
#
# 可调项（通常不用动）：
#   想指定解释器，先设置环境变量 BOOKTRANS_PYTHON=C:\path\to\python.exe
#   想跳过依赖升级，设置 BOOKTRANS_SKIP_PIP=1

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location $root

function Say($msg, $color = "Gray") { Write-Host $msg -ForegroundColor $color }

Say ""
Say "============================================" "Cyan"
Say "  booktrans setup  (Windows)" "Cyan"
Say "============================================" "Cyan"
Say ""

# ---------- 1. 找 Python ----------
function Test-Python($exe) {
    if (-not $exe) { return $false }
    try {
        & $exe -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" 2>$null | Out-Null
        return ($LASTEXITCODE -eq 0)
    } catch { return $false }
}

function Resolve-Store($cmd) {
    # Windows 应用商店的 python.exe 是个占位壳子，点了会跳商店，必须排除
    if (-not $cmd) { return $null }
    $src = $cmd.Source
    if ($src -and $src -like "*\WindowsApps\*") { return $null }
    return $src
}

$candidates = New-Object System.Collections.ArrayList
if ($env:BOOKTRANS_PYTHON) { [void]$candidates.Add(@("BOOKTRANS_PYTHON", $env:BOOKTRANS_PYTHON)) }

foreach ($name in @("py", "python", "python3")) {
    $c = Get-Command $name -ErrorAction SilentlyContinue
    if (-not $c) { continue }
    if ($name -eq "py") {
        [void]$candidates.Add(@("py launcher", "$($c.Source) -3"))
    } else {
        $src = Resolve-Store $c
        if ($src) { [void]$candidates.Add(@($name, $src)) }
    }
}

foreach ($pat in @("$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe",
                   "C:\Python3*\python.exe",
                   "$env:ProgramFiles\Python3*\python.exe",
                   "${env:ProgramFiles(x86)}\Python3*\python.exe")) {
    foreach ($p in (Get-ChildItem $pat -ErrorAction SilentlyContinue | Sort-Object FullName -Descending)) {
        [void]$candidates.Add(@("found at $($p.DirectoryName)", $p.FullName))
    }
}

$pyCmd = $null
$pyLabel = $null
foreach ($pair in $candidates) {
    $label, $exe = $pair[0], $pair[1]
    if (Test-Python $exe) { $pyCmd = $exe; $pyLabel = $label; break }
}

if (-not $pyCmd) {
    Say "[X] 没找到可用的 Python 3.10+。" "Red"
    Say ""
    Say "    常见原因："
    Say "      1) 根本没装 Python  -> https://www.python.org/downloads/"
    Say "         安装时务必勾选 'Add python.exe to PATH'"
    Say "      2) 只有应用商店的占位 python（WindowsApps\python.exe），它会跳商店，不是真解释器"
    Say "         -> 装完官方 Python 后，到「设置 > 应用 > 应用执行别名」关掉 python.exe 的别名"
    Say "      3) 装了但没进 PATH"
    Say "         -> 直接指定：`$env:BOOKTRANS_PYTHON='C:\Python312\python.exe'` 再运行 setup.cmd"
    Say ""
    exit 1
}

$ver = (& $pyCmd -V 2>&1) -join " "
Say "[OK] 解释器：$pyCmd" "Green"
Say "     $ver   （来源：$pyLabel）"
Say ""

# ---------- 2. 虚拟环境 ----------
$venvPy = Join-Path $root ".venv\Scripts\python.exe"
if (Test-Path $venvPy) {
    Say "[1/3] 虚拟环境已存在，跳过创建"
} else {
    Say "[1/3] 创建虚拟环境 .venv ..."
    & $pyCmd -m venv .venv
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $venvPy)) {
        Say "[X] 创建虚拟环境失败。" "Red"
        exit 1
    }
}

# ---------- 3. 依赖 ----------
Say "[2/3] 安装依赖（首次约 30~60 秒）..."
& $venvPy -m pip install --upgrade pip --quiet --disable-pip-version-check 2>&1 | Out-Null
& $venvPy -m pip install -r (Join-Path $root "requirements.txt") --disable-pip-version-check
if ($LASTEXITCODE -ne 0) {
    Say "[X] 装依赖失败。检查网络，或换国内镜像：" "Red"
    Say "    .venv\Scripts\python.exe -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple" "Yellow"
    exit 1
}

# ---------- 4. 配置 ----------
Say "[3/3] 生成 config.json 与 glossary.txt ..."
& $venvPy -m booktrans init
if ($LASTEXITCODE -ne 0) {
    Say "[X] 初始化失败，看上面的报错。" "Red"
    exit 1
}

Say ""
Say "============================================" "Cyan"
Say "  装好了。下一步：" "Cyan"
Say "    1. 打开 config.json，填 api_key" "Cyan"
Say "    2. booktrans.cmd doctor" "Cyan"
Say "    3. 把 epub 拖到「拖书到这里.cmd」上" "Cyan"
Say "============================================" "Cyan"
Say ""
exit 0
