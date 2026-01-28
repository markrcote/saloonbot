#!/bin/bash
# Run end-to-end tests for saloonbot server
set -e

echo "Running end-to-end tests..."
echo "This will start Redis and MySQL via docker-compose and test the server."
echo ""

# Change to the directory containing this script
cd "$(dirname "$0")"

# Run the tests
python test_e2e.py "$@"
