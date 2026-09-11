$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
$speechRequest = [Console]::In.ReadToEnd() | ConvertFrom-Json
Add-Type -AssemblyName System.Speech
$synth = [System.Speech.Synthesis.SpeechSynthesizer]::new()
try {
    $voice = $synth.GetInstalledVoices() | Where-Object {
        $_.Enabled -and $_.VoiceInfo.Culture.Name -eq $speechRequest.language
    } | Select-Object -First 1
    if (-not $voice) { throw 'No installed voice matches the requested language.' }
    $synth.SelectVoice($voice.VoiceInfo.Name)
    $synth.Rate = 0
    $synth.SetOutputToWaveFile([string]$speechRequest.output)
    $synth.Speak([string]$speechRequest.text)
} finally { $synth.Dispose() }
