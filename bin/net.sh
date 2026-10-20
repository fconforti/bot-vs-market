# Sourced by bin/run-session.sh and bin/run-research.sh. This machine is on Wi-Fi
# that drops a few times a day (2026-10-19: DNS failures, a reset Claude API
# connection, a TLS error on push), so wait for the network before starting and
# retry the push. Neither retries anything that touches the broker.

# Wait until the three services a session needs answer over HTTPS, up to $1 seconds.
wait_for_network() {
  local deadline=$(( SECONDS + ${1:-600} ))
  while (( SECONDS < deadline )); do
    if curl -s -o /dev/null --max-time 10 https://api.anthropic.com/ \
       && curl -s -o /dev/null --max-time 10 https://github.com/ \
       && curl -s -o /dev/null --max-time 10 https://secure.scalable.capital/; then
      return 0
    fi
    echo "network not ready, waiting ($(date +%T))"
    sleep 20
  done
  return 1
}

# git push, up to 5 attempts over about 4 minutes.
push_with_retry() {
  local n
  for n in 1 2 3 4 5; do
    git push -q && return 0
    echo "push attempt $n failed"
    (( n < 5 )) && sleep $(( n * 20 ))
  done
  return 1
}
