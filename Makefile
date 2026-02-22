.PHONY: install train test simulate simulate-standalone docker-up docker-down clean help status logs rebuild
# PdM targets
# Install dependencies
install:
	pip install -r requirements.txt
	pre-commit install

# Train model
train:
	PYTHONPATH=. python3 train_and_save.py

# Run all tests
test:
	PYTHONPATH=. pytest tests/ -v

# Run smoke test and simulation (engine runs as subprocess; stop simulation to stop engine).
# If Docker stack is up, pump_monitor container also writes to logs; use 'make docker-down' to stop it.
simulate:
	PYTHONPATH=. python3 tests/test_smoke.py
	PYTHONPATH=. python3 simulate_failure.py

# Stop Docker monitor (if running) so only simulation-driven engine writes logs; then run simulation.
# Keeps mosquitto running so simulation can publish.
simulate-standalone:
	-docker stop pump_monitor_service 2>/dev/null || true
	$(MAKE) simulate

# Run full stack in Docker
docker-up:
	docker compose up -d

docker-down:
	docker compose down

# Clean temporary files
clean:
	rm -rf .pytest_cache
	find . -type d -name "__pycache__" -exec rm -rf {} +
	rm -f models/*.joblib

# Check container health status
status:
	@docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

# View last 50 log lines
logs:
	@docker logs --tail 50 -f pump_monitor_service

# Full cycle: clean, build and run
rebuild:
	docker compose down --remove-orphans
	$(MAKE) clean
	docker compose up --build -d
	docker image prune -f

# Help
help:
	@echo "Available commands:"
	@echo "  make train       - Train model"
	@echo "  make test       - Run tests"
	@echo "  make simulate   - Run smoke test and failure simulation"
	@echo "  make docker-up  - Start stack in Docker"
	@echo "  make docker-down - Stop Docker containers"
	@echo "  make clean      - Remove cache and trained models"
	@echo "  make rebuild    - Full clean, rebuild and run Docker"
	@echo "  make status     - Check container status"
	@echo "  make logs       - View service logs"
