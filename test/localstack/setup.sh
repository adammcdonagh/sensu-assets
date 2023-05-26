#!/bin/bash

export AWS_ACCESS_KEY_ID=local
export AWS_SECRET_ACCESS_KEY=local
export AWS_DEFAULT_REGION=eu-west-2
export NO_PROXY=$NO_PROXY,localhost
export no_proxy=$NO_PROXY,localhost

export ENDPOINT_URL="--endpoint-url=http://localhost:4566"

##  Setup DynamoDB
export DYNAMO_TABLE="sensu-alerts"
# Check if table already exists
aws ${ENDPOINT_URL} dynamodb describe-table --table-name ${DYNAMO_TABLE} > /dev/null 2>&1
if [ $? -eq 0 ]; then
  echo "Table ${DYNAMO_TABLE} already exists"
else
  echo "Creating table ${DYNAMO_TABLE}"
  aws ${ENDPOINT_URL} dynamodb create-table --table-name ${DYNAMO_TABLE} \
    --attribute-definitions AttributeName=alert_key,AttributeType=S \
    --key-schema AttributeName=alert_key,KeyType=HASH \
    --provisioned-throughput ReadCapacityUnits=5,WriteCapacityUnits=5 >/dev/null
  aws ${ENDPOINT_URL} dynamodb update-time-to-live --table-name ${DYNAMO_TABLE} --time-to-live-specification "Enabled=true, AttributeName=expiration_time"

fi

# Check if SQS queue exists
aws ${ENDPOINT_URL} sqs get-queue-url --queue-name sensu-alerts.fifo > /dev/null 2>&1
if [ $? -eq 0 ]; then
  echo "Queue sensu-alerts.fifo already exists"
else
  # Wriet queue attributes to a temporary JSON file
  cat << EOF > /tmp/queue_attributes.json
{
  "MessageRetentionPeriod": "3600",
  "FifoQueue": "true",
  "ContentBasedDeduplication": "true"
}
EOF

  ## Setup SQS queue
  aws ${ENDPOINT_URL} sqs create-queue --queue-name sensu-alerts.fifo --attributes file:///tmp/queue_attributes.json
fi
