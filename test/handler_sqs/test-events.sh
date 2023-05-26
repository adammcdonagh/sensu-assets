#!/bin/bash -x
# Reset
Color_Off='\033[0m'       # Text Reset

# Regular Colors
Black='\033[0;30m'        # Black
Red='\033[0;31m'          # Red
Green='\033[0;32m'        # Green
Yellow='\033[0;33m'       # Yellow
Blue='\033[0;34m'         # Blue
Purple='\033[0;35m'       # Purple
Cyan='\033[0;36m'         # Cyan
White='\033[0;37m'        # White

export PYTHONPATH=../../src/python/sensu_plugin/lib
export AWS_ENDPOINT_URL=http://localhost:4566
export AWS_ACCESS_KEY_ID=local
export AWS_SECRET_ACCESS_KEY=local
export AWS_DEFAULT_REGION=eu-west-2
export SENSU_ASSET_LOG_FILE_PATH=/tmp/sqs.log
export SQS_QUEUE=sensu-alerts.fifo
export DYNAMODB_TABLE=sensu-alerts

export SCRIPT=../../src/python/handler_sqs/handler_sqs.py

# Purge the queue first
echo -e "${Yellow}Purging the SQS queue${Color_Off}"
aws sqs purge-queue --queue-url ${AWS_ENDPOINT_URL}/000000000000/${SQS_QUEUE}

# Send an good event to the SQS handler
echo -e "${Green}Sending OK event to the SQS handler${Color_Off}"
python ${SCRIPT} -v < test-event-ok.json

# Major alert
echo -e "${Yellow}Sending major alert to the SQS handler${Color_Off}"
python ${SCRIPT} -v < test-event-major.json

sleep 10

# Critical alert
echo -e "${Red}Upping to critical alert${Color_Off}"
python ${SCRIPT} -v < test-event-crit.json

sleep 10

# Back to Major
echo -e "${Yellow}Setting back to major${Color_Off}"
python ${SCRIPT} -v < test-event-major.json

sleep 10

# Clear
echo -e "${Green}Sending OK event to the SQS handler${Color_Off}"
python ${SCRIPT} -v < test-event-ok.json
