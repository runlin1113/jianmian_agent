$ErrorActionPreference = 'Stop'
$researchRoot = $PSScriptRoot
$researchRepos = @('langchain-ai/langgraph','pydantic/pydantic-ai','openai/openai-agents-python','agno-agi/agno','langgenius/dify','coze-dev/coze-studio','AmruthPillai/Reactive-Resume','xitanggg/open-resume','srbhr/Resume-Matcher','danielvolchek/ResuLLMe','mozilla/pdf.js','docling-project/docling','microsoft/markitdown','jlifeng/JobPilot','AlanYy-42/JD-Scout','Programmergyt/ai-career-copilot')
$researchRecords = $researchRepos | ForEach-Object -Parallel {
    $researchRepo = $_
    $researchFolder = Join-Path (Join-Path $using:researchRoot 'official') ($researchRepo.Replace('/','__'))
    New-Item -ItemType Directory -Path $researchFolder -Force | Out-Null
    $researchRecord = [ordered]@{repo=$researchRepo;retrieved_at=[DateTimeOffset]::UtcNow.ToString('o');commit=$null;files=@();errors=@()}
    $researchHeaders = @{'User-Agent'='Jianmian-Architecture-Research'}
    try {
        $researchPage = Invoke-WebRequest -Uri ('https://github.com/'+$researchRepo) -Headers $researchHeaders -TimeoutSec 20
        $researchMatch = [regex]::Match($researchPage.Content,'"currentOid":"([a-f0-9]{40})"')
        if ($researchMatch.Success) { $researchRecord.commit = $researchMatch.Groups[1].Value }
    } catch { $researchRecord.errors += ('page: '+$_.Exception.Message) }
    if (-not $researchRecord.commit) {
        $researchOld = Join-Path (Join-Path (Join-Path $using:researchRoot 'upstream') ($researchRepo.Replace('/','__'))) 'metadata.json'
        if (Test-Path -LiteralPath $researchOld) { $researchRecord.commit = (Get-Content -LiteralPath $researchOld -Raw | ConvertFrom-Json).commit }
    }
    $researchRef = if ($researchRecord.commit) { $researchRecord.commit } else { 'HEAD' }
    foreach ($researchCandidates in @(@('README.md','readme.md'),@('LICENSE','LICENSE.md','LICENSE.txt'),@('NOTICE'))) {
        foreach ($researchPath in $researchCandidates) {
            $researchUrl = 'https://raw.githubusercontent.com/'+$researchRepo+'/'+$researchRef+'/'+$researchPath
            try {
                $researchResponse = Invoke-WebRequest -Uri $researchUrl -Headers $researchHeaders -TimeoutSec 20
                $researchTarget = Join-Path $researchFolder $researchPath
                if ($researchResponse.Content -is [byte[]]) { [IO.File]::WriteAllBytes($researchTarget,$researchResponse.Content) } else { [IO.File]::WriteAllText($researchTarget,$researchResponse.Content,[Text.UTF8Encoding]::new($false)) }
                $researchRecord.files += [ordered]@{path=$researchPath;url=$researchUrl;sha256=(Get-FileHash -LiteralPath $researchTarget -Algorithm SHA256).Hash}
                break
            } catch {
                if ($_.Exception.Response.StatusCode.value__ -ne 404) { $researchRecord.errors += ($researchPath+': '+$_.Exception.Message) }
            }
        }
    }
    $researchRecord | ConvertTo-Json -Depth 7 | Set-Content -LiteralPath (Join-Path $researchFolder 'metadata.json') -Encoding utf8
    [pscustomobject]$researchRecord
} -ThrottleLimit 4
$researchRecords | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path (Join-Path $researchRoot 'official') 'index.json') -Encoding utf8
$researchRecords | ForEach-Object { [pscustomobject]@{repo=$_.repo;commit=$_.commit;files=($_.files.path -join ',');errors=$_.errors} | ConvertTo-Json -Depth 3 -Compress }
