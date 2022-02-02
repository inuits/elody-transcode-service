#!/bin/bash

__DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ -z "${PYPI_HOST}" ]; then
  echo PYPI_HOST is missing
  EXIT=1
fi

if [ -z "${PYPI_PATH}" ]; then
  echo PYPI_PATH is missing
  EXIT=1
fi

if [ -z "${PYPI_USERNAME}" ]; then
  echo PYPI_USERNAME is missing
  EXIT=1
fi

if [ -z "${PYPI_PASSWORD}" ]; then
  echo PYPI_PASSWORD is missing
  EXIT=1
fi

if [ "$EXIT" == 1 ]; then
  exit $EXIT
fi

cat $__DIR/docker/pip.conf.template | envsubst > $__DIR/docker/pip.conf
