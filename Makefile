.PHONY: help build up down logs clean restart status test

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
