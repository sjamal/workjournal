# 
# brew install powershell
# pwsh
#
# Install-Module -Name Microsoft.Graph
# Connect-MgGraph -Scopes Mail.Read
#

Connect-MgGraph -Scopes Mail.Read

$start = Get-Date "2026-07-01"
$end   = Get-Date "2026-08-01"

Get-MgUserMessage `
  -UserId me `
  -All `
  -Property Subject,ReceivedDateTime,ConversationId,Categories `
  -Filter "receivedDateTime ge $($start.ToString('o')) and receivedDateTime lt $($end.ToString('o'))"
  