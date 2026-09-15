param(
    [string]$LtspiceExe = 'D:\LTspice.exe',
    [string]$Circuit = 'C:\Users\24739\Documents\Codex\2026-08-10\new-chat\outputs\v2_self_consistent_rebuild\active_stage3_5\stage3_disturbance\ltspice_validation\CASE_000_BASELINE.cir',
    [string]$OutputDir = 'C:\Users\24739\Documents\Codex\2026-08-10\new-chat\outputs\v2_self_consistent_rebuild\active_stage3_5\ltspice_gui_evidence'
)

$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

# Work on an evidence copy so opening the GUI cannot replace the batch-run RAW
# whose hash is recorded by the numerical cross-validation audit.
$SourceCircuit = $Circuit
$SourceRaw = [IO.Path]::ChangeExtension($SourceCircuit, '.raw')
$SourceLog = [IO.Path]::ChangeExtension($SourceCircuit, '.log')
$Circuit = Join-Path $OutputDir 'CASE_000_BASELINE_GUI.cir'
Copy-Item -Force -LiteralPath $SourceCircuit -Destination $Circuit
Copy-Item -Force -LiteralPath $SourceRaw -Destination ([IO.Path]::ChangeExtension($Circuit, '.raw'))
Copy-Item -Force -LiteralPath $SourceLog -Destination ([IO.Path]::ChangeExtension($Circuit, '.log'))

Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class Win32Capture {
  [StructLayout(LayoutKind.Sequential)]
  public struct RECT { public int Left; public int Top; public int Right; public int Bottom; }
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
  public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc callback, IntPtr lParam);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr hWnd, System.Text.StringBuilder text, int count);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr hWnd, IntPtr hdcBlt, uint flags);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint flags, uint dx, uint dy, uint data, UIntPtr extraInfo);
}
'@

function Save-Window([IntPtr]$handle, [string]$Path) {
    $rect = New-Object Win32Capture+RECT
    if (-not [Win32Capture]::GetWindowRect($handle, [ref]$rect)) {
        throw 'Could not obtain the foreground-window rectangle.'
    }
    $width = [Math]::Max(1, $rect.Right - $rect.Left)
    $height = [Math]::Max(1, $rect.Bottom - $rect.Top)
    $bitmap = New-Object System.Drawing.Bitmap $width, $height
    [Win32Capture]::ShowWindow($handle, 3) | Out-Null
    [Win32Capture]::SetForegroundWindow($handle) | Out-Null
    Start-Sleep -Milliseconds 700
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    try {
        # LTspice 26 uses GPU-backed child panes. PrintWindow captures those as
        # black rectangles, so capture the actually displayed screen region.
        $graphics.CopyFromScreen($rect.Left, $rect.Top, 0, 0, $bitmap.Size)
        $bitmap.Save($Path, [System.Drawing.Imaging.ImageFormat]::Png)
    } finally {
        $graphics.Dispose()
        $bitmap.Dispose()
    }
}

function Save-WindowPrinted([IntPtr]$handle, [string]$Path) {
    $rect = New-Object Win32Capture+RECT
    if (-not [Win32Capture]::GetWindowRect($handle, [ref]$rect)) { throw 'Could not obtain window rectangle.' }
    $width = [Math]::Max(1, $rect.Right - $rect.Left)
    $height = [Math]::Max(1, $rect.Bottom - $rect.Top)
    $bitmap = New-Object System.Drawing.Bitmap $width, $height
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    try {
        $hdc = $graphics.GetHdc()
        try { [Win32Capture]::PrintWindow($handle, $hdc, 2) | Out-Null }
        finally { $graphics.ReleaseHdc($hdc) }
        $bitmap.Save($Path, [System.Drawing.Imaging.ImageFormat]::Png)
    } finally {
        $graphics.Dispose()
        $bitmap.Dispose()
    }
}

function Get-ProcessWindows([int]$ProcessId) {
    $found = New-Object System.Collections.Generic.List[object]
    $callback = [Win32Capture+EnumWindowsProc]{
        param([IntPtr]$hWnd, [IntPtr]$lParam)
        [uint32]$windowProcessId = 0
        [Win32Capture]::GetWindowThreadProcessId($hWnd, [ref]$windowProcessId) | Out-Null
        if ($windowProcessId -eq $ProcessId -and [Win32Capture]::IsWindowVisible($hWnd)) {
            $title = New-Object System.Text.StringBuilder 512
            [Win32Capture]::GetWindowText($hWnd, $title, $title.Capacity) | Out-Null
            $found.Add([pscustomobject]@{ Handle=$hWnd; Title=$title.ToString() })
        }
        return $true
    }
    [Win32Capture]::EnumWindows($callback, [IntPtr]::Zero) | Out-Null
    return $found
}

$started = Start-Process -FilePath $LtspiceExe -ArgumentList ('"' + $Circuit + '"') -PassThru
Start-Sleep -Seconds 5
$mainWindow = $null
foreach ($candidateProcess in @(Get-Process | Where-Object { $_.ProcessName -match 'LTspice' } | Sort-Object StartTime -Descending)) {
    $candidateWindows = @(Get-ProcessWindows $candidateProcess.Id)
    $guiNamePattern = [regex]::Escape([IO.Path]::GetFileName($Circuit))
    $candidateMain = $candidateWindows | Where-Object { $_.Title -match ("^LTspice - \[" + $guiNamePattern + "\]") } | Select-Object -First 1
    if ($null -ne $candidateMain) {
        $started = $candidateProcess
        $mainWindow = $candidateMain
        break
    }
}
if ($null -eq $mainWindow) { throw 'Could not locate the LTspice main window by title.' }
$mainHandle = $mainWindow.Handle
[Win32Capture]::ShowWindow($mainHandle, 3) | Out-Null
$shell = New-Object -ComObject WScript.Shell
$shell.AppActivate($started.Id) | Out-Null
Start-Sleep -Seconds 2
# LTspice may open both the netlist editor and the waveform tab. Select the
# previous MDI tab so the captured GUI visibly contains the executed .cir text.
[System.Windows.Forms.SendKeys]::SendWait('^+{TAB}')
Start-Sleep -Seconds 1
$mainRect = New-Object Win32Capture+RECT
[Win32Capture]::GetWindowRect($mainHandle, [ref]$mainRect) | Out-Null
[Win32Capture]::SetCursorPos($mainRect.Left + 110, $mainRect.Top + 125) | Out-Null
[Win32Capture]::mouse_event(0x0002, 0, 0, 0, [UIntPtr]::Zero)
[Win32Capture]::mouse_event(0x0004, 0, 0, 0, [UIntPtr]::Zero)
[System.Windows.Forms.SendKeys]::SendWait('^{HOME}')
Start-Sleep -Seconds 1
Save-Window $mainHandle (Join-Path $OutputDir 'LTspice_GUI_baseline_netlist.png')

# Select the waveform tab. A same-stem .plt file preloads magnitude and phase
# traces from the copied RAW for a deterministic GUI record.
[Win32Capture]::SetForegroundWindow($mainHandle) | Out-Null
[System.Windows.Forms.SendKeys]::SendWait('^{TAB}')
Start-Sleep -Seconds 2
Save-Window $mainHandle (Join-Path $OutputDir 'LTspice_GUI_waveform_V_n_port.png')

# Ctrl+L is LTspice's View SPICE Error Log command. The .raw/.log files already
# exist from the real batch run with the same circuit stem.
[Win32Capture]::SetForegroundWindow($mainHandle) | Out-Null
Start-Sleep -Milliseconds 500
[System.Windows.Forms.SendKeys]::SendWait('^l')
Start-Sleep -Seconds 3
$windows = @(Get-ProcessWindows $started.Id)
$windows | Select-Object @{n='Handle';e={$_.Handle.ToInt64()}},Title |
    ConvertTo-Json | Set-Content -Encoding UTF8 (Join-Path $OutputDir 'visible_window_titles.json')
$logWindow = $windows | Where-Object { $_.Title -match 'Output Log|Error Log|SPICE' -and $_.Handle -ne $mainHandle } | Select-Object -First 1
if ($null -eq $logWindow) {
    $logWindow = $windows | Where-Object { $_.Handle -ne $mainHandle } | Select-Object -First 1
}
if ($null -ne $logWindow) {
    Save-WindowPrinted $logWindow.Handle (Join-Path $OutputDir 'LTspice_SPICE_Error_Log.png')
} else {
    Save-WindowPrinted $mainHandle (Join-Path $OutputDir 'LTspice_SPICE_Error_Log.png')
}

$meta = [ordered]@{
    captured_at = (Get-Date).ToString('o')
    executable = $LtspiceExe
    executable_version = (Get-Item $LtspiceExe).VersionInfo.FileVersion
    source_circuit = $SourceCircuit
    source_circuit_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $SourceCircuit).Hash
    source_raw_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $SourceRaw).Hash
    source_log_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $SourceLog).Hash
    circuit = $Circuit
    circuit_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $Circuit).Hash
    raw_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath ([IO.Path]::ChangeExtension($Circuit, '.raw'))).Hash
    log_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath ([IO.Path]::ChangeExtension($Circuit, '.log'))).Hash
    method = 'Actual LTspice GUI capture from a byte-for-byte evidence copy of the batch .cir/.raw/.log; Ctrl+L Error Log view. The copy prevents GUI access from changing the audited batch RAW.'
}
$meta | ConvertTo-Json | Set-Content -Encoding UTF8 (Join-Path $OutputDir 'LTspice_GUI_evidence_metadata.json')

Write-Output ($meta | ConvertTo-Json -Compress)
