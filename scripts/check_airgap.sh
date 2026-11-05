#!/usr/bin/env bash
# Run an `agnostic` image on a Docker network with no route out and check the product works: migrations, bootstrap,
# the API and a worker, sign-in, the web app and the bundled guides, with no attempt to reach an outside host.
#
#   bash scripts/check_airgap.sh [IMAGE]       # default: agnostic:<version in backend/apps/agnostic-server/pyproject.toml>
#
# Everything it starts is named agnostic-airgap-* and removed on exit. Needs docker and openssl.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
version="$(sed -n 's/^version = "\(.*\)"$/\1/p' "${root}/backend/apps/agnostic-server/pyproject.toml" | head -n1)"
image="${1:-agnostic:${version}}"
net=agnostic-airgap
postgres_image=pgvector/pgvector:0.8.7-pg18-trixie@sha256:5895949dfcdf308eb0cd31c950c93c14895c77f33fbedfecf1fa511ab1d4bcd2
redis_image=redis:8.10.3-alpine@sha256:21090af93f8324db2f0f0f4f38a7c60369d47d917e000c3423d89d2ae2883537
curl_image=curlimages/curl:8.17.0@sha256:935d9100e9ba842cdb060de42472c7ca90cfe9a7c96e4dacb55e79e560b3ff40
workdir="$(mktemp -d)"
env_file="${workdir}/airgap.env"

cleanup() {
  docker rm -f "${net}-api" "${net}-worker" "${net}-postgres" "${net}-redis" >/dev/null 2>&1 || true
  docker network rm "${net}" >/dev/null 2>&1 || true
  rm -rf "${workdir}"
}
trap cleanup EXIT
cleanup

docker image inspect "${image}" >/dev/null 2>&1 || { echo "no local image ${image}: build it first (scripts/build_images.sh)" >&2; exit 2; }
# The helper images are pulled while there is still a route out; the network below has none.
for helper in "${postgres_image}" "${redis_image}" "${curl_image}"; do
  docker image inspect "${helper}" >/dev/null 2>&1 || docker pull --quiet "${helper}" >/dev/null
done

echo "==> ${image} on an internal network (no route out)"
docker network create --internal "${net}" >/dev/null
docker run -d --name "${net}-postgres" --network "${net}" --network-alias postgres -e POSTGRES_USER=agnostic \
  -e POSTGRES_PASSWORD=agnostic -e POSTGRES_DB=agnostic "${postgres_image}" >/dev/null
docker run -d --name "${net}-redis" --network "${net}" --network-alias redis "${redis_image}" >/dev/null
until docker exec "${net}-postgres" pg_isready -U agnostic >/dev/null 2>&1; do sleep 1; done

cat >"${env_file}" <<'ENV'
AGNOSTIC_ENV=production
AGNOSTIC_HTTP__PUBLIC_URL=http://api:8000
AGNOSTIC_DATABASE__URL=postgresql://agnostic:agnostic@postgres:5432/agnostic
AGNOSTIC_DATABASE__SSLMODE=disable
AGNOSTIC_REDIS__URL=redis://redis:6379/0
ENV
# A throwaway key for this run's database only, made fresh every time.
echo "AGNOSTIC_SECRETS__MASTER_KEY=$(openssl rand -base64 32)" >>"${env_file}"

run() { docker run --rm -i --network "${net}" --env-file "${env_file}" --read-only --tmpfs /tmp "${image}" "$@"; }
probe() { docker run --rm --network "${net}" "${curl_image}" "$@"; }

run migrate >/dev/null
printf '%s\n' "airgap-owner-password" | run bootstrap --org-name "Air gap" --owner-email owner@airgap.test \
  --owner-name "Owner" --password-stdin >/dev/null
docker run -d --name "${net}-api" --network "${net}" --network-alias api --env-file "${env_file}" --read-only \
  --tmpfs /tmp "${image}" api >/dev/null
docker run -d --name "${net}-worker" --network "${net}" --env-file "${env_file}" --read-only --tmpfs /tmp \
  "${image}" worker >/dev/null

ready=false
for _ in $(seq 60); do
  if probe -fsS http://api:8000/readyz >/dev/null 2>&1; then ready=true; break; fi
  sleep 2
done
${ready} || { docker logs "${net}-api" >&2; echo "the API never became ready" >&2; exit 1; }

probe -fsS http://api:8000/ | grep -q '<div id="root">'
echo "    ok: the web app is served"
probe -fsS -c /tmp/jar -H 'Content-Type: application/json' \
  -d '{"email":"owner@airgap.test","password":"airgap-owner-password"}' http://api:8000/api/v1/auth/login >/dev/null
echo "    ok: the Owner signs in"
probe -fsS http://api:8000/api/v1/system/docs | grep -q '"available":true'
echo "    ok: the bundled guides are available"
run config check --connect >/dev/null
echo "    ok: config check --connect passes"

if docker logs "${net}-api" 2>&1 | cat - <(docker logs "${net}-worker" 2>&1) \
  | grep -Ei "Temporary failure in name resolution|Network is unreachable|getaddrinfo failed"; then
  echo "a process tried to reach an outside host" >&2; exit 1
fi
echo "    ok: nothing tried to leave the network"
