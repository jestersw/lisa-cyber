.PHONY: up down logs test lint fmt

up:        ## start the full stack
	docker compose up --build

down:      ## stop and remove containers
	docker compose down

logs:      ## tail logs
	docker compose logs -f

test:      ## run backend + agent tests
	cd backend && pytest -v
	cd agent && pytest -v

lint:      ## lint everything
	cd backend && ruff check . && mypy app
	cd agent && ruff check .

fmt:       ## auto-format
	cd backend && ruff format .
	cd agent && ruff format .
