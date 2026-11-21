.PHONY: install test api demo
install:
	cd backend && python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt && cp -n .env.example .env
test:
	cd backend && . .venv/bin/activate && pytest
api:
	cd backend && . .venv/bin/activate && uvicorn app.main:app --reload
demo:
	cd demo && python -m http.server 5173
