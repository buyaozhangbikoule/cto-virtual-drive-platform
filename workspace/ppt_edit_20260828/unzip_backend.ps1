param(
  [Parameter(Position=0)] [string] $Mode,
  [Parameter(Position=1)] [string] $ZipPath,
  [Parameter(Position=2)] [string] $EntryName
)

Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive = [System.IO.Compression.ZipFile]::OpenRead($ZipPath)
try {
  if ($Mode -eq '-Z1') {
    foreach ($entry in $archive.Entries) {
      [Console]::Out.WriteLine($entry.FullName)
    }
    exit 0
  }

  if ($Mode -eq '-p') {
    $entry = $archive.GetEntry($EntryName)
    if ($null -eq $entry) {
      [Console]::Error.WriteLine("Entry not found: $EntryName")
      exit 11
    }
    $inputStream = $entry.Open()
    try {
      $outputStream = [Console]::OpenStandardOutput()
      $inputStream.CopyTo($outputStream)
      $outputStream.Flush()
    } finally {
      $inputStream.Dispose()
    }
    exit 0
  }

  [Console]::Error.WriteLine("Unsupported unzip mode: $Mode")
  exit 2
} finally {
  $archive.Dispose()
}
