# call_api.ps1
# Reads the token saved by get_token.ps1 and calls the protected /api/v1/employees endpoint.

$token = Get-Content -Path "token.txt" -Raw

$headers = @{
    Authorization = "Bearer $token"
}

try {
    $result = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/employees" -Headers $headers -Method Get
    Write-Host "`n--- RESPONSE ---`n"
    $result | ConvertTo-Json -Depth 5
} catch {
    Write-Host "`n--- ERROR ---`n"
    Write-Host $_.Exception.Message
    if ($_.ErrorDetails.Message) {
        Write-Host $_.ErrorDetails.Message
    }
}