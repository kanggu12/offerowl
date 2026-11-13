# Reads the text of one picture with the OCR engine Windows ships (Windows.Media.Ocr), for a PC with no tesseract.
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File winocr.ps1 <picture> <language tag, e.g. ko or en-US>
# Prints the lines, one per line, in UTF-8; prints nothing when the language has no OCR pack on this PC.
param([string]$Picture, [string]$Lang = "ko")
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [Text.Encoding]::UTF8                       # Korean reaches the caller intact
Add-Type -AssemblyName System.Runtime.WindowsRuntime                    # the bridge from WinRT's async calls to .NET tasks
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics, ContentType = WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Globalization, ContentType = WindowsRuntime]
# One WinRT async call, waited for: AsTask is generic, so it is picked by its shape (IAsyncOperation`1) and closed over the result type
$asTask = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' } | Select-Object -First 1
function Await($op, [Type]$type) { $t = $asTask.MakeGenericMethod($type).Invoke($null, @($op)); $t.Wait(-1) | Out-Null; $t.Result }
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage([Windows.Globalization.Language]::new($Lang))   # null without the language's pack
if ($null -eq $engine) { exit 3 }                                       # the caller says the picture could not be read
$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync((Resolve-Path $Picture).Path)) ([Windows.Storage.StorageFile])
$stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
$result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
foreach ($line in $result.Lines) { $line.Text }                         # one line of the picture a line
