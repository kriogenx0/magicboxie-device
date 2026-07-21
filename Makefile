IMAGE := magicbox-device

.PHONY: all setup dev build test clean

all: setup dev

# Everything here builds/runs in Docker - no local Python/venv needed.
setup:
	@command -v docker >/dev/null || { echo "docker not found - install Docker Desktop / Engine first"; exit 1; }
	docker build -t $(IMAGE):latest .

# Build for development and run it. `docker compose up --build` recreates the
# container from the freshly built image automatically, so there's nothing to
# manually delete between runs.
dev:
	docker compose up -d --build
	docker compose logs -f

# Production image build.
build:
	docker build -t $(IMAGE):latest .

# Runs the test suite inside the same image the app ships in.
test:
	docker build --target test -t $(IMAGE):test .
	docker run --rm $(IMAGE):test

clean:
	docker compose down --rmi local --volumes --remove-orphans 2>/dev/null || true
	docker image rm -f $(IMAGE):latest $(IMAGE):test 2>/dev/null || true
