param([Parameter(Mandatory=$true)][string]$Path)
$ErrorActionPreference = 'Stop'

$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($Path, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }

# 1. The two ACL reads must exist exactly once as executable assignments.
$requirements = @(
    @{ Name = 'baseAcl'; Path = 'Base'; Label = 'Base' },
    @{ Name = 'workAcl'; Path = 'Work'; Label = 'Work' }
)
foreach ($req in $requirements) {
    $assignments = @($ast.FindAll({ param($node)
        $node -is [System.Management.Automation.Language.AssignmentStatementAst] -and
        $node.Left -is [System.Management.Automation.Language.VariableExpressionAst] -and
        $node.Left.VariablePath.UserPath -eq $req.Name
    }, $true))
    if ($assignments.Count -ne 1) {
        throw "Missing or duplicate executable assignment: $($req.Name)"
    }
    $assignment = $assignments[0]
    $commands = @($assignment.Right.FindAll({ param($node)
        $node -is [System.Management.Automation.Language.CommandAst] -and
        $node.GetCommandName() -eq 'Get-AclForPath'
    }, $true))
    if ($commands.Count -ne 1) {
        throw "Missing Get-AclForPath for $($req.Name)"
    }
    $expected = "Get-AclForPath -Path `$$($req.Path) -Label '$($req.Label)'"
    if ($commands[0].Extent.Text -cne $expected) {
        throw "Wrong ACL target or arguments for $($req.Name): $($commands[0].Extent.Text)"
    }

    $addRule = @($ast.FindAll({ param($node)
        $node -is [System.Management.Automation.Language.InvokeMemberExpressionAst] -and
        $node.Expression -is [System.Management.Automation.Language.VariableExpressionAst] -and
        $node.Expression.VariablePath.UserPath -eq $req.Name -and
        $node.Member.Value -eq 'AddAccessRule'
    }, $true))
    if ($addRule.Count -ne 1) {
        throw "Missing AddAccessRule for $($req.Name)"
    }
    if ($assignment.Extent.StartOffset -ge $addRule[0].Extent.StartOffset) {
        throw "ACL assignment must precede AddAccessRule: $($req.Name)"
    }

    $setAcl = @($ast.FindAll({ param($node)
        $node -is [System.Management.Automation.Language.CommandAst] -and
        $node.GetCommandName() -eq 'Set-Acl' -and
        $node.Extent.Text -match ('-AclObject \$' + $req.Name + '\b')
    }, $true))
    if ($setAcl.Count -ne 1) {
        throw "Missing Set-Acl -AclObject `$$($req.Name)"
    }
}

# 2. The helper must fail closed: terminating read plus an explicit throw.
$helpers = @($ast.FindAll({ param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
    $node.Name -eq 'Get-AclForPath'
}, $true))
if ($helpers.Count -ne 1) { throw 'Missing or duplicate function: Get-AclForPath' }
$body = $helpers[0].Body.Extent.Text
if ($body -notmatch 'Get-Acl -LiteralPath \$Path -ErrorAction Stop') {
    throw 'Get-AclForPath must call Get-Acl with -ErrorAction Stop'
}
if ($body -notmatch 'throw "Unable to read') {
    throw 'Get-AclForPath must throw an explicit exception on failure'
}
if ($body -notmatch 'if \(\$null -eq \$acl\) \{ throw ') {
    throw 'Get-AclForPath must reject a null ACL'
}

# 3. No comment may contain executable-looking code (the reported regression).
foreach ($token in $tokens) {
    if ($token.Kind -ne 'Comment') { continue }
    if ($token.Text -match '\$\w+\s*=' -or
        $token.Text -match '\b(Get-Acl|Get-AclForPath|Set-Acl|AddAccessRule|New-LocalUser|Remove-LocalUser|Start-Process)\b') {
        throw "Comment contains executable-looking code at line $($token.Extent.StartLineNumber): $($token.Text)"
    }
}

# 5. The failure path must clean up the temporary account and empty directories.
$accountCleanup = $false
foreach ($try in @($ast.FindAll({ param($node)
    $node -is [System.Management.Automation.Language.TryStatementAst]
}, $true))) {
    foreach ($catch in $try.CatchClauses) {
        $calls = @($catch.Body.FindAll({ param($node)
            $node -is [System.Management.Automation.Language.CommandAst] -and
            $node.GetCommandName() -eq 'Remove-LocalUser'
        }, $true))
        if ($calls.Count -ge 1) { $accountCleanup = $true }
    }
}
if (-not $accountCleanup) { throw 'Catch block must call Remove-LocalUser' }

$emptyDirCalls = @($ast.FindAll({ param($node)
    $node -is [System.Management.Automation.Language.CommandAst] -and
    $node.GetCommandName() -eq 'Remove-EmptyDirectory'
}, $true))
if ($emptyDirCalls.Count -lt 3) {
    throw "Failure path must clean empty experiment directories (found $($emptyDirCalls.Count))"
}

# 6. Every executable assignment must be reachable, not hidden in a string.
$assignments = @($ast.FindAll({ param($node)
    $node -is [System.Management.Automation.Language.AssignmentStatementAst]
}, $true))
foreach ($name in @('baseAcl', 'workAcl')) {
    $found = @($assignments | Where-Object {
        $_.Left -is [System.Management.Automation.Language.VariableExpressionAst] -and
        $_.Left.VariablePath.UserPath -eq $name
    })
    if ($found.Count -ne 1) { throw "Executable assignment count is not 1: $name" }
}

Write-Output 'ACL_AST_OK'
