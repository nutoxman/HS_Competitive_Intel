.PHONY: fmt lint test run

fmt:
	black .
	ruff check . --fix
	ruff format .

lint:
	ruff check .
	black --check .

test:
	pytest

run:
	streamlit run ui/app.py

