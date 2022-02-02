#!/bin/bash

__DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

export DOCKER_BUILDKIT=1

DOCKER=docker
if [ -x "$(command -v podman)" ]; then
  DOCKER=podman
fi

if [ ! -f "$__DIR/docker/pip.conf" ]; then
  echo docker/pip.conf is missing
  echo You can generate this file with scripts/generate-pip-conf.sh
  exit 1
fi

${DOCKER} build -f docker/Dockerfile -t inuits-dams-transcode-service:dev --target=development-stage $__DIR $@
