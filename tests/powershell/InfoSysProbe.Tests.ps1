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
    It 'classifies a missing Help-ID as absent only from the selected scope' {
        $p = Join-Path $TestDrive 'missing-link.mshc'
        New-Fixture $p
        $r = Invoke-InfoSysProbe -ArchivePath $p -IncludeContent
        $r.matches[0].links[0].resolution.status | Should -Be 'not-found-in-scope'
        $r.matches[0].links[0].resolution.targets.Count | Should -Be 0
        $r.resolutionScope | Should -Be 'tcplclib_tc2_mc2/1033/'
        $r.matches[0].linkResolution.'not-found-in-scope' | Should -Be 1
    }
    It 'reports duplicate Help-IDs as ambiguous without selecting a winner' {
        $p = Join-Path $TestDrive 'ambiguous.mshc'
        New-Fixture $p
        $z = [IO.Compression.ZipFile]::Open($p, [IO.Compression.ZipArchiveMode]::Update)
        try {
            foreach ($name in @('902', '901')) {
                $w = [IO.StreamWriter]::new($z.CreateEntry("tcplclib_tc2_mc2/1033/$name.html").Open())
                try { $w.Write('<html><head><title>Duplicate</title><meta name="Microsoft.Help.Id" content="synthetic-target" /><meta name="Microsoft.Help.Id" content="synthetic-target" /></head><body><article>Original synthetic content</article></body></html>') } finally { $w.Dispose() }
            }
        } finally { $z.Dispose() }
        $r = Invoke-InfoSysProbe -ArchivePath $p -IncludeContent
        $r.matches[0].links[0].resolution.status | Should -Be 'ambiguous'
        $r.matches[0].links[0].resolution.targets.Count | Should -Be 2
        $r.matches[0].links[0].resolution.targets[0].entry | Should -Be 'tcplclib_tc2_mc2/1033/901.html'
        $r.matches[0].linkResolution.ambiguous | Should -Be 1
    }
    It 'classifies link syntax safely: <Href>' -TestCases @(
        @{ Href = 'https://example.invalid/topic'; Expected = 'external' }
        @{ Href = 'file:///C:/not-to-open'; Expected = 'unsupported' }
        @{ Href = 'javascript:throw(1)'; Expected = 'unsupported' }
        @{ Href = 'ms-xhelp:///?Id='; Expected = 'invalid' }
        @{ Href = 'ms-xhelp:///?Id=bad%ZZ'; Expected = 'invalid' }
        @{ Href = 'ms-xhelp:///?Id=bad%0Aid'; Expected = 'invalid' }
        @{ Href = 'ms-xhelp:///?Id=one&Id=two'; Expected = 'unsupported' }
        @{ Href = 'ms-xhelp:///?Id=one#anchor'; Expected = 'unsupported' }
    ) {
        param($Href, $Expected)
        (Resolve-InfoSysLink -Href $Href -Index @{}).status | Should -Be $Expected
    }
    It 'decodes the Help-ID once and matches it case-insensitively' {
        $index = @{ 'synthetic-target' = @([pscustomobject]@{ entry = 'one.html'; title = 'Target' }) }
        $r = Resolve-InfoSysLink -Href 'ms-xhelp:///?Id=SYNTHETIC%2Dtarget' -Index $index
        $r.status | Should -Be 'resolved'
        $r.helpId | Should -BeExactly 'SYNTHETIC-target'
        (Resolve-InfoSysLink -Href 'ms-xhelp:///?Id=synthetic%252Dtarget' -Index $index).status | Should -Be 'not-found-in-scope'
    }
    It 'does not resolve identical IDs from another library or language' {
        $p = Join-Path $TestDrive 'scope.mshc'
        New-Fixture $p
        $z = [IO.Compression.ZipFile]::Open($p, [IO.Compression.ZipArchiveMode]::Update)
        try {
            foreach ($entry in @('other_library/1033/999.html', 'tcplclib_tc2_mc2/1031/999.html')) {
                $w = [IO.StreamWriter]::new($z.CreateEntry($entry).Open())
                try { $w.Write('<html><head><title>Outside scope</title><meta name="Microsoft.Help.Id" content="synthetic-target" /></head><body><article>Other</article></body></html>') } finally { $w.Dispose() }
            }
        } finally { $z.Dispose() }
        $r = Invoke-InfoSysProbe -ArchivePath $p
        $r.scannedArticles | Should -Be 1
        $r.matches[0].linkResolution.'not-found-in-scope' | Should -Be 1
        $total = ($r.matches[0].linkResolution.PSObject.Properties.Value | Measure-Object -Sum).Sum
        $total | Should -Be $r.matches[0].linkCount
        $r.matches[0].PSObject.Properties.Name | Should -Not -Contain 'links'
    }
    It 'resolves a forward Help-ID reference through the complete scoped scan' {
        $p = Join-Path $TestDrive 'forward-link.mshc'
        New-Fixture $p
        $z = [IO.Compression.ZipFile]::Open($p, [IO.Compression.ZipArchiveMode]::Update)
        try {
            $w = [IO.StreamWriter]::new($z.CreateEntry('tcplclib_tc2_mc2/1033/999.html').Open())
            try { $w.Write('<html><head><title>Synthetic target</title><meta name="Microsoft.Help.Id" content="synthetic-target" /></head><body><article>Target body</article></body></html>') } finally { $w.Dispose() }
        } finally { $z.Dispose() }
        $before = (Get-FileHash $p).Hash
        $r = Invoke-InfoSysProbe -ArchivePath $p -IncludeContent | ConvertTo-Json -Depth 20 | ConvertFrom-Json
        $r.matches[0].links[0].resolution.status | Should -Be 'resolved'
        $r.matches[0].links[0].resolution.targets[0].entry | Should -Be 'tcplclib_tc2_mc2/1033/999.html'
        $r.matches[0].links[0].resolution.targets[0].title | Should -Be 'Synthetic target'
        $r.matches[0].linkResolution.resolved | Should -Be 1
        (Get-FileHash $p).Hash | Should -Be $before
    }
    It 'keeps block and cell boundaries without splitting inline words' {
        $p = Join-Path $TestDrive 'structure.mshc'
        New-Fixture $p -Html '<html><head><title>MC_MoveAbsolute</title></head><body><article><h1>Heading</h1><p>First <b>bold</b> paragraph.</p><p>Second paragraph.</p><ul><li>One</li><li>Two</li></ul><table><tr><td>A</td><td><p>B</p><p>C</p></td></tr></table></article></body></html>'
        $r = Invoke-InfoSysProbe -ArchivePath $p -IncludeContent
        $r.matches[0].text | Should -Match "Heading`n+First bold paragraph\.`n+Second paragraph\."
        $r.matches[0].text | Should -Match "One`n+Two"
        $r.matches[0].text | Should -Match "A`t"
        $r.matches[0].tables[0].rows[0].cells[1] | Should -Match "B`n+C"
    }
    It 'retains whitespace-only code nodes and spacing between inline elements' {
        $p = Join-Path $TestDrive 'whitespace.mshc'
        New-Fixture $p -Html "<html><head><title>MC_MoveAbsolute</title></head><body><article><p><b>One</b> <i>two</i></p><pre><span>A</span>`n`n`t<span>B</span></pre></article></body></html>"
        $r = Invoke-InfoSysProbe -ArchivePath $p -IncludeContent
        $r.matches[0].code[0] | Should -BeExactly "A`n`n`tB"
        $r.matches[0].text | Should -Match 'One two'
    }
    It 'preserves br-separated code lines through archive and JSON extraction' {
        $p = Join-Path $TestDrive 'code-breaks.mshc'
        New-Fixture $p -Html '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>MC_MoveAbsolute</title></head><body><article><pre><span>VAR_INPUT</span><br/><span>    Example : BOOL;</span><br/><br/>END_VAR</pre></article></body></html>'
        $r = Invoke-InfoSysProbe -ArchivePath $p -IncludeContent | ConvertTo-Json -Depth 20 | ConvertFrom-Json
        $r.matches[0].code[0] | Should -BeExactly "VAR_INPUT`n    Example : BOOL;`n`nEND_VAR"
    }
    It 'preserves code tokens, NBSP indentation and CRLF without executing markup' {
        $p = Join-Path $TestDrive 'code-tokens.mshc'
        New-Fixture $p -Html "<html><head><title>MC_MoveAbsolute</title></head><body><article><pre><code>&#160;&#160;IF X &lt; 2 THEN`r`n`tY := 'a;b';`r`nEND_IF</code></pre><script>DO_NOT_RUN</script></article></body></html>"
        $r = Invoke-InfoSysProbe -ArchivePath $p -IncludeContent
        $r.matches[0].code.Count | Should -Be 1
        $r.matches[0].code[0] | Should -BeExactly (([string][char]160) * 2 + "IF X < 2 THEN`n`tY := 'a;b';`nEND_IF")
        $r.matches[0].text | Should -Not -Match 'DO_NOT_RUN'
    }
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
