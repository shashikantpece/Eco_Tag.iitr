EcoTag IITR v4
Run:      pip install -r requirements.txt   then   python app.py   -> http://localhost:5000
Admin:    default password admin123  (set ADMIN_PASSWORD and SECRET_KEY environment variables before deploying)
Existing data: copy your old ecotag.db next to app.py; it upgrades itself and keeps your entries.
QR codes: open the site on your laptop's local IP (or set BASE_URL) so phones can reach it.
Logo / banner: static/iitr-logo.png and static/thomason.png (any of .jpg/.jpeg/.png/.webp named thomason.*)
Plant catalog: species_data.json (303 plants from the IIT Roorkee biodiversity report; locations marked "approximate" are estimates)

Species QR signs: Admin > Plant catalog > 'Print QR signs for all species' (/print/species). Scanning opens the plant's catalog page.
