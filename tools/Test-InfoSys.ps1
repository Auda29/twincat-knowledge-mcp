#requires -Version 5.1
<#!
Read-only, standalone installed-InfoSys diagnostic. No network, extraction to
files, HTML execution, installation or PLC access. JSON goes to stdout only.
Dot-source to load functions for testing. See tools/README.md for limitations.
!#>
[CmdletBinding()]
param(
    [string] $ArchivePath,
    [string] $CatalogRoot,
    [ValidateSet('EN-US', 'DE-DE')] [string] $Locale = 'EN-US',
    [string] $Topic = 'MC_MoveAbsolute',
    [switch] $IncludeContent
)

function Find-InfoSysArchive {
    [CmdletBinding()]
    param([string] $CatalogRoot, [ValidateSet('EN-US', 'DE-DE')] [string] $Locale = 'EN-US')
    $ErrorActionPreference = 'Stop'
    if (-not $CatalogRoot) {
        if ($env:OS -ne 'Windows_NT' -or -not $env:ProgramData) {
            throw 'Automatic discovery requires Windows; specify -ArchivePath or -CatalogRoot.'
        }
        $CatalogRoot = Join-Path $env:ProgramData 'Microsoft/HelpLibrary2/Catalogs'
    }
    if (-not (Test-Path -LiteralPath $CatalogRoot -PathType Container)) {
        throw 'Catalog root not found; specify -ArchivePath or -CatalogRoot.'
    }
    $candidates = @(
        foreach ($catalog in Get-ChildItem -LiteralPath $CatalogRoot -Directory) {
            $dir = Join-Path $catalog.FullName ('ContentStore/' + $Locale)
            if (Test-Path -LiteralPath $dir -PathType Container) {
                Get-ChildItem -LiteralPath $dir -File -Filter ('BKINFOSYS3*_' + $Locale + '*.mshc') |
                    ForEach-Object { $_.FullName }
            }
        }
    )
    if ($candidates.Count -eq 0) { throw 'No matching Beckhoff archive found; specify -ArchivePath.' }
    if ($candidates.Count -ne 1) { throw 'Multiple candidate archives found; specify -ArchivePath explicitly. No revision was selected automatically.' }
    return $candidates[0]
}

function Invoke-InfoSysProbe {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)] [string] $ArchivePath,
        [string] $Topic = 'MC_MoveAbsolute',
        [ValidateSet('EN-US', 'DE-DE')] [string] $Locale = 'EN-US',
        [switch] $IncludeContent
    )
    $ErrorActionPreference = 'Stop'
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [IO.Compression.ZipFile]::OpenRead($ArchivePath)
    try {
        $matches = @()
        $scanned = 0
        $totalBytes = 0L
        $seen = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
        $languageId = if ($Locale -eq 'EN-US') { '1033' } else { '1031' }
        $prefix = 'tcplclib_tc2_mc2/' + $languageId + '/'
        foreach ($entry in $zip.Entries) {
            if (-not $entry.FullName.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase) -or
                -not $entry.FullName.EndsWith('.html', [StringComparison]::OrdinalIgnoreCase)) { continue }
            $scanned++
            if ($entry.FullName -match '[\\:\x00-\x1F%]' -or $entry.FullName -match '(^|/)\.\.?(/|$)' -or
                -not $seen.Add($entry.FullName)) { throw 'Unsafe or duplicate archive entry name.' }
            $totalBytes += $entry.Length
            if ($entry.Length -gt 4MB -or $totalBytes -gt 64MB -or $scanned -gt 1000) {
                throw 'Article size limit or scan budget exceeded.'
            }
            $stream = $entry.Open()
            $settings = [Xml.XmlReaderSettings]::new()
            $settings.DtdProcessing = [Xml.DtdProcessing]::Prohibit
            $settings.XmlResolver = $null
            $settings.MaxCharactersInDocument = 4MB
            $reader = [Xml.XmlReader]::Create($stream, $settings)
            $doc = [Xml.XmlDocument]::new()
            $doc.XmlResolver = $null
            try { $doc.Load($reader) } finally { $reader.Dispose(); $stream.Dispose() }
            $titleNode = $doc.SelectSingleNode('//*[local-name()="title"]')
            if ($null -eq $titleNode -or $titleNode.InnerText.Trim() -ine $Topic) { continue }
            $article = $doc.SelectSingleNode('//*[local-name()="article"]')
            if ($null -eq $article) { throw "Matched topic has no article element: $($entry.FullName)" }
            foreach ($node in @($article.SelectNodes('.//*[local-name()="script" or local-name()="style"]'))) {
                [void] $node.ParentNode.RemoveChild($node)
            }
            $tables = @($article.SelectNodes('.//*[local-name()="table"]') | ForEach-Object {
                @{ rows = @($_.SelectNodes('.//*[local-name()="tr"]') | ForEach-Object {
                    @{ cells = @($_.SelectNodes('./*[local-name()="td" or local-name()="th"]') | ForEach-Object { $_.InnerText }) }
                }) }
            })
            $code = @($article.SelectNodes('.//*[local-name()="pre" or (local-name()="code" and not(ancestor::*[local-name()="pre"]))]') | ForEach-Object { $_.InnerText })
            $links = @($article.SelectNodes('.//*[local-name()="a"][@href]') | ForEach-Object {
                @{ href = $_.GetAttribute('href'); text = $_.InnerText }
            })
            $metadata = @($doc.SelectNodes('//*[local-name()="head"]/*[local-name()="meta"][@name]') | ForEach-Object {
                @{ name = $_.GetAttribute('name'); value = $_.GetAttribute('content') }
            })
            $match = [ordered]@{
                entry = $entry.FullName; title = $titleNode.InnerText.Trim()
                tableCount = $tables.Count; codeBlockCount = $code.Count; linkCount = $links.Count
            }
            if ($IncludeContent) {
                $match.metadata = $metadata; $match.text = $article.InnerText
                $match.tables = $tables; $match.code = $code; $match.links = $links
            }
            $matches += [pscustomobject] $match
        }
        [pscustomobject]@{
            schemaVersion = 'infosys-probe-1'
            status = $(if ($matches.Count) { 'matched' } else { 'not-found' })
            archive = [IO.Path]::GetFileName($ArchivePath)
            library = 'Tc2_MC2'; locale = $Locale; requestedTitle = $Topic
            scannedArticles = $scanned; includesContent = [bool] $IncludeContent
            matches = @($matches)
            limitations = @('Diagnostic only; not an import acceptance.', 'Links are recorded, not resolved.', 'Metadata does not prove TwinCAT build compatibility.')
        }
    } finally { $zip.Dispose() }
}

if ($MyInvocation.InvocationName -ne '.') {
    $ErrorActionPreference = 'Stop'
    try {
        if (-not $ArchivePath) { $ArchivePath = Find-InfoSysArchive -CatalogRoot $CatalogRoot -Locale $Locale }
        $result = Invoke-InfoSysProbe -ArchivePath $ArchivePath -Topic $Topic -Locale $Locale -IncludeContent:$IncludeContent
        $result | ConvertTo-Json -Depth 20
        if ($result.status -ne 'matched') { exit 2 }
    } catch {
        [Console]::Error.WriteLine('InfoSys probe failed: ' + $_.Exception.Message)
        exit 1
    }
}
