#!/bin/bash
DOCKER=docker
if [ -x "$(command -v podman)" ]; then
  DOCKER=podman
fi

${DOCKER} run -it --rm -p 8005:8005 --env APP_ENV=production inuits-dams-transcode-service:latest $@
