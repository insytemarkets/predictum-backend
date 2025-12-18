# PowerShell script to create GitHub repo and push code
# Run this from the backend directory

Write-Host "Creating GitHub repository..." -ForegroundColor Green

# Get GitHub username from git config or prompt
$username = git config --global user.name
if (-not $username) {
    $username = Read-Host "Enter your GitHub username"
}

# Create repo using GitHub API (requires personal access token)
# You can create a token at: https://github.com/settings/tokens
$token = $env:GITHUB_TOKEN
if (-not $token) {
    Write-Host "`nTo create the repo automatically, set GITHUB_TOKEN environment variable" -ForegroundColor Yellow
    Write-Host "Or create the repo manually at: https://github.com/new" -ForegroundColor Yellow
    Write-Host "`nRepository name: predictum-backend" -ForegroundColor Cyan
    Write-Host "Then run these commands:" -ForegroundColor Cyan
    Write-Host "  git remote add origin https://github.com/$username/predictum-backend.git" -ForegroundColor White
    Write-Host "  git branch -M main" -ForegroundColor White
    Write-Host "  git push -u origin main" -ForegroundColor White
    exit
}

# Create repo via API
$repoName = "predictum-backend"
$body = @{
    name = $repoName
    description = "Backend workers for Predictum - Polymarket data collection and analysis"
    private = $true
} | ConvertTo-Json

try {
    $headers = @{
        Authorization = "token $token"
        Accept = "application/vnd.github.v3+json"
    }
    
    $response = Invoke-RestMethod -Uri "https://api.github.com/user/repos" -Method Post -Headers $headers -Body $body -ContentType "application/json"
    
    Write-Host "Repository created successfully!" -ForegroundColor Green
    Write-Host "Repository URL: $($response.html_url)" -ForegroundColor Cyan
    
    # Add remote and push
    git remote add origin $response.clone_url
    git branch -M main
    git push -u origin main
    
    Write-Host "`nCode pushed successfully!" -ForegroundColor Green
} catch {
    Write-Host "Error creating repository: $_" -ForegroundColor Red
    Write-Host "`nPlease create the repo manually at: https://github.com/new" -ForegroundColor Yellow
}

