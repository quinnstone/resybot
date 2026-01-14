#!/bin/bash
#
# Rate Limit Test Runner
# Self-contained script deployed to each EC2 instance
# Outputs JSON logs to stdout for CloudWatch collection
#

set -e

# Configuration (can be overridden via environment variables)
VENUE_ID="${VENUE_ID:-2492}"
TEST_DATE="${TEST_DATE:-2026-02-15}"
PARTY_SIZE="${PARTY_SIZE:-2}"
INTERVAL="${INTERVAL:-1}"
MAX_REQUESTS="${MAX_REQUESTS:-100}"
API_KEY="VbWk7s3L4KiK5fzlO7JD3Q5EYolJI7n5"

# Get instance metadata
INSTANCE_ID=$(curl -s http://169.254.169.254/latest/meta-data/instance-id 2>/dev/null || echo "unknown")
PUBLIC_IP=$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || echo "unknown")

# Log function - outputs JSON
log_json() {
    local request_num=$1
    local status=$2
    local latency_ms=$3
    local blocked=$4
    local timestamp=$(date -u +"%Y-%m-%dT%H:%M:%S.%3NZ")
    
    echo "{\"instance_id\":\"${INSTANCE_ID}\",\"ip\":\"${PUBLIC_IP}\",\"request\":${request_num},\"status\":${status},\"latency_ms\":${latency_ms},\"blocked\":${blocked},\"timestamp\":\"${timestamp}\"}"
}

# Start message
echo "{\"instance_id\":\"${INSTANCE_ID}\",\"ip\":\"${PUBLIC_IP}\",\"event\":\"start\",\"venue_id\":${VENUE_ID},\"interval\":${INTERVAL},\"timestamp\":\"$(date -u +"%Y-%m-%dT%H:%M:%S.%3NZ")\"}"

# Run the test
request_num=0
blocked=false

while [ $request_num -lt $MAX_REQUESTS ] && [ "$blocked" = "false" ]; do
    request_num=$((request_num + 1))
    
    # Time the request
    start_time=$(date +%s%3N)
    
    status=$(curl -s -o /dev/null -w "%{http_code}" \
        "https://api.resy.com/4/find?lat=0&long=0&day=${TEST_DATE}&party_size=${PARTY_SIZE}&venue_id=${VENUE_ID}" \
        -H "Authorization: ResyAPI api_key=\"${API_KEY}\"" \
        --connect-timeout 10 \
        --max-time 15)
    
    end_time=$(date +%s%3N)
    latency_ms=$((end_time - start_time))
    
    # Check if blocked
    if [ "$status" != "200" ]; then
        blocked=true
        log_json $request_num $status $latency_ms "true"
        break
    else
        log_json $request_num $status $latency_ms "false"
    fi
    
    # Sleep for interval (if not the last request)
    if [ $request_num -lt $MAX_REQUESTS ]; then
        sleep $INTERVAL
    fi
done

# Summary message
echo "{\"instance_id\":\"${INSTANCE_ID}\",\"ip\":\"${PUBLIC_IP}\",\"event\":\"complete\",\"total_requests\":${request_num},\"blocked\":${blocked},\"timestamp\":\"$(date -u +"%Y-%m-%dT%H:%M:%S.%3NZ")\"}"
