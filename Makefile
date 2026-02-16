VENV=.venv
PYTHON=$(VENV)/bin/python
STREAMLIT=$(VENV)/bin/streamlit
PYTEST=$(VENV)/bin/pytest

run:
	$(STREAMLIT) run ui/app.py

test:
	$(PYTEST)


