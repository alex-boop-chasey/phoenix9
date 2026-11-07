#!/bin/sh
# docs/api.md lists every new route
cd "$(dirname "$0")/../../.." || exit 1
fails=0
for r in '/api/agent`' '/api/agent/messages' '/api/agent/stream' '/api/agent/send' '/api/agent/sessions'; do
  grep -E '^\| (GET|POST) \| `'"$r" docs/api.md >/dev/null || { echo "docs/api.md Endpoints table lacks row for $r"; fails=1; }
done
grep -E '^\| GET \| `/api/agent/stream' docs/api.md | grep -qi 'session' || { echo "stream row should mention the session event"; fails=1; }
grep -E '^\| POST \| `/api/agent/send' docs/api.md | grep -q '503' || { echo "send row should list 503"; fails=1; }
grep -E '^\| POST \| `/api/agent/send' docs/api.md | grep -q '400' || { echo "send row should list 400"; fails=1; }
exit $fails
