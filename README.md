# Affordmed FastAPI Backend

## Run locally

1. Create and activate a virtual environment.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Start the server:
   ```bash
   uvicorn app.main:app --reload
   ```

## Available endpoints

- GET `/` - welcome message
- GET `/health` - health check
- GET `/items` - list sample items
- POST `/items` - create an item
