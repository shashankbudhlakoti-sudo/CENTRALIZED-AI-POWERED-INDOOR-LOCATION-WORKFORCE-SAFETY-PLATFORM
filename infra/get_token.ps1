# get_token.ps1
# Requests a fresh access token from Keycloak for testuser2 and prints it clearly.

$response = Invoke-RestMethod -Uri "http://localhost:8080/realms/safety-platform/protocol/openid-connect/token" `
    -Method Post `
    -ContentType "application/x-www-form-urlencoded" `
    -Body @{
        client_id     = "safety-platform-api"
        client_secret = "3Tzxuc0PIVy4W4k8qBG0kClJMdIFeLcA"
        grant_type    = "password"
        username      = "testuser2"
        password      = "Test@1234"
    }

Write-Host "`n--- ACCESS TOKEN (copy everything below) ---`n"
Write-Host $response.access_token
Write-Host "`n--- END ---`n"

# Save it to a file too, so call_api.ps1 can read it automatically
$response.access_token | Out-File -FilePath "token.txt" -NoNewline
Write-Host "Token also saved to token.txt"