# KAVACH Interactive Map Tester

This ZIP is your project with an interactive browser-based testing frontend added.

## Run it
1. Extract this ZIP. Open the `kavach-agent1` folder in VS Code.
2. Use the same Python environment and `.env` you already configured. If needed, install dependencies: `pip install -r requirements.txt`.
3. From the project root (`kavach-agent1`), run in the VS Code terminal:
   `python -m uvicorn kavach.main:app --reload --app-dir src --env-file .env --log-level debug`
4. Open **http://127.0.0.1:8000/tester/**. Swagger remains at http://127.0.0.1:8000/docs.

## What it tests
- Complaint text and optional voice transcript.
- Incident location pin: click map, drag pin, or search a landmark/address.
- Device GPS separately, with browser permission and reported accuracy.
- Multiple image uploads; the API response includes server-generated EXIF results.
- Structured output including severity, category/type, missing information and location check.

## Notes
- Map tiles are provided by OpenStreetMap; address search uses the public Nominatim service. Internet is needed for map/search. Do not automate or send high-volume geocoding requests.
- GPS permission works on localhost in modern browsers; deployed use should be HTTPS.
- Device GPS is client-provided evidence, not proof. A selected incident pin is kept separate. If no pin is selected, the frontend does not invent one.
- Use original JPEG photos with embedded GPS metadata for EXIF testing. Many screenshots and chat-app images have no EXIF GPS.
- API errors are shown in the status and raw JSON panel. Gemini/key/configuration errors are backend issues, not map UI issues.
