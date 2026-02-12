.PHONY: help build up down logs clean restart status test k8s-build k8s-deploy k8s-delete k8s-status k8s-logs-collector k8s-logs-manager k8s-logs-simulator k8s-port-forward test-unit test-integration test-e2e test-all

help: ## Show this help message
	@echo 'Usage: make [target]'
	@echo ''
	@echo 'Available targets:'
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  %-15s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

build: ## Build all Docker images
	docker-compose build

up: ## Start all services
	docker-compose up -d
	@echo "Services starting..."
	@echo "Waiting for services to be ready..."
	@sleep 10
	@echo ""
	@echo "Services are up! Access points:"
	@echo "  Device Manager API: http://localhost:8080"
	@echo "  MinIO Console:      http://localhost:9090"
	@echo "  InfluxDB UI:        http://localhost:8086"
	@echo ""
	@echo "Run 'make logs' to view logs"
	@echo "Run 'make status' to check service status"

down: ## Stop all services
	docker-compose down

down-volumes: ## Stop all services and remove volumes
	docker-compose down -v

logs: ## Show logs from all services
	docker-compose logs -f

logs-collector: ## Show logs from MQTT collector
	docker-compose logs -f mqtt-collector

logs-manager: ## Show logs from Device Manager
	docker-compose logs -f device-manager

logs-simulator: ## Show logs from IoT simulator
	docker-compose logs -f iot-simulator

status: ## Show status of all services
	docker-compose ps

restart: ## Restart all services
	docker-compose restart

restart-collector: ## Restart MQTT collector
	docker-compose restart mqtt-collector

restart-manager: ## Restart Device Manager
	docker-compose restart device-manager

restart-simulator: ## Restart IoT simulator
	docker-compose restart iot-simulator

clean: ## Stop services and clean up everything
	docker-compose down -v
	docker system prune -f

test-api: ## Test Device Manager API
	@echo "Testing Device Manager API..."
	@echo ""
	@echo "1. Health check:"
	@curl -s http://localhost:8080/health | python3 -m json.tool || echo "Service not ready"
	@echo ""
	@echo "2. Get all devices:"
	@curl -s http://localhost:8080/api/devices | python3 -m json.tool || echo "Service not ready"
	@echo ""
	@echo "3. Get statistics:"
	@curl -s http://localhost:8080/api/stats | python3 -m json.tool || echo "Service not ready"

test-mqtt: ## Publish a test MQTT message
	docker exec iot-mosquitto mosquitto_pub \
		-t "iot/test-device/telemetry" \
		-m '{"timestamp":"'$$(date -u +"%Y-%m-%dT%H:%M:%SZ")'","device_id":"test-device","temperature":25.5,"humidity":60.0}'
	@echo "Test message published to iot/test-device/telemetry"

subscribe-mqtt: ## Subscribe to MQTT messages
	docker exec -it iot-mosquitto mosquitto_sub -t "iot/+/telemetry"

shell-postgres: ## Open PostgreSQL shell
	docker exec -it iot-postgres psql -U iot_user -d iot_devices

shell-influx: ## Open InfluxDB CLI
	docker exec -it iot-influxdb influx

shell-mosquitto: ## Open Mosquitto shell
	docker exec -it iot-mosquitto sh

backup-db: ## Backup PostgreSQL database
	docker exec iot-postgres pg_dump -U iot_user iot_devices > backup_$$(date +%Y%m%d_%H%M%S).sql
	@echo "Database backed up to backup_$$(date +%Y%m%d_%H%M%S).sql"

dev: ## Start in development mode with logs
	docker-compose up

rebuild: down build up ## Rebuild and restart all services

# ==================== Kubernetes Targets ====================

REGISTRY ?= iot-meter
K8S_NAMESPACE ?= iot-meter

k8s-build: ## Build Docker images for Kubernetes
	docker build -t $(REGISTRY)/device-manager:latest ./services/device-manager
	docker build -t $(REGISTRY)/mqtt-collector:latest ./services/mqtt-collector
	docker build -t $(REGISTRY)/iot-device-simulator:latest ./services/iot-device-simulator

k8s-deploy: ## Deploy all services to Kubernetes
	kubectl apply -k k8s/

k8s-delete: ## Delete all Kubernetes resources
	kubectl delete -k k8s/

k8s-status: ## Show status of Kubernetes pods
	kubectl get pods -n $(K8S_NAMESPACE)
	@echo ""
	kubectl get svc -n $(K8S_NAMESPACE)

k8s-logs-collector: ## Show logs from MQTT collector pod
	kubectl logs -f -l app=mqtt-collector -n $(K8S_NAMESPACE)

k8s-logs-manager: ## Show logs from Device Manager pod
	kubectl logs -f -l app=device-manager -n $(K8S_NAMESPACE)

k8s-logs-simulator: ## Show logs from IoT simulator pod
	kubectl logs -f -l app=iot-simulator -n $(K8S_NAMESPACE)

k8s-port-forward: ## Port-forward Device Manager API to localhost:8080
	kubectl port-forward svc/device-manager 8080:8080 -n $(K8S_NAMESPACE)

# ==================== Test Targets ====================

test-unit: ## Run unit tests (no infrastructure required)
	python -m pytest tests/unit -v --tb=short

test-integration: ## Run integration tests
	python -m pytest tests/integration -v --tb=short

test-e2e: ## Run e2e tests (requires running infrastructure)
	python -m pytest tests/e2e -v --tb=short -m e2e

test-all: ## Run all tests (unit + integration + e2e)
	python -m pytest tests/ -v --tb=short

test-ci: ## Run unit + integration tests (CI-friendly, no infra needed)
	python -m pytest tests/unit tests/integration -v --tb=short --cov=services --cov-report=term-missing
