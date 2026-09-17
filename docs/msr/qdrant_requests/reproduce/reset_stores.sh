#!/usr/bin/env bash
# 계측용 저장소(Qdrant, PostgreSQL)를 비운 상태로 다시 띄운다.
#
# 계측 A(trace_qdrant_requests.py)는 빈 저장소를 전제로 한다.
# 세션을 처음 만들 때의 요청 수를 재기 때문이다.
# 두 번째 측정부터는 이 스크립트를 먼저 실행한다.
#
# 사용법: bash reset_stores.sh

set -euo pipefail

QDRANT_IMAGE="qdrant/qdrant:v1.17.0"
PG_IMAGE="postgres:16-alpine"
QDRANT_PORT=16333
QDRANT_GRPC_PORT=16334
PG_PORT=15432

echo "1) 기존 컨테이너 제거"
docker rm -f mm-qdrant mm-pg >/dev/null 2>&1 || true

echo "2) Qdrant 기동 (포트 ${QDRANT_PORT})"
docker run -d --rm --name mm-qdrant \
  -p "${QDRANT_PORT}:6333" -p "${QDRANT_GRPC_PORT}:6334" \
  "${QDRANT_IMAGE}" >/dev/null

echo "3) PostgreSQL 기동 (포트 ${PG_PORT})"
docker run -d --rm --name mm-pg \
  -p "${PG_PORT}:5432" -e POSTGRES_PASSWORD=mmtest \
  "${PG_IMAGE}" >/dev/null

echo "4) 준비될 때까지 대기"
for i in $(seq 1 60); do
  if curl -fsS "localhost:${QDRANT_PORT}/" >/dev/null 2>&1 \
     && docker exec mm-pg pg_isready -U postgres >/dev/null 2>&1; then
    echo "   준비 완료 (${i}초)"
    break
  fi
  if [ "$i" -eq 60 ]; then
    echo "   오류: 60초 안에 준비되지 않았다. 'docker ps' 와 'docker logs mm-qdrant' 를 확인한다." >&2
    exit 1
  fi
  sleep 1
done

echo "5) 빈 상태 확인"
COLLECTIONS=$(curl -fsS "localhost:${QDRANT_PORT}/collections")
echo "   ${COLLECTIONS}"

if echo "${COLLECTIONS}" | grep -q '"collections":\[\]'; then
  echo
  echo "초기화 완료. 계측 A 부터 실행하면 된다."
else
  echo
  echo "경고: 컬렉션이 남아 있다. 계측 A 의 S1 값이 17 이 아닐 수 있다." >&2
  exit 1
fi
