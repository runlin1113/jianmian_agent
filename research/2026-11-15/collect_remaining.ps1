$ErrorActionPreference='Stop'
$researchRoot=$PSScriptRoot
$researchTargets=@(
    @('langchain-ai/langgraph','main','README.md','LICENSE'),
    @('pydantic/pydantic-ai','main','LICENSE'),
    @('openai/openai-agents-python','main','README.md','LICENSE'),
    @('langgenius/dify','main','README.md','LICENSE'),
    @('coze-dev/coze-studio','main','README.md','LICENSE'),
    @('AmruthPillai/Reactive-Resume','main','README.md'),
    @('xitanggg/open-resume','main','README.md'),
    @('srbhr/Resume-Matcher','main','README.md'),
    @('mozilla/pdf.js','master','README.md'),
    @('docling-project/docling','main','README.md','LICENSE'),
    @('agno-agi/agno','main','LICENSE')
)
$researchRecords=$researchTargets | ForEach-Object -Parallel {
    $researchTarget=$_
    $researchFolder=Join-Path (Join-Path $using:researchRoot 'branch_sources') ($researchTarget[0].Replace('/','__'))
    New-Item -ItemType Directory -Path $researchFolder -Force | Out-Null
    $researchRecord=[ordered]@{repo=$researchTarget[0];branch=$researchTarget[1];retrieved_at=[DateTimeOffset]::UtcNow.ToString('o');files=@();errors=@()}
    foreach($researchPath in $researchTarget[2..($researchTarget.Length-1)]) {
        $researchUrl='https://raw.githubusercontent.com/'+$researchTarget[0]+'/refs/heads/'+$researchTarget[1]+'/'+$researchPath
        try {
            $researchResponse=Invoke-WebRequest -Uri $researchUrl -TimeoutSec 10
            $researchLocal=Join-Path $researchFolder $researchPath
            if($researchResponse.Content -is [byte[]]){[IO.File]::WriteAllBytes($researchLocal,$researchResponse.Content)}else{[IO.File]::WriteAllText($researchLocal,$researchResponse.Content,[Text.UTF8Encoding]::new($false))}
            $researchRecord.files+=@{path=$researchPath;url=$researchUrl;sha256=(Get-FileHash -LiteralPath $researchLocal -Algorithm SHA256).Hash}
        }catch{$researchRecord.errors+=($researchPath+': '+$_.Exception.Message)}
    }
    $researchRecord | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $researchFolder 'metadata.json') -Encoding utf8
    [pscustomobject]$researchRecord
} -ThrottleLimit 4
$researchRecords | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path (Join-Path $researchRoot 'branch_sources') 'index.json') -Encoding utf8
$researchRecords | ForEach-Object {[pscustomobject]@{repo=$_.repo;files=($_.files.path -join ',');errors=$_.errors} | ConvertTo-Json -Depth 3 -Compress}
