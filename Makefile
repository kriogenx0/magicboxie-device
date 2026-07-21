IMAGE := magicbox-device

.PHONY: all setup dev build clean

all: setup dev

# Local dev environment for running tests/linting outside the container.
# The container itself installs its own dependencies at image-build time.
setup:
	@command -v docker >/dev/null || { echo "docker not found - install Docker Desktop / Engine first"; exit 1; }
	python3 -m venv .venv
	.venv/bin/pip install --quiet --upgrade pip
	.venv/bin/pip install --quiet -e ".[dev]"

# Build for development and run it. `docker compose up --build` recreates the
# container from the freshly built image automatically, so there's nothing to
# manually delete between runs.
dev:
	docker compose up -d --build
	docker compose logs -f

# Production image build.
build:
	docker build -t $(IMAGE):latest .

clean:
	docker compose down --rmi local --volumes --remove-orphans 2>/dev/null || true
	docker image rm -f $(IMAGE):latest 2>/dev/null || true
	rm -rf .venv build *.egg-info **/__pycache__ .pytest_cache
