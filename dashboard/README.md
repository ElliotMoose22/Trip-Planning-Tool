# Route map dashboard

Source of the "Asia 2027 Route Map" dashboard on claude.ai (a Dashboard artifact). It reads the
"Elliot Flights" table live from the Google Sheet through the Google Sheets connector, places each
flight with `places.json`, fills same-country gaps with bus/train legs and fly-instead options, and
draws everything on a spinnable globe. Kept here for version history; edit it by asking Claude.
