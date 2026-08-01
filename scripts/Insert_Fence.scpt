tell application "BBEdit"
    activate
    set dateStr to do shell script "date '+=== %Y-%m-%d, %I:%M %p ==='"
    set text of selection to dateStr
end tell