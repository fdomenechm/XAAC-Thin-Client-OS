SHELL := /usr/bin/env bash
.DEFAULT_GOAL := help

.PHONY: help venv install test coverage lint build clean all

help:
	@printf '%s\n' \
	  'XAAC Thin Client OS — ordres disponibles:' \
	  '  make venv      Crea .venv i instal·la dependències de desenvolupament' \
	  '  make install   Actualitza les dependències dins de .venv' \
	  '  make test      Executa pytest' \
	  '  make coverage  Executa tests i genera cobertura HTML' \
	  '  make lint      Executa Ruff i mypy' \
	  '  make build     Valida l’entorn i compila els mòduls Python' \
	  '  make clean     Elimina artefactes temporals' \
	  '  make all       Executa lint, test, coverage i build'

venv:
	./scripts/create-venv.sh

install:
	./scripts/install-dev.sh

test:
	./scripts/run-tests.sh

coverage:
	./scripts/run-coverage.sh

lint:
	./scripts/run-lint.sh

build:
	./scripts/build.sh

clean:
	./scripts/clean.sh

all: lint test coverage build
