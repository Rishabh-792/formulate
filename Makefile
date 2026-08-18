.PHONY: install dev demo test lint api ui docker

install:
	pip install -r requirements.txt

dev:
	pip install -r requirements-dev.txt

demo:
	python -m formulate.pipeline formulate/examples/production_planning.spec.json

test:
	pytest -q

lint:
	ruff check .

api:
	uvicorn api.main:app --reload

ui:
	streamlit run ui/app.py

docker:
	docker compose up --build
