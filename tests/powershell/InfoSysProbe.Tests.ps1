BeforeAll {
    $script:Tool = Join-Path $PSScriptRoot '../../tools/Test-InfoSys.ps1'
    if (Test-Path $script:Tool) { . $script:Tool }
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    function New-Fixture($Path, $EntryName = 'tcplclib_tc2_mc2/1033/123.html', $Html = '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>MC_MoveAbsolute</title><meta name="Microsoft.Help.Id" content="synthetic-topic" /></head><body><article><h1>MC_MoveAbsolute</h1><pre>VAR_INPUT&#10; Position : LREAL;&#10;END_VAR</pre><table><tr><th>Name</th></tr><tr><td>Position</td></tr></table><a href="ms-xhelp:///?Id=synthetic-target">Target</a><script>DO_NOT_RUN</script></article></body></html>') {
        $z = [IO.Compression.ZipFile]::Open($Path, [IO.Compression.ZipArchiveMode]::Create)
        try {
            $e = $z.CreateEntry($EntryName)
            $w = [IO.StreamWriter]::new($e.Open())
            try { $w.Write($Html) } finally { $w.Dispose() }
        } finally { $z.Dispose() }
    }
}
Describe 'Read-only InfoSys probe' {
    It 'discovers a unique English package without a fixed revision' {
        $root = Join-Path $TestDrive 'Catalogs'
        $dir = Join-Path $root 'VisualStudio15/ContentStore/EN-US'
        New-Item $dir -ItemType Directory -Force | Out-Null
        $p = Join-Path $dir 'BKINFOSYS3_VS_100_EN-US.99.mshc'
        New-Fixture $p
        (Find-InfoSysArchive -CatalogRoot $root -Locale EN-US) | Should -Be $p
        New-Fixture (Join-Path $dir 'BKINFOSYS3_VS_100_EN-US.100.mshc')
        { Find-InfoSysArchive -CatalogRoot $root -Locale EN-US } | Should -Throw '*Multiple*'
    }
    It 'omits article body and metadata by default' {
        $p = Join-Path $TestDrive 'private.mshc'
        New-Fixture $p
        $json = Invoke-InfoSysProbe -ArchivePath $p | ConvertTo-Json -Depth 20
        $json | Should -Not -Match 'VAR_INPUT|synthetic-topic|synthetic-target|Position'
    }
    It 'reports no match instead of claiming success for a reference-only article' {
        $p = Join-Path $TestDrive 'reference.mshc'
        New-Fixture $p -Html '<html><head><title>Other</title></head><body><article>MC_MoveAbsolute</article></body></html>'
        (Invoke-InfoSysProbe -ArchivePath $p).status | Should -Be 'not-found'
    }
    It 'rejects traversal entry names' {
        $p = Join-Path $TestDrive 'traversal.mshc'
        New-Fixture $p -EntryName 'tcplclib_tc2_mc2/1033/../123.html'
        { Invoke-InfoSysProbe -ArchivePath $p } | Should -Throw '*Unsafe*'
    }
    It 'rejects oversized articles before XML parsing' {
        $p = Join-Path $TestDrive 'oversized.mshc'
        New-Fixture $p -Html ('x' * (4MB + 1))
        { Invoke-InfoSysProbe -ArchivePath $p } | Should -Throw '*size limit*'
    }
    It 'prohibits external entities and DTD processing' {
        $p = Join-Path $TestDrive 'dtd.mshc'
        New-Fixture $p -Html '<!DOCTYPE html [<!ENTITY ext SYSTEM "file:///not-to-be-read">]><html>&ext;</html>'
        { Invoke-InfoSysProbe -ArchivePath $p } | Should -Throw '*DTD*'
    }
    It 'rejects a non-archive' {
        $p = Join-Path $TestDrive 'bad.mshc'
        [IO.File]::WriteAllText($p, 'not a zip')
        { Invoke-InfoSysProbe -ArchivePath $p } | Should -Throw
    }
    It 'runs the standalone CLI and returns JSON and meaningful exit codes' {
        $p = Join-Path $TestDrive 'cli.mshc'
        New-Fixture $p
        $exe = (Get-Process -Id $PID).Path
        $json = & $exe -NoProfile -File $script:Tool -ArchivePath $p
        $LASTEXITCODE | Should -Be 0
        ($json | ConvertFrom-Json).status | Should -Be 'matched'
        $json = & $exe -NoProfile -File $script:Tool -ArchivePath $p -Topic Missing
        $LASTEXITCODE | Should -Be 2
        ($json | ConvertFrom-Json).status | Should -Be 'not-found'
    }
    It 'parses as PowerShell without syntax errors' {
        $tokens = $null; $errors = $null
        [void][Management.Automation.Language.Parser]::ParseFile($script:Tool, [ref]$tokens, [ref]$errors)
        $errors | Should -BeNullOrEmpty
    }
    It 'extracts a synthetic article structure without changing the archive' {
        $p = Join-Path $TestDrive 'synthetic.mshc'
        New-Fixture $p
        $before = (Get-FileHash $p).Hash
        $r = Invoke-InfoSysProbe -ArchivePath $p -IncludeContent
        $r.status | Should -Be 'matched'
        $r.matches.Count | Should -Be 1
        $r.matches[0].title | Should -Be 'MC_MoveAbsolute'
        $r.matches[0].tables[0].rows[1].cells[0] | Should -Be 'Position'
        $r.matches[0].code[0] | Should -Match 'VAR_INPUT'
        $r.matches[0].links[0].href | Should -Be 'ms-xhelp:///?Id=synthetic-target'
        $r.matches[0].text | Should -Not -Match 'DO_NOT_RUN'
        (Get-FileHash $p).Hash | Should -Be $before
    }
}
